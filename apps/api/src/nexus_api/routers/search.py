import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api.context.search import hybrid_search
from nexus_api.db.models import JobRun, ProfileSnapshot
from nexus_api.db.session import get_session

router = APIRouter(tags=["search"])

SessionDep = Annotated[Session, Depends(get_session)]


class SearchHitOut(BaseModel):
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    conversation_title: str | None
    role: str
    snippet: str
    created_at: datetime
    score: float
    matched: str


@router.get("/search", response_model=list[SearchHitOut])
async def search(
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[SearchHitOut]:
    hits = await hybrid_search(session, q, limit=limit)
    return [SearchHitOut(**hit.__dict__) for hit in hits]


class ProfileOut(BaseModel):
    content: str
    generated_at: datetime
    token_count: int | None


@router.get("/profile", response_model=ProfileOut | None)
def profile(session: SessionDep) -> ProfileOut | None:
    snapshot = session.scalars(
        select(ProfileSnapshot).order_by(ProfileSnapshot.generated_at.desc())
    ).first()
    if snapshot is None:
        return None
    return ProfileOut(
        content=snapshot.content,
        generated_at=snapshot.generated_at,
        token_count=snapshot.token_count,
    )


class JobRunOut(BaseModel):
    name: str
    status: str
    detail: str | None
    started_at: datetime
    finished_at: datetime | None


@router.get("/jobs", response_model=list[JobRunOut])
def jobs(session: SessionDep, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[JobRunOut]:
    runs = session.scalars(select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)).all()
    return [
        JobRunOut(
            name=run.name,
            status=run.status.value,
            detail=run.detail,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )
        for run in runs
    ]
