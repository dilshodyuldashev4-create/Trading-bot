"""Сильный отскок против дневного тренда: разрешать ли покупки (или продажи), когда цена резко ушла от дна
(вершины), хотя дневной close ещё ниже (выше) EMA50? Проверка на истории XAUUSD M15 12.2023 – 08.2026.

База — бот как сейчас (10 стратегий, новостное правило «все High −10…+15 мин», как в news_research.py).
Фильтр тренда меняется только у 7 стратегий, которые торгуют по дневному тренду
(squeeze, fvg_m15, liq_m15, donchian_h1, days5, kama_h4, klinger_h4). asia, donchian (EMA200), amd — без изменений.

Варианты фильтра:
  * быстрее тренд: дневная EMA20, H4 EMA50 / EMA200, текущая цена против дневной EMA50;
  * «отскок»: дневной тренд вниз, но цена уже на k ATR дня выше минимума последних N дней →
    разрешить и покупки (обе стороны) или только покупки (переворот). Зеркально для роста;
  * «возврат уровня»: цена закрылась выше вчерашнего максимума / H4 EMA50 против тренда → разрешить обе стороны.

    python scripts/rebound_research.py      # отчёт: reports/rebound_table.md
"""
from __future__ import annotations

import sys
import warnings
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
warnings.filterwarnings("ignore")

import challenge_research as C  # noqa: E402
import indicator_research as R  # noqa: E402
import news_research as N  # noqa: E402
from goldbot.data import load_mt5_csv, resample  # noqa: E402
from goldbot.indicators import ema  # noqa: E402
from goldbot.strategies.fvg_bos import fvg_bos_signals  # noqa: E402
from goldbot.strategies.popular import days_breakout, donchian_h1, kama_h4, klinger_h4  # noqa: E402
from goldbot.strategies.research import htf_trend, squeeze_breakout, swing_sweep  # noqa: E402
from goldbot.strategies.sessions import asian_breakout_day  # noqa: E402


# ---------- фильтры: (можно BUY, можно SELL) на каждой свече M15 ----------

