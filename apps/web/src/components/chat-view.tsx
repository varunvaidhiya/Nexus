"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, apiFetch, getToken, type Provider } from "@/lib/api";
import { streamChat, type DoneEvent } from "@/lib/chat";

interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

interface ConversationDetail {
  id: string;
  title: string | null;
  model: string | null;
  messages: { role: string; content: string }[];
}

const LAST_PROVIDER_KEY = "nexus_last_provider";
const LAST_MODEL_KEY = "nexus_last_model";

export function ChatView({ conversationId }: { conversationId?: string }) {
  const router = useRouter();
  const [currentId, setCurrentId] = useState(conversationId ?? null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [budget, setBudget] = useState<{
    spend: string;
    limit: string | null;
  } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    const load = setTimeout(async () => {
      try {
        const list = await apiFetch<Provider[]>("/providers");
        setProviders(list);
        const savedProvider = localStorage.getItem(LAST_PROVIDER_KEY);
        const initial =
          list.find((p) => p.provider === savedProvider) ?? list[0];
        if (initial) {
          setProvider(initial.provider);
          setModel(
            localStorage.getItem(LAST_MODEL_KEY) ?? initial.models[0] ?? "",
          );
          setBudget({
            spend: initial.spend_usd,
            limit: initial.monthly_budget_usd,
          });
        }
        if (conversationId) {
          const detail = await apiFetch<ConversationDetail>(
            `/conversations/${conversationId}`,
          );
          setTurns(
            detail.messages
              .filter((m) => m.role === "user" || m.role === "assistant")
              .map((m) => ({
                role: m.role as "user" | "assistant",
                content: m.content,
              })),
          );
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load.");
      }
    }, 0);
    return () => clearTimeout(load);
  }, [conversationId, router]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  const selectedProvider = providers.find((p) => p.provider === provider);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    const message = input.trim();
    if (!message || streaming || !provider || !model) return;

    localStorage.setItem(LAST_PROVIDER_KEY, provider);
    localStorage.setItem(LAST_MODEL_KEY, model);
    setError(null);
    setInput("");
    setStreaming(true);
    setTurns((prev) => [
      ...prev,
      { role: "user", content: message },
      { role: "assistant", content: "" },
    ]);

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamChat(
        {
          conversation_id: currentId ?? undefined,
          provider,
          model,
          message,
        },
        {
          onMeta: (id) => {
            setCurrentId(id);
            // Keep the URL shareable without remounting mid-stream.
            window.history.replaceState(null, "", `/chat/${id}`);
          },
          onDelta: (text) =>
            setTurns((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              next[next.length - 1] = {
                ...last,
                content: last.content + text,
              };
              return next;
            }),
          onDone: (done: DoneEvent) => {
            if (done.spend_usd) {
              setBudget({
                spend: done.spend_usd,
                limit: done.monthly_budget_usd,
              });
            }
          },
          onError: (err) => {
            if (err.kind === "unauthorized") {
              router.push("/login");
              return;
            }
            setError(`${err.kind}: ${err.message}`);
          },
        },
        controller.signal,
      );
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setError(err instanceof Error ? err.message : "Stream failed.");
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
      // Drop an empty assistant bubble if nothing arrived.
      setTurns((prev) =>
        prev.length && prev[prev.length - 1].content === ""
          ? prev.slice(0, -1)
          : prev,
      );
    }
  }

  function stop() {
    abortRef.current?.abort();
  }

  return (
    <div className="mx-auto flex h-dvh w-full max-w-3xl flex-col px-6 py-6">
      <header className="flex items-center justify-between gap-2 border-b pb-4">
        <Button variant="ghost" size="sm" render={<Link href="/chat" />}>
          ← Conversations
        </Button>
        <div className="flex items-center gap-2 text-sm">
          {budget && (
            <span className="text-muted-foreground" data-testid="budget">
              ${Number(budget.spend).toFixed(2)}
              {budget.limit
                ? ` / $${Number(budget.limit).toFixed(2)}`
                : ""}{" "}
              this month
            </span>
          )}
          <Button
            variant="outline"
            size="sm"
            disabled
            title="Coming in Phase 2"
          >
            Context: clean
          </Button>
        </div>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto py-4">
        {turns.length === 0 && (
          <p className="text-muted-foreground pt-8 text-center text-sm">
            Pick a provider and model below, then say something.
          </p>
        )}
        {turns.map((turn, index) => (
          <div
            key={index}
            className={turn.role === "user" ? "flex justify-end" : "flex"}
          >
            <div
              className={
                turn.role === "user"
                  ? "bg-primary text-primary-foreground max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap"
                  : "bg-muted max-w-[85%] rounded-lg px-3 py-2 text-sm"
              }
            >
              {turn.role === "assistant" ? (
                <div className="prose-chat">
                  <ReactMarkdown>
                    {turn.content ||
                      (streaming && index === turns.length - 1 ? "…" : "")}
                  </ReactMarkdown>
                  {turn.content && (
                    <button
                      type="button"
                      className="text-muted-foreground mt-1 block text-xs hover:underline"
                      onClick={() =>
                        navigator.clipboard.writeText(turn.content)
                      }
                    >
                      Copy
                    </button>
                  )}
                </div>
              ) : (
                turn.content
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {error && <p className="text-destructive pb-2 text-sm">{error}</p>}

      <form onSubmit={send} className="flex flex-col gap-2 border-t pt-4">
        <div className="flex gap-2">
          <select
            className="border-input bg-background h-8 rounded-lg border px-2 text-sm"
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value);
              const p = providers.find((x) => x.provider === e.target.value);
              if (p) {
                setModel(p.models[0] ?? "");
                setBudget({ spend: p.spend_usd, limit: p.monthly_budget_usd });
              }
            }}
            aria-label="Provider"
          >
            {providers.length === 0 && <option value="">no keys</option>}
            {providers.map((p) => (
              <option key={p.provider} value={p.provider}>
                {p.provider}
              </option>
            ))}
          </select>
          <Input
            className="h-8 flex-1 font-mono text-sm"
            list="model-suggestions"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="model id"
            aria-label="Model"
          />
          <datalist id="model-suggestions">
            {(selectedProvider?.models ?? []).map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </div>
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              providers.length === 0
                ? "Add a provider key in settings first"
                : "Message…"
            }
            disabled={streaming || providers.length === 0}
            autoFocus
          />
          {streaming ? (
            <Button type="button" variant="destructive" onClick={stop}>
              Stop
            </Button>
          ) : (
            <Button
              type="submit"
              disabled={!input.trim() || !provider || !model}
            >
              Send
            </Button>
          )}
        </div>
      </form>
    </div>
  );
}
