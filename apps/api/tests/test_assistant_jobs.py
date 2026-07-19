"""Assistant-job tests: task extraction, loose ends, weekly review — real
Postgres, fake LLM."""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

TEST_DATABASE_URL = os.environ.get("NEXUS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="NEXUS_TEST_DATABASE_URL not set")


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
            "suggestion",
            "review",
            "goal_task",
            "task",
            "goal",
            "message",
            "conversation",
            "job_run",
            "provider_key",
            "source",
        ):
            conn.execute(text(f"DELETE FROM {table}"))
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


def _add_key(session: Session) -> None:
    from nexus_api import crypto
    from nexus_api.db.models import ProviderKey

    session.add(ProviderKey(provider="anthropic", encrypted_key=crypto.encrypt("sk-test")))
    session.commit()


def _add_conversation(session: Session, title: str, *, summary: str, age_days: float = 0):
    from nexus_api.db.models import Conversation, Message, MessageRole, Source, SourceKind

    source = session.scalars(select(Source)).first()
    if source is None:
        source = Source(name="nexus", kind=SourceKind.native, ingest_tier="D")
        session.add(source)
        session.flush()
    when = datetime.now(UTC) - timedelta(days=age_days)
    conversation = Conversation(
        source_id=source.id, title=title, summary=summary, updated_at=when, summarized_at=when
    )
    session.add(conversation)
    session.flush()
    session.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.user,
            content=f"let's work on {title}",
            created_at=when,
        )
    )
    session.commit()
    return conversation


def _fake_complete(response: dict[str, object]):
    async def fake(session: Session, prompt: str, *, max_tokens: int = 1024) -> str:
        return json.dumps(response)

    return fake


async def test_extract_tasks_thresholds_and_dedupes(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus_api.db.models import JobStatus, Task
    from nexus_api.jobs import assistant
    from nexus_api.jobs.framework import run_job

    _add_key(db)
    conversation = _add_conversation(db, "CI work", summary="Discussed fixing the CI pipeline.")

    monkeypatch.setattr(
        assistant,
        "complete",
        _fake_complete(
            {
                "tasks": [
                    {
                        "title": "Fix the flaky CI pipeline",
                        "detail": "The postgres service times out",
                        "priority": 2,
                        "due_at": "2026-07-25T00:00:00Z",
                        "why_it_matters": "Blocks every merge.",
                        "confidence": 0.9,
                    },
                    {
                        "title": "Maybe look at docs someday",
                        "priority": 0,
                        "confidence": 0.3,  # below threshold — dropped
                    },
                ]
            }
        ),
    )
    assert await run_job("extract_tasks", assistant.extract_tasks) == JobStatus.success

    tasks = db.scalars(select(Task)).all()
    assert [t.title for t in tasks] == ["Fix the flaky CI pipeline"]
    task = tasks[0]
    assert task.priority == 2
    assert task.due_at is not None
    assert task.source_conversation_id == conversation.id
    assert task.why_it_matters == "Blocks every merge."

    # Re-run after the conversation updates: same title is not duplicated.
    db.expire_all()
    refreshed = db.get(type(conversation), conversation.id)
    assert refreshed is not None
    refreshed.updated_at = datetime.now(UTC) + timedelta(seconds=5)
    db.commit()
    assert await run_job("extract_tasks", assistant.extract_tasks) == JobStatus.success
    assert len(db.scalars(select(Task)).all()) == 1


async def test_loose_end_detection_and_dismissal_sticks(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus_api.db.models import Conversation, JobStatus, Suggestion
    from nexus_api.jobs import assistant
    from nexus_api.jobs.framework import run_job

    _add_key(db)
    stale = _add_conversation(db, "Auth refactor", summary="Started refactoring auth.", age_days=5)
    _add_conversation(db, "Fresh chat", summary="Just now.", age_days=0)  # too recent
    _add_conversation(db, "Ancient", summary="Old.", age_days=60)  # too old

    monkeypatch.setattr(
        assistant,
        "complete",
        _fake_complete({"loose_end": True, "reason": "You never finished the auth refactor."}),
    )
    assert await run_job("detect_loose_ends", assistant.detect_loose_ends) == JobStatus.success

    (suggestion,) = db.scalars(select(Suggestion)).all()
    assert suggestion.conversation_id == stale.id
    assert "auth refactor" in suggestion.reason

    # Re-run: nothing new (already raised).
    assert await run_job("detect_loose_ends", assistant.detect_loose_ends) == JobStatus.success
    assert len(db.scalars(select(Suggestion)).all()) == 1

    # Dismiss, then update the conversation — the detector must NOT re-raise.
    suggestion.dismissed_at = datetime.now(UTC)
    conversation = db.get(Conversation, stale.id)
    assert conversation is not None
    conversation.updated_at = datetime.now(UTC) - timedelta(days=4)
    conversation.loose_end_checked_at = None
    db.commit()
    assert await run_job("detect_loose_ends", assistant.detect_loose_ends) == JobStatus.success
    assert len(db.scalars(select(Suggestion)).all()) == 1


async def test_weekly_review_generates_once_per_period(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nexus_api.db.models import JobStatus, Review
    from nexus_api.jobs import assistant
    from nexus_api.jobs.framework import run_job

    _add_key(db)
    _add_conversation(db, "Nexus phase 4", summary="Built the assistant layer.", age_days=2)

    async def fake(session: Session, prompt: str, *, max_tokens: int = 1024) -> str:
        return "## What you worked on\n- Nexus phase 4: built the assistant layer."

    monkeypatch.setattr(assistant, "complete", fake)
    assert await run_job("weekly_review", assistant.weekly_review) == JobStatus.success
    (review,) = db.scalars(select(Review)).all()
    assert "assistant layer" in review.content
    assert (review.period_end - review.period_start).days == 7

    # Within the same period: skipped, not duplicated.
    assert await run_job("weekly_review", assistant.weekly_review) == JobStatus.skipped
    assert len(db.scalars(select(Review)).all()) == 1


async def test_jobs_skip_without_key(db: Session) -> None:
    from nexus_api.db.models import JobStatus
    from nexus_api.jobs import assistant
    from nexus_api.jobs.framework import run_job

    assert await run_job("extract_tasks", assistant.extract_tasks) == JobStatus.skipped
    assert await run_job("detect_loose_ends", assistant.detect_loose_ends) == JobStatus.skipped
    assert await run_job("weekly_review", assistant.weekly_review) == JobStatus.skipped
