# apps/agent

Companion agent (Tier A) — a small read-only daemon that watches local
coding-tool logs, normalizes sessions into the `nexus.ingest.v1` shape, and
POSTs them to the Nexus backend's `/ingest` endpoint using a device token.

Currently supported tools:

| Tool | Where it reads from |
| --- | --- |
| Claude Code | `~/.claude/projects/*/*.jsonl` |

Adapters for Cursor, Codex, opencode, and Droid are planned (see
[docs/IMPLEMENTATION_PLAN.md](../../docs/IMPLEMENTATION_PLAN.md)).

## Install

```bash
pip install ./apps/agent
```

## Configure

Create a device token in Nexus (Settings → Devices), then write
`~/.config/nexus/nexus-agent.toml`:

```toml
[backend]
url = "http://localhost:8000"
token = "nxd_..."          # shown once when the device is created

[agent]
machine_name = "laptop"    # optional, defaults to "local"
# state_path = "~/.local/state/nexus-agent/state.json"
# interval_seconds = 120

[tools.claude_code]
enabled = true
# root = "~/.claude/projects"   # optional override
```

## Run

```bash
nexus-agent sync   # one pass, then exit
nexus-agent run    # keep syncing every interval_seconds
```

## Local handoff (opt-in)

The agent's single write capability (spec §5.2): fetch a context brief from
the backend and drop it into a repo as `NEXUS_BRIEF.md`, so a local tool can
pick the work up. Off by default — enable per machine:

```toml
[handoff]
enabled = true
```

```bash
nexus-agent handoff --repo ~/code/webapp --task <task-uuid>
nexus-agent handoff --repo ~/code/webapp --task <task-uuid> --launch  # also start claude there
```

## How it works

- **Read-only.** The agent never writes to tool directories; it only reads
  transcripts.
- **Incremental.** A state file records each session file's mtime at last
  push; only files that changed since are re-sent.
- **Idempotent.** The backend dedupes by conversation `external_id` and
  message id/fingerprint, so re-sending a session never duplicates data.
- **Tolerant.** Transcript formats drift between tool versions; unknown line
  types are skipped rather than fatal.

## Development

```bash
cd apps/agent
pip install -e ".[dev]"
ruff check . && mypy && pytest
```