def daily(df):
    d = df.resample("1D").agg(dict(high="max", low="min", close="last")).dropna()
    pc = d.close.shift()
    tr = pd.concat([d.high - d.low, (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1)
    return d, tr.ewm(alpha=1 / 14, adjust=False).mean()


def closed_days(df, s):
    """Значение дневного ряда s, известное на свече M15 (только по закрытым дням)."""
    return s.shift().reindex(df.index.normalize()).to_numpy()


def from_side(tr):
    tr = np.asarray(tr)
    return tr == 1, tr == -1


def f_base(df):
    return from_side(htf_trend(df, "1D", 50))


def f_htf(rule, n):
    return lambda df: from_side(htf_trend(df, rule, n))


def f_live_price(df):
    """Текущая цена (close M15) против дневной EMA50 по закрытым дням."""
    d, _ = daily(df)
    e = closed_days(df, ema(d.close, 50))
    c = df.close.to_numpy()
    return c > e, c < e


def rebound(df, k, n, mode):
    """Дневной тренд вниз, но close M15 выше минимума последних n дней (включая сегодня до этой свечи) на k ATR дня
    → mode='both': можно и BUY; mode='flip': только BUY. Зеркально при тренде вверх."""
    up, dn = f_base(df)
    d, a = daily(df)
    atr_d = closed_days(df, a)
    day = df.index.normalize()
    lo_prev = closed_days(df, d.low.rolling(n - 1).min()) if n > 1 else np.full(len(df), np.inf)
    hi_prev = closed_days(df, d.high.rolling(n - 1).max()) if n > 1 else np.full(len(df), -np.inf)
    lo_today = df.low.groupby(day).cummin().to_numpy()
    hi_today = df.high.groupby(day).cummax().to_numpy()
    lo, hi = np.fmin(lo_prev, lo_today), np.fmax(hi_prev, hi_today)
    c = df.close.to_numpy()
    reb_up = dn & (c - lo >= k * atr_d)     # отскок вверх против нисходящего тренда
    reb_dn = up & (hi - c >= k * atr_d)     # падение против восходящего тренда
    if mode == "both":
        return up | reb_up, dn | reb_dn
    return (up & ~reb_dn) | reb_up, (dn & ~reb_up) | reb_dn


def reclaim(df, kind):
    up, dn = f_base(df)
    c = df.close.to_numpy()
    if kind == "prevday":
        d, _ = daily(df)
        bu, bd = c > closed_days(df, d.high), c < closed_days(df, d.low)
    else:  # H4 EMA50
        t = htf_trend(df, "4h", 50)
        bu, bd = t == 1, t == -1
    return up | (dn & bu), dn | (up & bd)


def f_rebound(k, n, mode):
    return lambda df: rebound(df, k, n, mode)


def f_reclaim(kind):
    return lambda df: reclaim(df, kind)


def f_none(df):
    z = np.ones(len(df), dtype=bool)
    return z, z


VARIANTS = [
    ("**как сейчас: дневная EMA50**", f_base),
    ("без фильтра тренда", f_none),
    ("дневная EMA20", f_htf("1D", 20)),
    ("H4 EMA50", f_htf("4h", 50)),
    ("H4 EMA200", f_htf("4h", 200)),
    ("текущая цена против дневной EMA50", f_live_price),
    ("отскок 2 ATR дня от минимума 5 дней → обе стороны", f_rebound(2, 5, "both")),
    ("отскок 3 ATR / 5 дней → обе стороны", f_rebound(3, 5, "both")),
    ("отскок 4 ATR / 5 дней → обе стороны", f_rebound(4, 5, "both")),
    ("отскок 3 ATR / 10 дней → обе стороны", f_rebound(3, 10, "both")),
    ("отскок 4 ATR / 10 дней → обе стороны", f_rebound(4, 10, "both")),
    ("отскок 2 ATR / 5 дней → только по отскоку", f_rebound(2, 5, "flip")),
    ("отскок 3 ATR / 5 дней → только по отскоку", f_rebound(3, 5, "flip")),
    ("отскок 4 ATR / 10 дней → только по отскоку", f_rebound(4, 10, "flip")),
    ("закрытие за вчерашним хаем / лоем против тренда → обе стороны", f_reclaim("prevday")),
    ("H4 EMA50 против дневного тренда → обе стороны", f_reclaim("h4")),
]


# ---------- сборка портфеля с выбранным фильтром ----------

def filt(sig, ok):
    up, dn = ok
    s = np.asarray(sig)
    return np.where(((s == 1) & up) | ((s == -1) & dn), s, 0).astype(np.int8)


def build(mirror, fn):
    m5 = load_mt5_csv()
    if mirror:
        k = 2 * m5.close.mean()
        m5 = m5.assign(open=k - m5.open, high=k - m5.low, low=k - m5.high, close=k - m5.close)
    df = resample(m5, "15min")
    ok = fn(df)
    D0 = C.load(mirror)
    D0["sig"] = dict(D0["sig"])
    D0["sig"]["squeeze"] = filt(squeeze_breakout(df), ok)
    D0["sig"]["fvg_m15"] = filt(fvg_bos_signals(df), ok)
    D0["sig"]["liq_m15"] = filt(swing_sweep(df), ok)
    D, _, pin = R.prepare(D0, df)
    E = {"asia": asian_breakout_day(df).astype(np.int8), "donchian_h1": filt(donchian_h1(df), ok),
         "days5": filt(days_breakout(df, 5), ok), "kama_h4": filt(kama_h4(df), ok), "klinger_h4": filt(klinger_h4(df), ok)}
    blk = N.window_mask(df.index, N.high_approx(df.index), 10, 15)
    return D, df, pin, E, blk


def job(i):
    name, fn = VARIANTS[i]
    D, df, pin, E, blk = build(False, fn)
    hot = N.window_mask(df.index, N.high_approx(df.index), 5, 15)
    s = N.run(D, df, pin, E, blk)
    ss = N.run(D, df, pin, E, blk, slip=R.SLIP, news_hot=hot, news_slip=1.0)
    Dm, dfm, pinm, Em, blkm = build(True, fn)
    sm = N.run(Dm, dfm, pinm, Em, blkm)
    # сделки на «отскоках»: против дневной EMA50
    tr = htf_trend(df, "1D", 50)
    cnt = [x for x in s["taken"] if tr[x["sig"]] == -x["d"]]
    r = np.array([x["r"] for x in cnt]) if cnt else np.array([0.0])
    extra = f" {len(cnt)} | {r.mean():+.2f}R |"
    return i, N.row(name, s, ss, sm) + extra, s


def main():
    head = N.HEAD.replace("| Зеркало |", "| Зеркало | Сделок против EMA50 | R этих сделок |").replace(
        "|---|---|---|---|---|---|---|---|---|---|---|---|", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    rows = {}
    with Pool(4) as p:
        for i, ln, _ in p.imap_unordered(job, range(len(VARIANTS))):
            rows[i] = ln
            print(ln, flush=True)
    L = [head] + [rows[i] for i in range(len(VARIANTS))]
    out = Path(__file__).resolve().parent.parent / "reports" / "rebound_table.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
