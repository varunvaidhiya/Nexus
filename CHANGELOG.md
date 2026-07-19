# Changelog

## v1.0.0 — 2026-07-19

First complete release: the full spec §14 roadmap, phases 0–5.

- **Phase 0 — Foundation**: monorepo (Next.js web, FastAPI API, schema
  package), Postgres 16 + pgvector schema with Alembic, Docker Compose,
  encrypted provider-key storage, single-user auth, CI.
- **Phase 1 — Native chat**: provider gateway (Anthropic, OpenAI-compatible,
  Gemini wire protocols) over raw SSE, streaming chat UI with model picker,
  budgets and spend tracking, Tier D auto-capture of every native chat.
- **Phase 2 — Context engine**: background worker (embeddings, summaries,
  fact distillation, rolling profile), hybrid search (FTS + pgvector + RRF),
  context injection with an inspectable bundle.
- **Phase 3 — Ingestion**: idempotent `/ingest` with device tokens, companion
  agent reading Claude Code sessions incrementally, ChatGPT/Claude export
  importer, MV3 extension scaffold, sources dashboard.
- **Phase 4 — Assistant**: task/goal extraction from conversations, ranked
  Today view with explained scores, loose-end detection with permanent
  dismissals, weekly reviews, task board and goal progress rollups.
- **Phase 5 — Handoff + MCP**: `POST /handoff` context packages with
  per-target templates, handoff composer UI, agent primer-file writing
  (opt-in), MCP server at `/mcp` (`search_memory`, `get_profile`,
  `get_open_tasks`, `get_conversation`, `log_handoff`), operations and
  security documentation.

### Upgrade notes

- Run `alembic upgrade head` (or `docker compose run --rm api alembic
  upgrade head`) — v1.0.0 adds the `handoff` table.
- Device tokens now also authenticate `/handoff` and `/mcp` (previously
  `/ingest` only). Revoke any token you don't want to have memory read
  access via MCP.
- New docs: [docs/MCP.md](docs/MCP.md) (client setup),
  [docs/OPERATIONS.md](docs/OPERATIONS.md) (backup/restore),
  [docs/SECURITY.md](docs/SECURITY.md) (§13 review).
