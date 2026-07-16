import { getToken } from "@/lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ChatRequestBody {
  conversation_id?: string;
  provider: string;
  model: string;
  message: string;
}

export interface DoneEvent {
  message_id: string | null;
  stop_reason: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: string;
  spend_usd: string | null;
  monthly_budget_usd: string | null;
}

export interface StreamError {
  kind: string;
  provider?: string;
  message: string;
  retryable?: boolean;
}

export interface ChatCallbacks {
  onMeta: (conversationId: string) => void;
  onDelta: (text: string) => void;
  onDone: (done: DoneEvent) => void;
  onError: (error: StreamError) => void;
}

/** POST /chat and dispatch its SSE events. Resolves when the stream ends. */
export async function streamChat(
  body: ChatRequestBody,
  callbacks: ChatCallbacks,
  signal: AbortSignal,
): Promise<void> {
  const token = getToken();
  const response = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok || !response.body) {
    let detail: StreamError = {
      kind: "server",
      message: response.statusText || "request failed",
    };
    try {
      const parsed = (await response.json()) as {
        detail?: StreamError | string;
      };
      if (typeof parsed.detail === "object" && parsed.detail !== null) {
        detail = parsed.detail;
      } else if (typeof parsed.detail === "string") {
        detail = { kind: "server", message: parsed.detail };
      }
    } catch {
      // keep the statusText fallback
    }
    if (response.status === 401) detail = { ...detail, kind: "unauthorized" };
    callbacks.onError(detail);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName: string | null = null;

  const handle = (name: string, payload: string) => {
    const data = JSON.parse(payload) as Record<string, unknown>;
    if (name === "meta") {
      callbacks.onMeta(data.conversation_id as string);
    } else if (name === "delta") {
      callbacks.onDelta(data.text as string);
    } else if (name === "done") {
      callbacks.onDone(data as unknown as DoneEvent);
    } else if (name === "error") {
      callbacks.onError(data as unknown as StreamError);
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newlineIndex: number;
    while ((newlineIndex = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newlineIndex).replace(/\r$/, "");
      buffer = buffer.slice(newlineIndex + 1);
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:") && eventName) {
        handle(eventName, line.slice(5).trim());
      } else if (line === "") {
        eventName = null;
      }
    }
  }
}
