"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  DEFAULT_LOCALE,
  Locale,
  isLocale,
  translate,
} from "@/lib/i18n";
import { getAccessToken, getMe, updateMe } from "@/lib/api";

const STORAGE_KEY = "pms_locale";

interface LocaleCtx {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
}

const Ctx = createContext<LocaleCtx | null>(null);

function readStored(): Locale {
  if (typeof window === "undefined") return DEFAULT_LOCALE;
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (isLocale(v)) return v;
  } catch {
    /* private mode / disabled storage */
  }
  return DEFAULT_LOCALE;
}

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  // Paint immediately from the per-device preference, then reconcile with the
  // signed-in user's saved setting (the source of truth).
  const [locale, setLocaleState] = useState<Locale>(DEFAULT_LOCALE);

  useEffect(() => {
    setLocaleState(readStored());
  }, []);

  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.lang = locale;
    }
  }, [locale]);

  // On mount, if signed in, adopt the profile language.
  useEffect(() => {
    if (!getAccessToken()) return;
    let cancelled = false;
    (async () => {
      try {
        const me = await getMe();
        if (!cancelled && isLocale(me.language)) {
          setLocaleState(me.language);
          try {
            localStorage.setItem(STORAGE_KEY, me.language);
          } catch {
            /* ignore */
          }
        }
      } catch {
        /* not signed in / network — keep local preference */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* ignore */
    }
    // Persist to the profile when signed in (fire-and-forget).
    if (getAccessToken()) {
      updateMe({ language: l }).catch(() => {
        /* keep the local switch even if the server write fails */
      });
    }
  }, []);

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>) =>
      translate(locale, key, vars),
    [locale]
  );

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLocale(): LocaleCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useLocale must be used within LocaleProvider");
  return ctx;
}

export function useT() {
  return useLocale().t;
}
