"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  DecisionFilter,
  Project,
  clearTokens,
  getProjectByRef,
  listProjectDecisions,
} from "@/lib/api";
import { useT } from "@/lib/locale";
import ProjectTabs from "@/components/ProjectTabs";
import DecisionList from "@/components/DecisionList";

export default function ProjectDecisionsPage() {
  const router = useRouter();
  const t = useT();
  const { id: ref } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getProjectByRef(ref)
      .then(setProject)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearTokens();
          router.replace("/login");
        } else {
          setError(err instanceof ApiError ? err.message : t("decisions.loadFailed"));
        }
      });
  }, [ref, router, t]);

  const load = useCallback(
    (f: DecisionFilter) => (project ? listProjectDecisions(project.id, f) : Promise.resolve([])),
    [project]
  );

  return (
    <main className="mx-auto max-w-7xl p-8">
      <header>
        <Link href="/projects" className="text-sm text-muted hover:underline">
          {t("board.back")}
        </Link>
        <h1 className="mt-1 text-2xl font-semibold">
          {project && <span className="font-mono text-base text-muted">{project.code} </span>}
          {project?.name ?? t("decisions.title")}
        </h1>
        <ProjectTabs project={project} active="decisions" refSlug={ref} />
      </header>
      {error && <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {project && <DecisionList key={project.id} load={load} />}
      <p className="mt-6 text-xs text-muted">
        <Link href="/decisions" className="hover:underline">
          {t("decisions.globalLink")} →
        </Link>
      </p>
    </main>
  );
}
