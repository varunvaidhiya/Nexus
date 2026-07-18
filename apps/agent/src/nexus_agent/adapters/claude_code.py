"""Claude Code session adapter (Tier A).

Reads `~/.claude/projects/<project-dir>/<session-id>.jsonl` transcripts —
read-only, tolerant of unknown line types, and incremental via per-file
mtime tracking. Formats drift across versions, so anything unrecognized is
skipped rather than fatal.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path("~/.claude/projects")

TOOL_NAME = "claude_code"


@dataclass
class ParsedMessage:
    external_id: str | None
    role: str
    content: str
    created_at: str | None


@dataclass
class ParsedConversation:
    external_id: str
    title: str | None
    model: str | None
    project: str | None
    messages: list[ParsedMessage]
    mtime: float
    path: Path


def discover_sessions(root: Path | None = None) -> Iterator[Path]:
    base = (root or DEFAULT_ROOT).expanduser()
    if not base.exists():
        return
    yield from sorted(base.glob("*/*.jsonl"))


def parse_session(path: Path) -> ParsedConversation | None:
    messages: list[ParsedMessage] = []
    model: str | None = None
    summary: str | None = None
    cwd: str | None = None
    try:
        raw_lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return None

    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        kind = entry.get("type")
        if kind == "summary" and isinstance(entry.get("summary"), str):
            summary = entry["summary"]
            continue
        if kind not in ("user", "assistant"):
            continue
        payload = entry.get("message")
        if not isinstance(payload, dict):
            continue
        role = payload.get("role") or kind
        if role not in ("user", "assistant"):
            continue
        text = _content_text(payload.get("content"))
        if not text.strip():
            continue
        if payload.get("model"):
            model = payload["model"]
        if entry.get("cwd"):
            cwd = entry["cwd"]
        messages.append(
            ParsedMessage(
                external_id=entry.get("uuid"),
                role=role,
                content=text,
                created_at=entry.get("timestamp"),
            )
        )

    if not messages:
        return None
    first_user = next((m.content for m in messages if m.role == "user"), None)
    return ParsedConversation(
        external_id=path.stem,
        title=summary or (first_user[:80] if first_user else None),
        model=model,
        project=cwd,
        messages=messages,
        mtime=path.stat().st_mtime,
        path=path,
    )


def _content_text(content: object) -> str:
    """Claude Code content is a string or a list of typed blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return ""
