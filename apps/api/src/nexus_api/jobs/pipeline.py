"""The context-engine jobs: embed, summarize+distill, rebuild profile."""

from datetime import UTC, datetime

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from nexus_api.context.embeddings import embed_texts, embedding_available
from nexus_api.context.llm import complete, llm_available
from nexus_api.db.models import Conversation, MemoryNote, Message, ProfileSnapshot
from nexus_api.jobs.framework import SkipJob

logger = structlog.get_logger()

EMBED_BATCH_LIMIT = 256
SUMMARIZE_LIMIT = 20
TRANSCRIPT_CHAR_LIMIT = 8000

_SUMMARIZE_PROMPT = """\
You maintain a personal memory system. Below is a conversation transcript.

Return ONLY a JSON object with:
  "summary": 2-3 sentences describing what the conversation was about and any outcome.
  "facts": an array (possibly empty) of durable facts about the user worth
    remembering long-term (preferences, active projects, tools, decisions).
    Each fact: {"content": str, "category": str, "confidence": 0.0-1.0}.
    Only include facts that will still matter in a month; no small talk.

Transcript:
__TRANSCRIPT__
"""

_PROFILE_PROMPT = """\
You maintain a compact rolling profile of a person based on their AI chat
history. Write a concise document (under 300 words) with sections:
"Active projects", "Preferences & tools", "Open loops". Base it ONLY on the
data below; omit sections with no data.

Known facts:
__FACTS__

Recent conversations:
__CONVERSATIONS__
"""


async def embed_pending(session: Session) -> str:
    if not embedding_available(session):
        raise SkipJob("no API key for the embedding provider")
    rows = session.scalars(
        select(Message)
        .where(Message.embedding.is_(None), func.length(Message.content) > 0)
        .order_by(Message.created_at)
        .limit(EMBED_BATCH_LIMIT)
    ).all()
    if not rows:
        return "nothing to embed"
    vectors = await embed_texts(session, [row.content[:6000] for row in rows])
    for row, vector in zip(rows, vectors, strict=True):
        row.embedding = vector
    session.commit()
    return f"embedded {len(rows)} messages"


async def summarize_pending(session: Session) -> str:
    """Summarize updated conversations and distill durable facts (one LLM
    call per conversation covers both)."""
    if not llm_available(session):
        raise SkipJob("no API key for the summary provider")
    conversations = session.scalars(
        select(Conversation)
        .where(
            or_(
                Conversation.summarized_at.is_(None),
                Conversation.updated_at > Conversation.summarized_at,
            )
        )
        .order_by(Conversation.updated_at)
        .limit(SUMMARIZE_LIMIT)
    ).all()
    if not conversations:
        return "nothing to summarize"

    summarized = 0
    new_facts = 0
    for conversation in conversations:
        messages = session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at, Message.id)
        ).all()
        transcript = "\n".join(f"{m.role.value}: {m.content}" for m in messages)
        if len(transcript) < 40:  # too little signal; mark done and move on
            conversation.summarized_at = datetime.now(UTC)
            continue
        raw = await complete(
            session,
            _SUMMARIZE_PROMPT.replace("__TRANSCRIPT__", transcript[:TRANSCRIPT_CHAR_LIMIT]),
        )
        payload = _parse_summary(raw)
        if payload is None:
            logger.warning("unparseable summary output", conversation=str(conversation.id))
            continue
        summary, facts = payload
        conversation.summary = summary
        conversation.summarized_at = datetime.now(UTC)
        summarized += 1
        new_facts += _upsert_facts(session, facts, source_ref=str(conversation.id))
        session.commit()
    return f"summarized {summarized} conversations, {new_facts} new facts"


def _parse_summary(raw: str) -> tuple[str, list[dict[str, object]]] | None:
    import json
    import re

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary:
        return None
    facts = data.get("facts")
    return summary, [f for f in facts if isinstance(f, dict)] if isinstance(facts, list) else []


def _upsert_facts(session: Session, facts: list[dict[str, object]], *, source_ref: str) -> int:
    added = 0
    for fact in facts:
        content = fact.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        content = content.strip()
        exists = session.scalars(
            select(MemoryNote).where(func.lower(MemoryNote.content) == content.lower())
        ).first()
        if exists:
            continue
        confidence = fact.get("confidence")
        session.add(
            MemoryNote(
                content=content,
                category=str(fact.get("category") or "general")[:200],
                confidence=float(confidence) if isinstance(confidence, int | float) else None,
                source_ref=source_ref,
            )
        )
        added += 1
    return added


async def embed_notes(session: Session) -> str:
    if not embedding_available(session):
        raise SkipJob("no API key for the embedding provider")
    rows = session.scalars(
        select(MemoryNote).where(MemoryNote.embedding.is_(None)).limit(EMBED_BATCH_LIMIT)
    ).all()
    if not rows:
        return "nothing to embed"
    vectors = await embed_texts(session, [row.content for row in rows])
    for row, vector in zip(rows, vectors, strict=True):
        row.embedding = vector
    session.commit()
    return f"embedded {len(rows)} notes"


async def rebuild_profile(session: Session) -> str:
    if not llm_available(session):
        raise SkipJob("no API key for the summary provider")

    latest_snapshot = session.scalars(
        select(ProfileSnapshot).order_by(ProfileSnapshot.generated_at.desc())
    ).first()
    latest_activity = session.execute(select(func.max(Conversation.summarized_at))).scalar()
    if latest_activity is None:
        raise SkipJob("no summarized conversations yet")
    if latest_snapshot is not None and latest_snapshot.generated_at >= latest_activity:
        raise SkipJob("profile already up to date")

    notes = session.scalars(
        select(MemoryNote).order_by(MemoryNote.updated_at.desc()).limit(40)
    ).all()
    conversations = session.scalars(
        select(Conversation)
        .where(Conversation.summary.is_not(None))
        .order_by(Conversation.updated_at.desc())
        .limit(15)
    ).all()

    facts_text = "\n".join(f"- [{n.category}] {n.content}" for n in notes) or "(none)"
    conversations_text = (
        "\n".join(f"- {c.title or 'untitled'}: {c.summary}" for c in conversations) or "(none)"
    )
    content = await complete(
        session,
        _PROFILE_PROMPT.replace("__FACTS__", facts_text).replace(
            "__CONVERSATIONS__", conversations_text
        ),
    )
    if not content:
        raise SkipJob("profile model returned nothing")
    session.add(ProfileSnapshot(content=content, token_count=len(content) // 4))
    session.commit()
    return f"profile rebuilt from {len(notes)} notes and {len(conversations)} conversations"
