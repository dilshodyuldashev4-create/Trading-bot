"""Фильтр «не покупать под сопротивлением и не продавать над поддержкой» для стратегий бота.

База — как в ideas_research.py: 5 стратегий на M15, стоп 2 ATR, 50 % на +1R, безубыток, тейк 3R.
Уровни H1 без заглядывания вперёд: сопротивление — ближайший подтверждённый разворот (пивот 3/3) H1 выше цены
за последние W часов, поддержка — ближайший ниже. Покупка блокируется, если до сопротивления меньше k·ATR(H1),
продажа — если до поддержки меньше k·ATR(H1).

    python scripts/sr_filter_research.py     # отчёт в reports/sr_filter_research.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from challenge_research import KEYS, load  # noqa: E402
from goldbot.data import load_mt5_csv, resample  # noqa: E402
from goldbot.indicators import atr, pivot_high, pivot_low  # noqa: E402
from ideas_research import HEAD, row, simulate, stats  # noqa: E402

PIV = 3


def room(df15: pd.DataFrame, h1: pd.DataFrame, win: int):
    """Для каждой M15: расстояние от close до ближайшего сопротивления выше и поддержки ниже, в ATR(H1)."""
    hh, ll = h1.high.to_numpy(), h1.low.to_numpy()
    a = atr(h1, 14).to_numpy()
    ph, pl = pivot_high(hh, PIV), pivot_low(ll, PIV)
    # H1 с меткой t закрыта в t+1h: берём последнюю закрытую
    pos = np.searchsorted(h1.index + pd.Timedelta(hours=1), df15.index + pd.Timedelta(minutes=15), side="right") - 1
    c = df15.close.to_numpy()
    up = np.full(len(c), np.inf)
    dn = np.full(len(c), np.inf)
    for m in range(len(c)):
        p = pos[m]
        if p < win:
            continue
        lo_ = p - win + 1
        x, y = ph[lo_:p + 1], pl[lo_:p + 1]
        x = x[~np.isnan(x)]
        y = y[~np.isnan(y)]
        above = x[x > c[m]]
        below = y[y < c[m]]
        if above.size:
            up[m] = (above.min() - c[m]) / a[p]
        if below.size:
            dn[m] = (c[m] - below.max()) / a[p]
    return up, dn


def main():
    D = load()
    m5 = load_mt5_csv()
    df = resample(m5, "15min")
    h1 = resample(m5, "1h")
    idx = df.index
    opp = np.zeros(len(df), dtype=int)
    for k in KEYS:
        opp = np.where(opp == 0, D["sig"][k], opp)
    ctx = dict(c=df.close.to_numpy(), atr=atr(df, 14).to_numpy(), opp=opp)
    base = simulate(D, ctx)
    B = stats(base, idx)
    L = ["# Фильтр уровней: не покупать под сопротивлением, не продавать над поддержкой", "",
         "Свечи XAUUSD M15 01.12.2023 – 21.08.2026, 5 стратегий бота, сопровождение как в боте "
         "(стоп 2 ATR, 50 % на +1R, безубыток, тейк 3R), спред учтён. Уровни — подтверждённые развороты H1 "
         "(пивот 3/3) за последние W часов: ближайший выше цены — сопротивление, ниже — поддержка. "
         "R — в рисках сделки. Повторить: `python scripts/sr_filter_research.py`.", ""]
    rooms = {w: room(df, h1, w) for w in (24, 48, 96)}

    # диагностика: как сейчас торгуются сделки в зависимости от места до уровня
    up, dn = rooms[48]
    L += ["## Как сейчас: результат сделок по расстоянию до уровня (W = 48 ч)", "",
          "Для BUY — до сопротивления выше, для SELL — до поддержки ниже, на свече сигнала, в ATR(H1).", "",
          HEAD.format("Место до уровня")]
    for lo_, hi_ in ((0, .5), (.5, 1), (1, 2), (2, 4), (4, np.inf)):
        sel = [x for x in base if lo_ <= (up if x["d"] == 1 else dn)[x["i"] - 1] < hi_]
        L.append(row(f"{lo_:g}–{hi_:g} ATR", stats(sel, idx)))

    L += ["", "## Фильтр для всех стратегий", "", HEAD.format("Правило"), row("**как сейчас**", B)]
    best = None
    for w in (24, 48, 96):
        up, dn = rooms[w]
        for k_ in (0.5, 1.0, 1.5, 2.0):
            sig = {}
            for key in KEYS:
                s = D["sig"][key].copy()
                s[(s == 1) & (up < k_)] = 0
                s[(s == -1) & (dn < k_)] = 0
                sig[key] = s
            st = stats(simulate({**D, "sig": sig}, ctx), idx)
            L.append(row(f"W={w} ч, блок ближе {k_:g} ATR", st))
            if best is None or st["a"] > best[0]["a"]:
                best = (st, w, k_, sig)
    st, w, k_, sig = best
    L += ["", f"Лучший по первой половине: W={w} ч, {k_:g} ATR. По стратегиям (было → стало):", "",
          HEAD.format("Стратегия")]
    filt = simulate({**D, "sig": sig}, ctx)
    for key in KEYS:
        L.append(row(f"{key} как сейчас", stats([x for x in base if x["key"] == key], idx)))
        L.append(row(f"{key} с фильтром", stats([x for x in filt if x["key"] == key], idx)))
    out = Path(__file__).resolve().parent.parent / "reports/sr_filter_research.md"
    out.write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
