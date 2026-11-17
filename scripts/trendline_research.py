"""Стратегия трендовой линии на XAUUSD M15: проверка на истории 12.2023–08.2026.

Линии строятся автоматически по свингам (pivot, n свечей слева и справа, без заглядывания вперёд):
* линия поддержки — через два последних свинг-лоя, второй выше первого (восходящая);
* линия сопротивления — через два последних свинг-хая, второй ниже первого (нисходящая).
Линия «живёт» max_age свечей после второго свинга и умирает после первого пробоя.

Сигналы:
* break  — закрытие за линией на margin·ATR: поддержка пробита вниз → SELL, сопротивление вверх → BUY;
* bounce — касание линии (тень дошла до линии ± 0.2 ATR) и закрытие с правильной стороны → по тренду линии.

Сделки — как в боте: вход по открытию следующей свечи, стоп 2 ATR, тейк 3 ATR (1.5R), спред учтён,
стоп и тейк в одной свече — стоп. Плюс вариант «как бот сейчас» (50 % на +1R, безубыток, тейк 3R).
Параметры выбираются по первой половине (до 07.2025), вторая — проверка.

    python scripts/trendline_research.py     # отчёт в reports/trendline_research.md
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import challenge_research as CR  # noqa: E402
import next_research as NR  # noqa: E402
from goldbot.data import PIP, load_mt5_csv, resample  # noqa: E402
from goldbot.indicators import adx, atr, pivot_high, pivot_low  # noqa: E402
from goldbot.strategies.research import htf_trend  # noqa: E402
from ideas_research import HEAD, SPLIT, row, stats  # noqa: E402


def trendline_signals(df, swing=5, mode="break", margin=0.0, max_age=96, min_gap=None, touch=0.2):
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    a = atr(df, 14).to_numpy()
    ph, pl = pivot_high(h, swing), pivot_low(l, swing)
    n = len(c)
    sig = np.zeros(n, dtype=np.int8)
    min_gap = min_gap or swing
    lows, highs = [], []          # (индекс свинга, цена)
    sup = res = None              # (i1, p1, slope, i2, used_bounce_bar)
    for i in range(n):
        if not np.isnan(pl[i]):
            lows = (lows + [(i - swing, pl[i])])[-2:]
            if len(lows) == 2 and lows[1][1] > lows[0][1] and lows[1][0] - lows[0][0] >= min_gap:
                (i1, p1), (i2, p2) = lows
                k = (p2 - p1) / (i2 - i1)
                # между свингами и после второго до сейчас не было закрытия под линией
                seg = np.arange(i1, i + 1)
                sup = [i1, p1, k, i2] if (c[seg] >= p1 + k * (seg - i1)).all() else None
        if not np.isnan(ph[i]):
            highs = (highs + [(i - swing, ph[i])])[-2:]
            if len(highs) == 2 and highs[1][1] < highs[0][1] and highs[1][0] - highs[0][0] >= min_gap:
                (i1, p1), (i2, p2) = highs
                k = (p2 - p1) / (i2 - i1)
                seg = np.arange(i1, i + 1)
                res = [i1, p1, k, i2] if (c[seg] <= p1 + k * (seg - i1)).all() else None
        if np.isnan(a[i]):
            continue
        s = 0
        if sup is not None:
            if i - sup[3] > max_age:
                sup = None
            else:
                y = sup[1] + sup[2] * (i - sup[0])
                if c[i] < y - margin * a[i]:
                    if mode == "break":
                        s = -1
                    sup = None
                elif c[i] < y:
                    sup = None                       # закрылись под линией без запаса — линия сломана
                elif mode == "bounce" and i > sup[3] + swing and l[i] <= y + touch * a[i]:
                    s = 1
        if res is not None and s == 0:
            if i - res[3] > max_age:
                res = None
            else:
                y = res[1] + res[2] * (i - res[0])
                if c[i] > y + margin * a[i]:
                    if mode == "break":
                        s = 1
                    res = None
                elif c[i] > y:
                    res = None
                elif mode == "bounce" and i > res[3] + swing and h[i] >= y - touch * a[i]:
                    s = -1
        sig[i] = s
    return sig


def simple(D, sig, tp_r=1.5):
    """Стоп 2 ATR, тейк 3 ATR, одна сделка за раз."""
    o, h, l, spr, slp = D["o"], D["h"], D["l"], D["spr"], D["sl"]
    n = len(o)
    out = []
    i = 0
    while i < n - 2:
        d = int(sig[i])
        if d == 0:
            i += 1
            continue
        ent = i + 1
        dist = slp[i] * PIP
        e = o[ent] + (spr[ent] if d == 1 else 0.0)
        stop, tp = e - d * dist, e + d * tp_r * dist
        j = ent
        while j < n:
            bad = l[j] if d == 1 else h[j] + spr[j]
            good = h[j] if d == 1 else l[j] + spr[j]
            if (bad - stop) * d <= 0:
                r = -1.0
                break
            if (good - tp) * d >= 0:
                r = tp_r
                break
            j += 1
        else:
            break
        out.append(dict(key="x", i=ent, j=j, d=d, r=r, sig=i))
        i = j + 1
    return out


def main():
    D0 = CR.load()
    df = resample(load_mt5_csv(), "15min")
    idx = df.index
    ad = adx(df, 14)
    trend = htf_trend(df, "1D", 50)

    L = ["# Стратегия трендовой линии: проверка на истории", "",
         "Свечи XAUUSD M15 (MetaTrader 5) 01.12.2023 – 21.08.2026, спред учтён. Линии строит программа по точным",
         "правилам, без заглядывания в будущее: восходящая линия — через два последних свинг-лоя (второй выше первого),",
         "нисходящая — через два последних свинг-хая (второй ниже). Свинг — минимум/максимум, у которого N свечей слева",
         "и справа выше/ниже; он становится известен только через N свечей. Линия живёт ограниченное время после",
         "второго свинга и умирает после первого закрытия за ней.", "",
         "* **Пробой** — закрытие свечи за линией (как на скриншоте): восходящая пробита вниз → SELL, нисходящая вверх → BUY.",
         "* **Отскок** — тень дошла до линии и свеча закрылась с правильной стороны → вход по направлению линии.", "",
         "Сделка — как у бота: вход по открытию следующей свечи, стоп 2 ATR, тейк 3 ATR (1.5R), стоп и тейк в одной",
         "свече — считаем стоп. R — результат в рисках. Параметры выбираем по первой половине (до 07.2025),",
         "вторая половина — честная проверка. Повторить: `python scripts/trendline_research.py`.", ""]

    # 1) перебор параметров, простая сделка 2 ATR / 3 ATR
    grid = []
    filt_names = {"none": "без фильтра", "trend": "по дневному тренду", "adx": "ADX<25"}
    for mode, sw, mg, age, flt in itertools.product(("break", "bounce"), (3, 5, 8), (0.0, 0.3), (48, 96, 192),
                                                    ("none", "trend", "adx")):
        if mode == "bounce" and mg:
            continue
        s = trendline_signals(df, sw, mode, mg, age)
        if flt == "trend":
            s = np.where(s == trend, s, 0)
        elif flt == "adx":
            s = np.where(ad < 25, s, 0)
        st = stats(simple(D0, s), idx)
        grid.append(((mode, sw, mg, age, flt), st, s))

    def name(p):
        mode, sw, mg, age, flt = p
        m = "пробой" if mode == "break" else "отскок"
        return (f"{m}, свинг {sw}, запас {mg:g} ATR, линия {age * 15 // 60} ч, {filt_names[flt]}")

    L += ["## 1. Все варианты (простая сделка: стоп 2 ATR, тейк 3 ATR)", "",
          f"Проверено {len(grid)} вариантов. Сделка в плюс нужна в {100 / 2.5:.0f}% случаев, чтобы выйти в ноль "
          "(тейк 1.5R против стопа 1R) — плюс спред.", ""]
    for mode in ("break", "bounce"):
        g = [x for x in grid if x[0][0] == mode]
        a_pos = sum(1 for x in g if x[1]["a"] > 0)
        b_pos = sum(1 for x in g if x[1]["b"] > 0)
        both = sum(1 for x in g if x[1]["a"] > 0 and x[1]["b"] > 0)
        L.append(f"* {'Пробой' if mode == 'break' else 'Отскок'}: {len(g)} вариантов, в плюсе в 1-й половине — "
                 f"{a_pos}, во 2-й — {b_pos}, в обеих — {both}.")
    L += ["", "Срок жизни линии (12, 24 или 48 ч) почти ничего не меняет: линию раньше заменяет новый свинг или",
          "ломает закрытие. Поэтому ниже все варианты при сроке 24 ч:", "", HEAD.format("Вариант")]
    for p, st, _ in sorted((x for x in grid if x[0][3] == 96), key=lambda x: -x[1]["a"]):
        L.append(row(name(p), st))
    best_by_mode = {}
    for mode in ("break", "bounce"):
        best_by_mode[mode] = max((x for x in grid if x[0][0] == mode), key=lambda x: x[1]["a"])
    L += ["", "Лучший вариант каждого типа по первой половине:", "", HEAD.format("Вариант")]
    for mode in ("break", "bounce"):
        p, st, _ = best_by_mode[mode]
        L.append(row(name(p), st))
    L += ["", "Вариант «как на скриншоте» (пробой, свинг 5, без фильтров) по годам:", "", HEAD.format("Вариант")]
    for age in (48, 96, 192):
        p = ("break", 5, 0.0, age, "none")
        st = next(x[1] for x in grid if x[0] == p)
        L.append(row(name(p), st))

    # 2) для сравнения — текущие стратегии бота с той же простой сделкой
    L += ["", "## 2. Сравнение с текущими стратегиями бота (та же простая сделка)", "", HEAD.format("Стратегия")]
    for k in CR.KEYS:
        L.append(row(k, stats(simple(D0, D0["sig"][k]), idx)))
    for mode in ("break", "bounce"):
        p, _, s = best_by_mode[mode]
        L.append(row(f"**трендовая линия: {name(p)}**", stats(simple(D0, s), idx)))

    # 3) добавить к боту: как бот торгует сейчас (50 % на +1R, безубыток, тейк 3R, ADX-фильтр, вес по согласию)
    D = dict(D0)
    D["sig"] = dict(D0["sig"])
    for k in ("squeeze", "donchian"):
        D["sig"][k] = np.where(ad >= 25, 0, D0["sig"][k]).astype(np.int8)

    def run(keys):
        NR.KEYS = keys
        opp = np.zeros(len(df), dtype=int)
        for k in keys:
            opp = np.where(opp == 0, D["sig"][k], opp)
        ctx = dict(c=df.close.to_numpy(), atr=atr(df, 14).to_numpy(), opp=opp, trend=trend)
        sigs = np.stack([D["sig"][k] for k in keys])
        rows = NR.weigh(NR.simulate(D, ctx), sigs)
        return rows

    base_rows = run(CR.KEYS)
    L += ["", "## 3. Если добавить в бота (как бот торгует сейчас)", "",
          "Бот после PR #42: 50 % на +1R, безубыток, тейк 3R, закрытие по встречному сигналу, лот по согласию стратегий.", "",
          HEAD.format("Вариант"), row("**бот сейчас (5 стратегий)**", stats(base_rows, idx))]
    for mode in ("break", "bounce"):
        p, _, s = best_by_mode[mode]
        D["sig"]["tl"] = s.astype(np.int8)
        rows = run(CR.KEYS + ("tl",))
        L.append(row(f"бот + {name(p)}", stats(rows, idx)))
        tl = [x for x in rows if x["key"] == "tl"]
        L.append(row(f"  — из них сделки трендовой линии", stats(tl, idx)))
    NR.KEYS = CR.KEYS

    out = Path(__file__).resolve().parent.parent / "reports/trendline_research.md"
    out.write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
