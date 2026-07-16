/**
 * Compile-time exercise of the ingest types: a fully-populated literal batch
 * (mirroring fixtures/claude-code-batch.json) plus a minimal one. If the
 * types drift from the shapes producers actually send, this stops compiling.
 * Runs via `npm run typecheck` — no test runner needed.
 */

import { SCHEMA_VERSION, type IngestBatch } from "./index";

const fullBatch: IngestBatch = {
  schema_version: SCHEMA_VERSION,
  source: {
    kind: "claude_code",
    name: "varun-laptop",
    ingest_tier: "A",
  },
  conversations: [
    {
      external_id: "session-2f8a1c3d",
      title: "Fix flaky auth test",
      model: "claude-sonnet-5",
      tool: "claude_code",
      project: "github.com/varunvaidhiya/Nexus",
      started_at: "2026-07-15T09:12:00Z",
      updated_at: "2026-07-15T09:47:33Z",
      tags: ["testing", "auth"],
      messages: [
        {
          external_id: "msg-001",
          role: "user",
          content: "The auth test fails intermittently in CI.",
          created_at: "2026-07-15T09:12:00Z",
        },
        {
          role: "assistant",
          content: "The token expiry races the network call; extending it.",
          token_count: 128,
        },
      ],
    },
  ],
};

// Minimal batch: only required fields.
const minimalBatch: IngestBatch = {
  schema_version: "nexus.ingest.v1",
  source: { kind: "import", ingest_tier: "C" },
  conversations: [{ external_id: "conv-1", messages: [] }],
};

export { fullBatch, minimalBatch };
