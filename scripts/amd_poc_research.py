"""Бэктест стратегии из видео: «Накопление → Манипуляция → Распределение» + POC.

Правила (как в видео):
1. Накопление: боковик из N свечей, высота диапазона <= K * ATR14 (ATR до начала боковика).
2. Фиксированный профиль объёма на боковике (тиковый объём) -> POC.
3. Манипуляция: цена снимает ликвидность под минимумом боковика (для BUY) и разворачивается.
   Если ушла ниже минимума больше чем на 1 высоту боковика — это пробой, сетап отменён.
4. Цена закрывается выше POC, но мы не догоняем — ждём ретест POC сверху
   (свеча касается POC и закрывается выше него бычьей свечой) -> BUY по open следующей свечи.
5. Стоп под минимумом манипуляции, цель — максимум боковика (вариант: фиксированный 1:2 / 1:3).
   SELL — зеркально. Сетап живёт не дольше M свечей после боковика.

Исполнение как в goldbot/backtest.py: BUY по ask, выходы по bid/ask, спред учтён,
одна сделка за раз, если в свече задеты SL и TP — стоп.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from goldbot.data import PIP, load_mt5_csv, resample  # noqa: E402


def atr(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean().to_numpy()


def poc_of(h, l, v, bins=30):
    lo, hi = l.min(), h.max()
    edges = np.linspace(lo, hi, bins + 1)
    prof = np.zeros(bins)
    for a, b, vol in zip(l, h, v):
        i0 = min(int((a - lo) / (hi - lo) * bins), bins - 1)
        i1 = min(int((b - lo) / (hi - lo) * bins), bins - 1)
        prof[i0:i1 + 1] += vol / (i1 - i0 + 1)
    k = prof.argmax()
    return (edges[k] + edges[k + 1]) / 2


def run(df, N=24, K=3.0, M=48, target="range", min_rr=1.0, max_depth=1.0, fixed=None):
    o, h, l, c, v, s = (df[k].to_numpy() for k in ("open", "high", "low", "close", "volume", "spread"))
    a = atr(df)
    idx = df.index
    n = len(df)
    trades = []
    i = N + 15
    while i < n - 2:
        # 1. боковик на свечах [i-N+1, i]
        H = h[i - N + 1:i + 1].max(); L = l[i - N + 1:i + 1].min()
        base = a[i - N]
        if not (base > 0 and H - L <= K * base):
            i += 1; continue
        P = poc_of(h[i - N + 1:i + 1], l[i - N + 1:i + 1], v[i - N + 1:i + 1])
        hgt = H - L
        d = 0; ext = None; broke = False; sig = None
        j = i + 1
        end = min(n - 2, i + M)
        while j <= end:
            if d == 0:
                if l[j] < L and h[j] > H:
                    break  # обе стороны сразу — неясно
                if l[j] < L: d = 1; ext = l[j]
                elif h[j] > H: d = -1; ext = h[j]
                else:
                    j += 1; continue
            # манипуляция идёт
            if d == 1:
                ext = min(ext, l[j])
                if ext < L - max_depth * hgt or h[j] >= H: break
                if not broke:
                    if c[j] > P: broke = True
                elif l[j] <= P and c[j] > P and c[j] > o[j]:
                    sig = j; break
            else:
                ext = max(ext, h[j])
                if ext > H + max_depth * hgt or l[j] <= L: break
                if not broke:
                    if c[j] < P: broke = True
                elif h[j] >= P and c[j] < P and c[j] < o[j]:
                    sig = j; break
            j += 1
        if sig is None:
            i = max(j, i + 1); continue
        e = sig + 1
        entry = o[e] + (s[e] if d == 1 else 0.0)
        sl = ext - d * s[e]
        if fixed:
            sl = entry - d * fixed[0] * PIP
        risk = (entry - sl) * d
        if risk <= 0:
            i = e; continue
        if target == "range":
            tp = H if d == 1 else L + s[e]
        else:
            tp = entry + d * float(target) * risk
        rr = (tp - entry) * d / risk
        if rr < min_rr:
            i = e; continue
        k = e; res = None
        while k < n:
            hi = h[k] + (s[k] if d == -1 else 0.0); lo = l[k] + (s[k] if d == -1 else 0.0)
            hs = lo <= sl if d == 1 else hi >= sl
            ht = hi >= tp if d == 1 else lo <= tp
            if hs or ht:
                res = "SL" if hs else "TP"; break
            k += 1
        if res is None:
            break
        R = -1.0 if res == "SL" else rr
        trades.append(dict(time=idx[e], dir=d, entry=entry, sl=sl, tp=tp, rr=rr, res=res, R=R,
                           pips=R * risk / PIP, risk_pips=risk / PIP))
        i = k + 1
    return pd.DataFrame(trades)


def stats(t):
    if t.empty:
        return dict(n=0)
    eq = t["R"].cumsum().to_numpy()
    dd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
    g = t.loc[t.R > 0, "R"].sum(); lo = -t.loc[t.R < 0, "R"].sum()
    out = dict(n=len(t), wr=100 * (t.res == "TP").mean(), R=t.R.sum(), pf=g / lo if lo else np.inf,
               ddR=dd, avg_rr=t.rr.mean(), risk=t.risk_pips.median(), pips=t.pips.sum())
    for y in (2024, 2025, 2026):
        ty = t[t.time.dt.year == y]
        out[str(y)] = f"{len(ty)} / {100*(ty.res=='TP').mean():.0f}% / {ty.R.sum():+.1f}R" if len(ty) else "-"
    return out


if __name__ == "__main__":
    df5 = load_mt5_csv()
    rows = []
    for tf in ("5min", "15min", "1h"):
        df = resample(df5, tf)
        for N in (20, 30, 48):
            for K in (2.5, 3.5):
                for tgt in ("range", 2.0, 3.0):
                    t = run(df, N=N, K=K, M=N * 2, target=tgt)
                    st = stats(t)
                    rows.append(dict(tf=tf, N=N, K=K, tgt=tgt, **st))
                    print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv(Path(__file__).with_name("amd_poc_grid.csv"), index=False)
