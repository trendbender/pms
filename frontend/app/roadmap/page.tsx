"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ApiError, Roadmap, clearTokens, listPortfolioRoadmaps } from "@/lib/api";
import { useT } from "@/lib/locale";

const STATUS_STYLES: Record<string, string> = {
  DRAFT: "bg-slate-100 text-slate-600",
  AGREED: "bg-sky-100 text-sky-700",
  ACTIVE: "bg-indigo-100 text-indigo-700",
  COMPLETED: "bg-emerald-100 text-emerald-700",
  CANCELLED: "bg-slate-100 text-slate-400",
};

function day(value: string | null) {
  if (!value) return "—";
  const [y, m, d] = value.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

/** Доля пути периода, которая уже прошла: по ней видно, отстаёт ли роадмап. */
function elapsed(r: Roadmap): number | null {
  if (!r.period_end) return null;
  const start = Date.parse(r.period_start);
  const end = Date.parse(r.period_end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
  return Math.min(1, Math.max(0, (Date.now() - start) / (end - start)));
}

export default function PortfolioRoadmapPage() {
  const router = useRouter();
  const t = useT();
  const [rows, setRows] = useState<Roadmap[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listPortfolioRoadmaps()
      .then(setRows)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearTokens();
          router.replace("/login");
        } else {
          setError(err instanceof ApiError ? err.message : t("roadmap.loadFailed"));
        }
      });
  }, [router, t]);

  return (
    <main className="mx-auto max-w-6xl p-8">
      <h1 className="text-2xl font-semibold">{t("roadmap.portfolioTitle")}</h1>
      <p className="mt-1 text-sm text-muted">{t("roadmap.portfolioHint")}</p>

      {error && (
        <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}

      {rows.length === 0 && !error && (
        <p className="mt-6 text-sm text-muted">{t("roadmap.portfolioEmpty")}</p>
      )}

      <div className="mt-5 space-y-3">
        {rows.map((r) => {
          const share = r.task_count > 0 ? r.done_count / r.task_count : 0;
          const pace = elapsed(r);
          const behind = pace !== null && pace - share > 0.2;
          return (
            <Link
              key={r.id}
              href={`/projects/${(r.project_code ?? r.project_id).toLowerCase()}/roadmap`}
              className="block rounded-xl border border-slate-200 bg-white p-4 hover:border-slate-300"
            >
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="font-mono text-xs text-muted">{r.project_code}</span>
                <span className="font-medium">{r.project_name}</span>
                <span className="text-sm text-muted">· {r.title}</span>
                <span
                  className={
                    "ml-auto rounded-full px-2 py-0.5 text-xs " +
                    (STATUS_STYLES[r.status] ?? STATUS_STYLES.DRAFT)
                  }
                >
                  {t(`roadmap.status.${r.status}`)}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted">
                <span>
                  {day(r.period_start)}
                  {r.period_end ? ` — ${day(r.period_end)}` : ""}
                </span>
                <span>
                  {t("roadmap.items")}: {r.done_count}/{r.task_count}
                </span>
                {r.metric_count > 0 && (
                  <span>
                    {t("roadmap.metricsReached")}: {r.metric_reached_count}/{r.metric_count}
                  </span>
                )}
                {r.blocked_count > 0 && (
                  <span className="text-red-700">
                    {t("roadmap.blocked")}: {r.blocked_count}
                  </span>
                )}
                {r.overdue_count > 0 && (
                  <span className="text-amber-700">
                    {t("roadmap.overdue")}: {r.overdue_count}
                  </span>
                )}
                {behind && <span className="text-amber-700">{t("roadmap.behind")}</span>}
              </div>
              <div className="relative mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                <div
                  className={"h-full " + (behind ? "bg-amber-500" : "bg-indigo-500")}
                  style={{ width: `${Math.round(share * 100)}%` }}
                />
                {pace !== null && (
                  // отметка «где мы по календарю» — без неё процент готовности ни о чём
                  <span
                    className="absolute top-0 h-full w-px bg-slate-400"
                    style={{ left: `${Math.round(pace * 100)}%` }}
                    title={t("roadmap.today")}
                  />
                )}
              </div>
            </Link>
          );
        })}
      </div>
    </main>
  );
}
