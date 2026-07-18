"""Context-engine tests: embeddings client, jobs, hybrid search, retrieval,
and chat context injection — real Postgres, fake LLM/embeddings."""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

TEST_DATABASE_URL = os.environ.get("NEXUS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="NEXUS_TEST_DATABASE_URL not set")


def _vector(seed: int) -> list[float]:
    """Deterministic unit-ish vector concentrated on one dimension."""
    vector = [0.001] * 1536
    vector[seed % 1536] = 1.0
    return vector


@pytest.fixture
def db() -> Iterator[Session]:
    assert TEST_DATABASE_URL is not None
    os.environ["NEXUS_DATABASE_URL"] = TEST_DATABASE_URL
    from nexus_api.config import get_settings
    from nexus_api.db.session import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        for table in (
            "message",
            "conversation",
            "memory_note",
            "profile_snapshot",
            "job_run",
            "provider_key",
            "source",
        ):
            conn.execute(text(f"DELETE FROM {table}"))
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


def _add_key(session: Session, provider: str) -> None:
    from nexus_api import crypto
    from nexus_api.db.models import ProviderKey

    session.add(ProviderKey(provider=provider, encrypted_key=crypto.encrypt("sk-test")))
    session.commit()


def _add_conversation(session: Session, title: str, contents: list[tuple[str, str]]):
    from nexus_api.db.models import Conversation, Message, MessageRole, Source, SourceKind

    source = session.scalars(select(Source)).first()
    if source is None:
        source = Source(name="nexus", kind=SourceKind.native, ingest_tier="D")
        session.add(source)
        session.flush()
    conversation = Conversation(source_id=source.id, title=title)
    session.add(conversation)
    session.flush()
    for role, content in contents:
        session.add(
            Message(
                conversation_id=conversation.id,
                role=MessageRole(role),
                content=content,
            )
        )
    session.commit()
    return conversation


# --- embeddings client ---


async def test_embed_texts_batches_and_orders(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexus_api.context import embeddings

    _add_key(db, "openai")
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(len(payload["input"]))
        data = [
            {"index": i, "embedding": _vector(i)}
            for i in reversed(range(len(payload["input"])))  # out of order on purpose
        ]
        return httpx.Response(
            200, json={"data": data, "usage": {"prompt_tokens": 7 * len(payload["input"])}}
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw),
    )
    vectors = await embeddings.embed_texts(db, [f"text {i}" for i in range(70)])
    assert calls == [64, 6]  # batched
    assert len(vectors) == 70
    assert vectors[0][0] == 1.0  # index-sorted despite shuffled response


# --- jobs ---


async def test_embed_job_skips_without_key(db: Session) -> None:
    from nexus_api.db.models import JobStatus
    from nexus_api.jobs.framework import run_job
    from nexus_api.jobs.pipeline import embed_pending

    assert await run_job("embed_messages", embed_pending) == JobStatus.skipped
    run = db.scalars(select(_job_run_model())).one()
    assert run.status == JobStatus.skipped
    assert "no API key" in (run.detail or "")


def _job_run_model():
    from nexus_api.db.models import JobRun

    return JobRun


async def test_summarize_distill_and_profile(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexus_api.context import llm
    from nexus_api.db.models import Conversation, JobStatus, MemoryNote, ProfileSnapshot
    from nexus_api.jobs import pipeline
    from nexus_api.jobs.framework import run_job

    _add_key(db, "anthropic")
    conversation = _add_conversation(
        db,
        "TypeScript question",
        [
            ("user", "I prefer TypeScript for all my frontend work, remember that."),
            ("assistant", "Noted — TypeScript it is. Anything else?"),
        ],
    )

    async def fake_complete(session: Session, prompt: str, *, max_tokens: int = 1024) -> str:
        if "rolling profile" in prompt:
            return "Active projects: Nexus.\nPreferences: TypeScript."
        return json.dumps(
            {
                "summary": "User stated a strong TypeScript preference.",
                "facts": [
                    {"content": "Prefers TypeScript", "category": "preference", "confidence": 0.9}
                ],
            }
        )

    monkeypatch.setattr(llm, "complete", fake_complete)
    monkeypatch.setattr(pipeline, "complete", fake_complete)

    assert await run_job("summarize", pipeline.summarize_pending) == JobStatus.success
    db.expire_all()
    refreshed = db.get(Conversation, conversation.id)
    assert refreshed is not None and refreshed.summary is not None
    assert refreshed.summarized_at is not None
    note = db.scalars(select(MemoryNote)).one()
    assert note.content == "Prefers TypeScript"

    # Re-running does not duplicate facts (dedupe by content).
    refreshed.updated_at = datetime.now(UTC) + timedelta(seconds=5)
    db.commit()
    assert await run_job("summarize", pipeline.summarize_pending) == JobStatus.success
    assert len(db.scalars(select(MemoryNote)).all()) == 1

    # Profile rebuild consumes notes + summaries.
    assert await run_job("rebuild_profile", pipeline.rebuild_profile) == JobStatus.success
    snapshot = db.scalars(select(ProfileSnapshot)).one()
    assert "TypeScript" in snapshot.content

    # Second rebuild with no new activity is skipped.
    assert await run_job("rebuild_profile", pipeline.rebuild_profile) == JobStatus.skipped


# --- hybrid search ---


async def test_keyword_search_without_embeddings(db: Session) -> None:
    from nexus_api.context.search import hybrid_search

    _add_conversation(db, "Postgres tips", [("user", "How do I tune autovacuum in Postgres?")])
    _add_conversation(db, "Cooking", [("user", "Best pasta recipe with garlic")])

    hits = await hybrid_search(db, "autovacuum postgres")
    assert len(hits) == 1
    assert hits[0].conversation_title == "Postgres tips"
    assert hits[0].matched == "keyword"

    assert await hybrid_search(db, "kubernetes") == []


async def test_hybrid_search_merges_vector_results(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus_api.context import search as search_module
    from nexus_api.db.models import Message

    _add_key(db, "openai")
    conversation = _add_conversation(
        db,
        "Vector talk",
        [("user", "abstract musings entirely unrelated words"), ("user", "pasta recipe garlic")],
    )
    rows = db.scalars(select(Message).where(Message.conversation_id == conversation.id)).all()
    by_content = {row.content: row for row in rows}
    by_content["abstract musings entirely unrelated words"].embedding = _vector(1)
    by_content["pasta recipe garlic"].embedding = _vector(500)
    db.commit()

    async def fake_embed_query(session: Session, query: str) -> list[float]:
        return _vector(1)  # closest to the "abstract musings" message

    monkeypatch.setattr(search_module, "embed_query", fake_embed_query)
    monkeypatch.setattr(search_module, "embedding_available", lambda session: True)

    hits = await hybrid_search_with(search_module, db, "pasta garlic")
    matched = {hit.snippet[:5]: hit.matched for hit in hits}
    # Keyword found "pasta...", vector found "abstract..." — both present.
    assert any(m in ("keyword", "both") for m in matched.values())
    assert any(hit.matched == "vector" for hit in hits)


async def hybrid_search_with(search_module, db, query):  # type: ignore[no-untyped-def]
    return await search_module.hybrid_search(db, query)


# --- retrieval / context builder ---


async def test_build_context_sections_and_budget(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus_api.config import get_settings
    from nexus_api.context import retrieval
    from nexus_api.db.models import MemoryNote, ProfileSnapshot

    db.add(ProfileSnapshot(content="Works on Nexus. Prefers TypeScript."))
    db.add(MemoryNote(content="Ships side projects on weekends", category="habit"))
    db.commit()
    _add_conversation(db, "Deploy talk", [("user", "How do I deploy Nexus with Docker?")])

    bundle = await retrieval.build_context(db, "docker deploy")
    assert bundle is not None
    assert bundle.profile_used
    assert bundle.notes_count == 1
    assert bundle.messages_count == 1
    assert "Prefers TypeScript" in bundle.text
    assert "docker" in bundle.text.lower()

    # Budget: shrink drastically; profile survives, history is dropped.
    monkeypatch.setenv("NEXUS_CONTEXT_TOKEN_BUDGET", "60")
    get_settings.cache_clear()
    small = await retrieval.build_context(db, "docker deploy")
    get_settings.cache_clear()
    assert small is not None
    assert small.profile_used
    assert small.messages_count == 0
    assert len(small.text) <= 60 * 4


async def test_build_context_empty_returns_none(db: Session) -> None:
    from nexus_api.context.retrieval import build_context

    assert await build_context(db, "anything") is None
