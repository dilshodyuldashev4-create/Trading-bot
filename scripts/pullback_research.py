"""Откат после входа: вход на откате, поздний безубыток, пауза после стопа. База — бот с 10 стратегиями
(после PR 67: + Klinger H4), сопровождение как в боте: 50 % на +1R, остаток в безубыток, тейк 3R,
закрытие по встречному сигналу. Проверка как в profit5_research.py: обе половины истории, стресс издержек
+0.30 $, зеркальный график.

    python scripts/pullback_research.py   # таблица в reports/pullback_research.md (таблица)
"""
from __future__ import annotations

import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
warnings.filterwarnings("ignore")

import challenge_research as C  # noqa: E402
import day_guard_research as G  # noqa: E402
import indicator_research as R  # noqa: E402
import profit_research as P  # noqa: E402
import profit2_research as Q  # noqa: E402
import profit3_research as P3  # noqa: E402
from goldbot.data import PIP, load_mt5_csv, resample  # noqa: E402
from goldbot.strategies.popular import kama_h4, klinger_h4  # noqa: E402

SLIP = R.SLIP


@dataclass(frozen=True)
class Opt:
    mode: str = "market"     # market / atr (лимит на k ATR лучше) / candle (откат k доли сигнальной свечи)
    k: float = 0.0
    w: int = 0               # сколько свечей M15 ждать исполнения лимита
    fallback: bool = False   # не исполнился — войти по рынку в конце ожидания
    keep_stop: bool = False  # стоп на прежнем уровне (ближе к входу), иначе — прежнее расстояние от входа
    part_r: float = 1.0      # 50 % и безубыток, когда цена прошла столько R (0 — без фиксации и безубытка)
    be: bool = True          # после фиксации стоп в безубыток (False — стоп остаётся)
    be_lock: float = 0.0     # после фиксации стоп на −be_lock R вместо безубытка (если be=False и be_lock>0)
    cd: int = 0              # после стопа этой стратегии столько свечей M15 без её сигналов


def simulate(D, ctx, op: Opt = Opt()):
    o, h, l, c, spr = D["o"], D["h"], D["l"], ctx["c"], D["spr"]
    sl_p, a, opp = D["sl"], ctx["atr"], ctx["opp"]
    n = len(o)
    out = []
    for key in P.KEYS:
        s = D["sig"][key]
        i = 0
        while i < n - 2:
            d = int(s[i])
            if d == 0:
                i += 1
                continue
            dist = sl_p[i] * PIP
            mkt = o[i + 1] + (spr[i + 1] if d == 1 else 0.0)
            ent, e = i + 1, mkt
            if op.mode != "market":
                if op.mode == "atr":
                    px = mkt - d * op.k * a[i]
                else:
                    rng = h[i] - l[i]
                    px = (h[i] - op.k * rng + spr[i + 1]) if d == 1 else (l[i] + op.k * rng)
                    if (px - mkt) * d > 0:
                        px = mkt
                filled = None
                for q in range(i + 1, min(n, i + 1 + op.w)):
                    reach = l[q] + spr[q] if d == 1 else h[q]
                    if (reach - px) * d <= 0:
                        filled = q
                        break
                if filled is None:
                    if not op.fallback:
                        i += 1 + op.w
                        continue
                    q = min(n - 1, i + 1 + op.w)
                    ent, e = q, o[q] + (spr[q] if d == 1 else 0.0)
                else:
                    ent, e = filled, px
            stop = mkt - d * dist if op.keep_stop else e - d * dist
            rd = abs(e - stop)
            if rd < 0.3 * dist:                    # лимит почти у стопа — сделку не берём
                i = ent + 1
                continue
            tp = e + d * 3.0 * rd
            part_px = e + d * op.part_r * rd
            rest, res, part_done = 1.0, 0.0, False
            new_stop = None
            j = ent
            # в свече исполнения лимита цена уже была у лимита: стоп проверяем с этой же свечи
            while j < n:
                if new_stop is not None:
                    stop, new_stop = new_stop, None
                bad = l[j] if d == 1 else h[j] + spr[j]
                good = h[j] if d == 1 else l[j] + spr[j]
                if (bad - stop) * d <= 0:
                    res += rest * (stop - e) * d / rd
                    break
                if op.part_r and not part_done and (good - part_px) * d >= 0:
                    res += 0.5 * (part_px - e) * d / rd
                    rest -= 0.5
                    part_done = True
                    if op.be:
                        new_stop = e + d * spr[j]
                    elif op.be_lock:
                        new_stop = e - d * op.be_lock * rd
                if (good - tp) * d >= 0:
                    res += rest * (tp - e) * d / rd
                    break
                cl = c[j] + (spr[j] if d == -1 else 0.0)
                if part_done and (cl - e) * d > 0 and opp[j] == -d:
                    res += rest * (cl - e) * d / rd
                    break
                j += 1
            else:
                break
            # r в риске сделки; R.run считает проскальзывание через D["sl"][sig] — оставляем как есть
            out.append(dict(key=key, i=ent, j=j, d=d, r=res, sig=i))
            i = j + 1 + (op.cd if res <= -0.9 else 0)
    return out


