# Security review — v1.0 (spec §13)

Nexus is self-hosted and single-user; the whole stack is assumed to run on
your own machine or VPS, behind your own network boundary. This review walks
spec §13's requirements against the v1.0 implementation.

## Provider keys

- Envelope encryption (AES-256-GCM): per-key data keys wrapped by the master
  key from `NEXUS_MASTER_KEY` — the master key is never stored in the
  database (`crypto.py`).
- Plaintext keys never leave the server: `GET /providers` returns provider,
  models, budget, and spend only; keys are excluded from all logging paths.
- Rotation: re-adding a provider replaces its key.

## Auth surface

- Everything except `GET /healthz` requires a bearer token. If
  `NEXUS_AUTH_TOKEN` is unset the API refuses to serve (503) rather than
  running open.
- Device tokens (`nxd_…`) are SHA-256-hashed at rest, shown once at creation,
  revocable individually, and scoped to the companion-tool surface only:
  `/ingest` (write), `/handoff` (brief generation), and `/mcp` (memory
  tools). They cannot reach provider keys, settings, chat, or the rest of
  the API. All token comparisons use constant-time equality
  (`secrets.compare_digest` / hash lookup).
- TLS is assumed for any non-localhost deployment — terminate it in front
  of the API (Caddy/nginx/Tailscale) before exposing device tokens on a
  network.

## Companion agent

- Read-only on tool logs by design; syncing never writes to watched
  directories.
- The single write capability (primer files, spec §5.2) is off by default,
  must be enabled per machine in `nexus-agent.toml`, and writes exactly one
  file (`NEXUS_BRIEF.md`) into a directory the user names explicitly on the
  command line.

## Browser extension

- Allowlisted domains only (`chatgpt.com`, `claude.ai`), per-site toggles,
  read-only content scripts, capture buffered locally and pushed with a
  device token.

## MCP endpoint

- Same device-token gate as ingest; stateless; tools expose read access to
  memory plus `log_handoff` (an insert into the handoff log). No tool
  mutates conversations, tasks, keys, or settings.

## Data at rest

- Conversations, notes, and embeddings are plaintext in Postgres (searchable
  memory is the product); protect the database like the sensitive corpus it
  is — disk encryption and private deployment are the defaults. See
  [OPERATIONS.md](OPERATIONS.md) for backup handling.

## Dependency audit (v1.0, 2026-07-19)

- `pip-audit` on the API environment: no advisories against application
  dependencies (findings were limited to the virtualenv's own pip/setuptools
  tooling, not shipped code).
- `npm audit --omit dev` on the web app: two moderate advisories in the
  `postcss` version bundled inside Next.js itself (GHSA-qx2v-qp2m-jg93);
  the fix ships with Next's own dependency bump — track Next releases. No
  advisories in direct dependencies.

## Known gaps (tracked, not blockers for a private v1.0)

- No rate limiting on auth attempts (single-user, private deployment).
- Web auth token is kept in `localStorage`; acceptable for a private
  deployment, revisit if Nexus is ever exposed publicly.
- Extension pushes over whatever origin you configure — use TLS for
  non-localhost backends.
