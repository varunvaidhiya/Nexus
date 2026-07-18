"""Official-export parsers (Tier C) → canonical ingest batches.

Supported today: ChatGPT (`conversations.json`, mapping-tree format) and
Claude.ai (`conversations.json`, chat_messages format), as bare JSON or
inside the official export ZIP. Each parser is small and fixture-tested,
because vendor formats drift (spec §15).
"""

import io
import json
import zipfile
from datetime import UTC, datetime
from typing import Any

from nexus_schema import (
    IngestBatch,
    IngestConversation,
    IngestMessage,
    IngestSource,
    IngestTier,
    MessageRole,
    SourceKind,
)


class ImportError_(Exception):
    """Unrecognized or malformed export payload; message is user-facing."""


def parse_export(filename: str, data: bytes) -> IngestBatch:
    if filename.lower().endswith(".zip"):
        data = _extract_conversations_json(data)
    try:
        payload = json.loads(data)
    except ValueError as exc:
        raise ImportError_("file is not valid JSON") from exc
    if not isinstance(payload, list):
        raise ImportError_("expected a JSON array of conversations")
    if not payload:
        raise ImportError_("export contains no conversations")

    first = payload[0]
    if isinstance(first, dict) and "mapping" in first:
        return _parse_chatgpt(payload)
    if isinstance(first, dict) and "chat_messages" in first:
        return _parse_claude(payload)
    raise ImportError_("unrecognized export format (expected ChatGPT or Claude export)")


def _extract_conversations_json(data: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                if name.split("/")[-1] == "conversations.json":
                    return archive.read(name)
    except zipfile.BadZipFile as exc:
        raise ImportError_("file is not a valid ZIP archive") from exc
    raise ImportError_("no conversations.json found in the ZIP")


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


# --- ChatGPT: conversations.json with a "mapping" node tree ---


def _parse_chatgpt(payload: list[dict[str, Any]]) -> IngestBatch:
    conversations = []
    for raw in payload:
        mapping = raw.get("mapping") or {}
        messages = []
        nodes = sorted(
            (node.get("message") for node in mapping.values() if node.get("message")),
            key=lambda m: m.get("create_time") or 0,
        )
        for node in nodes:
            role = (node.get("author") or {}).get("role")
            if role not in ("user", "assistant", "system", "tool"):
                continue
            content = node.get("content") or {}
            parts = content.get("parts") if isinstance(content, dict) else None
            text = "\n".join(p for p in parts if isinstance(p, str)) if parts else ""
            if not text.strip():
                continue
            messages.append(
                IngestMessage(
                    external_id=node.get("id"),
                    role=MessageRole(role),
                    content=text,
                    created_at=_timestamp(node.get("create_time")),
                )
            )
        external_id = raw.get("conversation_id") or raw.get("id")
        if not external_id:
            continue
        conversations.append(
            IngestConversation(
                external_id=str(external_id),
                title=raw.get("title"),
                model=raw.get("default_model_slug"),
                started_at=_timestamp(raw.get("create_time")),
                updated_at=_timestamp(raw.get("update_time")),
                messages=messages,
            )
        )
    return IngestBatch(
        source=IngestSource(
            kind=SourceKind.chatgpt, name="chatgpt-export", ingest_tier=IngestTier.C
        ),
        conversations=conversations,
    )


# --- Claude.ai: conversations.json with "chat_messages" ---


def _parse_claude(payload: list[dict[str, Any]]) -> IngestBatch:
    conversations = []
    for raw in payload:
        messages = []
        for entry in raw.get("chat_messages") or []:
            sender = entry.get("sender")
            role = {"human": "user", "assistant": "assistant"}.get(sender)
            text = entry.get("text") or ""
            if not text and isinstance(entry.get("content"), list):
                text = "\n".join(
                    block.get("text", "")
                    for block in entry["content"]
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            if role is None or not text.strip():
                continue
            messages.append(
                IngestMessage(
                    external_id=entry.get("uuid"),
                    role=MessageRole(role),
                    content=text,
                    created_at=_timestamp(entry.get("created_at")),
                )
            )
        external_id = raw.get("uuid")
        if not external_id:
            continue
        conversations.append(
            IngestConversation(
                external_id=str(external_id),
                title=raw.get("name") or None,
                started_at=_timestamp(raw.get("created_at")),
                updated_at=_timestamp(raw.get("updated_at")),
                messages=messages,
            )
        )
    return IngestBatch(
        source=IngestSource(
            kind=SourceKind.claude_web, name="claude-export", ingest_tier=IngestTier.C
        ),
        conversations=conversations,
    )
