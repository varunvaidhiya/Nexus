"""Minimal Server-Sent Events parsing over an httpx line iterator."""

from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass(frozen=True)
class SSEMessage:
    event: str | None
    data: str


async def parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[SSEMessage]:
    event: str | None = None
    data_parts: list[str] = []
    async for line in lines:
        line = line.rstrip("\n").rstrip("\r")
        if line == "":
            if data_parts:
                yield SSEMessage(event=event, data="\n".join(data_parts))
            event = None
            data_parts = []
        elif line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_parts.append(line[len("data:") :].lstrip())
        # comments (":") and other fields are ignored
    if data_parts:
        yield SSEMessage(event=event, data="\n".join(data_parts))
