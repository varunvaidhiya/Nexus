"""Canonical data model from docs/SPEC.md §4."""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    LargeBinary,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus_api.db.base import Base

EMBEDDING_DIM = 1536


class SourceKind(enum.Enum):
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


class MessageRole(enum.Enum):
    user = "user"
    assistant = "assistant"
    tool = "tool"
    system = "system"


class EntityKind(enum.Enum):
    project = "project"
    person = "person"
    repo = "repo"
    topic = "topic"
    decision = "decision"


class TaskStatus(enum.Enum):
    todo = "todo"
    doing = "doing"
    blocked = "blocked"
    done = "done"


class GoalHorizon(enum.Enum):
    day = "day"
    week = "week"
    month = "month"
    quarter = "quarter"


class GoalStatus(enum.Enum):
    active = "active"
    paused = "paused"
    achieved = "achieved"
    dropped = "dropped"


def _enum(kind: type[enum.Enum], name: str) -> Enum:
    # values_callable stores the enum *values* (e.g. "import") in Postgres,
    # not the Python member names (e.g. "import_").
    return Enum(kind, name=name, values_callable=lambda e: [m.value for m in e])


class Source(Base):
    __tablename__ = "source"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[SourceKind] = mapped_column(_enum(SourceKind, "source_kind"))
    ingest_tier: Mapped[str] = mapped_column(String(1))
    auth_meta: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    last_synced_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="source")

    __table_args__ = (CheckConstraint("ingest_tier IN ('A','B','C','D')", name="ingest_tier"),)


class Conversation(Base):
    __tablename__ = "conversation"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"))
    external_id: Mapped[str | None] = mapped_column(String(500))
    title: Mapped[str | None] = mapped_column(String(500))
    model: Mapped[str | None] = mapped_column(String(200))
    tool: Mapped[str | None] = mapped_column(String(200))
    project: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    summary: Mapped[str | None] = mapped_column(Text)
    # When the summary/distillation pipeline last processed this conversation;
    # NULL or older than updated_at means it needs (re)processing.
    summarized_at: Mapped[datetime | None]

    source: Mapped[Source] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_conversation_source_id_updated_at", "source_id", "updated_at"),
        Index("ix_conversation_tags", "tags", postgresql_using="gin"),
        Index("uq_conversation_source_external", "source_id", "external_id", unique=True),
    )


class Message(Base):
    __tablename__ = "message"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE")
    )
    role: Mapped[MessageRole] = mapped_column(_enum(MessageRole, "message_role"))
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_message_conversation_id", "conversation_id"),
        Index(
            "ix_message_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class Entity(Base):
    __tablename__ = "entity"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    kind: Mapped[EntityKind] = mapped_column(_enum(EntityKind, "entity_kind"))
    name: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    first_seen: Mapped[datetime] = mapped_column(server_default=text("now()"))
    last_seen: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        Index("uq_entity_kind_name", "kind", "name", unique=True),
        Index(
            "ix_entity_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class ConversationEntity(Base):
    __tablename__ = "conversation_entity"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"), primary_key=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entity.id", ondelete="CASCADE"), primary_key=True
    )


class Task(Base):
    __tablename__ = "task"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str] = mapped_column(String(500))
    detail: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(
        _enum(TaskStatus, "task_status"), server_default="todo"
    )
    priority: Mapped[int] = mapped_column(server_default=text("0"))
    due_at: Mapped[datetime | None]
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversation.id", ondelete="SET NULL")
    )
    why_it_matters: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    completed_at: Mapped[datetime | None]

    __table_args__ = (Index("ix_task_status_due_at", "status", "due_at"),)


class Goal(Base):
    __tablename__ = "goal"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str] = mapped_column(String(500))
    horizon: Mapped[GoalHorizon] = mapped_column(_enum(GoalHorizon, "goal_horizon"))
    progress: Mapped[float] = mapped_column(server_default=text("0"))
    status: Mapped[GoalStatus] = mapped_column(
        _enum(GoalStatus, "goal_status"), server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    target_at: Mapped[datetime | None]


class GoalTask(Base):
    __tablename__ = "goal_task"

    goal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("goal.id", ondelete="CASCADE"), primary_key=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task.id", ondelete="CASCADE"), primary_key=True
    )


class MemoryNote(Base):
    __tablename__ = "memory_note"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(200))
    confidence: Mapped[float | None]
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    source_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        Index(
            "ix_memory_note_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class ProviderKey(Base):
    __tablename__ = "provider_key"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    provider: Mapped[str] = mapped_column(String(100), unique=True)
    encrypted_key: Mapped[bytes] = mapped_column(LargeBinary)
    models: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    monthly_budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    spend_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), server_default=text("0"))
    # First day of the month spend_usd belongs to; spend resets on rollover.
    spend_month: Mapped[date | None]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class JobStatus(enum.Enum):
    running = "running"
    success = "success"
    error = "error"
    skipped = "skipped"


class JobRun(Base):
    """Bookkeeping for background jobs (embed/summarize/distill/profile)."""

    __tablename__ = "job_run"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), server_default="running"
    )
    detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    finished_at: Mapped[datetime | None]

    __table_args__ = (Index("ix_job_run_name_started_at", "name", "started_at"),)


class ProfileSnapshot(Base):
    __tablename__ = "profile_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    content: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    token_count: Mapped[int | None]
