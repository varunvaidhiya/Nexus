"""Provider-key API tests against a real Postgres (skipped without
NEXUS_TEST_DATABASE_URL)."""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

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

    # Schema is provided by the session-scoped migrated_db fixture (conftest).
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM provider_key"))
    engine.dispose()

    token = os.environ["NEXUS_AUTH_TOKEN"]
    with TestClient(create_app(), headers={"Authorization": f"Bearer {token}"}) as test_client:
        yield test_client


def test_add_key_returns_no_key_material(client: TestClient) -> None:
    response = client.post(
        "/providers/keys",
        json={
            "provider": "anthropic",
            "api_key": "sk-ant-test-abc123",
            "models": ["claude-sonnet-5"],
            "monthly_budget_usd": "25.00",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["provider"] == "anthropic"
    assert body["models"] == ["claude-sonnet-5"]
    assert "sk-ant-test-abc123" not in response.text
    assert "api_key" not in body
    assert "encrypted_key" not in body


def test_key_is_encrypted_at_rest_and_round_trips(client: TestClient) -> None:
    from nexus_api.db.models import ProviderKey
    from nexus_api.db.session import get_engine
    from nexus_api.routers.providers import get_decrypted_key

    with Session(get_engine()) as session:
        row = session.scalars(select(ProviderKey).where(ProviderKey.provider == "anthropic")).one()
        assert b"sk-ant-test-abc123" not in row.encrypted_key
        assert get_decrypted_key(session, "anthropic").get_secret_value() == "sk-ant-test-abc123"


def test_upsert_replaces_key(client: TestClient) -> None:
    from nexus_api.db.session import get_engine
    from nexus_api.routers.providers import get_decrypted_key

    response = client.post(
        "/providers/keys",
        json={"provider": "anthropic", "api_key": "sk-ant-rotated"},
    )
    assert response.status_code == 201

    providers = client.get("/providers").json()
    assert [p["provider"] for p in providers] == ["anthropic"]

    with Session(get_engine()) as session:
        assert get_decrypted_key(session, "anthropic").get_secret_value() == "sk-ant-rotated"


def test_list_providers(client: TestClient) -> None:
    client.post("/providers/keys", json={"provider": "openai", "api_key": "sk-oai-x"})
    providers = client.get("/providers").json()
    assert [p["provider"] for p in providers] == ["anthropic", "openai"]
    assert all("api_key" not in p and "encrypted_key" not in p for p in providers)


def test_delete_key(client: TestClient) -> None:
    assert client.delete("/providers/keys/openai").status_code == 204
    assert client.delete("/providers/keys/openai").status_code == 404
    providers = client.get("/providers").json()
    assert [p["provider"] for p in providers] == ["anthropic"]


def test_invalid_provider_name_rejected(client: TestClient) -> None:
    response = client.post(
        "/providers/keys",
        json={"provider": "Not Valid!", "api_key": "sk-x"},
    )
    assert response.status_code == 422
