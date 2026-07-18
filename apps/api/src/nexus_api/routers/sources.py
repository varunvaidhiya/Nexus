"""Sources dashboard, export import, and on-demand sync."""

import asyncio
import uuid
from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_api.db.models import Conversation, Message, Source
from nexus_api.db.session import get_session
from nexus_api.services.importers import ImportError_, parse_export
from nexus_api.services.ingest import ingest_batch

logger = structlog.get_logger()

router = APIRouter(tags=["sources"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_IMPORT_BYTES = 200 * 1024 * 1024


class SourceOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    ingest_tier: str
    last_synced_at: datetime | None
    conversation_count: int
    message_count: int


@router.get("/sources", response_model=list[SourceOut])
def list_sources(session: SessionDep) -> list[SourceOut]:
    conversation_count = (
        select(func.count())
        .where(Conversation.source_id == Source.id)
        .correlate(Source)
        .scalar_subquery()
    )
    message_count = (
        select(func.count())
        .select_from(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Conversation.source_id == Source.id)
        .correlate(Source)
        .scalar_subquery()
    )
    rows = session.execute(
        select(Source, conversation_count, message_count).order_by(Source.kind, Source.name)
    ).all()
    return [
        SourceOut(
            id=source.id,
            name=source.name,
            kind=source.kind.value,
            ingest_tier=source.ingest_tier,
            last_synced_at=source.last_synced_at,
            conversation_count=conversations,
            message_count=messages,
        )
        for source, conversations, messages in rows
    ]


class ImportReportOut(BaseModel):
    source_kind: str
    conversations: int
    new_conversations: int
    new_messages: int
    skipped_messages: int


@router.post("/import", response_model=ImportReportOut)
async def import_export(file: UploadFile, session: SessionDep) -> ImportReportOut:
    data = await file.read(MAX_IMPORT_BYTES + 1)
    if len(data) > MAX_IMPORT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="export too large")
    try:
        batch = parse_export(file.filename or "export.json", data)
    except ImportError_ as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    report = ingest_batch(session, batch)
    return ImportReportOut(source_kind=batch.source.kind.value, **report.__dict__)


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_now() -> dict[str, str]:
    """Kick one pass of the context-engine jobs immediately (embeddings,
    summaries, profile) instead of waiting for the worker interval."""
    from nexus_api.worker import run_all

    task = asyncio.create_task(run_all())
    task.add_done_callback(
        lambda t: (
            logger.error("sync pass failed", error=str(t.exception()))
            if not t.cancelled() and t.exception()
            else None
        )
    )
    return {"status": "sync started"}
