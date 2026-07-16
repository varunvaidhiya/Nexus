from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class TextDelta:
    """A chunk of assistant text."""

    text: str


@dataclass(frozen=True)
class Completion:
    """Terminal event of a stream, carrying usage totals."""

    stop_reason: str | None
    input_tokens: int | None
    output_tokens: int | None


StreamEvent = TextDelta | Completion


class ErrorKind(StrEnum):
    auth = "auth"
    rate_limit = "rate_limit"
    context_overflow = "context_overflow"
    bad_request = "bad_request"
    overloaded = "overloaded"
    server = "server"
    network = "network"
    budget = "budget"


class GatewayError(Exception):
    """Provider failure normalized into one shape the API/UI can render.

    `message` must never contain key material.
    """

    def __init__(self, kind: ErrorKind, provider: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.kind = kind
        self.provider = provider
        self.message = message
        self.retryable = retryable

    @classmethod
    def from_status(cls, provider: str, status: int, detail: str) -> "GatewayError":
        detail = detail[:500]
        if status in (401, 403):
            return cls(ErrorKind.auth, provider, f"authentication failed: {detail}")
        if status == 404:
            return cls(ErrorKind.bad_request, provider, f"unknown model or endpoint: {detail}")
        if status == 429:
            return cls(ErrorKind.rate_limit, provider, f"rate limited: {detail}", retryable=True)
        if status in (503, 529):
            return cls(
                ErrorKind.overloaded, provider, f"provider overloaded: {detail}", retryable=True
            )
        if status >= 500:
            return cls(
                ErrorKind.server, provider, f"provider error ({status}): {detail}", retryable=True
            )
        lowered = detail.lower()
        if "context" in lowered and (
            "long" in lowered or "exceed" in lowered or "length" in lowered
        ):
            return cls(ErrorKind.context_overflow, provider, f"context too long: {detail}")
        return cls(ErrorKind.bad_request, provider, f"bad request ({status}): {detail}")
