"""Single-user bearer-token gate.

Every route except /healthz requires `Authorization: Bearer <NEXUS_AUTH_TOKEN>`.
The stack never runs open: if NEXUS_AUTH_TOKEN is unset, protected routes
return 503 with instructions instead of allowing anonymous access.
"""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from nexus_api.config import get_settings

_bearer = HTTPBearer(auto_error=False)


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
