"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  Sprint,
  Task,
  clearTokens,
  completeSprint,
  createSprint,
  getBacklog,
  listSprints,
  startSprint,
} from "@/lib/api";
import { useT } from "@/lib/locale";

const STATUS_STYLES: Record<string, string> = {
  PLANNED: "bg-slate-100 text-slate-600",
  ACTIVE: "bg-indigo-100 text-indigo-700",
  COMPLETED: "bg-emerald-100 text-emerald-700",
  CANCELLED: "bg-slate-100 text-slate-400",
};

const PRIORITY_STYLES: Record<string, string> = {
  CRITICAL: "bg-red-100 text-red-700",
  HIGH: "bg-orange-100 text-orange-700",
  MEDIUM: "bg-slate-100 text-slate-600",
  LOW: "bg-slate-100 text-slate-500",
  NONE: "bg-slate-100 text-slate-400",
};

export default function SprintsPage() {
  const router = useRouter();
  const t = useT();
  const { id } = useParams<{ id: string }>();
  const [sprints, setSprints] = useState<Sprint[]>([]);
  const [backlog, setBacklog] = useState<Task[]>([]);
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, b] = await Promise.all([listSprints(id), getBacklog(id)]);
      setSprints(s);
      setBacklog(b);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearTokens();
        router.replace("/login");
      } else if (err instanceof ApiError && err.status === 404) {
        setError(t("board.notFound"));
      }
    }
  }, [id, router, t]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setError(null);
    setBusy("create");
    try {
      await createSprint(id, { name: name.trim(), goal: goal.trim() || undefined });
      setName("");
      setGoal("");
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("sprints.createFailed"));
    } finally {
      setBusy(null);
    }
  }

  async function act(fn: () => Promise<unknown>, key: string) {
    setError(null);
    setBusy(key);
    try {
      await fn();
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("sprints.actionFailed"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="mx-auto max-w-4xl p-8">
      <header>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 text-sm">
            <Link href={`/projects/${id}`} className="text-muted hover:underline">
              {t("board.board")}
            </Link>
            <span className="font-medium text-ink">{t("board.sprints")}</span>
          </div>
        </div>
        <h1 className="mt-2 text-2xl font-semibold">{t("sprints.title")}</h1>
      </header>

      <form
        onSubmit={onCreate}
        className="mt-6 flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4"
      >
        <div>
          <label className="block text-xs font-medium text-muted">{t("sprints.newName")}</label>
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("sprints.namePlaceholder")}
            className="mt-1 w-40 rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
        <div className="flex-1">
          <label className="block text-xs font-medium text-muted">{t("sprints.goal")}</label>
          <input
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder={t("sprints.goalPlaceholder")}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={busy === "create"}
          className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy === "create" ? t("sprints.creating") : t("sprints.create")}
        </button>
      </form>

      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

      <section className="mt-6 flex flex-col gap-3">
        {sprints.length === 0 && (
          <p className="rounded-xl border border-dashed border-slate-200 p-6 text-center text-sm text-muted">
            {t("sprints.empty")}
          </p>
        )}
        {sprints.map((s) => {
          const pct = s.stats.total ? Math.round((s.stats.done / s.stats.total) * 100) : 0;
          return (
            <div key={s.id} className="rounded-xl border border-slate-200 bg-white p-4">
              <div className="flex items-center gap-3">
                <h2 className="font-semibold">{s.name}</h2>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    STATUS_STYLES[s.status] ?? "bg-slate-100"
                  }`}
                >
                  {t(`sprints.status.${s.status}`)}
                </span>
                <div className="ml-auto flex items-center gap-2">
                  {s.status === "PLANNED" && (
                    <button
                      onClick={() => act(() => startSprint(s.id), s.id)}
                      disabled={busy === s.id || !s.goal}
                      title={!s.goal ? t("sprints.noGoal") : undefined}
                      className="rounded-lg bg-ink px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
                    >
                      {busy === s.id ? t("sprints.working") : t("sprints.start")}
                    </button>
                  )}
                  {s.status === "ACTIVE" && (
                    <button
                      onClick={() => act(() => completeSprint(s.id), s.id)}
                      disabled={busy === s.id}
                      className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-sm font-medium text-emerald-700 disabled:opacity-40"
                    >
                      {busy === s.id ? t("sprints.working") : t("sprints.complete")}
                    </button>
                  )}
                </div>
              </div>

              <p className="mt-1 text-sm text-muted">
                {s.goal ? `🎯 ${s.goal}` : <span className="italic">{t("sprints.noGoal")}</span>}
              </p>

              <div className="mt-3 flex items-center gap-3">
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                  <div className="h-full bg-emerald-500" style={{ width: `${pct}%` }} />
                </div>
                <span className="text-xs tabular-nums text-muted">
                  {t("sprints.progress", { done: s.stats.done, total: s.stats.total })}
                </span>
              </div>
            </div>
          );
        })}
      </section>

      <section className="mt-8">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
          {t("backlog.title")}
        </h2>
        <div className="mt-3 overflow-hidden rounded-xl border border-slate-200 bg-white">
          {backlog.length === 0 && (
            <p className="px-4 py-6 text-center text-sm text-muted">{t("backlog.empty")}</p>
          )}
          {backlog.map((task) => (
            <div
              key={task.id}
              className="flex items-center gap-3 border-t border-slate-100 px-4 py-2.5 first:border-t-0"
            >
              <span
                className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                  PRIORITY_STYLES[task.priority] ?? "bg-slate-100"
                }`}
              >
                {task.priority}
              </span>
              <span className="font-mono text-xs text-muted">{task.key}</span>
              <span className="truncate text-sm">{task.title}</span>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
