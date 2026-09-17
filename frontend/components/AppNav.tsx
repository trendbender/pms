"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { clearTokens, getMe, getUnreadCount } from "@/lib/api";
import { useT } from "@/lib/locale";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";

type Key = "dashboard" | "myTasks" | "myReviews" | "allTasks" | "projects" | "users";

const LINKS: { key: Key; href: string; label: string }[] = [
  { key: "dashboard", href: "/dashboard", label: "nav.dashboard" },
  { key: "myTasks", href: "/my-tasks", label: "nav.myTasks" },
  { key: "myReviews", href: "/my-reviews", label: "nav.myReviews" },
  { key: "allTasks", href: "/all-tasks", label: "nav.allTasks" },
  { key: "projects", href: "/projects", label: "nav.projects" },
];

export function AppNav({ active }: { active?: Key }) {
  const router = useRouter();
  const t = useT();
  const [unread, setUnread] = useState(0);
  const [q, setQ] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    getUnreadCount()
      .then((r) => setUnread(r.unread))
      .catch(() => {});
    getMe()
      .then((me) => setIsAdmin(me.system_role === "OWNER" || me.system_role === "ADMIN"))
      .catch(() => {});
  }, []);

  const links = isAdmin
    ? [...LINKS, { key: "users" as Key, href: "/users", label: "nav.users" }]
    : LINKS;

  function logout() {
    clearTokens();
    router.replace("/login");
  }

  function onSearch(e: React.FormEvent) {
    e.preventDefault();
    if (q.trim()) router.push(`/search?q=${encodeURIComponent(q.trim())}`);
  }

  return (
    <nav className="flex flex-wrap items-center gap-1 border-b border-slate-200 bg-white px-6 py-2.5">
      <span className="mr-3 flex h-7 w-7 items-center justify-center rounded-md bg-ink text-sm font-bold text-white">
        P
      </span>
      {links.map((l) => (
        <Link
          key={l.key}
          href={l.href}
          className={
            "rounded-lg px-3 py-1.5 text-sm " +
            (active === l.key
              ? "bg-indigo-50 font-medium text-indigo-700"
              : "text-muted hover:bg-slate-100")
          }
        >
          {t(l.label)}
        </Link>
      ))}
      <div className="ml-auto flex items-center gap-2">
        <form onSubmit={onSearch}>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("search.placeholder")}
            className="w-44 rounded-lg border border-slate-300 bg-slate-50 px-3 py-1.5 text-sm outline-none focus:border-slate-400"
          />
        </form>
        <Link
          href="/notifications"
          title={t("notif.title")}
          className="relative rounded-lg p-1.5 text-muted hover:bg-slate-100"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.73 21a2 2 0 0 1-3.46 0" />
          </svg>
          {unread > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </Link>
        <LanguageSwitcher />
        <button
          onClick={logout}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-muted hover:bg-slate-100"
        >
          {t("common.signOut")}
        </button>
      </div>
    </nav>
  );
}
