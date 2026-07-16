/**
 * TypeScript binding of ingest.v1.schema.json — keep in lockstep with that
 * file. The JSON Schema is the source of truth.
 */

export const SCHEMA_VERSION = "nexus.ingest.v1" as const;

export type SourceKind =
  | "claude_code"
  | "cursor"
  | "codex"
  | "opencode"
  | "droid"
  | "chatgpt"
  | "gemini"
  | "claude_web"
  | "deepseek"
  | "minimax"
  | "qwen"
  | "native"
  | "import";

export type IngestTier = "A" | "B" | "C" | "D";

export type MessageRole = "user" | "assistant" | "tool" | "system";

export interface IngestSource {
  kind: SourceKind;
  /** Human-readable label, e.g. the machine or profile the data came from. */
  name?: string | null;
  ingest_tier: IngestTier;
}

export interface IngestMessage {
  /** Message ID in the source system, when it has one. */
  external_id?: string | null;
  role: MessageRole;
  content: string;
  token_count?: number | null;
  /** ISO 8601 date-time. */
  created_at?: string | null;
}

export interface IngestConversation {
  /** Stable ID in the source system; dedupe key together with the source. */
  external_id: string;
  title?: string | null;
  model?: string | null;
  tool?: string | null;
  /** Repo/workspace attribution if known. */
  project?: string | null;
  /** ISO 8601 date-time. */
  started_at?: string | null;
  /** ISO 8601 date-time. */
  updated_at?: string | null;
  tags?: string[];
  messages: IngestMessage[];
}

export interface IngestBatch {
  schema_version: typeof SCHEMA_VERSION;
  source: IngestSource;
  conversations: IngestConversation[];
}
