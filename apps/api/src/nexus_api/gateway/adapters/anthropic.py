"""Anthropic Messages API streaming adapter (raw SSE).

Wire format: message_start (input usage) -> content_block_delta/text_delta*
-> message_delta (stop_reason, output usage) -> message_stop.
"""

import json
from collections.abc import AsyncIterator

import httpx

from nexus_api.gateway.sse import parse_sse
from nexus_api.gateway.types import (
    ChatMessage,
    Completion,
    ErrorKind,
    GatewayError,
    StreamEvent,
    TextDelta,
)

PROVIDER = "anthropic"
ANTHROPIC_VERSION = "2023-06-01"


async def stream_chat(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[ChatMessage],
    system: str | None = None,
    max_tokens: int = 16000,
) -> AsyncIterator[StreamEvent]:
    body: dict[str, object] = {
        "model": model,
        "max_tokens": max_tokens,
        "stream": True,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
    }
    if system:
        body["system"] = system

    async with client.stream(
        "POST",
        f"{base_url}/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        json=body,
    ) as response:
        if response.status_code != 200:
            detail = _error_detail(await response.aread())
            raise GatewayError.from_status(PROVIDER, response.status_code, detail)

        input_tokens: int | None = None
        output_tokens: int | None = None
        stop_reason: str | None = None
        async for message in parse_sse(response.aiter_lines()):
            payload = json.loads(message.data)
            kind = payload.get("type")
            if kind == "message_start":
                usage = payload.get("message", {}).get("usage", {})
                input_tokens = usage.get("input_tokens")
            elif kind == "content_block_delta":
                delta = payload.get("delta", {})
                if delta.get("type") == "text_delta":
                    yield TextDelta(delta.get("text", ""))
            elif kind == "message_delta":
                stop_reason = payload.get("delta", {}).get("stop_reason") or stop_reason
                usage = payload.get("usage", {})
                if usage.get("output_tokens") is not None:
                    output_tokens = usage["output_tokens"]
            elif kind == "error":
                error = payload.get("error", {})
                raise GatewayError(
                    ErrorKind.server,
                    PROVIDER,
                    f"stream error: {error.get('type')}: {error.get('message', '')[:300]}",
                    retryable=error.get("type") == "overloaded_error",
                )
        yield Completion(stop_reason, input_tokens, output_tokens)


def _error_detail(raw: bytes) -> str:
    try:
        body = json.loads(raw)
        return str(body.get("error", {}).get("message") or body)
    except (ValueError, AttributeError):
        return raw[:300].decode(errors="replace")
