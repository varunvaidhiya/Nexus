"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { ApiError, apiFetch, getToken } from "@/lib/api";
import { getTasks, type Task } from "@/lib/assistant";

const TARGETS = [
  { key: "claude_code", label: "Claude Code" },
  { key: "cursor", label: "Cursor" },
  { key: "chatgpt", label: "ChatGPT" },
  { key: "generic", label: "Other" },
] as const;

interface HandoffResponse {
  id: string;
  target: string;
  brief: string;
}

export default function HandoffPage() {
  return (
    <Suspense>
      <HandoffComposer />
    </Suspense>
  );
}

function HandoffComposer() {
  const router = useRouter();
  const params = useSearchParams();
  const conversationId = params.get("conversation");

  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskId, setTaskId] = useState(params.get("task") ?? "");
  const [target, setTarget] = useState<string>("claude_code");
  const [instructions, setInstructions] = useState("");
  const [brief, setBrief] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    const load = setTimeout(async () => {
      try {
        setTasks((await getTasks()).filter((task) => task.status !== "done"));
      } catch (err) {
        if (err instanceof ApiError && err.status === 401)
          router.push("/login");
      }
    }, 0);
    return () => clearTimeout(load);
  }, [router]);

  async function generate(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await apiFetch<HandoffResponse>("/handoff", {
        method: "POST",
        body: JSON.stringify({
          target,
          task_id: taskId || null,
          conversation_id: conversationId,
          instructions: instructions.trim() || null,
        }),
      });
      setBrief(response.brief);
      setCopied(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate.");
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (brief) {
      await navigator.clipboard.writeText(brief);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-6 py-16">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Hand off</h1>
          <p className="text-muted-foreground text-sm">
            Package the context and continue this work in another tool.
          </p>
        </div>
        <Button variant="ghost" render={<Link href="/today" />}>
          Back to Today
        </Button>
      </header>

      <form onSubmit={generate} className="flex flex-col gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="target">Continue in</Label>
            <select
              id="target"
              className="h-9 rounded-md border bg-transparent px-2 text-sm"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              data-testid="handoff-target"
            >
              {TARGETS.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="task">Task</Label>
            <select
              id="task"
              className="h-9 rounded-md border bg-transparent px-2 text-sm"
              value={taskId}
              onChange={(e) => setTaskId(e.target.value)}
              data-testid="handoff-task"
            >
              <option value="">
                {conversationId ? "(none — conversation only)" : "Pick a task…"}
              </option>
              {tasks.map((task) => (
                <option key={task.id} value={task.id}>
                  {task.title}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="instructions">Extra instructions (optional)</Label>
          <textarea
            id="instructions"
            className="min-h-20 rounded-md border bg-transparent p-2 text-sm"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder="Anything the next tool should know or do first…"
          />
        </div>
        {error && <p className="text-destructive text-sm">{error}</p>}
        <Button
          type="submit"
          disabled={busy || (!taskId && !conversationId)}
          className="self-start"
          data-testid="handoff-generate"
        >
          {busy ? "Generating…" : "Generate brief"}
        </Button>
      </form>

      {brief !== null && (
        <section className="flex flex-col gap-3" data-testid="handoff-brief">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-medium">Brief — edit, then copy</h2>
            <Button
              variant="outline"
              size="sm"
              onClick={copy}
              data-testid="handoff-copy"
            >
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
          <textarea
            className="min-h-96 rounded-md border bg-transparent p-3 font-mono text-xs"
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
          />
          <p className="text-muted-foreground text-sm">
            Paste it into the target tool — or on a machine running the
            companion agent:{" "}
            <code className="bg-muted rounded px-1 py-0.5">
              nexus-agent handoff --repo &lt;path&gt;
              {taskId ? ` --task ${taskId}` : ""}
            </code>
          </p>
        </section>
      )}
    </div>
  );
}
