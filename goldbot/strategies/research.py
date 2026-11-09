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


def rsi_pullback_raw(df):
    """RSI(14) вернулся выше 40 → BUY, ниже 60 → SELL (без фильтра тренда, его накладывают отдельно)."""
    r = rsi(df.close, 14)
    up = ((r > 40) & (r.shift() <= 40)).to_numpy()
    dn = ((r < 60) & (r.shift() >= 60)).to_numpy()
    return (up.astype(np.int8) - dn.astype(np.int8))


def rsi_pullback(df):
    """Откат RSI(14) ниже 40 / выше 60 и возврат при дневном тренде (по закрытию свечи)."""
    return _filter(rsi_pullback_raw(df), htf_trend(df, "1D", 50))


def merge(*fns):
    """Несколько стратегий в одну: на каждой свече берётся сигнал первой сработавшей (по порядку)."""
    def f(df):
        out = np.zeros(len(df), dtype=np.int8)
        for g in reversed(fns):
            s = g(df)
            out = np.where(s != 0, s, out)
        return out.astype(np.int8)
    return f


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


def fibonacci_retracement(df, swing: int = 5, lo_lvl: float = 0.5, hi_lvl: float = 0.618, min_atr: float = 2.0):
    """Откат по Фибоначчи: после импульса (подтверждённые свинги low→high или high→low размером
    от min_atr × ATR14) ждём возврата в зону 50–61.8% и свечу в сторону импульса, закрытую из зоны.
    Один вход на импульс; импульс отменяется, если цена закрылась за его началом."""
    from ..indicators import pivot_high, pivot_low
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = atr(df, 14).to_numpy()
    ph, pl = pivot_high(h, swing), pivot_low(l, swing)
    sig = np.zeros(len(df), dtype=np.int8)
    last_low = last_high = np.nan
    up = dn = None  # (start, end) активного импульса
    for i in range(len(df)):
        if not np.isnan(pl[i]):
            last_low = pl[i]
            if not np.isnan(last_high) and last_high - last_low >= min_atr * a[i]:
                dn = (last_high, last_low)       # импульс вниз завершён на этом low
            up = up if up is None or last_low > up[0] else None
        if not np.isnan(ph[i]):
            last_high = ph[i]
            if not np.isnan(last_low) and last_high - last_low >= min_atr * a[i]:
                up = (last_low, last_high)
        if up is not None:
            s, e = up
            z_hi, z_lo = e - lo_lvl * (e - s), e - hi_lvl * (e - s)
            if c[i] < s:
                up = None
            elif l[i] <= z_hi and c[i] > z_lo and c[i] > o[i]:
                sig[i], up = 1, None
        if dn is not None and sig[i] == 0:
            s, e = dn
            z_lo, z_hi = e + lo_lvl * (s - e), e + hi_lvl * (s - e)
            if c[i] > s:
                dn = None
            elif h[i] >= z_lo and c[i] < z_hi and c[i] < o[i]:
                sig[i], dn = -1, None
    return sig


def trendline_breakout(df, swing: int = 5, bounce: bool = False):
    """Трендовая линия по двум последним подтверждённым свингам.
    breakout: линия по двум понижающимся хаям → BUY при закрытии выше линии; по двум повышающимся
    лоям → SELL при закрытии ниже. bounce: касание повышающейся линии лоёв и закрытие выше → BUY
    (и зеркально SELL от понижающейся линии хаёв). Один сигнал на линию."""
    from ..indicators import pivot_high, pivot_low
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    ph, pl = pivot_high(h, swing), pivot_low(l, swing)
    sig = np.zeros(len(df), dtype=np.int8)
    highs, lows = [], []          # (index, price)
    hl_used = ll_used = True
    for i in range(len(df)):
        if not np.isnan(ph[i]):
            highs = (highs + [(i - swing, ph[i])])[-2:]
            hl_used = False
        if not np.isnan(pl[i]):
            lows = (lows + [(i - swing, pl[i])])[-2:]
            ll_used = False
        # линия хаёв
        if len(highs) == 2 and not hl_used and highs[1][1] < highs[0][1]:
            (i1, p1), (i2, p2) = highs
            line = p2 + (p2 - p1) / (i2 - i1) * (i - i2)
            if not bounce and c[i] > line and c[i - 1] <= line + (p2 - p1) / (i2 - i1) * -1:
                sig[i], hl_used = 1, True
            elif bounce and h[i] >= line and c[i] < line and c[i] < o[i]:
                sig[i], hl_used = -1, True
        # линия лоёв
        if sig[i] == 0 and len(lows) == 2 and not ll_used and lows[1][1] > lows[0][1]:
            (i1, p1), (i2, p2) = lows
            line = p2 + (p2 - p1) / (i2 - i1) * (i - i2)
            if not bounce and c[i] < line and c[i - 1] >= line - (p2 - p1) / (i2 - i1):
                sig[i], ll_used = -1, True
            elif bounce and l[i] <= line and c[i] > line and c[i] > o[i]:
                sig[i], ll_used = 1, True
    return sig


