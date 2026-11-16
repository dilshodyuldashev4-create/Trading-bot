"""Семь идей для прибыли: проверка на истории XAUUSD 12.2023–08.2026.

База — бот после этого обновления: 5 стратегий на M15, стоп 2 ATR, 50 % на +1R, безубыток, тейк 3R,
закрытие остатка по встречному сигналу, пробои (Squeeze и Дончиан) не входят при ADX(14) M15 ≥ 25.
Спред учтён, стоп и цель в одной свече — стоп. R — результат в рисках сделки (стоп = −1R).

1. Вход на откате лимитным ордером.
2. Выход по времени, если сделка не дошла до +1R.
3. Две стратегии согласны — риск ×2.
4. Плохие часы каждой стратегии (часы выбраны по первой половине истории, проверка на второй).
5. Фильтр дневного тренда для Дончиана и AMD.
6. Риск ×0.5 после серии стопов.
7. Подтверждение по индексу доллара — в истории бота нет котировок доллара, не проверялось.

    python scripts/profit_research.py     # отчёт в reports/profit_research.md
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
from goldbot.indicators import atr  # noqa: E402
from goldbot.strategies.research import htf_trend  # noqa: E402
from ideas_research import HEAD, SPLIT, adx, row, stats  # noqa: E402

BREAKOUTS = ("squeeze", "donchian")


@dataclass(frozen=True)
class Opt:
    limit_k: float = 0.0     # лимитный ордер на столько ATR лучше цены (0 — по рынку)
    limit_w: int = 0         # сколько свечей M15 ждать исполнения
    time_bars: int = 0       # закрыть, если за столько свечей не дошли до +1R (0 — нет)
    time_loss_only: bool = False  # закрывать по времени только сделку в минусе


def simulate(D, ctx, op: Opt = Opt()):
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
            if op.limit_k:
                px = o[i + 1] + (spr[i + 1] if d == 1 else 0.0) - d * op.limit_k * a[i]
                filled = None
                for q in range(i + 1, min(n, i + 1 + op.limit_w)):
                    reach = l[q] + spr[q] if d == 1 else h[q]   # покупка по ask, продажа по bid
                    if (reach - px) * d <= 0:
                        filled = q
                        break
                if filled is None:
                    i += 1 + op.limit_w
                    continue
                ent, e = filled, px
            else:
                e = o[ent] + (spr[ent] if d == 1 else 0.0)
            stop = e - d * dist
            tp = e + d * 3.0 * dist
            part_px = e + d * dist
            rest, res, part_done = 1.0, 0.0, False
            new_stop = None
            j = ent
            while j < n:
                if new_stop is not None:
                    stop, new_stop = new_stop, None
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
                if (good - tp) * d >= 0:
                    res += rest * (tp - e) * d / dist
                    break
                cl = c[j] + (spr[j] if d == -1 else 0.0)
                if part_done and (cl - e) * d > 0 and opp[j] == -d:
                    res += rest * (cl - e) * d / dist
                    break
                if op.time_bars and not part_done and j - ent + 1 >= op.time_bars \
                        and (not op.time_loss_only or (cl - e) * d < 0):
                    res += rest * (cl - e) * d / dist
                    break
                j += 1
            else:
                break
            out.append(dict(key=k, i=ent, j=j, d=d, r=res, sig=i))
            i = j + 1
    return out


def macro_section(base, idx, df):
    """Доллар и нефть: дневные цены (data/USD_index_daily.csv — индекс доллара по 6 валютам с весами DXY,
    data/WTI_daily.csv — нефть WTI). Бот может знать только вчерашнее закрытие, поэтому фильтры — по вчерашнему дню."""
    root = Path(__file__).resolve().parent.parent / "data"
    usd = pd.read_csv(root / "USD_index_daily.csv", parse_dates=["Date"]).set_index("Date")["USD_index"]
    oil = pd.read_csv(root / "WTI_daily.csv", parse_dates=["Date"]).set_index("Date")["Price"]
    oil = oil[oil > 0]
    gold = df.close.resample("1D").last().dropna()
    gold.index = gold.index.tz_localize(None) if gold.index.tz is not None else gold.index
    R = pd.DataFrame({"gold": gold.pct_change(), "usd": usd.pct_change(), "oil": oil.pct_change()}).dropna() * 100
    L = ["", "## 7. Доллар и нефть", "",
         "Дневные цены: индекс доллара (6 валют с весами DXY) и нефть WTI. Сначала — насколько золото вообще",
         "двигается вместе с ними, потом — помогает ли вчерашнее движение доллара или нефти сделкам бота сегодня.", "",
         "| Связь (дневные изменения) | Корреляция |", "|---|---|",
         f"| золото и доллар в тот же день | {R.gold.corr(R.usd):+.2f} |",
         f"| золото и нефть в тот же день | {R.gold.corr(R.oil):+.2f} |",
         f"| золото сегодня и доллар вчера | {R.gold.corr(R.usd.shift(1)):+.2f} |",
         f"| золото сегодня и нефть вчера | {R.gold.corr(R.oil.shift(1)):+.2f} |"]
    big = R[R.oil <= -3]
    L.append(f"| в дни, когда нефть упала на 3 % и больше ({len(big)} дн.): золото в среднем | {big.gold.mean():+.2f} % |")
    nxt = R.gold.shift(-1)[R.oil <= -3].dropna()
    L.append(f"| на следующий день после такого падения нефти: золото в среднем | {nxt.mean():+.2f} % "
             f"(рост в {100 * (nxt > 0).mean():.0f} % дней) |")
    L.append(f"| золото в среднем за любой день | {R.gold.mean():+.2f} % (рост в {100 * (R.gold > 0).mean():.0f} % дней) |")
    # вчерашнее изменение для каждой сделки
    days = idx[[x["i"] for x in base]].tz_localize(None).normalize() if idx.tz is not None else \
        idx[[x["i"] for x in base]].normalize()
    prev = lambda ser: ser.shift(0).reindex(pd.DatetimeIndex(days) - pd.Timedelta(days=1), method="ffill").to_numpy()  # noqa: E731
    du, do = prev(R.usd), prev(R.oil)
    do3 = prev(oil.pct_change(3) * 100)

    def keep(cond):
        return [x for x, c in zip(base, cond) if not c]
    B = stats(base, idx)
    L += ["", HEAD.format("Фильтр (по вчерашнему дню)"), row("**без фильтра**", B)]
    dd = np.array([x["d"] for x in base])
    for thr in (0.0, 0.3, 0.5):
        cond = ((dd == 1) & (du > thr)) | ((dd == -1) & (du < -thr))
        L.append(row(f"не покупать после роста доллара > {thr:g} %, не продавать после падения", stats(keep(cond), idx)))
    for thr in (2, 3):
        L.append(row(f"не продавать после падения нефти на {thr} %+", stats(keep((dd == -1) & (do <= -thr)), idx)))
        L.append(row(f"не покупать после роста нефти на {thr} %+", stats(keep((dd == 1) & (do >= thr)), idx)))
    L.append(row("не продавать после падения нефти на 5 %+ за 3 дня", stats(keep((dd == -1) & (do3 <= -5)), idx)))
    L += ["", "Средний результат сделок бота после резкого падения нефти накануне (≤ −2 %):", "",
          "| Сделки | Сколько | Средний результат |", "|---|---|---|"]
    for name, cond in (("покупки", (dd == 1) & (do <= -2)), ("продажи", (dd == -1) & (do <= -2)),
                       ("покупки, остальные дни", (dd == 1) & ~(do <= -2)),
                       ("продажи, остальные дни", (dd == -1) & ~(do <= -2))):
        r = np.array([x["r"] for x, c in zip(base, cond) if c])
        L.append(f"| {name} | {len(r)} | {r.mean() if len(r) else 0:+.3f}R |")
    return L


def weighted(rows, w):
    return [{**x, "r": x["r"] * w(x)} for x in rows]


def main():
    D0 = load()
    df = resample(load_mt5_csv(), "15min")
    idx = df.index
    ad = adx(df, 14)
    D = dict(D0)
    D["sig"] = dict(D0["sig"])
    for k in BREAKOUTS:
        D["sig"][k] = np.where(ad >= 25, 0, D0["sig"][k]).astype(np.int8)

    def ctx_for(DD):
        opp = np.zeros(len(df), dtype=int)
        for k in KEYS:
            opp = np.where(opp == 0, DD["sig"][k], opp)
        return dict(c=df.close.to_numpy(), atr=atr(df, 14).to_numpy(), opp=opp)

    ctx = ctx_for(D)
    base = simulate(D, ctx)
    B = stats(base, idx)
    L = ["# Семь идей для прибыли: проверка на истории", "",
         "Свечи XAUUSD M15 01.12.2023 – 21.08.2026. База — бот после обновления: 5 стратегий, 50 % на +1R,",
         "безубыток, тейк 3R, закрытие по встречному сигналу, пробои не входят при ADX ≥ 25. Спред учтён,",
         "стоп и цель в одной свече — стоп. R — результат в рисках сделки (стоп = −1R).",
         "Идея годится, только если помогает в обеих половинах истории (до и после 01.07.2025).",
         "Повторить: `python scripts/profit_research.py`.", ""]

    L += ["## 1. Вход на откате лимитным ордером", "",
          "Ордер на k ATR лучше цены сигнала; стоп на том же расстоянии от входа. Не исполнился за W свечей — сделки нет.", "",
          HEAD.format("Вариант"), row("**по рынку (как сейчас)**", B)]
    for k_, w in ((0.1, 2), (0.2, 2), (0.2, 4), (0.3, 4), (0.5, 4), (0.5, 8)):
        L.append(row(f"на {k_:g} ATR лучше, ждать {w} свечи ({w * 15} мин)",
                     stats(simulate(D, ctx, Opt(limit_k=k_, limit_w=w)), idx)))

    L += ["", "## 2. Выход по времени", "", "Сделка за N свечей M15 не дошла до +1R — закрыть по рынку.", "",
          HEAD.format("Вариант"), row("**без выхода по времени**", B)]
    for tb in (8, 16, 32, 64):
        L.append(row(f"через {tb * 15 // 60} ч", stats(simulate(D, ctx, Opt(time_bars=tb)), idx)))
        L.append(row(f"через {tb * 15 // 60} ч, только если в минусе",
                     stats(simulate(D, ctx, Opt(time_bars=tb, time_loss_only=True)), idx)))

    # 3. согласие двух стратегий
    sigs = np.stack([D["sig"][k] for k in KEYS])
    L += ["", "## 3. Две стратегии согласны — риск ×2", "",
          "Согласие — другая стратегия дала сигнал в ту же сторону за последние N свечей (включая эту).", "",
          "| Окно | Сделок с согласием | Их средний результат | Остальные | Итог при риске ×2 | Просадка | до / после 07.2025 |",
          "|---|---|---|---|---|---|---|"]
    for win in (1, 4, 8):
        def agree(x, win=win):
            ki = KEYS.index(x["key"])
            lo = max(0, x["sig"] - win + 1)
            other = np.delete(sigs[:, lo:x["sig"] + 1], ki, axis=0)
            return bool((other == x["d"]).any())
        flag = [agree(x) for x in base]
        ra = np.array([x["r"] for x, f in zip(base, flag) if f])
        rb = np.array([x["r"] for x, f in zip(base, flag) if not f])
        s2 = stats(weighted(base, lambda x, win=win: 2.0 if agree(x, win) else 1.0), idx)
        L.append(f"| {win} св. | {len(ra)} | {ra.mean():+.3f}R | {rb.mean():+.3f}R | {s2['tot']:+.0f}R "
                 f"(база {B['tot']:+.0f}R) | {s2['dd']:.0f}R (база {B['dd']:.0f}R) | {s2['a']:+.0f} / {s2['b']:+.0f} |")

    def agree4(x):
        ki = KEYS.index(x["key"])
        lo = max(0, x["sig"] - 3)
        return bool((np.delete(sigs[:, lo:x["sig"] + 1], ki, axis=0) == x["d"]).any())
    flag4 = {id(x): agree4(x) for x in base}
    L += ["", "Риск в зависимости от согласия (окно 4 свечи = 1 час):", "", HEAD.format("Риск: одиночный / с согласием"),
          row("**1 / 1 (как сейчас)**", B)]
    for ws, wc in ((1, 2), (1, 1.5), (0.75, 1.5), (0.75, 1.25)):
        L.append(row(f"{ws:g} / {wc:g}", stats(weighted(base, lambda x, ws=ws, wc=wc: wc if flag4[id(x)] else ws), idx)))

    # 4. плохие часы: выбор по первой половине, проверка на второй
    hr = idx.hour.to_numpy()
    t_ent = idx[[x["i"] for x in base]]
    first = t_ent < SPLIT
    L += ["", "## 4. Плохие часы каждой стратегии", "",
          "Для каждой стратегии берём часы (UTC), где в первой половине истории средний результат хуже порога",
          "и сделок не меньше 15, и смотрим, что даёт их пропуск во второй половине (её бот «не видел»).", ""]
    bad = {}
    for k in KEYS:
        rs = {}
        for x, f in zip(base, first):
            if f and x["key"] == k:
                rs.setdefault(hr[x["sig"]], []).append(x["r"])
        bad[k] = {h_ for h_, v in rs.items() if len(v) >= 15 and np.mean(v) < -0.15}
        L.append(f"* {k}: " + (", ".join(f"{h_}:00" for h_ in sorted(bad[k])) or "нет"))
    sec = [x for x, f in zip(base, first) if not f]
    kept = [x for x in sec if hr[x["sig"]] not in bad[x["key"]]]
    s_all, s_keep = stats(sec, idx), stats(kept, idx)
    skipped = np.array([x["r"] for x in sec if hr[x["sig"]] in bad[x["key"]]])
    L += ["", "| Вторая половина | Сделок | Итог | На сделку | Просадка |", "|---|---|---|---|---|",
          f"| все часы | {s_all['n']} | {s_all['tot']:+.0f}R | {s_all['avg']:+.3f}R | {s_all['dd']:.0f}R |",
          f"| без плохих часов | {s_keep['n']} | {s_keep['tot']:+.0f}R | {s_keep['avg']:+.3f}R | {s_keep['dd']:.0f}R |",
          f"| пропущенные сделки | {len(skipped)} | {skipped.sum():+.0f}R | "
          f"{skipped.mean() if len(skipped) else 0:+.3f}R | — |"]

    # 5. дневной тренд для Дончиана и AMD
    tr = htf_trend(df, "1D", 50)
    L += ["", "## 5. Фильтр дневного тренда (EMA50) для Дончиана и AMD", "", HEAD.format("Вариант"),
          row("**как сейчас (без фильтра у этих двух)**", B)]
    for keys in (("donchian",), ("amd",), ("donchian", "amd")):
        D5 = dict(D)
        D5["sig"] = dict(D["sig"])
        for k in keys:
            D5["sig"][k] = np.where(D["sig"][k] == tr, D["sig"][k], 0).astype(np.int8)
        L.append(row("фильтр для " + " и ".join(keys), stats(simulate(D5, ctx_for(D5)), idx)))

    # 6. риск ×0.5 после серии стопов
    L += ["", "## 6. Риск ×0.5 после серии стопов (до первой прибыльной сделки)", "", HEAD.format("Вариант"),
          row("**всегда обычный риск**", B)]
    for n_sl in (2, 3, 4):
        out = []
        # риск сделки определяется в момент входа: смотрим серию среди сделок, закрытых до входа
        exits = sorted(base, key=lambda x: x["j"])
        ex_j = np.array([x["j"] for x in exits])
        ex_r = np.array([x["r"] for x in exits])
        streaks = np.zeros(len(exits), dtype=int)
        cur = 0
        for q, r_ in enumerate(ex_r):
            cur = cur + 1 if r_ < -0.05 else (cur if abs(r_) <= 0.05 else 0)
            streaks[q] = cur
        for x in base:
            m = np.searchsorted(ex_j, x["i"]) - 1
            st_ = streaks[m] if m >= 0 else 0
            out.append({**x, "r": x["r"] * (0.5 if st_ >= n_sl else 1.0)})
        L.append(row(f"после {n_sl} стопов подряд", stats(out, idx)))

    L += macro_section(base, idx, df)

    # 8. пауза после резкого движения (заголовки, геополитика)
    a_prev = atr(df, 14).shift(1).to_numpy()
    body = (df.close - df.open).abs().to_numpy()
    rng = (df.high - df.low).to_numpy()
    L += ["", "## 8. Пауза после резкого движения (внезапные новости, геополитика)", "",
          "Свеча M15 намного больше обычной (тело или размах больше k ATR) — новых входов нет N минут.", "",
          HEAD.format("Вариант"), row("**без паузы**", B)]
    for name, arr in (("размах", rng), ("тело", body)):
        for k_, nb in ((2.5, 2), (3, 2), (3, 4), (4, 4)):
            shock = arr > k_ * a_prev
            blk = np.zeros(len(df), bool)
            for q in np.flatnonzero(shock):
                blk[q:q + nb] = True
            D8 = dict(D)
            D8["sig"] = {k: np.where(blk, 0, v).astype(np.int8) for k, v in D["sig"].items()}
            L.append(row(f"{name} > {k_:g} ATR — пауза {nb * 15} мин", stats(simulate(D8, ctx_for(D8)), idx)))
    out = Path(__file__).resolve().parent.parent / "reports/profit_research.md"
    out.write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
