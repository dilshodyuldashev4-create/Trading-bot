"""Ещё три идеи для прибыли: проверка на истории XAUUSD 12.2023–08.2026.

База — бот после PR #42: 5 стратегий на M15, стоп 2 ATR, 50 % на +1R, безубыток, тейк 3R, закрытие остатка
по встречному сигналу, пробои не входят при ADX(14) ≥ 25, лот ×1.5 при согласии стратегий и ×0.75 у одиночного
сигнала. Спред учтён, стоп и цель в одной свече — стоп. R — результат в рисках обычной сделки.

1. Добавка к сделке, когда её стоп уже в безубытке (после фиксации 50 % на +1R).
2. Перезаход после выбивания в безубыток: стоп-ордер за уровнем фиксации, пока тренд сделки не сломан.
3. Свой тейк для каждой стратегии (выбран по первой половине истории, проверка на второй).

    python scripts/next_research.py     # отчёт в reports/next_research.md
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from challenge_research import KEYS, load  # noqa: E402
from goldbot.data import PIP, load_mt5_csv, resample  # noqa: E402
from goldbot.indicators import adx, atr  # noqa: E402
from ideas_research import HEAD, SPLIT, row, stats  # noqa: E402

BREAKOUTS = ("squeeze", "donchian")


@dataclass(frozen=True)
class Opt:
    add: float = 0.0          # добавка такого размера (от обычного лота) в момент фиксации, стоп — цена входа
    reentry_bars: int = 0     # после безубытка: стоп-ордер на уровне фиксации столько свечей (0 — нет)
    tp: dict | None = None    # тейк в R по стратегиям (None — 3R у всех)


def simulate(D, ctx, op: Opt = Opt()):
    o, h, l, c, spr = D["o"], D["h"], D["l"], ctx["c"], D["spr"]
    sl_p, opp = D["sl"], ctx["opp"]
    n = len(o)
    out = []
    for k in KEYS:
        s = D["sig"][k]
        tp_r = (op.tp or {}).get(k, 3.0)
        i = 0
        pending = None   # (до какой свечи, направление, уровень входа, стоп-дистанция, свеча сигнала)
        while i < n - 2:
            d = int(s[i])
            re = False
            if d == 0 and pending is not None and i <= pending[0]:
                pd_, lvl, dist0 = pending[1], pending[2], pending[3]
                reach = h[i] if pd_ == 1 else l[i] + spr[i]
                if (reach - lvl) * pd_ >= 0 and ctx["trend"][i] == pd_:
                    d, re = pd_, True
            if d == 0:
                i += 1
                continue
            if re:
                dist = pending[3]
                ent = i
                e = pending[2] + (spr[i] if d == 1 else 0.0)
                sig_i = pending[4]
            else:
                dist = sl_p[i] * PIP
                ent = i + 1
                e = o[ent] + (spr[ent] if d == 1 else 0.0)
                sig_i = i
            pending = None
            stop = e - d * dist
            tp = e + d * tp_r * dist
            part_px = e + d * dist
            rest, res, part_done = 1.0, 0.0, False
            new_stop = None
            exit_px, how = None, ""
            j = ent
            while j < n:
                if new_stop is not None:
                    stop, new_stop = new_stop, None
                bad = l[j] if d == 1 else h[j] + spr[j]
                good = h[j] if d == 1 else l[j] + spr[j]
                if (bad - stop) * d <= 0:
                    exit_px, how = stop, ("be" if part_done else "sl")
                    break
                if not part_done and (good - part_px) * d >= 0:
                    res += 0.5 * (part_px - e) * d / dist
                    rest -= 0.5
                    part_done = True
                    new_stop = e + d * spr[j]
                if (good - tp) * d >= 0:
                    exit_px, how = tp, "tp"
                    break
                cl = c[j] + (spr[j] if d == -1 else 0.0)
                if part_done and (cl - e) * d > 0 and opp[j] == -d:
                    exit_px, how = cl, "rev"
                    break
                j += 1
            else:
                break
            res += rest * (exit_px - e) * d / dist
            if op.add and part_done:
                # добавка по цене фиксации (с её спредом), выходит вместе с остатком основной сделки
                cost = spr[j] / dist if d == 1 else 0.0
                res += op.add * ((exit_px - part_px) * d / dist - cost)
            out.append(dict(key=k, i=ent, j=j, d=d, r=res, sig=sig_i, re=re, how=how))
            if op.reentry_bars and how == "be":
                pending = (j + op.reentry_bars, d, part_px, dist, sig_i)
            i = j + 1
    return out


def weigh(rows, sigs, win=4, single=0.75, strong=1.5):
    out = []
    for x in rows:
        ki = KEYS.index(x["key"])
        lo = max(0, x["sig"] - win + 1)
        agree = bool((np.delete(sigs[:, lo:x["sig"] + 1], ki, axis=0) == x["d"]).any())
        out.append({**x, "r": x["r"] * (strong if agree else single)})
    return out


def yrs(s):
    return " / ".join(f"{s['y'][y]:+.0f}" for y in (2024, 2025, 2026))


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
    from goldbot.strategies.research import htf_trend
    ctx = dict(c=df.close.to_numpy(), atr=atr(df, 14).to_numpy(), opp=opp, trend=htf_trend(df, "1D", 50))
    sigs = np.stack([D["sig"][k] for k in KEYS])

    def full(rows):
        return stats(weigh(rows, sigs), idx)

    base = simulate(D, ctx)
    B = full(base)
    head = HEAD.replace("|---|---|---|---|---|---|---|---|---|", "|---|---|---|---|---|---|---|---|---|---|")
    head = head.replace("после 07.2025 |", "после 07.2025 | 2024 / 2025 / 2026 |", 1)

    def r(name, s):
        return row(name, s) + f" {yrs(s)} |"

    L = ["# Ещё три идеи для прибыли: проверка на истории", "",
         "Свечи XAUUSD M15 01.12.2023 – 21.08.2026. База — бот после PR #42 (фильтр ADX для пробоев, лот по согласию",
         "стратегий, 50 % на +1R, безубыток, тейк 3R, закрытие по встречному сигналу). Спред учтён, стоп и цель в одной",
         "свече — стоп. R — в рисках обычной сделки. Идея годится, только если помогает в каждом году и не увеличивает",
         "просадку заметно. Повторить: `python scripts/next_research.py`.", "",
         "## 1. Добавка к сделке, когда стоп уже в безубытке", "",
         "В момент фиксации 50 % на +1R бот открывает ещё одну сделку в ту же сторону; её стоп — цена входа основной",
         "(там же, где стоп остатка), выход — вместе с остатком (тейк, безубыток или разворот).",
         "Добавка 0.5 лота: если цена вернётся к входу, она потеряет ровно столько, сколько дала фиксация, — итог сделки 0.", "",
         head.format("Вариант"), r("**без добавки (как сейчас)**", B)]
    for a in (0.25, 0.5, 1.0):
        L.append(r(f"добавка {a:g} лота", full(simulate(D, ctx, Opt(add=a)))))

    L += ["", "## 2. Перезаход после выбивания в безубыток", "",
          "Остаток закрылся в безубыток — бот N свечей держит стоп-ордер на уровне фиксации (+1R от входа) в ту же",
          "сторону, если дневной тренд (EMA50) смотрит туда же; стоп — на прежнем расстоянии.", "",
          head.format("Вариант"), r("**без перезахода (как сейчас)**", B)]
    for nb in (4, 8, 16):
        rows = simulate(D, ctx, Opt(reentry_bars=nb))
        s = full(rows)
        rr = np.array([x["r"] for x in weigh(rows, sigs) if x["re"]])
        L.append(r(f"ждать {nb * 15 // 60 if nb >= 4 else nb} ч ({len(rr)} перезаходов, в среднем {rr.mean() if len(rr) else 0:+.2f}R)", s))

    L += ["", "## 3. Свой тейк для каждой стратегии", "",
          "Для каждой стратегии смотрим тейк 2R, 3R, 4R и 5R. Лучший выбираем по первой половине истории и проверяем,",
          "что он даёт во второй (её подбор «не видел»).", "",
          "| Стратегия | 2R | 3R | 4R | 5R | Лучший по 1-й половине | 2-я половина: 3R → лучший |", "|---|---|---|---|---|---|---|"]
    choice = {}
    first_mask = lambda rows: [x for x in rows if idx[x["i"]] < SPLIT]  # noqa: E731
    second_mask = lambda rows: [x for x in rows if idx[x["i"]] >= SPLIT]  # noqa: E731
    per = {}
    for t in (2, 3, 4, 5):
        rows = weigh(simulate(D, ctx, Opt(tp={k: float(t) for k in KEYS})), sigs)
        for k in KEYS:
            per[(k, t)] = [x for x in rows if x["key"] == k]
    for k in KEYS:
        a1 = {t: sum(x["r"] for x in first_mask(per[(k, t)])) for t in (2, 3, 4, 5)}
        a2 = {t: sum(x["r"] for x in second_mask(per[(k, t)])) for t in (2, 3, 4, 5)}
        best = max(a1, key=a1.get)
        choice[k] = float(best)
        cells = " | ".join(f"{a1[t]:+.0f} / {a2[t]:+.0f}" for t in (2, 3, 4, 5))
        L.append(f"| {k} | {cells} | {best}R | {a2[3]:+.0f}R → {a2[best]:+.0f}R |")
    L += ["", "В ячейках — итог в R: первая половина / вторая половина.", "",
          head.format("Вариант"), r("**3R у всех (как сейчас)**", B),
          r("тейки, выбранные по 1-й половине: " + ", ".join(f"{k} {v:g}R" for k, v in choice.items()),
            full(simulate(D, ctx, Opt(tp=choice))))]
    out = Path(__file__).resolve().parent.parent / "reports/next_research.md"
    out.write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
