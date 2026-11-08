"""Движок сигналов: проверяет рынок каждые CHECK_INTERVAL секунд.

* каждую проверку — текущая цена: закрываем открытые сигналы по TP/SL;
* когда закрылась новая свеча таймфрейма стратегии — пересчитываем стратегию,
  и если на последней закрытой свече есть сигнал — создаём его и рассылаем.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import pandas as pd

from .chart import render_signal
from .data import PIP
from .db import DB
from .i18n import DEFAULT, per_lang, t
from .live_strategy import STRATEGIES, LiveStrategy, expected_setup
from .market import TF_MINUTES, Provider

log = logging.getLogger(__name__)


@dataclass
class NewSignal:
    id: int
    direction: int
    entry: float
    sl: float
    tp: float
    image: bytes
    texts: dict[str, str]  # язык → текст сигнала
    render: Optional[Callable[..., bytes]] = None  # картинка с подписями для конкретного подписчика

    @property
    def text(self) -> str:
        return self.texts[DEFAULT]


OnSignal = Callable[[NewSignal], Awaitable[None]]
OnClose = Callable[[dict, str, float], Awaitable[None]]
OnDayClosed = Callable[[int], Awaitable[None]]  # сколько стопов подряд
OnLate = Callable[[dict, float, float], Awaitable[None]]  # сигнал, цена, на сколько пипсов ушла


def market_open(now: pd.Timestamp) -> bool:
    """Рынок золота: с вс 18:00 до пт 17:00 по Нью-Йорку, ежедневный перерыв 17:00–18:00.

    Пока рынок закрыт (выходные, перерыв), котировки не запрашиваем — экономим лимит API.
    """
    ny = (now if now.tzinfo else now.tz_localize("UTC")).tz_convert("America/New_York")
    wd, h = ny.weekday(), ny.hour  # пн=0 … вс=6
    if wd == 5:                      # суббота
        return False
    if wd == 6:                      # воскресенье — открытие в 18:00
        return h >= 18
    if wd == 4 and h >= 17:          # пятница после 17:00
        return False
    return h != 17                   # ежедневный перерыв 17:00–18:00


def closed_bars(df: pd.DataFrame, tf: str, now: pd.Timestamp) -> pd.DataFrame:
    """Отбрасывает незакрытую последнюю свечу."""
    step = pd.Timedelta(minutes=TF_MINUTES[tf])
    now = now.tz_convert(None) if now.tzinfo else now
    return df[df.index + step <= now]


def format_signal(strategy: LiveStrategy, d: int, entry: float, sl: float, tp: float,
                  sl_pips: float, tp_pips: float, when: str, lang: str = "ru") -> str:
    return t(lang, "signal", side="🟢 BUY" if d == 1 else "🔴 SELL", entry=f"{entry:.2f}",
             sl=f"{sl:.2f}", tp=f"{tp:.2f}", sl_pips=f"{sl_pips:.0f}", tp_pips=f"{tp_pips:.0f}",
             rr=f"{tp_pips / sl_pips:.0f}", strategy=t(lang, f"strat_{strategy.key}"), when=when,
             note=t(lang, f"note_{strategy.key}"))


class SignalEngine:
    def __init__(self, db: DB, provider: Provider, strategy_key: str, sl_pips: float, tp_pips: float,
                 display_tz: str, on_signal: OnSignal, on_close: OnClose,
                 on_late: Optional[OnLate] = None, late_pips: float = 30,
                 on_day_closed: Optional[OnDayClosed] = None, max_sl_streak: int = 0):
        self.db, self.provider = db, provider
        self.strategy = STRATEGIES[strategy_key]
        self.sl_pips, self.tp_pips = sl_pips, tp_pips
        self.tz = display_tz
        self.on_signal, self.on_close, self.on_late = on_signal, on_close, on_late
        self.late_pips = late_pips
        self.on_day_closed, self.max_sl_streak = on_day_closed, max_sl_streak
        self.last_bar: pd.Timestamp | None = None
        self.last_df: pd.DataFrame | None = None
        self.last_price: float | None = None
        self.retry_at: pd.Timestamp | None = None  # когда снова запрашивать свечи, если новой ещё нет

    async def _load_last_bar(self) -> None:
        if self.last_bar is None:
            v = await self.db.get_kv("last_bar")
            self.last_bar = pd.Timestamp(v) if v else None

    async def check_open(self, price: float) -> None:
        for s in await self.db.open_signals():
            d = s["direction"]
            status = None
            if (d == 1 and price <= s["sl"]) or (d == -1 and price >= s["sl"]):
                status = "sl"
            elif (d == 1 and price >= s["tp"]) or (d == -1 and price <= s["tp"]):
                status = "tp"
            if status:
                await self.db.close_signal(s["id"], status)
                await self.on_close(s, status, price)
                if status == "sl":
                    await self.check_day_stop()
                continue
            moved = d * (price - s["entry"]) / PIP  # пипсов в сторону тейка
            key = f"late_warned:{s['id']}"
            if self.on_late and self.late_pips > 0 and moved >= self.late_pips and not await self.db.get_kv(key):
                await self.db.set_kv(key, "1")
                await self.on_late(s, price, moved)

    def today(self, now: pd.Timestamp | None = None) -> str:
        now = now or pd.Timestamp.now(tz="UTC")
        return now.tz_convert(self.tz).strftime("%Y-%m-%d")

    async def day_closed(self, now: pd.Timestamp | None = None) -> bool:
        return await self.db.get_kv("day_closed") == self.today(now)

    async def check_day_stop(self, now: pd.Timestamp | None = None) -> None:
        """N стопов подряд за сегодня — закрываем торговый день до завтра."""
        if self.max_sl_streak <= 0 or await self.day_closed(now):
            return
        now = now or pd.Timestamp.now(tz="UTC")
        start = now.tz_convert(self.tz).normalize().tz_convert("UTC").to_pydatetime()
        statuses = await self.db.closed_since(start)
        streak = 0
        for st in statuses:
            if st != "sl":
                break
            streak += 1
        if streak >= self.max_sl_streak:
            await self.db.set_kv("day_closed", self.today(now))
            if self.on_day_closed:
                await self.on_day_closed(streak)

    async def tick(self, now: pd.Timestamp | None = None) -> NewSignal | None:
        now = now or pd.Timestamp.now(tz="UTC")
        if not market_open(now):
            return None
        await self._load_last_bar()
        price = await self.provider.price()
        self.last_price = price
        await self.check_open(price)

        tf = self.strategy.timeframe
        step = pd.Timedelta(minutes=TF_MINUTES[tf])
        naive_now = now.tz_convert(None)
        if self.last_bar is not None and naive_now < self.last_bar + 2 * step:
            return None  # новая свеча ещё не закрылась
        if self.retry_at is not None and naive_now < self.retry_at:
            return None  # выходные или задержка данных: не тратим лимит API

        df = closed_bars(await self.provider.candles(tf, 400), tf, now)
        if df.empty:
            return None
        self.last_df = df
        bar = df.index[-1]
        if self.last_bar is not None and bar <= self.last_bar:
            self.retry_at = naive_now + pd.Timedelta(minutes=5)
            return None
        self.retry_at = None
        first_run = self.last_bar is None
        self.last_bar = bar
        await self.db.set_kv("last_bar", bar.isoformat())
        if first_run:
            return None  # не шлём старый сигнал при первом запуске
        if await self.day_closed(now):
            return None  # торговый день закрыт после серии стопов — ждём завтра

        sig = self.strategy.signals(df)
        d = int(sig[-1])
        if d == 0:
            return None
        entry = price
        sl = entry - d * self.sl_pips * PIP
        tp = entry + d * self.tp_pips * PIP
        sid = await self.db.add_signal(self.strategy.key, d, entry, sl, tp)
        when = now.tz_convert(self.tz).strftime("%d.%m.%Y %H:%M")
        title = f"XAUUSD {tf.replace('min', 'm')} · #{sid}"
        img = render_signal(df, d, entry, sl, tp, title, tz=self.tz)
        ns = NewSignal(sid, d, entry, sl, tp, img,
                       per_lang(lambda lang: format_signal(self.strategy, d, entry, sl, tp,
                                                           self.sl_pips, self.tp_pips, when, lang)),
                       lambda **kw: render_signal(df, d, entry, sl, tp, title, tz=self.tz, **kw))
        await self.on_signal(ns)
        return ns

    async def expected(self, lang: str = "ru") -> str:
        now = pd.Timestamp.now(tz="UTC")
        tf = self.strategy.timeframe
        df = self.last_df
        if df is None or df.empty:
            df = closed_bars(await self.provider.candles(tf, 400), tf, now)
            self.last_df = df
        return expected_setup(df, self.strategy.key, now, self.tz, lang)

    async def run_forever(self, interval: int) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — бот не должен падать из-за сети
                log.exception("market check failed")
            await asyncio.sleep(interval)
