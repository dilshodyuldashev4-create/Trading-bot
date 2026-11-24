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


def days_breakout(df, n: int = 5):
    """Пробой максимума / минимума последних n закрытых дней (UTC) закрытием свечи, первый пробой за день
    (reports/profit2_research.md). Сегодняшний день в уровень не входит."""
    day = df.index.normalize()
    d = df.resample("1D").agg({"high": "max", "low": "min"}).dropna()
    hi = d.high.rolling(n).max().shift().reindex(day).to_numpy()
    lo = d.low.rolling(n).min().shift().reindex(day).to_numpy()
    c = df.close.to_numpy()
    sig = np.where(c > hi, 1, np.where(c < lo, -1, 0))
    s = pd.Series(sig, index=df.index)
    first = s.ne(0).groupby(day).cumsum().to_numpy()
    return np.where((sig != 0) & (first == 1), sig, 0).astype(np.int8)


def kama(close: np.ndarray, n: int = 10, fast: int = 2, slow: int = 30) -> np.ndarray:
    """Адаптивная скользящая средняя Кауфмана (KAMA): быстрая в тренде, медленная в боковике."""
    c = np.asarray(close, dtype=float)
    out = np.full(len(c), np.nan)
    f, s = 2 / (fast + 1), 2 / (slow + 1)
    for i in range(n, len(c)):
        vol = np.abs(np.diff(c[i - n:i + 1])).sum()
        er = abs(c[i] - c[i - n]) / vol if vol else 0.0
        sc = (er * (f - s) + s) ** 2
        out[i] = c[i] if np.isnan(out[i - 1]) else out[i - 1] + sc * (c[i] - out[i - 1])
    return out


def kama_h4(df, n: int = 10):
    """Закрытие свечи H4 пересекло KAMA(n) H4: выше — BUY, ниже — SELL (только свеча пересечения).
    Работает на M15: сигнал на свече M15, которой закрывается H4 (свечи H4 с 00:00 UTC).
    Незакрытая H4 в конце df сигнала не даёт (reports/profit3_research.md, вторая волна)."""
    h4 = df.resample("4h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    c = h4.close.to_numpy()
    k = kama(c, n)
    x = np.where(c > k, 1, np.where(c < k, -1, 0))
    x = np.where(x != np.r_[0, x[:-1]], x, 0)
    s = pd.Series(x, index=h4.index + pd.Timedelta(hours=3, minutes=45))
    return s.reindex(df.index).fillna(0).to_numpy().astype(np.int8)
