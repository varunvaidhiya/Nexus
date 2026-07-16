"""Uniform entry point: stream_chat(provider, model, messages) -> events."""

from collections.abc import AsyncIterator

import httpx

from nexus_api.gateway.adapters import anthropic, gemini, openai_compat
from nexus_api.gateway.providers import get_provider
from nexus_api.gateway.types import ChatMessage, ErrorKind, GatewayError, StreamEvent

# Generous read timeout: model output can pause between tokens while thinking.
_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)


async def stream_chat(
    provider_name: str,
    *,
    api_key: str,
    model: str,
    messages: list[ChatMessage],
    system: str | None = None,
    max_tokens: int = 16000,
) -> AsyncIterator[StreamEvent]:
    provider = get_provider(provider_name)
    if provider is None:
        raise GatewayError(
            ErrorKind.bad_request, provider_name, f"unsupported provider {provider_name!r}"
        )

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            if provider.protocol == "anthropic":
                stream = anthropic.stream_chat(
                    client,
                    base_url=provider.base_url,
                    api_key=api_key,
                    model=model,
                    messages=messages,
                    system=system,
                    max_tokens=max_tokens,
                )
            elif provider.protocol == "gemini":
                stream = gemini.stream_chat(
                    client,
                    base_url=provider.base_url,
                    api_key=api_key,
                    model=model,
                    messages=messages,
                    system=system,
                    max_tokens=max_tokens,
                )
            else:
                stream = openai_compat.stream_chat(
                    client,
                    provider=provider.name,
                    base_url=provider.base_url,
                    api_key=api_key,
                    model=model,
                    messages=messages,
                    system=system,
                    max_tokens=max_tokens,
                )
            async for event in stream:
                yield event
    except httpx.HTTPError as exc:
        raise GatewayError(
            ErrorKind.network,
            provider_name,
            f"network error talking to provider: {exc.__class__.__name__}",
            retryable=True,
        ) from exc
