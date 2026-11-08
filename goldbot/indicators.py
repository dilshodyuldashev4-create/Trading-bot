"""Индикаторы на pandas/numpy."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def pivot_high(h: np.ndarray, n: int) -> np.ndarray:
    """Как ta.pivothigh(high, n, n): значение появляется на баре i (пивот на i-n), иначе NaN."""
    out = np.full(len(h), np.nan)
    for i in range(2 * n, len(h)):
        c = i - n
        win = h[c - n:i + 1]
        if h[c] == win.max() and (win[:n] < h[c]).all() and (win[n + 1:] <= h[c]).all():
            out[i] = h[c]
    return out


def pivot_low(l: np.ndarray, n: int) -> np.ndarray:
    return -pivot_high(-l, n)
