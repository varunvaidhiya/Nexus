"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createGoal, type Goal } from "@/lib/assistant";

export function GoalsPanel({
  goals,
  onChanged,
}: {
  goals: Goal[];
  onChanged: () => Promise<void>;
}) {
  const [title, setTitle] = useState("");
  const [horizon, setHorizon] = useState<Goal["horizon"]>("month");
  const [busy, setBusy] = useState(false);

  async function add(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    try {
      await createGoal(title.trim(), horizon);
      setTitle("");
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="flex flex-col gap-4" data-testid="goals-panel">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium">Goals</h2>
        <form onSubmit={add} className="flex items-center gap-2">
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="New goal…"
            className="w-56"
            data-testid="new-goal-title"
          />
          <select
            className="h-9 rounded-md border bg-transparent px-2 text-sm"
            value={horizon}
            onChange={(e) => setHorizon(e.target.value as Goal["horizon"])}
          >
            <option value="day">day</option>
            <option value="week">week</option>
            <option value="month">month</option>
            <option value="quarter">quarter</option>
          </select>
          <Button
            type="submit"
            size="sm"
            disabled={busy}
            data-testid="new-goal-submit"
          >
            Add
          </Button>
        </form>
      </div>
      {goals.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          No goals yet — add one and link tasks to it from the board.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {goals.map((goal) => (
            <div
              key={goal.id}
              className="flex flex-col gap-1"
              data-testid="goal-row"
            >
              <div className="flex items-center justify-between text-sm">
                <span className={goal.status !== "active" ? "opacity-60" : ""}>
                  {goal.title}
                  <span className="text-muted-foreground ml-2 text-xs">
                    {goal.horizon}
                    {goal.status !== "active" ? ` · ${goal.status}` : ""}
                  </span>
                </span>
                <span className="text-muted-foreground text-xs">
                  {goal.done_count}/{goal.task_count} tasks
                </span>
              </div>
              <div className="bg-muted h-2 overflow-hidden rounded-full">
                <div
                  className="bg-primary h-full rounded-full transition-all"
                  style={{ width: `${Math.round(goal.progress * 100)}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