# ── Стратегии ликвидности (ноябрь 2026) ──────────────────────────────────────────────────────────

def asian_sweep(df):
    """Sweep азиатского диапазона (Judas swing): Азия 00:00–07:00 Лондона; с 07:00 до 16:00 прокол
    хая Азии и закрытие обратно внутрь → SELL, прокол лоя и закрытие обратно → BUY. Один сигнал в день."""
    t = _local(df, "Europe/London")
    m, day = _minutes(t), t.normalize()
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    sig = np.zeros(len(df), dtype=np.int8)
    cur, ah, al, done = None, -np.inf, np.inf, False
    for i in range(len(df)):
        if day[i] != cur:
            cur, ah, al, done = day[i], -np.inf, np.inf, False
        if m[i] < 420:
            ah, al = max(ah, h[i]), min(al, l[i])
            continue
        if done or not np.isfinite(ah) or m[i] >= 960:
            continue
        if h[i] > ah and c[i] < ah:
            sig[i], done = -1, True
        elif l[i] < al and c[i] > al:
            sig[i], done = 1, True
    return sig


def swing_sweep(df, swing: int = 5):
    """Sweep ликвидности за последним подтверждённым свингом: прокол хая свинга и закрытие ниже → SELL,
    прокол лоя свинга и закрытие выше → BUY. Один сигнал на свинг."""
    from ..indicators import pivot_high, pivot_low
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    ph, pl = pivot_high(h, swing), pivot_low(l, swing)
    sig = np.zeros(len(df), dtype=np.int8)
    sh = sl = np.nan
    for i in range(len(df)):
        if not np.isnan(ph[i]):
            sh = ph[i]
        if not np.isnan(pl[i]):
            sl = pl[i]
        if not np.isnan(sh) and h[i] > sh and c[i] < sh:
            sig[i], sh = -1, np.nan
        elif not np.isnan(sl) and l[i] < sl and c[i] > sl:
            sig[i], sl = 1, np.nan
    return sig


def equal_levels_sweep(df, swing: int = 5, tol_atr: float = 0.15):
    """Sweep равных хаёв/лоёв: два последних свинга на одном уровне (в пределах 0.15 ATR) — пул ликвидности;
    прокол пула и закрытие обратно → вход в обратную сторону."""
    from ..indicators import pivot_high, pivot_low
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    a = atr(df, 14).to_numpy()
    ph, pl = pivot_high(h, swing), pivot_low(l, swing)
    sig = np.zeros(len(df), dtype=np.int8)
    highs, lows = [], []
    pool_h = pool_l = np.nan
    for i in range(len(df)):
        if not np.isnan(ph[i]):
            highs = (highs + [ph[i]])[-2:]
            if len(highs) == 2 and abs(highs[0] - highs[1]) <= tol_atr * a[i]:
                pool_h = max(highs)
        if not np.isnan(pl[i]):
            lows = (lows + [pl[i]])[-2:]
            if len(lows) == 2 and abs(lows[0] - lows[1]) <= tol_atr * a[i]:
                pool_l = min(lows)
        if not np.isnan(pool_h) and h[i] > pool_h and c[i] < pool_h:
            sig[i], pool_h = -1, np.nan
        elif not np.isnan(pool_l) and l[i] < pool_l and c[i] > pool_l:
            sig[i], pool_l = 1, np.nan
    return sig


def sweep_mss(df, swing: int = 5, window: int = 12):
    """Sweep + слом структуры (MSS): сняли ликвидность под лоем свинга, и в течение window свечей
    закрылись выше последнего хая свинга → BUY (зеркально SELL)."""
    from ..indicators import pivot_high, pivot_low
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    ph, pl = pivot_high(h, swing), pivot_low(l, swing)
    sig = np.zeros(len(df), dtype=np.int8)
    sh = sl = np.nan
    swept_low = swept_high = -10 ** 9   # индекс свечи, где сняли ликвидность
    for i in range(len(df)):
        if not np.isnan(ph[i]):
            sh = ph[i]
        if not np.isnan(pl[i]):
            sl = pl[i]
        if not np.isnan(sl) and l[i] < sl:
            swept_low, sl = i, np.nan
        if not np.isnan(sh) and h[i] > sh and i - swept_low > 0 and i - swept_low <= window and c[i] > sh:
            sig[i], swept_low, sh = 1, -10 ** 9, np.nan
            continue
        if not np.isnan(sh) and h[i] > sh:
            swept_high, sh = i, np.nan
        if not np.isnan(sl) and l[i] < sl and 0 < i - swept_high <= window and c[i] < sl:
            sig[i], swept_high, sl = -1, -10 ** 9, np.nan
    return sig
