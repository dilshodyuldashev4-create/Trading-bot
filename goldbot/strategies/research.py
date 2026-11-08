"""Дополнительные стратегии для исследования (ноябрь 2026): фильтры тренда старшего ТФ и
популярные у трейдеров золота сетапы 2025–2026.

Фильтр тренда берётся только по уже закрытым дневным / 4-часовым свечам (без заглядывания вперёд).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators import atr, ema, rsi
from .sessions import _local, _minutes, asian_range_breakout, ny_opening_range, silver_bullet


def htf_trend(df: pd.DataFrame, rule: str = "1D", n: int = 50) -> np.ndarray:
    """+1 если close последней закрытой свечи старшего ТФ выше её EMA(n), -1 если ниже."""
    agg = df.close.resample(rule, label="left", closed="left").last().dropna()
    e = ema(agg, n)
    side = np.sign(agg - e)
    # значение доступно только после закрытия свечи старшего ТФ
    side.index = side.index + pd.Timedelta(rule)
    return side.reindex(df.index, method="ffill").fillna(0).to_numpy().astype(np.int8)


def _filter(sig: np.ndarray, trend: np.ndarray) -> np.ndarray:
    return np.where(sig == trend, sig, 0).astype(np.int8)


def with_trend(fn, rule: str = "1D", n: int = 50):
    return lambda df: _filter(fn(df), htf_trend(df, rule, n))


def combo(df):
    a, b = asian_range_breakout(df), silver_bullet(df)
    return np.where(a != 0, a, b).astype(np.int8)


def combo3(df):
    a, b, c = asian_range_breakout(df), silver_bullet(df), ny_opening_range(df)
    return np.where(a != 0, a, np.where(b != 0, b, c)).astype(np.int8)


def prev_day_breakout(df):
    """Пробой хая/лоя прошлого дня закрытием свечи, 07:00–16:00 Лондона, один сигнал в день."""
    t = _local(df, "Europe/London")
    m, day = _minutes(t), t.normalize()
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    sig = np.zeros(len(df), dtype=np.int8)
    cur, pdh, pdl, dh, dl, done = None, np.nan, np.nan, -np.inf, np.inf, False
    for i in range(len(df)):
        if day[i] != cur:
            if cur is not None:
                pdh, pdl = dh, dl
            cur, dh, dl, done = day[i], -np.inf, np.inf, False
        if not done and not np.isnan(pdh) and 420 <= m[i] < 960:
            if c[i] > pdh:
                sig[i], done = 1, True
            elif c[i] < pdl:
                sig[i], done = -1, True
        dh, dl = max(dh, h[i]), min(dl, l[i])
    return sig


def london_open_trend(df):
    """Простейший сетап «вход на открытии Лондона по дневному тренду» (08:00 Лондона)."""
    t = _local(df, "Europe/London")
    m = _minutes(t)
    tr = htf_trend(df, "1D", 50)
    sig = np.where(m == 8 * 60, tr, 0).astype(np.int8)
    return sig


def rsi_pullback(df):
    """Откат RSI(14) ниже 40 / выше 60 и возврат при дневном тренде (по закрытию свечи)."""
    r = rsi(df.close, 14)
    tr = htf_trend(df, "1D", 50)
    up = ((r > 40) & (r.shift() <= 40)).to_numpy() & (tr == 1)
    dn = ((r < 60) & (r.shift() >= 60)).to_numpy() & (tr == -1)
    return (up.astype(np.int8) - dn.astype(np.int8))


def inside_bar(df):
    """Пробой внутреннего бара по тренду EMA200."""
    h, l, c = df.high, df.low, df.close
    ib = (h.shift() < h.shift(2)) & (l.shift() > l.shift(2))
    t = ema(c, 200)
    buy = ib & (c > h.shift()) & (c > t)
    sell = ib & (c < l.shift()) & (c < t)
    return (buy.astype(np.int8) - sell.astype(np.int8)).to_numpy()


def squeeze_breakout(df):
    """Сжатие Боллинджера внутри Кельтнера и выход по направлению закрытия за полосу."""
    m = df.close.rolling(20).mean()
    sd = df.close.rolling(20).std()
    a = atr(df, 20)
    squeeze = ((m + 2 * sd) < (m + 1.5 * a)) & ((m - 2 * sd) > (m - 1.5 * a))
    was = squeeze.shift().fillna(False).astype(bool)
    buy = was & ~squeeze & (df.close > m + 2 * sd)
    sell = was & ~squeeze & (df.close < m - 2 * sd)
    return (buy.astype(np.int8) - sell.astype(np.int8)).to_numpy()


def vwap_pullback(df):
    """Дневной VWAP (с 00:00 UTC): касание VWAP и закрытие от него по дневному тренду, 07:00–17:00 UTC."""
    tp = (df.high + df.low + df.close) / 3
    vol = df.volume.replace(0, 1)
    day = df.index.normalize()
    vwap = (tp * vol).groupby(day).cumsum() / vol.groupby(day).cumsum()
    tr = htf_trend(df, "1D", 50)
    hr = df.index.hour.to_numpy()
    sess = (hr >= 7) & (hr < 17)
    up = ((df.low <= vwap) & (df.close > vwap) & (df.close > df.open)).to_numpy() & (tr == 1) & sess
    dn = ((df.high >= vwap) & (df.close < vwap) & (df.close < df.open)).to_numpy() & (tr == -1) & sess
    return (up.astype(np.int8) - dn.astype(np.int8))


def engulfing_ema(df):
    """Поглощение у EMA50 по тренду EMA50/EMA200."""
    o, c, h, l = df.open, df.close, df.high, df.low
    e50, e200 = ema(c, 50), ema(c, 200)
    bull = (c > o) & (o.shift() > c.shift()) & (c >= o.shift()) & (o <= c.shift())
    bear = (c < o) & (o.shift() < c.shift()) & (c <= o.shift()) & (o >= c.shift())
    near = (l <= e50) | (l.shift() <= e50)
    near_s = (h >= e50) | (h.shift() >= e50)
    buy = bull & near & (e50 > e200) & (c > e50)
    sell = bear & near_s & (e50 < e200) & (c < e50)
    return (buy.astype(np.int8) - sell.astype(np.int8)).to_numpy()


def buy_only(fn):
    return lambda df: np.where(fn(df) == 1, 1, 0).astype(np.int8)