def portfolio_cd(cd_bars: int):
    """G.portfolio + после стопа любой стратегии cd_bars свечей без новых сделок в ту же сторону."""
    orig = G.portfolio

    def f(trades, idx, g, sizes):
        ends = sorted((x["j"], x["d"]) for x in trades)
        taken, bal = orig(trades, idx, g, sizes)
        # повторный проход: выкидываем сделки, открытые вскоре после стопа (по взятым сделкам), и пересчитываем
        for _ in range(3):
            sl = sorted((t["j"], t["d"]) for t in taken if t["r"] <= -0.9)
            js = np.array([e[0] for e in sl])
            ds = np.array([e[1] for e in sl])

            def ok(x):
                if not len(js):
                    return True
                m = (js < x["i"]) & (js >= x["i"] - cd_bars) & (ds == x["d"])
                return not m.any()
            kept = [x for x in trades if ok(x)]
            taken, bal = orig(kept, idx, g, sizes)
        del ends
        return taken, bal
    return f


def run(D, df, pin, E, op: Opt, slip=0.0, cd_all=0):
    orig_sim, orig_port = P.simulate, G.portfolio
    P.simulate = lambda D_, ctx: simulate(D_, ctx, op)
    if cd_all:
        G.portfolio = portfolio_cd(cd_all)
    try:
        return Q.run2(D, df, pin, E, slip=slip)
    finally:
        P.simulate, G.portfolio = orig_sim, orig_port


def extras(df):
    return {**P3.extras(df), "kama_h4": P3.trend(df, kama_h4(df)), "klinger_h4": P3.trend(df, klinger_h4(df))}


VARIANTS = [
    ("Лимит на 0.25 ATR лучше, ждать 1 ч", Opt("atr", 0.25, 4), 0),
    ("Лимит на 0.5 ATR лучше, ждать 2 ч", Opt("atr", 0.5, 8), 0),
    ("Лимит на 1 ATR лучше, ждать 4 ч", Opt("atr", 1.0, 16), 0),
    ("Откат 38 % сигнальной свечи, ждать 1 ч", Opt("candle", 0.382, 4), 0),
    ("Откат 50 % сигнальной свечи, ждать 2 ч", Opt("candle", 0.5, 8), 0),
    ("Откат 61.8 % сигнальной свечи, ждать 2 ч", Opt("candle", 0.618, 8), 0),
    ("Откат 50 % свечи, не дождались — по рынку", Opt("candle", 0.5, 8, fallback=True), 0),
    ("Лимит 0.5 ATR, не дождались — по рынку", Opt("atr", 0.5, 8, fallback=True), 0),
    ("Лимит 0.5 ATR, стоп на прежнем уровне", Opt("atr", 0.5, 8, keep_stop=True), 0),
    ("Безубыток позже: 50 % и безубыток на +1.5R", Opt(part_r=1.5), 0),
    ("Безубыток позже: на +2R", Opt(part_r=2.0), 0),
    ("50 % на +1R, без безубытка", Opt(be=False), 0),
    ("50 % на +1R, стоп на −0.5R", Opt(be=False, be_lock=0.5), 0),
    ("Без фиксации и безубытка (только стоп/тейк 3R)", Opt(part_r=0), 0),
    ("Пауза стратегии 2 ч после её стопа", Opt(cd=8), 0),
    ("Пауза стратегии 4 ч после её стопа", Opt(cd=16), 0),
    ("После любого стопа 2 ч нет сделок в ту же сторону", Opt(), 8),
    ("После любого стопа 4 ч нет сделок в ту же сторону", Opt(), 16),
]


