"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  DecisionDetail,
  clearTokens,
  decisionHref,
  getDecisionByRef,
  projectSlug,
} from "@/lib/api";
import { useT } from "@/lib/locale";
import { DecisionStatus } from "@/components/DecisionList";
import { splitDecisionRefs } from "@/lib/decisionRefs";

const CAT_DOT: Record<string, string> = {
  BACKLOG: "#94a3b8",
  READY: "#0ea5e9",
  IN_PROGRESS: "#6366f1",
  BLOCKED: "#ef4444",
  REVIEW: "#a855f7",
  CHANGES_REQUIRED: "#f97316",
  DONE: "#22c55e",
};

// Источник: ссылки и номера решений кликабельны.
function RichText({ text, projectCode }: { text: string; projectCode?: string }) {
  return (
    <>
      {text.split(/(https?:\/\/[^\s;,)]+)/g).map((part, i) =>
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
          <span key={i}>
            {splitDecisionRefs(part, projectCode).map((r, j) =>
              r.href ? (
                <Link key={j} href={r.href} className="text-indigo-600 underline">
                  {r.text}
                </Link>
              ) : (
                <span key={j}>{r.text}</span>
              )
            )}
          </span>
        )
      )}
    </>
  );
}

// Короткая ссылка на решение: /d/<префикс>-<номер>, напр. /d/ssk-p-030, /d/g-p-022.
export default function DecisionPage() {
  const router = useRouter();
  const t = useT();
  const { ref } = useParams<{ ref: string }>();
  const [d, setD] = useState<DecisionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDecisionByRef(ref)
      .then(setD)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearTokens();
          router.replace("/login");
        } else {
          setError(t("decisions.notFound"));
        }
      });
  }, [ref, router, t]);

  if (error) return <main className="mx-auto max-w-3xl p-8 text-sm text-muted">{error}</main>;
  if (!d) return <main className="mx-auto max-w-3xl p-8 text-sm text-muted">{t("common.loading")}</main>;

  const prefix = d.project_code ?? "G";
  const code = d.project_code ?? undefined;
  const sibling = (r: string) => decisionHref(`${prefix}-${r}`);
  const back = d.project_code ? `/projects/${projectSlug(d.project_code)}/decisions` : "/decisions";

  return (
    <main className="mx-auto max-w-3xl p-8">
      <Link href={back} className="text-sm text-muted hover:underline">
        ← {d.project_code ? `${d.project_code} · ${t("decisions.title")}` : t("decisions.globalTitle")}
      </Link>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        <span className="font-mono font-semibold">{d.full_ref}</span>
        <DecisionStatus status={d.status} />
        {d.area_title && <span className="text-muted">{d.area_title}</span>}
      </div>
      <h1 className="mt-2 text-xl font-semibold leading-snug">{d.question}</h1>

      {d.superseded_by && (
        <p className="mt-3 rounded-lg bg-slate-100 px-3 py-2 text-sm">
          {t("decisions.supersededBy")}{" "}
          <Link href={sibling(d.superseded_by)} className="font-mono text-indigo-600 underline">
            {d.superseded_by}
          </Link>
        </p>
      )}

      {d.decision && (
        <section className="mt-4 whitespace-pre-wrap rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm leading-relaxed">
          <RichText text={d.decision} projectCode={code} />
        </section>
      )}

      <dl className="mt-5 grid grid-cols-[10rem_1fr] gap-x-4 gap-y-2 text-sm">
        {d.decided_by && (
          <>
            <dt className="text-muted">{t("decisions.by")}</dt>
            <dd>{d.decided_by}</dd>
          </>
        )}
        {d.decided_on && (
          <>
            <dt className="text-muted">{t("decisions.date")}</dt>
            <dd>{d.decided_on}</dd>
          </>
        )}
        {d.applies && (
          <>
            <dt className="text-muted">{t("decisions.applies")}</dt>
            <dd>
              <RichText text={d.applies} projectCode={code} />
            </dd>
          </>
        )}
        {d.source && (
          <>
            <dt className="text-muted">{t("decisions.source")}</dt>
            <dd className="break-words">
              <RichText text={d.source} projectCode={code} />
            </dd>
          </>
        )}
        {d.supersedes && (
          <>
            <dt className="text-muted">{t("decisions.supersedes")}</dt>
            <dd>
              <Link href={sibling(d.supersedes)} className="font-mono text-indigo-600 underline">
                {d.supersedes}
              </Link>
            </dd>
          </>
        )}
        {d.keys.length + d.aliases.length > 0 && (
          <>
            <dt className="text-muted">{t("decisions.keys")}</dt>
            <dd className="flex flex-wrap gap-1">
              {[...d.keys, ...d.aliases].map((k) => (
                <span key={k} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                  {k}
                </span>
              ))}
            </dd>
          </>
        )}
      </dl>

      {d.tasks.length > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-semibold">{t("decisions.tasks")}</h2>
          <ul className="mt-2 flex flex-col gap-1.5 text-sm">
            {d.tasks.map((task) => (
              <li key={task.key} className="flex items-center gap-2">
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ background: CAT_DOT[task.status_category] ?? "#94a3b8" }}
                  title={task.status_name}
                />
                <Link href={`/t/${task.key.toLowerCase()}`} className="font-mono text-indigo-600 hover:underline">
                  {task.key}
                </Link>
                <span className="text-slate-700">{task.title}</span>
                <span className="ml-auto text-xs text-muted">{task.status_name}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="mt-8 text-xs text-muted">
        {t("decisions.sourceOfTruth")} {new Date(d.synced_at).toLocaleString()}.
      </p>
    </main>
  );
}
