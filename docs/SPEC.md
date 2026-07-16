# Nexus — Personal AI Control Tower

**Product spec / PRD · v0.1**
Self-hosted, single-user. Aggregates your AI activity across every tool into one
memory, lets you chat with any provider using your own keys, hands off tasks with
enriched context, and acts as a goal-tracking personal assistant.

> Working name: **Nexus**. Rename freely.

---

## 1. Problem & goal

Your AI work is scattered across ChatGPT, Gemini, Claude, DeepSeek, MiniMax, and
coding agents (Claude Code, Cursor, Codex, Droid, opencode). No single tool has
the full picture, so context is lost, tasks are forgotten, and unfinished work is
wasted.

**Goal:** one private app that (1) ingests activity from all these tools, (2)
builds a cross-platform memory that "understands you" better than any one app,
(3) lets you chat with any provider, (4) hands tasks off to other tools *with*
that context, and (5) tells you what to do today.

**Non-goals (v1):** multi-user SaaS, mobile-native app, fully automated remote
control of third-party tools, real-time collaboration.

---

## 2. The feasibility model (design driver)

"Fetch all my chats" is not uniformly possible. Sources fall into reliability
tiers; the architecture is built around the reliable ones.

| Tier | Sources | Mechanism | Reliability |
|---|---|---|---|
| **A — Local logs** | Claude Code, Cursor, Codex, opencode, Droid | Companion agent reads on-disk session files (JSON/SQLite), watches for changes | High |
| **B — Browser capture** | ChatGPT, Gemini, Claude.ai, DeepSeek, MiniMax, Qwen | MV3 browser extension captures conversations as you view them | Medium |
| **C — Manual export** | Any of the above | Drag-drop official data-export ZIP into importer | High but not live |
| **D — Native** | Chats started inside Nexus | Fully owned from creation | Highest |

**Principle:** never depend on undocumented vendor "get my history" endpoints —
they break constantly. Tier A + B + D are the backbone; C is the backfill.

---

## 3. System architecture

```
                 ┌───────────────────────── Tier A ─────────┐
Local machine →  │ Companion agent (Node/Python daemon)      │
                 │  • scans ~/.claude, ~/.cursor, codex logs │
                 │  • normalizes → POST /ingest              │──┐
                 └───────────────────────────────────────────┘  │
                 ┌───────────────────────── Tier B ─────────┐   │
Browser       →  │ MV3 extension (content scripts)          │   │
                 │  • captures web-chat DOM/network          │───┤
                 └───────────────────────────────────────────┘  │
                 ┌───────────────────────── Tier C ─────────┐   │
Manual        →  │ Export importer (web upload)             │───┤
                 └───────────────────────────────────────────┘  │
                                                                 ▼
        ┌──────────────────────── BACKEND (FastAPI or Next API) ─────────┐
        │  Normalizer → canonical Conversation/Message                    │
        │  Context engine: embeddings (pgvector), summaries, rolling      │
        │      profile, entity/task/goal extraction                       │
        │  Provider gateway: Anthropic/OpenAI/Gemini/DeepSeek/MiniMax/     │
        │      Qwen/OpenRouter with your encrypted keys                    │
        │  Assistant engine: "today" plan, loose-ends, weekly review      │
        │  Handoff service: context package + MCP server                  │
        └───────────────┬─────────────────────────────────────────────────┘
                        ▼
        ┌──────────────────────── FRONTEND (Next.js) ───────────────────┐
        │ Dashboard · Unified search · Multi-provider chat · Today ·     │
        │ Goals · Handoff composer · Sources & keys settings             │
        └─────────────────────────────────────────────────────────────────┘
```

---

## 4. Data model (Postgres + pgvector)

