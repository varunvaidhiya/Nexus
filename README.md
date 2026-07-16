# Nexus — Personal AI Control Tower

> Self-hosted, single-user. One private app that aggregates your AI activity across
> every tool into one memory, lets you chat with any provider using your own keys,
> hands off tasks with enriched context, and acts as a goal-tracking personal assistant.

**Status: 🚧 Planning / pre-implementation.** See the
[Implementation Plan](docs/IMPLEMENTATION_PLAN.md) and the
[Product Spec](docs/SPEC.md).

---

## Quickstart

```bash
cp .env.example .env   # set POSTGRES_PASSWORD (and anything else you want to override)
docker compose up --build
```

- Web UI: http://localhost:3000
- API: http://localhost:8000/healthz
- Postgres (pgvector): localhost:5432

For per-app development outside Docker, see [apps/web](apps/web/README.md) and
[apps/api](apps/api/README.md).

## The problem

Your AI work is scattered across ChatGPT, Gemini, Claude, DeepSeek, MiniMax, and
coding agents (Claude Code, Cursor, Codex, Droid, opencode). No single tool has the
full picture, so context is lost, tasks are forgotten, and unfinished work is wasted.

## What Nexus does

1. **Ingests** activity from all of these tools into one canonical store.
2. **Builds a cross-platform memory** that "understands you" better than any single app —
   embeddings, summaries, distilled facts, and a rolling profile.
3. **Chats with any provider** (Anthropic, OpenAI, Gemini, DeepSeek, MiniMax, Qwen,
   Mistral, xAI, OpenRouter) using your own encrypted keys, with optional full-context injection.
4. **Hands off tasks** to other tools with a portable context package — or serves live
   context to any MCP-capable client (Claude Code, Cursor) as an MCP server.
5. **Tells you what to do today** — ranked recommendations, loose-ends detection,
   goal tracking, and weekly reviews.

## How ingestion works (the feasibility model)

"Fetch all my chats" is not uniformly possible, so sources are handled by reliability tier:

| Tier | Sources | Mechanism | Reliability |
|---|---|---|---|
| **A — Local logs** | Claude Code, Cursor, Codex, opencode, Droid | Companion agent reads on-disk session files and watches for changes | High |
| **B — Browser capture** | ChatGPT, Gemini, Claude.ai, DeepSeek, MiniMax, Qwen | MV3 browser extension captures conversations as you view them | Medium |
| **C — Manual export** | Any of the above | Drag-drop official data-export ZIP into the importer | High, but not live |
| **D — Native** | Chats started inside Nexus | Fully owned from creation | Highest |

**Principle:** never depend on undocumented vendor "get my history" endpoints — they
break constantly. Tiers A + B + D are the backbone; C is the backfill.

## Architecture at a glance

```
                 ┌───────────────────────── Tier A ─────────┐
Local machine →  │ Companion agent (daemon)                  │
                 │  • scans ~/.claude, ~/.cursor, codex logs │
                 │  • normalizes → POST /ingest              │──┐
                 └───────────────────────────────────────────┘  │
                 ┌───────────────────────── Tier B ─────────┐   │
Browser       →  │ MV3 extension (content scripts)           │───┤
                 └───────────────────────────────────────────┘  │
                 ┌───────────────────────── Tier C ─────────┐   │
Manual        →  │ Export importer (web upload)              │───┤
                 └───────────────────────────────────────────┘  │
                                                                ▼
        ┌──────────────────────────── BACKEND ────────────────────────────┐
        │  Normalizer → canonical Conversation/Message                    │
        │  Context engine: embeddings (pgvector), summaries, rolling      │
        │      profile, entity/task/goal extraction                       │
        │  Provider gateway: multi-provider chat with encrypted keys      │
        │  Assistant engine: "today" plan, loose ends, weekly review      │
        │  Handoff service: context packages + MCP server                 │
        └───────────────┬──────────────────────────────────────────────────┘
                        ▼
        ┌──────────────────────── FRONTEND (Next.js) ─────────────────────┐
        │ Dashboard · Unified search · Multi-provider chat · Today ·      │
        │ Goals · Handoff composer · Sources & keys settings              │
        └──────────────────────────────────────────────────────────────────┘
```

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | Next.js, React, Tailwind, shadcn/ui |
| Backend | FastAPI (Python) — favored for AI/embeddings work |
| Database | Postgres + pgvector |
| Jobs | Celery / APScheduler for scans + summarization |
| Companion agent | Small read-only daemon (Node or Python) |
| Browser extension | Chrome/Edge Manifest V3 |
| Embeddings | Any provider you key in (e.g. OpenAI `text-embedding-3`, or local) |
| Hosting | Self-hosted via Docker Compose — all data stays private |

## Repository layout (planned)

```
nexus/
├── apps/
│   ├── web/          # Next.js frontend
│   ├── api/          # FastAPI backend (ingest, chat, context engine, MCP)
│   ├── agent/        # Companion agent (Tier A local-log watcher)
│   └── extension/    # MV3 browser extension (Tier B capture)
├── packages/
│   └── schema/       # Shared canonical types (Conversation/Message/...)
├── docs/
│   ├── SPEC.md                  # Product spec / PRD
│   └── IMPLEMENTATION_PLAN.md   # Phase-by-phase build plan
├── docker-compose.yml           # Postgres+pgvector, api, web, worker
└── README.md
```

## Roadmap

| Phase | Deliverable | Est. |
|---|---|---|
| **0 — Foundation** | Repo, Next.js, Postgres+pgvector, schema, encrypted keys, settings | 1–2 wk |
| **1 — Native chat** | Provider gateway, chat UI, auto-capture. **First usable product.** | 2 wk |
| **2 — Context engine** | Embeddings, unified semantic search, summaries, rolling profile | 2 wk |
| **3 — Ingestion** | Companion agent → browser extension → export importer | 3–4 wk |
| **4 — Assistant** | Task/goal extraction, Today view, loose ends, weekly review | 2 wk |
| **5 — Handoff + MCP** | Context packages, Nexus-as-MCP-server | 2 wk+ |

The recommended first ship is **Phase 0 + 1**: a great multi-provider chat that captures
everything going forward. It is immediately useful and needs zero risky scraping, while
Phases 2–3 build the cross-tool memory on top.

Full details, task breakdowns, and exit criteria per phase:
**[docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)**.

## Security & privacy posture

This app stores *all* of your AI conversations — it is highly sensitive by design.

- Provider keys are **encrypted at rest** (envelope encryption; master key from env,
  never in the DB), never logged, never returned to the client in plaintext.
- The companion agent is **read-only** on local logs and authenticates with a device token over TLS.
- The extension only runs on **allowlisted domains**, with a per-site capture toggle.
- The whole stack runs behind your own auth, on your own machine or VPS. Private
  deployment is the default; there is no hosted/multi-user mode in v1.

## Non-goals (v1)

Multi-user SaaS, mobile-native app, fully automated remote control of third-party
tools, real-time collaboration.
