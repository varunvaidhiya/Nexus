# packages/schema

Canonical normalized types shared by every ingestion tier and the backend —
the contract for `POST /ingest`.

**Source of truth: [`ingest.v1.schema.json`](ingest.v1.schema.json)** (JSON
Schema, draft 2020-12). The language bindings mirror it and must be updated in
lockstep:

- [`python/`](python/) — `nexus-schema` package (Pydantic v2 models).
- [`typescript/`](typescript/) — `@nexus/schema` package (plain types).

Shared example payloads live in [`fixtures/`](fixtures/). Tests validate every
fixture against **both** the JSON Schema and the Pydantic models (and the
TypeScript side compiles literal equivalents), so drift between the bindings
fails CI.

## Checks

```bash
# Python
cd python && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/pytest

# TypeScript
cd typescript && npm install && npm run typecheck
```

## Evolving the contract

`schema_version` is pinned to `nexus.ingest.v1`. Additive, backward-compatible
changes may extend the v1 schema; anything breaking gets a new
`ingest.v2.schema.json` and a new version constant, with the backend accepting
both during migration.
