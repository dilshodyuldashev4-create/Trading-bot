"""Ещё идеи для прибыли поверх бота с 7 стратегиями (после PR 51: + пробой Азии и Дончиан 100 H1).

1) Старые стратегии бота на H1/H4 как отдельные сигналы (Squeeze, FVG+BOS, снятие ликвидности, Дончиан H4).
2) Новые пробои: узкий день (NR4/NR7), внутренний день, хай/лой прошлой недели, первый час Нью-Йорка.
3) Размер лота: тройное согласие, окно согласия, вес стратегий по первой половине истории.

Проверка как в indicator_research.py: обе половины истории, стресс издержек +0.30 $, зеркальный график.

    python scripts/profit2_research.py   # отчёт в reports/profit2_research.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import day_guard_research as G  # noqa: E402
import indicator_research as R  # noqa: E402
import profit_research as P  # noqa: E402
from challenge_research import KEYS, load  # noqa: E402
from goldbot.data import PIP, load_mt5_csv, resample  # noqa: E402
from goldbot.indicators import atr  # noqa: E402
from goldbot.strategies.fvg_bos import fvg_bos_signals  # noqa: E402
from goldbot.strategies.popular import days_breakout, donchian_h1  # noqa: E402
from goldbot.strategies.research import htf_trend, squeeze_breakout, swing_sweep  # noqa: E402
from goldbot.strategies.sessions import _range_breakout, asian_breakout_day  # noqa: E402
from ideas_research import SPLIT  # noqa: E402

SLIP = R.SLIP


def bot_extra(df):
    s = donchian_h1(df)
    return {"asia": asian_breakout_day(df),
            "donchian_h1": np.where(s == htf_trend(df, "1D", 50), s, 0).astype(np.int8)}


def htf_events(df, rule, fn):
    """Стратегия fn на старшем ТФ rule → сигнал на свече M15, которой закрывается свеча rule."""
    x = resample(df, rule)
    sig = np.asarray(fn(x))
    step = pd.Timedelta(rule) - pd.Timedelta(minutes=15)
    s = pd.Series(sig, index=x.index + step)
    s = s[~s.index.duplicated()]
    return s.reindex(df.index).fillna(0).to_numpy().astype(np.int8)


def dc_first(x, n):
    v = np.where(x.close > x.high.rolling(n).max().shift(), 1, np.where(x.close < x.low.rolling(n).min().shift(), -1, 0))
    return np.where(v != np.r_[0, v[:-1]], v, 0)


def trend(df, s):
    return np.where(np.asarray(s) == htf_trend(df, "1D", 50), s, 0).astype(np.int8)


def daily_pattern_breakout(df, kind, end_h=20):
    """Вчерашний день узкий (NRn) или внутренний — сегодня первый пробой его хая/лоя закрытием M15 до end_h UTC."""
    d = df.resample("1D").agg(dict(high="max", low="min")).dropna()
    rng = d.high - d.low
    if kind.startswith("nr"):
        n = int(kind[2:])
        ok = rng <= rng.rolling(n).min()
    else:  # inside
        ok = (d.high <= d.high.shift()) & (d.low >= d.low.shift())
    nxt = lambda s: s.shift().reindex(df.index.normalize()).to_numpy()  # noqa: E731
    ph, pl, flag = nxt(d.high), nxt(d.low), nxt(ok.astype(float))
    c = df.close.to_numpy()
    h = df.index.hour
    win = (flag == 1) & (h >= 1) & (h < end_h)
    sig = np.where(win & (c > ph), 1, np.where(win & (c < pl), -1, 0))
    return R.once_per_day(sig, df.index)


def prev_week_breakout(df):
    w = df.resample("W-SUN").agg(dict(high="max", low="min")).dropna()   # неделя пн–вс, метка — воскресенье
    key = (df.index.normalize() - pd.to_timedelta(df.index.weekday, unit="D")) - pd.Timedelta(days=1)
    ph = w.high.reindex(key).to_numpy()
    pl = w.low.reindex(key).to_numpy()
    c = df.close.to_numpy()
    sig = np.where(c > ph, 1, np.where(c < pl, -1, 0))
    wk = pd.Series(key, index=df.index)
    s = pd.Series(sig, index=df.index)
    first = s.ne(0).groupby(wk.values).cumsum()
    return np.where((s != 0) & (first == 1), sig, 0).astype(np.int8)


def run2(D, df, pin, extra, slip=0.0, agree_bars=3, strong=1.5, single=0.75, triple=None, weights=None):
    keys = KEYS + tuple(extra)
    D2 = dict(D)
    D2["sig"] = {**D["sig"], **extra}
    opp = np.zeros(len(df), dtype=int)
    for k in keys:
        opp = np.where(opp == 0, D2["sig"][k], opp)
    P.KEYS = keys
    trades = P.simulate(D2, dict(c=df.close.to_numpy(), atr=atr(df, 14).to_numpy(), opp=opp))
    P.KEYS = KEYS
    if slip:
        for x in trades:
            x["r"] -= slip / (D2["sl"][x["sig"]] * PIP)
    sigs = np.stack([D2["sig"][k] for k in keys])
    trades = [x for x in trades if pin[x["sig"]] != -x["d"]]

    def n_agree(x):
        ki = keys.index(x["key"])
        lo = max(0, x["sig"] - agree_bars)
        return int((np.delete(sigs[:, lo:x["sig"] + 1], ki, axis=0) == x["d"]).any(axis=1).sum())
    sizes = {}
    for x in trades:
        k = n_agree(x)
        s = single if k == 0 else (triple if triple and k >= 2 else strong)
        sizes[id(x)] = s * (weights or {}).get(x["key"], 1.0)
    G.KEYS = keys
    t, _ = G.portfolio(trades, df.index, G.Guard(day_sl=4), sizes)
    G.KEYS = KEYS
    rep = G.report(t, df.index)
    rep["taken"] = t
    return rep


def main():
    D0, df = R.setup()
    D, h1, pin = R.prepare(D0, df)
    m5m = load_mt5_csv()
    k = 2 * m5m.close.mean()
    m5m = m5m.assign(open=k - m5m.open, high=k - m5m.low, low=k - m5m.high, close=k - m5m.close)
    dfm = resample(m5m, "15min")
    Dm, _, pinm = R.prepare(load(mirror=True), dfm)
    E, Em = bot_extra(df), bot_extra(dfm)

    b, bs, bm = run2(D, df, pin, E), run2(D, df, pin, E, slip=SLIP), run2(Dm, dfm, pinm, Em)
    rows = []

    def line(name, s, ss, sm):
        ok = s["tot"] > b["tot"] and s["a"] > b["a"] and s["b"] > b["b"] and ss["tot"] > bs["tot"] and sm["tot"] > bm["tot"]
        ln = G.row(name + (" ✅" if ok else ""), s) + f" {ss['tot']:+.0f} % | {sm['tot']:+.0f} % |"
        print(ln, flush=True)
        rows.append(ln)
        return ok

    base_ln = G.row("**как сейчас (7 стратегий)**", b) + f" {bs['tot']:+.0f} % | {bm['tot']:+.0f} % |"
    L = ["# Ещё идеи для прибыли: проверка на истории (после PR 51)", "",
         "Свечи XAUUSD M15 01.12.2023 – 21.08.2026. База — бот как сейчас: 7 стратегий (+ пробой Азии и Дончиан 100 H1),",
         "стоп 2 ATR, 50 % на +1R и безубыток, тейк 3R, ADX-фильтр пробоев, лот ×0.75 / ×1.5, стоп дня после 4-го SL,",
         "пин-бар H1 против сигнала за 2 ч — пропуск. Риск 1 % от старта. ✅ — лучше базы по итогу, в обеих половинах,",
         f"со стрессом издержек +{SLIP:.2f} $ на сделку и на зеркальном графике. Повторить: `python scripts/profit2_research.py`.", "",
         "## 1. Старые стратегии на H1 / H4 и новые пробои (8-я стратегия)", "", R.HEAD, base_ln]
    rows = L
    print(base_ln)

    def cands(d):
        return {
            "Squeeze H1 по дневному тренду": trend(d, htf_events(d, "1h", squeeze_breakout)),
            "FVG+BOS H1 по дневному тренду": trend(d, htf_events(d, "1h", fvg_bos_signals)),
            "Снятие ликвидности H1 по дневному тренду": trend(d, htf_events(d, "1h", swing_sweep)),
            "Squeeze H4 по дневному тренду": trend(d, htf_events(d, "4h", squeeze_breakout)),
            "FVG+BOS H4 по дневному тренду": trend(d, htf_events(d, "4h", fvg_bos_signals)),
            "Дончиан 20 H4 по дневному тренду": trend(d, htf_events(d, "4h", lambda x: dc_first(x, 20))),
            "Пробой после узкого дня NR4": daily_pattern_breakout(d, "nr4"),
            "Пробой после узкого дня NR7": daily_pattern_breakout(d, "nr7"),
            "Пробой после внутреннего дня": daily_pattern_breakout(d, "inside"),
            "Пробой после NR4 по дневному тренду": trend(d, daily_pattern_breakout(d, "nr4")),
            "Пробой хая/лоя прошлой недели": prev_week_breakout(d),
            "Пробой хая/лоя прошлой недели по тренду": trend(d, prev_week_breakout(d)),
            "Первый час Нью-Йорка (9:30–10:30), пробой до 16:00 NY": _range_breakout(d, "America/New_York", 570, 630, 960),
            "Первый час Лондона (8–9), пробой до 16:00 Лондона": _range_breakout(d, "Europe/London", 480, 540, 960),
        }
    C, Cm = cands(df), cands(dfm)
    good = []
    for name in C:
        ex, exm = {**E, "new": C[name]}, {**Em, "new": Cm[name]}
        if line(name, run2(D, df, pin, ex), run2(D, df, pin, ex, slip=SLIP), run2(Dm, dfm, pinm, exm)):
            good.append(name)

    L += ["", "## 2. Размер лота", "", R.HEAD, base_ln]
    for name, kw in (
        ("согласие 3+ стратегий — лот ×2", dict(triple=2.0)),
        ("согласие 3+ стратегий — лот ×1.75", dict(triple=1.75)),
        ("окно согласия 30 мин (сейчас 45–60)", dict(agree_bars=2)),
        ("окно согласия 2 ч", dict(agree_bars=8)),
        ("окно согласия 4 ч", dict(agree_bars=16)),
        ("одиночный ×0.5, согласие ×1.5", dict(single=0.5)),
        ("одиночный ×1.0, согласие ×1.5", dict(single=1.0)),
        ("одиночный ×0.75, согласие ×2", dict(strong=2.0)),
    ):
        line(name, run2(D, df, pin, E, **kw), run2(D, df, pin, E, slip=SLIP, **kw), run2(Dm, dfm, pinm, Em, **kw))

    # вес стратегии по средней R в первой половине (обучение), проверка — вторая половина
    t = b["taken"]
    first = pd.Series([x["r"] for x in t if df.index[x["i"]] < SPLIT],
                      index=[x["key"] for x in t if df.index[x["i"]] < SPLIT]).groupby(level=0).mean().sort_values()
    for lo_w, hi_w in ((0.75, 1.25), (0.5, 1.5)):
        w = {k_: lo_w for k_ in first.index[:2]} | {k_: hi_w for k_ in first.index[-2:]}
        name = (f"вес по 1-й половине: лучшие 2 ({', '.join(first.index[-2:])}) ×{hi_w:g}, "
                f"худшие 2 ({', '.join(first.index[:2])}) ×{lo_w:g}")
        line(name, run2(D, df, pin, E, weights=w), run2(D, df, pin, E, slip=SLIP, weights=w),
             run2(Dm, dfm, pinm, Em, weights=w))
    L += ["", "Средний R на сделку по стратегиям в первой половине (до 07.2025): " +
          ", ".join(f"{k_} {v:+.2f}" for k_, v in first.items())]
    L += ["", "## 3. Пробой хая / лоя последних N дней (первый за день, по дневному тренду) — соседние настройки", "",
          R.HEAD, base_ln]
    for n in (3, 5, 7, 10):
        f = lambda d, n=n: {**bot_extra(d), "days": trend(d, days_breakout(d, n))}  # noqa: E731
        line(f"**{n} дней — в боте**" if n == 5 else f"{n} дней", run2(D, df, pin, f(df)),
             run2(D, df, pin, f(df), slip=SLIP), run2(Dm, dfm, pinm, f(dfm)))
    f = lambda d: {**bot_extra(d), "days": trend(d, days_breakout(d, 5)), "nr": daily_pattern_breakout(d, "nr7")}  # noqa: E731
    line("5 дней + пробой после NR7", run2(D, df, pin, f(df)), run2(D, df, pin, f(df), slip=SLIP), run2(Dm, dfm, pinm, f(dfm)))
    L += ["", "## Вывод", "",
          "* **Добавлено в бота: пробой хая / лоя последних 5 дней по дневному тренду** (первый пробой за день).",
          "  +583 % против +517 %, просадка 32.0 % против 32.2 %, лучше в обеих половинах, со стрессом и на зеркале.",
          "  Соседние настройки 3–10 дней дают +574…+583 %. Сама стратегия: 235 сделок, +0.19R на сделку.",
          "* Пробой после узкого дня (NR5–NR10) устойчив и снижает просадку (28 %), но сделок мало (≈ 45 за 2.7 года),",
          "  прибавка +10…+14 % — не добавлено, можно позже.",
          "* FVG+BOS H1 и Дончиан 20 H4 добавляют прибыль, но просадка растёт до 37–38 % — не добавлено.",
          "* Лот: «согласие ×2» или «окно согласия 4 ч» дают больше прибыли, но это больший риск",
          "  (худший день до −8.8 %, просадка до 38 %); удвоение при согласии уже отклонялось раньше (profit_research).",
          "  Вес стратегий по первой половине снижает просадку до 26–29 %, но прибыль не растёт."]
    out = Path(__file__).resolve().parent.parent / "reports" / "profit2_research.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("GOOD:", good)


if __name__ == "__main__":
    main()
