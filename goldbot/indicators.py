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


def adx(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    """ADX Уайлдера: сила тренда (выше 25 — сильное движение в одну сторону)."""
    h, l, c = df["high"], df["low"], df["close"]
    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    a = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pdm.ewm(alpha=1 / n, adjust=False).mean() / a
    mdi = 100 * mdm.ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean().to_numpy()


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
