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
from .live_strategy import STRATEGIES, LiveStrategy, daily_trend_side, expected_setup, resolve_keys
from .market import TF_MINUTES, Provider

log = logging.getLogger(__name__)

CANDLES = 1000  # свечей на запрос: хватает на EMA200 и на вчерашний день даже на M5


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


def next_open(now: pd.Timestamp) -> pd.Timestamp:
    """Когда рынок откроется снова (вызывать, когда он закрыт): 18:00 по Нью-Йорку сегодня или в воскресенье."""
    ny = (now if now.tzinfo else now.tz_localize("UTC")).tz_convert("America/New_York")
    day = ny.normalize()
    if ny.weekday() == 4 and ny.hour >= 17:
        day += pd.Timedelta(days=2)          # пятница вечером → воскресенье
    elif ny.weekday() == 5:
        day += pd.Timedelta(days=1)          # суббота → воскресенье
    elif ny.hour >= 18:
        day += pd.Timedelta(days=1)
    return day.replace(hour=18).tz_convert("UTC")


def session_open(now: pd.Timestamp) -> pd.Timestamp:
    """Начало текущей торговой сессии золота: последние 18:00 по Нью-Йорку (в UTC)."""
    ny = (now if now.tzinfo else now.tz_localize("UTC")).tz_convert("America/New_York")
    start = ny.normalize() + pd.Timedelta(hours=18)
    if ny < start:
        start -= pd.Timedelta(days=1)
    return start.tz_convert("UTC")


def parse_hhmm(s: str) -> pd.Timedelta | None:
    """«08:00» → 8 часов от полуночи; пусто или ошибка — None."""
    try:
        h, m = (int(x) for x in s.strip().split(":"))
        return pd.Timedelta(hours=h, minutes=m)
    except (ValueError, AttributeError):
        return None


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


def news_line(info: dict | None, d: int, lang: str = "ru") -> str:
    """Строка о фоне новостей в сигнале (если есть оценка Claude)."""
    if not info or info.get("bias") not in ("bullish", "bearish", "neutral"):
        return ""
    side = {"bullish": 1, "bearish": -1, "neutral": 0}[info["bias"]]
    arrow = {1: "⬆️", -1: "⬇️", 0: "➡️"}[side]
    rel = "news_neutral" if side == 0 else ("news_with" if side == d else "news_against")
    return "\n\n" + t(lang, "news_bg", arrow=arrow, strength=t(lang, f"news_{info.get('strength', 'weak')}"),
                       rel=t(lang, rel))


