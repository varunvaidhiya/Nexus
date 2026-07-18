"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { apiFetch, apiUpload } from "@/lib/api";

interface Source {
  id: string;
  name: string;
  kind: string;
  ingest_tier: string;
  last_synced_at: string | null;
  conversation_count: number;
  message_count: number;
}

interface ImportReport {
  source_kind: string;
  conversations: number;
  new_conversations: number;
  new_messages: number;
  skipped_messages: number;
}

export function SourcesSection() {
  const [sources, setSources] = useState<Source[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setSources(await apiFetch<Source[]>("/sources"));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sources.");
    }
  }, []);

  useEffect(() => {
    const load = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(load);
  }, [refresh]);

  return (
    <section className="flex flex-col gap-4" data-testid="sources-section">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-medium">Sources</h2>
          <p className="text-muted-foreground text-sm">
            Everything feeding your memory: native chat, the companion agent,
            imports, and the browser extension.
          </p>
        </div>
        <SyncNowButton />
      </div>

      {error && <p className="text-destructive text-sm">{error}</p>}

      {sources === null ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : sources.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          Nothing ingested yet — chat natively, run the agent, or import an
          export below.
        </p>
      ) : (
        <div className="flex flex-col gap-1 font-mono text-xs">
          {sources.map((source) => (
            <div
              key={source.id}
              className="flex gap-2"
              data-testid="source-row"
            >
              <span className="w-8">{source.ingest_tier}</span>
              <span className="w-44 truncate">{source.name}</span>
              <span className="w-40 text-right">
                {source.conversation_count} conversations ·{" "}
                {source.message_count} messages
              </span>
              <span className="text-muted-foreground">
                {source.last_synced_at
                  ? `synced ${new Date(source.last_synced_at).toLocaleString()}`
                  : "never synced"}
              </span>
            </div>
          ))}
        </div>
      )}

      <ImportCard onImported={refresh} />
    </section>
  );
}

function SyncNowButton() {
  const [busy, setBusy] = useState(false);
  const [kicked, setKicked] = useState(false);

  async function sync() {
    setBusy(true);
    try {
      await apiFetch("/sync", { method: "POST" });
      setKicked(true);
      setTimeout(() => setKicked(false), 3000);
    } catch {
      // Non-fatal: worker will run on its own schedule anyway.
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button variant="outline" size="sm" onClick={sync} disabled={busy}>
      {kicked ? "Sync started" : busy ? "…" : "Sync now"}
    </Button>
  );
}

function ImportCard({ onImported }: { onImported: () => Promise<void> }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function upload(event: React.FormEvent) {
    event.preventDefault();
    const file = fileInput.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      setReport(await apiUpload<ImportReport>("/import", file));
      if (fileInput.current) fileInput.current.value = "";
      await onImported();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Import an export</CardTitle>
        <CardDescription>
          ChatGPT or Claude data export — the ZIP as downloaded, or its
          conversations.json. Re-importing never duplicates.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={upload} className="flex items-center gap-4">
          <input
            ref={fileInput}
            type="file"
            accept=".zip,.json"
            required
            className="text-sm"
            data-testid="import-file"
          />
          <Button type="submit" disabled={busy} data-testid="import-submit">
            {busy ? "Importing…" : "Import"}
          </Button>
        </form>
        {error && <p className="text-destructive mt-3 text-sm">{error}</p>}
        {report && (
          <p className="mt-3 text-sm" data-testid="import-report">
            Imported from {report.source_kind}: {report.conversations}{" "}
            conversations seen, {report.new_conversations} new,{" "}
            {report.new_messages} new messages, {report.skipped_messages}{" "}
            already known.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
