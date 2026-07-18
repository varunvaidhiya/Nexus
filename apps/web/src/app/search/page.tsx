"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError, apiFetch, getToken } from "@/lib/api";

interface SearchHit {
  message_id: string;
  conversation_id: string;
  conversation_title: string | null;
  role: string;
  snippet: string;
  created_at: string;
  score: number;
  matched: string;
}

export default function SearchPage() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) router.push("/login");
  }, [router]);

  async function search(event: React.FormEvent) {
    event.preventDefault();
    const q = query.trim();
    if (!q) return;
    setBusy(true);
    setError(null);
    try {
      setHits(
        await apiFetch<SearchHit[]>(
          `/search?q=${encodeURIComponent(q)}&limit=20`,
        ),
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Search failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-16">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Search</h1>
        <Button variant="ghost" render={<Link href="/chat" />}>
          Conversations
        </Button>
      </header>

      <form onSubmit={search} className="flex gap-2">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search every message, everywhere…"
          autoFocus
        />
        <Button type="submit" disabled={busy || !query.trim()}>
          {busy ? "Searching…" : "Search"}
        </Button>
      </form>

      {error && <p className="text-destructive text-sm">{error}</p>}

      {hits !== null && hits.length === 0 && (
        <p className="text-muted-foreground text-sm">No matches.</p>
      )}
      {hits?.map((hit) => (
        <Link key={hit.message_id} href={`/chat/${hit.conversation_id}`}>
          <Card className="hover:bg-muted/50 transition-colors">
            <CardHeader>
              <CardTitle className="text-base">
                {hit.conversation_title ?? "Untitled"}
                <span className="text-muted-foreground ml-2 text-xs font-normal">
                  {hit.matched}
                </span>
              </CardTitle>
              <CardDescription className="line-clamp-3">
                <span className="font-medium">{hit.role}:</span> {hit.snippet}
              </CardDescription>
            </CardHeader>
          </Card>
        </Link>
      ))}
    </div>
  );
}
