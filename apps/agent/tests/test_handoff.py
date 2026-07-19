from pathlib import Path

import httpx
import pytest

from nexus_agent.config import AgentConfig, HandoffConfig
from nexus_agent.handoff import BRIEF_FILENAME, HandoffError, fetch_brief, write_primer


def _config(tmp_path: Path, *, enabled: bool) -> AgentConfig:
    return AgentConfig(
        backend_url="http://backend",
        token="nxd_test",
        state_path=tmp_path / "state.json",
        handoff=HandoffConfig(enabled=enabled),
    )


def _client(handler) -> httpx.Client:  # type: ignore[no-untyped-def]
    return httpx.Client(base_url="http://backend", transport=httpx.MockTransport(handler))


def test_fetch_brief(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/handoff"
        return httpx.Response(200, json={"brief": "# Nexus handoff\ndo the thing"})

    with _client(handler) as client:
        brief = fetch_brief(
            client, target="claude_code", task_id="t1", conversation_id=None, instructions=None
        )
    assert brief.startswith("# Nexus handoff")


def test_fetch_brief_surfaces_backend_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "unknown target"})

    with _client(handler) as client, pytest.raises(HandoffError, match="unknown target"):
        fetch_brief(client, target="nope", task_id=None, conversation_id=None, instructions=None)


def test_write_primer_requires_opt_in(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(HandoffError, match="disabled"):
        write_primer(_config(tmp_path, enabled=False), repo, "brief")
    assert not (repo / BRIEF_FILENAME).exists()


def test_write_primer(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = write_primer(_config(tmp_path, enabled=True), repo, "# brief\ncontent")
    assert path == repo / BRIEF_FILENAME
    assert path.read_text() == "# brief\ncontent"


def test_write_primer_rejects_missing_repo(tmp_path: Path) -> None:
    with pytest.raises(HandoffError, match="not a directory"):
        write_primer(_config(tmp_path, enabled=True), tmp_path / "nope", "brief")
