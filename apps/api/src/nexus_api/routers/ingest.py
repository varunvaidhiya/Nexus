"""POST /ingest — canonical batches from the agent, extension, and importer.

Authenticated by the main token or a device token (see auth.require_ingest_auth,
applied at mount time in main.py).
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from nexus_schema import IngestBatch
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nexus_api.db.session import get_session
from nexus_api.services.ingest import ingest_batch

router = APIRouter(tags=["ingest"])

SessionDep = Annotated[Session, Depends(get_session)]


class IngestReportOut(BaseModel):
    conversations: int
    new_conversations: int
    new_messages: int
    skipped_messages: int


@router.post("/ingest", response_model=IngestReportOut)
def ingest(batch: IngestBatch, session: SessionDep) -> IngestReportOut:
    report = ingest_batch(session, batch)
    return IngestReportOut(**report.__dict__)