class SignalEngine:
    def __init__(self, db: DB, provider: Provider, strategy_key: str, sl_pips: float, tp_pips: float,
                 display_tz: str, on_signal: OnSignal, on_close: OnClose,
                 on_late: Optional[OnLate] = None, late_pips: float = 30,
                 on_day_closed: Optional[OnDayClosed] = None, max_sl_streak: int = 0):
        self.db, self.provider = db, provider
        # одна стратегия, список через запятую или «all» — тогда каждая работает независимо
        self.strategies = [STRATEGIES[k] for k in resolve_keys(strategy_key)]
        self.strategy = self.strategies[0]
        self.sl_pips, self.tp_pips = sl_pips, tp_pips
        self.tz = display_tz
        self.on_signal, self.on_close, self.on_late = on_signal, on_close, on_late
        self.late_pips = late_pips
        self.on_day_closed, self.max_sl_streak = on_day_closed, max_sl_streak
        self.last_bars: dict[str, pd.Timestamp | None] = {}   # стратегия → последняя обработанная свеча
        self.dfs: dict[str, pd.DataFrame] = {}                 # таймфрейм → последние закрытые свечи
        self.last_df: pd.DataFrame | None = None
        self.last_price: float | None = None
        self.retry_at: dict[str, pd.Timestamp] = {}  # когда снова запрашивать свечи, если новой ещё нет
        self._trend: tuple[pd.Timestamp, int] | None = None  # (день UTC, дневной тренд)
        self.news_pause_min = 0              # пауза новых сигналов вокруг новостей США (0 — выкл.)
        self.news_pause_impact: tuple[str, ...] = ("High",)
        # оценка фона новостей: (данные рынка) → {"bias", "strength", ...} или None; строка в сигнале
        self.news_bias: Optional[Callable[[str], Awaitable[dict | None]]] = None
        self.news_block = False  # True — не давать сигнал против сильного фона
        # за сколько минут до важной новости США закрывать открытые сделки (0 — не закрывать)
        self.news_close_min = 0
        self.on_news_close: Optional[Callable[[dict, float, dict, int], Awaitable[None]]] = None

    @property
    def multi(self) -> bool:
        return len(self.strategies) > 1

    def _kv_bar(self, key: str) -> str:
        return f"last_bar:{key}" if self.multi else "last_bar"

    async def _load_last_bar(self) -> None:
        for st in self.strategies:
            if st.key not in self.last_bars:
                v = await self.db.get_kv(self._kv_bar(st.key))
                self.last_bars[st.key] = pd.Timestamp(v) if v else None

    def df_for(self, strategy_key: str | None = None) -> pd.DataFrame | None:
        """Свечи таймфрейма стратегии (для картинки закрытия сделки)."""
        st = STRATEGIES.get(strategy_key or "")
        return self.dfs.get(st.timeframe) if st is not None and st.timeframe in self.dfs else self.last_df

    async def check_open(self, price: float) -> None:
        for s in await self.db.open_signals():
            d = s["direction"]
            # максимальный ход цены в плюс (mfe) и в минус (mae) за время сделки, в пипсах
            moved = d * (price - s["entry"]) / PIP
            mfe, mae = max(s.get("mfe") or 0, moved), max(s.get("mae") or 0, -moved)
            if (mfe, mae) != (s.get("mfe") or 0, s.get("mae") or 0):
                s["mfe"], s["mae"] = mfe, mae
                await self.db.set_excursion(s["id"], mfe, mae)
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

    async def news_pause(self, now: pd.Timestamp) -> dict | None:
        """Важная новость США в пределах ±news_pause_min минут — новые сигналы не даём."""
        if self.news_pause_min <= 0:
            return None
        m = pd.Timedelta(minutes=self.news_pause_min)
        try:
            events = await self.db.events_between((now - m).to_pydatetime(), (now + m).to_pydatetime())
        except Exception:  # noqa: BLE001 — без календаря работаем как раньше
            log.exception("news pause check")
            return None
        return next((e for e in events if e.get("country") == "USD"
                     and e.get("impact") in self.news_pause_impact), None)

    async def news_close_check(self, now: pd.Timestamp, price: float) -> int:
        """За news_close_min минут до важной новости США закрывает открытые сделки по рынку и сообщает всем."""
        if self.news_close_min <= 0 or self.on_news_close is None:
            return 0
        opened = await self.db.open_signals()
        if not opened:
            return 0
        events = await self.db.events_between(now.to_pydatetime(),
                                              (now + pd.Timedelta(minutes=self.news_close_min)).to_pydatetime())
        ev = next((e for e in events if e.get("country") == "USD" and e.get("impact") in self.news_pause_impact), None)
        if ev is None:
            return 0
        mins = max(1, int((pd.Timestamp(ev["ts"]) - now).total_seconds() // 60))
        for s in opened:
            await self.db.close_signal(s["id"], "news", price)
            log.info("signal #%s closed before news %s at %.2f", s["id"], ev.get("title"), price)
            await self.on_news_close(s, price, ev, mins)
        return len(opened)

    async def morning_review(self, lang: str = "ru", now: pd.Timestamp | None = None,
                             news: dict | None = None) -> str:
        """Утренний разбор: что было с открытия сессии, хай/лой прошлого дня, тренд и основной сценарий."""
        now = now or pd.Timestamp.now(tz="UTC")
        df = closed_bars(await self.provider.candles("5min", 500), "5min", now)
        so = session_open(now).tz_convert(None)
        night, prev = df[df.index >= so], df[(df.index >= so - pd.Timedelta(days=1)) & (df.index < so)]
        if night.empty:
            return t(lang, "mr_nodata")
        if prev.empty and so.weekday() == 6:  # понедельник: прошлый день — пятница
            prev = df[df.index < so].tail(276)
        price = self.last_price or float(night.close.iloc[-1])
        o, hi, lo = float(night.open.iloc[0]), float(night.high.max()), float(night.low.min())
        ch = (price - o) / PIP
        trend = await self.daily_trend(now)
        score = (1 if trend > 0 else -1 if trend < 0 else 0) + (1 if ch > 30 else -1 if ch < -30 else 0)
        lines = [t(lang, "mr_head", date=now.tz_convert(self.tz).strftime("%d.%m.%Y")),
                 t(lang, "mr_price", price=f"{price:.2f}", ch=f"{ch:+.0f}", open=f"{o:.2f}"),
                 t(lang, "mr_night", hi=f"{hi:.2f}", lo=f"{lo:.2f}", rng=f"{(hi - lo) / PIP:.0f}")]
        if not prev.empty:
            pdh, pdl = float(prev.high.max()), float(prev.low.min())
            lines.append(t(lang, "mr_prev", hi=f"{pdh:.2f}", lo=f"{pdl:.2f}"))
            if hi > pdh:
                lines.append(t(lang, "mr_swept_hi"))
            if lo < pdl:
                lines.append(t(lang, "mr_swept_lo"))
        lines.append(t(lang, "exp_daily_trend", trend=t(lang, "exp_trend_up" if trend >= 0 else "exp_trend_down")))
        tfs = await self.tf_trends(df, now)
        if tfs:
            lines.append(t(lang, "mr_tfs", tfs="  ".join(f"{k} {'⬆️' if v > 0 else '⬇️'}" for k, v in tfs.items())))
        if news and news.get("bias") in ("bullish", "bearish", "neutral"):
            arrow = {"bullish": "⬆️", "bearish": "⬇️", "neutral": "➡️"}[news["bias"]]
            lines.append(t(lang, "mr_news", arrow=arrow, strength=t(lang, f"news_{news.get('strength', 'weak')}")))
        key = "mr_up" if score >= 2 else "mr_down" if score <= -2 else "mr_mixed"
        lines.append("\n" + t(lang, key, hi=f"{hi:.2f}", lo=f"{lo:.2f}"))
        return "\n".join(lines)

    async def tf_trends(self, m5: pd.DataFrame, now: pd.Timestamp) -> dict[str, int]:
        """Тренд по EMA50 на M15, M30, H1, H4 (close последней закрытой свечи выше/ниже EMA50)."""
        from .data import resample
        from .indicators import ema
        out: dict[str, int] = {}
        for label, rule in (("M15", "15min"), ("M30", "30min")):
            d = resample(m5, rule)
            if len(d) >= 60:
                out[label] = 1 if d.close.iloc[-1] > ema(d.close, 50).iloc[-1] else -1
        for label, tf in (("H1", "1h"), ("H4", "4h")):
            try:
                d = closed_bars(await self.provider.candles(tf, 200), tf, now)
            except Exception:  # noqa: BLE001 — нет данных по ТФ: просто не показываем
                continue
            if len(d) >= 60:
                out[label] = 1 if d.close.iloc[-1] > ema(d.close, 50).iloc[-1] else -1
        return out

    async def market_text(self, now: pd.Timestamp | None = None) -> str:
        """Цена и дневной тренд — контекст для разбора новостей."""
        now = now or pd.Timestamp.now(tz="UTC")
        parts = [f"XAUUSD {self.last_price:.2f}"] if self.last_price else []
        try:
            trend = await self.daily_trend(now)
            parts.append("дневной тренд (EMA50): " + ("вверх" if trend > 0 else "вниз" if trend < 0 else "нет"))
        except Exception:  # noqa: BLE001
            pass
        return ", ".join(parts)

    async def tick(self, now: pd.Timestamp | None = None) -> NewSignal | None:
        now = now or pd.Timestamp.now(tz="UTC")
        if not market_open(now):
            return None
        await self._load_last_bar()
        price = await self.provider.price()
        self.last_price = price
        await self.check_open(price)
        await self.news_close_check(now, price)

        opened = await self.db.open_signals()
        open_keys = {s["strategy"] for s in opened}
        open_dirs = {s["direction"] for s in opened}   # стороны открытых сделок (1 BUY, -1 SELL)
        cache: dict[str, pd.DataFrame] = {}
        result = None
        for st in self.strategies:
            ns = await self._tick_strategy(st, now, price, cache, open_keys, open_dirs)
            result = ns or result
        return result

    async def _candles(self, tf: str, now: pd.Timestamp, cache: dict) -> pd.DataFrame:
        if tf not in cache:
            cache[tf] = closed_bars(await self.provider.candles(tf, CANDLES), tf, now)
        return cache[tf]

    async def _tick_strategy(self, st: LiveStrategy, now: pd.Timestamp, price: float,
                             cache: dict, open_keys: set, open_dirs: set | None = None) -> NewSignal | None:
        tf = st.timeframe
        step = pd.Timedelta(minutes=TF_MINUTES[tf])
        naive_now = now.tz_convert(None)
        last_bar = self.last_bars.get(st.key)
        if last_bar is not None and naive_now < last_bar + 2 * step:
            return None  # новая свеча ещё не закрылась
        retry = self.retry_at.get(st.key)
        if retry is not None and naive_now < retry:
            return None  # выходные или задержка данных: не тратим лимит API

        df = await self._candles(tf, now, cache)
        if df.empty:
            return None
        self.dfs[tf] = df
        self.last_df = df
        bar = df.index[-1]
        if last_bar is not None and bar <= last_bar:
            self.retry_at[st.key] = naive_now + pd.Timedelta(minutes=5)
            return None
        self.retry_at.pop(st.key, None)
        self.last_bars[st.key] = bar
        await self.db.set_kv(self._kv_bar(st.key), bar.isoformat())
        if last_bar is None:
            return None  # не шлём старый сигнал при первом запуске
        if await self.day_closed(now):
            return None  # торговый день закрыт после серии стопов — ждём завтра
        if st.key in open_keys:
            return None  # у этой стратегии уже есть открытая сделка (как в бэктесте)
        ev = await self.news_pause(now)
        if ev is not None:
            log.info("signal skipped (%s): news %s at %s", st.key, ev.get("title"), ev.get("ts"))
            return None  # рядом важная новость США — рынок непредсказуем

        d = await self.direction(df, now, st)
        if d == 0:
            return None
        open_dirs = open_dirs if open_dirs is not None else set()
        if -d in open_dirs:
            log.info("signal skipped (%s): %s while an opposite trade is open", st.key, "BUY" if d == 1 else "SELL")
            return None  # встречный сигнал: пока открыта сделка в другую сторону, не даём
        info = None
        if self.news_bias is not None:
            try:
                info = await self.news_bias(await self.market_text(now))
            except Exception:  # noqa: BLE001 — без оценки новостей работаем по графику
                log.exception("news bias")
            side = {"bullish": 1, "bearish": -1}.get((info or {}).get("bias"), 0)
            if self.news_block and side == -d and (info or {}).get("strength") == "strong":
                log.info("signal skipped (%s): strong news background against %s", st.key,
                         "BUY" if d == 1 else "SELL")
                return None
        entry = price
        sl = entry - d * self.sl_pips * PIP
        tp = entry + d * self.tp_pips * PIP
        sid = await self.db.add_signal(st.key, d, entry, sl, tp)
        open_keys.add(st.key)
        open_dirs.add(d)
        when = now.tz_convert(self.tz).strftime("%d.%m.%Y %H:%M")
        title = f"XAUUSD {tf.replace('min', 'm')} · #{sid}"
        img = render_signal(df, d, entry, sl, tp, title, tz=self.tz)
        ns = NewSignal(sid, d, entry, sl, tp, img,
                       per_lang(lambda lang: format_signal(st, d, entry, sl, tp,
                                                           self.sl_pips, self.tp_pips, when, lang)
                                + news_line(info, d, lang)),
                       lambda **kw: render_signal(df, d, entry, sl, tp, title, tz=self.tz, **kw))
        await self.on_signal(ns)
        return ns

    async def direction(self, df: pd.DataFrame, now: pd.Timestamp, st: LiveStrategy | None = None) -> int:
        """Сигнал на последней закрытой свече: 1 BUY, -1 SELL, 0 нет.
        С фильтром дневного тренда сигнал против тренда пропускается; у составной стратегии
        берётся первая её часть, давшая сигнал по тренду."""
        st = st or self.strategy
        raw = [int(p(df)[-1]) for p in (st.parts or (st.signals,))]
        if not any(raw):
            return 0
        if not st.daily_trend:
            return next(x for x in raw if x)
        trend = await self.daily_trend(now)
        return next((x for x in raw if x and x == trend), 0)

    async def daily_trend(self, now: pd.Timestamp) -> int:
        """Дневной тренд по EMA50 (запрашиваем дневные свечи только когда он нужен, один раз за день UTC)."""
        day = now.tz_convert("UTC").normalize()
        if self._trend is None or self._trend[0] != day:
            self._trend = (day, daily_trend_side(await self.provider.candles("1day", 150), now))
        return self._trend[1]

    async def expected(self, lang: str = "ru") -> str:
        now = pd.Timestamp.now(tz="UTC")
        if self.multi:
            trend = await self.daily_trend(now)
            lines = [t(lang, "exp_portfolio", n=len(self.strategies))]
            lines += [f"• {t(lang, f'strat_{st.key}')}" for st in self.strategies]
            lines += [t(lang, "exp_daily_trend",
                        trend=t(lang, "exp_trend_up" if trend >= 0 else "exp_trend_down")),
                      t(lang, "exp_confirm")]
            return "\n".join(lines)
        tf = self.strategy.timeframe
        df = self.dfs.get(tf)
        if df is None or df.empty:
            df = closed_bars(await self.provider.candles(tf, CANDLES), tf, now)
            self.dfs[tf] = self.last_df = df
        trend = await self.daily_trend(now) if self.strategy.daily_trend else 0
        return expected_setup(df, self.strategy.key, now, self.tz, lang, trend)

    async def run_forever(self, interval: int) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — бот не должен падать из-за сети
                log.exception("market check failed")
            await asyncio.sleep(interval)
