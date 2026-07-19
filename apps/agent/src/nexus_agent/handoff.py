"""Local handoff (spec §5.2): fetch a brief from the backend and write it as
a primer file into a chosen repo — the agent's one write capability, gated by
`[handoff] enabled = true` in nexus-agent.toml.
"""

import shutil
import subprocess
from pathlib import Path

import httpx

from nexus_agent.config import AgentConfig

BRIEF_FILENAME = "NEXUS_BRIEF.md"

LAUNCH_COMMANDS = {
    "claude_code": ["claude", f"Read {BRIEF_FILENAME} and continue the work described there."],
    "generic": [],
}


class HandoffError(Exception):
    """User-facing handoff failure."""


def fetch_brief(
    client: httpx.Client,
    *,
    target: str,
    task_id: str | None,
    conversation_id: str | None,
    instructions: str | None,
) -> str:
    response = client.post(
        "/handoff",
        json={
            "target": target,
            "task_id": task_id,
            "conversation_id": conversation_id,
            "instructions": instructions,
        },
    )
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise HandoffError(f"backend rejected the handoff ({response.status_code}): {detail}")
    brief = response.json().get("brief")
    if not isinstance(brief, str) or not brief:
        raise HandoffError("backend returned an empty brief")
    return brief


def write_primer(config: AgentConfig, repo: Path, brief: str) -> Path:
    """Write the primer file — the only write the agent ever performs, and
    only into the repo the user explicitly named."""
    if not config.handoff.enabled:
        raise HandoffError(
            "handoff is disabled on this machine; set [handoff] enabled = true "
            "in nexus-agent.toml to allow writing primer files"
        )
    repo = repo.expanduser().resolve()
    if not repo.is_dir():
        raise HandoffError(f"{repo} is not a directory")
    path = repo / BRIEF_FILENAME
    path.write_text(brief)
    return path


def launch_command(target: str) -> list[str] | None:
    command = LAUNCH_COMMANDS.get(target)
    return command or None


def launch(target: str, repo: Path) -> int:
    command = launch_command(target)
    if command is None:
        raise HandoffError(f"no launch command configured for target {target!r}")
    if shutil.which(command[0]) is None:
        raise HandoffError(f"{command[0]!r} is not installed on this machine")
    return subprocess.call(command, cwd=repo)
