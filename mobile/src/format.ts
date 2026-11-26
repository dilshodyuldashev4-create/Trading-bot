// Форматы чисел и дат — как в Mini App
const sp = (s: string) => s.replace(/,/g, " ");

export function money(x: number | null | undefined, d = 0): string {
  if (x == null || isNaN(x)) return "—";
  const s = sp(Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
  return (x < 0 ? "−$" : "$") + s;
}

export function usd2(x: number | null | undefined): string {
  if (x == null) return "—";
  const r = Math.round(x * 100) / 100;
  return money(r, Number.isInteger(r) ? 0 : 2);
}

export function pips(x: number | null | undefined): string {
  if (x == null || isNaN(x)) return "—";
  const r = Math.round(x);
  return (r > 0 ? "+" : r < 0 ? "−" : "") + sp(Math.abs(r).toLocaleString("en-US"));
}

export function pct(x: number, digits = 2): string {
  return `${x >= 0 ? "+" : ""}${x.toFixed(digits)}%`;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** Дата в часовом поясе бота (tz из сервера), формат 26.11 14:05 */
export function fmtDate(iso: string | null | undefined, tz?: string, time = true): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  try {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: tz || undefined, day: "2-digit", month: "2-digit", year: time ? undefined : "numeric",
      hour: time ? "2-digit" : undefined, minute: time ? "2-digit" : undefined, hour12: false,
    }).formatToParts(d);
    const g = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
    return time ? `${g("day")}.${g("month")} ${g("hour")}:${g("minute")}` : `${g("day")}.${g("month")}.${g("year")}`;
  } catch {
    return time ? `${pad(d.getDate())}.${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`
      : `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}`;
  }
}

/** Только время ЧЧ:ММ в часовом поясе */
export function fmtTime(iso: string, tz?: string): string {
  try {
    return new Intl.DateTimeFormat("en-GB", { timeZone: tz || undefined, hour: "2-digit", minute: "2-digit", hour12: false })
      .format(new Date(iso));
  } catch {
    const d = new Date(iso);
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
}

/** Ключ дня (ГГГГ-ММ-ДД) в часовом поясе — для группировки календаря */
export function dayKey(iso: string, tz?: string): string {
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone: tz || undefined, year: "numeric", month: "2-digit", day: "2-digit" })
      .format(new Date(iso));
  } catch {
    return iso.slice(0, 10);
  }
}

export function parseNum(s: string): number | null {
  const v = parseFloat(String(s).replace(/[\s$]/g, "").replace(",", "."));
  return isFinite(v) ? v : null;
}
