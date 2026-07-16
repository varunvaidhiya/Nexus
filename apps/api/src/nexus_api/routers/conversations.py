import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_api.db.models import Conversation, Message, Source, SourceKind
from nexus_api.db.session import get_session

router = APIRouter(prefix="/conversations", tags=["conversations"])

SessionDep = Annotated[Session, Depends(get_session)]


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str | None
    model: str | None
    source_kind: str
    started_at: datetime | None
    updated_at: datetime
    message_count: int


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    token_count: int | None
    created_at: datetime


class ConversationDetail(BaseModel):
    id: uuid.UUID
    title: str | None
    model: str | None
    source_kind: str
    updated_at: datetime
    messages: list[MessageOut]


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    session: SessionDep,
    source_kind: Annotated[SourceKind | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ConversationOut]:
    message_count = (
        select(func.count())
        .where(Message.conversation_id == Conversation.id)
        .correlate(Conversation)
        .scalar_subquery()
    )
    query = (
        select(Conversation, Source.kind, message_count)
        .join(Source, Conversation.source_id == Source.id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if source_kind is not None:
        query = query.where(Source.kind == source_kind)
    return [
        ConversationOut(
            id=conversation.id,
            title=conversation.title,
            model=conversation.model,
            source_kind=kind.value,
            started_at=conversation.started_at,
            updated_at=conversation.updated_at,
            message_count=count,
        )
        for conversation, kind, count in session.execute(query).all()
    ]


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: uuid.UUID, session: SessionDep) -> ConversationDetail:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="conversation not found")
    source = session.get(Source, conversation.source_id)
    messages = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)
    ).all()
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        model=conversation.model,
        source_kind=source.kind.value if source else "native",
        updated_at=conversation.updated_at,
        messages=[
            MessageOut(
                id=m.id,
                role=m.role.value,
                content=m.content,
                token_count=m.token_count,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )
