"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Decision, DecisionFilter, decisionHref } from "@/lib/api";
import { useT } from "@/lib/locale";

export const DECISION_STATUS_STYLES: Record<string, string> = {
  accepted: "bg-emerald-50 text-emerald-700",
  open: "bg-amber-50 text-amber-700",
  superseded: "bg-slate-100 text-slate-500",
  rejected: "bg-slate-100 text-slate-500",
};

export function DecisionStatus({ status }: { status: string }) {
  const t = useT();
  return (
    <span
      className={`whitespace-nowrap rounded px-1.5 py-0.5 text-xs ${
        DECISION_STATUS_STYLES[status] ?? "bg-slate-100 text-slate-600"
      }`}
    >
      {t(`decisions.status.${status}`)}
    </span>
  );
}

// Список решений с поиском и фильтрами (вкладка проекта и кросс-проектный реестр).
// Фильтры уходят на бэкенд, открытые вопросы показываются отдельным блоком сверху.
export default function DecisionList({
  load,
}: {
  load: (f: DecisionFilter) => Promise<Decision[]>;
}) {
  const t = useT();
  const [rows, setRows] = useState<Decision[] | null>(null);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("accepted");
  const [area, setArea] = useState("");
  const [areas, setAreas] = useState<[string, string][]>([]);
  const [open, setOpen] = useState<Decision[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Открытые вопросы и список областей грузим один раз, без фильтров.
  useEffect(() => {
    load({})
      .then((all) => {
        setOpen(all.filter((d) => d.status === "open"));
        const m = new Map<string, string>();
        all.forEach((d) => d.area && m.set(d.area, d.area_title || d.area));
        setAreas([...m.entries()].sort((a, b) => a[1].localeCompare(b[1])));
      })
      .catch(() => setError(t("decisions.loadFailed")));
  }, [load, t]);

  useEffect(() => {
    const h = setTimeout(() => {
      load({ q: q.trim() || undefined, status: status || undefined, area: area || undefined })
        .then(setRows)
        .catch(() => setError(t("decisions.loadFailed")));
    }, 250);
    return () => clearTimeout(h);
  }, [load, q, status, area, t]);

  const shown = useMemo(() => rows ?? [], [rows]);

  return (
    <div className="mt-5">
      {error && <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {open.length > 0 && (
        <section className="mb-6 rounded-lg border border-amber-200 bg-amber-50/40 p-4">
          <h2 className="text-sm font-semibold">
            {t("decisions.openQuestions")} <span className="text-muted">{open.length}</span>
          </h2>
          <ul className="mt-2 flex flex-col gap-1.5 text-sm">
            {open.map((d) => (
              <li key={d.id} className="flex gap-2">
                <Link href={decisionHref(d.full_ref)} className="shrink-0 font-mono text-indigo-600 hover:underline">
                  {d.ref}
                </Link>
                <Link href={decisionHref(d.full_ref)} className="line-clamp-2 hover:underline">
                  {d.question}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="flex flex-wrap gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("decisions.search")}
          className="min-w-[16rem] flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-lg border border-slate-300 px-2 py-2 text-sm"
        >
          <option value="">{t("decisions.allStatuses")}</option>
          {["accepted", "open", "superseded", "rejected"].map((s) => (
            <option key={s} value={s}>
              {t(`decisions.status.${s}`)}
            </option>
          ))}
        </select>
        <select
          value={area}
          onChange={(e) => setArea(e.target.value)}
          className="rounded-lg border border-slate-300 px-2 py-2 text-sm"
        >
          <option value="">{t("decisions.allAreas")}</option>
          {areas.map(([key, title]) => (
            <option key={key} value={key}>
              {title}
            </option>
          ))}
        </select>
      </div>

      {rows === null ? (
        <p className="mt-4 text-sm text-muted">{t("common.loading")}</p>
      ) : shown.length === 0 ? (
        <p className="mt-4 text-sm text-muted">{t("decisions.empty")}</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-muted">
                <th className="py-2 pr-3 font-medium">№</th>
                <th className="py-2 pr-3 font-medium">{t("decisions.question")}</th>
                <th className="py-2 pr-3 font-medium">{t("decisions.decision")}</th>
                <th className="py-2 pr-3 font-medium">{t("decisions.date")}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((d) => (
                <tr key={d.id} className="border-b border-slate-100 align-top">
                  <td className="whitespace-nowrap py-2 pr-3">
                    <Link href={decisionHref(d.full_ref)} className="font-mono text-indigo-600 hover:underline">
                      {d.ref}
                    </Link>
                    {d.status !== "accepted" && (
                      <div className="mt-1">
                        <DecisionStatus status={d.status} />
                      </div>
                    )}
                  </td>
                  <td className="py-2 pr-3">
                    <Link href={decisionHref(d.full_ref)} className="hover:underline">
                      {d.question}
                    </Link>
                    {d.area_title && <div className="mt-0.5 text-xs text-muted">{d.area_title}</div>}
                  </td>
                  <td className="max-w-xl py-2 pr-3 text-slate-700">
                    <span className="line-clamp-3">{d.decision ?? "—"}</span>
                  </td>
                  <td className="whitespace-nowrap py-2 pr-3 text-xs text-muted">
                    {d.decided_on ?? ""}
                    {d.decided_by && <div>{d.decided_by}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
