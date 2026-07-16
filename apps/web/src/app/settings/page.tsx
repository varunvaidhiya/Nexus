"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ApiError,
  apiFetch,
  clearToken,
  getToken,
  type Provider,
} from "@/lib/api";

export default function SettingsPage() {
  const router = useRouter();
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setProviders(await apiFetch<Provider[]>("/providers"));
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load.");
    }
  }, [router]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    // Defer so no setState runs synchronously inside the effect body.
    const load = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(load);
  }, [refresh, router]);

  function logout() {
    clearToken();
    router.push("/login");
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-6 py-16">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
          <p className="text-muted-foreground text-sm">
            Provider keys & budgets. Keys are encrypted at rest and never shown
            again.
          </p>
        </div>
        <Button variant="ghost" onClick={logout}>
          Log out
        </Button>
      </header>

      {error && <p className="text-destructive text-sm">{error}</p>}

      <AddKeyCard onSaved={refresh} />

      <section className="flex flex-col gap-4">
        <h2 className="text-lg font-medium">Configured providers</h2>
        {providers === null ? (
          <p className="text-muted-foreground text-sm">Loading…</p>
        ) : providers.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            No provider keys yet — add one above to start chatting.
          </p>
        ) : (
          providers.map((p) => (
            <ProviderCard key={p.id} provider={p} onChanged={refresh} />
          ))
        )}
      </section>
    </div>
  );
}

function AddKeyCard({ onSaved }: { onSaved: () => Promise<void> }) {
  const [provider, setProvider] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [models, setModels] = useState("");
  const [budget, setBudget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/providers/keys", {
        method: "POST",
        body: JSON.stringify({
          provider: provider.trim().toLowerCase(),
          api_key: apiKey,
          models: models
            .split(",")
            .map((m) => m.trim())
            .filter(Boolean),
          monthly_budget_usd: budget.trim() === "" ? null : budget.trim(),
        }),
      });
      setProvider("");
      setApiKey("");
      setModels("");
      setBudget("");
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save key.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Add or rotate a provider key</CardTitle>
        <CardDescription>
          e.g. anthropic, openai, openrouter, deepseek, gemini. Re-adding a
          provider replaces its key.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={save} className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-2">
              <Label htmlFor="provider">Provider</Label>
              <Input
                id="provider"
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                placeholder="anthropic"
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="apiKey">API key</Label>
              <Input
                id="apiKey"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-…"
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="models">Models (comma-separated, optional)</Label>
              <Input
                id="models"
                value={models}
                onChange={(e) => setModels(e.target.value)}
                placeholder="claude-sonnet-5, claude-haiku-4-5"
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="budget">Monthly budget USD (optional)</Label>
              <Input
                id="budget"
                type="number"
                min="0"
                step="0.01"
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
                placeholder="25.00"
              />
            </div>
          </div>
          {error && <p className="text-destructive text-sm">{error}</p>}
          <Button
            type="submit"
            disabled={busy}
            className="self-start"
            data-testid="save-key"
          >
            {busy ? "Saving…" : "Save key"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function ProviderCard({
  provider,
  onChanged,
}: {
  provider: Provider;
  onChanged: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);

  async function remove() {
    setBusy(true);
    try {
      await apiFetch(`/providers/keys/${provider.provider}`, {
        method: "DELETE",
      });
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-mono">{provider.provider}</CardTitle>
        <CardDescription>
          {provider.models.length > 0
            ? provider.models.join(" · ")
            : "no models pinned"}
          {" — "}
          spend ${provider.spend_usd}
          {provider.monthly_budget_usd
            ? ` of $${provider.monthly_budget_usd}/mo`
            : " (no budget cap)"}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button
          variant="destructive"
          size="sm"
          onClick={remove}
          disabled={busy}
        >
          {busy ? "Removing…" : "Remove key"}
        </Button>
      </CardContent>
    </Card>
  );
}
