"""Новые стратегии и индикаторы поверх бота с 8 стратегиями (после profit2: + пробой 5 дней).

1) Новые сигналы (9-я стратегия): RSI(2) Коннорса H1, Кельтнер H1, всплеск тикового объёма, Turtle Soup
   (вынос 20-дневного минимума / максимума и возврат), Parabolic SAR H1, MACD H4, откат к EMA20 H1 в сильном
   тренде, IBS дня, покупка в начале Азии, конец/начало месяца, азиатский пробой с фильтром ширины диапазона.
2) Размер лота: режим волатильности, сила дневного тренда.

Проверка как в profit2_research.py: обе половины истории, стресс издержек +0.30 $, зеркальный график.
Лучшие — ещё и на проп-счёте (challenge_research: 0.5 %, стоп дня после 1-го SL, риск ×0.25 при −2 %).

    python scripts/profit3_research.py   # отчёт в reports/profit3_research.md
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
from goldbot.data import load_mt5_csv, resample  # noqa: E402
from goldbot.indicators import atr, ema, rsi  # noqa: E402
from goldbot.strategies.popular import days_breakout  # noqa: E402
from goldbot.strategies.research import htf_trend  # noqa: E402
from goldbot.strategies.sessions import _local, _minutes  # noqa: E402

SLIP = R.SLIP


def first(sig):
    sig = np.asarray(sig)
    return np.where(sig != np.r_[0, sig[:-1]], sig, 0).astype(np.int8)


def on_close(df, rule, x_sig):
    """Сигнал свечи старшего ТФ → на свече M15, которой она закрывается."""
    return Q.htf_events(df, rule, x_sig)


def rsi2_h1(df, lo=10, hi=90):
    """Коннорс: H1 RSI(2) < lo при close > EMA200 H1 → BUY (откат в тренде), > hi при close < EMA200 → SELL."""
    def f(x):
        r = rsi(x.close, 2)
        t = ema(x.close, 200)
        b = (r < lo) & (x.close > t)
        s = (r > hi) & (x.close < t)
        return first(np.where(b, 1, np.where(s, -1, 0)))
    return on_close(df, "1h", f)


def keltner_h1(df, k=2.0):
    def f(x):
        m, a = ema(x.close, 20), atr(x, 20)
        return first(np.where(x.close > m + k * a, 1, np.where(x.close < m - k * a, -1, 0)))
    return on_close(df, "1h", f)


def vol_climax(df, vk=2.5, rk=1.5):
    """Свеча M15 с тиковым объёмом > vk × средний за 20 и размахом > rk × ATR, закрытие в крайней четверти."""
    v = df.volume
    a = atr(df, 14)
    rng = df.high - df.low
    pos = (df.close - df.low) / rng.replace(0, np.nan)
    big = (v > vk * v.rolling(20).mean().shift()) & (rng > rk * a.shift())
    return np.where(big & (pos > 0.75), 1, np.where(big & (pos < 0.25), -1, 0)).astype(np.int8)


def turtle_soup(df, n=20):
    """Сегодня цена ушла ниже минимума n дней и свеча M15 закрылась обратно выше него → BUY (и наоборот)."""
    day = df.index.normalize()
    d = df.resample("1D").agg(dict(high="max", low="min")).dropna()
    hi = d.high.rolling(n).max().shift().reindex(day).to_numpy()
    lo = d.low.rolling(n).min().shift().reindex(day).to_numpy()
    g = pd.Series(df.low.to_numpy(), index=df.index).groupby(day).cummin().to_numpy()
    gh = pd.Series(df.high.to_numpy(), index=df.index).groupby(day).cummax().to_numpy()
    c = df.close.to_numpy()
    sig = np.where((g < lo) & (c > lo), 1, np.where((gh > hi) & (c < hi), -1, 0))
    return R.once_per_day(sig, df.index)


def psar_h1(df, step=0.02, mx=0.2):
    def f(x):
        h, l = x.high.to_numpy(), x.low.to_numpy()
        n = len(x)
        d = np.ones(n, dtype=np.int8)
        sar, ep, af = l[0], h[0], step
        for i in range(1, n):
            sar = sar + af * (ep - sar)
            if d[i - 1] == 1:
                sar = min(sar, l[i - 1], l[i - 2] if i > 1 else l[i - 1])
                if l[i] < sar:
                    d[i], sar, ep, af = -1, ep, l[i], step
                else:
                    d[i] = 1
                    if h[i] > ep:
                        ep, af = h[i], min(af + step, mx)
            else:
                sar = max(sar, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
                if h[i] > sar:
                    d[i], sar, ep, af = 1, ep, h[i], step
                else:
                    d[i] = -1
                    if l[i] < ep:
                        ep, af = l[i], min(af + step, mx)
        return first(d) * (np.r_[0, d[1:] != d[:-1]])
    return on_close(df, "1h", f)


def macd_h4(df):
    def f(x):
        m = ema(x.close, 12) - ema(x.close, 26)
        return first(np.sign(m - ema(m, 9)).to_numpy())
    return on_close(df, "4h", f)


def ema_pullback_h1(df):
    """H1: EMA20 > EMA50 > EMA200, свеча коснулась EMA20 и закрылась выше неё → BUY (и наоборот)."""
    def f(x):
        e20, e50, e200 = ema(x.close, 20), ema(x.close, 50), ema(x.close, 200)
        up = (e20 > e50) & (e50 > e200) & (x.low <= e20) & (x.close > e20)
        dn = (e20 < e50) & (e50 < e200) & (x.high >= e20) & (x.close < e20)
        return first(np.where(up, 1, np.where(dn, -1, 0)))
    return on_close(df, "1h", f)


def day_open_bar(df):
    day = df.index.normalize()
    return np.r_[True, day[1:] != day[:-1]]


def ibs_daily(df, lo=0.2, hi=0.8):
    """Вчера закрылись у минимума дня (IBS < lo) → BUY на первой свече дня; у максимума (> hi) → SELL."""
    d = df.resample("1D").agg(dict(high="max", low="min", close="last")).dropna()
    ibs = ((d.close - d.low) / (d.high - d.low)).shift().reindex(df.index.normalize()).to_numpy()
    fb = day_open_bar(df)
    return np.where(fb & (ibs < lo), 1, np.where(fb & (ibs > hi), -1, 0)).astype(np.int8)


def asia_buy(df):
    """Начало азиатской сессии (00:00 Лондона, свеча 00:15) — сигнал BUY (тренд-фильтр снаружи)."""
    m = _minutes(_local(df, "Europe/London"))
    return np.where(m == 15, 1, 0).astype(np.int8)


def turn_of_month(df):
    """Последний торговый день месяца, 08:00 Лондона — BUY (идея «конец/начало месяца»)."""
    t = _local(df, "Europe/London")
    m = _minutes(t)
    day = df.index.normalize()
    days = pd.Series(day.unique())
    last = days.groupby(days.dt.to_period("M")).max()
    is_last = np.isin(day, last.to_numpy())
    return np.where(is_last & (m == 8 * 60), 1, 0).astype(np.int8)


def asia_filtered(df, lo_pct=0.3, hi_pct=1.6):
    """Пробой Азии (как в боте), но только если ширина диапазона lo_pct–hi_pct % цены."""
    from goldbot.strategies.sessions import asian_breakout_day
    s = asian_breakout_day(df)
    t = _local(df, "Europe/London")
    m, day = _minutes(t), t.normalize()
    asia = pd.Series(np.where(m < 420, 1, 0), index=df.index)
    hh = pd.Series(np.where(m < 420, df.high, np.nan), index=df.index).groupby(day).transform("max")
    ll = pd.Series(np.where(m < 420, df.low, np.nan), index=df.index).groupby(day).transform("min")
    w = ((hh - ll) / df.close * 100).to_numpy()
    del asia
    return np.where((w >= lo_pct) & (w <= hi_pct), s, 0).astype(np.int8)


def trend(df, s):
    return Q.trend(df, s)


def extras(df):
    return {**Q.bot_extra(df), "days5": trend(df, days_breakout(df, 5))}


def cands(d):
    return {
        "RSI(2) Коннорса H1, откат по дневному тренду": trend(d, rsi2_h1(d)),
        "RSI(2) H1 5/95 по дневному тренду": trend(d, rsi2_h1(d, 5, 95)),
        "RSI(2) H1 15/85 по дневному тренду": trend(d, rsi2_h1(d, 15, 85)),
        "Кельтнер H1 (EMA20 ± 2 ATR) по дневному тренду": trend(d, keltner_h1(d)),
        "Кельтнер H1 ± 2.5 ATR по дневному тренду": trend(d, keltner_h1(d, 2.5)),
        "Всплеск тикового объёма M15 по дневному тренду": trend(d, vol_climax(d)),
        "Всплеск объёма ×3, размах 2 ATR, по тренду": trend(d, vol_climax(d, 3, 2)),
        "Turtle Soup 20 дней (вынос и возврат)": turtle_soup(d),
        "Turtle Soup 20 дней по дневному тренду": trend(d, turtle_soup(d)),
        "Turtle Soup 10 дней по дневному тренду": trend(d, turtle_soup(d, 10)),
        "Parabolic SAR H1 по дневному тренду": trend(d, psar_h1(d)),
        "MACD H4 (пересечение сигнальной) по дневному тренду": trend(d, macd_h4(d)),
        "Откат к EMA20 H1 в сильном тренде (20>50>200)": ema_pullback_h1(d),
        "Откат к EMA20 H1 в сильном тренде, по дневному": trend(d, ema_pullback_h1(d)),
        "IBS дня (закрытие у края дня) по дневному тренду": trend(d, ibs_daily(d)),
        "Покупка в начале Азии (00:15 Лондона) по тренду": trend(d, asia_buy(d)),
        "Конец месяца — покупка по тренду": trend(d, turn_of_month(d)),
    }


def run_p(D, df, pin, E, **kw):
    return Q.run2(D, df, pin, E, **kw)


def vol_sizes(df, hi_k, hi_m, lo_k, lo_m):
    a = atr(df, 14)
    r = (a / a.rolling(96 * 20, min_periods=96).median()).to_numpy()
    return np.where(r > hi_k, hi_m, np.where(r < lo_k, lo_m, 1.0))


def trend_strength(df, k, m):
    d = df.resample("1D").agg(dict(high="max", low="min", close="last")).dropna()
    e = ema(d.close, 50)
    da = atr(d, 14)
    z = ((d.close - e) / da)
    z.index = z.index + pd.Timedelta("1D")
    z = z.reindex(df.index, method="ffill").fillna(0).to_numpy()
    return z, k, m


def main():
    D0, df = R.setup()
    D, _, pin = R.prepare(D0, df)
    m5m = load_mt5_csv()
    k = 2 * m5m.close.mean()
    m5m = m5m.assign(open=k - m5m.open, high=k - m5m.low, low=k - m5m.high, close=k - m5m.close)
    dfm = resample(m5m, "15min")
    Dm, _, pinm = R.prepare(C.load(mirror=True), dfm)
    E, Em = extras(df), extras(dfm)

    b, bs, bm = run_p(D, df, pin, E), run_p(D, df, pin, E, slip=SLIP), run_p(Dm, dfm, pinm, Em)
    L = ["# Новые стратегии и индикаторы: проверка на истории (после profit2)", "",
         "Свечи XAUUSD M15 01.12.2023 – 21.08.2026, спред брокера учтён. База — бот как сейчас: 8 стратегий",
         "(squeeze, donchian, fvg_m15, liq_m15, amd, asia, donchian_h1, days5), стоп 2 ATR, 50 % на +1R и безубыток,",
         "тейк 3R, ADX-фильтр пробоев, лот ×0.75 / ×1.5 при согласии, стоп дня после 4-го SL, пин-бар H1 против — пропуск.",
         "Риск 1 % от старта. ✅ — лучше базы по итогу, в обеих половинах (до / после 07.2025),",
         f"со стрессом издержек +{SLIP:.2f} $ на сделку и на зеркальном графике. Повторить: `python scripts/profit3_research.py`.",
         "", "## 1. Новая (9-я) стратегия", "", R.HEAD]
    base_ln = G.row("**как сейчас (8 стратегий)**", b) + f" {bs['tot']:+.0f} % | {bm['tot']:+.0f} % |"
    L.append(base_ln)
    print(base_ln, flush=True)
    good = []
    stats = []

    def line(name, s, ss, sm):
        ok = s["tot"] > b["tot"] and s["a"] > b["a"] and s["b"] > b["b"] and ss["tot"] > bs["tot"] and sm["tot"] > bm["tot"]
        ln = G.row(name + (" ✅" if ok else ""), s) + f" {ss['tot']:+.0f} % | {sm['tot']:+.0f} % |"
        print(ln, flush=True)
        L.append(ln)
        return ok

    Cs, Cm = cands(df), cands(dfm)
    Cs["Пробой Азии только при ширине 0.3–1.6 % цены (вместо обычного)"] = None
    for name in Cs:
        if Cs[name] is None:
            ex = {**E, "asia": asia_filtered(df)}
            exm = {**Em, "asia": asia_filtered(dfm)}
        else:
            ex, exm = {**E, "new": Cs[name]}, {**Em, "new": Cm[name]}
        s = run_p(D, df, pin, ex)
        if line(name, s, run_p(D, df, pin, ex, slip=SLIP), run_p(Dm, dfm, pinm, exm)):
            good.append(name)
        if Cs[name] is not None:
            nt = [x for x in s["taken"] if x["key"] == "new"]
            ra = [x["r"] for x in nt if df.index[x["i"]] < Q.SPLIT]
            rb = [x["r"] for x in nt if df.index[x["i"]] >= Q.SPLIT]
            stats.append(f"| {name} | {len(nt)} | {np.mean(ra) if ra else 0:+.3f}R | {np.mean(rb) if rb else 0:+.3f}R |")

    L += ["", "Сама новая стратегия внутри портфеля (сделки, которые бот открыл бы):", "",
          "| Стратегия | Сделок | R на сделку до 07.2025 | после 07.2025 |", "|---|---|---|---|"] + stats

    # 2. размер лота
    L += ["", "## 2. Размер лота по рынку", "", R.HEAD, base_ln]

    def sized(Dx, dfx, pinx, Ex, mult, slip=0.0):
        """mult[i] — множитель лота по свече сигнала."""
        rep0 = Q.run2(Dx, dfx, pinx, Ex, slip=slip)
        del rep0
        orig = G.portfolio

        def patched(trades, idx, g, sizes):
            s2 = {id(x): sizes[id(x)] * mult(x) for x in trades}
            return orig(trades, idx, g, s2)
        G.portfolio = patched
        try:
            return Q.run2(Dx, dfx, pinx, Ex, slip=slip)
        finally:
            G.portfolio = orig

    for name, hk, hm, lk, lm in (
        ("волатильность выше медианы ×1.5 — лот ×0.75", 1.5, 0.75, 0, 1),
        ("волатильность ниже медианы ×0.8 — лот ×1.25", 99, 1, 0.8, 1.25),
        ("оба правила вместе", 1.5, 0.75, 0.8, 1.25),
        ("волатильность выше ×1.3 — лот ×0.5", 1.3, 0.5, 0, 1),
    ):
        vs, vm = vol_sizes(df, hk, hm, lk, lm), vol_sizes(dfm, hk, hm, lk, lm)
        line(name, sized(D, df, pin, E, lambda x, v=vs: v[x["sig"]]),
             sized(D, df, pin, E, lambda x, v=vs: v[x["sig"]], slip=SLIP),
             sized(Dm, dfm, pinm, Em, lambda x, v=vm: v[x["sig"]]))
    for name, kz, mk in (("сильный дневной тренд (> 2 ATR дня от EMA50) — лот ×1.25 по тренду", 2, 1.25),
                         ("дневной тренд слабый (< 1 ATR дня от EMA50) — лот ×0.75", -1, 0.75)):
        z, _, _ = trend_strength(df, kz, mk)
        zm, _, _ = trend_strength(dfm, kz, mk)

        def fm(zz, kz=kz, mk=mk):
            if kz > 0:
                return lambda x: mk if zz[x["sig"]] * x["d"] > kz else 1.0
            return lambda x: mk if abs(zz[x["sig"]]) < 1 else 1.0
        line(name, sized(D, df, pin, E, fm(z)), sized(D, df, pin, E, fm(z), slip=SLIP), sized(Dm, dfm, pinm, Em, fm(zm)))

    print("GOOD:", good)
    out = Path(__file__).resolve().parent.parent / "reports" / "profit3_tables.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
