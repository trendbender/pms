"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, login } from "@/lib/api";
import { useT } from "@/lib/locale";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";

// Login-screen branding. Neutral defaults for the open-source build; set these
// env vars to brand your own instance (e.g. NEXT_PUBLIC_BRAND_NAME="Acme").
const BRAND_NAME = process.env.NEXT_PUBLIC_BRAND_NAME || "PMS";
const BRAND_BADGE = process.env.NEXT_PUBLIC_BRAND_BADGE || "P";
const BRAND_URL = process.env.NEXT_PUBLIC_BRAND_URL || "";

export default function LoginPage() {
  const router = useRouter();
  const t = useT();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email, password);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("login.failed"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-8 shadow-sm"
      >
        <div className="flex items-center justify-between">
          {(() => {
            const inner = (
              <>
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-ink text-sm font-bold text-white">
                  {BRAND_BADGE}
                </span>
                <span className="text-base font-semibold">{BRAND_NAME}</span>
              </>
            );
            return BRAND_URL ? (
              <a href={BRAND_URL} className="flex items-center gap-2" rel="noopener">
                {inner}
              </a>
            ) : (
              <span className="flex items-center gap-2">{inner}</span>
            );
          })()}
          <LanguageSwitcher />
        </div>

        <div className="mt-6">
          <h1 className="text-xl font-semibold">{t("login.title")}</h1>
          <p className="mt-1 text-sm text-muted">{t("login.subtitle")}</p>
        </div>

        <label className="mt-6 block text-sm font-medium">{t("login.email")}</label>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
          placeholder="owner@example.com"
        />

        <label className="mt-4 block text-sm font-medium">{t("login.password")}</label>
        <input
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
        />

        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="mt-6 w-full rounded-lg bg-ink px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {loading ? t("login.submitting") : t("login.submit")}
        </button>

        <p className="mt-6 border-t border-slate-100 pt-4 text-center text-xs text-muted">
          {t("login.note")}
          {BRAND_URL && (
            <>
              <br />
              <a href={BRAND_URL} rel="noopener" className="underline">
                {BRAND_URL.replace(/^https?:\/\//, "")}
              </a>
            </>
          )}
        </p>
      </form>
    </main>
  );
}
