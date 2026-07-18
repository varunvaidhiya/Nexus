"""Context injection: profile + relevant memory notes + relevant history,
packed to a token budget (approximated at 4 chars/token). Priority when over
budget: profile > notes > messages."""

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api.config import get_settings
from nexus_api.context.embeddings import embed_query, embedding_available
from nexus_api.context.search import hybrid_search
from nexus_api.db.models import MemoryNote, ProfileSnapshot

logger = structlog.get_logger()

_NOTES_LIMIT = 8
_MESSAGES_LIMIT = 6
_CHARS_PER_TOKEN = 4


@dataclass
class ContextBundle:
    text: str
    profile_used: bool
    notes_count: int
    messages_count: int


async def build_context(
    session: Session,
    query: str,
    *,
    exclude_conversation_id: uuid.UUID | None = None,
) -> ContextBundle | None:
    """Assemble the injection block, or None when there is nothing to inject."""
    budget_chars = get_settings().context_token_budget * _CHARS_PER_TOKEN

    profile = session.scalars(
        select(ProfileSnapshot).order_by(ProfileSnapshot.generated_at.desc())
    ).first()

    notes = await _relevant_notes(session, query)

    try:
        hits = await hybrid_search(
            session,
            query,
            limit=_MESSAGES_LIMIT,
            exclude_conversation_id=exclude_conversation_id,
        )
    except Exception:
        logger.exception("history retrieval failed; continuing without it")
        hits = []

    sections: list[str] = []
    if profile:
        sections.append(f"## Who the user is\n{profile.content}")
    if notes:
        notes_text = "\n".join(f"- {note.content}" for note in notes)
        sections.append(f"## Things known about the user\n{notes_text}")
    if hits:
        history = "\n".join(
            f"- [{hit.conversation_title or 'untitled'}] {hit.role}: {hit.snippet}" for hit in hits
        )
        sections.append(f"## Possibly relevant past conversations\n{history}")

    if not sections:
        return None

    header = (
        "The following is private context about the user, assembled from their "
        "cross-tool AI history. Use it when relevant; do not recite it back.\n\n"
    )
    body = header
    used_notes = used_messages = 0
    profile_used = False
    for index, section in enumerate(sections):
        if len(body) + len(section) > budget_chars and index > 0:
            break  # keep whole earlier (higher-priority) sections
        body += section + "\n\n"
        if section.startswith("## Who"):
            profile_used = True
        elif section.startswith("## Things"):
            used_notes = len(notes)
        else:
            used_messages = len(hits)
    body = body[:budget_chars].rstrip()

    return ContextBundle(
        text=body,
        profile_used=profile_used,
        notes_count=used_notes,
        messages_count=used_messages,
    )


async def _relevant_notes(session: Session, query: str) -> list[MemoryNote]:
    if embedding_available(session):
        try:
            qvec = await embed_query(session, query)
            from sqlalchemy import text as sql

            rows = session.execute(
                sql(
                    "SELECT id FROM memory_note WHERE embedding IS NOT NULL "
                    "ORDER BY embedding <=> CAST(:qvec AS vector) LIMIT :limit"
                ),
                {"qvec": str(qvec), "limit": _NOTES_LIMIT},
            ).all()
            if rows:
                ids = [row[0] for row in rows]
                notes = session.scalars(select(MemoryNote).where(MemoryNote.id.in_(ids))).all()
                order = {note_id: rank for rank, note_id in enumerate(ids)}
                return sorted(notes, key=lambda n: order[n.id])
        except Exception:
            logger.exception("note retrieval failed; using recency fallback")
    return list(
        session.scalars(
            select(MemoryNote).order_by(MemoryNote.updated_at.desc()).limit(_NOTES_LIMIT)
        ).all()
    )
