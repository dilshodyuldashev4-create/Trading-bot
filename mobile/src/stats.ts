import type { Trade } from "./types";

export type Point = { v: number; ts: string; p: number };

export type Calc = {
  n: number; open: number; w: number; l: number; wr: number | null; total: number; pf: number | null;
  best: number | null; worst: number | null; avg: number | null; dd: number; streak: number; pts: Point[];
};

export function periodTrades(trades: Trade[], days: number, nowMs = Date.now()): Trade[] {
  const from = days ? nowMs - days * 864e5 : 0;
  return trades.filter((x) => new Date(x.ts).getTime() >= from);
}

/** Итоги сделок — та же формула, что в Mini App */
export function calc(list: Trade[], win: string[]): Calc {
  const closed = list.filter((x) => x.status !== "open");
  const w = closed.filter((x) => win.includes(x.status));
  const l = closed.filter((x) => x.status === "sl");
  const vals = closed.filter((x) => x.pips != null) as (Trade & { pips: number })[];
  const total = vals.reduce((a, x) => a + x.pips, 0);
  const gp = vals.filter((x) => x.pips > 0).reduce((a, x) => a + x.pips, 0);
  const gl = -vals.filter((x) => x.pips < 0).reduce((a, x) => a + x.pips, 0);
  const asc = [...vals].sort((a, b) => +new Date(a.closed || a.ts) - +new Date(b.closed || b.ts));
  let cum = 0, peak = 0, dd = 0, run = 0, streak = 0;
  const pts: Point[] = [];
  for (const x of asc) {
    cum += x.pips;
    peak = Math.max(peak, cum);
    dd = Math.max(dd, peak - cum);
    pts.push({ v: cum, ts: x.closed || x.ts, p: x.pips });
    if (win.includes(x.status)) {
      run++;
      streak = Math.max(streak, run);
    } else if (x.status === "sl") run = 0;
  }
  return {
    n: list.length, open: list.length - closed.length, w: w.length, l: l.length,
    wr: w.length + l.length ? (100 * w.length) / (w.length + l.length) : null,
    total, pf: gl > 0 ? gp / gl : gp > 0 ? Infinity : null,
    best: vals.length ? Math.max(...vals.map((x) => x.pips)) : null,
    worst: vals.length ? Math.min(...vals.map((x) => x.pips)) : null,
    avg: vals.length ? total / vals.length : null, dd, streak, pts,
  };
}

export type StratRow = { key: string; n: number; w: number; l: number; p: number };

export function byStrategy(list: Trade[], win: string[]): StratRow[] {
  const by: Record<string, StratRow> = {};
  for (const x of list) {
    if (x.status === "open" || x.pips == null) continue;
    const k = x.strategy || "—";
    by[k] ??= { key: k, n: 0, w: 0, l: 0, p: 0 };
    by[k].n++;
    by[k].p += x.pips;
    if (win.includes(x.status)) by[k].w++;
    else if (x.status === "sl") by[k].l++;
  }
  return Object.values(by).sort((a, b) => b.p - a.p);
}

export type Filter = "all" | "win" | "loss" | "open";

export function filterTrades(list: Trade[], f: Filter, win: string[]): Trade[] {
  return list.filter((x) =>
    f === "all" ? true
      : f === "open" ? x.status === "open"
        : f === "win" ? win.includes(x.status)
          : x.status !== "open" && !win.includes(x.status) && (x.pips ?? 0) <= 0);
}

/** Лот по калькулятору урока (как в Mini App): риск % капитала на стоп в пипсах, шаг 0.01 */
export function calcLot(cap: number, risk: number, stop: number) {
  if (!(cap > 0) || !(stop > 0)) return null;
  const raw = (cap * risk) / 100 / (stop * 0.1);
  const units = Math.max(1, Math.min(10000, Math.floor(raw + 1e-9)));
  const loss = units * stop * 0.1;
  return { lot: units / 100, loss, real: (loss / cap) * 100, tooSmall: raw < 1 };
}

/** Порядок ответов квиза — тот же, что в Mini App (детерминированный по id урока) */
export function shuffled(id: string, n: number): number[] {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  const idx = [...Array(n).keys()];
  for (let i = n - 1; i > 0; i--) {
    h = (h * 1103515245 + 12345) >>> 0;
    const j = h % (i + 1);
    [idx[i], idx[j]] = [idx[j], idx[i]];
  }
  return idx;
}
