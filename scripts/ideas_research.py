"""Четыре идеи по торговле: проверка на истории XAUUSD 12.2023–08.2026.

Базовый вариант — как в боте сейчас: 5 стратегий на M15 (у каждой одна сделка за раз), стоп 2 ATR,
50 % на +1R, остаток в безубыток, тейк 3R, закрытие остатка по встречному сигналу. Спред учтён,
стоп и цель в одной свече — считается стоп. R — результат в рисках сделки (стоп = −1R).

1. Автоотключение стратегии с полосой неудач (по её последним N сделкам «на бумаге»).
2. Спред перед входом.
3. Тренд или боковик (ADX): какие стратегии работают в каком режиме.
4. Вести стоп за ценой после +2R вместо тейка 3R.

    python scripts/ideas_research.py     # отчёт в reports/ideas_research.md
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
from goldbot.data import PIP, load_mt5_csv, resample  # noqa: E402
from goldbot.indicators import adx, atr  # noqa: E402

SPLIT = pd.Timestamp("2025-07-01", tz=None)


@dataclass(frozen=True)
class Trail:
    start_r: float = 0.0     # после какого R начинаем вести стоп (0 — не ведём, тейк tp_r)
    atr_k: float = 0.0       # стоп на atr_k ATR от лучшей цены (закрытие свечи)
    lock_r: float = 0.0      # с этого момента стоп не ниже +lock_r
    tp_r: float = 3.0        # тейк (None/0 — без тейка, только стоп)


def simulate(D, ctx, tr: Trail = Trail(), spread_max: float = 0.0, spread_wait: int = 0):
    """Все сделки всех стратегий: dict(key, i вход, j выход, d, r, spr). spread_max — пропуск входа,
    если спред на свече входа больше spread_max доли стопа; spread_wait — сколько свечей ждать нормального спреда."""
    o, h, l, c, spr = D["o"], D["h"], D["l"], ctx["c"], D["spr"]
    sl_p, a, opp = D["sl"], ctx["atr"], ctx["opp"]
    n = len(o)
    out = []
    for k in KEYS:
        s = D["sig"][k]
        i = 0
        while i < n - 2:
            d = int(s[i])
            if d == 0:
                i += 1
                continue
            dist = sl_p[i] * PIP
            ent = i + 1
            if spread_max:
                w = 0
                while ent < n - 1 and spr[ent] > spread_max * dist and w < spread_wait:
                    ent += 1
                    w += 1
                if spr[ent] > spread_max * dist:
                    i = ent + 1
                    continue
            e = o[ent] + (spr[ent] if d == 1 else 0.0)
            stop = e - d * dist
            tp = e + d * tr.tp_r * dist if tr.tp_r else None
            part_px = e + d * dist
            rest, res, part_done = 1.0, 0.0, False
            new_stop = None
            trailing = False
            best = e
            j = ent
            while j < n:
                if new_stop is not None:
                    stop = new_stop if (new_stop - stop) * d > 0 else stop
                    new_stop = None
                bad = l[j] if d == 1 else h[j] + spr[j]
                good = h[j] if d == 1 else l[j] + spr[j]
                if (bad - stop) * d <= 0:
                    res += rest * (stop - e) * d / dist
                    break
                if not part_done and (good - part_px) * d >= 0:
                    res += 0.5 * (part_px - e) * d / dist
                    rest -= 0.5
                    part_done = True
                    new_stop = e + d * spr[j]
                if tp is not None and (good - tp) * d >= 0:
                    res += rest * (tp - e) * d / dist
                    break
                cl = c[j] + (spr[j] if d == -1 else 0.0)
                if tr.start_r:
                    if (good - e) * d >= tr.start_r * dist:
                        trailing = True
                    if trailing:
                        best = max(best, c[j]) if d == 1 else min(best, c[j] + spr[j])
                        cand = best - d * tr.atr_k * a[j]
                        lock = e + d * tr.lock_r * dist
                        cand = cand if (cand - lock) * d > 0 else lock
                        new_stop = cand if new_stop is None or (cand - new_stop) * d > 0 else new_stop
                if part_done and (cl - e) * d > 0 and opp[j] == -d:
                    res += rest * (cl - e) * d / dist
                    break
                j += 1
            else:
                break
            out.append(dict(key=k, i=ent, j=j, d=d, r=res, spr=spr[ent] / dist))
            i = j + 1
    return out


def stats(rows, idx):
    if not rows:
        return dict(n=0, win=0, tot=0, dd=0, streak=0, a=0, b=0, y={})
    rows = sorted(rows, key=lambda x: x["j"])
    r = np.array([x["r"] for x in rows])
    t = idx[[x["i"] for x in rows]]
    eq = np.cumsum(r)
    dd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    streak = cur = 0
    for x in r < -0.05:
        cur = cur + 1 if x else 0
        streak = max(streak, cur)
    first = t < SPLIT
    yrs = {y: r[t.year == y].sum() for y in (2024, 2025, 2026)}
    return dict(n=len(r), win=100 * (r > 0.05).mean(), tot=r.sum(), dd=dd, streak=streak,
                a=r[first].sum(), b=r[~first].sum(), avg=r.mean(), y=yrs)


HEAD = ("| {} | Сделок | В плюсе | Итог | На сделку | Макс. просадка | Убытков подряд | до 07.2025 | после 07.2025 |\n"
        "|---|---|---|---|---|---|---|---|---|")


def row(name, x):
    return (f"| {name} | {x['n']} | {x['win']:.0f}% | {x['tot']:+.0f}R | {x.get('avg', 0):+.3f}R | {x['dd']:.0f}R "
            f"| {x['streak']} | {x['a']:+.0f}R | {x['b']:+.0f}R |")


def auto_off(rows, n_last: int, thr: float, mode: str = "sum"):
    """Оставить сделки, перед которыми у стратегии последние n_last закрытых сделок дали больше thr R."""
    keep = []
    by = {}
    for x in rows:
        by.setdefault(x["key"], []).append(x)
    for k, lst in by.items():
        lst.sort(key=lambda x: x["i"])
        closed = sorted(lst, key=lambda x: x["j"])
        exits = np.array([x["j"] for x in closed])
        rs = np.array([x["r"] for x in closed])
        for x in lst:
            m = np.searchsorted(exits, x["i"])  # закрыты до входа
            last = rs[max(0, m - n_last):m]
            if len(last) < n_last:
                keep.append(x)
                continue
            if mode == "sum":
                ok = last.sum() > thr
            else:  # profit factor
                g, b = last[last > 0].sum(), -last[last < 0].sum()
                ok = (g / b if b else 9) >= thr
            if ok:
                keep.append(x)
    return keep


def main():
    D = load()
    df = resample(load_mt5_csv(), "15min")
    idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
    opp = np.zeros(len(df), dtype=int)
    for k in KEYS:
        opp = np.where(opp == 0, D["sig"][k], opp)
    ctx = dict(c=df.close.to_numpy(), atr=atr(df, 14).to_numpy(), opp=opp)
    base = simulate(D, ctx)
    B = stats(base, idx)
    L = ["# Четыре идеи по торговле: проверка на истории", "",
         "Свечи XAUUSD M15 01.12.2023 – 21.08.2026, 5 стратегий бота, у каждой одна сделка за раз, спред учтён,",
         "стоп и цель в одной свече — считается стоп. Сопровождение как в боте: 50 % на +1R, безубыток, тейк 3R,",
         "закрытие остатка по встречному сигналу. R — результат в рисках сделки (стоп = −1R).",
         "Две половины истории (до и после 01.07.2025) показаны отдельно: идея годится, только если помогает в обеих.",
         "Повторить: `python scripts/ideas_research.py`.", ""]

    # 1. Автоотключение
    L += ["## 1. Бот выключает стратегию с полосой неудач", "",
          "Стратегия торгует «на бумаге» всегда; реальные сигналы уходят, только если её последние N закрытых сделок",
          "в сумме лучше порога. Иначе — пауза, пока она снова не наберёт.", "",
          HEAD.format("Правило"), row("**как сейчас (всегда включены)**", B)]
    for n_last in (5, 10, 20, 30):
        for thr in (-3.0, 0.0):
            if n_last == 5 and thr == -3.0:
                continue
            L.append(row(f"последние {n_last} сделок в сумме > {thr:+g}R", stats(auto_off(base, n_last, thr), idx)))
    for n_last in (10, 20):
        L.append(row(f"последние {n_last}: PF ≥ 1", stats(auto_off(base, n_last, 1.0, "pf"), idx)))

    # по стратегиям: насколько их результат «держится» — автокорреляция серий
    L += ["", "Результат каждой стратегии (как сейчас):", "", HEAD.format("Стратегия")]
    for k in KEYS:
        L.append(row(k, stats([x for x in base if x["key"] == k], idx)))

    # 2. Спред
    sp = np.array([x["spr"] for x in base])
    L += ["", "## 2. Спред перед входом", "",
          f"В истории MetaTrader спред на входе в среднем {100 * sp.mean():.1f} % стопа, "
          f"99 % входов — до {100 * np.quantile(sp, .99):.1f} %, максимум {100 * sp.max():.1f} %.",
          "В файле истории записан обычный спред свечи, а не скачки в моменты новостей и ночного ролловера,",
          "поэтому история почти не показывает пользу этой защиты — она для редких реальных скачков у брокера.", "",
          HEAD.format("Правило"), row("как сейчас", B)]
    for lim in (0.05, 0.04, 0.03):
        L.append(row(f"пропуск, если спред > {100 * lim:g} % стопа", stats(simulate(D, ctx, spread_max=lim), idx)))
        L.append(row(f"ждать до 1 свечи, если спред > {100 * lim:g} % стопа",
                     stats(simulate(D, ctx, spread_max=lim, spread_wait=1), idx)))
    hr = idx.hour.to_numpy()
    night = [x for x in base if hr[x["i"]] in (21, 22, 23)]
    L.append(row("только входы 21:00–23:59 UTC (ролловер)", stats(night, idx)))

    # 3. Тренд или боковик
    ad = adx(df, 14)
    ad_h1 = pd.Series(adx(resample(load_mt5_csv(), "1h"), 14),
                      index=resample(load_mt5_csv(), "1h").index).shift(1).reindex(df.index, method="ffill").to_numpy()
    L += ["", "## 3. Тренд или боковик (ADX 14)", "",
          "ADX > 25 — тренд, ADX < 20 — боковик. Результат каждой стратегии отдельно по режиму на свече сигнала.", "",
          "| Стратегия | ТФ ADX | ADX < 20 | 20–25 | > 25 |", "|---|---|---|---|---|"]
    for k in KEYS:
        for name, arr in (("M15", ad), ("H1", ad_h1)):
            cells = []
            for lo_, hi_ in ((0, 20), (20, 25), (25, 999)):
                sel = [x for x in base if x["key"] == k and lo_ <= arr[x["i"] - 1] < hi_]
                s = stats(sel, idx)
                cells.append(f"{s['n']} сд. / {s.get('avg', 0):+.2f}R ({s['a']:+.0f} / {s['b']:+.0f})")
            L.append(f"| {k} | {name} | " + " | ".join(cells) + " |")
    L += ["", "В скобках — итог до и после 07.2025.", "", HEAD.format("Правило"), row("как сейчас", B)]
    brk = {"squeeze", "donchian"}
    for name, arr in (("M15", ad), ("H1", ad_h1)):
        for thr in (20, 25):
            sel = [x for x in base if (arr[x["i"] - 1] >= thr) == (x["key"] in brk) or np.isnan(arr[x["i"] - 1])]
            L.append(row(f"пробои только при ADX {name} ≥ {thr}, остальные только ниже", stats(sel, idx)))
            sel = [x for x in base if x["key"] not in brk or arr[x["i"] - 1] >= thr]
            L.append(row(f"пробои только при ADX {name} ≥ {thr}, остальные всегда", stats(sel, idx)))
            sel = [x for x in base if arr[x["i"] - 1] >= thr]
            L.append(row(f"все только при ADX {name} ≥ {thr}", stats(sel, idx)))

    # 4. Стоп за ценой после +2R
    L += ["", "## 4. Вести стоп за ценой после +2R вместо тейка 3R", "",
          "После +2R тейк снимается, стоп идёт за лучшим закрытием на k ATR, но не ниже +lock R.", "",
          HEAD.format("Вариант"), row("**как сейчас: тейк 3R**", B)]
    for start, k_, lock, tp in ((2, 1.0, 1.0, 0), (2, 1.5, 1.0, 0), (2, 2.0, 1.0, 0), (2, 3.0, 1.0, 0),
                                (2, 2.0, 1.0, 6), (2, 2.0, 2.0, 0), (1.5, 2.0, 0.5, 0), (3, 2.0, 2.0, 0)):
        tr = Trail(start_r=start, atr_k=k_, lock_r=lock, tp_r=tp)
        nm = f"после +{start:g}R стоп в {k_:g} ATR, не ниже +{lock:g}R" + (f", тейк {tp:g}R" if tp else ", без тейка")
        L.append(row(nm, stats(simulate(D, ctx, tr), idx)))
    for tp in (4, 5):
        L.append(row(f"тейк {tp}R без стопа за ценой", stats(simulate(D, ctx, Trail(tp_r=tp)), idx)))

    out = Path(__file__).resolve().parent.parent / "reports/ideas_research.md"
    out.write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
