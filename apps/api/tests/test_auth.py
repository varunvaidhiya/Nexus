import os

import pytest
from fastapi.testclient import TestClient

from nexus_api.config import get_settings
from nexus_api.main import create_app

TOKEN = os.environ["NEXUS_AUTH_TOKEN"]


@pytest.fixture
def client() -> TestClient:
    get_settings.cache_clear()
    return TestClient(create_app())


def test_healthz_is_public(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200


def test_missing_token_rejected(client: TestClient) -> None:
    assert client.get("/providers").status_code == 401


def test_wrong_token_rejected(client: TestClient) -> None:
    response = client.get("/providers", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


def test_wrong_scheme_rejected(client: TestClient) -> None:
    response = client.get("/providers", headers={"Authorization": f"Basic {TOKEN}"})
    assert response.status_code == 401


def test_unset_token_refuses_service(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUS_AUTH_TOKEN")
    get_settings.cache_clear()
    try:
        response = client.get("/providers", headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 503
        assert "NEXUS_AUTH_TOKEN" in response.json()["detail"]
    finally:
        get_settings.cache_clear()
