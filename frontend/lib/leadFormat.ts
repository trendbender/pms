// Форматирование для страниц лидов.

export function money(v: string | null | undefined, currency = "RUB") {
  if (v == null || v === "") return "";
  const n = Number(v);
  if (Number.isNaN(n)) return v;
  return `${n.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ${currency === "RUB" ? "₽" : currency}`;
}

export function shortDate(iso: string) {
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export const CATEGORY_STYLES: Record<string, string> = {
  OPEN: "bg-slate-100 text-slate-600",
  WON: "bg-green-100 text-green-700",
  LOST: "bg-red-100 text-red-700",
};
