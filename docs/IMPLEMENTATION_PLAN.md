# Nexus — Implementation Plan

Phase-by-phase build plan derived from the [Product Spec](SPEC.md). Each phase lists
its objective, detailed workstreams, deliverables, and **exit criteria** — the phase
is not done until every criterion passes. Phases are ordered so that every phase ends
with something usable, and no phase depends on fragile work (scraping, vendor
endpoints) before the reliable core exists.

**Guiding decisions (locked in up front):**

- **Backend:** FastAPI (Python). Python wins for embeddings, LLM orchestration, and
  parser-heavy ingestion work.
- **Frontend:** Next.js + React + Tailwind + shadcn/ui.
- **Database:** Postgres 16 + pgvector, run via Docker Compose.
- **Jobs:** APScheduler inside the API process to start (Phase 2); promote to
  Celery + Redis only if/when job volume demands it.
- **Monorepo:** `apps/web`, `apps/api`, `apps/agent`, `apps/extension`,
  `packages/schema`.
- **First ship target:** end of Phase 1 — a multi-provider chat that captures
  everything going forward.

---

## Phase 0 — Foundation (1–2 weeks)

**Objective:** a running skeleton — repo, containers, database with the full schema,
encrypted key storage, and a settings screen. No AI features yet, but every later
phase plugs into this without rework.

### 0.1 Repository & tooling
- Monorepo layout (`apps/`, `packages/`, `docs/`) with a root README.
- `apps/web`: Next.js (App Router) + Tailwind + shadcn/ui scaffold.
- `apps/api`: FastAPI scaffold with `/healthz`, settings via `pydantic-settings`,
  structured logging.
- Lint/format: Ruff + mypy (Python), ESLint + Prettier (TS). Pre-commit hooks.
- CI (GitHub Actions): lint + typecheck + unit tests on every PR.

### 0.2 Docker Compose stack
- Services: `db` (Postgres + pgvector), `api`, `web`. One `docker compose up` brings
  the whole stack up; `.env.example` documents every variable.
- Volume-mounted Postgres data; healthchecks so `api` waits for `db`.

### 0.3 Database schema & migrations
- Alembic migrations implementing the full data model from the spec §4:
  `source`, `conversation`, `message`, `entity`, `conversation_entity`, `task`,
  `goal`, `goal_task`, `memory_note`, `provider_key`, `profile_snapshot`.
- Enums as specified (source kinds, message roles, task status, goal horizon).
- Indexes: HNSW on `message.embedding` and other vector columns,
  `conversation(source_id, updated_at)`, `task(status, due_at)`, GIN on
  `conversation.tags`.
- Even though embeddings aren't populated until Phase 2, the columns and indexes
  exist now so no later migration reshapes hot tables.

### 0.4 Canonical schema package
- `packages/schema`: the normalized Conversation/Message shapes every ingestion
  tier will emit, defined once (JSON Schema as source of truth → generated
  Pydantic models + TypeScript types). This is the contract for `/ingest`.

### 0.5 Encrypted provider-key storage
- Envelope encryption: master key from `NEXUS_MASTER_KEY` env var (never in DB);
  per-key data keys; `provider_key.encrypted_key BYTEA`.
- API: `POST /providers/keys`, `GET /providers` (returns provider + models +
  budget + spend — **never** plaintext keys, not even masked-prefix leaks beyond
  last-4 display).
- Keys are excluded from all logging paths from day one.

### 0.6 Auth & settings UI
- Single-user auth: one password / token gate in front of everything (the stack
  is private, but never runs open).
- Settings screen in `apps/web`: add/remove provider keys, set monthly budgets,
  pick default models. First real end-to-end feature through the whole stack.

**Exit criteria**
- [ ] `docker compose up` gives a working web app + API + database from a clean checkout.
- [ ] All migrations apply cleanly; schema matches spec §4 including vector columns and indexes.
- [ ] A provider key can be added in the UI, is stored encrypted, round-trips for server-side use, and never appears in logs or API responses.
- [ ] CI runs lint/typecheck/tests on PRs.

---

## Phase 1 — Native chat (2 weeks) → **first usable product**

**Objective:** a genuinely good multi-provider chat. Every message is captured as
Tier D data — the highest-quality memory source, with zero scraping risk.