```
source(
  id, name, kind ENUM('claude_code','cursor','codex','opencode','droid',
    'chatgpt','gemini','claude_web','deepseek','minimax','qwen','native','import'),
  ingest_tier CHAR,  -- A/B/C/D
  auth_meta JSONB, last_synced_at, created_at )

conversation(
  id, source_id FK, external_id, title, model, tool,
  project TEXT,           -- repo/workspace if known
  started_at, updated_at, tags TEXT[], summary TEXT )

message(
  id, conversation_id FK, role ENUM('user','assistant','tool','system'),
  content TEXT, token_count INT, created_at,
  embedding VECTOR(1536) )   -- pgvector

entity(
  id, kind ENUM('project','person','repo','topic','decision'),
  name, description, embedding VECTOR(1536), first_seen, last_seen )

conversation_entity( conversation_id FK, entity_id FK )   -- join

task(
  id, title, detail, status ENUM('todo','doing','blocked','done'),
  priority INT, due_at, source_conversation_id FK,
  why_it_matters TEXT, created_at, updated_at, completed_at )

goal(
  id, title, horizon ENUM('day','week','month','quarter'),
  progress FLOAT, status, created_at, target_at )

goal_task( goal_id FK, task_id FK )

memory_note(   -- the "understands me" distilled facts
  id, content TEXT, category, confidence FLOAT,
  embedding VECTOR(1536), source_ref, created_at, updated_at )

provider_key(
  id, provider, encrypted_key BYTEA, models TEXT[],
  monthly_budget_usd NUMERIC, spend_usd NUMERIC, created_at )

profile_snapshot(   -- rolling "who you are / what you're working on"
  id, content TEXT, generated_at, token_count )
```

Indexes: `message.embedding` (ivfflat/hnsw), `conversation(source_id, updated_at)`,
`task(status, due_at)`, GIN on `conversation.tags`.

---

## 5. Ingestion connectors (detailed)

### 5.1 Companion agent (Tier A)
- **Form:** small daemon (Node or Python) you run on each machine. Read-only.
- **Watches:** known log locations, e.g.
  - Claude Code: `~/.claude/projects/**/*.jsonl` (session transcripts)
  - Cursor: workspace storage / SQLite chat DB
  - Codex / opencode / Droid: their session dirs (JSON)
  - *(exact paths validated per tool at build time; each gets an adapter)*
- **Flow:** on change → parse → normalize to canonical schema → `POST /ingest`
  with a device token. Dedupe by `(source, external_id, message hash)`.
- **Config:** `nexus-agent.toml` — which tools to watch, backend URL, token.

### 5.2 Browser extension (Tier B)
- **Form:** Chrome/Edge MV3 extension, domain-allowlisted.
- **Capture:** content script observes the conversation view (DOM + network
  responses) on chatgpt.com, gemini.google.com, claude.ai, chat.deepseek.com,
  MiniMax, Qwen. Extracts messages as they render.
- **Sync:** buffers locally (IndexedDB), pushes to `/ingest` over TLS.
- **Privacy:** only allowlisted domains; user toggles per-site capture; nothing
  captured on other pages.

### 5.3 Export importer (Tier C)
- Web upload of official export ZIPs (ChatGPT `conversations.json`, Claude
  export, Gemini Takeout, etc.). One parser per format → canonical schema.
- Idempotent: re-importing merges, never duplicates.

### 5.4 Sync triggers
- **Scheduled:** background job re-scans/re-summarizes every N minutes (config).
- **On-demand:** opening a new chat in Nexus forces a fresh pull of relevant
  sources first, so context is current (your stated requirement).

---

## 6. Context engine ("understands me")

Pipeline (runs on ingest + on schedule):
1. **Summarize** each new/updated conversation → `conversation.summary`.
2. **Embed** messages + summaries into pgvector.
3. **Extract** entities (projects/people/repos/topics/decisions), tasks, goals via
   an LLM pass; upsert into `entity`/`task`/`goal`.
4. **Distill** durable facts about you → `memory_note` (e.g. "prefers TypeScript",
   "working on OmniBot robotics repo", "ships via Vercel").
5. **Rebuild rolling profile** (`profile_snapshot`) periodically: a compact
   document = active projects + preferences + open loops.

**Retrieval (at chat / handoff time):**
`context = rolling_profile + top-K semantically relevant messages + open tasks in
that area + relevant memory_notes`, packed to a token budget.

---

## 7. Multi-provider chat & gateway

- **Adapters:** Anthropic, OpenAI, Google Gemini, DeepSeek, MiniMax, Qwen/Alibaba,
  Mistral, xAI. **OpenRouter** adapter as a shortcut to many models via one key.
- **Interface:** `chat(provider, model, messages, stream) -> tokens`. Streaming
  (SSE) to the UI.
- **Model picker** per conversation; per-provider budget + spend tracking.
- **Every native chat auto-captured** into memory (Tier D — best data, zero
  friction).
- **Context injection toggle:** each chat can run "with my full context" (RAG
  retrieval prepended) or "clean."

---

## 8. Task handoff

Since third-party tools can't be fully driven remotely, handoff = **portable
context package**:
- **"Continue in ___"** button → generates a formatted brief (goal + relevant
  history + current state + explicit next steps) to paste into the target tool.
