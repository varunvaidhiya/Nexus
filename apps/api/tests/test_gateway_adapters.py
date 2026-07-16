"""Adapter tests against recorded provider responses via httpx.MockTransport."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest

from nexus_api.gateway.adapters import anthropic, gemini, openai_compat
from nexus_api.gateway.sse import parse_sse
from nexus_api.gateway.types import ChatMessage, Completion, ErrorKind, GatewayError, TextDelta

MESSAGES = [ChatMessage("user", "hi")]


def _sse(*events: tuple[str | None, dict | str]) -> bytes:
    out = []
    for name, data in events:
        if name:
            out.append(f"event: {name}")
        payload = data if isinstance(data, str) else json.dumps(data)
        out.append(f"data: {payload}")
        out.append("")
    return ("\n".join(out) + "\n").encode()


def _client(body: bytes, status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        content_type = "text/event-stream" if status == 200 else "application/json"
        return httpx.Response(status, content=body, headers={"content-type": content_type})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _collect(stream: AsyncIterator) -> tuple[str, Completion]:
    text: list[str] = []
    completion: Completion | None = None
    async for event in stream:
        if isinstance(event, TextDelta):
            text.append(event.text)
        elif isinstance(event, Completion):
            completion = event
    assert completion is not None, "stream must end with a Completion"
    return "".join(text), completion


# --- SSE parser ---


async def test_sse_parser_multiline_and_events() -> None:
    async def lines() -> AsyncIterator[str]:
        for line in [
            ": comment",
            "event: ping",
            "data: one",
            "data: two",
            "",
            "data: solo",
            "",
        ]:
            yield line

    messages = [m async for m in parse_sse(lines())]
    assert messages[0].event == "ping"
    assert messages[0].data == "one\ntwo"
    assert messages[1].event is None
    assert messages[1].data == "solo"


# --- Anthropic ---


async def test_anthropic_stream() -> None:
    body = _sse(
        ("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 12}}}),
        (
            "content_block_delta",
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hel"}},
        ),
        (
            "content_block_delta",
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "lo"}},
        ),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 5},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    )
    async with _client(body) as client:
        text, completion = await _collect(
            anthropic.stream_chat(
                client,
                base_url="http://test",
                api_key="k",
                model="claude-sonnet-5",
                messages=MESSAGES,
            )
        )
    assert text == "Hello"
    assert completion == Completion("end_turn", 12, 5)


async def test_anthropic_auth_error() -> None:
    error = json.dumps(
        {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}
    ).encode()
    async with _client(error, status=401) as client:
        with pytest.raises(GatewayError) as excinfo:
            await _collect(
                anthropic.stream_chat(
                    client, base_url="http://test", api_key="bad", model="m", messages=MESSAGES
                )
            )
    assert excinfo.value.kind == ErrorKind.auth


# --- OpenAI-compatible ---


async def test_openai_compat_stream() -> None:
    body = _sse(
        (None, {"choices": [{"delta": {"role": "assistant", "content": ""}}]}),
        (None, {"choices": [{"delta": {"content": "Hi "}}]}),
        (None, {"choices": [{"delta": {"content": "there"}, "finish_reason": None}]}),
        (None, {"choices": [{"delta": {}, "finish_reason": "stop"}]}),
        (None, {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 4}}),
        (None, "[DONE]"),
    )
    async with _client(body) as client:
        text, completion = await _collect(
            openai_compat.stream_chat(
                client,
                provider="deepseek",
                base_url="http://test/v1",
                api_key="k",
                model="deepseek-chat",
                messages=MESSAGES,
            )
        )
    assert text == "Hi there"
    assert completion == Completion("stop", 9, 4)


async def test_openai_compat_rate_limit() -> None:
    error = json.dumps({"error": {"message": "Rate limit reached", "type": "rate_limit"}}).encode()
    async with _client(error, status=429) as client:
        with pytest.raises(GatewayError) as excinfo:
            await _collect(
                openai_compat.stream_chat(
                    client,
                    provider="openai",
                    base_url="http://test/v1",
                    api_key="k",
                    model="gpt-4o",
                    messages=MESSAGES,
                )
            )
    assert excinfo.value.kind == ErrorKind.rate_limit
    assert excinfo.value.retryable


# --- Gemini ---


async def test_gemini_stream() -> None:
    body = _sse(
        (None, {"candidates": [{"content": {"role": "model", "parts": [{"text": "Bon"}]}}]}),
        (
            None,
            {
                "candidates": [{"content": {"parts": [{"text": "jour"}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3},
            },
        ),
    )
    async with _client(body) as client:
        text, completion = await _collect(
            gemini.stream_chat(
                client,
                base_url="http://test",
                api_key="k",
                model="gemini-2.5-flash",
                messages=MESSAGES,
            )
        )
    assert text == "Bonjour"
    assert completion == Completion("STOP", 7, 3)


async def test_api_key_never_in_url() -> None:
    """Keys must travel in headers, not query strings (URLs get logged)."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=_sse((None, {"candidates": []})))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _collect(
            gemini.stream_chat(
                client, base_url="http://test", api_key="sk-secret", model="m", messages=MESSAGES
            )
        )
    assert "sk-secret" not in str(seen[0].url)
    assert seen[0].headers["x-goog-api-key"] == "sk-secret"
