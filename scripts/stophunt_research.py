"""Защита стопа от снятия ликвидности (stop hunt): проверка на истории XAUUSD 12.2023–08.2026.

5 стратегий бота (STRATEGY=all) на M15, у каждой одна сделка за раз, спред учтён, стоп и цель в одной свече —
считается стоп. Сопровождение как в боте: 50 % на +1R, остаток в безубыток, тейк остатка 3R.
R — результат в рисках сделки (стоп = −1R): риск на сделку одинаковый во всех вариантах, при более
широком стопе меньше лот.

Ликвидность — неснятый свинг-хай (для SELL) / свинг-лой (для BUY): фрактал 3 свечи M15, за последние 24 часа,
после него цена его ещё не пробивала.

    python scripts/stophunt_research.py     # отчёт в reports/stophunt_research.md
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
from goldbot.indicators import atr  # noqa: E402
from manage_research import swings  # noqa: E402

LOOK = 96          # 24 часа M15


@dataclass(frozen=True)
class V:
    name: str
    k_sl: float = 2.0          # стоп в ATR
    beyond: float = -1.0       # ≥0: стоп не ближе, чем за ликвидностью + beyond×ATR (только дальше, не ближе)
    swing_only: float = -1.0   # ≥0: стоп ровно за ликвидностью + столько ATR (1–4 ATR), без ликвидности — 2 ATR
    skip_near: float = 0.0     # >0: пропуск, если ликвидность лежит в пределах ±skip_near ATR от стопа
    sweep: int = 0             # >0: ждать снятия ликвидности до стольких свечей, вход после возврата под/над уровень
    sweep_need: bool = False   # True: без ликвидности рядом сигнал пропускается; False — вход сразу
    limit: int = 0             # >0: лимитный ордер у ликвидности (уровень − 0.1 ATR), живёт столько свечей
    max_r: float = 4.0         # стоп дальше стольких ATR — сделка пропускается
    sweep_stop: float = 0.5    # стоп после снятия: за хвостом снятия + столько ATR; <0 — 2 ATR от нового входа
    sweep_zone: bool = False   # ждать снятия, только если ликвидность между входом и стопом (там, где выбивают)
    fallback: bool = False     # True: ликвидность слишком далеко (стоп > max_r ATR) — обычный стоп, без пропуска


def liquidity(i, d, e, h, l, sh, swl, look=LOOK):
    """Ближайший неснятый свинг против сделки (выше входа для SELL, ниже для BUY), известный на свече i."""
    lo = max(0, i - look)
    if d == -1:
        best = None
        for k in range(i, lo, -1):
            v = sh[k]
            if np.isnan(v) or v <= e:
                continue
            if h[k - 2:i + 1].max() > v + 1e-9:   # уже пробит (вершина на k-3, известна на k)
                continue
            if best is None or v < best:
                best = v
        return best
    best = None
    for k in range(i, lo, -1):
        v = swl[k]
        if np.isnan(v) or v >= e:
            continue
        if l[k - 2:i + 1].min() < v - 1e-9:
            continue
        if best is None or v > best:
            best = v
    return best


def manage(o, h, l, spr, j0, d, e, stop, n):
    """Сопровождение как в боте: 50% на +1R, остаток в безубыток, тейк 3R. Возвращает (R, последняя свеча, был ли полный стоп)."""
    dist = abs(e - stop)
    tp = e + d * 3 * dist
    part_px = e + d * dist
    rest, res, part_done, new_stop = 1.0, 0.0, False, None
    j = j0
    while j < n:
        if new_stop is not None:
            stop, new_stop = new_stop, None
        bad = l[j] if d == 1 else h[j] + spr[j]
        good = h[j] if d == 1 else l[j] + spr[j]
        if (bad - stop) * d <= 0:
            res += rest * (stop - e) * d / dist
            return res, j, not part_done
        if not part_done and (good - part_px) * d >= 0:
            res += 0.5 * (part_px - e) * d / dist
            rest, part_done = 0.5, True
            new_stop = e + d * spr[j]
        if (good - tp) * d >= 0:
            res += rest * (tp - e) * d / dist
            return res, j, False
        j += 1
    return None


def run(D, A, sh, swl, v: V, diag=None):
    o, h, l, c, spr = D["o"], D["h"], D["l"], D["c"], D["spr"]
    n = len(o)
    out = []
    for key in KEYS:
        s = D["sig"][key]
        i = 0
        while i < n - 2:
            d = int(s[i])
            if d == 0:
                i += 1
                continue
            a = A[i]
            e = o[i + 1] + (spr[i + 1] if d == 1 else 0.0)
            j0 = i + 1
            liq = liquidity(i, d, e, h, l, sh, swl)
            stop = e - d * D["sl"][i] * PIP * v.k_sl / 2   # как в боте: 2 ATR в пипсах, не меньше 50
            if v.beyond >= 0 and liq is not None:
                cand = liq + v.beyond * a if d == -1 else liq - v.beyond * a
                if (stop - cand) * d > 0 and not (v.fallback and abs(e - cand) > v.max_r * a):
                    stop = cand      # ликвидность + запас дальше стопа — стоп туда
            if v.swing_only >= 0 and liq is not None:
                cand = liq + v.swing_only * a if d == -1 else liq - v.swing_only * a
                dist = abs(e - cand)
                stop = e - d * min(max(dist, 1.0 * a), 4.0 * a)
            if v.skip_near > 0 and liq is not None and abs(liq - stop) <= v.skip_near * a:
                i += 1
                continue
            if v.sweep:
                far = 3 * a if not v.sweep_zone else abs(e - stop)
                if liq is None or abs(liq - e) > far:
                    if v.sweep_need:
                        i += 1
                        continue
                else:
                    got = None
                    ext = None
                    for j in range(i + 1, min(n - 1, i + 1 + v.sweep)):
                        ext = h[j] if d == -1 else l[j]
                        if (ext - liq) * -d > 0:   # уровень снят
                            if (c[j] - liq) * -d < 0:   # и свеча закрылась обратно
                                got = j
                            break
                    if got is None:
                        i += 1
                        continue
                    wick = h[i + 1:got + 1].max() if d == -1 else l[i + 1:got + 1].min()
                    e = o[got + 1] + (spr[got + 1] if d == 1 else 0.0)
                    ss = v.sweep_stop
                    stop = wick + ss * A[got] if d == -1 else wick - ss * A[got]
                    if ss < 0:
                        stop = e - d * 2 * A[got]
                    if abs(e - stop) < 1.0 * A[got]:
                        stop = e - d * 1.0 * A[got]
                    j0 = got + 1
            if v.limit:
                if liq is None or abs(liq - e) > 2 * a:
                    i += 1
                    continue
                px = liq - 0.1 * a if d == -1 else liq + 0.1 * a
                got = None
                for j in range(i + 1, min(n - 1, i + 1 + v.limit)):
                    if (h[j] >= px) if d == -1 else (l[j] + spr[j] <= px):
                        got = j
                        break
                if got is None:
                    i += 1
                    continue
                e = px
                stop = e - d * v.k_sl * a
                j0 = got   # стоп проверяется уже на свече заполнения
            if abs(e - stop) > v.max_r * a:
                i += 1
                continue
            r = manage(o, h, l, spr, j0, d, e, stop, n)
            if r is None:
                break
            res, j, full_sl = r
            out.append((D["idx"][i], res))
            if diag is not None and full_sl:
                # «выбили и ушли»: после стопа за 24 часа цена дошла до тейка 3R
                tp = e + d * 3 * abs(e - stop)
                seg = l[j + 1:j + 97] if d == -1 else h[j + 1:j + 97]
                diag.append(bool(len(seg) and ((seg - tp) * d >= 0).any()))
            i = j + 1
    return out


def stats(rows, lo=None, hi=None):
    r = np.array([x[1] for x in rows if (lo is None or x[0] >= lo) and (hi is None or x[0] < hi)])
    if not len(r):
        return dict(n=0, win=0, tot=0, dd=0, avg=0)
    eq = np.cumsum(r)
    dd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    return dict(n=len(r), win=100 * (r > 0.05).mean(), tot=r.sum(), dd=dd, avg=r.mean())


def main():
    import pandas as pd
    D = load()
    df = resample(load_mt5_csv(), "15min")
    D["c"] = df.close.to_numpy()
    A = atr(df, 14).to_numpy()
    sh, swl = swings(df.high.to_numpy(), df.low.to_numpy())
    cut = pd.Timestamp("2025-04-01")
    vs = [
        V("**Сейчас в боте: стоп 2 ATR**"),
        V("Стоп шире: 2.5 ATR", k_sl=2.5),
        V("Стоп шире: 3 ATR", k_sl=3.0),
        V("Стоп за ликвидностью + 0.25 ATR (не ближе 2 ATR)", beyond=0.25),
        V("Стоп за ликвидностью + 0.5 ATR (не ближе 2 ATR)", beyond=0.5),
        V("Стоп за ликвидностью + 0.5 ATR, если до 3 ATR, иначе 2 ATR", beyond=0.5, max_r=3, fallback=True),
        V("Стоп за ликвидностью + 0.5 ATR, если до 4 ATR, иначе 2 ATR", beyond=0.5, fallback=True),
        V("Стоп 2.5 ATR, за ликвидностью + 0.5 ATR, если до 4 ATR", k_sl=2.5, beyond=0.5, fallback=True),
        V("Стоп шире: 2.25 ATR", k_sl=2.25),
        V("Стоп шире: 2.75 ATR", k_sl=2.75),
        V("Стоп за ликвидностью + 1 ATR (не ближе 2 ATR)", beyond=1.0),
        V("Стоп ровно за ликвидностью + 0.5 ATR (1–4 ATR)", swing_only=0.5),
        V("Пропуск, если ликвидность в ±0.5 ATR от стопа", skip_near=0.5),
        V("Пропуск, если ликвидность в ±1 ATR от стопа", skip_near=1.0),
        V("Ждать снятия ликвидности (до 2 ч), без ликвидности — вход сразу", sweep=8),
        V("Ждать снятия ликвидности (до 4 ч), без ликвидности — вход сразу", sweep=16),
        V("Ждать снятия (до 4 ч), стоп за хвостом + 0.25 ATR", sweep=16, sweep_stop=0.25),
        V("Ждать снятия (до 4 ч), стоп 2 ATR от нового входа", sweep=16, sweep_stop=-1),
        V("Ждать снятия, только если ликвидность внутри стопа (до 4 ч)", sweep=16, sweep_zone=True),
        V("Ждать снятия, только если ликвидность внутри стопа, стоп 2 ATR от входа", sweep=16, sweep_zone=True,
          sweep_stop=-1),
        V("Только после снятия ликвидности (до 4 ч), иначе пропуск", sweep=16, sweep_need=True),
        V("Лимитный ордер у ликвидности (до 2 ч), стоп 2 ATR", limit=8),
        V("Лимитный ордер у ликвидности (до 4 ч), стоп 2 ATR", limit=16),
    ]
    head = ("| Вариант | Сделок | В плюсе | Итог | Ср. на сделку | Макс. просадка "
            "| 12.2023–03.2025 | 04.2025–08.2026 |\n|---|---|---|---|---|---|---|---|")
    lines = ["# Защита стопа от снятия ликвидности: проверка на истории", "",
             "Свечи XAUUSD M15 01.12.2023 – 21.08.2026 (MetaTrader 5, спред учтён), 5 стратегий бота, у каждой одна",
             "сделка за раз. Сопровождение как в боте: 50 % на +1R, остаток в безубыток, тейк 3R. Стоп и цель в одной",
             "свече — считается стоп. R — результат в рисках сделки: риск одинаковый, при широком стопе меньше лот.",
             "Ликвидность — ближайший неснятый свинг-хай (для SELL) или свинг-лой (для BUY) за последние 24 часа.",
             "Два периода (примерно по 16 месяцев) — проверка, что улучшение не случайно. В ячейке периода: итог и",
             "среднее на сделку. Повторить: `python scripts/stophunt_research.py`.", "", head]
    for v in vs:
        rows = run(D, A, sh, swl, v)
        x, p1, p2 = stats(rows), stats(rows, hi=cut), stats(rows, lo=cut)
        lines.append(f"| {v.name} | {x['n']} | {x['win']:.0f}% | {x['tot']:+.0f}R | {x['avg']:+.3f}R | {x['dd']:.0f}R "
                     f"| {p1['tot']:+.0f}R ({p1['avg']:+.3f}) | {p2['tot']:+.0f}R ({p2['avg']:+.3f}) |")
        print(lines[-1], flush=True)
    diag = []
    rows = run(D, A, sh, swl, V(""), diag)
    lines += ["", "## Как часто стоп «выбивают, и цена уходит в нашу сторону»", "",
              f"Полных стопов в текущем боте: {len(diag)}. Из них после стопа цена за 24 часа дошла до тейка 3R: "
              f"{sum(diag)} ({100 * np.mean(diag):.0f}%).", ""]
    out = Path(__file__).resolve().parent.parent / "reports/stophunt_research.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[-3:]))


if __name__ == "__main__":
    main()
