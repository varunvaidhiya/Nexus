"""Assistant-layer jobs: task extraction, loose-end detection, weekly review.

All three follow the pipeline conventions: idempotent, bookkeeping timestamps
on the conversation row (re-run only when updated_at moves past them), and
SkipJob when no LLM key is configured.
"""

import json
import re
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from nexus_api.context.llm import complete, llm_available
from nexus_api.db.models import (
    Conversation,
    Message,
    Review,
    Suggestion,
    Task,
    TaskStatus,
)
from nexus_api.jobs.framework import SkipJob

logger = structlog.get_logger()

EXTRACT_LIMIT = 10
LOOSE_END_LIMIT = 10
CONFIDENCE_THRESHOLD = 0.6
TRANSCRIPT_CHAR_LIMIT = 6000
# Quiet window before a conversation can count as a loose end, and the horizon
# beyond which old threads are ancient history rather than loose ends.
LOOSE_END_MIN_AGE = timedelta(days=3)
LOOSE_END_MAX_AGE = timedelta(days=30)
REVIEW_PERIOD = timedelta(days=7)

_EXTRACT_PROMPT = """\
You extract actionable tasks from a person's AI conversations for their
personal task list.

Conversation summary:
__SUMMARY__

End of the transcript:
__TRANSCRIPT__

Their existing open tasks (do NOT re-extract anything already covered):
__OPEN_TASKS__

Return ONLY a JSON object: {"tasks": [...]}. Each task:
  {"title": str (imperative, <=100 chars),
   "detail": str or null,
   "priority": 0-3 (0 normal, 3 urgent),
   "due_at": ISO 8601 datetime or null (only if a real deadline was stated),
   "why_it_matters": one sentence tying it to their goals/context,
   "confidence": 0.0-1.0 (how clearly this is a real, still-open task)}
Only tasks the person still needs to do — not things already done in the
conversation, not things the assistant did for them. Empty array is a fine
answer; most conversations contain no new tasks.
"""

_LOOSE_END_PROMPT = """\
You spot abandoned work. Below is a summary and the final messages of a
conversation that has had no follow-up activity for days.

Summary:
__SUMMARY__

Final messages:
__TAIL__

Was this conversation left unfinished mid-task (work clearly planned or in
progress that never concluded)? Ordinary finished conversations, answered
questions, and idle chat are NOT loose ends.

Return ONLY JSON: {"loose_end": true/false, "reason": str}. The reason should
be one sentence addressed to the person, e.g. "You were mid-way through
debugging the login flow and never picked it back up."
"""

_REVIEW_PROMPT = """\
Write a weekly review for the period __START__ to __END__ based on this
person's AI activity across all their tools. Markdown, warm but factual,
under 400 words. Sections: "## What you worked on" (grouped by project/area),
"## Finished" (completed tasks), "## Still open" (open tasks and loose ends).
Base it ONLY on the data below; no invention. If a section has no data, omit it.

Conversations this week (source · project · title · summary):
__CONVERSATIONS__

Tasks completed this week:
__DONE_TASKS__

Open tasks:
__OPEN_TASKS__
"""


def _parse_json(raw: str) -> dict[str, object] | None:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _parse_due(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _tail_transcript(session: Session, conversation_id: object, limit: int = 8) -> str:
    rows = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    ).all()
    return "\n".join(f"{m.role.value}: {m.content[:800]}" for m in reversed(rows))


async def extract_tasks(session: Session) -> str:
    if not llm_available(session):
        raise SkipJob("no API key for the extraction provider")
    conversations = session.scalars(
        select(Conversation)
        .where(
            Conversation.summary.is_not(None),
            or_(
                Conversation.tasks_extracted_at.is_(None),
                Conversation.updated_at > Conversation.tasks_extracted_at,
            ),
        )
        .order_by(Conversation.updated_at)
        .limit(EXTRACT_LIMIT)
    ).all()
    if not conversations:
        return "nothing to extract from"

    open_tasks = session.scalars(
        select(Task)
        .where(Task.status != TaskStatus.done)
        .order_by(Task.created_at.desc())
        .limit(30)
    ).all()
    open_titles = {t.title.strip().lower() for t in open_tasks}
    open_tasks_text = "\n".join(f"- {t.title}" for t in open_tasks) or "(none)"

    extracted = 0
    for conversation in conversations:
        prompt = (
            _EXTRACT_PROMPT.replace("__SUMMARY__", conversation.summary or "")
            .replace(
                "__TRANSCRIPT__",
                _tail_transcript(session, conversation.id)[:TRANSCRIPT_CHAR_LIMIT],
            )
            .replace("__OPEN_TASKS__", open_tasks_text)
        )
        payload = _parse_json(await complete(session, prompt))
        if payload is None:
            logger.warning("unparseable extraction output", conversation=str(conversation.id))
            continue
        raw_tasks = payload.get("tasks")
        for raw in raw_tasks if isinstance(raw_tasks, list) else []:
            if not isinstance(raw, dict):
                continue
            title = raw.get("title")
            confidence = raw.get("confidence")
            if not isinstance(title, str) or not title.strip():
                continue
            if not isinstance(confidence, int | float) or confidence < CONFIDENCE_THRESHOLD:
                continue
            title = title.strip()[:500]
            if title.lower() in open_titles:
                continue  # near-duplicate of an existing open task
            priority = raw.get("priority")
            session.add(
                Task(
                    title=title,
                    detail=str(raw["detail"])[:2000] if raw.get("detail") else None,
                    priority=min(max(int(priority), 0), 3)
                    if isinstance(priority, int | float)
                    else 0,
                    due_at=_parse_due(raw.get("due_at")),
                    why_it_matters=str(raw["why_it_matters"])[:1000]
                    if raw.get("why_it_matters")
                    else None,
                    source_conversation_id=conversation.id,
                )
            )
            open_titles.add(title.lower())
            extracted += 1
        conversation.tasks_extracted_at = datetime.now(UTC)
        session.commit()
    return f"extracted {extracted} tasks from {len(conversations)} conversations"


