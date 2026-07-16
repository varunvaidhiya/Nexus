"""Provider key management.

Plaintext keys exist only inside the POST request body (a SecretStr, so it
never appears in reprs or logs) and are encrypted before touching the
database. No endpoint ever returns key material in any form.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api import crypto
from nexus_api.db.models import ProviderKey
from nexus_api.db.session import get_session

router = APIRouter(prefix="/providers", tags=["providers"])

SessionDep = Annotated[Session, Depends(get_session)]


class ProviderKeyIn(BaseModel):
    provider: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_-]+$")
    api_key: SecretStr = Field(min_length=1)
    models: list[str] = Field(default_factory=list)
    monthly_budget_usd: Decimal | None = Field(default=None, ge=0)


class ProviderOut(BaseModel):
    id: uuid.UUID
    provider: str
    models: list[str]
    monthly_budget_usd: Decimal | None
    spend_usd: Decimal
    created_at: datetime

    @classmethod
    def from_row(cls, row: ProviderKey) -> "ProviderOut":
        return cls(
            id=row.id,
            provider=row.provider,
            models=row.models,
            monthly_budget_usd=row.monthly_budget_usd,
            spend_usd=row.spend_usd,
            created_at=row.created_at,
        )


@router.get("", response_model=list[ProviderOut])
def list_providers(session: SessionDep) -> list[ProviderOut]:
    rows = session.scalars(select(ProviderKey).order_by(ProviderKey.provider)).all()
    return [ProviderOut.from_row(row) for row in rows]


@router.post("/keys", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
def upsert_provider_key(body: ProviderKeyIn, session: SessionDep) -> ProviderOut:
    try:
        encrypted = crypto.encrypt(body.api_key.get_secret_value())
    except crypto.CryptoError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    row = session.scalars(
        select(ProviderKey).where(ProviderKey.provider == body.provider)
    ).one_or_none()
    if row is None:
        row = ProviderKey(provider=body.provider, encrypted_key=encrypted)
        session.add(row)
    else:
        row.encrypted_key = encrypted
    row.models = body.models
    row.monthly_budget_usd = body.monthly_budget_usd
    session.flush()
    session.refresh(row)
    return ProviderOut.from_row(row)


@router.delete("/keys/{provider}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider_key(provider: str, session: SessionDep) -> None:
    row = session.scalars(select(ProviderKey).where(ProviderKey.provider == provider)).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no key for this provider")
    session.delete(row)


def get_decrypted_key(session: Session, provider: str) -> SecretStr:
    """Server-side only — used by the provider gateway (Phase 1). Never expose
    the result through an API response."""
    row = session.scalars(select(ProviderKey).where(ProviderKey.provider == provider)).one_or_none()
    if row is None:
        raise LookupError(f"no key stored for provider {provider!r}")
    return SecretStr(crypto.decrypt(row.encrypted_key))
