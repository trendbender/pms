"use client";

import { LOCALES } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";

/** Compact RU | EN segmented switch. Persists to the user's profile when signed in. */
export function LanguageSwitcher() {
  const { locale, setLocale } = useLocale();
  return (
    <div className="inline-flex items-center rounded-lg border border-slate-300 bg-white p-0.5">
      {LOCALES.map((l) => (
        <button
          key={l.code}
          type="button"
          onClick={() => setLocale(l.code)}
          aria-pressed={locale === l.code}
          title={l.label}
          className={
            "rounded-md px-2 py-1 text-xs font-semibold transition-colors " +
            (locale === l.code
              ? "bg-ink text-white"
              : "text-muted hover:bg-slate-100")
          }
        >
          {l.short}
        </button>
      ))}
    </div>
  );
}
