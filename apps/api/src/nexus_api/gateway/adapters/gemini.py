"""Google Gemini generateContent streaming adapter (SSE via alt=sse)."""

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

PROVIDER = "gemini"


async def stream_chat(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[ChatMessage],
    system: str | None = None,
    max_tokens: int | None = None,
) -> AsyncIterator[StreamEvent]:
    contents = [
        {
            "role": "user" if m.role == "user" else "model",
            "parts": [{"text": m.content}],
        }
        for m in messages
    ]
    body: dict[str, object] = {"contents": contents}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if max_tokens is not None:
        body["generationConfig"] = {"maxOutputTokens": max_tokens}

    async with client.stream(
        "POST",
        f"{base_url}/v1beta/models/{model}:streamGenerateContent",
        params={"alt": "sse"},
        headers={
            # Header auth keeps the key out of URLs (and any URL logging).
            "x-goog-api-key": api_key,
            "content-type": "application/json",
        },
        json=body,
    ) as response:
        if response.status_code != 200:
            detail = _error_detail(await response.aread())
            raise GatewayError.from_status(PROVIDER, response.status_code, detail)

        input_tokens: int | None = None
        output_tokens: int | None = None
        finish_reason: str | None = None
        async for message in parse_sse(response.aiter_lines()):
            payload = json.loads(message.data)
            for candidate in payload.get("candidates") or []:
                for part in (candidate.get("content") or {}).get("parts") or []:
                    text = part.get("text")
                    if text:
                        yield TextDelta(text)
                if candidate.get("finishReason"):
                    finish_reason = candidate["finishReason"]
            usage = payload.get("usageMetadata")
            if usage:
                input_tokens = usage.get("promptTokenCount", input_tokens)
                output_tokens = usage.get("candidatesTokenCount", output_tokens)
        yield Completion(finish_reason, input_tokens, output_tokens)


def _error_detail(raw: bytes) -> str:
    try:
        body = json.loads(raw)
        return str(body.get("error", {}).get("message") or body)
    except (ValueError, AttributeError):
        return raw[:300].decode(errors="replace")
