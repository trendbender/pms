"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  Notification,
  clearTokens,
  getNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/lib/api";
import { useT } from "@/lib/locale";

export default function NotificationsPage() {
  const router = useRouter();
  const t = useT();
  const [items, setItems] = useState<Notification[] | null>(null);

  async function load() {
    try {
      setItems(await getNotifications());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        clearTokens();
        router.replace("/login");
      }
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function readOne(n: Notification) {
    if (n.read_at) return;
    await markNotificationRead(n.id).catch(() => {});
    await load();
  }

  async function readAll() {
    await markAllNotificationsRead().catch(() => {});
    await load();
  }

  return (
    <>
      <main className="mx-auto max-w-2xl p-8">
        <header className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">{t("notif.title")}</h1>
          <button
            onClick={readAll}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-muted hover:bg-slate-100"
          >
            {t("notif.markAll")}
          </button>
        </header>

        {!items ? (
          <p className="mt-8 text-sm text-muted">{t("common.loading")}</p>
        ) : items.length === 0 ? (
          <p className="mt-8 rounded-xl border border-dashed border-slate-200 p-8 text-center text-sm text-muted">
            {t("notif.empty")}
          </p>
        ) : (
          <div className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white">
            {items.map((n) => (
              <button
                key={n.id}
                onClick={() => readOne(n)}
                className={`flex w-full items-start gap-3 border-t border-slate-100 px-4 py-3 text-left first:border-t-0 hover:bg-slate-50 ${
                  n.read_at ? "opacity-60" : ""
                }`}
              >
                {!n.read_at && (
                  <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-indigo-500" />
                )}
                <div className={n.read_at ? "pl-5" : ""}>
                  <div className="text-xs font-medium text-indigo-700">
                    {t(`notif.kind.${n.kind}`)}
                  </div>
                  <div className="text-sm">{n.title}</div>
                  {n.body && <div className="mt-0.5 text-xs text-muted">{n.body}</div>}
                </div>
              </button>
            ))}
          </div>
        )}
      </main>
    </>
  );
}
