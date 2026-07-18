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
import { ApiError, apiFetch, getToken } from "@/lib/api";

interface ConversationSummary {
  id: string;
  title: string | null;
  model: string | null;
  source_kind: string;
  updated_at: string;
  message_count: number;
}

export default function ChatListPage() {
  const router = useRouter();
  const [conversations, setConversations] = useState<
    ConversationSummary[] | null
  >(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    const load = setTimeout(async () => {
      try {
        setConversations(
          await apiFetch<ConversationSummary[]>("/conversations"),
        );
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load.");
      }
    }, 0);
    return () => clearTimeout(load);
  }, [router]);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-16">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Conversations</h1>
        <div className="flex gap-2">
          <Button variant="ghost" render={<Link href="/settings" />}>
            Settings
          </Button>
          <Button render={<Link href="/chat/new" />}>New chat</Button>
        </div>
      </header>

      {error && <p className="text-destructive text-sm">{error}</p>}

      {conversations === null ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : conversations.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          No conversations yet — start one.
        </p>
      ) : (
        conversations.map((c) => (
          <Link key={c.id} href={`/chat/${c.id}`}>
            <Card className="hover:bg-muted/50 transition-colors">
              <CardHeader>
                <CardTitle className="text-base">
                  {c.title ?? "Untitled"}
                </CardTitle>
                <CardDescription>
                  {c.model ?? "unknown model"} · {c.message_count} messages ·{" "}
                  {new Date(c.updated_at).toLocaleString()}
                </CardDescription>
              </CardHeader>
            </Card>
          </Link>
        ))
      )}
    </div>
  );
}
