"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, Portfolio, PortfolioRow, clearTokens, getPortfolio } from "@/lib/api";
import { useT } from "@/lib/locale";

function buildGroups(rows: PortfolioRow[]): { group: string; rows: PortfolioRow[] }[] {
  const order: string[] = [];
  const by: Record<string, PortfolioRow[]> = {};
  for (const r of rows) {
    const g = r.group_name?.trim() || "—";
    if (!(g in by)) {
      by[g] = [];
      order.push(g);
    }
    by[g].push(r);
  }
  return order.map((g) => ({ group: g, rows: by[g] }));
}

const HEALTH_STYLES: Record<string, string> = {
  ON_TRACK: "bg-emerald-100 text-emerald-700",
  AT_RISK: "bg-amber-100 text-amber-700",
  OFF_TRACK: "bg-red-100 text-red-700",
};

export default function DashboardPage() {
  const router = useRouter();
  const t = useT();
  const [pf, setPf] = useState<Portfolio | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setPf(await getPortfolio());
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
      <main className="mx-auto max-w-5xl p-8">
        <header>
          <h1 className="text-2xl font-semibold">{t("dash.title")}</h1>
          <p className="text-sm text-muted">{t("dash.subtitle")}</p>
        </header>

        {!pf ? (
          <p className="mt-8 text-sm text-muted">{t("common.loading")}</p>
        ) : (
          <>
            <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Kpi label={t("dash.kpi.activeProjects")} value={pf.totals.active_projects} />
              <Kpi
                label={t("dash.kpi.blockers")}
                value={pf.totals.blockers}
                tone={pf.totals.blockers ? "red" : undefined}
              />
              <Kpi
                label={t("dash.kpi.overdue")}
                value={pf.totals.overdue}
                tone={pf.totals.overdue ? "amber" : undefined}
              />
              <Kpi
                label={t("dash.kpi.waitingReview")}
                value={pf.totals.waiting_my_review}
                tone={pf.totals.waiting_my_review ? "violet" : undefined}
              />
            </div>

            <section className="mt-8 overflow-hidden rounded-xl border border-slate-200 bg-white">
              <div className="border-b border-slate-100 px-5 py-3">
                <h2 className="text-sm font-semibold">{t("dash.health.title")}</h2>
              </div>
              {pf.rows.length === 0 ? (
                <p className="px-5 py-8 text-center text-sm text-muted">{t("dash.empty")}</p>
              ) : (
                <table className="w-full text-sm tabular-nums">
                  <thead className="text-left text-xs uppercase tracking-wide text-muted">
                    <tr>
                      <th className="px-5 py-2 font-medium">{t("table.project")}</th>
                      <th className="px-2 py-2 font-medium">{t("table.health")}</th>
                      <th className="px-2 py-2 font-medium">{t("table.sprint")}</th>
                      <th className="px-2 py-2 text-right font-medium">{t("table.open")}</th>
                      <th className="px-2 py-2 text-right font-medium">{t("table.overdue")}</th>
                      <th className="px-2 py-2 text-right font-medium">{t("table.blocked")}</th>
                      <th className="px-5 py-2 text-right font-medium">{t("table.review")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {buildGroups(pf.rows).flatMap(({ group, rows }) => [
                      <tr key={`grp-${group}`} className="bg-slate-50">
                        <td
                          colSpan={7}
                          className="px-5 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted"
                        >
                          {group}
                        </td>
                      </tr>,
                      ...rows.map((r) => {
                      const pct = r.sprint_total
                        ? Math.round((r.sprint_done / r.sprint_total) * 100)
                        : 0;
                      return (
                        <tr
                          key={r.project_id}
                          onClick={() => router.push(`/projects/${r.project_id}`)}
                          className="cursor-pointer border-t border-slate-100 hover:bg-slate-50"
                        >
                          <td className="px-5 py-2.5">
                            <span className="mr-2 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-muted">
                              {r.code}
                            </span>
                            {r.name}
                          </td>
                          <td className="px-2 py-2.5">
                            <span
                              className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                                HEALTH_STYLES[r.health] ?? "bg-slate-100"
                              }`}
                            >
                              {t(`health.${r.health}`)}
                            </span>
                          </td>
                          <td className="px-2 py-2.5">
                            {r.sprint_name ? (
                              <div className="flex items-center gap-2">
                                <div className="h-1.5 w-14 overflow-hidden rounded-full bg-indigo-100">
                                  <div
                                    className="h-full bg-indigo-500"
                                    style={{ width: `${pct}%` }}
                                  />
                                </div>
                                <span className="text-xs text-muted">{r.sprint_name}</span>
                              </div>
                            ) : (
                              <span className="text-xs text-slate-300">—</span>
                            )}
                          </td>
                          <td className="px-2 py-2.5 text-right">{r.open}</td>
                          <td className="px-2 py-2.5 text-right text-amber-700">
                            {r.overdue || ""}
                          </td>
                          <td className="px-2 py-2.5 text-right text-red-600">
                            {r.blocked || ""}
                          </td>
                          <td className="px-5 py-2.5 text-right font-medium text-violet-700">
                            {r.review || ""}
                          </td>
                        </tr>
                      );
                      }),
                    ])}
                  </tbody>
                </table>
              )}
            </section>
          </>
        )}
      </main>
    </>
  );
}

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "red" | "amber" | "violet";
}) {
  const color =
    tone === "red"
      ? "text-red-600"
      : tone === "amber"
      ? "text-amber-700"
      : tone === "violet"
      ? "text-violet-700"
      : "text-ink";
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className={`mt-2 text-3xl font-bold tabular-nums ${color}`}>{value}</div>
    </div>
  );
}
