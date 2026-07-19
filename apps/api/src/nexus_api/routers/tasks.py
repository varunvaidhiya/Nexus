"""Task CRUD — the manual counterpart to LLM extraction (spec §10)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api.db.models import GoalTask, Task, TaskStatus
from nexus_api.db.session import get_session

router = APIRouter(prefix="/tasks", tags=["tasks"])

SessionDep = Annotated[Session, Depends(get_session)]


class TaskOut(BaseModel):
    id: uuid.UUID
    title: str
    detail: str | None
    status: str
    priority: int
    due_at: datetime | None
    why_it_matters: str | None
    source_conversation_id: uuid.UUID | None
    goal_ids: list[uuid.UUID]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    detail: str | None = None
    priority: int = Field(default=0, ge=0, le=3)
    due_at: datetime | None = None
    why_it_matters: str | None = None


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    detail: str | None = None
    status: TaskStatus | None = None
    priority: int | None = Field(default=None, ge=0, le=3)
    due_at: datetime | None = None
    why_it_matters: str | None = None


def _goal_ids(session: Session, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    links: dict[uuid.UUID, list[uuid.UUID]] = {}
    if task_ids:
        for link in session.scalars(select(GoalTask).where(GoalTask.task_id.in_(task_ids))):
            links.setdefault(link.task_id, []).append(link.goal_id)
    return links


def to_task_out(task: Task, goal_ids: list[uuid.UUID]) -> TaskOut:
    return TaskOut(
        id=task.id,
        title=task.title,
        detail=task.detail,
        status=task.status.value,
        priority=task.priority,
        due_at=task.due_at,
        why_it_matters=task.why_it_matters,
        source_conversation_id=task.source_conversation_id,
        goal_ids=goal_ids,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
    )


@router.get("", response_model=list[TaskOut])
def list_tasks(
    session: SessionDep,
    status_filter: Annotated[TaskStatus | None, Query(alias="status")] = None,
) -> list[TaskOut]:
    query = select(Task).order_by(Task.created_at.desc())
    if status_filter is not None:
        query = query.where(Task.status == status_filter)
    tasks = session.scalars(query).all()
    links = _goal_ids(session, [t.id for t in tasks])
    return [to_task_out(t, links.get(t.id, [])) for t in tasks]


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(body: TaskIn, session: SessionDep) -> TaskOut:
    task = Task(
        title=body.title,
        detail=body.detail,
        priority=body.priority,
        due_at=body.due_at,
        why_it_matters=body.why_it_matters,
    )
    session.add(task)
    session.flush()
    session.refresh(task)
    return to_task_out(task, [])


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: uuid.UUID, body: TaskPatch, session: SessionDep) -> TaskOut:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown task")
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(task, field, value)
    if "status" in updates:
        task.completed_at = datetime.now(UTC) if task.status == TaskStatus.done else None
    task.updated_at = datetime.now(UTC)
    session.flush()
    session.refresh(task)
    return to_task_out(task, _goal_ids(session, [task.id]).get(task.id, []))
