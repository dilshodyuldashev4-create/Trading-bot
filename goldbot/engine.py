"""Движок сигналов: проверяет рынок каждые CHECK_INTERVAL секунд.

* каждую проверку — текущая цена: закрываем открытые сигналы по TP/SL;
* когда закрылась новая свеча таймфрейма стратегии — пересчитываем стратегию,
  и если на последней закрытой свече есть сигнал — создаём его и рассылаем.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

import pandas as pd

from .chart import render_signal
from .data import PIP
from .db import DB
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
    text: str


OnSignal = Callable[[NewSignal], Awaitable[None]]
OnClose = Callable[[dict, str, float], Awaitable[None]]


def closed_bars(df: pd.DataFrame, tf: str, now: pd.Timestamp) -> pd.DataFrame:
    """Отбрасывает незакрытую последнюю свечу."""
    step = pd.Timedelta(minutes=TF_MINUTES[tf])
    now = now.tz_convert(None) if now.tzinfo else now
    return df[df.index + step <= now]


def format_signal(strategy: LiveStrategy, d: int, entry: float, sl: float, tp: float,
                  sl_pips: float, tp_pips: float, when: str) -> str:
    side = "🟢 BUY" if d == 1 else "🔴 SELL"
    return (f"<b>{side} XAUUSD</b>\n\n"
            f"📍 Вход: <b>{entry:.2f}</b>\n"
            f"🛑 Stop Loss: <b>{sl:.2f}</b> ({sl_pips:.0f} пипсов)\n"
            f"🎯 Take Profit: <b>{tp:.2f}</b> ({tp_pips:.0f} пипсов)\n"
            f"⚖️ Риск/прибыль 1:{tp_pips / sl_pips:.0f}\n\n"
            f"📊 Стратегия: {strategy.title}\n"
            f"🕒 {when}\n\n"
            f"<i>{strategy.backtest_note}. Прошлые результаты не гарантируют будущих. "
            f"Рискуйте не больше 1–2% депозита на сделку.</i>")


class SignalEngine:
    def __init__(self, db: DB, provider: Provider, strategy_key: str, sl_pips: float, tp_pips: float,
                 display_tz: str, on_signal: OnSignal, on_close: OnClose):
        self.db, self.provider = db, provider
        self.strategy = STRATEGIES[strategy_key]
        self.sl_pips, self.tp_pips = sl_pips, tp_pips
        self.tz = display_tz
        self.on_signal, self.on_close = on_signal, on_close
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

    async def tick(self, now: pd.Timestamp | None = None) -> NewSignal | None:
        now = now or pd.Timestamp.now(tz="UTC")
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

        sig = self.strategy.signals(df)
        d = int(sig[-1])
        if d == 0:
            return None
        entry = price
        sl = entry - d * self.sl_pips * PIP
        tp = entry + d * self.tp_pips * PIP
        sid = await self.db.add_signal(self.strategy.key, d, entry, sl, tp)
        when = now.tz_convert(self.tz).strftime("%d.%m.%Y %H:%M")
        img = render_signal(df, d, entry, sl, tp, f"XAUUSD {tf.replace('min', 'm')} · сигнал #{sid}", tz=self.tz)
        ns = NewSignal(sid, d, entry, sl, tp, img,
                       format_signal(self.strategy, d, entry, sl, tp, self.sl_pips, self.tp_pips, when))
        await self.on_signal(ns)
        return ns

    async def expected(self) -> str:
        now = pd.Timestamp.now(tz="UTC")
        tf = self.strategy.timeframe
        df = self.last_df
        if df is None or df.empty:
            df = closed_bars(await self.provider.candles(tf, 400), tf, now)
            self.last_df = df
        return expected_setup(df, self.strategy.key, now, self.tz)

    async def run_forever(self, interval: int) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — бот не должен падать из-за сети
                log.exception("market check failed")
            await asyncio.sleep(interval)
