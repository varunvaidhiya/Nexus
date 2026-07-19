"""Handoff briefs and the MCP endpoint — real Postgres."""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

TEST_DATABASE_URL = os.environ.get("NEXUS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="NEXUS_TEST_DATABASE_URL not set")


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
def clean(client: TestClient) -> Iterator[None]:
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        for table in (
            "handoff",
            "goal_task",
            "task",
            "goal",
            "message",
            "conversation",
            "source",
            "device_token",
            "profile_snapshot",
        ):
            conn.execute(text(f"DELETE FROM {table}"))
    engine.dispose()
    yield


def _seed_conversation(client: TestClient) -> tuple[str, str]:
    """Ingest a conversation; returns (conversation_id, task_id)."""
    batch = {
        "schema_version": "nexus.ingest.v1",
        "source": {"kind": "claude_code", "name": "claude_code@laptop", "ingest_tier": "A"},
        "conversations": [
            {
                "external_id": "s1",
                "title": "Fix the flaky login test",
                "project": "/home/user/webapp",
                "messages": [
                    {"role": "user", "content": "The login test is flaky, help me fix it."},
                    {"role": "assistant", "content": "It races the redirect; await the promise."},
                ],
            }
        ],
    }
    client.post("/ingest", json=batch).raise_for_status()
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conversation_id = conn.execute(text("SELECT id FROM conversation")).scalar()
        conn.execute(
            text("UPDATE conversation SET summary = 'Debugging a flaky login test together.'")
        )
    engine.dispose()
    task = client.post(
        "/tasks",
        json={
            "title": "Fix the flaky login test",
            "why_it_matters": "Blocks every deploy.",
            "priority": 2,
        },
    ).json()
    return str(conversation_id), task["id"]


# --- POST /handoff ---


def test_handoff_brief_from_task_and_conversation(client: TestClient) -> None:
    conversation_id, task_id = _seed_conversation(client)
    response = client.post(
        "/handoff",
        json={
            "target": "claude_code",
            "task_id": task_id,
            "conversation_id": conversation_id,
            "instructions": "Start by reproducing the race locally.",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    brief = payload["brief"]
    assert "continue in Claude Code" in brief
    assert "Fix the flaky login test" in brief
    assert "Blocks every deploy." in brief
    assert "Debugging a flaky login test" in brief  # conversation summary
    assert "races the redirect" in brief  # transcript tail
    assert "Start by reproducing the race locally." in brief  # custom next steps

    # The handoff was logged.
    (logged,) = client.get("/handoffs").json()
    assert logged["target"] == "claude_code"
    assert logged["task_id"] == task_id


def test_handoff_validation(client: TestClient) -> None:
    assert client.post("/handoff", json={"target": "nope", "task_id": None}).status_code == 400
    assert client.post("/handoff", json={"target": "cursor"}).status_code == 400
    missing = client.post(
        "/handoff",
        json={"target": "cursor", "task_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert missing.status_code == 404


def test_handoff_accepts_device_token(client: TestClient) -> None:
    _, task_id = _seed_conversation(client)
    device = client.post("/devices", json={"name": "laptop"}).json()
    response = client.post(
        "/handoff",
        json={"target": "generic", "task_id": task_id},
        headers={"Authorization": f"Bearer {device['token']}"},
    )
    assert response.status_code == 200
    # But device tokens still can't reach the primary API.
    assert (
        client.get("/tasks", headers={"Authorization": f"Bearer {device['token']}"}).status_code
        == 401
    )


# --- /mcp ---


def _rpc(client: TestClient, method: str, params: dict | None = None, **kw) -> dict:
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    response = client.post("/mcp", json=body, **kw)
    assert response.status_code == 200, response.text
    return response.json()


def _tool_call(client: TestClient, name: str, arguments: dict) -> dict:
    reply = _rpc(client, "tools/call", {"name": name, "arguments": arguments})
    assert "result" in reply, reply
    return reply["result"]


def test_mcp_initialize_and_list(client: TestClient) -> None:
    reply = _rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    assert reply["result"]["protocolVersion"] == "2025-06-18"
    assert reply["result"]["serverInfo"]["name"] == "nexus"

    # Notifications get 202 with no body.
    note = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert note.status_code == 202

    tools = _rpc(client, "tools/list")["result"]["tools"]
    assert {tool["name"] for tool in tools} == {
        "search_memory",
        "get_profile",
        "get_open_tasks",
        "get_conversation",
        "log_handoff",
    }


def test_mcp_tools_roundtrip(client: TestClient) -> None:
    import json

    conversation_id, _task_id = _seed_conversation(client)

    hits = json.loads(
        _tool_call(client, "search_memory", {"query": "flaky login"})["content"][0]["text"]
    )
    assert hits and hits[0]["conversation_id"] == conversation_id

    tasks = json.loads(_tool_call(client, "get_open_tasks", {})["content"][0]["text"])
    assert [t["title"] for t in tasks] == ["Fix the flaky login test"]

    detail = json.loads(
        _tool_call(client, "get_conversation", {"conversation_id": conversation_id})["content"][0][
            "text"
        ]
    )
    assert detail["title"] == "Fix the flaky login test"
    assert len(detail["messages"]) == 2

    profile = _tool_call(client, "get_profile", {})
    assert "No profile" in profile["content"][0]["text"]

    logged = json.loads(
        _tool_call(
            client,
            "log_handoff",
            {"target": "cursor", "conversation_id": conversation_id, "note": "picked up"},
        )["content"][0]["text"]
    )
    assert "handoff_id" in logged
    (row,) = client.get("/handoffs").json()
    assert row["target"] == "cursor"
    assert row["note"] == "picked up"


def test_mcp_errors(client: TestClient) -> None:
    unknown = _rpc(client, "resources/list")
    assert unknown["error"]["code"] == -32601

    bad_tool = _tool_call(client, "no_such_tool", {})
    assert bad_tool["isError"] is True

    bad_conversation = _tool_call(client, "get_conversation", {"conversation_id": "not-a-uuid"})
    assert bad_conversation["isError"] is True

    assert client.get("/mcp").status_code == 405


def test_mcp_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 401


def test_mcp_batch(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json=[
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ],
    )
    assert response.status_code == 200
    replies = response.json()
    assert [r["id"] for r in replies] == [1, 2]
