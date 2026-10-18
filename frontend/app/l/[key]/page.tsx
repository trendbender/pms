"use client";

// Карточка лида по короткой ссылке /l/<KEY> (например /l/kl-l-3).

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  Lead,
  LeadEvent,
  LeadField,
  LeadSettings,
  Project,
  UserRow,
  addLeadComment,
  changeLeadStage,
  clearTokens,
  createLeadTask,
  deleteLead,
  getLeadByKey,
  getLeadEvents,
  getLeadSettings,
  getProject,
  listUsers,
  projectSlug,
  updateLead,
} from "@/lib/api";
import { useT } from "@/lib/locale";
import { CATEGORY_STYLES, money, shortDate } from "@/lib/leadFormat";

interface Form {
  title: string;
  contact_name: string;
  phone: string;
  email: string;
  amount: string;
  source_url: string;
  data: Record<string, string>;
}

function toForm(l: Lead, fields: LeadField[]): Form {
  const data: Record<string, string> = {};
  for (const f of fields) {
    const v = l.data?.[f.key];
    data[f.key] = v == null ? "" : String(v);
  }
  return {
    title: l.title,
    contact_name: l.contact_name ?? "",
    phone: l.phone ?? "",
    email: l.email ?? "",
    amount: l.amount ?? "",
    source_url: l.source_url ?? "",
    data,
  };
}

const INPUT_TYPES: Record<string, string> = {
  number: "number",
  money: "number",
  date: "date",
  datetime: "datetime-local",
  email: "email",
  url: "url",
  phone: "tel",
};

function eventText(e: LeadEvent, users: Record<string, string>) {
  const d = (e.data ?? {}) as Record<string, unknown>;
  const who = e.actor_id ? users[e.actor_id] ?? "—" : e.token_id ? "API" : "—";
  switch (e.action) {
    case "comment":
      return { who, text: String(d.text ?? "") };
    case "stage.changed":
      return {
        who,
        text: `${d.from ?? "—"} → ${d.to}${d.lost_reason ? ` (${d.lost_reason})` : ""}`,
      };
    case "lead.created":
      return { who, text: `создан, этап «${d.stage}»${d.via ? `, ключ «${d.via}»` : ""}` };
    case "lead.updated":
      return { who, text: `изменено: ${(d.fields as string[] | undefined)?.join(", ") ?? ""}` };
    case "ingest.repeat":
      return { who, text: d.updated ? "повторный приём, поля обновлены" : "повторный приём" };
    case "task.linked":
      return { who, text: `задача ${d.task_key}` };
    default:
      return { who, text: e.action };
  }
}

