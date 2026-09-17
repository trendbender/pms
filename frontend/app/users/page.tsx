"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  Member,
  Project,
  UserRow,
  addMember,
  clearTokens,
  getMe,
  inviteUser,
  listMembers,
  listProjects,
  listUsers,
  removeMember,
  updateUser,
} from "@/lib/api";
import { AppNav } from "@/components/AppNav";

// System roles (workspace-level). OWNER/ADMIN are superusers on every project.
const SYSTEM_ROLES = ["MEMBER", "MANAGER", "ADMIN", "VIEWER", "GUEST", "OWNER"];
// Per-project roles; "" = no access.
const PROJECT_ROLES = ["", "VIEWER", "MEMBER", "MANAGER", "OWNER"];

type Access = Record<string, Record<string, string>>; // projectId -> userId -> role

export default function UsersPage() {
  const router = useRouter();
  const [meRole, setMeRole] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [access, setAccess] = useState<Access>({});
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // invite form
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("MEMBER");
  const [password, setPassword] = useState("");
  const [inviteMsg, setInviteMsg] = useState<string | null>(null);

  const isAdmin = meRole === "OWNER" || meRole === "ADMIN";

  const loadAll = useCallback(async () => {
    const [us, ps] = await Promise.all([listUsers(), listProjects()]);
    setUsers([...us].sort((a, b) => a.name.localeCompare(b.name)));
    ps.sort((a, b) => (a.group_name || "").localeCompare(b.group_name || "") || a.code.localeCompare(b.code));
    setProjects(ps);
    // build access map: fetch members of every project once
    const acc: Access = {};
    const members = await Promise.all(
      ps.map((p) => listMembers(p.id).catch(() => [] as Member[]))
    );
    ps.forEach((p, i) => {
      acc[p.id] = {};
      members[i].forEach((m) => {
        acc[p.id][m.user_id] = m.role;
      });
    });
    setAccess(acc);
  }, []);

  useEffect(() => {
    getMe()
      .then(async (me) => {
        setMeRole(me.system_role);
        if (me.system_role === "OWNER" || me.system_role === "ADMIN") {
          await loadAll().catch((e) => setError(String(e)));
        }
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearTokens();
          router.replace("/login");
        }
      })
      .finally(() => setReady(true));
  }, [router, loadAll]);

  async function onInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !name.trim()) return;
    setBusy(true);
    setError(null);
    setInviteMsg(null);
    try {
      await inviteUser({
        email: email.trim(),
        name: name.trim(),
        system_role: role,
        initial_password: password.trim() || undefined,
      });
      setInviteMsg(
        password.trim()
          ? `Приглашён ${email.trim()} — передайте пароль, попросите сменить после входа.`
          : `Приглашён ${email.trim()} — задайте ему пароль (пока без пароля вход невозможен).`
      );
      setEmail("");
      setName("");
      setPassword("");
      setRole("MEMBER");
      await loadAll();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось пригласить");
    } finally {
      setBusy(false);
    }
  }

  async function onSystemRole(u: UserRow, newRole: string) {
    setBusy(true);
    setError(null);
    try {
      await updateUser(u.id, { system_role: newRole });
      setUsers((prev) => prev.map((x) => (x.id === u.id ? { ...x, system_role: newRole } : x)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось изменить роль");
    } finally {
      setBusy(false);
    }
  }

  async function onToggleSuspend(u: UserRow) {
    setBusy(true);
    setError(null);
    try {
      const next = !u.is_suspended;
      await updateUser(u.id, { is_suspended: next });
      setUsers((prev) => prev.map((x) => (x.id === u.id ? { ...x, is_suspended: next } : x)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось изменить статус");
    } finally {
      setBusy(false);
    }
  }

  async function onProjectRole(projectId: string, userId: string, newRole: string) {
    setBusy(true);
    setError(null);
    const prevRole = access[projectId]?.[userId] ?? "";
    try {
      if (newRole === "") {
        await removeMember(projectId, userId);
      } else {
        await addMember(projectId, userId, newRole);
      }
      setAccess((prev) => {
        const copy: Access = { ...prev, [projectId]: { ...(prev[projectId] || {}) } };
        if (newRole === "") delete copy[projectId][userId];
        else copy[projectId][userId] = newRole;
        return copy;
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `Не удалось изменить доступ (было: ${prevRole || "нет"})`);
    } finally {
      setBusy(false);
    }
  }

  if (!ready) return <main className="p-8 text-sm text-muted">Загрузка…</main>;
  if (!isAdmin) {
    return (
      <>
        <AppNav />
        <main className="mx-auto max-w-3xl p-8">
          <p className="text-sm text-red-600">
            Недостаточно прав. Управление пользователями доступно только владельцу и админам воркспейса.
          </p>
        </main>
      </>
    );
  }

  return (
    <>
      <AppNav active="users" />
      <main className="mx-auto max-w-5xl p-6">
        <h1 className="text-2xl font-semibold">Пользователи</h1>
        <p className="mt-1 text-sm text-muted">
          Приглашение сотрудников, системные роли и доступ к проектам. OWNER/ADMIN — суперпользователи
          на всех проектах; остальным доступ выдаётся по проектам ниже.
        </p>

        {error && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

        {/* invite */}
        <form
          onSubmit={onInvite}
          className="mt-5 flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4"
        >
          <div>
            <label className="mb-1 block text-xs font-medium text-muted">Имя</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Антон"
              className="w-40 rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="anton@example.com"
              className="w-56 rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted">Системная роль</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="rounded-lg border border-slate-300 px-2.5 py-2 text-sm"
            >
              {SYSTEM_ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted">Пароль (мин. 8)</label>
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="временный"
              className="w-40 rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Пригласить
          </button>
        </form>
        {inviteMsg && <p className="mt-2 text-sm text-green-700">{inviteMsg}</p>}

        {/* users table */}
        <div className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-2.5">Имя</th>
                <th className="px-4 py-2.5">Email</th>
                <th className="px-4 py-2.5">Системная роль</th>
                <th className="px-4 py-2.5">Статус</th>
                <th className="px-4 py-2.5">Доступ к проектам</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const nProjects = projects.filter((p) => access[p.id]?.[u.id]).length;
                const superuser = u.system_role === "OWNER" || u.system_role === "ADMIN";
                return (
                  <Fragment key={u.id}>
                    <tr className="border-t border-slate-100">
                      <td className="px-4 py-2.5 font-medium text-ink">{u.name}</td>
                      <td className="px-4 py-2.5 text-muted">{u.email}</td>
                      <td className="px-4 py-2.5">
                        <select
                          value={u.system_role ?? "MEMBER"}
                          disabled={busy}
                          onChange={(e) => onSystemRole(u, e.target.value)}
                          className="rounded-lg border border-slate-300 px-2 py-1 text-sm"
                        >
                          {SYSTEM_ROLES.map((r) => (
                            <option key={r} value={r}>
                              {r}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-4 py-2.5">
                        <button
                          onClick={() => onToggleSuspend(u)}
                          disabled={busy}
                          className={
                            "rounded-full px-2.5 py-0.5 text-xs font-medium " +
                            (u.is_suspended
                              ? "bg-red-50 text-red-700 hover:bg-red-100"
                              : "bg-green-50 text-green-700 hover:bg-green-100")
                          }
                        >
                          {u.is_suspended ? "заблокирован" : "активен"}
                        </button>
                      </td>
                      <td className="px-4 py-2.5">
                        <button
                          onClick={() => setExpanded(expanded === u.id ? null : u.id)}
                          className="text-sm text-indigo-600 hover:underline"
                        >
                          {superuser
                            ? "суперпользователь (все проекты)"
                            : `${nProjects} проект(ов) ${expanded === u.id ? "▾" : "▸"}`}
                        </button>
                      </td>
                    </tr>
                    {expanded === u.id && !superuser && (
                      <tr className="border-t border-slate-100 bg-slate-50/50">
                        <td colSpan={5} className="px-4 py-3">
                          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
                            {projects.map((p) => (
                              <div key={p.id} className="flex items-center gap-2">
                                <span className="w-14 shrink-0 font-mono text-xs text-slate-500">{p.code}</span>
                                <span className="flex-1 truncate text-xs text-slate-600" title={p.name}>
                                  {p.name}
                                </span>
                                <select
                                  value={access[p.id]?.[u.id] ?? ""}
                                  disabled={busy}
                                  onChange={(e) => onProjectRole(p.id, u.id, e.target.value)}
                                  className="rounded-md border border-slate-300 px-1.5 py-0.5 text-xs"
                                >
                                  {PROJECT_ROLES.map((r) => (
                                    <option key={r} value={r}>
                                      {r === "" ? "— нет —" : r}
                                    </option>
                                  ))}
                                </select>
                              </div>
                            ))}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </main>
    </>
  );
}