async def detect_loose_ends(session: Session) -> str:
    if not llm_available(session):
        raise SkipJob("no API key for the loose-end provider")
    now = datetime.now(UTC)
    conversations = session.scalars(
        select(Conversation)
        .where(
            Conversation.summary.is_not(None),
            Conversation.updated_at < now - LOOSE_END_MIN_AGE,
            Conversation.updated_at > now - LOOSE_END_MAX_AGE,
            or_(
                Conversation.loose_end_checked_at.is_(None),
                Conversation.updated_at > Conversation.loose_end_checked_at,
            ),
            # One suggestion per conversation, ever — a dismissed row is
            # permanent feedback, so exclude anything already raised.
            ~select(Suggestion.id).where(Suggestion.conversation_id == Conversation.id).exists(),
            # A conversation with an open extracted task is already tracked.
            ~select(Task.id)
            .where(
                Task.source_conversation_id == Conversation.id,
                Task.status != TaskStatus.done,
            )
            .exists(),
        )
        .order_by(Conversation.updated_at)
        .limit(LOOSE_END_LIMIT)
    ).all()
    if not conversations:
        return "nothing to check"

    found = 0
    for conversation in conversations:
        prompt = _LOOSE_END_PROMPT.replace("__SUMMARY__", conversation.summary or "").replace(
            "__TAIL__", _tail_transcript(session, conversation.id, limit=4)
        )
        payload = _parse_json(await complete(session, prompt))
        if payload is None:
            logger.warning("unparseable loose-end output", conversation=str(conversation.id))
            continue
        if payload.get("loose_end") is True and isinstance(payload.get("reason"), str):
            session.add(
                Suggestion(
                    conversation_id=conversation.id,
                    reason=str(payload["reason"])[:1000],
                )
            )
            found += 1
        conversation.loose_end_checked_at = datetime.now(UTC)
        session.commit()
    return f"checked {len(conversations)} conversations, {found} loose ends"


async def weekly_review(session: Session) -> str:
    if not llm_available(session):
        raise SkipJob("no API key for the review provider")
    today = datetime.now(UTC).date()
    latest = session.execute(select(func.max(Review.period_end))).scalar()
    if latest is not None and latest > today - REVIEW_PERIOD:
        raise SkipJob(f"current review covers through {latest}")

    period_start = today - REVIEW_PERIOD
    window_start = datetime.combine(period_start, datetime.min.time(), tzinfo=UTC)
    conversations = session.scalars(
        select(Conversation)
        .where(Conversation.updated_at >= window_start, Conversation.summary.is_not(None))
        .order_by(Conversation.updated_at.desc())
        .limit(60)
    ).all()
    if not conversations:
        raise SkipJob("no summarized activity this period")

    done_tasks = session.scalars(
        select(Task).where(Task.completed_at.is_not(None), Task.completed_at >= window_start)
    ).all()
    open_tasks = session.scalars(select(Task).where(Task.status != TaskStatus.done).limit(30)).all()

    conversations_text = "\n".join(
        f"- {c.source.kind.value} · {c.project or '-'} · {c.title or 'untitled'}: {c.summary}"
        for c in conversations
    )
    content = await complete(
        session,
        _REVIEW_PROMPT.replace("__START__", period_start.isoformat())
        .replace("__END__", today.isoformat())
        .replace("__CONVERSATIONS__", conversations_text)
        .replace("__DONE_TASKS__", "\n".join(f"- {t.title}" for t in done_tasks) or "(none)")
        .replace("__OPEN_TASKS__", "\n".join(f"- {t.title}" for t in open_tasks) or "(none)"),
        max_tokens=2048,
    )
    if not content:
        raise SkipJob("review model returned nothing")
    session.add(Review(period_start=period_start, period_end=today, content=content))
    session.commit()
    return f"review generated for {period_start}..{today} from {len(conversations)} conversations"
