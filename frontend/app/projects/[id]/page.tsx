"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  Board,
  BoardColumn,
  Project,
  Task,
  clearTokens,
  createTask,
  getBoard,
  getProject,
  moveTask,
} from "@/lib/api";
import { useT } from "@/lib/locale";

const PRIORITY_STYLES: Record<string, string> = {
  CRITICAL: "bg-red-100 text-red-700",
  HIGH: "bg-orange-100 text-orange-700",
  MEDIUM: "bg-slate-100 text-slate-600",
  LOW: "bg-slate-100 text-slate-500",
  NONE: "bg-slate-100 text-slate-400",
};

export default function ProjectBoardPage() {
  const router = useRouter();
  const t = useT();
  const { id } = useParams<{ id: string }>();
  const [board, setBoard] = useState<Board | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [title, setTitle] = useState("");
  const [dragId, setDragId] = useState<string | null>(null);
  const [overCol, setOverCol] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [b, p] = await Promise.all([getBoard(id), getProject(id)]);
      setBoard(b);
      setProject(p);
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
    if (!title.trim()) return;
    setError(null);
    setLoading(true);
    try {
      await createTask({ project_id: id, title: title.trim() });
      setTitle("");
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("board.createFailed"));
    } finally {
      setLoading(false);
    }
  }

  // Drop the dragged task before `beforeTask` (or at the bottom of `col` when null).
  async function drop(col: BoardColumn, beforeTask: Task | null) {
    const taskId = dragId;
    setDragId(null);
    setOverCol(null);
    if (!taskId) return;

    const rest = col.tasks.filter((t) => t.id !== taskId);
    let after_id: string | null = null;
    let before_id: string | null = null;
    if (beforeTask && beforeTask.id !== taskId) {
      const idx = rest.findIndex((t) => t.id === beforeTask.id);
      before_id = beforeTask.id;
      after_id = idx > 0 ? rest[idx - 1].id : null;
    } else {
      after_id = rest.length ? rest[rest.length - 1].id : null;
    }

    try {
      await moveTask(taskId, { status_id: col.status_id, after_id, before_id });
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("board.moveFailed"));
    }
  }

  if (error && !board) {
    return (
      <main className="mx-auto max-w-6xl p-8">
        <p className="text-sm text-red-600">{error}</p>
        <Link href="/projects" className="text-sm text-muted hover:underline">
          {t("board.back")}
        </Link>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-7xl p-8">
      <header>
        <div className="flex items-center justify-between">
          <Link href="/projects" className="text-sm text-muted hover:underline">
            {t("board.back")}
          </Link>
        </div>
        <h1 className="mt-1 text-2xl font-semibold">
          {project && (
            <span className="font-mono text-base text-muted">{project.code} </span>
          )}
          {project?.name ?? "Board"}
        </h1>
        {project?.goal && <p className="mt-1 text-sm text-muted">🎯 {project.goal}</p>}
        <nav className="mt-3 flex gap-4 border-b border-slate-200 text-sm">
          <span className="border-b-2 border-ink pb-2 font-medium">{t("board.board")}</span>
          <Link
            href={`/projects/${id}/sprints`}
            className="pb-2 text-muted hover:text-ink"
          >
            {t("board.sprints")}
          </Link>
        </nav>
      </header>

      <form onSubmit={onCreate} className="mt-6 flex gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t("board.quickAdd")}
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {loading ? t("board.adding") : t("board.addTask")}
        </button>
      </form>

      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

      <div className="mt-6 flex gap-4 overflow-x-auto pb-4">
        {board?.columns.map((col) => (
          <div
            key={col.status_id}
            onDragOver={(e) => {
              e.preventDefault();
              setOverCol(col.status_id);
            }}
            onDrop={() => drop(col, null)}
            className={`w-72 shrink-0 rounded-xl p-1 transition-colors ${
              overCol === col.status_id ? "bg-slate-100" : ""
            }`}
          >
            <div className="mb-2 flex items-center justify-between px-2">
              <h2 className="text-sm font-semibold text-ink">{col.name}</h2>
              <span
                className={`text-xs ${
                  col.wip_exceeded ? "font-semibold text-red-600" : "text-muted"
                }`}
              >
                {col.wip_limit != null
                  ? `${col.tasks.length} / ${col.wip_limit}`
                  : col.tasks.length}
              </span>
            </div>
            {col.wip_exceeded && (
              <p className="mb-2 px-2 text-xs text-red-600">{t("board.wipExceeded")}</p>
            )}
            <div className="flex min-h-[3rem] flex-col gap-2">
              {col.tasks.map((t) => (
                <div
                  key={t.id}
                  draggable
                  onDragStart={() => setDragId(t.id)}
                  onDragEnd={() => setDragId(null)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.stopPropagation();
                    drop(col, t);
                  }}
                  onClick={() => router.push(`/tasks/${t.id}`)}
                  className={`cursor-pointer rounded-lg border border-slate-200 bg-white p-3 shadow-sm active:cursor-grabbing ${
                    dragId === t.id ? "opacity-40" : ""
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs text-muted">{t.key}</span>
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        PRIORITY_STYLES[t.priority] ?? "bg-slate-100"
                      }`}
                    >
                      {t.priority}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-ink">{t.title}</p>
                  {t.is_blocked && (
                    <p className="mt-1 text-xs text-red-600">
                      ⛔ {t.blocked_reason ?? "Blocked"}
                    </p>
                  )}
                </div>
              ))}
              {col.tasks.length === 0 && (
                <div className="rounded-lg border border-dashed border-slate-200 p-4 text-center text-xs text-muted">
                  {t("board.dropHere")}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
