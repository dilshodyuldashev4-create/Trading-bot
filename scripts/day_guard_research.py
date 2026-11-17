"""Защита обычного (не проп) счёта от плохих дней: проверка на истории XAUUSD 12.2023–08.2026.

Повод — 17.11.2026: 9 сделок за день, 8 в минусе (−473 $ на счёте 5000 $). Бот продавал против роста,
после каждого стопа открывал новую сделку, а между продажами дважды купил.

База — обычный счёт как в боте сейчас: 5 стратегий на M15, стоп 2 ATR, 50 % на +1R и безубыток, тейк 3R,
закрытие остатка по встречному сигналу, пробои не входят при ADX ≥ 25, лот ×0.75 / ×1.5 по согласию
стратегий, без встречных сделок и без двух сделок в одну сторону на одной свече (engine.py).
Риск 1 % от начального баланса на сделку (без сложного процента — так варианты сравнимы). День — по времени сервера MT5 (свечи в истории — время сервера).

Варианты: стоп дня после N Stop Loss; запрет сделок против направления, в котором был стоп; риск ×k,
когда баланс ниже максимума на X %.

    python scripts/day_guard_research.py     # отчёт в reports/day_guard_research.md
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from challenge_research import KEYS, load  # noqa: E402
from goldbot.data import load_mt5_csv, resample  # noqa: E402
from goldbot.indicators import atr  # noqa: E402
from ideas_research import SPLIT, adx  # noqa: E402
from profit_research import BREAKOUTS, simulate  # noqa: E402

RISK = 1.0


@dataclass(frozen=True)
class Guard:
    day_sl: int = 0          # после стольких Stop Loss за день — до завтра без новых сделок (0 — нет)
    lock_side: bool = False  # после стопа — до завтра только в сторону, куда рынок выбил стоп
    day_side: bool = False   # за день только в одну сторону — как первая сделка дня
    dd_pct: float = 0.0      # баланс ниже максимума на столько % — риск × dd_mult (0 — нет)
    dd_mult: float = 0.25


def portfolio(trades, idx, g: Guard, sizes):
    """Сделки всех стратегий по времени входа → какие бот открыл бы с защитой g. Баланс в % от старта."""
    day = np.asarray(idx.normalize().asi8)
    bal = peak = 100.0
    taken = []
    opened: list[dict] = []
    events = []          # закрытые сделки: (бар выхода, r, d)
    fresh: dict[int, set] = {}
    first_side: dict = {}
    for x in sorted(trades, key=lambda x: (x["i"], KEYS.index(x["key"]))):
        i = x["i"]
        # сделки, закрытые до входа: баланс
        still = []
        for t in opened:
            if t["j"] < i:
                bal += t["pnl"]
                peak = max(peak, bal)
                events.append((t["j"], t["r"], t["d"]))
                events.sort()
            else:
                still.append(t)
        opened = still
        if any(t["key"] == x["key"] for t in opened):
            continue
        if any(t["d"] == -x["d"] for t in opened):
            continue                      # встречная сделка открыта
        if x["d"] in fresh.get(i, set()):
            continue                      # в эту сторону уже вошли на этой свече
        k = len(events)
        while k and day[events[k - 1][0]] == day[i]:
            k -= 1
        sl_today = [e for e in events[k:] if e[1] <= -0.9]
        if g.day_sl and len(sl_today) >= g.day_sl:
            continue
        if g.lock_side and sl_today and x["d"] == sl_today[0][2]:
            continue                      # стоп по продаже — сегодня больше не продаём (и наоборот)
        if g.day_side:
            side = first_side.setdefault(day[i], x["d"])
            if x["d"] != side:
                continue
        r = RISK * sizes[id(x)]
        if g.dd_pct and bal <= peak * (1 - g.dd_pct / 100):
            r *= g.dd_mult
        t = {**x, "pnl": x["r"] * r}
        opened.append(t)
        fresh.setdefault(i, set()).add(x["d"])
        taken.append(t)
    for t in opened:
        bal += t["pnl"]
        events.append((t["j"], t["r"], t["d"]))
    return taken, bal


def report(taken, idx):
    taken = sorted(taken, key=lambda t: t["j"])
    pnl = np.array([t["pnl"] for t in taken])
    eq = 100 + np.cumsum(pnl)
    pk = np.maximum.accumulate(np.r_[100, eq])
    dd = float(((pk - np.r_[100, eq]) / pk).max() * 100)
    days = pd.Series(pnl, index=idx[[t["j"] for t in taken]].normalize()).groupby(level=0).sum()
    t_in = idx[[t["i"] for t in taken]]
    first = t_in < SPLIT
    tot = eq[-1] - 100
    return dict(n=len(pnl), tot=tot, dd=dd, ratio=tot / dd, worst=days.min(), bad=int((days <= -3).sum()),
                a=pnl[first].sum(), b=pnl[~first].sum())


HEAD = ("| Вариант | Сделок | Итог | Макс. просадка | Итог / просадка | Худший день | Дней хуже −3 % | до 07.2025 | после 07.2025 |\n"
        "|---|---|---|---|---|---|---|---|---|")


def row(name, s):
    return (f"| {name} | {s['n']} | {s['tot']:+.0f} % | {s['dd']:.1f} % | {s['ratio']:.1f} | {s['worst']:+.1f} % | {s['bad']} "
            f"| {s['a']:+.0f} % | {s['b']:+.0f} % |")


def main():
    D0 = load()
    df = resample(load_mt5_csv(), "15min")
    idx = df.index
    ad = adx(df, 14)
    D = dict(D0)
    D["sig"] = dict(D0["sig"])
    for k in BREAKOUTS:
        D["sig"][k] = np.where(ad >= 25, 0, D0["sig"][k]).astype(np.int8)
    opp = np.zeros(len(df), dtype=int)
    for k in KEYS:
        opp = np.where(opp == 0, D["sig"][k], opp)
    trades = simulate(D, dict(c=df.close.to_numpy(), atr=atr(df, 14).to_numpy(), opp=opp))
    sigs = np.stack([D["sig"][k] for k in KEYS])

    def agree(x):
        ki = KEYS.index(x["key"])
        lo = max(0, x["sig"] - 3)
        return bool((np.delete(sigs[:, lo:x["sig"] + 1], ki, axis=0) == x["d"]).any())
    sizes = {id(x): 1.5 if agree(x) else 0.75 for x in trades}

    variants = [
        ("**без защиты (как было)**", Guard()),
        ("за день только в сторону первой сделки дня", Guard(day_side=True)),
        ("стоп дня после 1-го SL", Guard(day_sl=1)),
        ("стоп дня после 2-го SL", Guard(day_sl=2)),
        ("стоп дня после 3-го SL", Guard(day_sl=3)),
        ("стоп дня после 4-го SL", Guard(day_sl=4)),
        ("после SL — до завтра не входить в ту же сторону", Guard(lock_side=True)),
        ("риск ×0.5 при −3 % от максимума", Guard(dd_pct=3, dd_mult=0.5)),
        ("риск ×0.5 при −5 % от максимума", Guard(dd_pct=5, dd_mult=0.5)),
        ("риск ×0.75 при −5 % от максимума", Guard(dd_pct=5, dd_mult=0.75)),
        ("риск ×0.5 при −10 % от максимума", Guard(dd_pct=10, dd_mult=0.5)),
        ("одна сторона + стоп после 2-го SL", Guard(day_side=True, day_sl=2)),
        ("одна сторона + стоп после 3-го SL", Guard(day_side=True, day_sl=3)),
        ("одна сторона + стоп после 4-го SL", Guard(day_side=True, day_sl=4)),
        ("одна сторона + стоп после 3-го SL + риск ×0.75 при −5 %", Guard(day_side=True, day_sl=3, dd_pct=5, dd_mult=0.75)),
        ("одна сторона + стоп после 2-го SL + риск ×0.5 при −3 % (PR сначала)", Guard(day_side=True, day_sl=2, dd_pct=3, dd_mult=0.5)),
    ]
    L = ["# Защита обычного счёта от плохих дней", "",
         "Свечи XAUUSD M15 01.12.2023 – 21.08.2026, обычный счёт (не проп): 5 стратегий, 50 % на +1R, безубыток,",
         "тейк 3R, закрытие по встречному сигналу, пробои не входят при ADX ≥ 25, лот ×0.75 / ×1.5 по согласию.",
         "Риск 1 % от начального баланса на сделку, без сложного процента, спред учтён, стоп и цель в одной свече — стоп.",
         "День — по времени сервера MT5. Просадка — от максимума баланса. Повторить: `python scripts/day_guard_research.py`.",
         "", HEAD]
    for name, g in variants:
        taken, _ = portfolio(trades, idx, g, sizes)
        L.append(row(name, report(taken, idx)))
    L += ["", "## Вывод", "",
          "* Без защиты бывают дни по −9 % (риск 1 %) и 70 дней хуже −3 % за 2.7 года — 17.11.2026 был таким днём.",
          "* «За день только в сторону первой сделки дня» — прибыль не меньше (+359 % против +345 %), просадка",
          "  28 % вместо 34 %: встречные сделки в один день в среднем убыточны.",
          "* Стоп дня после 1–2 Stop Loss и снижение риска в просадке убирают плохие дни, но заметно режут прибыль.",
          "* **В боте по умолчанию: только стоп дня после 4-го SL** — прибыль +331 % (−4 %), худший день",
          "  −6.8 % вместо −9.4 %. «Одна сторона за день» (AUTOTRADE_DAY_SIDE=1) и снижение риска в просадке",
          "  (AUTOTRADE_DD_PCT) есть, но выключены."]
    out = Path(__file__).resolve().parent.parent / "reports" / "day_guard_research.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
