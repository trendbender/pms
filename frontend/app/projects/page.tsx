"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  Project,
  clearTokens,
  createProject,
  listProjects,
} from "@/lib/api";
import { useT } from "@/lib/locale";

const HEALTH_STYLES: Record<string, string> = {
  ON_TRACK: "bg-emerald-100 text-emerald-700",
  AT_RISK: "bg-amber-100 text-amber-700",
  OFF_TRACK: "bg-red-100 text-red-700",
};

export default function ProjectsPage() {
  const router = useRouter();
  const t = useT();
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [goal, setGoal] = useState("");
  const [group, setGroup] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    try {
      setProjects(await listProjects());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearTokens();
        router.replace("/login");
      }
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await createProject({
        name,
        code,
        goal: goal || undefined,
        group_name: group || undefined,
      });
      setName("");
      setCode("");
      setGoal("");
      setGroup("");
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("projects.createFailed"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-4xl p-8">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t("projects.title")}</h1>
        <div className="flex items-center gap-3">
          <Link href="/dashboard" className="text-sm text-muted hover:underline">
            {t("projects.back")}
          </Link>
        </div>
      </header>

      <form
        onSubmit={onCreate}
        className="mt-6 flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4"
      >
        <div>
          <label className="block text-xs font-medium text-muted">{t("projects.name")}</label>
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 w-56 rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder={t("projects.namePlaceholder")}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-muted">{t("projects.code")}</label>
          <input
            required
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            className="mt-1 w-28 rounded-lg border border-slate-300 px-3 py-2 text-sm uppercase"
            placeholder="UBO"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-muted">{t("projects.group")}</label>
          <input
            value={group}
            onChange={(e) => setGroup(e.target.value)}
            className="mt-1 w-40 rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder={t("projects.groupPlaceholder")}
          />
        </div>
        <div className="flex-1">
          <label className="block text-xs font-medium text-muted">{t("projects.goalOptional")}</label>
          <input
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder={t("projects.goalPlaceholder")}
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {loading ? t("projects.creating") : t("projects.create")}
        </button>
      </form>

      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

      <div className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-muted">
            <tr>
              <th className="px-4 py-2 font-medium">{t("table.code")}</th>
              <th className="px-4 py-2 font-medium">{t("table.name")}</th>
              <th className="px-4 py-2 font-medium">{t("table.goal")}</th>
              <th className="px-4 py-2 font-medium">{t("table.health")}</th>
              <th className="px-4 py-2 font-medium">{t("table.status")}</th>
            </tr>
          </thead>
          <tbody>
            {projects.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-muted">
                  {t("projects.empty")}
                </td>
              </tr>
            )}
            {projects.map((p) => (
              <tr
                key={p.id}
                onClick={() => router.push(`/projects/${p.id}`)}
                className="cursor-pointer border-t border-slate-100 hover:bg-slate-50"
              >
                <td className="px-4 py-2 font-mono text-xs">{p.code}</td>
                <td className="px-4 py-2 font-medium text-ink hover:underline">{p.name}</td>
                <td className="px-4 py-2 text-muted">{p.goal ?? "—"}</td>
                <td className="px-4 py-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs ${
                      HEALTH_STYLES[p.health] ?? "bg-slate-100 text-slate-600"
                    }`}
                  >
                    {p.health}
                  </span>
                </td>
                <td className="px-4 py-2 text-muted">{p.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
