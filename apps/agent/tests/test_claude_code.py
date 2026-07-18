from pathlib import Path

from nexus_agent.adapters import claude_code

FIXTURES = Path(__file__).parent / "fixtures"


def _copy_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "projects"
    session = root / "-home-user-webapp" / "abc123.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text((FIXTURES / "session.jsonl").read_text())
    return root


def test_discover_sessions(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    (root / "-home-user-webapp" / "notes.txt").write_text("ignored")
    found = list(claude_code.discover_sessions(root))
    assert [p.name for p in found] == ["abc123.jsonl"]


def test_discover_missing_root(tmp_path: Path) -> None:
    assert list(claude_code.discover_sessions(tmp_path / "nope")) == []


def test_parse_session(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    parsed = claude_code.parse_session(root / "-home-user-webapp" / "abc123.jsonl")
    assert parsed is not None
    assert parsed.external_id == "abc123"
    assert parsed.title == "Fix flaky login test"
    assert parsed.model == "claude-sonnet-5"
    assert parsed.project == "/home/user/webapp"
    # tool_result-only user turn, progress line, and garbage line are skipped
    assert [m.role for m in parsed.messages] == ["user", "assistant", "assistant", "user"]
    assert parsed.messages[0].content == "The login test is flaky, can you fix it?"
    assert parsed.messages[0].external_id == "u-1"
    assert parsed.messages[0].created_at == "2026-07-01T10:00:00Z"
    assert parsed.messages[1].content == "Looking at the test now."


def test_parse_session_title_falls_back_to_first_user_message(tmp_path: Path) -> None:
    session = tmp_path / "s.jsonl"
    session.write_text(
        '{"type":"user","uuid":"u1","message":{"role":"user","content":"hello world"}}\n'
    )
    parsed = claude_code.parse_session(session)
    assert parsed is not None
    assert parsed.title == "hello world"


def test_parse_empty_session_returns_none(tmp_path: Path) -> None:
    session = tmp_path / "s.jsonl"
    session.write_text('{"type":"summary","summary":"nothing"}\n')
    assert claude_code.parse_session(session) is None
