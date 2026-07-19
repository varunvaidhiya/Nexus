"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  createTask,
  linkTask,
  patchTask,
  type Goal,
  type Task,
  type TaskStatus,
} from "@/lib/assistant";

const COLUMNS: { status: TaskStatus; label: string }[] = [
  { status: "todo", label: "To do" },
  { status: "doing", label: "Doing" },
  { status: "blocked", label: "Blocked" },
  { status: "done", label: "Done" },
];

export function TaskBoard({
  tasks,
  goals,
  onChanged,
}: {
  tasks: Task[];
  goals: Goal[];
  onChanged: () => Promise<void>;
}) {
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);

  async function add(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    try {
      await createTask(title.trim());
      setTitle("");
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="flex flex-col gap-4" data-testid="task-board">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium">Task board</h2>
        <form onSubmit={add} className="flex items-center gap-2">
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Add a task…"
            className="w-64"
            data-testid="new-task-title"
          />
          <Button
            type="submit"
            size="sm"
            disabled={busy}
            data-testid="new-task-submit"
          >
            Add
          </Button>
        </form>
      </div>
      <div className="grid gap-4 md:grid-cols-4">
        {COLUMNS.map((column) => (
          <div key={column.status} className="flex flex-col gap-2">
            <h3 className="text-muted-foreground text-sm font-medium">
              {column.label} (
              {tasks.filter((t) => t.status === column.status).length})
            </h3>
            {tasks
              .filter((t) => t.status === column.status)
              .map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  goals={goals}
                  onChanged={onChanged}
                />
              ))}
          </div>
        ))}
      </div>
    </section>
  );
}

function TaskCard({
  task,
  goals,
  onChanged,
}: {
  task: Task;
  goals: Goal[];
  onChanged: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const unlinkedGoals = goals.filter(
    (goal) => goal.status === "active" && !task.goal_ids.includes(goal.id),
  );

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  const moves: TaskStatus[] = (
    {
      todo: ["doing"],
      doing: ["done", "blocked"],
      blocked: ["doing"],
      done: ["todo"],
    } as Record<TaskStatus, TaskStatus[]>
  )[task.status];

  return (
    <div
      className="bg-card flex flex-col gap-2 rounded-lg border p-3 text-sm"
      data-testid="board-task"
    >
      <span className={task.status === "done" ? "line-through opacity-60" : ""}>
        {task.title}
      </span>
      {task.why_it_matters && (
        <span className="text-muted-foreground text-xs">
          {task.why_it_matters}
        </span>
      )}
      <div className="flex flex-wrap items-center gap-1">
        {moves.map((next) => (
          <Button
            key={next}
            variant="outline"
            size="sm"
            className="h-6 px-2 text-xs"
            disabled={busy}
            onClick={() => run(() => patchTask(task.id, { status: next }))}
          >
            → {next}
          </Button>
        ))}
        {unlinkedGoals.length > 0 && task.status !== "done" && (
          <select
            className="text-muted-foreground h-6 rounded border bg-transparent text-xs"
            value=""
            disabled={busy}
            onChange={(e) => {
              if (e.target.value) {
                void run(() => linkTask(e.target.value, task.id));
              }
            }}
          >
            <option value="">+ goal</option>
            {unlinkedGoals.map((goal) => (
              <option key={goal.id} value={goal.id}>
                {goal.title}
              </option>
            ))}
          </select>
        )}
        {task.status !== "done" && (
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xs"
            render={<Link href={`/handoff?task=${task.id}`} />}
            data-testid="handoff-link"
          >
            Hand off
          </Button>
        )}
      </div>
    </div>
  );
}
