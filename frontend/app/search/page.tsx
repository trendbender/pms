"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, TaskCard, clearTokens, searchTasks } from "@/lib/api";
import { useT } from "@/lib/locale";
import { PRIORITY_STYLES } from "@/lib/buckets";

function SearchInner() {
  const router = useRouter();
  const t = useT();
  const params = useSearchParams();
  const q = params.get("q") ?? "";
  const [results, setResults] = useState<TaskCard[] | null>(null);

  useEffect(() => {
    if (!q.trim()) {
      setResults(null);
      return;
    }
    setResults(null);
    searchTasks(q)
      .then(setResults)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearTokens();
          router.replace("/login");
        }
      });
  }, [q, router]);

  return (
    <main className="mx-auto max-w-3xl p-8">
      <h1 className="text-2xl font-semibold">{t("search.title")}</h1>
      {q && <p className="mt-1 text-sm text-muted">“{q}”</p>}

      {!q.trim() ? (
        <p className="mt-8 text-sm text-muted">{t("search.hint")}</p>
      ) : !results ? (
        <p className="mt-8 text-sm text-muted">{t("common.loading")}</p>
      ) : results.length === 0 ? (
        <p className="mt-8 rounded-xl border border-dashed border-slate-200 p-8 text-center text-sm text-muted">
          {t("search.empty")}
        </p>
      ) : (
        <div className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white">
          {results.map((task) => (
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
            </div>
          ))}
        </div>
      )}
    </main>
  );
}

export default function SearchPage() {
  return (
    <>
      <Suspense fallback={null}>
        <SearchInner />
      </Suspense>
    </>
  );
}
