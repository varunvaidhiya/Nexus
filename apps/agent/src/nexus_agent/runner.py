"""Sync loop: discover changed sessions, normalize, POST to /ingest.

The agent builds plain dicts in the nexus.ingest.v1 shape rather than
depending on the schema package — the backend validates strictly and the
agent's tests validate fixtures against the JSON Schema to catch drift.
"""

import logging
import time
from pathlib import Path

import httpx

from nexus_agent.adapters import claude_code
from nexus_agent.config import AgentConfig
from nexus_agent.state import SyncState

logger = logging.getLogger("nexus_agent")

BATCH_LIMIT = 20  # conversations per POST, keeps request bodies bounded


def _conversation_payload(parsed: claude_code.ParsedConversation) -> dict[str, object]:
    return {
        "external_id": parsed.external_id,
        "title": parsed.title,
        "model": parsed.model,
        "tool": claude_code.TOOL_NAME,
        "project": parsed.project,
        "messages": [
            {
                "external_id": m.external_id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at,
            }
            for m in parsed.messages
        ],
    }


def sync_once(config: AgentConfig, client: httpx.Client, state: SyncState) -> int:
    """One pass over every enabled tool. Returns conversations pushed."""
    pushed = 0
    for tool_name, tool in config.tools.items():
        if not tool.enabled:
            continue
        if tool_name != claude_code.TOOL_NAME:
            logger.warning("no adapter for tool %r, skipping", tool_name)
            continue
        pushed += _sync_claude_code(config, client, state, tool.root)
    return pushed


def _sync_claude_code(
    config: AgentConfig,
    client: httpx.Client,
    state: SyncState,
    root: Path | None,
) -> int:
    changed: list[claude_code.ParsedConversation] = []
    for path in claude_code.discover_sessions(root):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if not state.needs_sync(claude_code.TOOL_NAME, path, mtime):
            continue
        parsed = claude_code.parse_session(path)
        if parsed is None:
            # Empty/unparseable now; record the mtime so we only retry on change.
            state.mark_synced(claude_code.TOOL_NAME, path, mtime)
            continue
        changed.append(parsed)

    pushed = 0
    for start in range(0, len(changed), BATCH_LIMIT):
        chunk = changed[start : start + BATCH_LIMIT]
        batch = {
            "schema_version": "nexus.ingest.v1",
            "source": {
                "kind": claude_code.TOOL_NAME,
                "name": f"{claude_code.TOOL_NAME}@{config.machine_name}",
                "ingest_tier": "A",
            },
            "conversations": [_conversation_payload(p) for p in chunk],
        }
        response = client.post("/ingest", json=batch)
        response.raise_for_status()
        report = response.json()
        logger.info(
            "pushed %d conversation(s): %s new, %d new message(s)",
            len(chunk),
            report.get("new_conversations", "?"),
            report.get("new_messages", 0),
        )
        for parsed in chunk:
            state.mark_synced(claude_code.TOOL_NAME, parsed.path, parsed.mtime)
        state.save()
        pushed += len(chunk)
    return pushed


def make_client(config: AgentConfig) -> httpx.Client:
    return httpx.Client(
        base_url=config.backend_url,
        headers={"Authorization": f"Bearer {config.token}"},
        timeout=30.0,
    )


def run_forever(config: AgentConfig) -> None:
    state = SyncState(config.state_path)
    state.load()
    with make_client(config) as client:
        while True:
            try:
                sync_once(config, client, state)
            except httpx.HTTPError as exc:
                logger.warning("sync failed, retrying next interval: %s", exc)
            time.sleep(config.interval_seconds)
