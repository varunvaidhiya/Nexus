"""Single-user bearer-token gate.

Every route except /healthz requires `Authorization: Bearer <NEXUS_AUTH_TOKEN>`.
The stack never runs open: if NEXUS_AUTH_TOKEN is unset, protected routes
return 503 with instructions instead of allowing anonymous access.
"""

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from nexus_api.config import get_settings

_bearer = HTTPBearer(auto_error=False)


def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    expected = get_settings().auth_token
    if expected is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NEXUS_AUTH_TOKEN is not set; refusing to serve unauthenticated. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"',
        )
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), expected.get_secret_value().encode()
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_device_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    """Routes for companion tools (/ingest, /handoff, /mcp) accept the main
    auth token OR an active device token, so the agent, extension, and MCP
    clients never need to hold the primary credential."""
    expected = get_settings().auth_token
    if (
        expected is not None
        and credentials is not None
        and secrets.compare_digest(
            credentials.credentials.encode(), expected.get_secret_value().encode()
        )
    ):
        return

    if credentials is not None:
        from nexus_api.db.models import DeviceToken
        from nexus_api.db.session import get_engine

        factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
        with factory() as session:
            row = session.scalars(
                select(DeviceToken).where(
                    DeviceToken.token_hash == hash_device_token(credentials.credentials),
                    DeviceToken.revoked_at.is_(None),
                )
            ).first()
            if row is not None:
                row.last_used_at = datetime.now(UTC)
                session.commit()
                return

    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail="invalid or missing bearer/device token",
        headers={"WWW-Authenticate": "Bearer"},
    )