### 1.1 Provider gateway
- Uniform adapter interface: `chat(provider, model, messages, stream) -> tokens`.
- Adapters (in order): **Anthropic → OpenAI → OpenRouter → DeepSeek → Gemini**.
  OpenRouter early because it unlocks many models (incl. Qwen/MiniMax/Mistral/xAI
  routes) with one key; remaining native adapters (MiniMax, Qwen, Mistral, xAI)
  can land any time after without blocking anything.
- Streaming end-to-end: provider SSE → FastAPI `StreamingResponse` → UI.
- Token counting + per-provider spend tracking; enforce `monthly_budget_usd`
  with a hard stop and a UI warning at 80%.
- Error normalization (rate limits, context overflow, auth failures) into one
  error shape the UI can render sensibly.

### 1.2 Chat API & auto-capture (Tier D)
- `POST /chat`: creates/continues a `conversation` (source kind `native`),
  persists every user/assistant message *as it streams*, records model + token
  counts. Capture is not optional — it is the write path.
- `GET /conversations`, `GET /conversations/:id` with filters (source, date, model).

### 1.3 Chat UI
- Conversation list + chat view; provider/model picker per conversation.
- Streaming rendering with markdown + code blocks; stop/regenerate; copy.
- **Context toggle** placeholder ("with my full context" / "clean") — wired in
  Phase 2, visible now so the UX is designed for it from the start.
- Budget/spend indicator surfaced near the model picker.

**Exit criteria**
- [ ] Can hold streaming conversations with at least Anthropic, OpenAI, and OpenRouter models, switching models per conversation.
- [ ] Every native chat is persisted with correct roles, timestamps, model, and token counts; visible in the conversation list.
- [ ] Spend accrues per provider; hitting the monthly budget blocks new requests with a clear message.
- [ ] Daily-drivable: this replaces at least one first-party chat UI for daily use.

---

## Phase 2 — Context engine (2 weeks)

**Objective:** turn the captured data into memory: embeddings, unified semantic
search, summaries, and the rolling profile. This is what "understands me" means.

### 2.1 Background job runner
- APScheduler in a worker process (same image as `api`, different entrypoint,
  added to Compose as `worker`).
- Job framework: idempotent jobs, per-job locks, retry with backoff, a `job_run`
  bookkeeping table, and a simple status page in settings.

### 2.2 Embedding pipeline
- Pluggable embedding provider (default OpenAI `text-embedding-3-small`,
  1536-dim; configurable, including local models later).
- Jobs: embed new/updated messages and conversation summaries; batching;
  cost tracking against the same budget system as chat.
- Backfill command for pre-existing rows.

### 2.3 Summarization pipeline
- Per-conversation summary generated on ingest/update (cheap model, configurable)
  → `conversation.summary`, re-embedded.
- Incremental: only re-summarize conversations whose messages changed.

### 2.4 Unified search
- `GET /search?q=`: hybrid retrieval — pgvector similarity + Postgres full-text
  keyword search, merged/re-ranked (reciprocal rank fusion to start).
- Search UI: one box over every message everywhere; filters by source, date,
  project/tag; results grouped by conversation with hit highlighting.

### 2.5 Distillation & rolling profile
- LLM pass distilling durable facts → `memory_note` (content, category,
  confidence, source_ref). Upsert semantics: strengthen/update existing notes
  rather than duplicating; decay/retire contradicted notes.
- Scheduled `profile_snapshot` rebuild: compact document = active projects +
  preferences + open loops, within a fixed token budget.

### 2.6 Context injection (retrieval at chat time)
- Wire the Phase 1 toggle: `context = rolling_profile + top-K relevant messages
  + open tasks in that area + relevant memory_notes`, packed to a token budget
  with clear precedence (profile > notes > messages) when over budget.
- UI affordance showing *what* was injected (expandable "context used" panel) —
  essential for trust and debugging retrieval quality.

**Exit criteria**
- [ ] All native conversations are embedded and summarized automatically within one scheduler cycle.
- [ ] Search returns relevant results for both keyword and semantic queries across all captured data.
- [ ] `memory_note` and `profile_snapshot` populate and visibly improve over a week of use.
- [ ] A context-on chat demonstrably knows recent projects/preferences; the injected context is inspectable in the UI.

