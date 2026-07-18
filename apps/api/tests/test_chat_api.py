"""Chat API tests: SSE streaming, Tier D capture, budgets — real Postgres,
fake gateway (the adapters have their own tests)."""

import json
import os
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from nexus_api.gateway.types import ChatMessage, Completion, ErrorKind, GatewayError, TextDelta

TEST_DATABASE_URL = os.environ.get("NEXUS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="NEXUS_TEST_DATABASE_URL not set")

captured_calls: list[dict[str, object]] = []


async def fake_stream_chat(
    provider_name: str,
    *,
    api_key: str,
    model: str,
    messages: list[ChatMessage],
    system: str | None = None,
    max_tokens: int = 16000,
) -> AsyncIterator[TextDelta | Completion]:
    captured_calls.append(
        {"provider": provider_name, "model": model, "messages": list(messages), "system": system}
    )
    if model == "explode-mid-stream":
        yield TextDelta("partial ")
        raise GatewayError(ErrorKind.overloaded, provider_name, "boom", retryable=True)
    yield TextDelta("Hello ")
    yield TextDelta("world")
    yield Completion("end_turn", 10, 2)


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    assert TEST_DATABASE_URL is not None
    os.environ["NEXUS_DATABASE_URL"] = TEST_DATABASE_URL

    from nexus_api.config import get_settings
    from nexus_api.db.session import get_engine
    from nexus_api.main import create_app

    get_settings.cache_clear()
    get_engine.cache_clear()

    token = os.environ["NEXUS_AUTH_TOKEN"]
    with TestClient(create_app(), headers={"Authorization": f"Bearer {token}"}) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    import nexus_api.routers.chat as chat_module

    monkeypatch.setattr(chat_module, "stream_chat", fake_stream_chat)
    captured_calls.clear()
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM message"))
        conn.execute(text("DELETE FROM conversation"))
        conn.execute(text("DELETE FROM provider_key"))
    engine.dispose()
    client.post(
        "/providers/keys",
        json={"provider": "anthropic", "api_key": "sk-test", "monthly_budget_usd": "10.00"},
    ).raise_for_status()
    yield


def _events(response) -> list[tuple[str, dict]]:  # type: ignore[no-untyped-def]
    events: list[tuple[str, dict]] = []
    event: str | None = None
    for line in response.iter_lines():
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and event:
            events.append((event, json.loads(line.split(":", 1)[1])))
    return events


def _db() -> Session:
    assert TEST_DATABASE_URL is not None
    return Session(create_engine(TEST_DATABASE_URL))


def test_chat_streams_and_captures(client: TestClient) -> None:
    from nexus_api.db.models import Conversation, Message, ProviderKey, Source, SourceKind

    with client.stream(
        "POST",
        "/chat",
        json={"provider": "anthropic", "model": "claude-sonnet-5", "message": "Say hello"},
    ) as response:
        assert response.status_code == 200
        events = _events(response)

    kinds = [name for name, _ in events]
    assert kinds[0] == "meta"
    assert "delta" in kinds
    assert kinds[-1] == "done"
    done = events[-1][1]
    assert done["stop_reason"] == "end_turn"
    assert done["input_tokens"] == 10

    with _db() as db:
        conversation = db.scalars(select(Conversation)).one()
        assert conversation.title == "Say hello"
        source = db.get(Source, conversation.source_id)
        assert source is not None and source.kind == SourceKind.native
        assert source.ingest_tier == "D"
        messages = db.scalars(select(Message).order_by(Message.created_at, Message.id)).all()
        assert [m.role.value for m in messages] == ["user", "assistant"]
        assert messages[1].content == "Hello world"
        assert messages[1].token_count == 2
        key = db.scalars(select(ProviderKey)).one()
        assert key.spend_usd > 0  # spend recorded


def test_chat_continues_conversation_with_history(client: TestClient) -> None:
    with client.stream(
        "POST",
        "/chat",
        json={"provider": "anthropic", "model": "claude-sonnet-5", "message": "First"},
    ) as response:
        conversation_id = _events(response)[0][1]["conversation_id"]

    with client.stream(
        "POST",
        "/chat",
        json={
            "conversation_id": conversation_id,
            "provider": "anthropic",
            "model": "claude-sonnet-5",
            "message": "Second",
        },
    ) as response:
        events = _events(response)
        assert events[0][1]["conversation_id"] == conversation_id

    # The gateway received the full history including the prior assistant turn.
    roles = [m.role for m in captured_calls[-1]["messages"]]  # type: ignore[union-attr]
    assert roles == ["user", "assistant", "user"]


def test_chat_unknown_conversation_404(client: TestClient) -> None:
    response = client.post(
        "/chat",
        json={
            "conversation_id": "00000000-0000-0000-0000-000000000000",
            "provider": "anthropic",
            "model": "m",
            "message": "hi",
        },
    )
    assert response.status_code == 404


def test_chat_without_key_is_400(client: TestClient) -> None:
    response = client.post("/chat", json={"provider": "openai", "model": "gpt-4o", "message": "hi"})
    assert response.status_code == 400
    assert response.json()["detail"]["kind"] == "auth"


def test_chat_over_budget_is_402(client: TestClient) -> None:
    from nexus_api.db.models import ProviderKey

    with _db() as db, db.begin():
        key = db.scalars(select(ProviderKey)).one()
        key.spend_usd = Decimal("10.00")
        from nexus_api.gateway.budget import _current_month

        key.spend_month = _current_month()

    response = client.post(
        "/chat", json={"provider": "anthropic", "model": "claude-sonnet-5", "message": "hi"}
    )
    assert response.status_code == 402
    assert response.json()["detail"]["kind"] == "budget"


def test_mid_stream_error_persists_partial(client: TestClient) -> None:
    from nexus_api.db.models import Message

    with client.stream(
        "POST",
        "/chat",
        json={"provider": "anthropic", "model": "explode-mid-stream", "message": "hi"},
    ) as response:
        events = _events(response)

    assert events[-1][0] == "error"
    assert events[-1][1]["kind"] == "overloaded"
    assert events[-1][1]["retryable"] is True

    with _db() as db:
        contents = [m.content for m in db.scalars(select(Message)).all()]
    assert "partial " in contents  # partial assistant output captured


def test_chat_with_context_injects_system_prompt(client: TestClient) -> None:
    from nexus_api.db.models import ProfileSnapshot

    with _db() as db, db.begin():
        db.add(ProfileSnapshot(content="Works on Nexus; prefers TypeScript."))

    with client.stream(
        "POST",
        "/chat",
        json={
            "provider": "anthropic",
            "model": "claude-sonnet-5",
            "message": "hi",
            "use_context": True,
        },
    ) as response:
        events = _events(response)

    meta = events[0][1]
    assert meta["context"] is not None
    assert meta["context"]["profile"] is True
    assert "prefers TypeScript" in meta["context"]["text"]
    # The same block reached the gateway as the system prompt.
    assert "prefers TypeScript" in (captured_calls[-1]["system"] or "")

    # Clean chats send no system prompt and report no context.
    with client.stream(
        "POST",
        "/chat",
        json={"provider": "anthropic", "model": "claude-sonnet-5", "message": "hi again"},
    ) as response:
        clean_meta = _events(response)[0][1]
    assert clean_meta["context"] is None
    assert captured_calls[-1]["system"] is None


def test_conversation_endpoints(client: TestClient) -> None:
    with client.stream(
        "POST",
        "/chat",
        json={"provider": "anthropic", "model": "claude-sonnet-5", "message": "List me"},
    ) as response:
        conversation_id = _events(response)[0][1]["conversation_id"]

    listing = client.get("/conversations").json()
    assert len(listing) == 1
    assert listing[0]["id"] == conversation_id
    assert listing[0]["message_count"] == 2
    assert listing[0]["source_kind"] == "native"

    detail = client.get(f"/conversations/{conversation_id}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert client.get("/conversations?source_kind=chatgpt").json() == []
    assert client.get("/conversations/00000000-0000-0000-0000-000000000000").status_code == 404
