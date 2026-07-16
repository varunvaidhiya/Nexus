# apps/agent

Companion agent (Tier A) — small read-only daemon that watches local coding-tool
logs (Claude Code, Cursor, Codex, opencode, Droid), normalizes sessions, and
POSTs them to `/ingest` with a device token. Configured via `nexus-agent.toml`.

Built in **Phase 3** (see [docs/IMPLEMENTATION_PLAN.md](../../docs/IMPLEMENTATION_PLAN.md)).
