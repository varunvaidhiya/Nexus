"""The assistant surface: ranked Today view, loose-end suggestions, reviews.

Ranking is deliberately transparent — every point a task scores comes with a
human-readable reason, because a recommendation you can't explain is one you
can't trust (spec §9).
"""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api.db.models import Goal, GoalTask, Review, Suggestion, Task, TaskStatus
from nexus_api.db.session import get_session
from nexus_api.routers.tasks import TaskOut, to_task_out

router = APIRouter(tags=["assistant"])

SessionDep = Annotated[Session, Depends(get_session)]

TODAY_LIMIT = 10


class TodayItem(BaseModel):
    task: TaskOut
    score: int
    reasons: list[str]


def score_task(task: Task, goal_titles: list[str], now: datetime) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if task.due_at is not None:
        due = task.due_at if task.due_at.tzinfo else task.due_at.replace(tzinfo=UTC)
        days = (due - now).total_seconds() / 86400
        if days < 0:
            score += 6
            reasons.append(f"Overdue by {max(1, int(-days))} day(s).")
        elif days <= 1:
            score += 5
            reasons.append("Due within 24 hours.")
        elif days <= 3:
            score += 3
            reasons.append(f"Due in {int(days) + 1} days.")
        elif days <= 7:
            score += 1
            reasons.append("Due this week.")

    if task.priority > 0:
        score += 2 * task.priority
        reasons.append(f"Priority {task.priority}.")

    updated = task.updated_at if task.updated_at.tzinfo else task.updated_at.replace(tzinfo=UTC)
    stale_days = int((now - updated).total_seconds() / 86400)
    if task.status == TaskStatus.doing and stale_days >= 3:
        score += 2
        reasons.append(f"You started this {stale_days} days ago and left it unfinished.")
    elif task.status == TaskStatus.todo and stale_days >= 7:
        score += 1
        reasons.append(f"Sitting in your list for {stale_days} days.")

    for title in goal_titles[:2]:
        score += 1
        reasons.append(f'Advances your goal "{title}".')

    return score, reasons


@router.get("/today", response_model=list[TodayItem])
def today(session: SessionDep) -> list[TodayItem]:
    now = datetime.now(UTC)
    tasks = session.scalars(
        select(Task).where(Task.status.in_([TaskStatus.todo, TaskStatus.doing]))
    ).all()

    goal_titles: dict[uuid.UUID, list[str]] = {}
    if tasks:
        rows = session.execute(
            select(GoalTask.task_id, Goal.title)
            .join(Goal, Goal.id == GoalTask.goal_id)
            .where(GoalTask.task_id.in_([t.id for t in tasks]))
        ).all()
        for task_id, title in rows:
            goal_titles.setdefault(task_id, []).append(title)

    goal_ids: dict[uuid.UUID, list[uuid.UUID]] = {}
    if tasks:
        for link in session.scalars(
            select(GoalTask).where(GoalTask.task_id.in_([t.id for t in tasks]))
        ):
            goal_ids.setdefault(link.task_id, []).append(link.goal_id)

    items = []
    for task in tasks:
        score, reasons = score_task(task, goal_titles.get(task.id, []), now)
        items.append(
            TodayItem(
                task=to_task_out(task, goal_ids.get(task.id, [])), score=score, reasons=reasons
            )
        )
    items.sort(key=lambda item: (-item.score, item.task.created_at))
    return items[:TODAY_LIMIT]


class SuggestionOut(BaseModel):
    id: uuid.UUID
    kind: str
    conversation_id: uuid.UUID
    conversation_title: str | None
    reason: str
    created_at: datetime


@router.get("/suggestions", response_model=list[SuggestionOut])
def list_suggestions(session: SessionDep) -> list[SuggestionOut]:
    rows = session.scalars(
        select(Suggestion)
        .where(Suggestion.dismissed_at.is_(None))
        .order_by(Suggestion.created_at.desc())
    ).all()
    return [
        SuggestionOut(
            id=row.id,
            kind=row.kind,
            conversation_id=row.conversation_id,
            conversation_title=conversation.title
            if (conversation := _conv(session, row))
            else None,
            reason=row.reason,
            created_at=row.created_at,
        )
        for row in rows
    ]


def _conv(session: Session, suggestion: Suggestion):  # type: ignore[no-untyped-def]
    from nexus_api.db.models import Conversation

    return session.get(Conversation, suggestion.conversation_id)


@router.post("/suggestions/{suggestion_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_suggestion(suggestion_id: uuid.UUID, session: SessionDep) -> None:
    suggestion = session.get(Suggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown suggestion")
    suggestion.dismissed_at = suggestion.dismissed_at or datetime.now(UTC)
    session.flush()


class ReviewOut(BaseModel):
    id: uuid.UUID
    period_start: date
    period_end: date
    content: str
    created_at: datetime


@router.get("/reviews", response_model=list[ReviewOut])
def list_reviews(session: SessionDep, limit: int = 8) -> list[ReviewOut]:
    rows = session.scalars(
        select(Review).order_by(Review.period_start.desc()).limit(min(max(limit, 1), 52))
    ).all()
    return [
        ReviewOut(
            id=row.id,
            period_start=row.period_start,
            period_end=row.period_end,
            content=row.content,
            created_at=row.created_at,
        )
        for row in rows
    ]
