"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import {
  ApiError,
  Attachment,
  Project,
  TaskActivity,
  TaskComment,
  TaskFull,
  TaskPatch,
  TaskStatus,
  UserRow,
  addTaskComment,
  attachmentBlobUrl,
  changeTaskStatus,
  clearTokens,
  deleteAttachment,
  deleteComment,
  deleteTask,
  getMe,
  getProject,
  getTask,
  getTaskByKey,
  getTaskActivity,
  getTaskComments,
  listAttachments,
  listStatuses,
  listUsers,
  updateTask,
  uploadAttachment,
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
const PRIORITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"];

function toDateInput(iso: string | null): string {
  return iso ? new Date(iso).toISOString().slice(0, 10) : "";
}

export default function TaskPage() {
  const router = useRouter();
  const t = useT();
  // This component backs two routes: /tasks/<uuid> and /t/<KEY> (short shareable
  // link). `ref` is whichever param the active route supplied.
  const params = useParams<{ taskId?: string; key?: string }>();
  const ref = (params.taskId ?? params.key ?? "") as string;
  const isKey = /^[A-Za-z]+-\d+$/.test(ref);

  const [task, setTask] = useState<TaskFull | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [statuses, setStatuses] = useState<TaskStatus[]>([]);
  const [usersList, setUsersList] = useState<UserRow[]>([]);
  const [meId, setMeId] = useState<string | null>(null);
  const [comments, setComments] = useState<TaskComment[]>([]);
  const [activity, setActivity] = useState<TaskActivity[]>([]);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [comment, setComment] = useState("");
  const [editingDesc, setEditingDesc] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dropActive, setDropActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const tk = isKey ? await getTaskByKey(ref) : await getTask(ref);
      setTask(tk);
      const [p, st, us, me, cs, ac, at] = await Promise.all([
        getProject(tk.project_id),
        listStatuses(tk.project_id),
        listUsers().catch(() => [] as UserRow[]),
        getMe().catch(() => null),
        getTaskComments(tk.id),
        getTaskActivity(tk.id),
        listAttachments(tk.id).catch(() => [] as Attachment[]),
      ]);
      setProject(p);
      setStatuses([...st].sort((a, b) => a.position - b.position));
      setUsersList(us);
      setMeId(me?.id ?? null);
      setComments(cs);
      setActivity(ac);
      setAttachments(at);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearTokens();
        router.replace("/login");
      } else if (err instanceof ApiError && err.status === 404) {
        setError(t("task.notFound"));
      }
    }
  }, [ref, isKey, router, t]);

  useEffect(() => {
    load();
  }, [load]);

  // Paste screenshots / files straight from the clipboard (Cmd/Ctrl+V).
  useEffect(() => {
    function onPaste(e: ClipboardEvent) {
      const files = Array.from(e.clipboardData?.items ?? [])
        .filter((it) => it.kind === "file")
        .map((it) => it.getAsFile())
        .filter((f): f is File => f !== null);
      if (files.length === 0) return;
      const dt = new DataTransfer();
      files.forEach((f) => dt.items.add(f));
      onUpload(dt.files);
    }
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.id]);

  const usersMap: Record<string, string> = Object.fromEntries(
    usersList.map((u) => [u.id, u.name])
  );
  const name = (id: string | null) => (id ? usersMap[id] ?? "—" : t("task.none"));

  async function patch(fields: TaskPatch) {
    if (!task) return;
    setBusy(true);
    setError(null);
    try {
      await updateTask(task.id, fields);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }
  async function onStatus(statusId: string) {
    if (!task) return;
    setBusy(true);
    try {
      await changeTaskStatus(task.id, statusId);
      await load();
    } finally {
      setBusy(false);
    }
  }
  async function onComment(e: React.FormEvent) {
    e.preventDefault();
    if (!task || !comment.trim()) return;
    setBusy(true);
    try {
      await addTaskComment(task.id, comment.trim());
      setComment("");
      await load();
    } finally {
      setBusy(false);
    }
  }
  async function onDeleteComment(id: string) {
    await deleteComment(id).catch(() => {});
    await load();
  }

  async function onUpload(files: FileList | null) {
    if (!task || !files || files.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      for (const f of Array.from(files)) {
        await uploadAttachment(task.id, f);
      }
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }
  async function onDeleteAttachment(id: string) {
    await deleteAttachment(id).catch(() => {});
    await load();
  }
  async function onDeleteTask() {
    if (!task) return;
    if (!window.confirm(t("task.deleteConfirm"))) return;
    setBusy(true);
    setError(null);
    try {
      await deleteTask(task.id);
      router.push(`/projects/${task.project_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed");
      setBusy(false);
    }
  }

  if (error && !task) {
    return (
      <main className="mx-auto max-w-2xl p-8">
        <p className="text-sm text-red-600">{error}</p>
      </main>
    );
  }
  if (!task) return <main className="p-8 text-sm text-muted">{t("common.loading")}</main>;

  return (
    <main className="mx-auto max-w-5xl p-6">
      <div className="flex items-center gap-2 text-sm">
        <Link href={`/projects/${task.project_id}`} className="text-muted hover:underline">
          ← {project ? `${project.code} ${project.name}` : t("board.board")}
        </Link>
        <span className="text-slate-300">/</span>
        <span className="font-mono text-ink">{task.key}</span>
        {busy && <span className="text-xs text-muted">· {t("task.saving")}</span>}
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}

      <div className="mt-4 grid grid-cols-1 gap-6 md:grid-cols-[1fr_260px]">
        {/* main */}
        <div className="min-w-0">
          <div className="mb-2 flex items-center gap-2">
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                PRIORITY_STYLES[task.priority] ?? "bg-slate-100"
              }`}
            >
              {task.priority}
            </span>
            {task.type_name && <span className="text-xs text-muted">{task.type_name}</span>}
          </div>

          {/* editable title */}
          <input
            key={`title-${task.id}`}
            defaultValue={task.title}
            onBlur={(e) => {
              const v = e.target.value.trim();
              if (v && v !== task.title) patch({ title: v });
            }}
            className="w-full rounded-md border border-transparent px-1 py-0.5 text-xl font-semibold leading-snug hover:border-slate-200 focus:border-slate-300 focus:outline-none"
          />

          {task.is_blocked && (
            <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
              ⛔ {task.blocked_reason || "Blocked"}
            </p>
          )}

          <section className="mt-5">
            <h2 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
              {t("task.description")}
            </h2>
            {editingDesc ? (
              <textarea
                key={`desc-${task.id}`}
                autoFocus
                defaultValue={task.description ?? ""}
                placeholder={t("task.descPlaceholder")}
                rows={5}
                onBlur={(e) => {
                  setEditingDesc(false);
                  if (e.target.value !== (task.description ?? "")) {
                    patch({ description: e.target.value });
                  }
                }}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm leading-relaxed focus:border-slate-400 focus:outline-none"
              />
            ) : (
              <div
                onClick={() => setEditingDesc(true)}
                title={t("task.descEditHint")}
                className="min-h-[3rem] w-full cursor-text rounded-lg border border-transparent px-3 py-2 text-sm leading-relaxed hover:border-slate-200"
              >
                {task.description ? (
                  <Markdown text={task.description} />
                ) : (
                  <span className="text-muted">{t("task.descPlaceholder")}</span>
                )}
              </div>
            )}
          </section>

          <section className="mt-4">
            <h2 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
              {t("task.acceptance")}
            </h2>
            <textarea
              key={`acc-${task.id}`}
              defaultValue={task.acceptance_criteria ?? ""}
              placeholder={t("task.accPlaceholder")}
              rows={3}
              onBlur={(e) => {
                if (e.target.value !== (task.acceptance_criteria ?? "")) {
                  patch({ acceptance_criteria: e.target.value });
                }
              }}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-slate-300 focus:outline-none"
            />
          </section>

          {/* attachments */}
          <section
            className="mt-6"
            onDragOver={(e) => {
              e.preventDefault();
              if (!dropActive) setDropActive(true);
            }}
            onDragLeave={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget as Node)) setDropActive(false);
            }}
            onDrop={(e) => {
              e.preventDefault();
              setDropActive(false);
              onUpload(e.dataTransfer.files);
            }}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold">
                {t("task.attachments")}{" "}
                <span className="text-muted">{attachments.length}</span>
              </h2>
              <button
                type="button"
                onClick={() => fileInput.current?.click()}
                disabled={uploading}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium hover:bg-slate-50 disabled:opacity-50"
              >
                {uploading ? t("task.uploading") : `📎 ${t("task.attach")}`}
              </button>
              <input
                ref={fileInput}
                type="file"
                multiple
                hidden
                onChange={(e) => onUpload(e.target.files)}
              />
            </div>

            {attachments.length > 0 && (
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                {attachments.map((a) => (
                  <AttachmentCard
                    key={a.id}
                    att={a}
                    canDelete={a.uploaded_by === meId}
                    onDelete={() => onDeleteAttachment(a.id)}
                  />
                ))}
              </div>
            )}

            <div
              onClick={() => fileInput.current?.click()}
              className={`mt-3 cursor-pointer rounded-lg border-2 border-dashed px-3 py-4 text-center text-xs transition-colors ${
                dropActive
                  ? "border-indigo-400 bg-indigo-50 text-indigo-600"
                  : "border-slate-200 text-muted hover:border-slate-300"
              }`}
            >
              {uploading ? t("task.uploading") : t("task.dropHint")}
            </div>
          </section>

          {/* comments */}
          <section className="mt-6">
            <h2 className="text-sm font-semibold">
              {t("task.comments")} <span className="text-muted">{comments.length}</span>
            </h2>
            <div className="mt-3 flex flex-col gap-3">
              {comments.map((c) => (
                <div key={c.id} className="group flex gap-2.5">
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-800 text-xs font-semibold text-white">
                    {(name(c.author_id) || "?").slice(0, 1)}
                  </span>
                  <div className="flex-1">
                    <div className="flex items-baseline gap-2 text-xs">
                      <span className="font-medium text-ink">{name(c.author_id)}</span>
                      <span className="text-muted">{new Date(c.created_at).toLocaleString()}</span>
                      {c.author_id === meId && (
                        <button
                          onClick={() => onDeleteComment(c.id)}
                          title={t("task.deleteComment")}
                          className="ml-auto text-slate-300 hover:text-red-500"
                        >
                          ×
                        </button>
                      )}
                    </div>
                    <div className="mt-1 whitespace-pre-wrap rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
                      <Linkified text={c.body} />
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <form onSubmit={onComment} className="mt-3 flex gap-2">
              <input
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder={t("task.commentPlaceholder")}
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <button
                type="submit"
                disabled={busy}
                className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                {t("task.addComment")}
              </button>
            </form>
          </section>

          <section className="mt-6">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">
              {t("task.activity")}
            </h2>
            <div className="mt-2 flex flex-col gap-2">
              {activity.map((a) => (
                <div key={a.id} className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
                  <span className="font-medium text-slate-600">{name(a.actor_id)}</span>
                  <span>{t(`activity.${a.action}`)}</span>
                  {a.data && typeof a.data.from === "string" && (
                    <span>
                      <span className="text-slate-400">{a.data.from as string}</span> →{" "}
                      <span className="text-slate-600">{a.data.to as string}</span>
                    </span>
                  )}
                  <span className="text-slate-400">· {new Date(a.created_at).toLocaleString()}</span>
                </div>
              ))}
            </div>
          </section>
        </div>

        {/* right rail */}
        <aside className="flex h-fit flex-col gap-4 rounded-xl border border-slate-200 bg-white p-4">
          <Field label={t("task.status")}>
            <select
              value={task.status_id}
              disabled={busy}
              onChange={(e) => onStatus(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm"
            >
              {statuses.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            <div className="mt-1 flex items-center gap-1.5 text-xs text-muted">
              <span
                className="h-2 w-2 rounded-full"
                style={{ background: CAT_DOT[task.status_category ?? ""] ?? "#cbd5e1" }}
              />
              {task.status_name}
            </div>
          </Field>

          <Field label={t("task.priority")}>
            <select
              value={task.priority}
              disabled={busy}
              onChange={(e) => patch({ priority: e.target.value })}
              className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm"
            >
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </Field>

          <Field label={t("task.assignee")}>
            <UserSelect
              value={task.assignee_id}
              users={usersList}
              disabled={busy}
              unassigned={t("task.unassigned")}
              onChange={(v) => patch({ assignee_id: v })}
            />
          </Field>
          <Field label={t("task.reviewer")}>
            <UserSelect
              value={task.reviewer_id}
              users={usersList}
              disabled={busy}
              unassigned={t("task.unassigned")}
              onChange={(v) => patch({ reviewer_id: v })}
            />
          </Field>

          <Field label={t("task.due")}>
            <input
              type="date"
              value={toDateInput(task.due_at)}
              disabled={busy}
              onChange={(e) =>
                patch({ due_at: e.target.value ? `${e.target.value}T00:00:00Z` : null })
              }
              className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm"
            />
          </Field>
          <Field label={t("task.points")}>
            <input
              key={`pts-${task.id}`}
              type="number"
              min={0}
              defaultValue={task.story_points ?? ""}
              disabled={busy}
              onBlur={(e) => {
                const v = e.target.value === "" ? null : Number(e.target.value);
                if (v !== task.story_points) patch({ story_points: v });
              }}
              className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm"
            />
          </Field>

          <div className="border-t border-slate-100 pt-3 text-xs text-muted">
            {t("task.reporter")}: {name(task.reporter_id)} · {t("task.type")}:{" "}
            {task.type_name ?? t("task.none")}
          </div>

          <button
            type="button"
            onClick={onDeleteTask}
            disabled={busy}
            className="mt-1 rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
          >
            🗑 {t("task.deleteTask")}
          </button>
        </aside>
      </div>
    </main>
  );
}

// Render plain text with clickable http(s) links (task descriptions & comments).
function Linkified({ text }: { text: string }) {
  const parts = text.split(/(https?:\/\/[^\s]+)/g);
  return (
    <>
      {parts.map((part, i) =>
        /^https?:\/\//.test(part) ? (
          <a
            key={i}
            href={part}
            target="_blank"
            rel="noopener noreferrer"
            className="break-all text-indigo-600 underline hover:text-indigo-700"
          >
            {part}
          </a>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}

// Render a task description as Markdown (headings, lists, bold, links, tables).
// Single newlines become <br> (remark-breaks) so plain-text descriptions keep
// their line breaks; bare URLs auto-link (remark-gfm). No raw HTML → XSS-safe.
function Markdown({ text }: { text: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkBreaks]}
      components={{
        a: ({ node, ...props }) => (
          <a
            {...props}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="break-all text-indigo-600 underline hover:text-indigo-700"
          />
        ),
        p: ({ node, ...props }) => <p className="my-1.5 first:mt-0 last:mb-0" {...props} />,
        ul: ({ node, ...props }) => <ul className="my-1.5 list-disc space-y-0.5 pl-5" {...props} />,
        ol: ({ node, ...props }) => <ol className="my-1.5 list-decimal space-y-0.5 pl-5" {...props} />,
        li: ({ node, ...props }) => <li className="pl-0.5" {...props} />,
        h1: ({ node, ...props }) => <h1 className="mb-1 mt-3 text-base font-semibold first:mt-0" {...props} />,
        h2: ({ node, ...props }) => <h2 className="mb-1 mt-3 text-sm font-semibold first:mt-0" {...props} />,
        h3: ({ node, ...props }) => <h3 className="mb-1 mt-2 text-sm font-semibold first:mt-0" {...props} />,
        strong: ({ node, ...props }) => <strong className="font-semibold" {...props} />,
        code: ({ node, ...props }) => (
          <code className="rounded bg-slate-100 px-1 py-0.5 text-[0.85em]" {...props} />
        ),
        blockquote: ({ node, ...props }) => (
          <blockquote className="my-1.5 border-l-2 border-slate-200 pl-3 text-muted" {...props} />
        ),
        hr: () => <hr className="my-3 border-slate-200" />,
        table: ({ node, ...props }) => (
          <div className="my-2 overflow-x-auto">
            <table className="border-collapse text-xs" {...props} />
          </div>
        ),
        th: ({ node, ...props }) => (
          <th className="border border-slate-200 px-2 py-1 text-left font-semibold" {...props} />
        ),
        td: ({ node, ...props }) => <td className="border border-slate-200 px-2 py-1" {...props} />,
      }}
    >
      {text}
    </ReactMarkdown>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function AttachmentCard({
  att,
  canDelete,
  onDelete,
}: {
  att: Attachment;
  canDelete: boolean;
  onDelete: () => void;
}) {
  const isImage = att.content_type.startsWith("image/");
  const [preview, setPreview] = useState<string | null>(null);

  useEffect(() => {
    if (!isImage) return;
    let url: string | null = null;
    let alive = true;
    attachmentBlobUrl(att.id)
      .then((u) => {
        if (alive) {
          url = u;
          setPreview(u);
        } else {
          URL.revokeObjectURL(u);
        }
      })
      .catch(() => {});
    return () => {
      alive = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [att.id, isImage]);

  async function download() {
    const url = preview ?? (await attachmentBlobUrl(att.id).catch(() => null));
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = att.filename;
    a.click();
    if (!preview) setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  return (
    <div className="group relative overflow-hidden rounded-lg border border-slate-200 bg-white">
      <button
        type="button"
        onClick={download}
        title={att.filename}
        className="block w-full text-left"
      >
        {isImage && preview ? (
          <img src={preview} alt={att.filename} className="h-24 w-full object-cover" />
        ) : (
          <div className="flex h-24 w-full items-center justify-center bg-slate-50 text-2xl">
            📄
          </div>
        )}
        <div className="px-2 py-1.5">
          <div className="truncate text-xs font-medium text-ink">{att.filename}</div>
          <div className="text-[10px] text-muted">{formatBytes(att.size_bytes)}</div>
        </div>
      </button>
      {canDelete && (
        <button
          type="button"
          onClick={onDelete}
          title="Delete"
          className="absolute right-1 top-1 hidden h-5 w-5 items-center justify-center rounded bg-white/90 text-slate-500 shadow-sm hover:text-red-600 group-hover:flex"
        >
          ×
        </button>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
        {label}
      </div>
      {children}
    </div>
  );
}

function UserSelect({
  value,
  users,
  disabled,
  unassigned,
  onChange,
}: {
  value: string | null;
  users: UserRow[];
  disabled: boolean;
  unassigned: string;
  onChange: (v: string | null) => void;
}) {
  return (
    <select
      value={value ?? ""}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value || null)}
      className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm"
    >
      <option value="">{unassigned}</option>
      {users.map((u) => (
        <option key={u.id} value={u.id}>
          {u.name}
        </option>
      ))}
    </select>
  );
}