- **Local tools:** companion agent can write a primer file into the repo or
  launch a Claude Code / opencode session seeded with the brief.
- **MCP server:** Nexus exposes its memory as an **MCP server** so any
  MCP-capable client (Claude Code, Cursor) pulls live context — the cleanest
  long-term path.

---

## 9. Assistant / planning layer

- **Today view:** ranked recommendations from open tasks, due dates, staleness,
  and goals. "You started X 5 days ago and left it unfinished."
- **Loose-ends detector:** conversations that end mid-task with no follow-up.
- **Weekly review:** auto cross-tool summary of what you worked on.
- **Goal tracking:** progress rollups from linked tasks.

---

## 10. API surface (backend)

```
POST   /ingest                  # normalized events from agent/extension/import
GET    /conversations           # list/filter/search
GET    /conversations/:id
GET    /search?q=...            # semantic + keyword unified search
POST   /chat                    # multi-provider, streaming
GET    /providers  POST /providers/keys   # manage encrypted keys
GET    /tasks  POST /tasks  PATCH /tasks/:id
GET    /goals  POST /goals
GET    /today                   # ranked recommendations
POST   /handoff                 # generate context package for target tool
GET    /profile                 # current rolling profile
POST   /sync                    # force re-scan
/mcp                            # MCP server endpoint (Phase 5)
```

---

## 11. Frontend (screens)

- **Dashboard** — activity across all sources, today's plan, loose ends.
- **Unified search** — one box over every message everywhere (semantic + keyword).
- **Chat** — provider/model picker, context toggle, streaming, auto-captured.
- **Today / Goals** — recommendations, task board, goal progress.
- **Handoff composer** — pick target tool → generated brief → copy/launch.
- **Sources & keys** — connect agent/extension, upload exports, manage API keys,
  budgets, sync interval.

Stack: Next.js + React + Tailwind + shadcn/ui.

---

## 12. Tech stack

| Layer | Choice |
|---|---|
| Frontend | Next.js, React, Tailwind, shadcn/ui |
| Backend | FastAPI (Python) *or* Next.js API routes; Python favored for AI/embeddings |
| DB | Postgres + pgvector (Supabase local/self-hosted) |
| Jobs | BullMQ (Node) or Celery/APScheduler (Python) for scans + summarization |
| Companion agent | Node or Python daemon (read-only) |
| Extension | Chrome/Edge MV3 |
| Embeddings | Any provider you key in (OpenAI `text-embedding-3`, or local) |
| Hosting | Self-hosted (Docker Compose) — all data stays private |

---

## 13. Security (self-hosted, single-user)

- Provider keys **encrypted at rest** (envelope encryption; master key from env,
  not in DB). Never logged, never returned to client in plaintext.
- Companion agent: **read-only** on logs; authenticates with a device token;
  TLS to backend.
- Extension: allowlisted domains only; per-site toggle.
- Whole stack runs behind your own auth on your own machine/VPS. This data (all
  your AI chats) is highly sensitive — private deployment is the default.

---

## 14. Roadmap

| Phase | Deliverable | Est. |
|---|---|---|
| **0 Foundation** | Repo, Next.js, Postgres+pgvector, schema, encrypted keys, settings | 1–2 wk |
| **1 Native chat** | Provider gateway (Anthropic/OpenAI/DeepSeek/OpenRouter), chat UI, auto-capture. **Usable product.** | 2 wk |
| **2 Context engine** | Embeddings, unified semantic search, summaries, rolling profile | 2 wk |
| **3 Ingestion** | Companion agent (coding tools) → extension (web chats) → export importer | 3–4 wk |
| **4 Assistant** | Task/goal extraction, Today, loose-ends, weekly review | 2 wk |
| **5 Handoff + MCP** | Context packages, Nexus-as-MCP-server | 2 wk+ |

**Recommended first ship:** Phase 0+1 — a great multi-provider chat that captures
everything going forward. It's immediately useful and needs zero risky scraping,
while Phases 2–3 build the cross-tool memory on top.

---

## 15. Open questions / risks

- **Exact local log paths** per coding tool need per-tool validation (they change
  across versions) — each gets a small, testable adapter.
- **Browser capture** is inherently vendor-fragile; treat as best-effort + lean on
  export importer for completeness.
- **Cost:** embeddings + summarization of large histories cost tokens — add a
  budget cap and let you pick a cheap embedding/summary model.
- **Chinese model API access** may need region/endpoint config (DeepSeek/Qwen have
  official APIs for *new* chats; history still relies on Tier B/C).
```
