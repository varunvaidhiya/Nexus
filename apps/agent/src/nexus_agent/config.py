"""nexus-agent.toml loading.

[backend]
url = "http://localhost:8000"
token = "nxd_..."          # device token from Nexus settings

[tools.claude_code]
enabled = true
# root = "~/.claude/projects"   # optional override
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATHS = [
    Path("~/.config/nexus/nexus-agent.toml"),
    Path("~/.nexus-agent.toml"),
    Path("nexus-agent.toml"),
]


@dataclass
class ToolConfig:
    enabled: bool = True
    root: Path | None = None


@dataclass
class HandoffConfig:
    """The agent's single write capability (spec §5.2): writing a primer file
    into a repo you name. Off by default; enable per machine."""

    enabled: bool = False


@dataclass
class AgentConfig:
    backend_url: str
    token: str
    machine_name: str = "local"
    tools: dict[str, ToolConfig] = field(default_factory=dict)
    state_path: Path = Path("~/.local/state/nexus-agent/state.json")
    interval_seconds: int = 120
    handoff: HandoffConfig = field(default_factory=HandoffConfig)


def load_config(path: Path | None = None) -> AgentConfig:
    candidates = [path] if path else [p.expanduser() for p in DEFAULT_CONFIG_PATHS]
    for candidate in candidates:
        if candidate and candidate.exists():
            return _parse(candidate)
    raise FileNotFoundError(
        "no nexus-agent.toml found (looked in "
        + ", ".join(str(p) for p in DEFAULT_CONFIG_PATHS)
        + ")"
    )


def _parse(path: Path) -> AgentConfig:
    with open(path, "rb") as handle:
        raw = tomllib.load(handle)
    backend = raw.get("backend") or {}
    url = backend.get("url")
    token = backend.get("token")
    if not url or not token:
        raise ValueError(f"{path}: [backend] url and token are required")
    tools = {
        name: ToolConfig(
            enabled=bool(tool.get("enabled", True)),
            root=Path(tool["root"]).expanduser() if tool.get("root") else None,
        )
        for name, tool in (raw.get("tools") or {}).items()
    }
    agent = raw.get("agent") or {}
    state_path = agent.get("state_path", "~/.local/state/nexus-agent/state.json")
    handoff = raw.get("handoff") or {}
    return AgentConfig(
        backend_url=str(url).rstrip("/"),
        token=str(token),
        machine_name=str(agent.get("machine_name", "local")),
        tools=tools or {"claude_code": ToolConfig()},
        state_path=Path(state_path).expanduser(),
        interval_seconds=int(agent.get("interval_seconds", 120)),
        handoff=HandoffConfig(enabled=bool(handoff.get("enabled", False))),
    )
