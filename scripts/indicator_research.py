"""Новые индикаторы и стратегии поверх бота: Supertrend, Ichimoku, VWAP, открытие дня, ADX/Choppiness,
Donchian H1, MACD H1, RSI-дивергенция, Heikin-Ashi, азиатский диапазон, пробой прошлого дня, часы и дни недели.

База — обычный счёт как в боте сейчас: 5 стратегий M15, стоп 2 ATR, 50 % на +1R и безубыток, тейк 3R,
ADX-фильтр пробоев, лот ×0.75 / ×1.5, стоп дня после 4-го SL, пин-бар H1 против сигнала за 2 ч — пропуск.
Свечи XAUUSD 01.12.2023 – 21.08.2026, спред брокера учтён. Отдельно — стресс издержек (+0.30 $ на сделку,
проскальзывание и комиссия) и зеркальный график (рост ↔ падение).

Два способа: (1) новая 6-я стратегия с тем же сопровождением; (2) фильтр сигналов бота.
Принимается только то, что поднимает итог И в обеих половинах истории, и на зеркале, и со стрессом издержек.

    python scripts/indicator_research.py   # отчёт в reports/indicator_research.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import day_guard_research as G  # noqa: E402
import profit_research as P  # noqa: E402
from challenge_research import KEYS, load  # noqa: E402
from goldbot.data import PIP, load_mt5_csv, resample  # noqa: E402
from goldbot.indicators import atr, ema, pin_bar, rsi  # noqa: E402
from goldbot.strategies.popular import donchian_h1, supertrend  # noqa: E402
from goldbot.strategies.research import htf_trend  # noqa: E402
from goldbot.strategies.sessions import _range_breakout  # noqa: E402
from ideas_research import adx  # noqa: E402

SLIP = 0.30          # $ на сделку в стресс-тесте


def h1_of(df):
    return df.resample("1h").agg(dict(open="first", high="max", low="min", close="last")).dropna()


def on_m15(values, h1_index, idx, state=True):
    """Значение H1 свечи с началом T известно на свече M15 T+45 (её закрытие = закрытие H1)."""
    s = pd.Series(np.asarray(values, dtype=float), index=h1_index + pd.Timedelta(minutes=45))
    s = s[~s.index.duplicated()]
    if state:
        return s.reindex(idx, method="ffill").fillna(0).to_numpy()
    return s.reindex(idx).fillna(0).to_numpy()


def st_dir(x, n=10, mult=3.0):
    flips = supertrend(x, n, mult)
    return pd.Series(np.where(flips == 0, np.nan, flips)).ffill().fillna(0).to_numpy()


def ichimoku(x):
    h, l, c = x.high, x.low, x.close
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2
    a = ((tenkan + kijun) / 2).shift(26)
    b = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    top, bot = np.maximum(a, b), np.minimum(a, b)
    cloud = np.where(c > top, 1, np.where(c < bot, -1, 0))
    up = (tenkan > kijun) & (tenkan.shift() <= kijun.shift())
    dn = (tenkan < kijun) & (tenkan.shift() >= kijun.shift())
    sig = np.where(up & (cloud == 1), 1, np.where(dn & (cloud == -1), -1, 0))
    return cloud, sig


def chop(x, n=14):
    tr = pd.concat([x.high - x.low, (x.high - x.close.shift()).abs(), (x.low - x.close.shift()).abs()], axis=1).max(axis=1)
    rng = x.high.rolling(n).max() - x.low.rolling(n).min()
    return (100 * np.log10(tr.rolling(n).sum() / rng) / np.log10(n)).to_numpy()


def heikin_dir(x):
    hc = (x.open + x.high + x.low + x.close) / 4
    ho = hc.copy()
    ho.iloc[0] = (x.open.iloc[0] + x.close.iloc[0]) / 2
    hcv, hov = hc.to_numpy().copy(), ho.to_numpy().copy()
    for i in range(1, len(hov)):
        hov[i] = (hov[i - 1] + hcv[i - 1]) / 2
    return np.sign(hcv - hov)


def flips(d):
    d = np.asarray(d)
    out = np.zeros(len(d), dtype=np.int8)
    ch = np.r_[False, (d[1:] != d[:-1]) & (d[1:] != 0)]
    out[ch] = d[ch]
    return out


def rsi_div(x, n=5):
    """Бычья дивергенция: новый пивот-лой ниже прошлого, RSI в нём выше → BUY (на свече подтверждения)."""
    c = x.close.to_numpy()
    lo, hi = x.low.to_numpy(), x.high.to_numpy()
    r = rsi(x.close, 14).to_numpy()
    sig = np.zeros(len(x), dtype=np.int8)
    pl = ph = None
    for i in range(2 * n, len(x)):
        k = i - n
        if lo[k] == lo[k - n:i + 1].min():
            if pl is not None and lo[k] < lo[pl] and r[k] > r[pl] and r[k] < 40:
                sig[i] = 1
            pl = k
        if hi[k] == hi[k - n:i + 1].max():
            if ph is not None and hi[k] > hi[ph] and r[k] < r[ph] and r[k] > 60:
                sig[i] = -1
            ph = k
    return sig


def once_per_day(sig, idx):
    day = idx.normalize()
    s = pd.Series(sig, index=idx)
    first = s.ne(0).groupby(day).cumsum()
    return np.where((s != 0) & (first == 1), sig, 0).astype(np.int8)


def asian_breakout(df):
    idx = df.index
    m = idx.hour * 60 + idx.minute
    asia = (m < 7 * 60)
    day = idx.normalize()
    hi = df.high.where(asia).groupby(day).cummax().groupby(day).ffill()
    lo = df.low.where(asia).groupby(day).cummin().groupby(day).ffill()
    win = (m >= 7 * 60) & (m < 16 * 60)
    sig = np.where(win & (df.close > hi), 1, np.where(win & (df.close < lo), -1, 0))
    return once_per_day(sig, idx)


def prev_day_breakout(df):
    idx = df.index
    d = df.resample("1D").agg(dict(high="max", low="min")).dropna()
    ph = d.high.shift().reindex(idx.normalize()).to_numpy()
    pl = d.low.shift().reindex(idx.normalize()).to_numpy()
    h = idx.hour
    win = (h >= 7) & (h < 17)
    sig = np.where(win & (df.close.to_numpy() > ph), 1, np.where(win & (df.close.to_numpy() < pl), -1, 0))
    return once_per_day(sig, idx)


def setup():
    D0 = load()
    df = resample(load_mt5_csv(), "15min")
    return D0, df


def prepare(D0, df):
    ad = adx(df, 14)
    D = dict(D0)
    D["sig"] = dict(D0["sig"])
    for k in P.BREAKOUTS:
        D["sig"][k] = np.where(ad >= 25, 0, D0["sig"][k]).astype(np.int8)
    h1 = h1_of(df)
    pin = on_m15(pin_bar(h1), h1.index, df.index, state=False)
    pin_recent = pd.Series(pin, index=df.index).replace(0, np.nan).ffill(limit=7).fillna(0).to_numpy()
    return D, h1, pin_recent


def run(D, df, pin_recent, extra=None, keep=None, slip=0.0):
    """extra: {key: sig} — новые стратегии. keep(x) → False — сделку пропустить (фильтр)."""
    keys = KEYS + tuple(extra or ())
    D2 = dict(D)
    D2["sig"] = {**D["sig"], **(extra or {})}
    opp = np.zeros(len(df), dtype=int)
    for k in keys:
        opp = np.where(opp == 0, D2["sig"][k], opp)
    a = atr(df, 14)
    P.KEYS = keys
    trades = P.simulate(D2, dict(c=df.close.to_numpy(), atr=a.to_numpy(), opp=opp))
    P.KEYS = KEYS
    if slip:
        for x in trades:
            x["r"] -= slip / (D2["sl"][x["sig"]] * PIP)
    sigs = np.stack([D2["sig"][k] for k in keys])

    def agree(x):
        ki = keys.index(x["key"])
        lo = max(0, x["sig"] - 3)
        return bool((np.delete(sigs[:, lo:x["sig"] + 1], ki, axis=0) == x["d"]).any())
    trades = [x for x in trades if pin_recent[x["sig"]] != -x["d"]]
    if keep is not None:
        trades = [x for x in trades if keep(x)]
    sizes = {id(x): 1.5 if agree(x) else 0.75 for x in trades}
    G.KEYS = keys
    t, _ = G.portfolio(trades, df.index, G.Guard(day_sl=4), sizes)
    G.KEYS = KEYS
    return G.report(t, df.index)


def candidates(df, h1):
    idx = df.index
    c = df.close
    dtr = htf_trend(df, "1D", 50)
    st = on_m15(st_dir(h1), h1.index, idx)
    st_slow = on_m15(st_dir(h1, 10, 4.0), h1.index, idx)
    cloud_h1, ichi_sig = ichimoku(h1)
    cloud = on_m15(cloud_h1, h1.index, idx)
    ha = on_m15(heikin_dir(h1), h1.index, idx)
    e200h1 = on_m15(np.sign(h1.close - ema(h1.close, 200)), h1.index, idx)
    adx_h1 = on_m15(adx(h1, 14), h1.index, idx)
    chop_h1 = on_m15(chop(h1), h1.index, idx)
    rsi_h1 = on_m15(rsi(h1.close, 14).to_numpy(), h1.index, idx)
    # дневной VWAP (с 00:00 UTC) по тиковому объёму M15
    tp = (df.high + df.low + df.close) / 3
    vol = df.volume.replace(0, 1)
    day = idx.normalize()
    vwap = ((tp * vol).groupby(day).cumsum() / vol.groupby(day).cumsum()).to_numpy()
    day_open = df.open.groupby(day).transform("first").to_numpy()
    wk = idx.to_period("W").start_time
    week_open = df.open.groupby(wk).transform("first").to_numpy()
    cv = c.to_numpy()
    # стратегии (сигналы на M15)
    macd = ema(h1.close, 12) - ema(h1.close, 26)
    sgn = ema(macd, 9)
    macd_x = np.where((macd > sgn) & (macd.shift() <= sgn.shift()), 1,
                      np.where((macd < sgn) & (macd.shift() >= sgn.shift()), -1, 0))
    e20, e50 = ema(h1.close, 20), ema(h1.close, 50)
    pb = np.where((e20 > e50) & (h1.low <= e20) & (h1.close > e20) & (h1.close > h1.open), 1,
                  np.where((e20 < e50) & (h1.high >= e20) & (h1.close < e20) & (h1.close < h1.open), -1, 0))
    dc55 = np.where(h1.close > h1.high.rolling(55).max().shift(), 1,
                    np.where(h1.close < h1.low.rolling(55).min().shift(), -1, 0))
    dc55 = np.where(dc55 != pd.Series(dc55).shift().fillna(0).to_numpy(), dc55, 0)
    ev = lambda s: on_m15(s, h1.index, idx, state=False).astype(np.int8)  # noqa: E731
    trend = lambda s: np.where(np.asarray(s) == dtr, s, 0).astype(np.int8)  # noqa: E731
    strategies = {
        "Supertrend H1 10/3, разворот": ev(flips(st_dir(h1))),
        "Supertrend H1 10/3, разворот по дневному тренду": trend(ev(flips(st_dir(h1)))),
        "Ichimoku H1: Tenkan/Kijun над/под облаком": ev(ichi_sig),
        "Ichimoku H1 по дневному тренду": trend(ev(ichi_sig)),
        "MACD H1 пересечение по EMA200 H1": np.where(ev(macd_x) == e200h1, ev(macd_x), 0).astype(np.int8),
        "Откат к EMA20 H1 (EMA20>EMA50)": ev(pb),
        "Откат к EMA20 H1 по дневному тренду": trend(ev(pb)),
        "Дончиан 55 H1 (черепахи)": ev(dc55),
        "Дончиан 55 H1 по дневному тренду": trend(ev(dc55)),
        "Heikin-Ashi H1 смена цвета по дневному тренду": trend(ev(flips(heikin_dir(h1)))),
        "RSI-дивергенция H1": ev(rsi_div(h1)),
        "RSI-дивергенция H1 по дневному тренду": trend(ev(rsi_div(h1))),
        "Пробой азиатского диапазона (07–16 UTC)": asian_breakout(df),
        "Пробой азиатского диапазона по дневному тренду": trend(asian_breakout(df)),
        "Пробой хая/лоя прошлого дня по дневному тренду": trend(prev_day_breakout(df)),
    }
    hr = idx.hour.to_numpy()
    wd = idx.weekday.to_numpy()
    filters = {
        "Supertrend H1 10/3 по сделке": lambda x: st[x["sig"]] == x["d"],
        "Supertrend H1 10/4 по сделке": lambda x: st_slow[x["sig"]] == x["d"],
        "Ichimoku H1: не против облака": lambda x: cloud[x["sig"]] != -x["d"],
        "Ichimoku H1: только по облаку": lambda x: cloud[x["sig"]] == x["d"],
        "Heikin-Ashi H1 по сделке": lambda x: ha[x["sig"]] == x["d"],
        "EMA200 H1 по сделке": lambda x: e200h1[x["sig"]] == x["d"],
        "VWAP дня по сделке (BUY выше, SELL ниже)": lambda x: (cv[x["sig"]] - vwap[x["sig"]]) * x["d"] > 0,
        "Открытие дня по сделке": lambda x: (cv[x["sig"]] - day_open[x["sig"]]) * x["d"] > 0,
        "Открытие недели по сделке": lambda x: (cv[x["sig"]] - week_open[x["sig"]]) * x["d"] > 0,
        "ADX H1 ≥ 20": lambda x: adx_h1[x["sig"]] >= 20,
        "ADX H1 < 40": lambda x: adx_h1[x["sig"]] < 40,
        "Choppiness H1 < 61.8 (не боковик)": lambda x: chop_h1[x["sig"]] < 61.8,
        "Choppiness H1 > 38.2 (не перегретый тренд)": lambda x: chop_h1[x["sig"]] > 38.2,
        "RSI H1: BUY не выше 75, SELL не ниже 25": lambda x: not (rsi_h1[x["sig"]] - 50) * x["d"] > 25,
        "RSI H1: BUY не выше 70, SELL не ниже 30": lambda x: not (rsi_h1[x["sig"]] - 50) * x["d"] > 20,
        "без сделок 20–23 UTC (ролловер, широкий спред)": lambda x: not 20 <= hr[x["sig"]] <= 23,
        "без сделок 00–06 UTC (Азия)": lambda x: hr[x["sig"]] >= 7,
        "только 07–17 UTC (Лондон + Нью-Йорк)": lambda x: 7 <= hr[x["sig"]] < 17,
        "без сделок в понедельник до 07 UTC": lambda x: not (wd[x["sig"]] == 0 and hr[x["sig"]] < 7),
        "без сделок в пятницу после 16 UTC": lambda x: not (wd[x["sig"]] == 4 and hr[x["sig"]] >= 16),
        "без сделок 12:30–14:00 UTC (данные США)": lambda x: not (750 <= hr[x["sig"]] * 60 + idx.minute[x["sig"]] < 840),
    }
    return strategies, filters


HEAD = G.HEAD.replace("| после 07.2025 |", "| после 07.2025 | Стресс +0.30 $ | Зеркало |") \
    .replace("|---|---|---|---|---|---|---|---|---|", "|---|---|---|---|---|---|---|---|---|---|---|")


def main():
    D0, df = setup()
    D, h1, pin = prepare(D0, df)
    Dm0, dfm = load(mirror=True), None
    m5m = load_mt5_csv()
    k = 2 * m5m.close.mean()
    m5m = m5m.assign(open=k - m5m.open, high=k - m5m.low, low=k - m5m.high, close=k - m5m.close)
    dfm = resample(m5m, "15min")
    Dm, h1m, pinm = prepare(Dm0, dfm)
    strat, filt = candidates(df, h1)
    strat_m, filt_m = candidates(dfm, h1m)

    b = run(D, df, pin)
    bs = run(D, df, pin, slip=SLIP)
    bm = run(Dm, dfm, pinm)

    def line(name, s, ss, sm):
        ok = s["tot"] > b["tot"] and s["a"] > b["a"] and s["b"] > b["b"] and ss["tot"] > bs["tot"] and sm["tot"] > bm["tot"]
        mark = " ✅" if ok else ""
        return G.row(name + mark, s) + f" {ss['tot']:+.0f} % | {sm['tot']:+.0f} % |", ok

    L = ["# Новые индикаторы и стратегии: проверка на истории", "",
         "Свечи XAUUSD M15 01.12.2023 – 21.08.2026. База — обычный счёт как в боте сейчас: 5 стратегий, стоп 2 ATR,",
         "50 % на +1R и безубыток, тейк 3R, ADX-фильтр пробоев, лот ×0.75 / ×1.5, стоп дня после 4-го SL,",
         "пин-бар H1 против сигнала за 2 ч — пропуск. Риск 1 % от старта, спред брокера учтён.",
         f"«Стресс» — то же с издержками +{SLIP:.2f} $ на каждую сделку (проскальзывание, комиссия).",
         "«Зеркало» — график перевёрнут (рост ↔ падение): проверка, что прибыль не только от роста золота.",
         "✅ — лучше базы по итогу, в обеих половинах истории, со стрессом и на зеркале.",
         "Повторить: `python scripts/indicator_research.py`.", "",
         "## 1. Новая 6-я стратегия (то же сопровождение, что у остальных)", "", HEAD,
         G.row("**как сейчас**", b) + f" {bs['tot']:+.0f} % | {bm['tot']:+.0f} % |"]
    good = []
    for name, sig in strat.items():
        ex = {"new": sig}
        exm = {"new": strat_m[name]}
        s, ss, sm = run(D, df, pin, ex), run(D, df, pin, ex, slip=SLIP), run(Dm, dfm, pinm, exm)
        ln, ok = line(name, s, ss, sm)
        L.append(ln)
        print(ln, flush=True)
        if ok:
            good.append(("strat", name))
    L += ["", "## 2. Фильтр сигналов бота (сделка пропускается, если условие не выполнено)", "", HEAD,
          G.row("**как сейчас**", b) + f" {bs['tot']:+.0f} % | {bm['tot']:+.0f} % |"]
    for name, f in filt.items():
        s, ss, sm = run(D, df, pin, keep=f), run(D, df, pin, keep=f, slip=SLIP), run(Dm, dfm, pinm, keep=filt_m[name])
        ln, ok = line(name, s, ss, sm)
        L.append(ln)
        print(ln, flush=True)
        if ok:
            good.append(("filt", name))
    # 3. соседние настройки двух лучших и обе вместе — как добавлено в бота
    L += ["", "## 3. Соседние настройки и обе стратегии вместе", "",
          "Азия — диапазон 00:00–07:00 Лондона, пробой закрытием до указанного часа Лондона, один раз в день.",
          "Дончиан H1 — первая свеча H1, закрывшаяся за каналом n часов, только по дневному тренду (EMA50).", "",
          HEAD, G.row("**как сейчас**", b) + f" {bs['tot']:+.0f} % | {bm['tot']:+.0f} % |"]

    def dch(d, n):
        s_ = donchian_h1(d, n)
        return np.where(s_ == htf_trend(d, "1D", 50), s_, 0).astype(np.int8)

    asia = lambda d, end: _range_breakout(d, "Europe/London", 0, 7 * 60, end * 60)  # noqa: E731
    variants = [(f"Азия до {e}:00 Лондона", (lambda e: lambda d: {"asia": asia(d, e)})(e)) for e in (11, 13, 16)]
    variants += [(f"Дончиан {n} H1 по дневному тренду", (lambda n: lambda d: {"dch1": dch(d, n)})(n))
                 for n in (40, 55, 70, 100, 120)]
    variants += [(f"Азия до 16:00 + Дончиан {n} H1", (lambda n: lambda d: {"asia": asia(d, 16), "dch1": dch(d, n)})(n))
                 for n in (55, 70, 100, 120)]
    for name, mk in variants:
        ex, exm = mk(df), mk(dfm)
        s, ss, sm = run(D, df, pin, ex), run(D, df, pin, ex, slip=SLIP), run(Dm, dfm, pinm, exm)
        ln, _ = line(("**" + name + " — в боте**") if name.endswith("Дончиан 100 H1") else name, s, ss, sm)
        L.append(ln)
        print(ln, flush=True)
    L += ["", "## Вывод", "",
          "* **Фильтры (Supertrend, Ichimoku, VWAP, открытие дня/недели, ADX, Choppiness, RSI, часы, дни недели)** —",
          "  ни один не поднял прибыль: все режут хорошие сделки вместе с плохими. Некоторые снижают просадку",
          "  (открытие дня: 19 % вместо 30 % при +327 %), но правило — сначала прибыль. Не добавлены.",
          "* **Новые стратегии, прошедшие все проверки (✅):** пробой азиатского диапазона, Дончиан 55 H1,",
          "  Supertrend H1 по тренду, RSI-дивергенция H1 по тренду. Supertrend и RSI-дивергенция неустойчивы",
          "  к настройкам (Supertrend 3.5 и 4 хуже базы в первой половине) — не добавлены.",
          "* **Добавлены в бота две:** пробой Азии до 16:00 Лондона и Дончиан 100 H1 по дневному тренду.",
          "  Вместе: +517 % против +359 %, просадка 32 % против 30 %, итог/просадка 16.1 против 12.0;",
          "  лучше в обеих половинах истории, со стрессом издержек и на зеркальном графике. Все соседние",
          "  настройки (Азия до 11/13/16, Дончиан 40–120) тоже лучше базы по прибыли.",
          "* Честно: у Дончиана 55–70 вместе с Азией просадка выше (39–40 %), то есть просадка зависит от",
          "  настройки сильнее, чем прибыль. Дней хуже −3 % больше (101 против 68): сделок стало больше.",
          "* Сама Азия в одиночку слабая (+0.04R на сделку); половину её прибавки дают сделки других стратегий,",
          "  которые она подтверждает (лот ×1.5 при согласии). Дончиан 100 H1 сильный сам: +0.22R на сделку."]
    out = Path(__file__).resolve().parent.parent / "reports" / "indicator_research.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("GOOD:", good)


if __name__ == "__main__":
    main()
