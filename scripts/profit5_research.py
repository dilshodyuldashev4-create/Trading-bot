"""Третья волна индикаторов поверх бота с 9 стратегиями (после PR 66: + KAMA H4). Каждый — 10-я стратегия,
по дневному тренду, по две настройки. Проверка как в profit4_research.py.

    python scripts/profit5_research.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
warnings.filterwarnings("ignore")

import challenge_research as C  # noqa: E402
import day_guard_research as G  # noqa: E402
import indicator_research as R  # noqa: E402
import profit2_research as Q  # noqa: E402
import profit3_research as P3  # noqa: E402
from profit4_research import H, cross_up, sig  # noqa: E402
from goldbot.data import load_mt5_csv, resample  # noqa: E402
from goldbot.indicators import atr, ema  # noqa: E402
from goldbot.strategies.popular import days_breakout, kama_h4  # noqa: E402

SLIP = R.SLIP


def extras(df):
    return {**P3.extras(df), "kama_h4": P3.trend(df, kama_h4(df))}


def wma(s, n):
    w = np.arange(1, n + 1)
    return s.rolling(n).apply(lambda v: np.dot(v, w) / w.sum(), raw=True)


def ma_cross(kind, n):
    """Цена закрылась выше / ниже скользящей kind(n)."""
    def f(x):
        c = x.close
        if kind == "zlema":
            lag = (n - 1) // 2
            m = ema(2 * c - c.shift(lag), n)
        elif kind == "tema":
            e1 = ema(c, n); e2 = ema(e1, n); e3 = ema(e2, n)
            m = 3 * e1 - 3 * e2 + e3
        elif kind == "mcginley":
            v = c.to_numpy(); out = np.full(len(v), np.nan); out[0] = v[0]
            for i in range(1, len(v)):
                out[i] = out[i - 1] + (v[i] - out[i - 1]) / (n * (v[i] / out[i - 1]) ** 4)
            m = pd.Series(out, index=c.index)
        elif kind == "vidya":
            d = c.diff()
            up, dn = d.clip(lower=0).rolling(9).sum(), (-d.clip(upper=0)).rolling(9).sum()
            cmo = ((up - dn) / (up + dn)).abs().fillna(0).to_numpy()
            a = 2 / (n + 1); v = c.to_numpy(); out = np.full(len(v), np.nan); out[0] = v[0]
            for i in range(1, len(v)):
                out[i] = a * cmo[i] * v[i] + (1 - a * cmo[i]) * out[i - 1]
            m = pd.Series(out, index=c.index)
        elif kind == "t3":
            b = 0.7
            e = [c]
            for _ in range(6):
                e.append(ema(e[-1], n))
            c1, c2, c3, c4 = -b ** 3, 3 * b ** 2 + 3 * b ** 3, -6 * b ** 2 - 3 * b - 3 * b ** 3, 1 + 3 * b + b ** 3 + 3 * b ** 2
            m = c1 * e[6] + c2 * e[5] + c3 * e[4] + c4 * e[3]
        elif kind == "alma":
            off, sg = 0.85, 6
            mm = off * (n - 1); s = n / sg
            w = np.exp(-((np.arange(n) - mm) ** 2) / (2 * s * s)); w /= w.sum()
            m = c.rolling(n).apply(lambda v: np.dot(v, w), raw=True)
        return sig(c > m, c < m)
    return f


def heikin(x):
    ha_c = (x.open + x.high + x.low + x.close) / 4
    o = np.empty(len(x)); o[0] = (x.open.iloc[0] + x.close.iloc[0]) / 2
    hc = ha_c.to_numpy()
    for i in range(1, len(x)):
        o[i] = (o[i - 1] + hc[i - 1]) / 2
    return sig(hc > o, hc < o)


def elder_impulse(x):
    e = ema(x.close, 13)
    m = ema(x.close, 12) - ema(x.close, 26)
    h = m - ema(m, 9)
    return sig((e.diff() > 0) & (h.diff() > 0), (e.diff() < 0) & (h.diff() < 0))


def schaff(n_fast=23, n_slow=50, cyc=10):
    def f(x):
        m = ema(x.close, n_fast) - ema(x.close, n_slow)
        def stoch(s):
            lo, hi = s.rolling(cyc).min(), s.rolling(cyc).max()
            return (100 * (s - lo) / (hi - lo).replace(0, np.nan)).ffill()
        k = ema(stoch(m), 3)
        st = ema(stoch(k), 3)
        return sig(cross_up(st, pd.Series(25, index=x.index)), cross_up(pd.Series(75, index=x.index), st))
    return f


def fisher(n):
    def f(x):
        m = (x.high + x.low) / 2
        lo, hi = m.rolling(n).min(), m.rolling(n).max()
        v = (2 * ((m - lo) / (hi - lo).replace(0, np.nan) - 0.5)).clip(-0.999, 0.999).fillna(0)
        v = v.ewm(alpha=0.33, adjust=False).mean().clip(-0.999, 0.999)
        fi = 0.5 * np.log((1 + v) / (1 - v))
        fi = fi.ewm(alpha=0.5, adjust=False).mean()
        return sig(cross_up(fi, fi.shift()) & (fi < -1), cross_up(fi.shift(), fi) & (fi > 1))
    return f


def cmo(n):
    def f(x):
        d = x.close.diff()
        up, dn = d.clip(lower=0).rolling(n).sum(), (-d.clip(upper=0)).rolling(n).sum()
        c = 100 * (up - dn) / (up + dn)
        return sig(c > 0, c < 0)
    return f


def klinger(x):
    tp = x.high + x.low + x.close
    t = np.sign(tp.diff()).fillna(0)
    vf = x.volume * t
    kvo = ema(vf, 34) - ema(vf, 55)
    s = ema(kvo, 13)
    return sig(kvo > s, kvo < s)


def cmf(n):
    def f(x):
        mfm = ((x.close - x.low) - (x.high - x.close)) / (x.high - x.low).replace(0, np.nan)
        v = (mfm.fillna(0) * x.volume).rolling(n).sum() / x.volume.rolling(n).sum()
        return sig(v > 0.05, v < -0.05)
    return f


def boll_break(n, k):
    def f(x):
        m, sd = x.close.rolling(n).mean(), x.close.rolling(n).std()
        return sig(x.close > m + k * sd, x.close < m - k * sd)
    return f


def atr_trail(n, k):
    """Chandelier: цена закрылась выше максимума n свечей − k ATR после того, как была ниже (и наоборот)."""
    def f(x):
        a = atr(x, n)
        long_stop = x.high.rolling(n).max() - k * a
        short_stop = x.low.rolling(n).min() + k * a
        c = x.close.to_numpy(); ls = long_stop.to_numpy(); ss = short_stop.to_numpy()
        d = np.zeros(len(c), dtype=int)
        for i in range(1, len(c)):
            d[i] = 1 if c[i] > ss[i - 1] else -1 if c[i] < ls[i - 1] else d[i - 1]
        return sig(d == 1, d == -1)
    return f


def ultimate(lo):
    def f(x):
        pc = x.close.shift()
        bp = x.close - np.minimum(x.low, pc)
        tr = np.maximum(x.high, pc) - np.minimum(x.low, pc)
        av = lambda n: bp.rolling(n).sum() / tr.rolling(n).sum()  # noqa: E731
        uo = 100 * (4 * av(7) + 2 * av(14) + av(28)) / 7
        return sig(cross_up(uo, pd.Series(lo, index=x.index)), cross_up(pd.Series(100 - lo, index=x.index), uo))
    return f


def weekly_vwap(df):
    """Цена закрылась выше / ниже недельного VWAP (тиковый объём), первое пересечение — на M15."""
    wk = df.index.to_period("W")
    tp = (df.high + df.low + df.close) / 3
    pv = (tp * df.volume).groupby(wk).cumsum()
    vv = df.volume.groupby(wk).cumsum()
    vw = pv / vv
    return R.once_per_day(sig(df.close > vw, df.close < vw), df.index)


def coppock_d(x):
    r = x.close.pct_change(14) * 100 + x.close.pct_change(11) * 100
    cp = wma(r, 10)
    return sig(cp > 0, cp < 0)


CANDS = [
    ("ZLEMA H4 (20)", H("4h", ma_cross("zlema", 20))), ("ZLEMA H4 (34)", H("4h", ma_cross("zlema", 34))),
    ("TEMA H4 (20)", H("4h", ma_cross("tema", 20))), ("TEMA H4 (34)", H("4h", ma_cross("tema", 34))),
    ("McGinley Dynamic H4 (14)", H("4h", ma_cross("mcginley", 14))), ("McGinley H4 (21)", H("4h", ma_cross("mcginley", 21))),
    ("VIDYA H4 (14)", H("4h", ma_cross("vidya", 14))), ("VIDYA H4 (21)", H("4h", ma_cross("vidya", 21))),
    ("T3 Тилсона H4 (5)", H("4h", ma_cross("t3", 5))), ("T3 H4 (8)", H("4h", ma_cross("t3", 8))),
    ("ALMA H4 (21)", H("4h", ma_cross("alma", 21))), ("ALMA H4 (34)", H("4h", ma_cross("alma", 34))),
    ("Heikin-Ashi H4 смена цвета", H("4h", heikin)), ("Heikin-Ashi H2", H("2h", heikin)),
    ("Импульс Элдера H4", H("4h", elder_impulse)), ("Импульс Элдера H1", H("1h", elder_impulse)),
    ("Schaff Trend Cycle H4", H("4h", schaff())), ("Schaff Trend Cycle H1", H("1h", schaff())),
    ("Fisher Transform H4 разворот (10)", H("4h", fisher(10))), ("Fisher H1 (10)", H("1h", fisher(10))),
    ("Chande Momentum H4 (14)", H("4h", cmo(14))), ("Chande Momentum H4 (9)", H("4h", cmo(9))),
    ("Klinger Volume H4", H("4h", klinger)), ("Klinger Volume H1", H("1h", klinger)),
    ("Chaikin Money Flow H4 (20)", H("4h", cmf(20))), ("Chaikin Money Flow H1 (20)", H("1h", cmf(20))),
    ("Пробой Боллинджера H4 (20, 2σ)", H("4h", boll_break(20, 2))), ("Боллинджер H4 (20, 2.5σ)", H("4h", boll_break(20, 2.5))),
    ("Chandelier Exit H4 (22, 3 ATR) смена", H("4h", atr_trail(22, 3))), ("Chandelier H4 (14, 2.5 ATR)", H("4h", atr_trail(14, 2.5))),
    ("Ultimate Oscillator H1 выход из 30/70", H("1h", ultimate(30))), ("Ultimate Oscillator H4 30/70", H("4h", ultimate(30))),
    ("Недельный VWAP, пересечение", weekly_vwap), ("Coppock D1", H("1D", coppock_d)),
    ("Черепахи: пробой 20 дней", lambda d: days_breakout(d, 20)), ("Черепахи: пробой 55 дней", lambda d: days_breakout(d, 55)),
]


def main():
    D0, df = R.setup()
    D, _, pin = R.prepare(D0, df)
    m5m = load_mt5_csv()
    k = 2 * m5m.close.mean()
    m5m = m5m.assign(open=k - m5m.open, high=k - m5m.low, low=k - m5m.high, close=k - m5m.close)
    dfm = resample(m5m, "15min")
    Dm, _, pinm = R.prepare(C.load(mirror=True), dfm)
    E, Em = extras(df), extras(dfm)
    b, bs, bm = Q.run2(D, df, pin, E), Q.run2(D, df, pin, E, slip=SLIP), Q.run2(Dm, dfm, pinm, Em)
    H_ = R.HEAD.replace("| Зеркало |", "| Зеркало | Своих сделок | R до / после 07.2025 |").replace(
        "|---|---|---|---|---|---|---|---|---|---|---|", "|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    L = [H_, G.row("**как сейчас (9 стратегий)**", b) + f" {bs['tot']:+.0f} % | {bm['tot']:+.0f} % | — | — |"]
    print(L[-1], flush=True)
    for name, fn in CANDS:
        s, sm = P3.trend(df, fn(df)), P3.trend(dfm, fn(dfm))
        r, rs, rm = (Q.run2(D, df, pin, {**E, "new": s}), Q.run2(D, df, pin, {**E, "new": s}, slip=SLIP),
                     Q.run2(Dm, dfm, pinm, {**Em, "new": sm}))
        ok = r["tot"] > b["tot"] and r["a"] > b["a"] and r["b"] > b["b"] and rs["tot"] > bs["tot"] and rm["tot"] > bm["tot"]
        nt = [x for x in r["taken"] if x["key"] == "new"]
        ra = [x["r"] for x in nt if df.index[x["i"]] < Q.SPLIT]
        rb = [x["r"] for x in nt if df.index[x["i"]] >= Q.SPLIT]
        ln = (G.row(name + (" ✅" if ok else ""), r) + f" {rs['tot']:+.0f} % | {rm['tot']:+.0f} % | {len(nt)} | "
              f"{np.mean(ra) if ra else 0:+.2f} / {np.mean(rb) if rb else 0:+.2f} |")
        print(ln, flush=True)
        L.append(ln)
    out = Path(__file__).resolve().parent.parent / "reports" / "profit5_table.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
