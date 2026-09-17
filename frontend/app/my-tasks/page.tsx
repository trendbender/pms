"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, TaskCard, clearTokens, getMyTasks } from "@/lib/api";
import { useT } from "@/lib/locale";
import { BUCKET_ORDER, PRIORITY_STYLES, bucketByDue } from "@/lib/buckets";

const DOT: Record<string, string> = {
  BACKLOG: "#94a3b8",
  READY: "#0ea5e9",
  IN_PROGRESS: "#6366f1",
  BLOCKED: "#ef4444",
  REVIEW: "#a855f7",
  CHANGES_REQUIRED: "#f97316",
  DONE: "#22c55e",
};

export default function MyTasksPage() {
  const router = useRouter();
  const t = useT();
  const [tasks, setTasks] = useState<TaskCard[] | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setTasks(await getMyTasks());
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          clearTokens();
          router.replace("/login");
        }
      }
    })();
  }, [router]);

  const groups = tasks ? bucketByDue(tasks) : null;

  return (
    <>
      <main className="mx-auto max-w-3xl p-8">
        <header>
          <h1 className="text-2xl font-semibold">{t("myTasks.title")}</h1>
          <p className="text-sm text-muted">{t("myTasks.subtitle")}</p>
        </header>

        {!tasks ? (
          <p className="mt-8 text-sm text-muted">{t("common.loading")}</p>
        ) : tasks.length === 0 ? (
          <p className="mt-8 rounded-xl border border-dashed border-slate-200 p-8 text-center text-sm text-muted">
            {t("myTasks.empty")}
          </p>
        ) : (
          <div className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white">
            {BUCKET_ORDER.map((key) => {
              const rows = groups![key];
              if (rows.length === 0) return null;
              return (
                <div key={key}>
                  <div
                    className={`flex items-center gap-2 px-4 py-2 text-xs font-semibold ${
                      key === "overdue" ? "bg-red-50 text-red-700" : "text-muted"
                    }`}
                  >
                    {t(`group.${key}`)}
                    <span className="rounded-full bg-white/70 px-1.5 tabular-nums">
                      {rows.length}
                    </span>
                  </div>
                  {rows.map((task) => (
                    <div
                      key={task.id}
                      onClick={() => router.push(`/tasks/${task.id}`)}
                      className="flex cursor-pointer items-center gap-3 border-t border-slate-100 px-4 py-2.5 hover:bg-slate-50"
                    >
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                          PRIORITY_STYLES[task.priority] ?? "bg-slate-100"
                        }`}
                      >
                        {task.priority}
                      </span>
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ background: DOT[task.status_category ?? ""] ?? "#cbd5e1" }}
                      />
                      <span className="font-mono text-xs text-muted">{task.key}</span>
                      <span className="truncate text-sm">{task.title}</span>
                      {task.is_blocked && (
                        <span className="ml-auto shrink-0 rounded-full bg-red-50 px-2 text-xs text-red-600">
                          ⛔
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        )}
      </main>
    </>
  );
}