def reentry_stats(taken, idx, hours=4):
    """Сделки, открытые в ту же сторону в течение hours после стопа другой сделки, — их средний результат."""
    sl = [(t["j"], t["d"]) for t in taken if t["r"] <= -0.9]
    w = hours * 4
    after, rest = [], []
    for t in taken:
        hit = any(j < t["i"] <= j + w and d == t["d"] for j, d in sl)
        (after if hit else rest).append(t["r"])
    return len(after), np.mean(after) if after else 0, np.mean([r <= -0.9 for r in after]) if after else 0, \
        len(rest), np.mean(rest), np.mean([r <= -0.9 for r in rest])


def pullback_stats(D, df, taken):
    """Взятые сделки: был ли откат на 0.5 ATR против входа за первые 2 ч, и чем кончились обе группы."""
    from goldbot.indicators import atr
    a = atr(df, 14).to_numpy()
    h, l = D["h"], D["l"]
    o, spr = D["o"], D["spr"]
    g = {True: [], False: []}
    for t in taken:
        i, d = t["i"], t["d"]
        e = o[i] + (spr[i] if d == 1 else 0)
        seg = slice(i, min(i + 8, len(h)))
        adverse = (e - l[seg].min()) if d == 1 else (h[seg].max() - e)
        g[bool(adverse >= 0.5 * a[t["sig"]])].append(t["r"])
    return {k: (len(v), float(np.mean(v)), float(np.sum(v))) for k, v in g.items()}


def main():
    D0, df = R.setup()
    D, _, pin = R.prepare(D0, df)
    m5m = load_mt5_csv()
    k = 2 * m5m.close.mean()
    m5m = m5m.assign(open=k - m5m.open, high=k - m5m.low, low=k - m5m.high, close=k - m5m.close)
    dfm = resample(m5m, "15min")
    Dm, _, pinm = R.prepare(C.load(mirror=True), dfm)
    E, Em = extras(df), extras(dfm)
    base = Opt()
    b, bs, bm = run(D, df, pin, E, base), run(D, df, pin, E, base, SLIP), run(Dm, dfm, pinm, Em, base)
    L = ["## Диагностика текущего бота", ""]
    tk = b["taken"]
    pb = pullback_stats(D, df, tk)
    L += ["| За первые 2 ч после входа | Сделок | Средний результат | Итог |", "|---|---|---|---|",
          f"| был откат против нас на 0.5 ATR и больше | {pb[True][0]} | {pb[True][1]:+.2f}R | {pb[True][2]:+.0f}R |",
          f"| отката не было, сразу пошло в нашу сторону | {pb[False][0]} | {pb[False][1]:+.2f}R | {pb[False][2]:+.0f}R |", ""]
    for hrs in (2, 4, 8):
        na, ma, sa, nr, mr, sr = reentry_stats(tk, df.index, hrs)
        L.append(f"* Вход в ту же сторону в течение {hrs} ч после стопа: {na} сделок, в среднем {ma:+.2f}R, "
                 f"стопом кончились {sa:.0%}; остальные {nr} сделок: {mr:+.2f}R, стопом {sr:.0%}.")
    L += ["", R.HEAD, G.row("**как сейчас (10 стратегий)**", b) + f" {bs['tot']:+.0f} % | {bm['tot']:+.0f} % |"]
    print("\n".join(L), flush=True)
    for name, op, cd in VARIANTS:
        r, rs, rm = run(D, df, pin, E, op, cd_all=cd), run(D, df, pin, E, op, SLIP, cd_all=cd), \
            run(Dm, dfm, pinm, Em, op, cd_all=cd)
        ok = r["tot"] > b["tot"] and r["a"] > b["a"] and r["b"] > b["b"] and rs["tot"] > bs["tot"] and rm["tot"] > bm["tot"]
        ln = G.row(name + (" ✅" if ok else ""), r) + f" {rs['tot']:+.0f} % | {rm['tot']:+.0f} % |"
        print(ln, flush=True)
        L.append(ln)
    out = Path(__file__).resolve().parent.parent / "reports" / "pullback_table.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
