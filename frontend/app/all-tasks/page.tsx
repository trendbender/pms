"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, PagedTasks, clearTokens, getAllTasks } from "@/lib/api";
import { useT } from "@/lib/locale";
import { PRIORITY_STYLES } from "@/lib/buckets";

const PAGE = 25;
const PRIORITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"];

export default function AllTasksPage() {
  const router = useRouter();
  const t = useT();
  const [data, setData] = useState<PagedTasks | null>(null);
  const [priority, setPriority] = useState("");
  const [offset, setOffset] = useState(0);

  const load = useCallback(async () => {
    try {
      setData(await getAllTasks({ priority: priority || undefined, limit: PAGE, offset }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearTokens();
        router.replace("/login");
      }
    }
  }, [priority, offset, router]);

  useEffect(() => {
    load();
  }, [load]);

  const total = data?.total ?? 0;

  return (
    <>
      <main className="mx-auto max-w-4xl p-8">
        <header className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">{t("allTasks.title")}</h1>
          <select
            value={priority}
            onChange={(e) => {
              setPriority(e.target.value);
              setOffset(0);
            }}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
          >
            <option value="">{t("allTasks.priorityAll")}</option>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </header>

        <p className="mt-2 text-sm text-muted">{t("allTasks.count", { total })}</p>

        <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-white">
          {!data ? (
            <p className="px-4 py-8 text-center text-sm text-muted">{t("common.loading")}</p>
          ) : data.items.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-muted">{t("allTasks.empty")}</p>
          ) : (
            data.items.map((task) => (
              <div
                key={task.id}
                onClick={() => router.push(`/tasks/${task.id}`)}
                className="flex cursor-pointer items-center gap-3 border-t border-slate-100 px-4 py-2.5 first:border-t-0 hover:bg-slate-50"
              >
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                    PRIORITY_STYLES[task.priority] ?? "bg-slate-100"
                  }`}
                >
                  {task.priority}
                </span>
                <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-muted">
                  {task.project_code}
                </span>
                <span className="font-mono text-xs text-muted">{task.key}</span>
                <span className="truncate text-sm">{task.title}</span>
                <span className="ml-auto shrink-0 text-xs text-muted">{task.status_name}</span>
              </div>
            ))
          )}
        </div>

        <div className="mt-4 flex items-center justify-between">
          <button
            onClick={() => setOffset(Math.max(0, offset - PAGE))}
            disabled={offset === 0}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-40"
          >
            {t("allTasks.prev")}
          </button>
          <button
            onClick={() => setOffset(offset + PAGE)}
            disabled={offset + PAGE >= total}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-40"
          >
            {t("allTasks.next")}
          </button>
        </div>
      </main>
    </>
  );
}
