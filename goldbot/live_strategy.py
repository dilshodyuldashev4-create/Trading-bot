"""Стратегии, которые бот использует в реальном времени, и описание ожидаемого сетапа."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from .i18n import t
from .strategies.fvg_bos import fvg_bos_signals
from .strategies.popular import donchian_breakout
from .strategies.research import squeeze_breakout, swing_sweep
from .strategies.sessions import asian_range_breakout, bank_manipulation, silver_bullet


@dataclass(frozen=True)
class LiveStrategy:
    key: str
    title: str
    timeframe: str
    signals: Callable[[pd.DataFrame], np.ndarray]
    backtest_note: str
    daily_trend: bool = False   # сигналы только по дневному тренду (close последнего закрытого дня vs EMA50)
    # несколько стратегий сразу: фильтр тренда к каждой, берётся первая сработавшая по тренду
    parts: tuple = ()


def _combo(df: pd.DataFrame) -> np.ndarray:
    a, b = asian_range_breakout(df), silver_bullet(df)
    return np.where(a != 0, a, b)


def _fvg_raw(df: pd.DataFrame) -> np.ndarray:
    return fvg_bos_signals(df)



# Ключи стратегий с общим описанием «что ждёт бот» (тренд + текст exp_<key>)
GENERIC = {"squeeze", "donchian", "fvg_m15", "liq_m15", "amd"}

STRATEGIES = {
    "combo": LiveStrategy(
        "combo", "ICT Silver Bullet + пробой азиатского диапазона", "15min", _combo,
        "Бэктест XAUUSD 2023–2026, SL 100 / TP 200 пипсов: 632 сделки, винрейт 36.6%, +6100 пипсов"),
    "fvg": LiveStrategy(
        "fvg", "OB + FVG + BOS по тренду EMA200", "1h",
        lambda df: fvg_bos_signals(df, trend_filter=True),
        "Бэктест XAUUSD 2023–2026, SL 100 / TP 200 пипсов: 283 сделки, винрейт 37.8%, +3800 пипсов"),
    # ── самые прибыльные на M15 (без привязки к сессиям). Сигналов на M5 нет: на M5 слишком много шума ──
    "squeeze": LiveStrategy(
        "squeeze", "Squeeze (Боллинджер в Кельтнере) по дневному тренду", "15min", squeeze_breakout,
        "Бэктест XAUUSD 2023–2026, SL 100 / TP 200 пипсов: 441 сделка, винрейт 40.8%, +9900 пипсов",
        daily_trend=True),
    "donchian": LiveStrategy(
        "donchian", "Пробой канала Дончиана 20 по тренду EMA200", "15min", donchian_breakout,
        "Бэктест XAUUSD 2023–2026, SL 100 / TP 200 пипсов: 1635 сделок, винрейт 34.7%, +6900 пипсов"),
    "fvg_m15": LiveStrategy(
        "fvg_m15", "OB + FVG + BOS по дневному тренду", "15min", _fvg_raw,
        "Бэктест XAUUSD 2023–2026, SL 100 / TP 200 пипсов: 647 сделок, винрейт 38.5%, +10000 пипсов",
        daily_trend=True),
    "liq_m15": LiveStrategy(
        "liq_m15", "Снятие ликвидности за свингом по дневному тренду", "15min", swing_sweep,
        "Бэктест XAUUSD 2023–2026, SL 100 / TP 200 пипсов: 967 сделок, винрейт 36.4%, +8900 пипсов",
        daily_trend=True),
    "amd": LiveStrategy(
        "amd", "Манипуляция банка: Азия — диапазон, Лондон — вынос ликвидности, Нью-Йорк — вход", "15min",
        bank_manipulation,
        "Бэктест XAUUSD 12.2023–08.2026, стоп 2 ATR / тейк 3 ATR: 386 сделок, тейков 46%, +54R"),
}


# STRATEGY=all — самые прибыльные стратегии на M15 (по одной на сетап, чтобы один и тот же сигнал не приходил
# дважды). У каждой не больше одной открытой сделки, а встречный сигнал (против открытой сделки) не даётся.
PORTFOLIO = ("squeeze", "donchian", "fvg_m15", "liq_m15", "amd")


def resolve_keys(spec: str) -> list[str]:
    """«all» → PORTFOLIO, «a,b» → [a, b], иначе одна стратегия."""
    keys = list(PORTFOLIO) if spec.strip() == "all" else [k.strip() for k in spec.split(",") if k.strip()]
    unknown = [k for k in keys if k not in STRATEGIES]
    if unknown or not keys:
        raise ValueError(f"неизвестные стратегии: {unknown or spec}")
    return keys


DAILY_EMA = 50


def daily_trend_side(daily: pd.DataFrame, now: pd.Timestamp) -> int:
    """+1 / -1 / 0: close последней ЗАКРЫТОЙ дневной свечи (UTC) выше / ниже EMA50 дневных close."""
    today = _utc(now).tz_convert(None).normalize()
    idx = daily.index.tz_convert(None) if daily.index.tz is not None else daily.index
    closed = daily.close[idx < today]
    if len(closed) < 2:
        return 0
    e = closed.ewm(span=DAILY_EMA, adjust=False).mean().iloc[-1]
    return int(np.sign(closed.iloc[-1] - e))


def _utc(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts


def expected_setup(df: pd.DataFrame, strategy_key: str, now: pd.Timestamp, tz: str, lang: str = "ru",
                   trend: int = 0) -> str:
    """Текст «что бот ждёт» по закрытым свечам df (UTC); trend — дневной тренд для стратегий с daily_trend."""
    now = _utc(now)
    fmt = lambda x: x.tz_convert(tz).strftime("%H:%M")  # noqa: E731
    if strategy_key == "fvg":
        last = df.iloc[-1]
        up = last.close > df.close.ewm(span=200, adjust=False).mean().iloc[-1]
        return t(lang, "exp_fvg", trend=t(lang, "exp_trend_up" if up else "exp_trend_down"))

    if strategy_key in GENERIC:
        lines = [t(lang, f"exp_{strategy_key}"), t(lang, "exp_confirm")]
        if STRATEGIES[strategy_key].daily_trend:
            lines.insert(0, t(lang, "exp_daily_trend",
                              trend=t(lang, "exp_trend_up" if trend >= 0 else "exp_trend_down")))
        return "\n".join(lines)
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
            parts.append(t(lang, "exp_asia_forming", lo=f"{lo:.2f}", hi=f"{hi:.2f}",
                           start=fmt(win_start), end=fmt(win_end)))
        elif ldn < win_end:
            after = df[(idx.tz_convert("Europe/London") >= win_start)]
            broke = ((after.close > hi) | (after.close < lo)).any()
            if broke:
                parts.append(t(lang, "exp_asia_broken"))
            else:
                parts.append(t(lang, "exp_asia_setup", hi=f"{hi:.2f}", lo=f"{lo:.2f}", end=fmt(win_end)))
    if not parts or ldn >= win_end:
        nxt = win_start if ldn < win_start else win_start + pd.Timedelta(days=1)
        parts.append(t(lang, "exp_asia_next", when=f"{nxt.tz_convert(tz):%d.%m %H:%M}"))

    # Silver Bullet
    ny = now.tz_convert("America/New_York")
    nday = ny.normalize()
    s, e = nday + pd.Timedelta(hours=10), nday + pd.Timedelta(hours=11)
    nymask = idx.tz_convert("America/New_York") >= nday
    day_open = df.open[nymask].iloc[0] if nymask.any() else None
    if ny < e and day_open is not None:
        side = "BUY" if df.close.iloc[-1] > day_open else "SELL"
        parts.append(t(lang, "exp_sb_window", start=fmt(s), end=fmt(e), open=f"{day_open:.2f}",
                       pos=t(lang, "exp_above" if side == "BUY" else "exp_below"), side=side))
    else:
        nxt = s if ny < s else s + pd.Timedelta(days=1)
        parts.append(t(lang, "exp_sb_next", when=f"{nxt.tz_convert(tz):%d.%m %H:%M}"))
    parts.append(t(lang, "exp_confirm"))
    return "\n".join(parts)
