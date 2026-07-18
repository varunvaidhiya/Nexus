"""Ingestion API tests: /ingest dedupe, device tokens, /sources, /import.

Real Postgres (NEXUS_TEST_DATABASE_URL), no fakes — the whole point of the
ingest path is what ends up in the database.
"""

import io
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

TEST_DATABASE_URL = os.environ.get("NEXUS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="NEXUS_TEST_DATABASE_URL not set")

FIXTURES = Path(__file__).parent / "fixtures"


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
        conn.execute(text("DELETE FROM message"))
        conn.execute(text("DELETE FROM conversation"))
        conn.execute(text("DELETE FROM source"))
        conn.execute(text("DELETE FROM device_token"))
    engine.dispose()
    yield


def _batch(**overrides: object) -> dict:
    batch = {
        "schema_version": "nexus.ingest.v1",
        "source": {"kind": "claude_code", "name": "claude_code@laptop", "ingest_tier": "A"},
        "conversations": [
            {
                "external_id": "session-1",
                "title": "Fix flaky test",
                "model": "claude-sonnet-5",
                "tool": "claude_code",
                "project": "/home/user/webapp",
                "messages": [
                    {"external_id": "m1", "role": "user", "content": "fix the login test"},
                    {"external_id": "m2", "role": "assistant", "content": "done, it was a race"},
                ],
            }
        ],
    }
    batch.update(overrides)
    return batch


def test_ingest_and_resend_is_idempotent(client: TestClient) -> None:
    first = client.post("/ingest", json=_batch())
    assert first.status_code == 200
    assert first.json() == {
        "conversations": 1,
        "new_conversations": 1,
        "new_messages": 2,
        "skipped_messages": 0,
    }

    # Same batch again: nothing new.
    again = client.post("/ingest", json=_batch())
    assert again.json() == {
        "conversations": 1,
        "new_conversations": 0,
        "new_messages": 0,
        "skipped_messages": 2,
    }

    # The session grew: only the new message lands.
    grown = _batch()
    grown["conversations"][0]["messages"].append(  # type: ignore[index]
        {"external_id": "m3", "role": "user", "content": "thanks!"}
    )
    third = client.post("/ingest", json=grown)
    assert third.json()["new_messages"] == 1
    assert third.json()["skipped_messages"] == 2


def test_ingest_dedupes_by_fingerprint_without_external_id(client: TestClient) -> None:
    batch = _batch()
    for message in batch["conversations"][0]["messages"]:  # type: ignore[index]
        message["external_id"] = None
    client.post("/ingest", json=batch).raise_for_status()
    again = client.post("/ingest", json=batch)
    assert again.json()["new_messages"] == 0
    assert again.json()["skipped_messages"] == 2


def test_ingest_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post("/ingest", json=_batch(surprise="field"))
    assert response.status_code == 422


def test_device_token_lifecycle(client: TestClient) -> None:
    created = client.post("/devices", json={"name": "laptop"})
    assert created.status_code == 201
    device = created.json()
    assert device["token"].startswith("nxd_")
    assert device["revoked"] is False

    # Listing never re-exposes the token.
    (listed,) = client.get("/devices").json()
    assert "token" not in listed
    assert listed["last_used_at"] is None

    # The device token can ingest but cannot reach other routes.
    device_headers = {"Authorization": f"Bearer {device['token']}"}
    ok = client.post("/ingest", json=_batch(), headers=device_headers)
    assert ok.status_code == 200
    assert client.get("/sources", headers=device_headers).status_code == 401

    # Use is recorded.
    (listed,) = client.get("/devices").json()
    assert listed["last_used_at"] is not None

    # Revocation shuts the door.
    assert client.delete(f"/devices/{device['id']}").status_code == 204
    denied = client.post("/ingest", json=_batch(), headers=device_headers)
    assert denied.status_code == 401


def test_ingest_rejects_bad_token(client: TestClient) -> None:
    response = client.post("/ingest", json=_batch(), headers={"Authorization": "Bearer nxd_wrong"})
    assert response.status_code == 401


def test_sources_dashboard(client: TestClient) -> None:
    client.post("/ingest", json=_batch()).raise_for_status()
    (source,) = client.get("/sources").json()
    assert source["kind"] == "claude_code"
    assert source["name"] == "claude_code@laptop"
    assert source["ingest_tier"] == "A"
    assert source["conversation_count"] == 1
    assert source["message_count"] == 2
    assert source["last_synced_at"] is not None


def test_import_chatgpt_export(client: TestClient) -> None:
    upload = {
        "file": (
            "conversations.json",
            io.BytesIO((FIXTURES / "chatgpt-export.json").read_bytes()),
            "application/json",
        )
    }
    response = client.post("/import", files=upload)
    assert response.status_code == 200
    report = response.json()
    assert report["source_kind"] == "chatgpt"
    assert report["new_conversations"] == 2
    assert report["new_messages"] == 2

    # Importing the same file twice adds nothing.
    upload["file"] = (
        "conversations.json",
        io.BytesIO((FIXTURES / "chatgpt-export.json").read_bytes()),
        "application/json",
    )
    again = client.post("/import", files=upload).json()
    assert again["new_conversations"] == 0
    assert again["new_messages"] == 0


def test_import_rejects_garbage(client: TestClient) -> None:
    upload = {"file": ("conversations.json", io.BytesIO(b"{nope"), "application/json")}
    response = client.post("/import", files=upload)
    assert response.status_code == 400
    assert "JSON" in response.json()["detail"]