---

## Phase 3 — Ingestion (3–4 weeks)

**Objective:** bring in the outside world, in strict reliability order:
companion agent (Tier A) → export importer (Tier C) → browser extension (Tier B).
*Note: C before B* — the importer is high-reliability and immediately backfills
years of history, while the extension is the most fragile component; sequencing
this way de-risks the phase.

### 3.0 Ingest endpoint hardening (prerequisite for all tiers)
- `POST /ingest` accepting canonical batches from `packages/schema`.
- Device tokens: issue/revoke in settings; scope per source; TLS assumed.
- Dedupe by `(source, external_id, message hash)`; idempotent upserts —
  re-sending anything must never duplicate.
- Ingest → context-engine hook: new data queues summarize/embed/distill jobs.

### 3.1 Companion agent (Tier A)
- Small daemon in `apps/agent`; **read-only** on log files; config via
  `nexus-agent.toml` (which tools to watch, backend URL, device token).
- Adapter-per-tool architecture — each adapter is small and independently
  testable against **fixture files** committed to the repo (real session files
  with content scrubbed), because exact paths/formats drift across versions:
  1. **Claude Code** — `~/.claude/projects/**/*.jsonl` (best-documented, first).
  2. **Cursor** — workspace storage / SQLite chat DB.
  3. **Codex**, **opencode**, **Droid** — their session dirs (JSON).
- File watching (debounced) + periodic full scan; incremental parsing state so
  large histories aren't re-read; project/repo attribution → `conversation.project`.
- Packaging: `pipx`/single-binary install; runs as user service (launchd/systemd).

### 3.2 Export importer (Tier C)
- Web upload (ZIP) in settings → parser per format → canonical schema:
  ChatGPT `conversations.json`, Claude export, Gemini Takeout; DeepSeek/others
  as formats are obtained.
- Idempotent merge with anything already captured (agent/extension/native) —
  re-importing never duplicates; import report UI (N conversations, M new,
  K merged, errors listed).

### 3.3 Browser extension (Tier B)
- MV3 extension in `apps/extension`; **allowlisted domains only**, per-site
  capture toggle, visible capture indicator.
- Content scripts per site (chatgpt.com, gemini.google.com, claude.ai,
  chat.deepseek.com, MiniMax, Qwen) extracting messages from the conversation
  view as rendered; site adapters isolated so one vendor's redesign breaks only
  that adapter. Treat as best-effort by design — the importer covers gaps.
- Local buffering in IndexedDB; batched push to `/ingest` with the device token;
  retry with backoff when the backend is unreachable.

### 3.4 Sync triggers
- Scheduled re-scan/re-summarize every N minutes (configurable in settings).
- **On-demand freshness:** opening a new Nexus chat forces `POST /sync` for
  relevant sources first, so injected context is current.
- Sources dashboard in settings: last-synced per source, error states, counts.

**Exit criteria**
- [ ] Claude Code + Cursor sessions appear in Nexus within a sync cycle of finishing them; re-syncing never duplicates.
- [ ] A real ChatGPT export ZIP imports cleanly, merges with previously captured data, and shows an accurate import report.
- [ ] Extension captures a live conversation on at least ChatGPT + Claude.ai, only on toggled-on sites.
- [ ] Unified search now spans coding-tool, web-chat, imported, and native history.

---

## Phase 4 — Assistant / planning layer (2 weeks)

**Objective:** turn memory into direction: tasks, goals, the Today view,
loose-ends detection, weekly review.

### 4.1 Task & goal extraction
- LLM extraction pass over new/updated conversations → upsert `task` rows
  (title, detail, status, priority, due_at, `why_it_matters`,
  `source_conversation_id`); confidence threshold + dedupe against existing
  open tasks so re-processing doesn't spawn near-duplicates.
- Manual CRUD everywhere extraction happens: `GET/POST /tasks`,
  `PATCH /tasks/:id`; `goal` + `goal_task` linking (`GET/POST /goals`).

### 4.2 Today view
- `GET /today`: ranked recommendations scoring open tasks by due date,
  priority, staleness, and goal linkage. Each item carries its *why*
  ("You started X 5 days ago and left it unfinished").
