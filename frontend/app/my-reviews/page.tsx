"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, TaskCard, clearTokens, getMyReviews } from "@/lib/api";
import { useT } from "@/lib/locale";
import { PRIORITY_STYLES } from "@/lib/buckets";

export default function MyReviewsPage() {
  const router = useRouter();
  const t = useT();
  const [tasks, setTasks] = useState<TaskCard[] | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setTasks(await getMyReviews());
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          clearTokens();
          router.replace("/login");
        }
      }
    })();
  }, [router]);

  return (
    <>
      <main className="mx-auto max-w-3xl p-8">
        <header>
          <h1 className="text-2xl font-semibold">{t("myReviews.title")}</h1>
          <p className="text-sm text-muted">{t("myReviews.subtitle")}</p>
        </header>

        {!tasks ? (
          <p className="mt-8 text-sm text-muted">{t("common.loading")}</p>
        ) : tasks.length === 0 ? (
          <p className="mt-8 rounded-xl border border-dashed border-slate-200 p-8 text-center text-sm text-muted">
            {t("myReviews.empty")}
          </p>
        ) : (
          <div className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white">
            {tasks.map((task) => (
              <div
                key={task.id}
                onClick={() => router.push(`/tasks/${task.id}`)}
                className="flex cursor-pointer items-center gap-3 border-t border-slate-100 px-4 py-3 first:border-t-0 hover:bg-slate-50"
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
                <span className="ml-auto shrink-0 rounded-full bg-violet-50 px-2 py-0.5 text-xs text-violet-700">
                  {task.status_name}
                </span>
              </div>
            ))}
          </div>
        )}
      </main>
    </>
  );
}
