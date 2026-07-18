"""Device-token management (settings UI). The plaintext token is returned
exactly once, at creation."""

import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api.auth import hash_device_token
from nexus_api.db.models import DeviceToken
from nexus_api.db.session import get_session

router = APIRouter(prefix="/devices", tags=["devices"])

SessionDep = Annotated[Session, Depends(get_session)]


class DeviceOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None
    revoked: bool


class DeviceCreated(DeviceOut):
    token: str  # shown once


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def _out(row: DeviceToken) -> DeviceOut:
    return DeviceOut(
        id=row.id,
        name=row.name,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked=row.revoked_at is not None,
    )


@router.get("", response_model=list[DeviceOut])
def list_devices(session: SessionDep) -> list[DeviceOut]:
    rows = session.scalars(select(DeviceToken).order_by(DeviceToken.created_at)).all()
    return [_out(row) for row in rows]


@router.post("", response_model=DeviceCreated, status_code=status.HTTP_201_CREATED)
def create_device(body: DeviceIn, session: SessionDep) -> DeviceCreated:
    token = f"nxd_{secrets.token_urlsafe(32)}"
    row = DeviceToken(name=body.name, token_hash=hash_device_token(token))
    session.add(row)
    session.flush()
    session.refresh(row)
    return DeviceCreated(**_out(row).model_dump(), token=token)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_device(device_id: uuid.UUID, session: SessionDep) -> None:
    row = session.get(DeviceToken, device_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="unknown device")
    row.revoked_at = row.revoked_at or datetime.now(UTC)
