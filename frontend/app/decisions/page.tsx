"use client";

import { useCallback } from "react";
import Link from "next/link";
import { DecisionFilter, listGlobalDecisions } from "@/lib/api";
import { useT } from "@/lib/locale";
import DecisionList from "@/components/DecisionList";

// Кросс-проектные решения владельца (реестр _global). Видят владелец и админы.
export default function GlobalDecisionsPage() {
  const t = useT();
  const load = useCallback((f: DecisionFilter) => listGlobalDecisions(f), []);
  return (
    <main className="mx-auto max-w-7xl p-8">
      <header>
        <Link href="/projects" className="text-sm text-muted hover:underline">
          {t("board.back")}
        </Link>
        <h1 className="mt-1 text-2xl font-semibold">{t("decisions.globalTitle")}</h1>
      </header>
      <DecisionList load={load} />
    </main>
  );
}
