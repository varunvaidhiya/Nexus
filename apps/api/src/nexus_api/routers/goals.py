"""Goals with progress rolled up from linked task completion (spec §9)."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api.db.models import Goal, GoalHorizon, GoalStatus, GoalTask, Task, TaskStatus
from nexus_api.db.session import get_session

router = APIRouter(prefix="/goals", tags=["goals"])

SessionDep = Annotated[Session, Depends(get_session)]


class GoalOut(BaseModel):
    id: uuid.UUID
    title: str
    horizon: str
    status: str
    target_at: datetime | None
    created_at: datetime
    task_count: int
    done_count: int
    progress: float  # 0..1, rolled up from linked tasks


class GoalIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    horizon: GoalHorizon
    target_at: datetime | None = None


class GoalPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    horizon: GoalHorizon | None = None
    status: GoalStatus | None = None
    target_at: datetime | None = None


class GoalTaskIn(BaseModel):
    task_id: uuid.UUID


def _to_out(goal: Goal, linked: list[Task]) -> GoalOut:
    done = sum(1 for t in linked if t.status == TaskStatus.done)
    return GoalOut(
        id=goal.id,
        title=goal.title,
        horizon=goal.horizon.value,
        status=goal.status.value,
        target_at=goal.target_at,
        created_at=goal.created_at,
        task_count=len(linked),
        done_count=done,
        progress=done / len(linked) if linked else goal.progress,
    )


def _linked_tasks(session: Session, goal_id: uuid.UUID) -> list[Task]:
    return list(
        session.scalars(
            select(Task)
            .join(GoalTask, GoalTask.task_id == Task.id)
            .where(GoalTask.goal_id == goal_id)
        )
    )


@router.get("", response_model=list[GoalOut])
def list_goals(session: SessionDep) -> list[GoalOut]:
    goals = session.scalars(select(Goal).order_by(Goal.created_at)).all()
    return [_to_out(goal, _linked_tasks(session, goal.id)) for goal in goals]


@router.post("", response_model=GoalOut, status_code=status.HTTP_201_CREATED)
def create_goal(body: GoalIn, session: SessionDep) -> GoalOut:
    goal = Goal(title=body.title, horizon=body.horizon, target_at=body.target_at)
    session.add(goal)
    session.flush()
    session.refresh(goal)
    return _to_out(goal, [])


@router.patch("/{goal_id}", response_model=GoalOut)
def update_goal(goal_id: uuid.UUID, body: GoalPatch, session: SessionDep) -> GoalOut:
    goal = session.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown goal")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(goal, field, value)
    session.flush()
    session.refresh(goal)
    return _to_out(goal, _linked_tasks(session, goal.id))


@router.post("/{goal_id}/tasks", status_code=status.HTTP_204_NO_CONTENT)
def link_task(goal_id: uuid.UUID, body: GoalTaskIn, session: SessionDep) -> None:
    if session.get(Goal, goal_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown goal")
    if session.get(Task, body.task_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown task")
    if session.get(GoalTask, (goal_id, body.task_id)) is None:
        session.add(GoalTask(goal_id=goal_id, task_id=body.task_id))
        session.flush()


@router.delete("/{goal_id}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_task(goal_id: uuid.UUID, task_id: uuid.UUID, session: SessionDep) -> None:
    link = session.get(GoalTask, (goal_id, task_id))
    if link is not None:
        session.delete(link)
        session.flush()
