"""OpenAI-compatible chat/completions streaming adapter.

Used by OpenAI, OpenRouter, DeepSeek, and any self-hosted server speaking the
same protocol (Ollama, LM Studio, vLLM) via a base-URL override.
"""

import json
from collections.abc import AsyncIterator

import httpx

from nexus_api.gateway.sse import parse_sse
from nexus_api.gateway.types import (
    ChatMessage,
    Completion,
    GatewayError,
    StreamEvent,
    TextDelta,
)


async def stream_chat(
    client: httpx.AsyncClient,
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[ChatMessage],
    system: str | None = None,
    max_tokens: int | None = None,
) -> AsyncIterator[StreamEvent]:
    wire_messages: list[dict[str, str]] = []
    if system:
        wire_messages.append({"role": "system", "content": system})
    wire_messages.extend({"role": m.role, "content": m.content} for m in messages)

    body: dict[str, object] = {
        "model": model,
        "messages": wire_messages,
        "stream": True,
        # Ask for a final usage chunk; servers that don't support it ignore it.
        "stream_options": {"include_usage": True},
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens

    async with client.stream(
        "POST",
        f"{base_url}/chat/completions",
        headers={
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        },
        json=body,
    ) as response:
        if response.status_code != 200:
            detail = _error_detail(await response.aread())
            raise GatewayError.from_status(provider, response.status_code, detail)

        input_tokens: int | None = None
        output_tokens: int | None = None
        finish_reason: str | None = None
        async for message in parse_sse(response.aiter_lines()):
            if message.data.strip() == "[DONE]":
                break
            payload = json.loads(message.data)
            for choice in payload.get("choices") or []:
                content = (choice.get("delta") or {}).get("content")
                if content:
                    yield TextDelta(content)
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
            usage = payload.get("usage")
            if usage:
                input_tokens = usage.get("prompt_tokens", input_tokens)
                output_tokens = usage.get("completion_tokens", output_tokens)
        yield Completion(finish_reason, input_tokens, output_tokens)


def _error_detail(raw: bytes) -> str:
    try:
        body = json.loads(raw)
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)
        return str(error or body)
    except (ValueError, AttributeError):
        return raw[:300].decode(errors="replace")
