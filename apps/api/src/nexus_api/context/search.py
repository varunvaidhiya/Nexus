"""Hybrid search: Postgres full-text + pgvector similarity, merged with
reciprocal rank fusion. Falls back to keyword-only when embeddings are
unavailable."""

import uuid
from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import text as sql
from sqlalchemy.orm import Session

from nexus_api.context.embeddings import embed_query, embedding_available

logger = structlog.get_logger()

_CANDIDATES = 30
_RRF_K = 60


@dataclass
class SearchHit:
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    conversation_title: str | None
    role: str
    snippet: str
    created_at: datetime
    score: float
    matched: str  # "keyword" | "vector" | "both"


_KEYWORD_SQL = sql(
    """
    SELECT m.id FROM message m
    WHERE to_tsvector('english', m.content) @@ plainto_tsquery('english', :q)
    ORDER BY ts_rank(to_tsvector('english', m.content),
                     plainto_tsquery('english', :q)) DESC
    LIMIT :limit
    """
)

_VECTOR_SQL = sql(
    """
    SELECT m.id FROM message m
    WHERE m.embedding IS NOT NULL
    ORDER BY m.embedding <=> CAST(:qvec AS vector)
    LIMIT :limit
    """
)

_HYDRATE_SQL = sql(
    """
    SELECT m.id, m.conversation_id, c.title, m.role, m.content, m.created_at
    FROM message m JOIN conversation c ON c.id = m.conversation_id
    WHERE m.id = ANY(:ids)
    """
)


async def hybrid_search(
    session: Session,
    query: str,
    *,
    limit: int = 10,
    exclude_conversation_id: uuid.UUID | None = None,
) -> list[SearchHit]:
    keyword_ids = [
        row[0] for row in session.execute(_KEYWORD_SQL, {"q": query, "limit": _CANDIDATES}).all()
    ]

    vector_ids: list[uuid.UUID] = []
    if embedding_available(session):
        try:
            qvec = await embed_query(session, query)
            vector_ids = [
                row[0]
                for row in session.execute(
                    _VECTOR_SQL, {"qvec": str(qvec), "limit": _CANDIDATES}
                ).all()
            ]
        except Exception:
            # Semantic half is best-effort; keyword results still stand.
            logger.exception("vector search failed; falling back to keyword only")

    # Reciprocal rank fusion across both lists.
    scores: dict[uuid.UUID, float] = {}
    matched: dict[uuid.UUID, set[str]] = {}
    for kind, ids in (("keyword", keyword_ids), ("vector", vector_ids)):
        for rank, message_id in enumerate(ids):
            scores[message_id] = scores.get(message_id, 0.0) + 1.0 / (_RRF_K + rank + 1)
            matched.setdefault(message_id, set()).add(kind)

    if not scores:
        return []

    rows = session.execute(_HYDRATE_SQL, {"ids": list(scores)}).all()
    hits = []
    for message_id, conversation_id, title, role, content, created_at in rows:
        if exclude_conversation_id and conversation_id == exclude_conversation_id:
            continue
        kinds = matched[message_id]
        hits.append(
            SearchHit(
                message_id=message_id,
                conversation_id=conversation_id,
                conversation_title=title,
                role=role,
                snippet=content[:400],
                created_at=created_at,
                score=scores[message_id],
                matched="both" if len(kinds) == 2 else next(iter(kinds)),
            )
        )
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[:limit]
