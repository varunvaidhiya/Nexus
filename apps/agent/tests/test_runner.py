import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import jsonschema
import pytest

from nexus_agent.config import AgentConfig, ToolConfig
from nexus_agent.runner import sync_once
from nexus_agent.state import SyncState

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA_PATH = Path(__file__).parents[3] / "packages" / "schema" / "ingest.v1.schema.json"


def _setup(tmp_path: Path) -> tuple[AgentConfig, SyncState, Path]:
    root = tmp_path / "projects"
    session = root / "-home-user-webapp" / "abc123.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text((FIXTURES / "session.jsonl").read_text())
    config = AgentConfig(
        backend_url="http://backend",
        token="nxd_test",
        machine_name="laptop",
        tools={"claude_code": ToolConfig(enabled=True, root=root)},
        state_path=tmp_path / "state.json",
    )
    state = SyncState(config.state_path)
    state.load()
    return config, state, session


def _client(received: list[dict[str, Any]]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ingest"
        assert request.headers["authorization"] == "Bearer nxd_test"
        received.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "conversations": 1,
                "new_conversations": 1,
                "new_messages": 4,
                "skipped_messages": 0,
            },
        )

    return httpx.Client(
        base_url="http://backend",
        headers={"Authorization": "Bearer nxd_test"},
        transport=httpx.MockTransport(handler),
    )


def test_sync_pushes_schema_valid_batch(tmp_path: Path) -> None:
    config, state, _ = _setup(tmp_path)
    received: list[dict[str, Any]] = []
    assert sync_once(config, _client(received), state) == 1

    (batch,) = received
    jsonschema.validate(batch, json.loads(SCHEMA_PATH.read_text()))
    assert batch["source"] == {
        "kind": "claude_code",
        "name": "claude_code@laptop",
        "ingest_tier": "A",
    }
    (conversation,) = batch["conversations"]
    assert conversation["external_id"] == "abc123"
    assert conversation["title"] == "Fix flaky login test"
    assert len(conversation["messages"]) == 4


def test_sync_is_incremental(tmp_path: Path) -> None:
    config, state, session = _setup(tmp_path)
    received: list[dict[str, Any]] = []
    client = _client(received)

    assert sync_once(config, client, state) == 1
    assert sync_once(config, client, state) == 0  # unchanged file is skipped
    assert len(received) == 1

    # State survives a restart.
    fresh = SyncState(config.state_path)
    fresh.load()
    assert sync_once(config, client, fresh) == 0

    # A modified file is re-sent.
    new_mtime = session.stat().st_mtime + 10
    os.utime(session, (new_mtime, new_mtime))
    assert sync_once(config, client, fresh) == 1
    assert len(received) == 2


def test_failed_push_is_retried_next_pass(tmp_path: Path) -> None:
    config, state, _ = _setup(tmp_path)

    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    client = httpx.Client(base_url="http://backend", transport=httpx.MockTransport(failing))
    with pytest.raises(httpx.HTTPStatusError):
        sync_once(config, client, state)

    received: list[dict[str, Any]] = []
    assert sync_once(config, _client(received), state) == 1


def test_disabled_tool_is_skipped(tmp_path: Path) -> None:
    config, state, _ = _setup(tmp_path)
    config.tools["claude_code"].enabled = False
    received: list[dict[str, Any]] = []
    assert sync_once(config, _client(received), state) == 0
    assert received == []


def test_unparseable_session_not_reparsed_until_changed(tmp_path: Path) -> None:
    config, state, session = _setup(tmp_path)
    session.write_text('{"type":"progress"}\n')
    received: list[dict[str, Any]] = []
    client = _client(received)
    assert sync_once(config, client, state) == 0
    assert state.needs_sync("claude_code", session, session.stat().st_mtime) is False
    assert state.needs_sync("claude_code", session, time.time() + 100) is True
