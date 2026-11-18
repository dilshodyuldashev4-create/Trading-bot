"""Не входить по ходу движения, когда оно уже растянуто (продажа на дне после сильного падения).

Повод — 18.11.2026: золото за ~15 часов упало на ~100 $ (3847 → 3740), бот продал 0.02 у самого дна по 3747,
стоп 3763 выбит откатом. Проверяем на истории XAUUSD 12.2023–08.2026: если перед входом цена уже ушла
в сторону сделки на k ATR (за N свечей M15, или от EMA50), — сделку пропустить.

База — обычный счёт как в боте сейчас (portfolio из day_guard_research, стоп дня после 4-го SL).

    python scripts/overextended_research.py   # отчёт в reports/overextended_research.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from challenge_research import KEYS, load  # noqa: E402
from day_guard_research import HEAD, Guard, portfolio, report, row  # noqa: E402
from goldbot.data import load_mt5_csv, resample  # noqa: E402
from goldbot.indicators import atr  # noqa: E402
from ideas_research import adx  # noqa: E402
from profit_research import BREAKOUTS, simulate  # noqa: E402


def base():
    D0 = load()
    df = resample(load_mt5_csv(), "15min")
    ad = adx(df, 14)
    D = dict(D0)
    D["sig"] = dict(D0["sig"])
    for k in BREAKOUTS:
        D["sig"][k] = np.where(ad >= 25, 0, D0["sig"][k]).astype(np.int8)
    opp = np.zeros(len(df), dtype=int)
    for k in KEYS:
        opp = np.where(opp == 0, D["sig"][k], opp)
    a = atr(df, 14)
    trades = simulate(D, dict(c=df.close.to_numpy(), atr=a.to_numpy(), opp=opp))
    sigs = np.stack([D["sig"][k] for k in KEYS])

    def agree(x):
        ki = KEYS.index(x["key"])
        lo = max(0, x["sig"] - 3)
        return bool((np.delete(sigs[:, lo:x["sig"] + 1], ki, axis=0) == x["d"]).any())
    sizes = {id(x): 1.5 if agree(x) else 0.75 for x in trades}
    return df, a, trades, sizes


def features(df, a):
    c = df.close
    h1a = atr(resample_h1(df), 14).reindex(df.index, method="ffill")
    f = {}
    for n in (16, 32, 48, 64, 96):          # 4, 8, 12, 16, 24 часа
        f[f"mv{n}"] = ((c - c.shift(n)) / h1a).to_numpy()
    for span in (50, 200):
        f[f"ema{span}"] = ((c - c.ewm(span=span, adjust=False).mean()) / h1a).to_numpy()
    # от экстремума за 24 ч: насколько цена уже ушла от хая (для продажи) / лоя (для покупки)
    f["hi96"] = ((df.high.rolling(96).max() - c) / h1a).to_numpy()
    f["lo96"] = ((c - df.low.rolling(96).min()) / h1a).to_numpy()
    return f


def resample_h1(df):
    return df.resample("1h").agg(dict(open="first", high="max", low="min", close="last")).dropna()


def ext(f, name, x):
    i, d = x["sig"], x["d"]
    if name == "range96":
        return f["hi96"][i] if d == -1 else f["lo96"][i]
    return f[name][i] * d


def main():
    df, a, trades, sizes = base()
    idx = df.index
    f = features(df, a)
    g = Guard(day_sl=4)
    L = ["# Не входить по ходу растянутого движения", "",
         "Повод — 18.11.2026: золото за ~15 ч упало на ~100 $ (3847 → 3740), бот продал у дна по 3747 и получил стоп.",
         "Свечи XAUUSD M15 01.12.2023 – 21.08.2026, обычный счёт как в боте сейчас (5 стратегий, 50 % на +1R,",
         "безубыток, тейк 3R, ADX-фильтр пробоев, лот ×0.75 / ×1.5, стоп дня после 4-го SL). Риск 1 % от старта.",
         "Растянутость — путь цены в сторону сделки перед сигналом в ATR(14) H1. Повторить: `python scripts/overextended_research.py`.",
         "", "## Сделки по растянутости (все сигналы, до защиты дня)", "",
         "| Мера | Корзина | Сделок | Средний R | Сумма R |", "|---|---|---|---|---|"]
    names = ["mv16", "mv32", "mv48", "mv96", "ema50", "ema200", "range96"]
    bins = [-np.inf, 0, 1, 2, 3, 4, 5, 6, np.inf]
    for nm in names:
        v = np.array([ext(f, nm, x) for x in trades])
        r = np.array([x["r"] for x in trades])
        for lo, hi in zip(bins[:-1], bins[1:]):
            m = (v >= lo) & (v < hi)
            if m.sum():
                L.append(f"| {nm} | {lo:g}…{hi:g} | {m.sum()} | {r[m].mean():+.2f} | {r[m].sum():+.0f} |")
    L += ["", "## Фильтр в портфеле", "", HEAD]
    taken, _ = portfolio(trades, idx, g, sizes)
    L.append(row("**как сейчас**", report(taken, idx)))
    for nm in names:
        for k in (3, 4, 5, 6, 8):
            keep = [x for x in trades if not ext(f, nm, x) >= k]
            taken, _ = portfolio(keep, idx, g, sizes)
            L.append(row(f"пропуск, если {nm} ≥ {k}", report(taken, idx)))
    out = Path(__file__).resolve().parent.parent / "reports" / "overextended_research.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
