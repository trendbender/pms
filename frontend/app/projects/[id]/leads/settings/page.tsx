"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  LeadCategory,
  LeadFieldType,
  LeadSettings,
  LeadToken,
  Project,
  clearTokens,
  createLeadField,
  createLeadStage,
  createLeadToken,
  deleteLeadField,
  deleteLeadStage,
  disableLeads,
  enableLeads,
  getLeadSettings,
  getProjectByRef,
  revokeLeadToken,
  updateLeadStage,
} from "@/lib/api";
import { useT } from "@/lib/locale";
import ProjectTabs from "@/components/ProjectTabs";

const PRESETS = ["sales", "orders", "basic"] as const;
const CATEGORIES: LeadCategory[] = ["OPEN", "WON", "LOST"];
const FIELD_TYPES: LeadFieldType[] = [
  "text", "number", "money", "date", "datetime", "select", "phone", "email", "url",
];

export default function LeadSettingsPage() {
  const router = useRouter();
  const t = useT();
  const { id: ref } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [s, setS] = useState<LeadSettings | null>(null);
  const [preset, setPreset] = useState<(typeof PRESETS)[number]>("sales");
  const [stageName, setStageName] = useState("");
  const [stageCat, setStageCat] = useState<LeadCategory>("OPEN");
  const [field, setField] = useState({
    key: "", label: "", type: "text" as LeadFieldType, options: "", required: false, is_pii: false,
  });
  const [tokenLabel, setTokenLabel] = useState("");
  const [newToken, setNewToken] = useState<LeadToken | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const p = await getProjectByRef(ref);
      setProject(p);
      setS(await getLeadSettings(p.id));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearTokens();
        router.replace("/login");
      } else if (err instanceof ApiError && err.status === 404) {
        setError(t("leads.settingsNoAccess"));
      } else {
        setError(err instanceof ApiError ? err.message : String(err));
      }
    }
  }, [ref, router, t]);

  useEffect(() => {
    load();
  }, [load]);

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  const canEdit = s?.tokens != null; // токены отдаются только с правом lead.settings

  return (
    <main className="mx-auto max-w-4xl p-8">
      <Link href="/projects" className="text-sm text-muted hover:underline">
        {t("board.back")}
      </Link>
      <h1 className="mt-1 text-2xl font-semibold">
        {project && <span className="font-mono text-base text-muted">{project.code} </span>}
        {t("leads.settingsTitle")}
      </h1>
      <ProjectTabs project={project} active="leads" refSlug={ref} />

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      {s && !s.enabled && (
        <section className="mt-6 rounded-xl border border-slate-200 bg-white p-5 text-sm">
          <p>{t("leads.enableHint")}</p>
          <div className="mt-3 flex items-center gap-2">
            <select
              value={preset}
              onChange={(e) => setPreset(e.target.value as (typeof PRESETS)[number])}
              className="rounded-lg border border-slate-300 px-3 py-2"
            >
              {PRESETS.map((p) => (
                <option key={p} value={p}>
                  {t(`leads.preset.${p}`)}
                </option>
              ))}
            </select>
            <button
              disabled={!canEdit || !project}
              onClick={() => project && run(() => enableLeads(project.id, preset))}
              className="rounded-lg bg-ink px-4 py-2 font-medium text-white disabled:opacity-50"
            >
              {t("leads.enable")}
            </button>
          </div>
          {s.stages.length > 0 && <p className="mt-2 text-xs text-muted">{t("leads.reenableHint")}</p>}
        </section>
      )}

      {s?.enabled && project && (
        <>
          <section className="mt-6 rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-sm font-semibold">{t("leads.stages")}</h2>
            <ul className="mt-3 space-y-2">
              {s.stages.map((st) => (
                <li key={st.id} className="flex items-center gap-2 text-sm">
                  <input
                    defaultValue={st.name}
                    disabled={!canEdit}
                    onBlur={(e) =>
                      e.target.value.trim() &&
                      e.target.value.trim() !== st.name &&
                      run(() => updateLeadStage(st.id, { name: e.target.value.trim() }))
                    }
                    className="flex-1 rounded border border-slate-200 px-2 py-1"
                  />
                  <select
                    value={st.category}
                    disabled={!canEdit}
                    onChange={(e) =>
                      run(() => updateLeadStage(st.id, { category: e.target.value as LeadCategory }))
                    }
                    className="rounded border border-slate-200 px-2 py-1"
                  >
                    {CATEGORIES.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                  {canEdit && (
                    <button
                      onClick={() => run(() => deleteLeadStage(st.id))}
                      className="text-xs text-red-600 hover:underline"
                    >
                      {t("leads.remove")}
                    </button>
                  )}
                </li>
              ))}
            </ul>
            {canEdit && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!stageName.trim()) return;
                  run(async () => {
                    await createLeadStage(project.id, { name: stageName.trim(), category: stageCat });
                    setStageName("");
                  });
                }}
                className="mt-3 flex gap-2 text-sm"
              >
                <input
                  value={stageName}
                  onChange={(e) => setStageName(e.target.value)}
                  placeholder={t("leads.newStage")}
                  className="flex-1 rounded-lg border border-slate-300 px-3 py-2"
                />
                <select
                  value={stageCat}
                  onChange={(e) => setStageCat(e.target.value as LeadCategory)}
                  className="rounded-lg border border-slate-300 px-3 py-2"
                >
                  {CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
                <button className="rounded-lg border border-slate-300 px-3 py-2">+</button>
              </form>
            )}
            <p className="mt-2 text-xs text-muted">{t("leads.stagesHint")}</p>
          </section>

          <section className="mt-6 rounded-xl border border-slate-200 bg-white p-5">
            <h2 className="text-sm font-semibold">{t("leads.fields")}</h2>
            <table className="mt-3 w-full text-left text-sm">
              <tbody>
                {s.fields.map((f) => (
                  <tr key={f.id} className="border-t border-slate-100">
                    <td className="py-1.5 font-mono text-xs">{f.key}</td>
                    <td>{f.label}</td>
                    <td className="text-muted">
                      {f.type}
                      {f.options && ` (${f.options.join(", ")})`}
                    </td>
                    <td className="text-xs text-muted">
                      {f.required && t("leads.required")} {f.is_pii && t("leads.pii")}
                    </td>
                    <td className="text-right">
                      {canEdit && (
                        <button
                          onClick={() => run(() => deleteLeadField(f.id))}
                          className="text-xs text-red-600 hover:underline"
                        >
                          {t("leads.remove")}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {canEdit && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  run(async () => {
                    await createLeadField(project.id, {
                      key: field.key.trim(),
                      label: field.label.trim(),
                      type: field.type,
                      options:
                        field.type === "select"
                          ? field.options.split(",").map((o) => o.trim()).filter(Boolean)
                          : undefined,
                      required: field.required,
                      is_pii: field.is_pii,
                    });
                    setField({ key: "", label: "", type: "text", options: "", required: false, is_pii: false });
                  });
                }}
                className="mt-3 flex flex-wrap items-center gap-2 text-sm"
              >
                <input
                  value={field.key}
                  onChange={(e) => setField({ ...field, key: e.target.value })}
                  placeholder="key"
                  className="w-32 rounded-lg border border-slate-300 px-3 py-2 font-mono"
                />
                <input
                  value={field.label}
                  onChange={(e) => setField({ ...field, label: e.target.value })}
                  placeholder={t("leads.fieldLabel")}
                  className="flex-1 rounded-lg border border-slate-300 px-3 py-2"
                />
                <select
                  value={field.type}
                  onChange={(e) => setField({ ...field, type: e.target.value as LeadFieldType })}
                  className="rounded-lg border border-slate-300 px-3 py-2"
                >
                  {FIELD_TYPES.map((ft) => (
                    <option key={ft} value={ft}>
                      {ft}
                    </option>
                  ))}
                </select>
                {field.type === "select" && (
                  <input
                    value={field.options}
                    onChange={(e) => setField({ ...field, options: e.target.value })}
                    placeholder={t("leads.fieldOptions")}
                    className="w-48 rounded-lg border border-slate-300 px-3 py-2"
                  />
                )}
                <label className="flex items-center gap-1 text-xs">
                  <input
                    type="checkbox"
                    checked={field.required}
                    onChange={(e) => setField({ ...field, required: e.target.checked })}
                  />
                  {t("leads.required")}
                </label>
                <label className="flex items-center gap-1 text-xs">
                  <input
                    type="checkbox"
                    checked={field.is_pii}
                    onChange={(e) => setField({ ...field, is_pii: e.target.checked })}
                  />
                  {t("leads.pii")}
                </label>
                <button className="rounded-lg border border-slate-300 px-3 py-2">+</button>
              </form>
            )}
          </section>

          {canEdit && (
            <section className="mt-6 rounded-xl border border-slate-200 bg-white p-5">
              <h2 className="text-sm font-semibold">{t("leads.tokens")}</h2>
              <p className="mt-1 text-xs text-muted">{t("leads.tokensHint")}</p>
              {newToken?.token && (
                <div className="mt-3 rounded-lg bg-amber-50 p-3 text-sm">
                  <p className="font-medium text-amber-800">{t("leads.tokenOnce")}</p>
                  <code className="mt-1 block break-all font-mono text-xs">{newToken.token}</code>
                </div>
              )}
              <ul className="mt-3 space-y-1 text-sm">
                {(s.tokens ?? []).map((tk) => (
                  <li key={tk.id} className="flex items-center gap-3">
                    <code className="font-mono text-xs">{tk.prefix}…</code>
                    <span className="flex-1">{tk.label}</span>
                    <span className="text-xs text-muted">
                      {tk.revoked_at
                        ? t("leads.tokenRevoked")
                        : tk.last_used_at
                          ? `${t("leads.tokenUsed")} ${tk.last_used_at.slice(0, 16).replace("T", " ")}`
                          : t("leads.tokenNeverUsed")}
                    </span>
                    {!tk.revoked_at && (
                      <button
                        onClick={() => window.confirm(t("leads.revokeConfirm")) && run(() => revokeLeadToken(tk.id))}
                        className="text-xs text-red-600 hover:underline"
                      >
                        {t("leads.revoke")}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!tokenLabel.trim()) return;
                  run(async () => {
                    setNewToken(await createLeadToken(project.id, tokenLabel.trim()));
                    setTokenLabel("");
                  });
                }}
                className="mt-3 flex gap-2 text-sm"
              >
                <input
                  value={tokenLabel}
                  onChange={(e) => setTokenLabel(e.target.value)}
                  placeholder={t("leads.tokenLabel")}
                  className="flex-1 rounded-lg border border-slate-300 px-3 py-2"
                />
                <button className="rounded-lg border border-slate-300 px-3 py-2">{t("leads.tokenCreate")}</button>
              </form>
            </section>
          )}

          {canEdit && (
            <section className="mt-6 text-sm">
              <button
                onClick={() => window.confirm(t("leads.disableConfirm")) && run(() => disableLeads(project.id))}
                className="text-red-600 hover:underline"
              >
                {t("leads.disable")}
              </button>
            </section>
          )}
        </>
      )}
    </main>
  );
}
