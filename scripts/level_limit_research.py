"""Лимитные ордера на уровнях с несколькими касаниями (поддержка / сопротивление, где цена разворачивалась
3+ раза), по дневному тренду, с объёмом брокера — как 11-я стратегия поверх бота после PR 87.

Уровень: развороты H1 (пивот 3/3) за последние W часов, сгруппированные в зону ±tol·ATR(H1); касаний ≥ T.
Покупка: дневной тренд вверх, уровень ниже цены (поддержка), свеча M15 опустилась до уровня — лимит исполнен
по уровню (с учётом спреда). Продажа — зеркально. Сопровождение как в боте: стоп 2 ATR, 50 % на +1R,
безубыток, тейк 3R. В свече исполнения задет стоп — стоп.

    python scripts/level_limit_research.py
"""
from __future__ import annotations
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(Path(__file__).resolve().parent))
warnings.filterwarnings("ignore")
import edge_research as X
from goldbot.data import PIP
from goldbot.indicators import atr
from goldbot.strategies.research import htf_trend


def levels_entries(df, D, W=120, T=3, tol=0.25, vol_min=0.0, piv=3):
    """Список (бар исполнения, направление, цена входа) — лимит у уровня."""
    h1 = df.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    a1 = atr(h1, 14).to_numpy()
    hi, lo, vv = h1.high.to_numpy(), h1.low.to_numpy(), h1.volume.to_numpy().astype(float)
    vavg = pd.Series(vv).rolling(100).mean().to_numpy()
    n = len(h1)
    ph = np.zeros(n, bool); pl = np.zeros(n, bool)
    for i in range(piv, n - piv):
        ph[i] = hi[i] == hi[i - piv:i + piv + 1].max()
        pl[i] = lo[i] == lo[i - piv:i + piv + 1].min()
    # на час t известны пивоты с индексом ≤ t - piv
    trend = htf_trend(df, "1D", 50)
    h1_idx = h1.index
    pos = h1_idx.searchsorted(df.index, side="right") - 1   # текущий незакрытый час M15-бара
    o, h, l, spr = D["o"], D["h"], D["l"], D["spr"]
    out = []
    cache = {}
    for i in range(len(df)):
        t = pos[i] - 1          # последний закрытый час
        if t < W or np.isnan(a1[t]):
            continue
        if t not in cache:
            lo_t = t - W
            pts = [(hi[k], vv[k] / vavg[k] if vavg[k] > 0 else 1) for k in range(lo_t, t - piv + 1) if ph[k]]
            pts += [(lo[k], vv[k] / vavg[k] if vavg[k] > 0 else 1) for k in range(lo_t, t - piv + 1) if pl[k]]
            pts.sort()
            lv = []
            z = tol * a1[t]
            j = 0
            while j < len(pts):
                g = [pts[j]]
                while j + 1 < len(pts) and pts[j + 1][0] - g[0][0] <= 2 * z:
                    j += 1; g.append(pts[j])
                if len(g) >= T and np.mean([x[1] for x in g]) >= vol_min:
                    lv.append(float(np.mean([x[0] for x in g])))
                j += 1
            cache[t] = lv
        d = int(trend[i])
        if d == 0 or not cache[t]:
            continue
        prev_close = o[i]
        for L in cache[t]:
            if d == 1 and prev_close > L and l[i] + spr[i] <= L:      # ask дошёл до поддержки сверху
                out.append((i, 1, L)); break
            if d == -1 and prev_close < L and h[i] >= L:               # bid дошёл до сопротивления снизу
                out.append((i, -1, L)); break
    return out


def manage(entries, D, df, tp_r=3.0):
    """Сделки (по одной за раз) с сопровождением бота; формат как у X.sim."""
    o, h, l, spr = D["o"], D["h"], D["l"], D["spr"]
    c = df.close.to_numpy()
    n = len(o); res_list = []; busy = -1
    for (i, d, e) in entries:
        if i <= busy:
            continue
        dist = D["sl"][i - 1] * PIP
        stop, tp, part_px = e - d * dist, e + d * tp_r * dist, e + d * dist
        rest, res, part_done = 1.0, 0.0, False
        j = i
        # свеча исполнения: стоп задет — стоп
        bad = l[i] if d == 1 else h[i] + spr[i]
        if (bad - stop) * d <= 0:
            res_list.append(dict(key="lvl", i=i, j=i, d=d, r=-1.0, sig=i - 1, dist=dist)); busy = i; continue
        j = i + 1; new_stop = None
        while j < n:
            if new_stop is not None:
                stop, new_stop = new_stop, None
            bad = l[j] if d == 1 else h[j] + spr[j]
            good = h[j] if d == 1 else l[j] + spr[j]
            if (bad - stop) * d <= 0:
                res += rest * (stop - e) * d / dist; break
            if not part_done and (good - part_px) * d >= 0:
                res += 0.5 * (part_px - e) * d / dist; rest -= 0.5; part_done = True; new_stop = e + d * spr[j]
            if (good - tp) * d >= 0:
                res += rest * (tp - e) * d / dist; break
            j += 1
        else:
            break
        res_list.append(dict(key="lvl", i=i, j=j, d=d, r=res, sig=i - 1, dist=dist)); busy = j
    return res_list


def main():
    real, _ = X.load_all()
    D, df, *_ = real
    split = pd.Timestamp("2025-07-01")
    print("| Окно, ч | Касаний | Зона, ATR H1 | Объём у касаний ≥ | Сделок | В плюсе | Итог | На сделку | до 07.2025 | после 07.2025 | Стресс +0.30 $ |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for W, T, tol, vm in ((120, 3, 0.25, 0), (120, 4, 0.25, 0), (72, 3, 0.25, 0), (240, 3, 0.25, 0),
                          (120, 3, 0.15, 0), (120, 2, 0.25, 0), (120, 3, 0.25, 1.2), (240, 4, 0.25, 1.0)):
        tr = manage(levels_entries(df, D, W, T, tol, vm), D, df)
        r = np.array([x["r"] for x in tr]); f = np.array([df.index[x["i"]] < split for x in tr])
        rs = r - np.array([0.3 / x["dist"] for x in tr])
        print(f"| {W} | {T} | {tol} | {vm or '—'} | {len(tr)} | {(r > 0).mean():.0%} | {r.sum():+.1f}R | {r.mean():+.3f}R "
              f"| {r[f].sum():+.1f}R | {r[~f].sum():+.1f}R | {rs.sum():+.1f}R |", flush=True)


if __name__ == "__main__":
    main()
