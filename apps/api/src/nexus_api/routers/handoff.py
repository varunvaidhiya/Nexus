"""POST /handoff — generate a context package for a target tool.

Mounted with device auth so the companion agent can fetch briefs with its
device token (spec §5.2/5.3).
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api.db.models import Conversation, Handoff, Task
from nexus_api.db.session import get_session
from nexus_api.services.handoff import TARGETS, build_brief, log_handoff

router = APIRouter(tags=["handoff"])

SessionDep = Annotated[Session, Depends(get_session)]


class HandoffIn(BaseModel):
    target: str
    task_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    instructions: str | None = Field(default=None, max_length=4000)


class HandoffOut(BaseModel):
    id: uuid.UUID
    target: str
    task_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    brief: str
    created_at: datetime


@router.post("/handoff", response_model=HandoffOut)
async def create_handoff(body: HandoffIn, session: SessionDep) -> HandoffOut:
    target = TARGETS.get(body.target)
    if target is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"unknown target (expected one of: {', '.join(sorted(TARGETS))})",
        )
    if body.task_id is None and body.conversation_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="task_id or conversation_id is required"
        )

    task = session.get(Task, body.task_id) if body.task_id else None
    if body.task_id and task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown task")
    conversation = session.get(Conversation, body.conversation_id) if body.conversation_id else None
    if body.conversation_id and conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown conversation")

    brief = await build_brief(
        session, target, task=task, conversation=conversation, instructions=body.instructions
    )
    handoff = log_handoff(
        session,
        target=target.key,
        task_id=body.task_id,
        conversation_id=body.conversation_id,
        brief=brief,
    )
    session.flush()
    session.refresh(handoff)
    return HandoffOut(
        id=handoff.id,
        target=handoff.target,
        task_id=handoff.task_id,
        conversation_id=handoff.conversation_id,
        brief=brief,
        created_at=handoff.created_at,
    )


class HandoffLogOut(BaseModel):
    id: uuid.UUID
    target: str
    task_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    note: str | None
    created_at: datetime


@router.get("/handoffs", response_model=list[HandoffLogOut])
def list_handoffs(session: SessionDep, limit: int = 20) -> list[HandoffLogOut]:
    rows = session.scalars(
        select(Handoff).order_by(Handoff.created_at.desc()).limit(min(max(limit, 1), 100))
    ).all()
    return [
        HandoffLogOut(
            id=row.id,
            target=row.target,
            task_id=row.task_id,
            conversation_id=row.conversation_id,
            note=row.note,
            created_at=row.created_at,
        )
        for row in rows
    ]
