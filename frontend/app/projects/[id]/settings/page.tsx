"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  Member,
  Project,
  UserRow,
  addMember,
  archiveProject,
  clearTokens,
  getProjectByRef,
  listMembers,
  listUsers,
  removeMember,
  unarchiveProject,
  updateProject,
} from "@/lib/api";
import { useT } from "@/lib/locale";

// ARCHIVED is deliberately absent: archiving goes through its own button below,
// so the audit log and `archived_at` stay in sync.
const STATUSES = ["DRAFT", "ACTIVE", "ON_HOLD", "COMPLETED"];
const HEALTHS = ["ON_TRACK", "AT_RISK", "OFF_TRACK"];
const PROJECT_ROLES = ["VIEWER", "MEMBER", "MANAGER", "OWNER"];

interface Form {
  name: string;
  goal: string;
  description: string;
  group_name: string;
  status: string;
  health: string;
  wip_limit: string;
}

const EMPTY: Form = {
  name: "",
  goal: "",
  description: "",
  group_name: "",
  status: "DRAFT",
  health: "ON_TRACK",
  wip_limit: "",
};

function toForm(p: Project): Form {
  return {
    name: p.name,
    goal: p.goal ?? "",
    description: p.description ?? "",
    group_name: p.group_name ?? "",
    status: p.status === "ARCHIVED" ? "ACTIVE" : p.status,
    health: p.health,
    wip_limit: p.wip_limit != null ? String(p.wip_limit) : "",
  };
}

