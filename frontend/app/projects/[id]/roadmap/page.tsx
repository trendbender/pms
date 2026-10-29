"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  Project,
  RoadmapDetail,
  RoadmapTask,
  clearTokens,
  decisionHref,
  getProjectByRef,
  getProjectRoadmap,
} from "@/lib/api";
import { useT } from "@/lib/locale";
import ProjectTabs from "@/components/ProjectTabs";

const STATUS_STYLES: Record<string, string> = {
  DRAFT: "bg-slate-100 text-slate-600",
  AGREED: "bg-sky-100 text-sky-700",
  ACTIVE: "bg-indigo-100 text-indigo-700",
  COMPLETED: "bg-emerald-100 text-emerald-700",
  CANCELLED: "bg-slate-100 text-slate-400",
};

function day(value: string | null) {
  if (!value) return "—";
  const [y, m, d] = value.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

function TaskRow({ task }: { task: RoadmapTask }) {
  const done = task.status_category === "DONE";
  return (
    <tr className="border-t border-slate-100">
      <td className="py-1.5 pr-3 align-top font-mono text-xs">
        <Link href={`/t/${task.key.toLowerCase()}`} className="hover:underline">
          {task.key}
        </Link>
      </td>
      <td className={"py-1.5 pr-3 align-top " + (done ? "text-muted line-through" : "")}>
        {task.title}
        {task.is_blocked && task.blocked_reason && (
          <span className="ml-2 rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-700">
            {task.blocked_reason}
          </span>
        )}
      </td>
      <td className="py-1.5 pr-3 align-top text-xs text-muted">{task.assignee_name ?? "—"}</td>
      <td className="py-1.5 align-top text-xs text-muted">{day(task.due_at)}</td>
    </tr>
  );
}

export default function ProjectRoadmapPage() {
  const router = useRouter();
  const t = useT();
  const { id: ref } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [roadmap, setRoadmap] = useState<RoadmapDetail | null>(null);
  const [empty, setEmpty] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const p = await getProjectByRef(ref);
        setProject(p);
        setRoadmap(await getProjectRoadmap(p.id));
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          clearTokens();
          router.replace("/login");
        } else if (err instanceof ApiError && err.status === 404) {
          // у проекта просто нет роадмапа — это не ошибка
          setEmpty(true);
        } else {
          setError(err instanceof ApiError ? err.message : t("roadmap.loadFailed"));
        }
      }
    })();
  }, [ref, router, t]);

  const share = roadmap
    ? `${roadmap.done_count}/${roadmap.task_count}`
    : "0/0";

  return (
    <main className="mx-auto max-w-5xl p-8">
      <header>
        <Link href="/projects" className="text-sm text-muted hover:underline">
          {t("board.back")}
        </Link>
        <h1 className="mt-1 text-2xl font-semibold">
          {project && <span className="font-mono text-base text-muted">{project.code} </span>}
          {project?.name ?? t("roadmap.title")}
        </h1>
        <ProjectTabs project={project} active="roadmap" refSlug={ref} />
      </header>

      {error && <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {empty && (
        <div className="mt-6 rounded-xl border border-slate-200 bg-white p-5 text-sm text-muted">
          <p>{t("roadmap.none")}</p>
          <code className="mt-2 block text-xs">
            pms.py roadmap add --project {project?.code ?? "CODE"} --title &quot;
            {t("roadmap.monthExample")}&quot; --start 2026-11-01 --end 2026-11-30
          </code>
        </div>
      )}

      {roadmap && (
        <>
          <section className="mt-5 rounded-xl border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-baseline gap-3">
              <h2 className="text-lg font-semibold">{roadmap.title}</h2>
              <span
                className={
                  "rounded-full px-2 py-0.5 text-xs " +
                  (STATUS_STYLES[roadmap.status] ?? STATUS_STYLES.DRAFT)
                }
              >
                {t(`roadmap.status.${roadmap.status}`)}
              </span>
              <span className="text-sm text-muted">
                {day(roadmap.period_start)}
                {roadmap.period_end ? ` — ${day(roadmap.period_end)}` : ""}
              </span>
            </div>
            {roadmap.goal && <p className="mt-2 text-sm">{roadmap.goal}</p>}
            {roadmap.scope_note && (
              <p className="mt-1 text-sm text-muted">
                {roadmap.scope_note}
                {roadmap.decision_ref && (
                  <>
                    {" · "}
                    <Link
                      href={decisionHref(
                        roadmap.decision_ref.includes(":")
                          ? roadmap.decision_ref.replace(":", "-")
                          : `${roadmap.project_code ?? ""}-${roadmap.decision_ref}`
                      )}
                      className="hover:underline"
                    >
                      {roadmap.decision_ref}
                    </Link>
                  </>
                )}
              </p>
            )}
            <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <div>
                <dt className="text-xs text-muted">{t("roadmap.items")}</dt>
                <dd className="text-lg font-semibold">{share}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">{t("roadmap.waves")}</dt>
                <dd className="text-lg font-semibold">{roadmap.wave_count}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">{t("roadmap.metricsReached")}</dt>
                <dd className="text-lg font-semibold">
                  {roadmap.metric_reached_count}/{roadmap.metric_count}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted">{t("roadmap.blockedOverdue")}</dt>
                <dd className="text-lg font-semibold">
                  {roadmap.blocked_count} + {roadmap.overdue_count}
                </dd>
              </div>
            </dl>
            {(roadmap.report_url || roadmap.plan_url) && (
              <p className="mt-3 flex gap-4 text-sm">
                {roadmap.plan_url && (
                  <a href={roadmap.plan_url} className="text-indigo-700 hover:underline">
                    {t("roadmap.plan")} →
                  </a>
                )}
                {roadmap.report_url && (
                  <a href={roadmap.report_url} className="text-indigo-700 hover:underline">
                    {t("roadmap.report")} →
                  </a>
                )}
              </p>
            )}
          </section>

          {roadmap.waves.map((wave) => (
            <section key={wave.id} className="mt-4 rounded-xl border border-slate-200 bg-white p-5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-medium">{wave.name}</h3>
                <span className="text-xs text-muted">
                  {wave.due_date ? `${t("roadmap.by")} ${day(wave.due_date)} · ` : ""}
                  {wave.done_count}/{wave.task_count}
                </span>
              </div>
              {wave.description && <p className="mt-1 text-sm text-muted">{wave.description}</p>}
              {wave.tasks.length > 0 ? (
                <table className="mt-3 w-full text-sm">
                  <tbody>
                    {wave.tasks.map((task) => (
                      <TaskRow key={task.id} task={task} />
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="mt-2 text-sm text-muted">{t("roadmap.waveEmpty")}</p>
              )}
            </section>
          ))}

          {roadmap.metrics.length > 0 && (
            <section className="mt-4 rounded-xl border border-slate-200 bg-white p-5">
              <h3 className="font-medium">{t("roadmap.metrics")}</h3>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-muted">
                      <th className="pb-2 pr-3 font-medium">{t("roadmap.metric")}</th>
                      <th className="pb-2 pr-3 font-medium">{t("roadmap.baseline")}</th>
                      <th className="pb-2 pr-3 font-medium">{t("roadmap.target")}</th>
                      <th className="pb-2 pr-3 font-medium">{t("roadmap.current")}</th>
                      <th className="pb-2 font-medium">{t("roadmap.source")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {roadmap.metrics.map((m) => (
                      <tr key={m.id} className="border-t border-slate-100 align-top">
                        <td className="py-1.5 pr-3">{m.name}</td>
                        <td className="py-1.5 pr-3 text-muted">
                          {m.baseline ?? "—"}
                          {m.baseline_on && (
                            <span className="ml-1 text-xs">{day(m.baseline_on)}</span>
                          )}
                        </td>
                        <td className="py-1.5 pr-3">{m.target ?? "—"}</td>
                        <td className="py-1.5 pr-3">
                          {m.current ?? <span className="text-muted">{t("roadmap.notYet")}</span>}
                          {m.reached_on && (
                            <span className="ml-2 rounded bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-700">
                              {t("roadmap.reached")}
                            </span>
                          )}
                        </td>
                        <td className="py-1.5 text-xs text-muted">
                          {m.source ?? "—"}
                          {m.measured_on ? `, ${day(m.measured_on)}` : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {(roadmap.waiting.length > 0 || roadmap.open_decisions.length > 0) && (
            <section className="mt-4 rounded-xl border border-amber-200 bg-amber-50/50 p-5">
              <h3 className="font-medium">{t("roadmap.waiting")}</h3>
              <ul className="mt-2 space-y-1 text-sm">
                {roadmap.waiting.map((task) => (
                  <li key={task.id}>
                    <Link
                      href={`/t/${task.key.toLowerCase()}`}
                      className="font-mono text-xs hover:underline"
                    >
                      {task.key}
                    </Link>{" "}
                    {task.title} — {task.blocked_reason ?? t("roadmap.noReason")}
                  </li>
                ))}
                {roadmap.open_decisions.map((d) => (
                  <li key={d.ref}>
                    <Link
                      href={decisionHref(`${roadmap.project_code ?? ""}-${d.ref}`)}
                      className="font-mono text-xs hover:underline"
                    >
                      {d.ref}
                    </Link>{" "}
                    {d.question}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <p className="mt-6 text-xs text-muted">
            <Link href="/roadmap" className="hover:underline">
              {t("roadmap.portfolioLink")} →
            </Link>
          </p>
        </>
      )}
    </main>
  );
}
