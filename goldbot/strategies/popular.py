"""Популярные стратегии для сравнения."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators import atr, ema, rsi


def _cross(a: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series]:
    up = (a > b) & (a.shift() <= b.shift())
    dn = (a < b) & (a.shift() >= b.shift())
    return up, dn


def _to_sig(buy: pd.Series, sell: pd.Series) -> np.ndarray:
    return (buy.astype(np.int8) - sell.astype(np.int8)).to_numpy()


def ema_cross_rsi(df):
    up, dn = _cross(ema(df.close, 9), ema(df.close, 21))
    r = rsi(df.close, 14)
    return _to_sig(up & (r < 70), dn & (r > 30))


def macd_trend(df):
    macd = ema(df.close, 12) - ema(df.close, 26)
    up, dn = _cross(macd, ema(macd, 9))
    t = ema(df.close, 200)
    return _to_sig(up & (macd < 0) & (df.close > t), dn & (macd > 0) & (df.close < t))


def bollinger_rsi(df):
    m = df.close.rolling(20).mean()
    sd = df.close.rolling(20).std()
    r = rsi(df.close, 14)
    buy = (df.close < m - 2 * sd) & (r < 30)
    sell = (df.close > m + 2 * sd) & (r > 70)
    return _to_sig(buy & ~buy.shift(fill_value=False), sell & ~sell.shift(fill_value=False))


def donchian_breakout(df):
    hi = df.high.rolling(20).max().shift()
    lo = df.low.rolling(20).min().shift()
    t = ema(df.close, 200)
    buy = (df.close > hi) & (df.close > t)
    sell = (df.close < lo) & (df.close < t)
    return _to_sig(buy & ~buy.shift(fill_value=False), sell & ~sell.shift(fill_value=False))


def supertrend(df, n: int = 10, mult: float = 3.0):
    a = atr(df, n).to_numpy()
    hl2 = ((df.high + df.low) / 2).to_numpy()
    c = df.close.to_numpy()
    up, dn = hl2 - mult * a, hl2 + mult * a
    d = np.ones(len(df), dtype=np.int8)
    for i in range(1, len(df)):
        up[i] = max(up[i], up[i - 1]) if c[i - 1] > up[i - 1] else up[i]
        dn[i] = min(dn[i], dn[i - 1]) if c[i - 1] < dn[i - 1] else dn[i]
        d[i] = 1 if c[i] > dn[i - 1] else -1 if c[i] < up[i - 1] else d[i - 1]
    sig = np.zeros(len(df), dtype=np.int8)
    flip = np.r_[False, d[1:] != d[:-1]]
    sig[flip] = d[flip]
    return sig


def donchian_h1(df, n: int = 100):
    """Пробой канала Дончиана n свечей H1 (закрытие H1 выше максимума / ниже минимума прошлых n часов),
    только первая свеча пробоя. Работает на M15: сигнал на свече M15, которой закрывается час
    (reports/indicator_research.md). Незакрытый час в конце df сигнала не даёт."""
    h1 = df.resample("1h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    x = np.where(h1.close > h1.high.rolling(n).max().shift(), 1,
                 np.where(h1.close < h1.low.rolling(n).min().shift(), -1, 0))
    x = np.where(x != np.r_[0, x[:-1]], x, 0)
    s = pd.Series(x, index=h1.index + pd.Timedelta(minutes=45))
    return s.reindex(df.index).fillna(0).to_numpy().astype(np.int8)