export default function LeadPage() {
  const router = useRouter();
  const t = useT();
  const { key } = useParams<{ key: string }>();
  const [lead, setLead] = useState<Lead | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [settings, setSettings] = useState<LeadSettings | null>(null);
  const [events, setEvents] = useState<LeadEvent[]>([]);
  const [users, setUsers] = useState<Record<string, string>>({});
  const [form, setForm] = useState<Form | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    try {
      const l = await getLeadByKey(key);
      const [p, s, ev] = await Promise.all([
        getProject(l.project_id),
        getLeadSettings(l.project_id),
        getLeadEvents(l.id),
      ]);
      setLead(l);
      setProject(p);
      setSettings(s);
      setEvents(ev);
      setForm(toForm(l, s.fields));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearTokens();
        router.replace("/login");
      } else {
        setError(err instanceof ApiError && err.status === 404 ? t("leads.notFound") : String(err));
      }
    }
  }, [key, router, t]);

  useEffect(() => {
    load();
    listUsers()
      .then((us: UserRow[]) => setUsers(Object.fromEntries(us.map((u) => [u.id, u.name]))))
      .catch(() => {});
  }, [load]);

  if (error && !lead) {
    return (
      <main className="mx-auto max-w-4xl p-8">
        <p className="text-sm text-red-600">{error}</p>
      </main>
    );
  }
  if (!lead || !form || !settings) {
    return <main className="mx-auto max-w-4xl p-8 text-sm text-muted">{t("common.loading")}</main>;
  }

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    if (!lead || !form || !settings) return;
    setError(null);
    setSaved(false);
    const data: Record<string, unknown> = {};
    for (const f of settings.fields) {
      const v = form.data[f.key] ?? "";
      const old = lead.data?.[f.key];
      if (v !== (old == null ? "" : String(old))) data[f.key] = v === "" ? null : v;
    }
    const nul = (s: string) => (s.trim() === "" ? null : s.trim());
    try {
      const updated = await updateLead(lead.id, {
        title: form.title.trim() || lead.title,
        contact_name: nul(form.contact_name),
        phone: nul(form.phone),
        email: nul(form.email),
        amount: nul(form.amount),
        source_url: nul(form.source_url),
        ...(Object.keys(data).length ? { data } : {}),
      });
      setLead(updated);
      setForm(toForm(updated, settings.fields));
      setEvents(await getLeadEvents(lead.id));
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("leads.saveFailed"));
    }
  }

  async function onStage(stageId: string) {
    if (!lead || !settings) return;
    const stage = settings.stages.find((s) => s.id === stageId);
    let reason: string | undefined;
    if (stage?.category === "LOST") {
      reason = window.prompt(t("leads.lostReasonPrompt"))?.trim();
      if (!reason) return;
    }
    try {
      setLead(await changeLeadStage(lead.id, stageId, reason));
      setEvents(await getLeadEvents(lead.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("leads.moveFailed"));
    }
  }

  async function onComment(e: React.FormEvent) {
    e.preventDefault();
    if (!lead || !comment.trim()) return;
    try {
      await addLeadComment(lead.id, comment.trim());
      setComment("");
      setEvents(await getLeadEvents(lead.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("leads.saveFailed"));
    }
  }

  async function onTask() {
    if (!lead) return;
    try {
      setLead(await createLeadTask(lead.id));
      setEvents(await getLeadEvents(lead.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("leads.saveFailed"));
    }
  }

  async function onDelete() {
    if (!lead || !window.confirm(t("leads.deleteConfirm"))) return;
    try {
      await deleteLead(lead.id);
      router.push(project ? `/projects/${projectSlug(project.code)}/leads` : "/projects");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("leads.saveFailed"));
    }
  }

  const set = (k: keyof Omit<Form, "data">) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value });
  const extra = (lead.data?._extra ?? null) as Record<string, unknown> | null;
  const slug = project ? projectSlug(project.code) : "";

  return (
    <main className="mx-auto max-w-4xl p-8">
      <Link href={`/projects/${slug}/leads`} className="text-sm text-muted hover:underline">
        ← {project?.code} · {t("leads.tab")}
      </Link>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <span className="font-mono text-sm text-muted">{lead.key}</span>
        <select
          value={lead.stage_id}
          onChange={(e) => onStage(e.target.value)}
          className={`rounded px-2 py-1 text-sm ${CATEGORY_STYLES[lead.stage_category]}`}
        >
          {settings.stages.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <span className="text-xs text-muted">
          {lead.source}
          {lead.external_id && ` #${lead.external_id}`} · {shortDate(lead.received_at)}
        </span>
        {lead.amount && <span className="text-sm font-medium">{money(lead.amount, lead.currency)}</span>}
      </div>
      {lead.lost_reason && lead.stage_category === "LOST" && (
        <p className="mt-2 text-sm text-red-700">
          {t("leads.lostReason")}: {lead.lost_reason}
        </p>
      )}

      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

      <form onSubmit={onSave} className="mt-4 rounded-xl border border-slate-200 bg-white p-5">
        <input
          value={form.title}
          onChange={set("title")}
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-lg font-semibold"
        />
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {(
            [
              ["contact_name", t("leads.contact"), "text"],
              ["phone", t("leads.phone"), "tel"],
              ["email", "Email", "email"],
              ["amount", t("leads.amount"), "number"],
              ["source_url", t("leads.sourceUrl"), "url"],
            ] as const
          ).map(([k, label, type]) => (
            <label key={k} className="block text-sm">
              <span className="text-xs text-muted">{label}</span>
              <input
                type={type}
                value={form[k]}
                onChange={set(k)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              />
            </label>
          ))}
        </div>

        {settings.fields.length > 0 && (
          <div className="mt-5 grid gap-3 border-t border-slate-100 pt-4 sm:grid-cols-2">
            {settings.fields.map((f) => (
              <label key={f.id} className="block text-sm">
                <span className="text-xs text-muted">
                  {f.label}
                  {f.required && " *"}
                </span>
                {f.type === "select" ? (
                  <select
                    value={form.data[f.key] ?? ""}
                    onChange={(e) => setForm({ ...form, data: { ...form.data, [f.key]: e.target.value } })}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  >
                    <option value="">—</option>
                    {(f.options ?? []).map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={INPUT_TYPES[f.type] ?? "text"}
                    value={
                      f.type === "datetime"
                        ? (form.data[f.key] ?? "").slice(0, 16)
                        : form.data[f.key] ?? ""
                    }
                    onChange={(e) => setForm({ ...form, data: { ...form.data, [f.key]: e.target.value } })}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  />
                )}
              </label>
            ))}
          </div>
        )}

        {extra && Object.keys(extra).length > 0 && (
          <div className="mt-4 rounded-lg bg-amber-50 p-3 text-xs">
            <p className="font-medium text-amber-800">{t("leads.extra")}</p>
            {Object.entries(extra).map(([k, v]) => (
              <p key={k} className="mt-1 font-mono text-amber-900">
                {k}: {typeof v === "string" ? v : JSON.stringify(v)}
              </p>
            ))}
          </div>
        )}

        <div className="mt-4 flex items-center gap-3">
          <button type="submit" className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white">
            {t("leads.save")}
          </button>
          {saved && <span className="text-xs text-green-700">{t("leads.saved")}</span>}
          <span className="flex-1" />
          {lead.task_key ? (
            <Link href={`/t/${lead.task_key.toLowerCase()}`} className="text-sm underline">
              {t("leads.task")}: {lead.task_key}
            </Link>
          ) : (
            <button type="button" onClick={onTask} className="text-sm text-muted hover:text-ink">
              + {t("leads.createTask")}
            </button>
          )}
          <button type="button" onClick={onDelete} className="text-sm text-red-600 hover:underline">
            {t("leads.delete")}
          </button>
        </div>
      </form>

      <section className="mt-6">
        <h2 className="text-sm font-semibold">{t("leads.journal")}</h2>
        <form onSubmit={onComment} className="mt-2 flex gap-2">
          <input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder={t("leads.commentPlaceholder")}
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          <button type="submit" className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
            {t("leads.comment")}
          </button>
        </form>
        <ul className="mt-3 space-y-2">
          {[...events].reverse().map((e) => {
            const { who, text } = eventText(e, users);
            return (
              <li key={e.id} className="text-sm">
                <span className="text-xs text-muted">
                  {shortDate(e.created_at)} · {who}
                </span>
                <p className={e.action === "comment" ? "whitespace-pre-wrap" : "text-muted"}>{text}</p>
              </li>
            );
          })}
        </ul>
      </section>
    </main>
  );
}
