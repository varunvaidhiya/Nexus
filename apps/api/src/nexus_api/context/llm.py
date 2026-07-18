"""Non-streaming LLM completion on top of the gateway, for background jobs
(summaries, distillation, profile). Uses the configured cheap summary model."""

import json
import re

import structlog
from sqlalchemy.orm import Session

from nexus_api.config import get_settings
from nexus_api.gateway import ChatMessage, Completion, TextDelta, stream_chat
from nexus_api.gateway.budget import check_budget, record_spend
from nexus_api.routers.providers import get_decrypted_key

logger = structlog.get_logger()


def llm_available(session: Session) -> bool:
    try:
        get_decrypted_key(session, get_settings().summary_provider)
        return True
    except LookupError:
        return False


async def complete(session: Session, prompt: str, *, max_tokens: int = 1024) -> str:
    """One-shot completion with the summary model; spend is recorded."""
    settings = get_settings()
    provider = settings.summary_provider
    check_budget(session, provider)
    api_key = get_decrypted_key(session, provider).get_secret_value()

    parts: list[str] = []
    completion: Completion | None = None
    async for event in stream_chat(
        provider,
        api_key=api_key,
        model=settings.summary_model,
        messages=[ChatMessage("user", prompt)],
        max_tokens=max_tokens,
    ):
        if isinstance(event, TextDelta):
            parts.append(event.text)
        elif isinstance(event, Completion):
            completion = event
    record_spend(
        session,
        provider,
        settings.summary_model,
        completion.input_tokens if completion else None,
        completion.output_tokens if completion else None,
    )
    return "".join(parts).strip()


def parse_json_array(raw: str) -> list[dict[str, object]]:
    """Extract a JSON array from LLM output (tolerates code fences/prose)."""
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except ValueError:
        logger.warning("llm returned unparseable JSON array")
        return []
    return [item for item in parsed if isinstance(item, dict)]
