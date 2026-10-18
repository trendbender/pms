"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  Lead,
  LeadBoardColumn,
  LeadStage,
  LeadStats,
  Project,
  changeLeadStage,
  clearTokens,
  createLead,
  getLeadBoard,
  getLeadStats,
  getProjectByRef,
  leadHref,
  listLeads,
} from "@/lib/api";
import { useT } from "@/lib/locale";
import ProjectTabs from "@/components/ProjectTabs";
import { CATEGORY_STYLES, money, shortDate } from "@/lib/leadFormat";

export default function ProjectLeadsPage() {
  const router = useRouter();
  const t = useT();
  const { id: ref } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [columns, setColumns] = useState<LeadBoardColumn[]>([]);
  const [rows, setRows] = useState<Lead[]>([]);
  const [stats, setStats] = useState<LeadStats | null>(null);
  const [view, setView] = useState<"board" | "table">("board");
  const [title, setTitle] = useState("");
  const [q, setQ] = useState("");
  const [stageFilter, setStageFilter] = useState("");
  const [dragId, setDragId] = useState<string | null>(null);
  const [overCol, setOverCol] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const p = await getProjectByRef(ref);
      setProject(p);
      if (!p.leads_enabled) return;
      const [board, st] = await Promise.all([getLeadBoard(p.id), getLeadStats(p.id)]);
      setColumns(board.columns);
      setStats(st);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearTokens();
        router.replace("/login");
      } else {
        setError(err instanceof ApiError ? err.message : t("leads.loadFailed"));
      }
    }
  }, [ref, router, t]);

  const refreshTable = useCallback(async () => {
    if (!project?.leads_enabled) return;
    try {
      setRows(await listLeads(project.id, { q: q.trim(), stage_id: stageFilter }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("leads.loadFailed"));
    }
  }, [project, q, stageFilter, t]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (view === "table") refreshTable();
  }, [view, refreshTable]);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !project) return;
    setBusy(true);
    setError(null);
    try {
      await createLead(project.id, { title: title.trim() });
      setTitle("");
      await refresh();
      if (view === "table") await refreshTable();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("leads.createFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function moveTo(stage: LeadStage) {
    const leadId = dragId;
    setDragId(null);
    setOverCol(null);
    if (!leadId) return;
    const lead = columns.flatMap((c) => c.leads).find((l) => l.id === leadId);
    if (!lead || lead.stage_id === stage.id) return;
    let reason: string | undefined;
    if (stage.category === "LOST") {
      reason = window.prompt(t("leads.lostReasonPrompt"))?.trim();
      if (!reason) return;
    }
    try {
      await changeLeadStage(leadId, stage.id, reason);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("leads.moveFailed"));
    }
  }

  const stages = columns.map((c) => c.stage);

  return (
    <main className="mx-auto max-w-7xl p-8">
      <header>
        <Link href="/projects" className="text-sm text-muted hover:underline">
          {t("board.back")}
        </Link>
        <h1 className="mt-1 text-2xl font-semibold">
          {project && <span className="font-mono text-base text-muted">{project.code} </span>}
          {project?.name ?? t("leads.tab")}
        </h1>
        <ProjectTabs project={project} active="leads" refSlug={ref} />
      </header>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      {project && !project.leads_enabled && (
        <div className="mt-6 rounded-xl border border-slate-200 bg-white p-5 text-sm">
          <p>{t("leads.disabled")}</p>
          <Link
            href={`/projects/${ref}/leads/settings`}
            className="mt-2 inline-block text-ink underline"
          >
            {t("leads.openSettings")}
          </Link>
        </div>
      )}

      {project?.leads_enabled && (
        <>
          {stats && (
            <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-6">
              {[
                [t("leads.statTotal"), stats.total],
                [t("leads.statOpen"), stats.open],
                [t("leads.statWon"), stats.won],
                [t("leads.statLost"), stats.lost],
                [
                  t("leads.statWinRate"),
                  stats.win_rate != null ? `${Math.round(stats.win_rate * 100)}%` : "—",
                ],
                [t("leads.statOpenAmount"), money(stats.open_amount) || "—"],
              ].map(([label, value]) => (
                <div key={String(label)} className="rounded-lg border border-slate-200 bg-white p-3">
                  <p className="text-xs text-muted">{label}</p>
                  <p className="mt-1 text-lg font-semibold">{value}</p>
                </div>
              ))}
              <p className="col-span-2 text-xs text-muted sm:col-span-6">{t("leads.statPeriod")}</p>
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <form onSubmit={onCreate} className="flex flex-1 gap-2">
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={t("leads.quickAdd")}
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <button
                type="submit"
                disabled={busy}
                className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                {t("leads.add")}
              </button>
            </form>
            <div className="flex rounded-lg border border-slate-300 text-sm">
              {(["board", "table"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  className={`px-3 py-2 ${view === v ? "bg-slate-100 font-medium" : "text-muted"}`}
                >
                  {t(v === "board" ? "leads.viewBoard" : "leads.viewTable")}
                </button>
              ))}
            </div>
            <Link
              href={`/projects/${ref}/leads/settings`}
              className="px-2 text-sm text-muted hover:text-ink"
            >
              {t("leads.funnelSettings")}
            </Link>
          </div>

          {view === "board" && (
            <div className="mt-6 flex gap-4 overflow-x-auto pb-4">
              {columns.map((col) => (
                <div
                  key={col.stage.id}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setOverCol(col.stage.id);
                  }}
                  onDrop={() => moveTo(col.stage)}
                  className={`w-72 shrink-0 rounded-xl p-1 transition-colors ${
                    overCol === col.stage.id ? "bg-slate-100" : ""
                  }`}
                >
                  <div className="mb-2 flex items-center justify-between px-2">
                    <h2 className="text-sm font-semibold text-ink">{col.stage.name}</h2>
                    <span className="text-xs text-muted">
                      {col.count}
                      {Number(col.amount) > 0 && ` · ${money(col.amount)}`}
                    </span>
                  </div>
                  <div className="flex min-h-[3rem] flex-col gap-2">
                    {col.leads.map((l) => (
                      <div
                        key={l.id}
                        draggable
                        onDragStart={() => setDragId(l.id)}
                        onDragEnd={() => setDragId(null)}
                        onClick={() => router.push(leadHref(l.key))}
                        className={`cursor-pointer rounded-lg border border-slate-200 bg-white p-3 shadow-sm ${
                          dragId === l.id ? "opacity-40" : ""
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-mono text-xs text-muted">{l.key}</span>
                          <span className="text-[10px] text-muted">{l.source}</span>
                        </div>
                        <p className="mt-1 text-sm text-ink">{l.title}</p>
                        <div className="mt-1 flex justify-between text-xs text-muted">
                          <span>{l.contact_name ?? ""}</span>
                          <span>{money(l.amount, l.currency)}</span>
                        </div>
                        {l.task_key && (
                          <p className="mt-1 font-mono text-[10px] text-muted">↳ {l.task_key}</p>
                        )}
                      </div>
                    ))}
                    {col.leads.length === 0 && (
                      <div className="rounded-lg border border-dashed border-slate-200 p-4 text-center text-xs text-muted">
                        {t("board.dropHere")}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {view === "table" && (
            <div className="mt-6">
              <div className="flex gap-2">
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder={t("leads.search")}
                  className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
                <select
                  value={stageFilter}
                  onChange={(e) => setStageFilter(e.target.value)}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
                >
                  <option value="">{t("leads.allStages")}</option>
                  {stages.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </div>
              <table className="mt-3 w-full text-left text-sm">
                <thead className="text-xs text-muted">
                  <tr>
                    <th className="py-2">{t("leads.colKey")}</th>
                    <th>{t("leads.colTitle")}</th>
                    <th>{t("leads.colStage")}</th>
                    <th>{t("leads.colSource")}</th>
                    <th>{t("leads.colContact")}</th>
                    <th className="text-right">{t("leads.colAmount")}</th>
                    <th className="text-right">{t("leads.colReceived")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((l) => (
                    <tr
                      key={l.id}
                      onClick={() => router.push(leadHref(l.key))}
                      className="cursor-pointer border-t border-slate-100 hover:bg-slate-50"
                    >
                      <td className="py-2 font-mono text-xs text-muted">{l.key}</td>
                      <td>{l.title}</td>
                      <td>
                        <span
                          className={`rounded px-1.5 py-0.5 text-xs ${CATEGORY_STYLES[l.stage_category]}`}
                        >
                          {l.stage_name}
                        </span>
                      </td>
                      <td className="text-muted">{l.source}</td>
                      <td>
                        {l.contact_name}
                        {l.phone && <span className="ml-1 text-muted">{l.phone}</span>}
                      </td>
                      <td className="text-right">{money(l.amount, l.currency)}</td>
                      <td className="text-right text-muted">{shortDate(l.received_at)}</td>
                    </tr>
                  ))}
                  {rows.length === 0 && (
                    <tr>
                      <td colSpan={7} className="py-6 text-center text-muted">
                        {t("leads.empty")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </main>
  );
}
