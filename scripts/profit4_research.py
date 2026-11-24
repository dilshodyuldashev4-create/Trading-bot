"""Вторая волна индикаторов поверх бота с 8 стратегиями. Каждый — 9-я стратегия, по дневному тренду,
по две настройки (основная и соседняя). Проверка как в profit3_research.py.

    python scripts/profit4_research.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import challenge_research as C  # noqa: E402
import day_guard_research as G  # noqa: E402
import indicator_research as R  # noqa: E402
import profit2_research as Q  # noqa: E402
import profit3_research as P3  # noqa: E402
from goldbot.data import load_mt5_csv, resample  # noqa: E402
from goldbot.indicators import adx, atr, ema  # noqa: E402

SLIP = R.SLIP
first = P3.first


def sig(b, s):
    return first(np.where(np.asarray(b), 1, np.where(np.asarray(s), -1, 0)))


def cross_up(a, b):
    return (a > b) & (a.shift() <= b.shift())


def H(rule, f):
    return lambda df: Q.htf_events(df, rule, f)


def aroon(n):
    def f(x):
        up = x.high.rolling(n + 1).apply(np.argmax, raw=True) / n * 100
        dn = x.low.rolling(n + 1).apply(np.argmin, raw=True) / n * 100
        return sig(cross_up(up, dn) & (up > 70), cross_up(dn, up) & (dn > 70))
    return f


def stoch(n, lo):
    def f(x):
        k = 100 * (x.close - x.low.rolling(n).min()) / (x.high.rolling(n).max() - x.low.rolling(n).min())
        d = k.rolling(3).mean()
        return sig(cross_up(k, d) & (d < lo), cross_up(d, k) & (d > 100 - lo))
    return f


def cci(n, lvl):
    def f(x):
        tp = (x.high + x.low + x.close) / 3
        md = tp.rolling(n).apply(lambda v: np.abs(v - v.mean()).mean(), raw=True)
        c = (tp - tp.rolling(n).mean()) / (0.015 * md)
        return sig(c > lvl, c < -lvl)
    return f


def hma(s, n):
    w = lambda k: s.rolling(k).apply(lambda v: np.dot(v, np.arange(1, k + 1)) / (k * (k + 1) / 2), raw=True)  # noqa: E731
    raw = 2 * w(n // 2) - w(n)
    k = int(np.sqrt(n))
    return raw.rolling(k).apply(lambda v: np.dot(v, np.arange(1, k + 1)) / (k * (k + 1) / 2), raw=True)


def hull(n):
    def f(x):
        h = hma(x.close, n)
        sl = np.sign(h.diff())
        return sig(sl > 0, sl < 0)
    return f


def kama_flip(n):
    def f(x):
        c = x.close.to_numpy()
        er_n = n
        k = np.full(len(c), np.nan)
        fast, slow = 2 / 3, 2 / 31
        for i in range(er_n, len(c)):
            ch = abs(c[i] - c[i - er_n])
            vol = np.abs(np.diff(c[i - er_n:i + 1])).sum()
            er = ch / vol if vol else 0
            sc = (er * (fast - slow) + slow) ** 2
            k[i] = c[i] if np.isnan(k[i - 1]) else k[i - 1] + sc * (c[i] - k[i - 1])
        ks = pd.Series(k, index=x.index)
        return sig(x.close > ks, x.close < ks)
    return f


def vortex(n):
    def f(x):
        tr = pd.concat([x.high - x.low, (x.high - x.close.shift()).abs(), (x.low - x.close.shift()).abs()], axis=1).max(axis=1)
        vp = (x.high - x.low.shift()).abs().rolling(n).sum() / tr.rolling(n).sum()
        vm = (x.low - x.high.shift()).abs().rolling(n).sum() / tr.rolling(n).sum()
        return sig(vp > vm, vp < vm)
    return f


def mfi(n, lo):
    def f(x):
        tp = (x.high + x.low + x.close) / 3
        mf = tp * x.volume
        pos = mf.where(tp > tp.shift(), 0).rolling(n).sum()
        neg = mf.where(tp < tp.shift(), 0).rolling(n).sum()
        m = 100 - 100 / (1 + pos / neg.replace(0, np.nan))
        return sig(cross_up(m, pd.Series(lo, index=x.index)), cross_up(pd.Series(100 - lo, index=x.index), m))
    return f


def obv_break(n):
    def f(x):
        obv = (np.sign(x.close.diff()).fillna(0) * x.volume).cumsum()
        b = (obv > obv.rolling(n).max().shift()) & (x.close > x.high.rolling(n).max().shift())
        s = (obv < obv.rolling(n).min().shift()) & (x.close < x.low.rolling(n).min().shift())
        return sig(b, s)
    return f


def linreg(n, r2min):
    def f(x):
        t = np.arange(n)
        y = x.close
        cov = y.rolling(n).apply(lambda v: np.corrcoef(t, v)[0, 1], raw=True)
        r2 = cov ** 2
        return sig((cov > 0) & (r2 > r2min), (cov < 0) & (r2 > r2min))
    return f


def pivots(level):
    """Классические дневные пивоты: первый пробой R1 (BUY) / S1 (SELL) за день; level=2 — R2/S2."""
    def f(df):
        d = df.resample("1D").agg(dict(high="max", low="min", close="last")).dropna()
        p = (d.high + d.low + d.close) / 3
        r = (2 * p - d.low) if level == 1 else p + (d.high - d.low)
        s = (2 * p - d.high) if level == 1 else p - (d.high - d.low)
        day = df.index.normalize()
        rr, ss = r.shift().reindex(day).to_numpy(), s.shift().reindex(day).to_numpy()
        c = df.close.to_numpy()
        return R.once_per_day(np.where(c > rr, 1, np.where(c < ss, -1, 0)), df.index)
    return f


def fractal_break(n):
    def f(x):
        h, l = x.high, x.low
        fh = h[(h == h.rolling(2 * n + 1, center=True).max())].reindex(x.index)
        fl = l[(l == l.rolling(2 * n + 1, center=True).min())].reindex(x.index)
        # фрактал известен только через n свечей
        fh, fl = fh.shift(n).ffill(), fl.shift(n).ffill()
        return sig((x.close > fh) & (x.close.shift() <= fh.shift()), (x.close < fl) & (x.close.shift() >= fl.shift()))
    return f


def golden(a, b):
    def f(x):
        ea, eb = ema(x.close, a), ema(x.close, b)
        return sig(ea > eb, ea < eb)
    return f


def dmi(n, amin):
    def f(x):
        up, dn = x.high.diff(), -x.low.diff()
        pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=x.index)
        mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=x.index)
        a = atr(x, n)
        pdi = pdm.ewm(alpha=1 / n, adjust=False).mean() / a
        mdi = mdm.ewm(alpha=1 / n, adjust=False).mean() / a
        ad = pd.Series(adx(x, n), index=x.index)
        return sig((pdi > mdi) & (ad > amin), (pdi < mdi) & (ad > amin))
    return f


def trix(n):
    def f(x):
        t = ema(ema(ema(x.close, n), n), n).pct_change()
        return sig(t > 0, t < 0)
    return f


def ao():
    def f(x):
        m = (x.high + x.low) / 2
        a = m.rolling(5).mean() - m.rolling(34).mean()
        return sig(a > 0, a < 0)
    return f


def roc(n, k):
    def f(x):
        r = x.close.pct_change(n) * 100
        a = (atr(x, 14) / x.close * 100) * np.sqrt(n)
        return sig(r > k * a, r < -k * a)
    return f


def ichi_kumo():
    """Пробой облака Ишимоку H4 (как вход, не фильтр)."""
    def f(x):
        t = (x.high.rolling(9).max() + x.low.rolling(9).min()) / 2
        k = (x.high.rolling(26).max() + x.low.rolling(26).min()) / 2
        a = ((t + k) / 2).shift(26)
        b = ((x.high.rolling(52).max() + x.low.rolling(52).min()) / 2).shift(26)
        top, bot = np.maximum(a, b), np.minimum(a, b)
        return sig(x.close > top, x.close < bot)
    return f


CANDS = [
    ("Aroon H1 (25)", H("1h", aroon(25))), ("Aroon H1 (14)", H("1h", aroon(14))),
    ("Стохастик H1 откат (14, 20/80)", H("1h", stoch(14, 20))), ("Стохастик H1 (14, 30/70)", H("1h", stoch(14, 30))),
    ("CCI H1 пробой ±100 (20)", H("1h", cci(20, 100))), ("CCI H1 ±150 (20)", H("1h", cci(20, 150))),
    ("Hull MA H1 смена наклона (55)", H("1h", hull(55))), ("Hull MA H1 (34)", H("1h", hull(34))),
    ("KAMA H1 пересечение (10)", H("1h", kama_flip(10))), ("KAMA H4 пересечение (10)", H("4h", kama_flip(10))),
    ("Vortex H1 (14)", H("1h", vortex(14))), ("Vortex H4 (14)", H("4h", vortex(14))),
    ("MFI H1 выход из 20/80 (14)", H("1h", mfi(14, 20))), ("MFI H1 30/70 (14)", H("1h", mfi(14, 30))),
    ("OBV + цена новый максимум 20 H1", H("1h", obv_break(20))), ("OBV + цена 50 H1", H("1h", obv_break(50))),
    ("Линейная регрессия H1 (50, R² > 0.8)", H("1h", linreg(50, 0.8))), ("Линейная регрессия H1 (30, R² > 0.7)", H("1h", linreg(30, 0.7))),
    ("Пивоты дня: пробой R1/S1", pivots(1)), ("Пивоты дня: пробой R2/S2", pivots(2)),
    ("Фракталы Вильямса H1 пробой (2)", H("1h", fractal_break(2))), ("Фракталы H4 пробой (2)", H("4h", fractal_break(2))),
    ("EMA 50/200 H4 (золотой крест)", H("4h", golden(50, 200))), ("EMA 20/50 H4", H("4h", golden(20, 50))),
    ("DMI H1 +DI/−DI при ADX > 25", H("1h", dmi(14, 25))), ("DMI H4 при ADX > 20", H("4h", dmi(14, 20))),
    ("TRIX H1 (15)", H("1h", trix(15))), ("TRIX H4 (9)", H("4h", trix(9))),
    ("Awesome Oscillator H1", H("1h", ao())), ("Awesome Oscillator H4", H("4h", ao())),
    ("Моментум ROC H4 (6 свечей, > 1.5σ)", H("4h", roc(6, 1.5))), ("ROC H4 (12, > 2σ)", H("4h", roc(12, 2))),
    ("Облако Ишимоку H4, пробой", H("4h", ichi_kumo())), ("Облако Ишимоку H1, пробой", H("1h", ichi_kumo())),
]


def main():
    D0, df = R.setup()
    D, _, pin = R.prepare(D0, df)
    m5m = load_mt5_csv()
    k = 2 * m5m.close.mean()
    m5m = m5m.assign(open=k - m5m.open, high=k - m5m.low, low=k - m5m.high, close=k - m5m.close)
    dfm = resample(m5m, "15min")
    Dm, _, pinm = R.prepare(C.load(mirror=True), dfm)
    E, Em = P3.extras(df), P3.extras(dfm)
    b, bs, bm = Q.run2(D, df, pin, E), Q.run2(D, df, pin, E, slip=SLIP), Q.run2(Dm, dfm, pinm, Em)
    H_ = R.HEAD.replace("| Зеркало |", "| Зеркало | Своих сделок | R до / после 07.2025 |").replace("|---|---|---|---|---|---|---|---|---|---|---|", "|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    L = [H_, G.row("**как сейчас (8 стратегий)**", b) + f" {bs['tot']:+.0f} % | {bm['tot']:+.0f} % | — | — |"]
    print(L[-1], flush=True)
    for name, fn in CANDS:
        s, sm = P3.trend(df, fn(df)), P3.trend(dfm, fn(dfm))
        r, rs, rm = Q.run2(D, df, pin, {**E, "new": s}), Q.run2(D, df, pin, {**E, "new": s}, slip=SLIP), Q.run2(Dm, dfm, pinm, {**Em, "new": sm})
        ok = r["tot"] > b["tot"] and r["a"] > b["a"] and r["b"] > b["b"] and rs["tot"] > bs["tot"] and rm["tot"] > bm["tot"]
        nt = [x for x in r["taken"] if x["key"] == "new"]
        ra = [x["r"] for x in nt if df.index[x["i"]] < Q.SPLIT]
        rb = [x["r"] for x in nt if df.index[x["i"]] >= Q.SPLIT]
        ln = (G.row(name + (" ✅" if ok else ""), r) + f" {rs['tot']:+.0f} % | {rm['tot']:+.0f} % | {len(nt)} | "
              f"{np.mean(ra) if ra else 0:+.2f} / {np.mean(rb) if rb else 0:+.2f} |")
        print(ln, flush=True)
        L.append(ln)
    out = Path(__file__).resolve().parent.parent / "reports" / "profit4_table.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
