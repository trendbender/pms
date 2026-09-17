import { TaskCard } from "@/lib/api";

export const PRIORITY_STYLES: Record<string, string> = {
  CRITICAL: "bg-red-100 text-red-700",
  HIGH: "bg-orange-100 text-orange-700",
  MEDIUM: "bg-slate-100 text-slate-600",
  LOW: "bg-slate-100 text-slate-500",
  NONE: "bg-slate-100 text-slate-400",
};

export type BucketKey = "overdue" | "today" | "thisWeek" | "later" | "noDate";

export const BUCKET_ORDER: BucketKey[] = [
  "overdue",
  "today",
  "thisWeek",
  "later",
  "noDate",
];

function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

/** Group tasks into due-date buckets relative to now (spec §31). */
export function bucketByDue(tasks: TaskCard[]): Record<BucketKey, TaskCard[]> {
  const out: Record<BucketKey, TaskCard[]> = {
    overdue: [],
    today: [],
    thisWeek: [],
    later: [],
    noDate: [],
  };
  const today = startOfDay(new Date());
  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  const weekEnd = new Date(today);
  weekEnd.setDate(today.getDate() + 7);

  for (const task of tasks) {
    if (!task.due_at) {
      out.noDate.push(task);
      continue;
    }
    const due = new Date(task.due_at);
    if (due < today) out.overdue.push(task);
    else if (due < tomorrow) out.today.push(task);
    else if (due < weekEnd) out.thisWeek.push(task);
    else out.later.push(task);
  }
  return out;
}
