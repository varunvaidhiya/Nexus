import { apiFetch } from "@/lib/api";

export type TaskStatus = "todo" | "doing" | "blocked" | "done";

export interface Task {
  id: string;
  title: string;
  detail: string | null;
  status: TaskStatus;
  priority: number;
  due_at: string | null;
  why_it_matters: string | null;
  source_conversation_id: string | null;
  goal_ids: string[];
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface TodayItem {
  task: Task;
  score: number;
  reasons: string[];
}

export interface Goal {
  id: string;
  title: string;
  horizon: "day" | "week" | "month" | "quarter";
  status: "active" | "paused" | "achieved" | "dropped";
  target_at: string | null;
  created_at: string;
  task_count: number;
  done_count: number;
  progress: number;
}

export interface Suggestion {
  id: string;
  kind: string;
  conversation_id: string;
  conversation_title: string | null;
  reason: string;
  created_at: string;
}

export interface Review {
  id: string;
  period_start: string;
  period_end: string;
  content: string;
  created_at: string;
}

export const getToday = () => apiFetch<TodayItem[]>("/today");
export const getTasks = () => apiFetch<Task[]>("/tasks");
export const getGoals = () => apiFetch<Goal[]>("/goals");
export const getSuggestions = () => apiFetch<Suggestion[]>("/suggestions");
export const getReviews = () => apiFetch<Review[]>("/reviews?limit=1");

export const createTask = (title: string) =>
  apiFetch<Task>("/tasks", { method: "POST", body: JSON.stringify({ title }) });

export const patchTask = (
  id: string,
  patch: Partial<Pick<Task, "status" | "priority">>,
) =>
  apiFetch<Task>(`/tasks/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const createGoal = (title: string, horizon: Goal["horizon"]) =>
  apiFetch<Goal>("/goals", {
    method: "POST",
    body: JSON.stringify({ title, horizon }),
  });

export const linkTask = (goalId: string, taskId: string) =>
  apiFetch<void>(`/goals/${goalId}/tasks`, {
    method: "POST",
    body: JSON.stringify({ task_id: taskId }),
  });

export const dismissSuggestion = (id: string) =>
  apiFetch<void>(`/suggestions/${id}/dismiss`, { method: "POST" });
