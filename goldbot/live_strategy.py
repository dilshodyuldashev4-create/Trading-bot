"""Стратегии, которые бот использует в реальном времени, и описание ожидаемого сетапа."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from .strategies.fvg_bos import fvg_bos_signals
from .strategies.sessions import asian_range_breakout, silver_bullet


@dataclass(frozen=True)
class LiveStrategy:
    key: str
    title: str
    timeframe: str
    signals: Callable[[pd.DataFrame], np.ndarray]
    backtest_note: str


def _combo(df: pd.DataFrame) -> np.ndarray:
    a, b = asian_range_breakout(df), silver_bullet(df)
    return np.where(a != 0, a, b)


STRATEGIES = {
    "combo": LiveStrategy(
        "combo", "ICT Silver Bullet + пробой азиатского диапазона", "15min", _combo,
        "Бэктест XAUUSD 2023–2026, SL 100 / TP 200 пипсов: 632 сделки, винрейт 36.6%, +6100 пипсов"),
    "fvg": LiveStrategy(
        "fvg", "OB + FVG + BOS по тренду EMA200", "1h",
        lambda df: fvg_bos_signals(df, trend_filter=True),
        "Бэктест XAUUSD 2023–2026, SL 100 / TP 200 пипсов: 283 сделки, винрейт 37.8%, +3800 пипсов"),
}


def _utc(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts


def expected_setup(df: pd.DataFrame, strategy_key: str, now: pd.Timestamp, tz: str) -> str:
    """Текст «что бот ждёт» по закрытым свечам df (UTC)."""
    now = _utc(now)
    fmt = lambda t: t.tz_convert(tz).strftime("%H:%M")  # noqa: E731
    if strategy_key == "fvg":
        last = df.iloc[-1]
        trend = "вверх (ищем только BUY)" if last.close > df.close.ewm(span=200, adjust=False).mean().iloc[-1] \
            else "вниз (ищем только SELL)"
        return (f"Тренд по EMA200 на H1: {trend}.\n"
                "Сигнал появится, когда цена пробьёт последний свинг (BOS) и рядом будет FVG того же направления.")

    parts = []
    idx = df.index.tz_localize("UTC") if df.index.tz is None else df.index
    # пробой азиатского диапазона
    ldn = now.tz_convert("Europe/London")
    day = ldn.normalize()
    lmask = (idx.tz_convert("Europe/London") >= day) & (idx.tz_convert("Europe/London") < day + pd.Timedelta(hours=7))
    win_start = day + pd.Timedelta(hours=7)
    win_end = day + pd.Timedelta(hours=11)
    if lmask.any():
        hi, lo = df.high[lmask].max(), df.low[lmask].min()
        if ldn < win_start:
            parts.append(f"🌏 Азиатский диапазон формируется: {lo:.2f} – {hi:.2f}. "
                         f"Окно пробоя {fmt(win_start)}–{fmt(win_end)}.")
        elif ldn < win_end:
            after = df[(idx.tz_convert("Europe/London") >= win_start)]
            broke = ((after.close > hi) | (after.close < lo)).any()
            if broke:
                parts.append("🌏 Пробой азиатского диапазона сегодня уже был.")
            else:
                parts.append(f"🌏 Ожидаемый сетап: если свеча M15 закроется выше {hi:.2f} — BUY, "
                             f"ниже {lo:.2f} — SELL (до {fmt(win_end)}).")
    if not parts or ldn >= win_end:
        nxt = win_start if ldn < win_start else win_start + pd.Timedelta(days=1)
        parts.append(f"🌏 Следующее окно пробоя азиатского диапазона: {nxt.tz_convert(tz):%d.%m %H:%M}.")

    # Silver Bullet
    ny = now.tz_convert("America/New_York")
    nday = ny.normalize()
    s, e = nday + pd.Timedelta(hours=10), nday + pd.Timedelta(hours=11)
    nymask = idx.tz_convert("America/New_York") >= nday
    day_open = df.open[nymask].iloc[0] if nymask.any() else None
    if ny < e and day_open is not None:
        side = "BUY" if df.close.iloc[-1] > day_open else "SELL"
        parts.append(f"🎯 Silver Bullet: окно {fmt(s)}–{fmt(e)}. Открытие дня {day_open:.2f}, цена "
                     f"{'выше' if side == 'BUY' else 'ниже'} — ждём FVG на {side}.")
    else:
        nxt = s if ny < s else s + pd.Timedelta(days=1)
        parts.append(f"🎯 Следующее окно Silver Bullet: {nxt.tz_convert(tz):%d.%m %H:%M}.")
    parts.append("Как только сетап подтвердится, бот сам пришлёт сигнал.")
    return "\n".join(parts)
