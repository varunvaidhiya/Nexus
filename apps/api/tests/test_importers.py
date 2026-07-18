"""Export-parser unit tests — no database needed."""

import io
import json
import zipfile
from pathlib import Path

import pytest

from nexus_api.services.importers import ImportError_, parse_export

FIXTURES = Path(__file__).parent / "fixtures"


def test_chatgpt_export() -> None:
    batch = parse_export("conversations.json", (FIXTURES / "chatgpt-export.json").read_bytes())
    assert batch.source.kind.value == "chatgpt"
    assert batch.source.ingest_tier.value == "C"
    assert len(batch.conversations) == 2

    first = batch.conversations[0]
    assert first.external_id == "cgpt-conv-1"
    assert first.title == "Explain monads"
    assert first.model == "gpt-5"
    assert first.started_at is not None and first.started_at.year == 2025
    # Blank system part is dropped; user + assistant survive in time order.
    assert [(m.role.value, m.external_id) for m in first.messages] == [
        ("user", "msg-u1"),
        ("assistant", "msg-a1"),
    ]
    assert first.messages[0].content == "What is a monad?"

    assert batch.conversations[1].messages == []


def test_claude_export() -> None:
    batch = parse_export("conversations.json", (FIXTURES / "claude-export.json").read_bytes())
    assert batch.source.kind.value == "claude_web"
    (conversation,) = batch.conversations
    assert conversation.external_id == "claude-conv-1"
    assert conversation.title == "Trip planning"
    assert [m.role.value for m in conversation.messages] == ["user", "assistant", "user"]
    # Assistant text pulled from content blocks when top-level text is empty.
    assert conversation.messages[1].content == "Sure — how many days do you have?"


def test_zip_export() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "export/conversations.json", (FIXTURES / "claude-export.json").read_bytes()
        )
        archive.writestr("export/users.json", b"[]")
    batch = parse_export("data-2026-06-01.zip", buffer.getvalue())
    assert batch.source.kind.value == "claude_web"


def test_zip_without_conversations_json() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", b"hi")
    with pytest.raises(ImportError_, match="no conversations.json"):
        parse_export("export.zip", buffer.getvalue())


def test_invalid_zip() -> None:
    with pytest.raises(ImportError_, match="valid ZIP"):
        parse_export("export.zip", b"definitely not a zip")


def test_not_json() -> None:
    with pytest.raises(ImportError_, match="not valid JSON"):
        parse_export("conversations.json", b"{oops")


def test_wrong_shape() -> None:
    with pytest.raises(ImportError_, match="JSON array"):
        parse_export("conversations.json", b"{}")


def test_empty_export() -> None:
    with pytest.raises(ImportError_, match="no conversations"):
        parse_export("conversations.json", b"[]")


def test_unrecognized_format() -> None:
    payload = json.dumps([{"something": "else"}]).encode()
    with pytest.raises(ImportError_, match="unrecognized"):
        parse_export("conversations.json", payload)
