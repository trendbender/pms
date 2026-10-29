"use client";

import Link from "next/link";
import { Project } from "@/lib/api";
import { useT } from "@/lib/locale";

// Вкладки проекта для страниц модулей «Лиды», «Роадмап» и «Решения». Вкладка
// «Лиды» видна только у проектов, где модуль включён.
export default function ProjectTabs({
  project,
  active,
  refSlug,
}: {
  project: Project | null;
  active: "board" | "leads" | "roadmap" | "decisions" | "sprints" | "settings";
  refSlug: string;
}) {
  const t = useT();
  const tabs: { id: typeof active; href: string; label: string; show: boolean }[] = [
    { id: "board", href: `/projects/${refSlug}`, label: t("board.board"), show: true },
    {
      id: "leads",
      href: `/projects/${refSlug}/leads`,
      label: t("leads.tab"),
      show: !!project?.leads_enabled,
    },
    { id: "roadmap", href: `/projects/${refSlug}/roadmap`, label: t("roadmap.tab"), show: true },
    { id: "decisions", href: `/projects/${refSlug}/decisions`, label: t("decisions.tab"), show: true },
    { id: "sprints", href: `/projects/${refSlug}/sprints`, label: t("board.sprints"), show: true },
    { id: "settings", href: `/projects/${refSlug}/settings`, label: t("board.settings"), show: true },
  ];
  return (
    <nav className="mt-3 flex gap-4 border-b border-slate-200 text-sm">
      {tabs
        .filter((tab) => tab.show)
        .map((tab) =>
          tab.id === active ? (
            <span key={tab.id} className="border-b-2 border-ink pb-2 font-medium">
              {tab.label}
            </span>
          ) : (
            <Link key={tab.id} href={tab.href} className="pb-2 text-muted hover:text-ink">
              {tab.label}
            </Link>
          )
        )}
    </nav>
  );
}
