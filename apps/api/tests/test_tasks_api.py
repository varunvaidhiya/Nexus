"""Tasks, goals, Today ranking, suggestions, reviews — API surface tests."""

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

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
            "suggestion",
            "review",
            "goal_task",
            "task",
            "goal",
            "message",
            "conversation",
            "source",
        ):
            conn.execute(text(f"DELETE FROM {table}"))
    engine.dispose()
    yield


def test_task_crud_and_completion(client: TestClient) -> None:
    created = client.post("/tasks", json={"title": "Write the Phase 4 tests", "priority": 2})
    assert created.status_code == 201
    task = created.json()
    assert task["status"] == "todo"
    assert task["completed_at"] is None

    # Move through the board; done stamps completed_at, reopening clears it.
    doing = client.patch(f"/tasks/{task['id']}", json={"status": "doing"}).json()
    assert doing["status"] == "doing"
    done = client.patch(f"/tasks/{task['id']}", json={"status": "done"}).json()
    assert done["completed_at"] is not None
    reopened = client.patch(f"/tasks/{task['id']}", json={"status": "todo"}).json()
    assert reopened["completed_at"] is None

    assert client.get("/tasks", params={"status": "todo"}).json()[0]["id"] == task["id"]
    assert client.get("/tasks", params={"status": "done"}).json() == []
    assert client.patch(f"/tasks/{task['id']}", json={"priority": 9}).status_code == 422


def test_goal_linking_and_progress(client: TestClient) -> None:
    goal = client.post("/goals", json={"title": "Ship Nexus v1", "horizon": "quarter"}).json()
    first = client.post("/tasks", json={"title": "Finish phase 4"}).json()
    second = client.post("/tasks", json={"title": "Finish phase 5"}).json()

    for task in (first, second):
        assert (
            client.post(f"/goals/{goal['id']}/tasks", json={"task_id": task["id"]}).status_code
            == 204
        )
    # Linking twice is a no-op.
    client.post(f"/goals/{goal['id']}/tasks", json={"task_id": first["id"]})

    (listed,) = client.get("/goals").json()
    assert listed["task_count"] == 2
    assert listed["done_count"] == 0
    assert listed["progress"] == 0

    client.patch(f"/tasks/{first['id']}", json={"status": "done"})
    (listed,) = client.get("/goals").json()
    assert listed["done_count"] == 1
    assert listed["progress"] == 0.5

    # The task lists its goal; unlinking drops it from the rollup.
    assert client.get("/tasks").json()[0]["goal_ids"] == [goal["id"]]
    client.delete(f"/goals/{goal['id']}/tasks/{second['id']}")
    (listed,) = client.get("/goals").json()
    assert listed["task_count"] == 1
    assert listed["progress"] == 1.0


def test_today_ranks_with_reasons(client: TestClient) -> None:
    now = datetime.now(UTC)
    overdue = client.post(
        "/tasks",
        json={"title": "Pay the invoice", "due_at": (now - timedelta(days=2)).isoformat()},
    ).json()
    urgent = client.post("/tasks", json={"title": "Prep the demo", "priority": 3}).json()
    background = client.post("/tasks", json={"title": "Read that article"}).json()
    done = client.post("/tasks", json={"title": "Already finished"}).json()
    client.patch(f"/tasks/{done['id']}", json={"status": "done"})

    goal = client.post("/goals", json={"title": "Stay solvent", "horizon": "month"}).json()
    client.post(f"/goals/{goal['id']}/tasks", json={"task_id": overdue["id"]})

    items = client.get("/today").json()
    assert [item["task"]["id"] for item in items] == [
        overdue["id"],
        urgent["id"],
        background["id"],
    ]  # done tasks never appear
    top = items[0]
    assert top["score"] > items[1]["score"] > items[2]["score"] == 0
    assert any("Overdue" in reason for reason in top["reasons"])
    assert any('goal "Stay solvent"' in reason for reason in top["reasons"])
    assert any("Priority 3" in reason for reason in items[1]["reasons"])


def test_suggestions_dismiss(client: TestClient) -> None:
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        source_id = conn.execute(
            text(
                "INSERT INTO source (name, kind, ingest_tier) "
                "VALUES ('nexus', 'native', 'D') RETURNING id"
            )
        ).scalar()
        conversation_id = conn.execute(
            text(
                "INSERT INTO conversation (source_id, title) "
                "VALUES (:s, 'Auth refactor') RETURNING id"
            ).bindparams(s=source_id)
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO suggestion (conversation_id, reason) "
                "VALUES (:c, 'You never finished this.')"
            ).bindparams(c=conversation_id)
        )
    engine.dispose()

    (suggestion,) = client.get("/suggestions").json()
    assert suggestion["conversation_title"] == "Auth refactor"
    assert suggestion["kind"] == "loose_end"

    assert client.post(f"/suggestions/{suggestion['id']}/dismiss").status_code == 204
    assert client.get("/suggestions").json() == []


def test_reviews_listing(client: TestClient) -> None:
    assert TEST_DATABASE_URL is not None
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO review (period_start, period_end, content) VALUES "
                "('2026-07-05', '2026-07-12', '## Week one'), "
                "('2026-07-12', '2026-07-19', '## Week two')"
            )
        )
    engine.dispose()

    reviews = client.get("/reviews").json()
    assert [r["content"] for r in reviews] == ["## Week two", "## Week one"]  # newest first
