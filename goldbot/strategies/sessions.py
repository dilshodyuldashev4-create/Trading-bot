"""Популярные у трейдеров золота сессионные стратегии (2024–2026).

Время в данных — UTC; окна сессий считаются в местном времени Лондона / Нью-Йорка,
поэтому переход на летнее время учитывается автоматически. Не больше одного сигнала в день.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators import ema


def _local(df: pd.DataFrame, tz: str) -> pd.DatetimeIndex:
    idx = df.index if df.index.tz is not None else df.index.tz_localize("UTC")
    return idx.tz_convert(tz)


def _minutes(t: pd.DatetimeIndex) -> np.ndarray:
    return (t.hour * 60 + t.minute).to_numpy()


def _range_breakout(df, tz, r_start, r_end, t_end):
    """Диапазон [r_start, r_end) местного времени, затем первый close за его пределы до t_end."""
    t = _local(df, tz)
    m, day = _minutes(t), t.normalize()
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    sig = np.zeros(len(df), dtype=np.int8)
    cur_day, hi, lo, done = None, -np.inf, np.inf, False
    for i in range(len(df)):
        if day[i] != cur_day:
            cur_day, hi, lo, done = day[i], -np.inf, np.inf, False
        if r_start <= m[i] < r_end:
            hi, lo = max(hi, h[i]), min(lo, l[i])
        elif r_end <= m[i] < t_end and not done and np.isfinite(hi):
            if c[i] > hi:
                sig[i], done = 1, True
            elif c[i] < lo:
                sig[i], done = -1, True
    return sig


def asian_range_breakout(df):
    """Азиатский диапазон 00:00–07:00 Лондона, пробой на лондонской сессии до 11:00."""
    return _range_breakout(df, "Europe/London", 0, 7 * 60, 11 * 60)


def ny_opening_range(df):
    """NY ORB: диапазон 9:30–9:45 Нью-Йорка, пробой до 12:00."""
    return _range_breakout(df, "America/New_York", 9 * 60 + 30, 9 * 60 + 45, 12 * 60)


def silver_bullet(df):
    """ICT Silver Bullet: первый FVG в окне 10:00–11:00 NY по направлению от открытия дня (00:00 NY)."""
    t = _local(df, "America/New_York")
    m, day = _minutes(t), t.normalize()
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    sig = np.zeros(len(df), dtype=np.int8)
    cur_day, day_open, done = None, np.nan, False
    for i in range(2, len(df)):
        if day[i] != cur_day:
            cur_day, day_open, done = day[i], o[i], False
        if done or not (600 <= m[i] < 660):
            continue
        if l[i] > h[i - 2] and c[i] > day_open:
            sig[i], done = 1, True
        elif h[i] < l[i - 2] and c[i] < day_open:
            sig[i], done = -1, True
    return sig


def liquidity_sweep(df):
    """Sweep хая/лоя прошлого дня (turtle soup): прокол уровня и close обратно, 07:00–16:00 Лондона."""
    t = _local(df, "Europe/London")
    m, day = _minutes(t), t.normalize()
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    sig = np.zeros(len(df), dtype=np.int8)
    cur_day, pdh, pdl, dh, dl, done = None, np.nan, np.nan, -np.inf, np.inf, False
    for i in range(len(df)):
        if day[i] != cur_day:
            if cur_day is not None:
                pdh, pdl = dh, dl
            cur_day, dh, dl, done = day[i], -np.inf, np.inf, False
        dh, dl = max(dh, h[i]), min(dl, l[i])
        if done or np.isnan(pdh) or not (420 <= m[i] < 960):
            continue
        if h[i] > pdh and c[i] < pdh:
            sig[i], done = -1, True
        elif l[i] < pdl and c[i] > pdl:
            sig[i], done = 1, True
    return sig


def ema_pullback(df):
    """Откат к EMA50 по тренду EMA50/EMA200: касание EMA50 и закрытие в сторону тренда."""
    e50, e200 = ema(df.close, 50), ema(df.close, 200)
    up = (e50 > e200) & (df.low <= e50) & (df.close > e50) & (df.close > df.open)
    dn = (e50 < e200) & (df.high >= e50) & (df.close < e50) & (df.close < df.open)
    return (up.astype(np.int8) - dn.astype(np.int8)).to_numpy()
