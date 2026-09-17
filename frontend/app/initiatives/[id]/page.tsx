"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  Initiative,
  Project,
  Task,
  clearTokens,
  getInitiative,
  getProject,
  listInitiativeTasks,
  updateInitiative,
} from "@/lib/api";
import { useT } from "@/lib/locale";
import { PRIORITY_STYLES } from "@/lib/buckets";

const CAT_DOT: Record<string, string> = {
  BACKLOG: "#94a3b8",
  READY: "#0ea5e9",
  IN_PROGRESS: "#6366f1",
  BLOCKED: "#ef4444",
  REVIEW: "#a855f7",
  CHANGES_REQUIRED: "#f97316",
  DONE: "#22c55e",
};

export default function InitiativePage() {
  const router = useRouter();
  const t = useT();
  const { id } = useParams<{ id: string }>();

  const [initiative, setInitiative] = useState<Initiative | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const ini = await getInitiative(id);
      setInitiative(ini);
      setName(ini.name);
      setDescription(ini.description ?? "");
      const [proj, tk] = await Promise.all([
        getProject(ini.project_id).catch(() => null),
        listInitiativeTasks(id),
      ]);
      setProject(proj);
      setTasks(tk);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearTokens();
        router.replace("/login");
      } else {
        setError(t("initiative.notFound"));
      }
    } finally {
      setLoading(false);
    }
  }, [id, router, t]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setEditError(null);
    setBusy(true);
    try {
      const updated = await updateInitiative(id, {
        name: name.trim(),
        description: description.trim() || null,
      });
      setInitiative(updated);
      setEditing(false);
    } catch (err) {
      setEditError(err instanceof ApiError ? err.message : t("initiative.saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <main className="mx-auto max-w-4xl p-8">
        <p className="text-sm text-muted">{t("common.loading")}</p>
      </main>
    );
  }

  if (error || !initiative) {
    return (
      <main className="mx-auto max-w-4xl p-8">
        <Link href="/projects" className="text-sm text-muted hover:underline">
          {t("common.projects")}
        </Link>
        <p className="mt-4 text-sm text-red-600">{error ?? t("initiative.notFound")}</p>
      </main>
    );
  }

  const pct = initiative.task_count
    ? Math.round((initiative.done_count / initiative.task_count) * 100)
    : 0;

  return (
    <main className="mx-auto max-w-4xl p-8">
      <div className="flex items-center gap-3 text-sm">
        <Link
          href={`/projects/${initiative.project_id}`}
          className="text-muted hover:underline"
        >
          {project ? project.name : t("initiative.back")}
        </Link>
      </div>

      <header className="mt-2 flex items-start justify-between gap-4">
        <h1 className="text-2xl font-semibold">{initiative.name}</h1>
        {!editing && (
          <button
            onClick={() => {
              setName(initiative.name);
              setDescription(initiative.description ?? "");
              setEditError(null);
              setEditing(true);
            }}
            className="shrink-0 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-ink hover:bg-slate-50"
          >
            {t("initiative.edit")}
          </button>
        )}
      </header>

      {/* Progress */}
      <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted">
            {t("initiative.progress", {
              done: initiative.done_count,
              total: initiative.task_count,
            })}
          </span>
          <span className="font-medium text-ink">{pct}%</span>
        </div>
        <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-emerald-500" style={{ width: `${pct}%` }} />
        </div>
      </div>

      {/* Description / edit */}
      {editing ? (
        <form
          onSubmit={onSave}
          className="mt-4 rounded-xl border border-slate-200 bg-white p-4"
        >
          <label className="block text-xs font-medium text-muted">
            {t("initiative.namePlaceholder")}
          </label>
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("initiative.namePlaceholder")}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          <label className="mt-3 block text-xs font-medium text-muted">
            {t("initiative.description")}
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t("initiative.descPlaceholder")}
            rows={4}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          {editError && <p className="mt-2 text-sm text-red-600">{editError}</p>}
          <div className="mt-3 flex gap-2">
            <button
              type="submit"
              disabled={busy}
              className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {busy ? t("initiative.saving") : t("initiative.save")}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-ink hover:bg-slate-50"
            >
              {t("initiative.cancel")}
            </button>
          </div>
        </form>
      ) : (
        <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
          <h2 className="text-xs font-medium uppercase tracking-wide text-muted">
            {t("initiative.description")}
          </h2>
          <p className="mt-2 whitespace-pre-wrap text-sm text-ink">
            {initiative.description ? (
              initiative.description
            ) : (
              <span className="text-muted">{t("initiative.noDescription")}</span>
            )}
          </p>
        </section>
      )}

      {/* Tasks */}
      <section className="mt-6">
        <h2 className="mb-3 text-lg font-semibold">{t("initiative.tasks")}</h2>
        {tasks.length === 0 ? (
          <p className="rounded-xl border border-dashed border-slate-200 p-6 text-center text-sm text-muted">
            {t("initiative.empty")}
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {tasks.map((task) => (
              <li key={task.id}>
                <button
                  onClick={() => router.push(`/tasks/${task.id}`)}
                  className="flex w-full items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 text-left hover:border-slate-300 hover:bg-slate-50"
                >
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ background: CAT_DOT[task.status_category ?? ""] ?? "#cbd5e1" }}
                    title={task.status_name ?? ""}
                  />
                  <span className="shrink-0 font-mono text-xs text-muted">{task.key}</span>
                  <span className="flex-1 truncate text-sm text-ink">{task.title}</span>
                  {task.is_blocked && (
                    <span className="shrink-0 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                      ⚠
                    </span>
                  )}
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${
                      PRIORITY_STYLES[task.priority] ?? "bg-slate-100 text-slate-500"
                    }`}
                  >
                    {task.priority}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
