"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { GoalsPanel } from "@/components/goals-panel";
import { TaskBoard } from "@/components/task-board";
import { Button } from "@/components/ui/button";
import { ApiError, getToken } from "@/lib/api";
import {
  dismissSuggestion,
  getGoals,
  getReviews,
  getSuggestions,
  getTasks,
  getToday,
  patchTask,
  type Goal,
  type Review,
  type Suggestion,
  type Task,
  type TodayItem,
} from "@/lib/assistant";

export default function TodayPage() {
  const router = useRouter();
  const [today, setToday] = useState<TodayItem[] | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [review, setReview] = useState<Review | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [todayItems, allTasks, allGoals, openSuggestions, reviews] =
        await Promise.all([
          getToday(),
          getTasks(),
          getGoals(),
          getSuggestions(),
          getReviews(),
        ]);
      setToday(todayItems);
      setTasks(allTasks);
      setGoals(allGoals);
      setSuggestions(openSuggestions);
      setReview(reviews[0] ?? null);
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
    const load = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(load);
  }, [refresh, router]);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-10 px-6 py-16">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Today</h1>
          <p className="text-muted-foreground text-sm">
            What deserves your attention, and why.
          </p>
        </div>
        <nav className="flex gap-2">
          <Button variant="ghost" render={<Link href="/chat" />}>
            Chat
          </Button>
          <Button variant="ghost" render={<Link href="/search" />}>
            Search
          </Button>
          <Button variant="ghost" render={<Link href="/settings" />}>
            Settings
          </Button>
        </nav>
      </header>

      {error && <p className="text-destructive text-sm">{error}</p>}

      <section className="flex flex-col gap-3" data-testid="today-list">
        {today === null ? (
          <p className="text-muted-foreground text-sm">Loading…</p>
        ) : today.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            Nothing on deck — add tasks below, or let extraction fill this in as
            you work.
          </p>
        ) : (
          today.map((item, index) => (
            <div
              key={item.task.id}
              className="bg-card flex items-start gap-4 rounded-lg border p-4"
              data-testid="today-item"
            >
              <span className="text-muted-foreground w-6 text-right font-mono text-lg">
                {index + 1}
              </span>
              <div className="flex flex-1 flex-col gap-1">
                <span className="font-medium">{item.task.title}</span>
                {item.reasons.length > 0 && (
                  <ul className="text-muted-foreground text-sm">
                    {item.reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                )}
              </div>
              {item.task.status === "todo" ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={async () => {
                    await patchTask(item.task.id, { status: "doing" });
                    await refresh();
                  }}
                >
                  Start
                </Button>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={async () => {
                    await patchTask(item.task.id, { status: "done" });
                    await refresh();
                  }}
                >
                  Done
                </Button>
              )}
            </div>
          ))
        )}
      </section>

      {suggestions.length > 0 && (
        <section className="flex flex-col gap-3" data-testid="loose-ends">
          <h2 className="text-lg font-medium">Loose ends</h2>
          {suggestions.map((suggestion) => (
            <div
              key={suggestion.id}
              className="flex items-start justify-between gap-4 rounded-lg border border-dashed p-4"
              data-testid="loose-end"
            >
              <div className="flex flex-col gap-1 text-sm">
                {suggestion.conversation_title && (
                  <span className="font-medium">
                    {suggestion.conversation_title}
                  </span>
                )}
                <span className="text-muted-foreground">
                  {suggestion.reason}
                </span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                data-testid="dismiss-suggestion"
                onClick={async () => {
                  await dismissSuggestion(suggestion.id);
                  await refresh();
                }}
              >
                Dismiss
              </Button>
            </div>
          ))}
        </section>
      )}

      <TaskBoard tasks={tasks} goals={goals} onChanged={refresh} />

      <GoalsPanel goals={goals} onChanged={refresh} />

      {review && (
        <section className="flex flex-col gap-2" data-testid="weekly-review">
          <h2 className="text-lg font-medium">
            Weekly review · {review.period_start} → {review.period_end}
          </h2>
          <div className="bg-card rounded-lg border p-4 text-sm whitespace-pre-wrap">
            {review.content}
          </div>
        </section>
      )}
    </div>
  );
}