- UI: Today panel on the dashboard + a task board (todo/doing/blocked/done).

### 4.3 Loose-ends detector
- Heuristic + LLM classification of conversations that end mid-task with no
  follow-up activity in any source; surfaces as dismissible suggestions
  (dismiss = feedback that tunes the threshold).

### 4.4 Weekly review & goal tracking
- Scheduled job: cross-tool weekly summary (what you worked on, per project,
  across every source) rendered as a reviewable document.
- Goal progress rollups from linked task completion; goal UI with horizon
  (day/week/month/quarter) and target dates.

**Exit criteria**
- [ ] Tasks extracted from real conversations are accurate enough to act on without heavy pruning (spot-check ≥80% keep rate).
- [ ] Today view gives a defensible ranked list each morning, with reasons.
- [ ] Loose-ends surfaces genuinely forgotten threads; dismissals stick.
- [ ] A week of use produces a weekly review that reads true.

---

## Phase 5 — Handoff + MCP (2 weeks+)

**Objective:** close the loop — move work *out* of Nexus into the tool that will
do it, carrying full context.

### 5.1 Context packages ("Continue in ___")
- `POST /handoff`: given a task/conversation + target tool, generate a formatted
  brief — goal, relevant history, current state, explicit next steps — using the
  same retrieval stack as context injection, packed to the target's practical
  paste size.
- Handoff composer UI: pick target → preview brief → edit → copy. Per-target
  formatting templates (Claude Code, Cursor, ChatGPT, ...).

### 5.2 Local handoff via companion agent
- Agent gains one *write* capability, explicit and narrowly scoped: write a
  primer file (e.g. `NEXUS_BRIEF.md`) into a chosen repo, and optionally launch
  a Claude Code / opencode session seeded with the brief. Off by default;
  enabled per-machine in agent config.

### 5.3 Nexus as an MCP server
- `/mcp` endpoint exposing memory to MCP-capable clients (Claude Code, Cursor):
  - **Tools:** `search_memory`, `get_profile`, `get_open_tasks`,
    `get_conversation`, `log_handoff`.
  - Same auth (device token) and the same retrieval stack as everything else.
- Setup docs for wiring Claude Code and Cursor to it. This is the cleanest
  long-term handoff path and supersedes copy-paste over time.

### 5.4 v1 hardening pass
- Security review against spec §13 (key handling, agent scope, extension
  allowlist, auth surface); dependency audit.
- Backup/restore documentation (pg_dump + master-key handling).
- Cut `v1.0` with upgrade notes.

**Exit criteria**
- [ ] "Continue in Claude Code" on a real task produces a brief good enough that the session needs no manual context re-explaining.
- [ ] Claude Code, connected via MCP, can pull profile/tasks/search live from Nexus.
- [ ] Primer-file handoff works end-to-end on a local repo, and is off unless explicitly enabled.
- [ ] Security checklist from spec §13 fully passes.

---

## Cross-cutting concerns (all phases)

- **Cost control:** every LLM/embedding call goes through the budget system from
  Phase 1; summarization/embedding/extraction models are independently
  configurable so cheap models can do bulk work (spec §15).
- **Testing:** parsers and adapters (the fragile surface) are fixture-tested;
  gateway adapters get contract tests with recorded responses; retrieval gets a
  small relevance regression set once Phase 2 lands.
- **Privacy:** no telemetry, no third-party calls except the providers you key
  in; everything self-hosted (spec §13).
- **Vendor fragility:** anything touching vendor formats (agent adapters,
  extension site scripts, export parsers) is isolated behind small modules with
  fixtures, so breakage is contained and fixable in one place (spec §15).

## Key risks & mitigations (from spec §15)

| Risk | Mitigation |
|---|---|
| Local log paths/formats drift across tool versions | One small adapter per tool, fixture-tested; agent reports parse failures to the sources dashboard instead of failing silently |
| Browser capture is vendor-fragile | Treated as best-effort; export importer (built *before* the extension) guarantees completeness |
| Embedding/summarization cost on large histories | Budget caps, cheap-model configuration, incremental processing, batch backfill with a dry-run cost estimate |
| Chinese-model API access (region/endpoint) | Endpoint config per provider adapter; OpenRouter as fallback route; history via Tiers B/C regardless |
