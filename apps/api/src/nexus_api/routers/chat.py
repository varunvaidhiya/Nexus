"""Multi-provider streaming chat with Tier D auto-capture.

Persistence IS the write path: the user message is committed before the
provider call, and whatever assistant text arrives is committed afterwards —
including partial output when a stream fails or the client disconnects.

SSE protocol emitted to the client:
    event: meta   {conversation_id, user_message_id}
    event: delta  {text}
    event: done   {message_id, stop_reason, input_tokens, output_tokens,
                   cost_usd, spend_usd, monthly_budget_usd}
    event: error  {kind, provider, message, retryable}
Pre-flight failures (unknown provider, no key, budget exhausted) are plain
HTTP errors before any streaming starts.
"""

import json
import uuid
from collections.abc import AsyncIterator

import structlog
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from nexus_api.db.models import Conversation, Message, MessageRole, Source, SourceKind
from nexus_api.db.session import get_engine
from nexus_api.gateway import ChatMessage, Completion, GatewayError, TextDelta, stream_chat
from nexus_api.gateway.budget import check_budget, record_spend
from nexus_api.routers.providers import get_decrypted_key

logger = structlog.get_logger()

router = APIRouter(tags=["chat"])

MAX_TOKENS_CAP = 128_000


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1)
    max_tokens: int = Field(default=16_000, ge=1, le=MAX_TOKENS_CAP)
    # "with my full context": prepend profile + notes + relevant history.
    use_context: bool = False


def _session() -> Session:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)()


def _native_source(session: Session) -> Source:
    source = session.scalars(select(Source).where(Source.kind == SourceKind.native)).first()
    if source is None:
        source = Source(name="nexus", kind=SourceKind.native, ingest_tier="D")
        session.add(source)
        session.flush()
    return source


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _history(session: Session, conversation_id: uuid.UUID) -> list[ChatMessage]:
    rows = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)
    ).all()
    return [
        ChatMessage(role=row.role.value, content=row.content)
        for row in rows
        if row.role in (MessageRole.user, MessageRole.assistant) and row.content
    ]


@router.post("/chat")
async def chat(body: ChatRequest) -> StreamingResponse:
    session = _session()
    try:
        # Pre-flight: key + budget, as plain HTTP errors before the stream opens.
        try:
            key_row = check_budget(session, body.provider)
            api_key = get_decrypted_key(session, body.provider).get_secret_value()
        except GatewayError as exc:
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED
                if exc.kind == "budget"
                else status.HTTP_400_BAD_REQUEST,
                detail={"kind": exc.kind, "message": exc.message},
            ) from exc
        except LookupError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail={"kind": "auth", "message": str(exc)},
            ) from exc

        if body.conversation_id is not None:
            conversation = session.get(Conversation, body.conversation_id)
            if conversation is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="conversation not found")
        else:
            conversation = Conversation(
                source_id=_native_source(session).id,
                title=body.message[:80],
                model=body.model,
                tool="nexus",
            )
            session.add(conversation)
            session.flush()

        user_message = Message(
            conversation_id=conversation.id, role=MessageRole.user, content=body.message
        )
        session.add(user_message)
        conversation.model = body.model
        session.commit()  # user turn is captured even if the provider call fails

        history = _history(session, conversation.id)
        monthly_budget = key_row.monthly_budget_usd

        context = None
        if body.use_context:
            # Best-effort: a retrieval failure must not block the chat.
            try:
                from nexus_api.context.retrieval import build_context

                context = await build_context(
                    session, body.message, exclude_conversation_id=conversation.id
                )
            except Exception:
                logger.exception("context retrieval failed; sending clean")
    except HTTPException:
        session.close()
        raise
    except Exception:
        session.close()
        raise

    async def event_stream() -> AsyncIterator[str]:
        yield _sse(
            "meta",
            {
                "conversation_id": str(conversation.id),
                "user_message_id": str(user_message.id),
                "context": (
                    {
                        "profile": context.profile_used,
                        "notes": context.notes_count,
                        "messages": context.messages_count,
                        "text": context.text,
                    }
                    if context
                    else None
                ),
            },
        )
        parts: list[str] = []
        completion: Completion | None = None
        error: GatewayError | None = None
        try:
            async for event in stream_chat(
                body.provider,
                api_key=api_key,
                model=body.model,
                messages=history,
                system=context.text if context else None,
                max_tokens=body.max_tokens,
            ):
                if isinstance(event, TextDelta):
                    parts.append(event.text)
                    yield _sse("delta", {"text": event.text})
                elif isinstance(event, Completion):
                    completion = event
        except GatewayError as exc:
            error = exc
        finally:
            # Persist whatever arrived — full answers, partial output on
            # errors, and partial output on client disconnect alike.
            text = "".join(parts)
            try:
                message_id: str | None = None
                if text:
                    assistant = Message(
                        conversation_id=conversation.id,
                        role=MessageRole.assistant,
                        content=text,
                        token_count=completion.output_tokens if completion else None,
                    )
                    session.add(assistant)
                    session.flush()
                    message_id = str(assistant.id)
                cost = record_spend(
                    session,
                    body.provider,
                    body.model,
                    completion.input_tokens if completion else None,
                    completion.output_tokens if completion else None,
                )
                spend = session.get(type(key_row), key_row.id)
                session.commit()
            except Exception:
                session.rollback()
                logger.exception("failed to persist chat turn")
                raise
            finally:
                session.close()

        if error is not None:
            yield _sse(
                "error",
                {
                    "kind": error.kind,
                    "provider": error.provider,
                    "message": error.message,
                    "retryable": error.retryable,
                },
            )
        elif completion is not None:
            yield _sse(
                "done",
                {
                    "message_id": message_id,
                    "stop_reason": completion.stop_reason,
                    "input_tokens": completion.input_tokens,
                    "output_tokens": completion.output_tokens,
                    "cost_usd": str(cost),
                    "spend_usd": str(spend.spend_usd) if spend else None,
                    "monthly_budget_usd": str(monthly_budget) if monthly_budget else None,
                },
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )
