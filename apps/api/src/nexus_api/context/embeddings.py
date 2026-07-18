"""Embedding client: OpenAI-compatible /embeddings endpoint, pluggable via
the same provider registry (and base-URL overrides) as the chat gateway."""

import httpx
from sqlalchemy.orm import Session

from nexus_api.config import get_settings
from nexus_api.gateway.budget import record_spend
from nexus_api.gateway.providers import get_provider
from nexus_api.gateway.types import ErrorKind, GatewayError
from nexus_api.routers.providers import get_decrypted_key

EMBEDDING_DIM = 1536
_BATCH_SIZE = 64
_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)


def embedding_available(session: Session) -> bool:
    """True when a key for the embedding provider is stored."""
    try:
        get_decrypted_key(session, get_settings().embedding_provider)
        return True
    except LookupError:
        return False


async def embed_texts(session: Session, texts: list[str]) -> list[list[float]]:
    """Embed texts (batched); records spend against the embedding provider."""
    settings = get_settings()
    provider = get_provider(settings.embedding_provider)
    if provider is None:
        raise GatewayError(
            ErrorKind.bad_request,
            settings.embedding_provider,
            f"unsupported embedding provider {settings.embedding_provider!r}",
        )
    api_key = get_decrypted_key(session, provider.name).get_secret_value()

    vectors: list[list[float]] = []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[start : start + _BATCH_SIZE]
            response = await client.post(
                f"{provider.base_url}/embeddings",
                headers={"authorization": f"Bearer {api_key}"},
                json={"model": settings.embedding_model, "input": batch},
            )
            if response.status_code != 200:
                raise GatewayError.from_status(
                    provider.name, response.status_code, response.text[:300]
                )
            payload = response.json()
            rows = sorted(payload["data"], key=lambda item: item["index"])
            vectors.extend(row["embedding"] for row in rows)
            usage = payload.get("usage", {})
            record_spend(
                session,
                provider.name,
                settings.embedding_model,
                usage.get("prompt_tokens") or usage.get("total_tokens"),
                0,
            )
    return vectors


async def embed_query(session: Session, text: str) -> list[float]:
    return (await embed_texts(session, [text]))[0]