export default function ProjectSettingsPage() {
  const router = useRouter();
  const t = useT();
  // Alias route param (project code, e.g. "mur"); UUIDs still resolve.
  const { id: ref } = useParams<{ id: string }>();

  const [project, setProject] = useState<Project | null>(null);
  const [form, setForm] = useState<Form>(EMPTY);
  const [members, setMembers] = useState<Member[] | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [pickUser, setPickUser] = useState("");
  const [pickRole, setPickRole] = useState("MEMBER");
  const [busy, setBusy] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [memberError, setMemberError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const p = await getProjectByRef(ref);
      setProject(p);
      setForm(toForm(p));
      // Members need PROJECT_MEMBERS_VIEW and the user picker needs WORKSPACE_VIEW;
      // either can be refused, and the page still works without them.
      const [ms, us] = await Promise.all([
        listMembers(p.id).then<Member[] | null>((x) => x).catch(() => null),
        listUsers().catch(() => [] as UserRow[]),
      ]);
      setMembers(ms);
      setUsers(us);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearTokens();
        router.replace("/login");
      } else {
        setError(t("board.notFound"));
      }
    }
  }, [ref, router, t]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  function set<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((f) => ({ ...f, [key]: value }));
    setSaved(false);
  }

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    if (!project) return;
    setError(null);
    setBusy("save");
    try {
      const wip = form.wip_limit.trim();
      const updated = await updateProject(project.id, {
        name: form.name.trim(),
        goal: form.goal.trim(),
        description: form.description.trim(),
        group_name: form.group_name.trim(),
        // an archived project keeps its ARCHIVED status until it is restored
        status: project.status === "ARCHIVED" ? undefined : form.status,
        health: form.health,
        wip_limit: wip === "" ? undefined : Number(wip),
      });
      setProject(updated);
      setForm(toForm(updated));
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("settings.saveFailed"));
    } finally {
      setBusy(null);
    }
  }

  async function onArchiveToggle() {
    if (!project) return;
    const archived = project.status === "ARCHIVED";
    if (!archived && !window.confirm(t("settings.archiveConfirm", { name: project.name }))) {
      return;
    }
    setError(null);
    setBusy("archive");
    try {
      const updated = archived
        ? await unarchiveProject(project.id)
        : await archiveProject(project.id);
      setProject(updated);
      setForm(toForm(updated));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("settings.archiveFailed"));
    } finally {
      setBusy(null);
    }
  }

  async function onMemberRole(userId: string, role: string) {
    if (!project) return;
    setMemberError(null);
    setBusy(`m:${userId}`);
    try {
      await addMember(project.id, userId, role);
      setMembers((prev) =>
        (prev ?? []).map((m) => (m.user_id === userId ? { ...m, role } : m))
      );
    } catch (err) {
      setMemberError(err instanceof ApiError ? err.message : t("settings.memberFailed"));
    } finally {
      setBusy(null);
    }
  }

  async function onMemberRemove(m: Member) {
    if (!project) return;
    if (!window.confirm(t("settings.memberRemoveConfirm", { name: m.name }))) return;
    setMemberError(null);
    setBusy(`m:${m.user_id}`);
    try {
      await removeMember(project.id, m.user_id);
      setMembers((prev) => (prev ?? []).filter((x) => x.user_id !== m.user_id));
    } catch (err) {
      setMemberError(err instanceof ApiError ? err.message : t("settings.memberFailed"));
    } finally {
      setBusy(null);
    }
  }

  async function onMemberAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!project || !pickUser) return;
    setMemberError(null);
    setBusy("m:add");
    try {
      const m = await addMember(project.id, pickUser, pickRole);
      setMembers((prev) => [...(prev ?? []).filter((x) => x.user_id !== m.user_id), m]);
      setPickUser("");
    } catch (err) {
      setMemberError(err instanceof ApiError ? err.message : t("settings.memberFailed"));
    } finally {
      setBusy(null);
    }
  }

  if (error && !project) {
    return (
      <main className="mx-auto max-w-3xl p-8">
        <p className="text-sm text-red-600">{error}</p>
        <Link href="/projects" className="text-sm text-muted hover:underline">
          {t("board.back")}
        </Link>
      </main>
    );
  }
  if (!project) {
    return <main className="p-8 text-sm text-muted">{t("common.loading")}</main>;
  }

  const archived = project.status === "ARCHIVED";
  const candidates = users.filter(
    (u) => !(members ?? []).some((m) => m.user_id === u.id)
  );

  return (
    <main className="mx-auto max-w-3xl p-8">
      <header>
        <Link href="/projects" className="text-sm text-muted hover:underline">
          {t("board.back")}
        </Link>
        <h1 className="mt-1 flex items-center gap-2 text-2xl font-semibold">
          <span className="font-mono text-base text-muted">{project.code}</span>
          {project.name}
          {archived && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-normal text-slate-500">
              {t("settings.archivedBadge")}
            </span>
          )}
        </h1>
        <nav className="mt-3 flex gap-4 border-b border-slate-200 text-sm">
          <Link href={`/projects/${ref}`} className="pb-2 text-muted hover:text-ink">
            {t("board.board")}
          </Link>
          <Link href={`/projects/${ref}/sprints`} className="pb-2 text-muted hover:text-ink">
            {t("board.sprints")}
          </Link>
          <span className="border-b-2 border-ink pb-2 font-medium">
            {t("board.settings")}
          </span>
        </nav>
      </header>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      <form
        onSubmit={onSave}
        className="mt-6 rounded-xl border border-slate-200 bg-white p-5"
      >
        <h2 className="text-sm font-semibold">{t("settings.details")}</h2>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="text-xs font-medium text-muted">{t("settings.name")}</span>
            <input
              required
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-muted">{t("settings.code")}</span>
            <input
              value={project.code}
              readOnly
              className="mt-1 w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-sm text-muted"
            />
          </label>
          <label className="block sm:col-span-2">
            <span className="text-xs font-medium text-muted">{t("settings.goal")}</span>
            <input
              value={form.goal}
              onChange={(e) => set("goal", e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              placeholder={t("projects.goalPlaceholder")}
            />
          </label>
          <label className="block sm:col-span-2">
            <span className="text-xs font-medium text-muted">
              {t("settings.description")}
            </span>
            <textarea
              value={form.description}
              onChange={(e) => set("description", e.target.value)}
              rows={3}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-muted">{t("settings.group")}</span>
            <input
              value={form.group_name}
              onChange={(e) => set("group_name", e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              placeholder={t("projects.groupPlaceholder")}
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-muted">{t("settings.wip")}</span>
            <input
              type="number"
              min={1}
              max={100}
              value={form.wip_limit}
              onChange={(e) => set("wip_limit", e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-muted">{t("settings.status")}</span>
            <select
              value={form.status}
              disabled={archived}
              onChange={(e) => set("status", e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm disabled:bg-slate-50 disabled:text-muted"
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-xs font-medium text-muted">{t("settings.health")}</span>
            <select
              value={form.health}
              onChange={(e) => set("health", e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
              {HEALTHS.map((h) => (
                <option key={h} value={h}>
                  {h}
                </option>
              ))}
            </select>
          </label>
        </div>

        <p className="mt-3 text-xs text-muted">
          {t("settings.codeHint", { slug: project.code.toLowerCase() })} {t("settings.wipHint")}
        </p>

        <div className="mt-4 flex items-center gap-3">
          <button
            type="submit"
            disabled={busy === "save"}
            className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy === "save" ? t("settings.saving") : t("settings.save")}
          </button>
          {saved && <span className="text-sm text-emerald-600">{t("settings.saved")}</span>}
        </div>
      </form>

      <section className="mt-6 rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="text-sm font-semibold">{t("settings.archiveTitle")}</h2>
        <p className="mt-1 text-sm text-muted">{t("settings.archiveHint")}</p>
        {archived && project.archived_at && (
          <p className="mt-2 text-sm text-muted">
            {t("settings.archivedAt", {
              date: new Date(project.archived_at).toLocaleDateString(),
            })}
          </p>
        )}
        <button
          type="button"
          onClick={onArchiveToggle}
          disabled={busy === "archive"}
          className={`mt-3 rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50 ${
            archived
              ? "bg-ink text-white"
              : "border border-red-200 bg-red-50 text-red-700 hover:bg-red-100"
          }`}
        >
          {busy === "archive"
            ? archived
              ? t("settings.restoring")
              : t("settings.archiving")
            : archived
              ? t("settings.restore")
              : t("settings.archive")}
        </button>
      </section>

      <section className="mt-6 rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="text-sm font-semibold">{t("settings.members")}</h2>
        <p className="mt-1 text-sm text-muted">{t("settings.membersHint")}</p>

        {members === null ? (
          <p className="mt-3 text-sm text-muted">{t("settings.membersNoAccess")}</p>
        ) : (
          <>
            <table className="mt-3 w-full text-sm">
              <tbody>
                {members.length === 0 && (
                  <tr>
                    <td className="py-3 text-muted" colSpan={3}>
                      {t("settings.membersEmpty")}
                    </td>
                  </tr>
                )}
                {members.map((m) => (
                  <tr key={m.user_id} className="border-t border-slate-100">
                    <td className="py-2">
                      <div className="font-medium">{m.name}</div>
                      <div className="text-xs text-muted">{m.email}</div>
                    </td>
                    <td className="py-2">
                      <select
                        value={m.role}
                        disabled={busy === `m:${m.user_id}`}
                        onChange={(e) => onMemberRole(m.user_id, e.target.value)}
                        className="rounded-lg border border-slate-300 px-2 py-1 text-sm"
                      >
                        {PROJECT_ROLES.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="py-2 text-right">
                      <button
                        type="button"
                        onClick={() => onMemberRemove(m)}
                        disabled={busy === `m:${m.user_id}`}
                        className="text-sm text-red-600 hover:underline disabled:opacity-50"
                      >
                        {t("settings.memberRemove")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {candidates.length > 0 && (
              <form onSubmit={onMemberAdd} className="mt-4 flex flex-wrap items-center gap-2">
                <select
                  value={pickUser}
                  onChange={(e) => setPickUser(e.target.value)}
                  className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                >
                  <option value="">{t("settings.pickUser")}</option>
                  {candidates.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name} · {u.email}
                    </option>
                  ))}
                </select>
                <select
                  value={pickRole}
                  onChange={(e) => setPickRole(e.target.value)}
                  className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                >
                  {PROJECT_ROLES.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
                <button
                  type="submit"
                  disabled={!pickUser || busy === "m:add"}
                  className="rounded-lg bg-ink px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                >
                  {t("settings.memberAdd")}
                </button>
              </form>
            )}
          </>
        )}
        {memberError && <p className="mt-3 text-sm text-red-600">{memberError}</p>}
      </section>
    </main>
  );
}
