"""Pydantic binding of ingest.v1.schema.json — keep in lockstep with that file.

The JSON Schema is the source of truth; tests validate shared fixtures against
both to catch drift.
"""

from datetime import datetime
from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION: Final = "nexus.ingest.v1"


class SourceKind(StrEnum):
    claude_code = "claude_code"
    cursor = "cursor"
    codex = "codex"
    opencode = "opencode"
    droid = "droid"
    chatgpt = "chatgpt"
    gemini = "gemini"
    claude_web = "claude_web"
    deepseek = "deepseek"
    minimax = "minimax"
    qwen = "qwen"
    native = "native"
    import_ = "import"


class IngestTier(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class MessageRole(StrEnum):
    user = "user"
    assistant = "assistant"
    tool = "tool"
    system = "system"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IngestSource(_StrictModel):
    kind: SourceKind
    name: str | None = Field(default=None, max_length=200)
    ingest_tier: IngestTier


class IngestMessage(_StrictModel):
    external_id: str | None = Field(default=None, max_length=500)
    role: MessageRole
    content: str
    token_count: int | None = Field(default=None, ge=0)
    created_at: datetime | None = None


class IngestConversation(_StrictModel):
    external_id: str = Field(min_length=1, max_length=500)
    title: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    tool: str | None = Field(default=None, max_length=200)
    project: str | None = None
    started_at: datetime | None = None
    updated_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    messages: list[IngestMessage]


class IngestBatch(_StrictModel):
    schema_version: Literal["nexus.ingest.v1"] = SCHEMA_VERSION
    source: IngestSource
    conversations: list[IngestConversation]
