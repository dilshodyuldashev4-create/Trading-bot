"""Telegram-бот: меню, подписка (Telegram Stars), пробный период, админ-панель, рассылка сигналов."""
from __future__ import annotations

import asyncio
import csv
import html
import io
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BufferedInputFile, CallbackQuery, ChatMemberUpdated, InlineKeyboardButton,
                           InlineKeyboardMarkup, KeyboardButton, LabeledPrice, Message,
                           PreCheckoutQuery, ReplyKeyboardMarkup, ReplyParameters)

import json

from . import changelog, econ_calendar, news_alerts
from . import daily_report as dr
from . import prop as pr
from .autotrade import split_volume, BROKERS, AutoTrader, BrokerMarket, MetaApi, MetaApiError, demo_servers, sl_tp_dist
from .config import config
from .db import DB, now
from .chart import render_signal, render_stats
from .engine import NewSignal, SignalEngine, market_open, next_open, parse_hhmm
from .i18n import CHOOSE, LANG_BUTTONS, norm, t, variants
from .data import PIP
from .lots import fmt_usd, lot_for, money, parse_capital
from .market import Failover, make_provider
from .news import NewsService
from .results import WIN, move_pips, part_pips, signal_pips, tp1_move_pips
from .health import AlertHandler, Watch, backup_db

log = logging.getLogger(__name__)


def menu(lang: str) -> ReplyKeyboardMarkup:
    b = lambda key: KeyboardButton(text=t(lang, key))  # noqa: E731
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [b("btn_signal")],
        [b("btn_fund"), b("btn_cal")],
        [b("btn_stats")],
        [b("btn_sub"), b("btn_profile")],
        *([[b("btn_auto"), b("btn_fundednext")]] if config.metaapi_token else []),
    ])


LANG_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text=label, callback_data=f"lang:{code}")] for code, label in LANG_BUTTONS])

ADMIN_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📈 Статистика", callback_data="adm:stats"),
     InlineKeyboardButton(text="📣 Рассылка", callback_data="adm:broadcast")],
    [InlineKeyboardButton(text="👥 Подписчики (CSV)", callback_data="adm:export"),
     InlineKeyboardButton(text="🧾 Последние сигналы", callback_data="adm:signals")],
    [InlineKeyboardButton(text="📢 Telegram-канал", callback_data="adm:channel")],
    [InlineKeyboardButton(text="🎁 Выдать / забрать подписку", callback_data="adm:granthelp")],
    [InlineKeyboardButton(text="🆕 Обновление: отправить всем", callback_data="adm:release")],
])


def release_kb(version: str, sent: bool = False) -> InlineKeyboardMarkup:
    send = ("🔁 Отправить ещё раз", f"rel:force:{version}") if sent else ("📣 Отправить всем", f"rel:send:{version}")
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=send[0], callback_data=send[1]),
        InlineKeyboardButton(text="❌ Не отправлять", callback_data=f"rel:skip:{version}")]])


class AdminStates(StatesGroup):
    broadcast = State()


class CapitalStates(StatesGroup):
    waiting = State()


class AutoStates(StatesGroup):
    broker_name = State()   # «Другой брокер»: ждём название
    server = State()        # ждём имя сервера вручную
    login = State()
    password = State()


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def broker_kb(lang: str) -> InlineKeyboardMarkup:
    rows = [[_btn(name, f"at:br:{i}") for i, (name, _) in enumerate(BROKERS)][j:j + 3]
            for j in range(0, len(BROKERS), 3)]
    rows.append([_btn(t(lang, "btn_other_broker"), "at:br:other")])
    rows.append([_btn(t(lang, "btn_cancel"), "at:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def servers_kb(lang: str, servers: list[str]) -> InlineKeyboardMarkup:
    rows = [[_btn(sv, f"at:sv:{i}")] for i, sv in enumerate(servers)]
    rows.append([_btn(t(lang, "btn_server_manual"), "at:sv:manual")])
    rows.append([_btn(t(lang, "btn_cancel"), "at:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def connect_error_text(lang: str, e: Exception, server: str) -> str:
    code = getattr(e, "code", "")
    if code == "NOT_PAID":
        return t(lang, "at_pay") + t(lang, "at_pay_each")
    key = {"E_AUTH": "at_err_auth", "E_SRV_NOT_FOUND": "at_err_server", "REAL_NOT_ALLOWED": "at_err_real",
           "DEMO_NOT_ALLOWED": "at_err_demo", "READ_ONLY": "at_err_readonly",
           "NO_GOLD": "at_err_gold", "TIMEOUT": "at_err_timeout"}.get(code)
    if not key and isinstance(e, asyncio.TimeoutError):
        key = "at_err_timeout"
    if key:
        return t(lang, key, server=html.escape(server)) if key == "at_err_server" else t(lang, key)
    return t(lang, "at_err_other", error=html.escape(code or str(e) or type(e).__name__)[:150])


def usd(x: float) -> str:
    return f"${x:,.2f}".replace(",", " ")


def reply_to(msg_id: int | None) -> dict:
    """Аргументы «ответом на сообщение» (на карточку сигнала); карточки нет — обычное сообщение."""
    if not msg_id:
        return {}
    return {"reply_parameters": ReplyParameters(message_id=msg_id, allow_sending_without_reply=True)}


def card_status(lang: str, s: dict, status: str | None, price: float | None, tz: str) -> str:
    """Блок состояния живой карточки сигнала: ход сделки, фиксация части, итог."""
    d, entry = s["direction"], s["entry"]
    lines = []
    if s.get("part_at"):
        lines.append(t(lang, "card_partial", pct=f"{100 * (s.get('part') or 0):.0f}", tp1=f"{s['tp1']:.2f}",
                       entry=f"{entry:.2f}"))
    if status in ("tp", "sl", "be", "rev", "news"):
        if status == "news":
            pips = d * ((price or entry) - entry) / PIP
        else:
            pips = signal_pips({**s, "exit_price": price} if status == "rev" else s, status) or 0
        lines.append(t(lang, f"card_{status}", pips=f"{pips:+.0f}"))
    elif price is not None:
        dist = abs(entry - s["sl"]) or 1e-9
        r = d * (price - entry) / dist
        when = datetime.now(ZoneInfo(tz)).strftime("%H:%M")
        lines.append(t(lang, "card_live", r=f"{r:+.1f}", pips=f"{d * (price - entry) / PIP:+.0f}",
                       price=f"{price:.2f}", time=when))
    return "\n".join(lines)


def trade_error_text(lang: str, error: str) -> str:
    if error == "SPREAD":
        return t(lang, "at_e_spread")
    if error == "PROP_LIMIT":
        return t(lang, "at_e_prop")
    if error == "PROP_DAY_LOSS":
        return t(lang, "at_e_prop_loss")
    if error == "DAY_LOSS":
        return t(lang, "at_e_day_loss", n=config.autotrade_day_losses)
    if error == "DAY_SIDE":
        return t(lang, "at_e_day_side")
    if error in ("NO_MONEY", "TRADE_RETCODE_NO_MONEY"):
        return t(lang, "at_e_money")
    if error in ("TRADE_RETCODE_MARKET_CLOSED", "TRADE_RETCODE_TRADE_DISABLED"):
        return t(lang, "at_e_market")
    if error in ("TRADE_RETCODE_CONNECTION", "TRADE_RETCODE_NO_CONNECTION") or "connect" in error.lower():
        return t(lang, "at_e_conn")
    return html.escape(error)[:150]


STARS_SAFE_MAX = 2500   # столько ⭐ в одном счёте Telegram принимает точно; больше — если позволяет лимит Telegram


def autotrade_plan(month_usd: float, stars_per_usd: float, cap: int, max_days: int) -> tuple[int, int, int]:
    """Цена автоторговли: (дней за одну оплату, ⭐ за эти дни, ⭐ за 30 дней). Месяц стоит month_usd долларов;
    один счёт Telegram — не больше cap ⭐, поэтому за раз продаём столько дней, сколько в него помещается."""
    month_stars = max(1, round(month_usd * stars_per_usd))
    days = max(1, min(max_days, 30 * cap // month_stars))
    return days, max(1, round(month_stars * days / 30)), month_stars


def fmt_money(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ") if abs(x - round(x)) < 0.005 else f"{x:,.2f}".replace(",", " ")


CAPITAL_PRESETS = (50, 100, 200, 300, 500, 1000, 2000, 5000)


def capital_kb(lang: str) -> InlineKeyboardMarkup:
    btn = lambda v: InlineKeyboardButton(text=f"${v:,}".replace(",", " "), callback_data=f"cap:{v}")  # noqa: E731
    rows = [[btn(v) for v in CAPITAL_PRESETS[i:i + 4]] for i in range(0, len(CAPITAL_PRESETS), 4)]
    rows.append([InlineKeyboardButton(text=t(lang, "btn_skip"), callback_data="cap:skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lot_plan(capital: float, sl_pips: float = 0, tp_pips: float = 0, tp1_pips: float = 0, part: float = 0,
             size: float = 1.0) -> dict:
    """Лот подписчика и что он теряет/зарабатывает по стопу/тейку (пипсы сигнала; 0 — из настроек).
    С фиксацией части (tp1_pips, part) прибыль до тейка — часть на tp1 и остаток на тейке.
    size — множитель лота сигнала (две стратегии согласны — больше, одиночный сигнал — меньше)."""
    sl_pips, tp_pips = sl_pips or config.sl_pips, tp_pips or config.tp_pips
    if config.lot_mode == "risk":
        lot = lot_for(capital, config.lot_mode, config.lot_risk_pct * size, sl_pips)
    else:
        lot = max(0.01, round(lot_for(capital, config.lot_mode, config.lot_risk_pct, sl_pips) * size, 2))
    loss, profit = money(lot, sl_pips), money(lot, tp_pips)
    if tp1_pips and part:
        profit = money(lot, tp1_pips) * part + money(lot, tp_pips) * (1 - part)
    return {"lot": lot, "loss": loss, "profit": profit, "loss_pct": 100 * loss / capital}


def lot_text(lang: str, capital: float | None, sl_pips: float = 0, tp_pips: float = 0,
             tp1_pips: float = 0, part: float = 0, size: float = 1.0) -> str:
    """Блок «Ваш лот» для подписи сигнала."""
    strong = t(lang, "sig_strong", x=f"{size:g}") if size > 1 + 1e-9 else ""
    if not capital:
        return strong + t(lang, "sig_nocap")
    p = lot_plan(capital, sl_pips, tp_pips, tp1_pips, part, size)
    pct = f"{p['loss_pct']:.1f}".rstrip("0").rstrip(".")
    text = t(lang, "sig_lot", lot=f"{p['lot']:.2f}", cap=fmt_usd(capital), loss=fmt_usd(p["loss"]),
             loss_pct=pct, profit=fmt_usd(p["profit"]))
    limit = config.lot_risk_pct * max(size, 1.0) if config.lot_mode == "risk" else None
    if limit and p["loss_pct"] > limit + 1e-9:
        text += t(lang, "sig_lot_warn", loss_pct=pct, pct=f"{limit:g}")
    return strong + text


def late_hint(lang: str, direction: int, entry: float) -> str:
    """«Входить, только пока цена не выше/ниже X» — для тех, кто увидит сигнал позже."""
    if config.late_pips <= 0:
        return ""
    limit = entry + direction * config.late_pips * PIP
    return t(lang, "late_hint_buy" if direction == 1 else "late_hint_sell", limit=f"{limit:.2f}")


def decision_kb(lang: str, sid: int, choice: str | None = None) -> InlineKeyboardMarkup:
    """Кнопки под сигналом; выбранная помечена «•»."""
    mark = lambda key, c: ("• " if choice == c else "") + t(lang, key)  # noqa: E731
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=mark("btn_accept", "acc"), callback_data=f"sig:acc:{sid}"),
        InlineKeyboardButton(text=mark("btn_decline", "dec"), callback_data=f"sig:dec:{sid}")]])


def excursion_text(lang: str, s: dict, status: str) -> str:
    """Сколько сделка была в плюсе и какая была просадка (пипсы и цена) — для отчёта о закрытии."""
    d, out = s["direction"], []
    v = s.get("mfe") or 0
    out.append(t(lang, "close_mfe", pips=f"{v:.0f}", price=f"{s['entry'] + d * v * PIP:.2f}") if v >= 1
               else t(lang, "close_mfe_none"))
    v = s.get("mae") or 0
    out.append(t(lang, "close_mae", pips=f"{v:.0f}", price=f"{s['entry'] - d * v * PIP:.2f}") if v >= 1
               else t(lang, "close_mae_none"))
    return "\n".join(out) + "\n\n"


def part_split(lang: str, s: dict, status: str | None = None) -> str:
    """Строка «часть закрыта на tp1 (+X), остаток на выходе (+Y), итог на весь лот» для сигнала с фиксацией."""
    status = status or s["status"]
    part = s.get("part") or 0
    level = s["tp"] if status == "tp" else s.get("exit_price")
    return t(lang, "part_split", pct=f"{100 * part:.0f}", tp1=f"{s['tp1']:.2f}", p1=f"{tp1_move_pips(s):+.0f}",
             rest=f"{100 * (1 - part):.0f}", exit=f"{level:.2f}", p2=f"{move_pips(s, status):+.0f}",
             total=f"{signal_pips(s, status):+.0f}")


def stats_text(lang: str, rows: list[dict], tz: str) -> str:
    """Статистика для подписчиков: итоги и последние сигналы со входом, выходом и результатом."""
    from datetime import datetime
    if not rows:
        return t(lang, "stats_empty")
    win = [r for r in rows if r["status"] in WIN]   # тейк, безубыток после фиксации, разворот
    sl = [r for r in rows if r["status"] == "sl"]
    total = sum(v for v in (signal_pips(r) for r in rows) if v is not None)
    closed = len(win) + len(sl)
    n_open = sum(1 for r in rows if r["status"] == "open")
    out = t(lang, "stats_head", total=len(rows), tp=len(win), sl=len(sl), open=n_open,
            wr=f"{100 * len(win) / closed:.0f}%" if closed else "—", pips=f"{total:+.0f}")
    for r in rows[:15]:
        v = signal_pips(r)
        if r["status"] == "tp":   # пипсы хода цены до тейка; при фиксации части ниже — итог на весь лот
            res = t(lang, "stats_tp", exit=f"{r['tp']:.2f}", pips=f"{move_pips(r):.0f}")
        elif r["status"] == "sl":
            res = t(lang, "stats_sl", exit=f"{r['sl']:.2f}", pips=f"{-v:.0f}")
        elif r["status"] == "be":
            res = t(lang, "stats_be", tp1=f"{r['tp1']:.2f}", pips=f"{v:+.0f}")
        elif r["status"] == "rev" and v is not None:
            res = t(lang, "stats_rev", exit=f"{r['exit_price']:.2f}", pips=f"{v:+.0f}")
        elif r["status"] == "news" and v is not None:
            res = t(lang, "stats_news", exit=f"{r['exit_price']:.2f}", pips=f"{v:+.0f}")
        elif r["status"] == "open" and r.get("part_at"):
            res = t(lang, "stats_open_part", tp1=f"{r['tp1']:.2f}")
        else:
            res = t(lang, "stats_open")
        if r.get("part_at") and r["status"] in ("tp", "rev") and v is not None:
            res += part_split(lang, r)
        when = datetime.fromisoformat(r["created_at"]).astimezone(ZoneInfo(tz)).strftime("%d.%m %H:%M")
        out += t(lang, "stats_row", id=r["id"], when=when, side="🟢 BUY" if r["direction"] == 1 else "🔴 SELL",
                 entry=f"{r['entry']:.2f}", sl=f"{r['sl']:.2f}", tp=f"{r['tp']:.2f}", result=res)
    return out


def signal_caption(lang: str, text: str, capital: float | None, direction: int, entry: float,
                   sl_pips: float = 0, tp_pips: float = 0, tp1_pips: float = 0, part: float = 0,
                   size: float = 1.0) -> str:
    """Подпись к фото сигнала для конкретного подписчика: его лот, до какой цены входить, правила."""
    rules = t(lang, "sig_rules", n=config.max_sl_streak) if config.max_sl_streak > 0 else ""
    return with_lot(text, lot_text(lang, capital, sl_pips, tp_pips, tp1_pips, part, size)
                    + late_hint(lang, direction, entry)) + rules


def with_lot(caption: str, block: str) -> str:
    """Вставляет блок лота (и подсказку «до какой цены входить») перед курсивной припиской внизу сигнала."""
    mark = "\n\n<i>"
    return caption.replace(mark, block + mark, 1) if mark in caption else caption + block


class App:
    autotrader: AutoTrader | None = None
    alerts: AlertHandler | None = None

    def __init__(self) -> None:
        session = AiohttpSession(proxy=config.telegram_proxy) if config.telegram_proxy else None
        self.bot = Bot(config.bot_token, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dp = Dispatcher()
        self.db = DB(config.db_path)
        self._release_lock = asyncio.Lock()  # одна рассылка об обновлении за раз
        self.news = NewsService(config.news_feeds, config.anthropic_model)
        self.provider = make_provider(config)
        self.engine = SignalEngine(self.db, self.provider, config.strategy, config.sl_pips, config.tp_pips,
                                   config.display_tz, self.broadcast_signal, self.broadcast_close,
                                   self.broadcast_late, config.late_pips,
                                   self.broadcast_day_closed, config.max_sl_streak)
        self.engine.sl_atr, self.engine.tp_atr = config.sl_atr, config.tp_atr
        self.engine.sl_min_pips = config.sl_min_pips
        self.engine.partial_r, self.engine.final_r = config.partial_r, config.final_tp_r
        self.engine.partial_pct = max(0.0, min(config.partial_pct, 90.0)) / 100
        self.engine.on_partial = self.broadcast_partial
        self.engine.reversal_close = config.reversal_close
        self.engine.reversal_min_pips = config.reversal_min_pips
        self.engine.adx_max, self.engine.adx_keys = config.adx_max, config.adx_keys
        self.engine.has_prop = self.has_prop
        self.engine.pin_hours = config.candle_pin_hours
        self.engine.confluence_min = config.confluence_min
        self.engine.confluence_single = config.confluence_single
        self.engine.confluence_strong = config.confluence_strong
        self.engine.news_pause_min = config.news_pause_min
        self.engine.news_pause_impact = config.news_pause_impact
        self.engine.news_bias = self.news.bias       # строка о фоне новостей в сигнале
        self.engine.news_close_min = config.news_close_min
        self.engine.on_news_close = self.broadcast_news_close
        self.engine.news_block = config.news_filter  # блокировать сигнал против сильного фона
        self.engine.news_trade = self.news_trade_on  # торговля во время новостей (/newstrade)
        self.engine.news_event_bias = self.news.event_bias
        self.engine.news_hot_before, self.engine.news_hot_after = config.news_hot_before, config.news_hot_after
        self.autotrader: AutoTrader | None = None
        self.stars_cap = config.stars_invoice_max   # лимит ⭐ на один счёт; уменьшается, если Telegram отказал
        if config.metaapi_token:
            self.autotrader = AutoTrader(self.db, MetaApi(config.metaapi_token), config.autotrade_demo_only,
                                         real_only=config.autotrade_real_only, risk_pct=config.autotrade_risk_pct,
                                         max_lot=config.autotrade_max_lot, symbol_override=config.autotrade_symbol,
                                         region=config.metaapi_region,
                                         exempt=frozenset(config.admin_ids), paid_days=self.at_days,
                                         prop_risk_pct=config.prop_risk_pct,
                                         prop_strong_risk_pct=config.prop_strong_risk_pct, prop_guard_pct=config.prop_guard_pct,
                                         prop_max_lot=config.prop_max_lot, prop_risk_cap=config.prop_risk_cap,
                                         prop_max_trade=config.prop_max_trade_pct,
                                         prop_day_tz=config.prop_day_tz,
                                         prop_close=config.prop_close,
                                         prop_day_losses=config.prop_day_losses,
                                         prop_dd_pct=config.prop_dd_pct, prop_dd_mult=config.prop_dd_mult,
                                         prop_tp_r=config.prop_tp_r if config.partial_r > 0 else 0.0,
                                         prop_partial=config.prop_partial,
                                         max_spread_pct=config.autotrade_max_spread_pct,
                                         spread_wait=config.autotrade_spread_wait,
                                         prop_milestones=config.prop_milestones,
                                         day_losses=config.autotrade_day_losses, day_side=config.autotrade_day_side,
                                         dd_pct=config.autotrade_dd_pct, dd_mult=config.autotrade_dd_mult)
        if self.autotrader and config.market_from_broker:
            # анализ по графику брокера с подключённого счёта админа; запасной — прежний источник
            self.provider = Failover(BrokerMarket(self.autotrader.api, self.market_account), self.provider,
                                     price_timeout=15, candle_timeout=40, price_cooldown=15)
            self.engine.provider = self.provider
        self._market_src: tuple[float, dict | None] = (0.0, None)
        self._connecting: set[int] = set()   # чьи счета сейчас подключаются
        self._tasks: set[asyncio.Task] = set()
        self._card_r: dict[int, float] = {}   # сигнал → ход сделки (R) в последнем обновлении живой карточки
        self._bot_name: str | None = None     # @имя бота — для ссылки в постах канала
        self.router = Router()
        self._register()
        self.dp.include_router(self.router)

    # ── helpers ──────────────────────────────────────────────────────────────
    def fmt_dt(self, iso_or_dt) -> str:
        from datetime import datetime
        d = datetime.fromisoformat(iso_or_dt) if isinstance(iso_or_dt, str) else iso_or_dt
        return d.astimezone(ZoneInfo(config.display_tz)).strftime("%d.%m.%Y %H:%M")

    async def send_long(self, chat_id: int, text: str, **kw) -> None:
        chunk = ""
        for line in text.split("\n"):
            if len(chunk) + len(line) + 1 > 3900:
                await self.bot.send_message(chat_id, chunk, **kw)
                chunk = ""
            chunk += line + "\n"
        if chunk.strip():
            await self.bot.send_message(chat_id, chunk, **kw)

    async def _send(self, uid: int, coro_factory) -> bool:
        try:
            await coro_factory()
            return True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            return await self._send(uid, coro_factory)
        except TelegramForbiddenError:
            await self.db.set_blocked(uid)
        except Exception as e:  # noqa: BLE001
            log.warning("send to %s failed: %s", uid, e)
        return False

    async def broadcast(self, uids: list[int], make) -> int:
        ok = 0
        for uid in uids:
            ok += await self._send(uid, lambda u=uid: make(u))
            await asyncio.sleep(0.04)  # не больше ~25 сообщений в секунду
        return ok

    # ── Telegram-канал: туда же всё, что получают подписчики ──────────────
    async def chan_target(self) -> int | str | None:
        """Куда постить: канал из /channel (база) или CHANNEL_ID из .env; None — канал не подключён."""
        v = await self.db.get_kv("channel_id")
        v = (config.channel_id if v is None else v).strip()
        if not v or v == "off":
            return None
        if v.lstrip("-").isdigit():
            return int(v)
        return v if v.startswith("@") else "@" + v.split("/")[-1]

    async def chan_lang(self) -> str:
        return norm(await self.db.get_kv("channel_lang") or config.channel_lang)

    async def chan_cta(self, lang: str) -> str:
        """Ссылка на бота под постом канала."""
        if self._bot_name is None:
            try:
                self._bot_name = (await self.bot.get_me()).username or ""
            except Exception:  # noqa: BLE001
                return ""
        return t(lang, "chan_cta", bot=self._bot_name) if self._bot_name else ""

    async def to_channel(self, make, raise_errors: bool = False):
        """make(chat_id, lang) → корутина отправки. Ошибка канала не мешает рассылке подписчикам."""
        cid = await self.chan_target()
        if cid is None:
            return None
        lang = await self.chan_lang()
        for _ in range(3):
            try:
                return await make(cid, lang)
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except Exception as e:  # noqa: BLE001
                if raise_errors:
                    raise
                log.error("Telegram-канал: не удалось отправить пост (%s). Бот админ в канале? /channel", e)
                return None
        return None

    async def chan_card(self, sid: int) -> dict | None:
        v = await self.db.get_kv(f"chan_card:{sid}")
        return json.loads(v) if v else None

    async def chan_reply(self, sid: int) -> dict:
        """Ответом на пост сигнала в канале (если он есть)."""
        c = await self.chan_card(sid)
        return reply_to(c and c.get("m"))

    async def chan_post_signal(self, s: NewSignal) -> None:
        async def send(cid, lang):
            strong = t(lang, "sig_strong", x=f"{s.size:g}") if s.size > 1 + 1e-9 else ""
            rules = t(lang, "sig_rules", n=config.max_sl_streak) if config.max_sl_streak > 0 else ""
            caption = (with_lot(s.texts[lang], strong + late_hint(lang, s.direction, s.entry)) + rules
                       + await self.chan_cta(lang))
            m = await self.bot.send_photo(cid, BufferedInputFile(s.image, filename=f"signal_{s.id}.png"),
                                          caption=caption)
            await self.db.set_kv(f"chan_card:{s.id}", json.dumps({"m": m.message_id, "c": caption}))
            return m
        await self.to_channel(send)

    async def chan_text(self, make_text, reply: dict | None = None, **kw) -> None:
        """Текстовый пост в канал: make_text(lang) → текст."""
        await self.to_channel(lambda cid, lang: self.bot.send_message(cid, make_text(lang), **(reply or {}), **kw))

    async def channel_panel(self) -> tuple[str, InlineKeyboardMarkup]:
        """/channel для админа: какой канал подключён, язык постов, кнопки."""
        cid = await self.chan_target()
        lang = await self.chan_lang()
        langs = [InlineKeyboardButton(text=("• " if code == lang else "") + label, callback_data=f"chan:lang:{code}")
                 for code, label in LANG_BUTTONS]
        if cid is None:
            text = ("📢 <b>Telegram-канал не подключён</b>\n\n"
                    "1. Создайте канал в Telegram (открытый или закрытый).\n"
                    "2. Канал → Управление каналом → Администраторы → Добавить администратора → "
                    "найдите этого бота → разрешите «Публикация сообщений» → Сохранить.\n"
                    "3. Бот сам напишет вам сюда, что канал подключён.\n\n"
                    "После этого в канал будет уходить всё, что получают подписчики: сигналы, фиксация и безубыток, "
                    "итоги сделок, отчёты, утренние разборы и новости.")
            return text, InlineKeyboardMarkup(inline_keyboard=[langs])
        try:
            chat = await self.bot.get_chat(cid)
            name = html.escape(chat.title or str(cid))
        except Exception as e:  # noqa: BLE001
            name = f"{html.escape(str(cid))}\n⚠️ Бот не видит канал: {html.escape(str(e))[:150]}"
        text = (f"📢 <b>Telegram-канал подключён</b>: {name}\n\n"
                "Туда уходит всё, что получают подписчики: сигналы, фиксация и безубыток, итоги сделок, отчёты, "
                "утренние разборы и новости. Язык постов — ниже.")
        return text, InlineKeyboardMarkup(inline_keyboard=[
            langs,
            [InlineKeyboardButton(text="📨 Тестовый пост", callback_data="chan:test")],
            [InlineKeyboardButton(text="⛔️ Отключить канал", callback_data="chan:off")]])

    async def broadcast_signal(self, s: NewSignal) -> None:
        """Каждому подписчику — картинка и текст с его лотом (по его капиталу)."""
        self.spawn(self.autotrade_open(s))   # на подключённых счетах сделка открывается сразу
        if s.prop_only:   # пробой при сильном разгоне (ADX): только проп-счета, подписчикам не шлём
            return
        await self.chan_post_signal(s)
        uids = await self.db.active_user_ids()
        langs = await self.db.user_langs()
        caps = await self.db.user_capitals()
        images: dict[float, bytes] = {}  # лот → картинка (рисуем один раз на каждый разный лот)

        async def image_for(capital: float | None) -> bytes:
            if not capital or s.render is None:
                return s.image
            p = lot_plan(capital, s.sl_pips, s.tp_pips, s.tp1_pips, s.part, s.size)
            if p["lot"] not in images:
                extra = {}
                if s.tp1 and s.part:   # у линии TP1 — сколько даст фиксация части, у TP — остаток
                    extra = {"tp1_note": f"{100 * s.part:.0f}% +${fmt_usd(money(p['lot'], s.tp1_pips) * s.part)}",
                             "tp_note": f"+${fmt_usd(money(p['lot'], s.tp_pips) * (1 - s.part))}"}
                try:
                    images[p["lot"]] = await asyncio.to_thread(
                        s.render, lot=f"LOT {p['lot']:.2f}",
                        sl_note=f"−${fmt_usd(p['loss'])}", **{"tp_note": f"+${fmt_usd(p['profit'])}", **extra})
                except Exception:  # noqa: BLE001
                    log.exception("lot chart")
                    images[p["lot"]] = s.image
            return images[p["lot"]]

        ok = 0
        for u in uids:
            lang, capital = norm(langs.get(u)), caps.get(u)
            img = await image_for(capital)
            caption = signal_caption(lang, s.texts[lang], capital, s.direction, s.entry, s.sl_pips, s.tp_pips,
                                     s.tp1_pips, s.part, s.size)
            box: dict = {}

            async def send_card(u=u, img=img, caption=caption, lang=lang, box=box):
                box["m"] = await self.bot.send_photo(
                    u, BufferedInputFile(img, filename=f"signal_{s.id}.png"), caption=caption,
                    reply_markup=decision_kb(lang, s.id))
            sent = await self._send(u, send_card)
            if sent:  # запоминаем, кто получил сигнал, с каким лотом (0 — капитал не указан) и его карточку
                msg = box.get("m")
                await self.db.add_signal_lot(
                    s.id, u, lot_plan(capital, s.sl_pips, s.tp_pips, size=s.size)["lot"] if capital else 0,
                    getattr(msg, "message_id", None), caption if config.live_card else None)
            ok += sent
            await asyncio.sleep(0.04)
        log.info("signal #%s sent to %s users", s.id, ok)

    async def broadcast_news_close(self, s: dict, price: float, ev: dict, mins: int) -> None:
        """Перед важной новостью: всем — закрыть сделку по рынку."""
        self.spawn(self.autotrade_close(s["id"]))
        if s.get("prop_only"):
            return
        self.spawn(self.update_cards(s, "news", price))
        side = "BUY" if s["direction"] == 1 else "SELL"
        res = s["direction"] * (price - s["entry"]) / PIP
        langs = await self.db.user_langs()

        def text(lang: str) -> str:
            return t(lang, "news_close", id=s["id"], side=side, entry=f"{s['entry']:.2f}", mins=mins,
                     title=html.escape(ev.get("title", "")), price=f"{price:.2f}", pips=f"{res:+.0f}")

        await self.chan_text(text, await self.chan_reply(s["id"]))
        n = await self.broadcast(await self.db.all_user_ids(),
                                 lambda u: self.bot.send_message(u, text(norm(langs.get(u)))))
        log.info("news close #%s sent to %s users", s["id"], n)

    async def broadcast_close(self, s: dict, status: str, price: float) -> None:
        """Итог сигнала — всем участникам бота (подписчикам и тем, у кого доступ закончился)."""
        # что не закрыл брокер по своим SL/TP — закрываем (проп-счета ведут свои SL/TP, кроме стопа и тейка сигнала)
        self.spawn(self.autotrade_close(s["id"], skip_prop=status in ("be", "rev")))
        if s.get("prop_only"):   # сигнал только для проп-счетов: подписчикам о нём не писали
            return
        side = "BUY" if s["direction"] == 1 else "SELL"
        if status == "rev":
            s = {**s, "exit_price": price}
        level = {"tp": s["tp"], "sl": s["sl"], "be": s["entry"]}.get(status, price)
        res = signal_pips(s, status)   # весь лот: зафиксированная часть + остаток
        pips = abs(res)
        st = await self.db.stats()
        wins = st["tp"] + st["be"]
        closed = wins + st["sl"]
        key = {"tp": "close_tp", "sl": "close_sl", "be": "close_be", "rev": "close_rev"}[status]

        def text(lang: str) -> str:
            head = t(lang, key, id=s["id"], side=side, pips=f"{pips:.0f}", price=f"{price:.2f}")
            if s.get("part_at") and status in ("tp", "rev"):
                head += part_split(lang, s, status)
            elif s.get("part_at") and status == "be":
                head += t(lang, "close_part_note", pct=f"{100 * (s.get('part') or 0):.0f}", tp1=f"{s['tp1']:.2f}",
                          pips=f"{part_pips(s):+.0f}")
            return (head + "\n\n" + excursion_text(lang, s, status)
                    + t(lang, "close_body", entry=f"{s['entry']:.2f}", exit=f"{level:.2f}",
                                  sl=f"{s['sl']:.2f}", tp=f"{s['tp']:.2f}", tp_n=wins, sl_n=st["sl"])
                    + (t(lang, "winrate", wr=f"{100 * wins / closed:.0f}") if closed else ""))

        image = None
        df = self.engine.df_for(s.get("strategy"))
        if df is not None:
            try:
                label = {"tp": "TAKE PROFIT", "sl": "STOP LOSS", "be": "BREAKEVEN", "rev": "REVERSAL"}[status]
                image = render_signal(df, s["direction"], s["entry"], s["sl"], s["tp"],
                                      f"XAUUSD · #{s['id']} · {label}",
                                      tz=config.display_tz, mfe=s.get("mfe"), mae=s.get("mae"), pip=PIP,
                                      tp1=s.get("tp1"))
            except Exception:  # noqa: BLE001
                log.exception("close chart")
        active = set(await self.db.active_user_ids())
        langs = await self.db.user_langs()

        # у кого был лот в этом сигнале — пересчитываем баланс и пишем результат в $
        results: dict[int, str] = {}
        for u, lot in (await self.db.signal_lots(s["id"])).items():
            if not lot:
                continue
            pnl = money(lot, pips) * (1 if res >= 0 else -1)
            bal = await self.db.add_capital(u, pnl)
            results[u] = (lot, pnl, bal)

        def balance_text(lang: str, u: int) -> str:
            if u not in results:
                return ""
            lot, pnl, bal = results[u]
            sign = "+" if pnl >= 0 else "−"
            return t(lang, "close_balance", lot=f"{lot:.2f}", pnl=f"{sign}${fmt_usd(abs(pnl))}", bal=fmt_usd(bal))

        declined = await self.db.declined_users(s["id"])
        cards = {c["user_id"]: c["msg_id"] for c in await self.db.signal_cards(s["id"])}
        await self.update_cards(s, status, price)

        def make(u: int):
            lang = norm(langs.get(u))
            body = text(lang) + balance_text(lang, u)
            if u not in active:
                body += t(lang, "close_cta")
            reply = reply_to(cards.get(u))   # итог — ответом на карточку сигнала
            if image:
                return self.bot.send_photo(u, BufferedInputFile(image, f"result_{s['id']}.png"), caption=body,
                                           **reply)
            return self.bot.send_message(u, body, **reply)

        chan_reply = await self.chan_reply(s["id"])

        async def chan_close(cid, lang):
            body = text(lang) + await self.chan_cta(lang)
            if image:
                return await self.bot.send_photo(cid, BufferedInputFile(image, f"result_{s['id']}.png"),
                                                 caption=body, **chan_reply)
            return await self.bot.send_message(cid, body, **chan_reply)
        await self.to_channel(chan_close)

        # кто нажал «Отклонить» под этим сигналом — результат по нему не присылаем
        await self.broadcast([u for u in await self.db.all_user_ids() if u not in declined], make)

    async def broadcast_partial(self, s: dict, price: float) -> None:
        """Цена дошла до TP1: тем, кто получил сигнал — закрыть часть и перенести стоп в безубыток;
        на счетах автоторговли бот делает это сам."""
        self.spawn(self.autotrade_partial(s["id"], s.get("part") or 0))
        if s.get("prop_only"):
            return
        self.spawn(self.update_cards(s, "partial", price))
        cards = {c["user_id"]: c["msg_id"] for c in await self.db.signal_cards(s["id"])}
        langs = await self.db.user_langs()
        side = "BUY" if s["direction"] == 1 else "SELL"
        pct = f"{100 * (s.get('part') or 0):.0f}"
        tp1_pips = abs(s["tp1"] - s["entry"]) / PIP
        lots = await self.db.signal_lots(s["id"])

        def make(u: int):
            lang = norm(langs.get(u))
            text = t(lang, "partial", id=s["id"], side=side, tp1=f"{s['tp1']:.2f}", price=f"{price:.2f}", pct=pct,
                     entry=f"{s['entry']:.2f}", tp=f"{s['tp']:.2f}", pips=f"{tp1_pips:.0f}")
            lot = lots.get(u) or 0
            if lot:
                close = split_volume(lot, s.get("part") or 0)   # как на автоторговле: 0.03 → закрыть 0.02
                if close > 0:
                    text += t(lang, "partial_lot", lot=f"{lot:.2f}", close=f"{close:.2f}", left=f"{lot - close:.2f}",
                              pnl=fmt_usd(money(close, tp1_pips)))
                else:
                    text += t(lang, "partial_min", lot=f"{lot:.2f}")
            return self.bot.send_message(u, text, **reply_to(cards.get(u)))

        await self.chan_text(lambda lang: t(lang, "partial", id=s["id"], side=side, tp1=f"{s['tp1']:.2f}",
                                            price=f"{price:.2f}", pct=pct, entry=f"{s['entry']:.2f}",
                                            tp=f"{s['tp']:.2f}", pips=f"{tp1_pips:.0f}"),
                             await self.chan_reply(s["id"]))
        n = await self.broadcast(list(lots), make)
        log.info("partial for signal #%s sent to %s users", s["id"], n)

    async def autotrade_partial(self, sid: int, fraction: float) -> None:
        if not self.autotrader:
            return
        lock = self.__dict__.setdefault("_partial_lock", asyncio.Lock())   # не делать фиксацию дважды одновременно
        try:
            async with lock:
                results = await self.autotrader.partial_signal(sid, fraction)
        except Exception:  # noqa: BLE001
            log.exception("autotrade partial #%s", sid)
            return
        langs = await self.db.user_langs()
        multi = await self.multi_users()
        for r in results:
            if not r.ok:
                if r.error == "CLOSED":
                    log.warning("autotrade partial #%s for %s (%s): position already closed", sid, r.uid, r.login)
                else:   # админу придёт сообщение; через минуту бот попробует снова (partial_loop)
                    log.error("autotrade partial #%s for %s (%s): %s", sid, r.uid, r.login, r.error)
                continue
            lang = norm(langs.get(r.uid))
            text = (t(lang, "at_partial", id=sid, closed=f"{r.closed:.2f}", left=f"{r.left:.2f}", stop=f"{r.stop:.2f}")
                    if r.closed else t(lang, "at_partial_be", id=sid, stop=f"{r.stop:.2f}"))
            if r.uid in multi:
                text = t(lang, "at_acc_prefix", login=html.escape(r.login)) + text
            await self._send(r.uid, lambda u=r.uid, x=text: self.bot.send_message(u, x))

    async def partial_loop(self, every: float = 60) -> None:
        """Раз в минуту: по сигналам, где часть прибыли уже зафиксирована, доделать фиксацию и безубыток на счетах
        автоторговли, где не получилось с первого раза (нет связи с MetaApi и т. п.)."""
        while True:
            await asyncio.sleep(every)
            if not self.autotrader:
                continue
            try:
                for s in await self.db.open_signals():
                    if s.get("part_at") and s.get("part"):
                        await self.autotrade_partial(s["id"], s["part"])
            except Exception:  # noqa: BLE001
                log.warning("partial loop", exc_info=True)

    async def broadcast_late(self, s: dict, price: float, moved: float) -> None:
        """Цена уже ушла от входа к тейку — тем, кто получил сигнал: не входите, вы опоздали."""
        if s.get("prop_only"):
            return
        langs = await self.db.user_langs()
        side = "BUY" if s["direction"] == 1 else "SELL"
        uids = list(await self.db.signal_lots(s["id"]))

        def make(u: int):
            lang = norm(langs.get(u))
            return self.bot.send_message(u, t(lang, "late", id=s["id"], side=side, entry=f"{s['entry']:.2f}",
                                              price=f"{price:.2f}", pips=f"{moved:.0f}"))

        await self.chan_text(lambda lang: t(lang, "late", id=s["id"], side=side, entry=f"{s['entry']:.2f}",
                                            price=f"{price:.2f}", pips=f"{moved:.0f}"),
                             await self.chan_reply(s["id"]))
        n = await self.broadcast(uids, make)
        log.info("late warning for signal #%s sent to %s users", s["id"], n)

    async def broadcast_day_closed(self, streak: int) -> None:
        """Серия стопов: всем подписчикам — торговый день закрыт, у кого указан капитал — сколько осталось."""
        langs = await self.db.user_langs()
        caps = await self.db.user_capitals()

        def make(u: int):
            lang = norm(langs.get(u))
            text = t(lang, "day_closed", n=streak)
            if caps.get(u):
                text += t(lang, "day_closed_cap", cap=fmt_usd(caps[u]))
            return self.bot.send_message(u, text)

        await self.chan_text(lambda lang: t(lang, "day_closed", n=streak))
        n = await self.broadcast(await self.db.active_user_ids(), make)
        log.info("day closed after %s SL, sent to %s users", streak, n)

    async def broadcast_all(self, make_text) -> None:
        """Всем пользователям, каждому на его языке: make_text(lang) → текст."""
        langs = await self.db.user_langs()
        texts: dict[str, str] = {}

        def make(u: int):
            lang = norm(langs.get(u))
            if lang not in texts:
                texts[lang] = make_text(lang)
            return self.bot.send_message(u, texts[lang])

        await self.chan_text(make_text)
        await self.broadcast(await self.db.all_user_ids(), make)

    async def lang_of(self, uid: int) -> str:
        u = await self.db.get_user(uid)
        return norm(u.get("lang") if u else None)

    async def news_trade_on(self) -> bool:
        """Торговля во время новостей: переключатель админа (/newstrade), по умолчанию NEWS_TRADE из .env."""
        v = await self.db.get_kv("news_trade")
        return config.news_trade if v is None else v == "1"

    def is_admin(self, uid: int) -> bool:
        return uid in config.admin_ids

    async def sub_status(self, uid: int, lang: str) -> str:
        u = await self.db.get_user(uid)
        if not u:
            return t(lang, "st_start")
        if self.db.is_paid(u):
            return t(lang, "st_paid", until=self.fmt_dt(u["paid_until"]))
        if self.db.has_access(u):
            return t(lang, "st_trial", until=self.fmt_dt(u["trial_until"]))
        return t(lang, "st_expired")

    async def send_invoice(self, chat_id: int, lang: str) -> None:
        await self.bot.send_invoice(
            chat_id, title=t(lang, "inv_title", days=config.sub_days),
            description=t(lang, "inv_desc"),
            payload="sub", currency="XTR", provider_token="",
            prices=[LabeledPrice(label=t(lang, "inv_label", days=config.sub_days), amount=config.sub_price_stars)])

    def at_plan(self) -> tuple[int, int, int]:
        """(дней за одну оплату, ⭐ за них, ⭐ за 30 дней) — по цене AUTOTRADE_MONTH_USD в месяц."""
        return autotrade_plan(config.autotrade_month_usd, config.stars_per_usd, self.stars_cap, config.autotrade_days)

    @property
    def at_days(self) -> int:
        return self.at_plan()[0]

    async def set_stars_cap(self, cap: int) -> None:
        self.stars_cap = cap
        if self.autotrader:
            self.autotrader.paid_days = self.at_days
        await self.db.set_kv("stars_cap", str(cap))

    async def send_auto_invoice(self, chat_id: int, lang: str, acc: dict | None = None) -> None:
        """Счёт на оплату автоторговли (отдельно от подписки на сигналы): без acc — подключение нового
        счёта, с acc — продление этого счёта."""
        days, stars, _ = self.at_plan()
        title = (t(lang, "inv_auto_acc_title", login=acc["login"], days=days) if acc
                 else t(lang, "inv_auto_title", days=days))
        try:
            await self.bot.send_invoice(
                chat_id, title=title, description=t(lang, "inv_auto_desc"),
                payload=f"auto:{acc['id']}" if acc else "auto", currency="XTR", provider_token="",
                prices=[LabeledPrice(label=t(lang, "inv_label", days=days), amount=stars)])
        except TelegramBadRequest as e:
            if stars <= STARS_SAFE_MAX or self.stars_cap <= STARS_SAFE_MAX:
                raise
            # Telegram не принял такую сумму ⭐ в одном счёте — дальше продаём меньше дней за раз (та же цена в месяц)
            log.warning("invoice of %s XTR rejected (%s), stars cap -> %s", stars, e, STARS_SAFE_MAX)
            await self.set_stars_cap(STARS_SAFE_MAX)
            await self.send_auto_invoice(chat_id, lang, acc)

    async def can_connect(self, uid: int) -> bool:
        """Можно ли подключить новый счёт: каждый счёт оплачивается отдельно (админам — бесплатно)."""
        return self.is_admin(uid) or await self.db.credits(uid) > 0

    async def ask_payment(self, chat_id: int, uid: int, lang: str, intent: str) -> None:
        """Счёт на оплату нового счёта; после оплаты продолжим intent: real — обычный счёт, prop — FundedNext."""
        await self.db.set_kv(f"pay_intent:{uid}", intent)
        await self.bot.send_message(chat_id, t(lang, "at_pay") + t(lang, "at_pay_each") + "\n\n" + self.price_line(lang))
        await self.send_auto_invoice(chat_id, lang)

    def price_line(self, lang: str) -> str:
        days, stars, month_stars = self.at_plan()
        text = t(lang, "at_price", usd=fmt_money(config.autotrade_month_usd), month_stars=fmt_money(month_stars))
        if days < 30:   # в один счёт Telegram месяц не помещается — платят частями
            text += t(lang, "at_price_part", stars=fmt_money(stars), days=days,
                      usd=fmt_money(config.autotrade_month_usd * days / 30))
        return text

    async def show_risks(self, chat_id: int, lang: str) -> None:
        demo = (t(lang, "at_demo_note") if config.autotrade_demo_only else
                t(lang, "at_real_note") if config.autotrade_real_only else "")
        await self.bot.send_message(
            chat_id, t(lang, "at_risks", risk=f"{config.autotrade_risk_pct:g}",
                       max_lot=f"{config.autotrade_max_lot:g}", demo=demo),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [_btn(t(lang, "btn_agree"), "at:agree")], [_btn(t(lang, "btn_cancel"), "at:cancel")]]))

    async def send_hello(self, chat_id: int, uid: int, first_name: str | None, lang: str, new: bool) -> None:
        hello = t(lang, "hello", name=html.escape(first_name or t(lang, "trader")))
        if new:
            hello += t(lang, "trial_new", days=config.trial_days)
        else:
            hello += await self.sub_status(uid, lang)
        await self.bot.send_message(chat_id, hello, reply_markup=menu(lang))

    async def ask_capital(self, chat_id: int, lang: str, state: FSMContext, onboard: bool = False,
                          new_user: bool = False) -> None:
        await state.set_state(CapitalStates.waiting)
        await state.update_data(onboard=onboard, new_user=new_user)
        await self.bot.send_message(chat_id, t(lang, "ask_capital"), reply_markup=capital_kb(lang))

    async def capital_done(self, chat_id: int, user, state: FSMContext, capital: float) -> None:
        """Сохраняет капитал (0 — пропустил) и продолжает: приветствие для новых или подтверждение."""
        data = await state.get_data()
        await state.clear()
        await self.db.set_capital(user.id, capital)
        lang = await self.lang_of(user.id)
        text = (t(lang, "cap_set", cap=fmt_usd(capital), lot=f"{lot_plan(capital)['lot']:.2f}") if capital
                else t(lang, "cap_skipped"))
        if data.get("onboard"):  # новый пользователь: дальше приветствие с меню и вопрос про автоторговлю
            await self.bot.send_message(chat_id, text)
            await self.send_hello(chat_id, user.id, user.first_name, lang, bool(data.get("new_user")))
            await self.ask_autotrade(chat_id, user.id, lang)
        else:
            await self.bot.send_message(chat_id, text, reply_markup=menu(lang))

    # ── автоторговля ─────────────────────────────────────────────────────────
    async def market_account(self) -> dict | None:
        """Счёт админа, с которого берём свечи и цену (кэш на минуту)."""
        import time
        at, src = self._market_src
        if time.monotonic() - at < 60:
            return src
        accs = [a for a in await self.db.trade_accounts() if a["user_id"] in config.admin_ids]
        # счёт админа только для цен (инвесторский пароль) или реальный надёжнее демо: не истекает; иначе — первый
        real = [a for a in accs if a.get("read_only") or (not a.get("demo", 1) and not a.get("prop_plan"))]
        src = (real or accs or [None])[0]
        self._market_src = (time.monotonic(), src)
        return src

    def spawn(self, coro) -> None:
        """Автоторговля в фоне, чтобы не задерживать рассылку сигналов."""
        if not self.autotrader:
            coro.close()
            return
        tasks = self.__dict__.setdefault("_tasks", set())
        task = asyncio.create_task(coro)
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def autotrade_open(self, s: NewSignal) -> None:
        if not self.autotrader:
            return
        sl_d, tp_d = sl_tp_dist(s.entry, s.sl, s.tp, s.sl_pips, s.tp_pips)
        try:
            results = await self.autotrader.open_signal(s.id, s.direction, sl_d, tp_d,
                                                        strong=getattr(s, "strong", False),
                                                        prop_only=getattr(s, "prop_only", False),
                                                        size=getattr(s, "size", 1.0))
        except Exception:  # noqa: BLE001
            log.exception("autotrade open #%s", s.id)
            return
        langs = await self.db.user_langs()
        multi = await self.multi_users()
        side = "🟢 BUY" if s.direction == 1 else "🔴 SELL"
        for r in results:
            lang = norm(langs.get(r.uid))
            if r.ok:
                text = t(lang, "at_opened", id=s.id, side=side, symbol=html.escape(r.symbol), lot=f"{r.volume:.2f}",
                         price=f"{r.price:.2f}", sl=f"{r.sl:.2f}", tp=f"{r.tp:.2f}")
            elif r.error == "DUPLICATE":
                continue
            else:
                text = t(lang, "at_open_fail", id=s.id, error=trade_error_text(lang, r.error))
            if r.uid in multi:
                text = t(lang, "at_acc_prefix", login=html.escape(r.login)) + text
            await self._send(r.uid, lambda u=r.uid, x=text: self.bot.send_message(u, x))
        log.info("autotrade #%s: %s opened, %s failed", s.id, sum(r.ok for r in results),
                 sum(not r.ok for r in results))
        failed = [r for r in results if not r.ok and r.error not in ("DUPLICATE", "NO_MONEY", "SPREAD", "DAY_LOSS", "DAY_SIDE")]
        if failed:   # админу — на каких счетах сделка не открылась и почему
            lines = [f"• {html.escape(r.login or str(r.uid))} (id {r.uid}): {html.escape(r.error)}" for r in failed[:20]]
            await self.notify_admins(f"⚠️ <b>Сигнал #{s.id}: сделка не открылась на {len(failed)} счетах</b>\n"
                                     + "\n".join(lines))

    async def multi_users(self) -> set[int]:
        """Подписчики с несколькими счетами — в их сообщениях указываем номер счёта."""
        counts: dict[int, int] = {}
        for a in await self.db.trade_accounts():
            counts[a["user_id"]] = counts.get(a["user_id"], 0) + 1
        return {u for u, n in counts.items() if n > 1}

    async def autotrade_close(self, sid: int, uids: set[int] | None = None, skip_prop: bool = False) -> None:
        if not self.autotrader:
            return
        try:
            results = await self.autotrader.close_signal(sid, uids, skip_prop=skip_prop)
        except Exception:  # noqa: BLE001
            log.exception("autotrade close #%s", sid)
            return
        langs = await self.db.user_langs()
        multi = await self.multi_users()
        for r in results:
            if not r.ok:
                log.warning("autotrade close #%s for %s: %s", sid, r.uid, r.error)
                continue
            lang = norm(langs.get(r.uid))
            profit = ""
            if r.profit is not None:
                sign = "+" if r.profit >= 0 else "−"
                profit = t(lang, "at_closed_profit", pnl=f"{sign}{abs(r.profit):,.2f}".replace(",", " "),
                           currency=html.escape(r.currency))
            text = t(lang, "at_closed", id=sid, profit=profit)
            if r.uid in multi:
                text = t(lang, "at_acc_prefix", login=html.escape(r.login)) + text
            await self._send(r.uid, lambda u=r.uid, x=text: self.bot.send_message(u, x))

    async def ask_autotrade(self, chat_id: int, uid: int, lang: str) -> None:
        """Один раз спрашиваем подписчика, подключить ли бота к его счёту."""
        if not self.autotrader:
            return
        u = await self.db.get_user(uid)
        if not u or u.get("autotrade_asked") or await self.db.get_trade_account(uid):
            return
        await self.db.set_autotrade_asked(uid)
        text = t(lang, "at_ask") + ("" if await self.can_connect(uid) else "\n\n" + self.price_line(lang))
        await self.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn(t(lang, "btn_yes_connect"), "at:yes"), _btn(t(lang, "btn_no_thanks"), "at:no")],
            [_btn(t(lang, "btn_prop"), "at:prop")]]))

    async def autotrade_menu(self, chat_id: int, uid: int, lang: str) -> None:
        if not self.autotrader:
            await self.bot.send_message(chat_id, t(lang, "at_unavailable"))
            return
        accs = [a for a in await self.autotrader.statuses(uid) if a]
        connect_rows = [[_btn(t(lang, "btn_connect"), "at:yes")], [_btn(t(lang, "btn_prop"), "at:prop")]]
        if not accs:
            price = "" if self.is_admin(uid) else "\n\n" + self.price_line(lang) + t(lang, "at_pay_each")
            await self.bot.send_message(chat_id, t(lang, "at_none") + price,
                                        reply_markup=InlineKeyboardMarkup(inline_keyboard=connect_rows))
            return
        off = await self.db.get_kv("autotrade_off") == "1"
        blocks, rows = [], []
        for acc in accs:
            state = t(lang, "at_global_off") if off else t(lang, "at_on" if acc["enabled"] else "at_paused")
            bal = acc.get("balance")
            balance = f"{bal:,.2f} {acc.get('currency') or ''}".replace(",", " ") if bal is not None else "—"
            block = t(lang, "at_acc", broker=html.escape(acc.get("broker") or "—"), login=acc["login"],
                      server=html.escape(acc["server"]),
                      kind=t(lang, "at_kind_demo" if acc["demo"] else "at_kind_real"), balance=balance, state=state)
            if acc.get("prop_plan") in pr.PLANS:
                block += self.prop_status(acc, lang)
            else:
                block += t(lang, "at_acc_risk", risk=f"{config.autotrade_risk_pct:g}",
                           max_lot=f"{config.autotrade_max_lot:g}")
            blocks.append(block + self.paid_line(uid, acc, lang))
            login, aid = acc["login"], acc["id"]
            row = [_btn(t(lang, "btn_pause_acc", login=login), f"at:pause:{aid}") if acc["enabled"]
                   else _btn(t(lang, "btn_resume_acc", login=login), f"at:resume:{aid}")]
            if not self.is_admin(uid):
                row.append(_btn(t(lang, "btn_extend_acc", login=login), f"at:pay:{aid}"))
            rows += [row, [_btn(t(lang, "btn_disc_acc", login=login), f"at:disc:{aid}")]]
        text = t(lang, "at_header", n=len(accs)) + "\n\n" + "\n\n".join(blocks)
        if not self.is_admin(uid):
            text += "\n\n" + self.price_line(lang) + t(lang, "at_pay_each")
        more = [[_btn(t(lang, "btn_connect_more"), "at:yes")], [_btn(t(lang, "btn_prop"), "at:prop")]]
        await self.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows + more))

    def paid_line(self, uid: int, acc: dict, lang: str) -> str:
        """Строка «Оплачено до …» для счёта в меню автоторговли."""
        if self.is_admin(uid):
            return t(lang, "at_until_admin")
        until = self.db.paid_until(acc)
        return t(lang, "at_until", until=self.fmt_dt(until)) if until and until > now() else ""

    # ── проп-счета FundedNext ──────────────────────────────────────────────
    @staticmethod
    def stage_name(lang: str, stage: str | None) -> str:
        return t(lang, f"prop_stage_{stage}") if stage in ("phase1", "phase2", "funded") else "—"

    def prop_status(self, acc: dict, lang: str) -> str:
        """Строки о лимитах FundedNext в меню автоторговли (пусто для обычного счёта)."""
        if acc.get("prop_plan") not in pr.PLANS:
            return ""
        plan = pr.PLANS[acc["prop_plan"]]
        size = float(acc["prop_size"])
        equity = acc.get("equity")
        lim = pr.limits(acc, float(equity if equity is not None else size), config.prop_risk_cap)
        goal = pr.target_balance(acc)
        halt = acc.get("prop_halt") or ""
        return t(lang, "prop_status", plan=plan.name, stage=self.stage_name(lang, acc.get("prop_stage")),
                 size=f"{size:,.0f}".replace(",", " "), day_loss=usd(lim.day_loss),
                 day_limit=usd(lim.day_limit), day_left=usd(max(0.0, lim.day_limit - lim.day_loss)),
                 floor=usd(lim.total_floor), days=f"{int(acc.get('prop_days') or 0)}/{plan.min_days}"
                 if plan.min_days and goal else str(int(acc.get("prop_days") or 0)),
                 target=t(lang, "prop_status_target", goal=usd(goal)) if goal else "",
                 halt=t(lang, f"prop_status_halt_{halt}") if halt in ("daily", "total", "loss") else "") \
            + self.prop_forecast(acc, lang)

    def prop_forecast(self, acc: dict, lang: str) -> str:
        """Полоска «сколько цели этапа набрано» и сколько дней обычно занимает этап (по симуляции на истории)."""
        bal = acc.get("balance")
        goal = pr.target_balance(acc)
        if goal is None or bal is None:
            return ""
        frac = pr.progress(acc, float(bal)) or 0.0
        size = float(acc["prop_size"])
        text = t(lang, "prop_progress", bar=pr.progress_bar(max(frac, 0.0)), done=f"{max(frac, 0.0) * 100:.0f}",
                 profit=f"{(float(bal) / size - 1) * 100:+.2f}",
                 target=f"{pr.PLANS[acc['prop_plan']].targets.get(acc.get('prop_stage'), 0):g}",
                 left=usd(max(0.0, goal - float(bal))))
        days = pr.TYPICAL_DAYS.get((acc["prop_plan"], acc.get("prop_stage")))
        if days:
            text += t(lang, "prop_typical", days=days)
        return text

    async def prop_intro(self, chat_id: int, lang: str) -> None:
        discount = (t(lang, "prop_discount", code=html.escape(config.fundednext_code),
                      pct=html.escape(config.fundednext_discount)) if config.fundednext_code else "")
        rows = []
        if config.fundednext_url:
            rows.append([InlineKeyboardButton(text=t(lang, "btn_prop_register"), url=config.fundednext_url)])
        rows += [[_btn(t(lang, "btn_prop_have"), "at:pplan")], [_btn(t(lang, "btn_cancel"), "at:cancel")]]
        await self.bot.send_message(chat_id, t(lang, "prop_intro", discount=discount),
                                    reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
                                    disable_web_page_preview=True)

    async def prop_plan_ask(self, chat_id: int, lang: str) -> None:
        await self.bot.send_message(chat_id, t(lang, "prop_plan_ask"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            *[[_btn(p.name, f"at:pp:{k}")] for k, p in pr.PLANS.items()],
            [_btn(t(lang, "btn_cancel"), "at:cancel")]]))

    async def prop_ask_size(self, message, lang: str, plan_key: str) -> None:
        sizes = pr.PLANS[plan_key].sizes
        btns = [_btn(f"${x // 1000}K", f"at:pz:{x}") for x in sizes]
        await message.answer(t(lang, "prop_size_ask"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            btns[i:i + 3] for i in range(0, len(btns), 3)] + [[_btn(t(lang, "btn_cancel"), "at:cancel")]]))

    async def prop_rules(self, chat_id: int, lang: str, plan_key: str, stage: str, size: float) -> None:
        plan = pr.PLANS[plan_key]
        cap = config.prop_risk_cap
        risk = min(config.prop_risk_pct, config.prop_max_trade_pct)
        n = lambda x: f"{x:,.0f}".replace(",", " ")  # noqa: E731
        acc = {"prop_plan": plan_key, "prop_size": size, "prop_day_balance": size, "prop_peak": size}
        lim = pr.limits(acc, size, cap)
        if plan.trailing:
            total = t(lang, "prop_total_trailing", pct=f"{plan.total_pct:g}")
        else:
            total = t(lang, "prop_total_static", pct=f"{plan.total_pct:g}", floor=n(size * (1 - plan.total_pct / 100)))
        pct = plan.targets.get(stage)
        target = (t(lang, "prop_target", pct=f"{pct:g}", goal=n(size * (1 + pct / 100))) if pct
                  else t(lang, "prop_target_none"))
        text = t(lang, "prop_rules", plan=plan.name, stage=self.stage_name(lang, stage), size=n(size),
                 daily=f"{plan.daily_pct:g}%" if plan.daily_pct else t(lang, "prop_none"), total=total,
                 target=target, days=str(plan.min_days) if pct and plan.min_days else t(lang, "prop_none"),
                 risk=f"{risk:g}", risk_usd=n(size * risk / 100),
                 strong=f"{min(config.prop_strong_risk_pct, config.prop_max_trade_pct):g}",
                 strong_usd=n(size * min(config.prop_strong_risk_pct, config.prop_max_trade_pct) / 100), max_trade=f"{config.prop_max_trade_pct:g}",
                 max_trade_usd=n(size * config.prop_max_trade_pct / 100),
                 max_open=f"{pr.MAX_OPEN_PCT:g}", max_open_usd=n(size * pr.MAX_OPEN_PCT / 100),
                 two=f"{2 * risk:g}", two_usd=n(size * 2 * risk / 100),
                 day_cap=f"{lim.day_limit / size * 100:g}", day_cap_usd=n(lim.day_limit),
                 guard_usd=n(size * config.prop_guard_pct / 100),
                 reset=f"{pr.reset_time(config.display_tz, now(), config.prop_day_tz)} ({config.display_tz})")
        if config.prop_day_losses > 0:
            text += "\n\n" + t(lang, "prop_rules_loss", n=config.prop_day_losses)
        if config.prop_dd_pct > 0:
            low = min(config.prop_risk_pct, config.prop_max_trade_pct) * config.prop_dd_mult
            text += "\n" + t(lang, "prop_rules_dd", dd=f"{config.prop_dd_pct:g}", dd_usd=n(size * config.prop_dd_pct / 100),
                              risk=f"{risk:g}", low=f"{low:g}")
        await self.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn(t(lang, "btn_agree"), "at:pagree")], [_btn(t(lang, "btn_cancel"), "at:cancel")]]))

    async def prop_events(self, events: list[dict]) -> None:
        multi = await self.multi_users() if events else set()
        for e in events:
            uid = e["uid"]
            lang = await self.lang_of(uid)
            markup = None
            if e["kind"] == "new_day":
                text = t(lang, "prop_new_day")
            elif e["kind"] == "loss_stop":
                text = t(lang, "prop_loss_stop")
            elif e["kind"] == "halt":
                text = t(lang, "prop_halt_daily" if e["limit"] == "daily" else "prop_halt_total",
                         equity=usd(e["equity"]), floor=usd(e["floor"]), closed=e["closed"])
            elif e["kind"] == "milestone":
                a = e["acc"]
                size = float(a["prop_size"])
                goal = pr.target_balance(a) or size
                text = t(lang, "prop_milestone", pct=e["pct"], bar=pr.progress_bar(min(e["frac"], 1.0)),
                         profit=f"{(e['balance'] / size - 1) * 100:+.2f}",
                         target=f"{pr.PLANS[a['prop_plan']].targets.get(a.get('prop_stage'), 0):g}",
                         left=usd(max(0.0, goal - e["balance"])))
            elif e["kind"] == "passed":
                a = e["acc"]
                size = float(a["prop_size"])
                bal = float(a["balance"])
                nxt = self.stage_name(lang, e.get("next"))
                text = t(lang, "prop_passed", stage=self.stage_name(lang, a.get("prop_stage")),
                         plan=pr.PLANS[a["prop_plan"]].name, size=f"{size:,.0f}".replace(",", " "),
                         balance=usd(bal), profit=f"{(bal / size - 1) * 100:.2f}",
                         target=f"{pr.PLANS[a['prop_plan']].targets.get(a.get('prop_stage'), 0):g}",
                         days=int(a.get("prop_days") or 0),
                         worst=f"{float(a.get('prop_worst_day') or 0) / size * 100:.2f}",
                         dd=f"{max(0.0, size - float(a.get('prop_min_equity') or size)) / size * 100:.2f}",
                         next=nxt)
                if e.get("next"):
                    markup = InlineKeyboardMarkup(inline_keyboard=[[_btn(t(lang, "btn_prop_next", next=nxt),
                                                                         "at:pnext")]])
                log.info("prop: user %s passed %s %s", uid, a["prop_plan"], a.get("prop_stage"))
            else:
                continue
            if uid in multi or e.get("kind") == "passed":
                text = t(lang, "at_acc_prefix", login=html.escape(e.get("login") or "")) + text
            await self._send(uid, lambda u=uid, x=text, mk=markup: self.bot.send_message(u, x, reply_markup=mk))

    async def has_prop(self) -> bool:
        """Есть ли включённые проп-счета (для сигналов только для проп-счетов)."""
        if not self.autotrader:
            return False
        accs = await self.db.trade_accounts(enabled_only=True, exempt=frozenset(config.admin_ids))
        return any(a.get("prop_plan") in pr.PLANS and not a.get("prop_halt") for a in accs)

    # ── живая карточка сигнала ────────────────────────────────────────────
    async def update_cards(self, s: dict, status: str | None = None, price: float | None = None) -> int:
        """Обновляет подпись сигнала у каждого, кто его получил: ход сделки, фиксация части, итог.
        Кнопки «Принять / Отклонить» остаются, пока подписчик их не нажал и сделка открыта."""
        if not config.live_card or s.get("prop_only"):
            return 0
        closed = status in ("tp", "sl", "be", "rev", "news")
        langs = await self.db.user_langs()
        n = 0
        for c in await self.db.signal_cards(s["id"]):
            if not c.get("caption"):
                continue
            lang = norm(langs.get(c["user_id"]))
            block = card_status(lang, s, status, price, config.display_tz)
            caption = c["caption"] + ("\n\n" + block if block else "")
            kb = None if closed or c.get("decided") else decision_kb(lang, s["id"])
            try:
                await self.bot.edit_message_caption(chat_id=c["user_id"], message_id=c["msg_id"], caption=caption,
                                                    reply_markup=kb)
                n += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except Exception as e:  # noqa: BLE001 — сообщение удалено, подпись не изменилась и т.п.
                log.debug("card #%s for %s: %s", s["id"], c["user_id"], e)
            await asyncio.sleep(0.04)
        await self.chan_update_card(s, status, price)
        return n

    async def chan_update_card(self, s: dict, status: str | None, price: float | None) -> None:
        """Тот же ход сделки — в посте сигнала в канале."""
        card = await self.chan_card(s["id"])
        cid = await self.chan_target()
        if not card or cid is None:
            return
        block = card_status(await self.chan_lang(), s, status, price, config.display_tz)
        try:
            await self.bot.edit_message_caption(chat_id=cid, message_id=card["m"],
                                                caption=card["c"] + ("\n\n" + block if block else ""))
        except Exception as e:  # noqa: BLE001
            log.debug("channel card #%s: %s", s["id"], e)

    async def live_card_tick(self) -> None:
        """Ход открытых сделок в карточках: обновляем, когда он изменился хотя бы на 0.2R."""
        if not config.live_card or not market_open(pd.Timestamp.now(tz="UTC")):
            return
        opened = [x for x in await self.db.open_signals() if not x.get("prop_only")]
        if not opened:
            return
        price = await self.engine.fresh_price()
        if not price:
            return
        for s in opened:
            dist = abs(s["entry"] - s["sl"]) or 1e-9
            r = s["direction"] * (price - s["entry"]) / dist
            if abs(r - self._card_r.get(s["id"], 0.0)) < 0.2:
                continue
            self._card_r[s["id"]] = r
            await self.update_cards(s, None, price)

    async def live_card_loop(self) -> None:
        while True:
            await asyncio.sleep(max(1, config.live_card_min) * 60)
            try:
                await self.live_card_tick()
            except Exception:  # noqa: BLE001
                log.exception("live card")

    # ── сверка счетов ─────────────────────────────────────────────────────
    async def reconcile_events(self, events: list[dict]) -> None:
        """Сообщения подписчикам и админу о том, что исправила сверка счетов."""
        if not events:
            return
        multi = await self.multi_users()
        admin_lines = []
        for e in events:
            uid = e["uid"]
            lang = await self.lang_of(uid)
            kind = e["kind"]
            if kind == "sl_fixed":
                text = t(lang, "rc_sl_fixed", id=e["sid"], stop=f"{e['stop']:.2f}")
            elif kind == "zombie":
                profit = ""
                if e.get("profit") is not None:
                    sign = "+" if e["profit"] >= 0 else "−"
                    profit = t(lang, "at_closed_profit", pnl=f"{sign}{abs(e['profit']):,.2f}".replace(",", " "),
                               currency=html.escape(e.get("currency") or "USD"))
                text = t(lang, "rc_zombie", id=e["sid"], profit=profit)
            elif kind == "reopened":
                r = e["result"]
                text = t(lang, "rc_reopened", id=e["sid"], lot=f"{r.volume:.2f}", price=f"{r.price:.2f}",
                         sl=f"{r.sl:.2f}", tp=f"{r.tp:.2f}")
            else:   # reopen_failed — подписчику уже писали, что сделка не открылась; только админу
                admin_lines.append(f"• #{e['sid']} {html.escape(e.get('login') or '')} (id {uid}): "
                                   f"{html.escape(e.get('error') or '')}")
                continue
            admin_lines.append(f"• #{e['sid']} {html.escape(e.get('login') or '')} (id {uid}): {kind}")
            if uid in multi:
                text = t(lang, "at_acc_prefix", login=html.escape(e.get("login") or "")) + text
            await self._send(uid, lambda u=uid, x=text: self.bot.send_message(u, x))
        if admin_lines:
            await self.notify_admins("🔎 <b>Сверка счетов</b>\n" + "\n".join(admin_lines[:30]),
                                     disable_notification=True)

    async def reconcile_loop(self) -> None:
        """Раз в RECONCILE_SEC секунд: стоп на месте, нет сделок по закрытым сигналам, неоткрывшиеся — повтор."""
        if not self.autotrader or config.reconcile_sec <= 0:
            return
        while True:
            await asyncio.sleep(config.reconcile_sec)
            try:
                if market_open(pd.Timestamp.now(tz="UTC")):
                    price = await self.engine.fresh_price()
                    await self.reconcile_events(await self.autotrader.reconcile(price))
            except Exception:  # noqa: BLE001
                log.exception("reconcile")

    async def prop_loop(self) -> None:
        """Каждые 20 с: средства проп-счетов против лимитов FundedNext, торговые дни, прохождение этапа."""
        if not self.autotrader:
            return
        while True:
            try:
                await self.prop_events(await self.autotrader.prop_check())
            except Exception:  # noqa: BLE001
                log.exception("prop check")
            await asyncio.sleep(20)

    async def show_servers(self, chat_id: int, lang: str, state: FSMContext, query: str) -> None:
        data = await state.get_data()
        version = 4 if data.get("platform") == "mt4" else 5
        await self.bot.send_message(chat_id, t(lang, "at_searching", q=html.escape(query)))
        try:
            servers = demo_servers(await self.autotrader.api.search_servers(version, query),
                                   config.autotrade_demo_only)[:24]
        except Exception as e:  # noqa: BLE001
            log.warning("server search %r: %s", query, e)
            servers = []
        if not servers:
            await state.set_state(AutoStates.broker_name)
            await self.bot.send_message(chat_id, t(lang, "at_no_servers", q=html.escape(query)))
            return
        await state.set_state(None)
        await state.update_data(servers=servers)
        hint = "prop_servers" if data.get("prop_plan") else "at_servers"
        await self.bot.send_message(chat_id, t(lang, hint), reply_markup=servers_kb(lang, servers))

    async def ask_login(self, chat_id: int, lang: str, state: FSMContext, server: str) -> None:
        await state.update_data(server=server)
        await state.set_state(AutoStates.login)
        await self.bot.send_message(chat_id, t(lang, "at_login", server=html.escape(server)))

    async def run_connect(self, chat_id: int, uid: int, lang: str, platform: str, server: str, login: str,
                          password: str, prop: dict | None = None, paid_until: str | None = None) -> None:
        """Подключает ещё один счёт. Новый счёт забирает одно оплаченное подключение и оплачен на
        AUTOTRADE_DAYS дней; тот же счёт заново — сохраняет свою оплату; счёт следующего этапа FundedNext —
        дни прошлого этапа (paid_until)."""
        try:
            same = any(a["login"] == login and a["server"] == server for a in await self.db.user_accounts(uid))
            charge = not (paid_until or same or self.is_admin(uid))   # новый счёт — одно оплаченное подключение
            if charge and not await self.db.use_credit(uid):
                raise MetaApiError("not paid", "NOT_PAID")
            try:
                info = await self.autotrader.connect(uid, platform, server, login, password, prop=prop,
                                                     paid_until=self.db.paid_until({"paid_until": paid_until}))
            except Exception:
                if charge:
                    await self.db.add_credit(uid)   # не подключился — оплаченное подключение возвращаем
                raise
            bal = info.get("balance")
            balance = f"{bal:,.2f} {info.get('currency') or ''}".replace(",", " ") if bal is not None else "—"
            if prop:
                await self.db.set_kv(f"prop_next:{uid}", "")
                text = t(lang, "prop_connected", plan=pr.PLANS[prop["plan"]].name,
                         stage=self.stage_name(lang, prop["stage"]),
                         size=f"{float(prop['size']):,.0f}".replace(",", " "), login=login,
                         server=html.escape(server), balance=balance)
            else:
                text = t(lang, "at_connected", broker=html.escape(info.get("broker") or "—"), login=login,
                         server=html.escape(server), balance=balance, symbol=html.escape(info["symbol"]),
                         risk=f"{config.autotrade_risk_pct:g}")
                if info.get("price_only"):
                    text = t(lang, "at_price_only", broker=html.escape(info.get("broker") or "—"), login=login,
                             server=html.escape(server), balance=balance, symbol=html.escape(info["symbol"]))
            log.info("autotrade: user %s connected %s@%s", uid, login, server)
        except Exception as e:  # noqa: BLE001
            log.warning("autotrade connect for %s (%s@%s) failed: %s %s %s", uid, login, server,
                        type(e).__name__, getattr(e, "code", ""), e)
            text = connect_error_text(lang, e, server)
        finally:
            self._connecting.discard(uid)
        await self._send(uid, lambda: self.bot.send_message(chat_id, text, reply_markup=menu(lang)))

    # ── handlers ─────────────────────────────────────────────────────────────
    def _register(self) -> None:
        r = self.router

        @r.message(CommandStart())
        async def start(m: Message, state: FSMContext):
            new = await self.db.add_user(m.from_user.id, m.from_user.username, m.from_user.first_name,
                                         config.trial_days)
            u = await self.db.get_user(m.from_user.id)
            if not u.get("lang"):  # сначала просим выбрать язык
                await state.update_data(new_user=new)
                await m.answer(CHOOSE, reply_markup=LANG_KB)
                return
            if u.get("capital") is None:  # потом капитал (один раз; 0 — пропустил)
                await self.ask_capital(m.chat.id, norm(u["lang"]), state, onboard=True, new_user=new)
                return
            await self.send_hello(m.chat.id, m.from_user.id, m.from_user.first_name, norm(u["lang"]), new)
            await self.ask_autotrade(m.chat.id, m.from_user.id, norm(u["lang"]))

        @r.message(Command("language", "lang"))
        async def language(m: Message):
            await m.answer(CHOOSE, reply_markup=LANG_KB)

        @r.callback_query(F.data.startswith("lang:"))
        async def choose_lang(c: CallbackQuery, state: FSMContext):
            code = c.data.split(":", 1)[1]
            if code == "menu":
                await c.message.answer(CHOOSE, reply_markup=LANG_KB)
                await c.answer()
                return
            lang = norm(code)
            uid = c.from_user.id
            new = await self.db.add_user(uid, c.from_user.username, c.from_user.first_name, config.trial_days)
            first = new or not (await self.db.get_user(uid)).get("lang")
            await self.db.set_lang(uid, lang)
            await c.answer(t(lang, "lang_set"))
            try:
                await c.message.delete()
            except Exception:  # noqa: BLE001 — старое сообщение могло уже не удаляться
                pass
            if first:
                data = await state.get_data()
                new_user = new or bool(data.get("new_user"))
                if (await self.db.get_user(uid)).get("capital") is None:
                    await self.ask_capital(c.message.chat.id, lang, state, onboard=True, new_user=new_user)
                else:
                    await state.update_data(new_user=False)
                    await self.send_hello(c.message.chat.id, uid, c.from_user.first_name, lang, new_user)
            else:
                await c.message.answer(t(lang, "lang_set"), reply_markup=menu(lang))

        @r.message(Command("capital"))
        async def capital_cmd(m: Message, state: FSMContext):
            await self.ask_capital(m.chat.id, await self.lang_of(m.from_user.id), state)

        @r.callback_query(F.data.startswith("cap:"))
        async def capital_cb(c: CallbackQuery, state: FSMContext):
            v = c.data.split(":", 1)[1]
            await c.answer()
            if v == "menu":
                await self.ask_capital(c.message.chat.id, await self.lang_of(c.from_user.id), state)
                return
            try:
                await c.message.edit_reply_markup(reply_markup=None)
            except Exception:  # noqa: BLE001
                pass
            await self.capital_done(c.message.chat.id, c.from_user, state, 0 if v == "skip" else float(v))

        @r.message(CapitalStates.waiting, F.text.func(lambda s: parse_capital(s) is not None))
        async def capital_typed(m: Message, state: FSMContext):
            await self.capital_done(m.chat.id, m.from_user, state, parse_capital(m.text))

        @r.message(F.text.in_(variants("btn_signal")))
        @r.message(Command("signal"))
        async def signal(m: Message):
            u = await self.db.get_user(m.from_user.id)
            if not u:
                await self.db.add_user(m.from_user.id, m.from_user.username, m.from_user.first_name,
                                       config.trial_days)
                u = await self.db.get_user(m.from_user.id)
            lang = norm(u.get("lang"))
            if not self.db.has_access(u):
                await m.answer(t(lang, "sig_expired"))
                await self.send_invoice(m.chat.id, lang)
                return
            await m.answer(t(lang, "analyzing"))
            try:
                text = await self.engine.expected(lang)
            except Exception:  # noqa: BLE001
                log.exception("expected setup")
                text = t(lang, "quotes_fail")
            now_price = await self.engine.fresh_price()   # цена на момент ответа, а не прошлой проверки
            price = t(lang, "price_now", price=f"{now_price:.2f}") if now_price else ""
            opened = [x for x in await self.db.open_signals() if not x.get("prop_only")]
            active = ""
            if opened:
                s = opened[-1]
                active = t(lang, "open_signal", id=s["id"], side="BUY" if s["direction"] == 1 else "SELL",
                           entry=f"{s['entry']:.2f}", sl=f"{s['sl']:.2f}", tp=f"{s['tp']:.2f}")
            await m.answer(f"{t(lang, 'analysis_head')}\n\n{text}{price}{active}")

        @r.callback_query(F.data.startswith("sig:"))
        async def signal_decision(c: CallbackQuery):
            _, choice, sid = c.data.split(":")
            sid, uid = int(sid), c.from_user.id
            lang = await self.lang_of(uid)
            sig = await self.db.get_signal(sid)
            if not sig or sig["status"] != "open":
                await c.answer(t(lang, "sig_already_closed"), show_alert=True)
                return
            u = await self.db.get_user(uid) or {}
            lot = lot_plan(u["capital"])["lot"] if u.get("capital") else 0
            await self.db.set_decision(sid, uid, choice == "dec", lot)
            if choice == "dec":  # отклонил — закрываем сделку на его счёте, если бот её открыл
                self.spawn(self.autotrade_close(sid, {uid}))
            await c.answer()
            await c.message.answer(t(lang, "declined" if choice == "dec" else "accepted", id=sid))
            try:
                await c.message.edit_reply_markup(reply_markup=None)  # кнопки исчезают после выбора
            except Exception:  # noqa: BLE001 — кнопки уже убраны
                pass

        @r.message(F.text.in_(variants("btn_stats")))
        @r.message(Command("stats"))
        async def statistics(m: Message):
            lang = await self.lang_of(m.from_user.id)
            rows = await self.db.last_signals(1000)
            if rows:  # сначала картинка-отчёт, потом подробности текстом
                try:
                    png = await asyncio.to_thread(render_stats, rows, lang, config.display_tz, PIP)
                    await m.answer_photo(BufferedInputFile(png, "stats.png"))
                except Exception:  # noqa: BLE001
                    log.exception("stats chart")
            await self.send_long(m.chat.id, stats_text(lang, rows, config.display_tz))
            if config.myfxbook_url:   # независимая проверенная статистика реального счёта
                await m.answer(t(lang, "myfxbook_text"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=t(lang, "btn_myfxbook"), url=config.myfxbook_url)]]),
                    disable_web_page_preview=True)

        @r.message(F.text.in_(variants("btn_fund")))
        @r.message(Command("news"))
        async def fundamental(m: Message):
            lang = await self.lang_of(m.from_user.id)
            await m.answer(t(lang, "news_wait"))
            try:
                await self.send_long(m.chat.id, await self.news.digest(lang, await self.engine.market_text()))
            except Exception:  # noqa: BLE001
                log.exception("news")
                await m.answer(t(lang, "news_fail"))

        @r.message(F.text.in_(variants("btn_cal")))
        @r.message(Command("calendar"))
        async def calendar(m: Message):
            lang = await self.lang_of(m.from_user.id)
            await self.send_long(m.chat.id, await econ_calendar.render(self.db, config.display_tz, lang=lang))

        @r.message(F.text.in_(variants("btn_sub")))
        @r.message(Command("subscribe"))
        async def subscribe(m: Message):
            lang = await self.lang_of(m.from_user.id)
            await m.answer(f"{await self.sub_status(m.from_user.id, lang)}\n\n"
                           + t(lang, "sub_price", price=config.sub_price_stars, days=config.sub_days))
            await self.send_invoice(m.chat.id, lang)

        @r.message(F.text.in_(variants("btn_profile")))
        @r.message(Command("profile"))
        async def profile(m: Message):
            u = await self.db.get_user(m.from_user.id) or {}
            lang = norm(u.get("lang"))
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "btn_capital"), callback_data="cap:menu")],
                [InlineKeyboardButton(text=t(lang, "btn_lang"), callback_data="lang:menu")],
                *([[_btn(t(lang, "btn_auto"), "at:menu")]] if self.autotrader else [])])
            cap = u.get("capital")
            cap_line = (t(lang, "profile_cap", cap=fmt_usd(cap), lot=f"{lot_plan(cap)['lot']:.2f}") if cap
                        else t(lang, "profile_nocap"))
            await m.answer(t(lang, "profile", id=m.from_user.id, status=await self.sub_status(m.from_user.id, lang),
                             language=t(lang, "lang_name")) + cap_line, reply_markup=kb)

        @r.pre_checkout_query()
        async def pre_checkout(q: PreCheckoutQuery):
            await q.answer(ok=True)

        @r.message(F.successful_payment)
        async def paid(m: Message):
            p = m.successful_payment
            await self.db.add_payment(m.from_user.id, p.total_amount, p.currency, p.telegram_payment_charge_id)
            if p.invoice_payload.startswith("auto:"):   # продление конкретного счёта
                uid, lang = m.from_user.id, await self.lang_of(m.from_user.id)
                aid = p.invoice_payload.split(":", 1)[1]
                acc = await self.db.get_account(int(aid)) if aid.isdigit() else None
                if acc and acc["user_id"] == uid:
                    until = await self.db.extend_account(acc["id"], self.at_days)
                    await m.answer(t(lang, "at_paid_acc", login=acc["login"], until=self.fmt_dt(until)),
                                   reply_markup=menu(lang))
                else:   # счёт уже отключён — оплата пойдёт на подключение нового
                    await self.db.add_credit(uid)
                    await m.answer(t(lang, "at_paid_credit", days=self.at_days), reply_markup=menu(lang))
                return
            if p.invoice_payload == "auto":   # оплата подключения нового счёта
                uid, lang = m.from_user.id, await self.lang_of(m.from_user.id)
                await self.db.add_credit(uid)
                await m.answer(t(lang, "at_paid_credit", days=self.at_days), reply_markup=menu(lang))
                intent = await self.db.get_kv(f"pay_intent:{uid}") or "real"
                await self.db.set_kv(f"pay_intent:{uid}", "")
                if self.autotrader and uid not in self._connecting:   # сразу продолжаем подключение
                    if intent == "prop":
                        await self.prop_plan_ask(m.chat.id, lang)
                    elif intent == "pnext":   # счёт следующего этапа FundedNext
                        raw = await self.db.get_kv(f"prop_next:{uid}")
                        nxt = self.stage_name(lang, (json.loads(raw) if raw else {}).get("stage"))
                        label = t(lang, "btn_prop_next", next=nxt)
                        await self.bot.send_message(m.chat.id, label, reply_markup=InlineKeyboardMarkup(
                            inline_keyboard=[[_btn(label, "at:pnext")]]))
                    else:
                        await self.show_risks(m.chat.id, lang)
                return
            until = await self.db.extend_paid(m.from_user.id, config.sub_days)
            lang = await self.lang_of(m.from_user.id)
            await m.answer(t(lang, "paid_ok", until=self.fmt_dt(until)), reply_markup=menu(lang))

        # ── админ-панель ─────────────────────────────────────────────────────
        @r.message(Command("admin"))
        async def admin(m: Message):
            if self.is_admin(m.from_user.id):
                await m.answer("🛠 <b>Админ-панель</b>", reply_markup=ADMIN_KB)

        @r.callback_query(F.data.startswith("adm:"))
        async def admin_cb(c: CallbackQuery, state: FSMContext):
            if not self.is_admin(c.from_user.id):
                await c.answer()
                return
            action = c.data.split(":", 1)[1]
            if action == "stats":
                s = await self.db.stats()
                closed = s["tp"] + s["be"] + s["sl"]
                wr = f"{100 * (s['tp'] + s['be']) / closed:.1f}%" if closed else "—"
                langs = ", ".join(f"{k}: {v}" for k, v in sorted((await self.db.lang_stats()).items()))
                accs = await self.db.trade_accounts()
                auto = (f"\n🤖 Автоторговля: {len(accs)} счетов, включено {sum(a['enabled'] for a in accs)}"
                        + (" (остановлена /autotrade off)" if await self.db.get_kv("autotrade_off") == "1" else "")
                        if self.autotrader else "")
                auto += ("\n⚡️ Торговля в новости: " + ("включена" if await self.news_trade_on() else "выключена")
                         + " (/newstrade)")
                await c.message.answer(
                    f"👥 Всего: {s['total']} (заблокировали: {s['blocked']})\n"
                    f"💎 Платных: {s['paid']}\n🎁 На пробном: {s['trial']}\n"
                    f"⭐ Выручка: {s['revenue']}\n\n"
                    f"📊 Сигналов: {s['signals']}, TP: {s['tp']}, безубыток/разворот в плюсе: {s['be']}, "
                    f"SL: {s['sl']}, в плюсе: {wr}\n"
                    f"🌐 Языки: {langs or '—'}{auto}")
            elif action == "release":
                rel = changelog.latest()
                if not rel:
                    await c.message.answer("В changelog.py пока нет ни одной версии")
                else:
                    await self.offer_release(c.from_user.id, rel)
            elif action == "broadcast":
                await state.set_state(AdminStates.broadcast)
                await c.message.answer("Отправьте сообщение для рассылки всем (текст или фото). /cancel — отмена.")
            elif action == "export":
                buf = io.StringIO()
                users = await self.db.all_users()
                w = csv.DictWriter(buf, fieldnames=list(users[0].keys()) if users else ["id"])
                w.writeheader()
                w.writerows(users)
                await c.message.answer_document(BufferedInputFile(buf.getvalue().encode(), "users.csv"))
            elif action == "signals":
                rows = await self.db.last_signals(10)
                text = "\n".join(f"#{s['id']} {self.fmt_dt(s['created_at'])} "
                                 f"{'BUY' if s['direction'] == 1 else 'SELL'} {s['entry']:.2f} → {s['status']}"
                                 for s in rows) or "Сигналов пока нет"
                await c.message.answer(text)
            elif action == "channel":
                text, kb = await self.channel_panel()
                await c.message.answer(text, reply_markup=kb)
            elif action == "granthelp":
                await c.message.answer("/grant &lt;user_id&gt; &lt;дней&gt; — выдать подписку\n"
                                       "/revoke &lt;user_id&gt; — забрать доступ\n"
                                       "/close &lt;номер&gt; tp|sl — закрыть сигнал вручную и сообщить всем\n"
                                       "/autotrade off|on — остановить / включить автоторговлю у всех\n"
                                       "/autotrade invite — спросить про автоторговлю всех, кого ещё не спрашивали\n"
                                       "/autotrade test — тестовая сделка мин. лотом на своём счёте (откроет и закроет)\n"
                                       "/grantauto &lt;user_id&gt; &lt;дней&gt; — выдать автоторговлю без оплаты\n"
                                       "/feed — откуда сейчас берутся цены (брокер или запасной источник)\n"
                                       "/channel — Telegram-канал: подключение, язык постов, тестовый пост")
            await c.answer()

        @r.message(Command("channel"))
        async def channel_cmd(m: Message):
            if self.is_admin(m.from_user.id):
                text, kb = await self.channel_panel()
                await m.answer(text, reply_markup=kb)

        @r.callback_query(F.data.startswith("chan:"))
        async def channel_cb(c: CallbackQuery):
            if not self.is_admin(c.from_user.id):
                await c.answer()
                return
            _, action, *arg = c.data.split(":")
            note = None
            if action == "set" and arg:
                await self.db.set_kv("channel_id", arg[0])
                note = "✅ Канал подключён"
            elif action == "off":
                await self.db.set_kv("channel_id", "off")
                note = "Канал отключён"
            elif action == "lang" and arg:
                await self.db.set_kv("channel_lang", norm(arg[0]))
                note = "Язык постов изменён"
            elif action == "test":
                try:
                    await self.to_channel(lambda cid, lang: self.bot.send_message(
                        cid, "✅ Бот подключён к каналу. Здесь будут сигналы и отчёты."), raise_errors=True)
                    note = "📨 Тестовый пост отправлен"
                except Exception as e:  # noqa: BLE001
                    await c.message.answer(f"⚠️ Не получилось отправить в канал: {html.escape(str(e))[:200]}\n\n"
                                           "Проверьте, что бот — администратор канала с правом «Публикация сообщений».")
            text, kb = await self.channel_panel()
            try:
                await c.message.edit_text(text, reply_markup=kb)
            except Exception:  # noqa: BLE001 — текст не изменился
                pass
            await c.answer(note or "")

        @r.my_chat_member()
        async def bot_membership(ev: ChatMemberUpdated):
            """Бота сделали админом канала — подключаем канал; убрали — предупреждаем админов."""
            if ev.chat.type != "channel":
                return
            title = html.escape(ev.chat.title or str(ev.chat.id))
            st = ev.new_chat_member.status
            current = await self.chan_target()
            if st == "administrator":
                if not getattr(ev.new_chat_member, "can_post_messages", True):
                    await self.tell_admins(f"📢 Бот стал админом канала «{title}», но без права «Публикация "
                                             "сообщений». Включите это право, иначе бот не сможет туда писать.")
                    return
                if current == ev.chat.id:
                    return
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                    text="✅ Отправлять сюда", callback_data=f"chan:set:{ev.chat.id}")]])
                if current is None and self.is_admin(ev.from_user.id):
                    await self.db.set_kv("channel_id", str(ev.chat.id))
                    await self.tell_admins(f"✅ <b>Канал «{title}» подключён.</b>\n\nТеперь туда уходит всё, "
                                             "что получают подписчики: сигналы, итоги, отчёты и новости. "
                                             "Язык постов и тестовый пост: /channel")
                else:
                    await self.tell_admins(f"📢 Бот стал админом канала «{title}». Отправлять сигналы и отчёты "
                                             "в этот канал?" + (" Сейчас они идут в другой канал." if current else ""),
                                             reply_markup=kb)
            elif st in ("left", "kicked", "member", "restricted") and current == ev.chat.id:
                await self.tell_admins(f"⚠️ Бот больше не админ канала «{title}», посты туда не уходят. "
                                         "Верните ему права администратора или подключите другой канал: /channel")

        @r.message(Command("cancel"))
        async def cancel(m: Message, state: FSMContext):
            await state.clear()
            lang = await self.lang_of(m.from_user.id)
            await m.answer(t(lang, "cancelled"), reply_markup=menu(lang))

        @r.callback_query(F.data.startswith("rel:"))
        async def release_cb(c: CallbackQuery):
            if not self.is_admin(c.from_user.id):
                await c.answer()
                return
            _, action, version = c.data.split(":", 2)
            await c.message.edit_reply_markup(reply_markup=None)
            if action == "skip":
                await c.answer("Не отправляем")
                await c.message.answer("❌ Рассылку об обновлении не отправляем. "
                                       "Передумаете — /admin → «🆕 Обновление».")
                return
            rel = changelog.find(version)
            if not rel:
                await c.answer("Версия не найдена", show_alert=True)
                return
            async with self._release_lock:
                ok = await changelog.claim_send(self.db, version, force=action == "force")
            if not ok:
                await c.answer("Эта версия уже разослана", show_alert=True)
                return
            await c.answer("Отправляю…")
            await c.message.answer("📣 Отправляю обновление всем подписчикам…")
            n = await self.broadcast_release(rel)
            await c.message.answer(f"✅ Обновление отправлено: {n} подписчикам")

        @r.message(AdminStates.broadcast)
        async def do_broadcast(m: Message, state: FSMContext):
            await state.clear()
            uids = await self.db.all_user_ids()
            n = await self.broadcast(uids, lambda u: m.copy_to(u))
            posted = await self.to_channel(lambda cid, lang: m.copy_to(cid))
            await m.answer(f"📣 Отправлено: {n} из {len(uids)}" + (" и в канал" if posted else ""))

        @r.message(Command("grant"))
        async def grant(m: Message, command: CommandObject):
            if not self.is_admin(m.from_user.id):
                return
            try:
                uid, days = (int(x) for x in (command.args or "").split())
            except ValueError:
                await m.answer("Формат: /grant &lt;user_id&gt; &lt;дней&gt;")
                return
            if not await self.db.get_user(uid):
                await m.answer("Пользователь не найден (он должен нажать /start)")
                return
            until = await self.db.extend_paid(uid, days)
            await m.answer(f"✅ {uid}: подписка до {self.fmt_dt(until)}")
            ulang = await self.lang_of(uid)
            await self._send(uid, lambda: self.bot.send_message(
                uid, t(ulang, "granted", until=self.fmt_dt(until))))

        @r.message(Command("close"))
        async def close_signal(m: Message, command: CommandObject):
            """Закрыть открытый сигнал вручную (например, тейк задет только у брокера) —
            всем уходит обычное сообщение о тейке или стопе."""
            if not self.is_admin(m.from_user.id):
                return
            args = (command.args or "").split()
            if len(args) != 2 or not args[0].lstrip("#").isdigit() or args[1].lower() not in ("tp", "sl"):
                await m.answer("Формат: /close &lt;номер сигнала&gt; tp|sl")
                return
            sid, status = int(args[0].lstrip("#")), args[1].lower()
            s = await self.db.get_signal(sid)
            if not s or s["status"] != "open":
                await m.answer(f"Сигнал #{sid} не найден или уже закрыт")
                return
            await self.db.close_signal(sid, status)
            await self.broadcast_close(s, status, s[status])
            if status == "sl":
                await self.engine.check_day_stop()
            await m.answer(f"✅ Сигнал #{sid} закрыт: {status.upper()}, сообщение отправлено всем")

        @r.message(Command("feed"))
        async def feed(m: Message):
            """Админу: откуда сейчас берутся цены, последняя ошибка MetaApi и живая проверка обоих источников."""
            if not self.is_admin(m.from_user.id):
                return
            import time
            p = self.provider
            if not isinstance(p, Failover):
                await m.answer("Источник цен: только DATA_PROVIDER / PRICE_PROVIDER "
                               "(нет METAAPI_TOKEN или MARKET_FROM_BROKER=0)")
                return
            src = await self.market_account()
            lines = ["📡 <b>Источник цен</b>",
                     f"Цена: {'⚠️ запасной источник' if 'price' in p.backup_for else '✅ брокер через MetaApi'}",
                     f"Свечи: {'⚠️ запасной источник' if 'candles' in p.backup_for else '✅ брокер через MetaApi'}",
                     f"Счёт для цен: {html.escape(src['login'] + ' · ' + src['server'] + ' · ' + src['symbol']) if src else '❌ нет подключённого счёта админа'}"]
            if p.last_ok_at:
                lines.append(f"MetaApi отвечал: {self.fmt_dt(datetime.fromtimestamp(p.last_ok_at, timezone.utc))}")
            if p.last_error:
                lines.append(f"Последняя ошибка ({self.fmt_dt(datetime.fromtimestamp(p.last_error_at, timezone.utc))}): "
                             f"<code>{html.escape(p.last_error)}</code>")
            if hasattr(p.primary, "account_state"):
                try:
                    from .autotrade import describe_account
                    from .autotrade import GONE, MetaApiError
                    state = describe_account(await asyncio.wait_for(p.primary.account_state(), 12))
                except MetaApiError as e:
                    state = (GONE if e.status == 404 else "" if e.code == "NO_ACCOUNT"
                             else f"❓ не удалось узнать: {e}"[:200])
                except Exception as e:  # noqa: BLE001
                    state = f"❓ не удалось узнать: {type(e).__name__}: {e}"[:200]
                if state:
                    lines.append(f"Счёт в MetaApi: {html.escape(state)}")
                else:
                    lines.append("Пока счёта нет, цены и свечи идут из запасного источника")
            if p.heal_note:
                lines.append(f"Автопочинка ({self.fmt_dt(datetime.fromtimestamp(p.heal_at, timezone.utc))}): "
                             f"{html.escape(p.heal_note)}")
            if p.offset is not None:
                when = self.fmt_dt(datetime.fromtimestamp(p.offset_at, timezone.utc))
                tail = ("запасная цена показывается с этой поправкой" if p.offset_fresh else
                        f"старше {p.offset_ttl / 3600:g} ч, поэтому не применяется до новой сверки")
                lines.append(f"Разница брокер − запасной: {p.offset:+.2f} (сверка {when}); {tail}")
            for name, prov in (("MetaApi", p.primary), ("Запасной", p.backup)):
                t0 = time.monotonic()
                try:
                    price = await asyncio.wait_for(prov.price(), 10)
                    extra = f" → с поправкой {p.backup_adjusted(price):.2f}" if prov is p.backup and p.offset_fresh else ""
                    lines.append(f"{name}: {price:.2f}{extra} ({time.monotonic() - t0:.1f} с)")
                except Exception as e:  # noqa: BLE001
                    lines.append(f"{name}: ❌ {html.escape(type(e).__name__ + ': ' + str(e))[:200]} "
                                 f"({time.monotonic() - t0:.1f} с)")
            await m.answer("\n".join(lines))

        @r.message(Command("newstrade"))
        async def newstrade(m: Message, command: CommandObject):
            """Админу: торговать ли во время важных новостей (/newstrade on|off)."""
            if not self.is_admin(m.from_user.id):
                return
            arg = (command.args or "").strip().lower()
            if arg in ("on", "off"):
                await self.db.set_kv("news_trade", "1" if arg == "on" else "0")
            on = await self.news_trade_on()
            await m.answer(
                ("⚡️ Торговля во время новостей <b>включена</b>: бот даёт сигналы и открывает сделки и рядом "
                 "с важными новостями, сделки перед новостью не закрываются. Перед сигналом Claude заново оценивает "
                 "новость и геополитику; против сильного или умеренного фона сигнал не даётся. "
                 f"В сам момент выхода новости (за {config.news_hot_before} мин до и {config.news_hot_after} мин после) "
                 "новые сделки не открываются.\n"
                 "Выключить: /newstrade off")
                if on else
                ("⏸ Торговля во время новостей <b>выключена</b>: за {0} мин до важной новости США сигналы на паузе, "
                 "открытые сделки закрываются.\nВключить: /newstrade on").format(config.news_pause_min))

        @r.message(Command("grantauto"))
        async def grant_auto(m: Message, command: CommandObject):
            if not self.is_admin(m.from_user.id):
                return
            try:
                uid, days = (int(x) for x in (command.args or "").split())
            except ValueError:
                await m.answer("Формат: /grantauto &lt;user_id&gt; &lt;дней&gt;")
                return
            if not await self.db.get_user(uid):
                await m.answer("Пользователь не найден (он должен нажать /start)")
                return
            until = await self.db.extend_autotrade(uid, days)
            await m.answer(f"🤖 {uid}: автоторговля до {self.fmt_dt(until)}")
            ulang = await self.lang_of(uid)
            await self._send(uid, lambda: self.bot.send_message(uid, t(ulang, "at_paid_ok", until=self.fmt_dt(until))))

        @r.message(Command("revoke"))
        async def revoke(m: Message, command: CommandObject):
            if not self.is_admin(m.from_user.id):
                return
            try:
                uid = int((command.args or "").strip())
            except ValueError:
                await m.answer("Формат: /revoke &lt;user_id&gt;")
                return
            await self.db.revoke(uid)
            await m.answer(f"⛔️ Доступ {uid} закрыт")

        @r.message(CapitalStates.waiting, F.text, ~F.text.startswith("/"))
        async def capital_bad(m: Message):  # ждём капитал, а прислали не число и не кнопку меню
            await m.answer(t(await self.lang_of(m.from_user.id), "cap_bad"))

        self._register_autotrade()

    def _register_autotrade(self) -> None:
        r = self.router

        @r.message(F.text.in_(variants("btn_fundednext")))
        @r.message(Command("fundednext"))
        async def fundednext_cmd(m: Message, state: FSMContext):
            """Отдельный раздел FundedNext: подключённый проп-счёт — его состояние, иначе — как подключить."""
            await state.clear()
            uid, lang = m.from_user.id, await self.lang_of(m.from_user.id)
            if not self.autotrader:
                await m.answer(t(lang, "at_unavailable"))
                return
            if any(a.get("prop_plan") for a in await self.db.user_accounts(uid)):
                await self.autotrade_menu(m.chat.id, uid, lang)   # подключённые проп-счета и их лимиты
            await self.prop_intro(m.chat.id, lang)

        @r.message(F.text.in_(variants("btn_auto")))
        @r.message(Command("autotrade"))
        async def autotrade_cmd(m: Message, state: FSMContext, command: CommandObject | None = None):
            arg = (command.args or "").strip().lower() if command else ""
            if arg and self.is_admin(m.from_user.id):
                if arg in ("off", "on"):
                    await self.db.set_kv("autotrade_off", "1" if arg == "off" else "0")
                    await m.answer("⛔️ Автоторговля остановлена у всех: новые сделки не открываются"
                                   if arg == "off" else "✅ Автоторговля включена")
                    return
                if arg == "test":
                    if not self.autotrader:
                        await m.answer("Нет METAAPI_TOKEN в .env")
                        return
                    await m.answer("🧪 Открываю тестовую сделку BUY минимальным лотом на вашем счёте "
                                   "(SL/TP ±$10), через 5 секунд закрою…")
                    res, closed = await self.autotrader.test_trade(m.from_user.id)
                    if not res.ok:
                        await m.answer(f"❌ Сделка не открылась:\n<code>{html.escape(res.error)}</code>")
                        return
                    text = (f"✅ Открыта: {html.escape(res.symbol)} BUY {res.volume:.2f} лота по {res.price:.2f}, "
                            f"SL {res.sl:.2f}, TP {res.tp:.2f}")
                    if closed and closed.ok:
                        pnl = "" if closed.profit is None else f", результат {closed.profit:+.2f} {closed.currency}"
                        text += f"\n✅ Закрыта{pnl}"
                    else:
                        err = closed.error if closed else "нет записи о сделке"
                        text += f"\n❌ Не закрылась, закройте вручную в MT5: <code>{html.escape(err)}</code>"
                    await m.answer(text)
                    return
                if arg == "invite":
                    if not self.autotrader:
                        await m.answer("Нет METAAPI_TOKEN в .env")
                        return
                    uids = await self.db.not_asked_autotrade()
                    langs = await self.db.user_langs()
                    n = 0
                    for u in uids:
                        lang = norm(langs.get(u))
                        n += await self._send(u, lambda u=u, lang=lang: self.ask_autotrade(u, u, lang))
                        await asyncio.sleep(0.04)
                    await m.answer(f"🤖 Вопрос про автоторговлю отправлен: {n} из {len(uids)}")
                    return
            await state.clear()
            await self.autotrade_menu(m.chat.id, m.from_user.id, await self.lang_of(m.from_user.id))

        @r.callback_query(F.data.startswith("at:"))
        async def autotrade_cb(c: CallbackQuery, state: FSMContext):
            parts = c.data.split(":")
            action, arg = parts[1], (parts[2] if len(parts) > 2 else "")
            uid, chat = c.from_user.id, c.message.chat.id
            lang = await self.lang_of(uid)
            await c.answer()
            if not self.autotrader:
                await c.message.answer(t(lang, "at_unavailable"))
                return
            if action not in ("menu", "no", "cancel"):
                try:  # кнопки прошлого шага убираем, чтобы не нажимали дважды
                    await c.message.edit_reply_markup(reply_markup=None)
                except Exception:  # noqa: BLE001
                    pass
            if action == "menu":
                await state.clear()
                await self.autotrade_menu(chat, uid, lang)
            elif action == "no":
                try:
                    await c.message.edit_reply_markup(reply_markup=None)
                except Exception:  # noqa: BLE001
                    pass
                await c.message.answer(t(lang, "at_declined_ok"))
            elif action == "cancel":
                await state.clear()
                try:
                    await c.message.edit_reply_markup(reply_markup=None)
                except Exception:  # noqa: BLE001
                    pass
                await c.message.answer(t(lang, "cancelled"), reply_markup=menu(lang))
            elif action == "yes":
                if not await self.can_connect(uid):   # каждый новый счёт: сначала оплата, потом подключение
                    await self.ask_payment(chat, uid, lang, "real")
                    return
                if uid in self._connecting:
                    await c.message.answer(t(lang, "at_busy"))
                    return
                await self.show_risks(chat, lang)
            elif action == "pay":   # продлить конкретный счёт
                acc = await self.db.get_account(int(arg)) if arg.isdigit() else None
                if acc and acc["user_id"] == uid:
                    await self.send_auto_invoice(chat, lang, acc)
                else:
                    await self.ask_payment(chat, uid, lang, "real")
            elif action == "agree":
                await state.clear()
                await c.message.answer(t(lang, "at_platform"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [_btn("MetaTrader 5", "at:pf:mt5"), _btn("MetaTrader 4", "at:pf:mt4")],
                    [_btn(t(lang, "btn_cancel"), "at:cancel")]]))
            elif action == "pf" and arg in ("mt4", "mt5"):
                await state.update_data(platform=arg)
                if (await state.get_data()).get("prop_plan"):   # проп-счёт: сразу серверы FundedNext
                    await self.show_servers(chat, lang, state, "FundedNext")
                else:
                    await c.message.answer(t(lang, "at_broker"), reply_markup=broker_kb(lang))
            elif action == "prop":
                await state.clear()
                await self.prop_intro(chat, lang)
            elif action == "pplan":
                if not await self.can_connect(uid):   # каждый новый счёт: сначала оплата, потом подключение
                    await self.ask_payment(chat, uid, lang, "prop")
                    return
                if uid in self._connecting:
                    await c.message.answer(t(lang, "at_busy"))
                    return
                await state.clear()
                await self.prop_plan_ask(chat, lang)
            elif action == "pp" and arg in pr.PLANS:
                plan = pr.PLANS[arg]
                await state.update_data(prop_plan=arg)
                if len(plan.stages) == 1:   # Instant — сразу финансируемый
                    await state.update_data(prop_stage=plan.stages[0])
                    await self.prop_ask_size(c.message, lang, arg)
                else:
                    await c.message.answer(t(lang, "prop_stage_ask", plan=plan.name),
                                           reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                               *[[_btn(self.stage_name(lang, st), f"at:ps:{st}")] for st in plan.stages],
                                               [_btn(t(lang, "btn_cancel"), "at:cancel")]]))
            elif action == "ps":
                plan_key = (await state.get_data()).get("prop_plan")
                if plan_key in pr.PLANS and arg in pr.PLANS[plan_key].stages:
                    await state.update_data(prop_stage=arg)
                    await self.prop_ask_size(c.message, lang, plan_key)
            elif action == "pz" and arg.isdigit():
                data = await state.get_data()
                plan_key, stage = data.get("prop_plan"), data.get("prop_stage")
                if plan_key in pr.PLANS and int(arg) in pr.PLANS[plan_key].sizes and stage:
                    await state.update_data(prop_size=int(arg))
                    await self.prop_rules(chat, lang, plan_key, stage, int(arg))
            elif action == "pagree":
                if not (await state.get_data()).get("prop_size"):
                    await c.message.answer(t(lang, "cancelled"), reply_markup=menu(lang))
                    return
                await c.message.answer(t(lang, "at_platform"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [_btn("MetaTrader 5", "at:pf:mt5"), _btn("MetaTrader 4", "at:pf:mt4")],
                    [_btn(t(lang, "btn_cancel"), "at:cancel")]]))
            elif action == "pnext":   # этап пройден — подключаем счёт следующего этапа
                raw = await self.db.get_kv(f"prop_next:{uid}")
                nxt = json.loads(raw) if raw else None
                if not nxt or nxt.get("plan") not in pr.PLANS or not nxt.get("stage"):
                    await self.prop_intro(chat, lang)
                    return
                paid = nxt.get("paid_until")   # оплаченные дни прошлого этапа переходят на новый счёт
                still_paid = bool(paid) and (self.db.paid_until({"paid_until": paid}) or now()) > now()
                if not still_paid and not await self.can_connect(uid):
                    await self.ask_payment(chat, uid, lang, "pnext")
                    return
                await state.clear()
                await state.update_data(prop_plan=nxt["plan"], prop_stage=nxt["stage"],
                                        prop_size=nxt["size"], platform=nxt.get("platform") or "mt5",
                                        prop_paid_until=paid if still_paid else None)
                await c.message.answer(t(lang, "prop_next_login", stage=self.stage_name(lang, nxt["stage"]),
                                         plan=pr.PLANS[nxt["plan"]].name,
                                         size=f"{float(nxt['size']):,.0f}".replace(",", " ")))
                await self.show_servers(chat, lang, state, "FundedNext")
            elif action == "br":
                if arg == "other":
                    await state.set_state(AutoStates.broker_name)
                    await c.message.answer(t(lang, "at_broker_name"))
                elif arg.isdigit() and int(arg) < len(BROKERS):
                    await self.show_servers(chat, lang, state, BROKERS[int(arg)][1])
            elif action == "sv":
                servers = (await state.get_data()).get("servers") or []
                if arg == "manual":
                    await state.set_state(AutoStates.server)
                    await c.message.answer(t(lang, "at_server_manual"))
                elif arg.isdigit() and int(arg) < len(servers):
                    await self.ask_login(chat, lang, state, servers[int(arg)])
            elif action in ("pause", "resume", "disc"):   # кнопки конкретного счёта
                acc = await self.db.get_account(int(arg)) if arg.isdigit() else None
                if not acc or acc["user_id"] != uid:
                    await self.autotrade_menu(chat, uid, lang)
                    return
                if action == "disc":
                    await self.autotrader.disconnect(acc["id"])
                    await c.message.answer(t(lang, "at_acc_prefix", login=acc["login"]) + t(lang, "at_disconnected"),
                                           reply_markup=menu(lang))
                    return
                await self.db.set_trade_enabled(acc["id"], action == "resume")
                if action == "resume":   # снять остановку проп-счёта у лимита (у лимита бот остановит снова)
                    await self.db.update_prop_state(acc["id"], prop_halt="")
                await c.message.answer(t(lang, "at_acc_prefix", login=acc["login"])
                                       + t(lang, "at_resumed_ok" if action == "resume" else "at_paused_ok"))

        not_cmd = ~F.text.startswith("/")

        @r.message(AutoStates.broker_name, F.text, not_cmd)
        async def broker_typed(m: Message, state: FSMContext):
            await self.show_servers(m.chat.id, await self.lang_of(m.from_user.id), state, m.text.strip()[:40])

        @r.message(AutoStates.server, F.text, not_cmd)
        async def server_typed(m: Message, state: FSMContext):
            await self.ask_login(m.chat.id, await self.lang_of(m.from_user.id), state, m.text.strip()[:80])

        @r.message(AutoStates.login, F.text, not_cmd)
        async def login_typed(m: Message, state: FSMContext):
            lang = await self.lang_of(m.from_user.id)
            login = m.text.strip()
            if not login.isdigit() or len(login) > 20:
                await m.answer(t(lang, "at_login_bad"))
                return
            await state.update_data(login=login)
            await state.set_state(AutoStates.password)
            # админ может подключить счёт только для цен — ему подходит и инвесторский пароль
            await m.answer(t(lang, "at_password_admin" if self.is_admin(m.from_user.id) else "at_password"))

        @r.message(AutoStates.password, F.text, not_cmd)
        async def password_typed(m: Message, state: FSMContext):
            uid, lang = m.from_user.id, await self.lang_of(m.from_user.id)
            password = m.text.strip()
            data = await state.get_data()
            await state.clear()   # в памяти бота пароль не остаётся
            try:
                await m.delete()  # и в чате тоже
            except Exception:  # noqa: BLE001
                log.warning("could not delete password message of %s", uid)
            platform, server, login = data.get("platform") or "mt5", data.get("server"), data.get("login")
            if not server or not login:
                await m.answer(t(lang, "cancelled"), reply_markup=menu(lang))
                return
            if uid in self._connecting:
                await m.answer(t(lang, "at_busy"))
                return
            self._connecting.add(uid)
            await m.answer(t(lang, "at_connecting", login=login, server=html.escape(server)))
            prop = ({"plan": data["prop_plan"], "stage": data.get("prop_stage") or "funded",
                     "size": float(data["prop_size"])}
                    if data.get("prop_plan") in pr.PLANS and data.get("prop_size") else None)
            self.spawn(self.run_connect(m.chat.id, uid, lang, platform, server, login, password, prop,
                                        data.get("prop_paid_until") if prop else None))

    # ── фоновые задачи ───────────────────────────────────────────────────────
    async def tell_admins(self, text: str, **kw) -> None:
        """Сообщение всем админам (не зависит от ADMIN_ALERTS)."""
        for a in config.admin_ids:
            await self._send(a, lambda a=a: self.bot.send_message(a, text, **kw))

    async def notify_admins(self, text: str, **kw) -> None:
        if not config.admin_alerts:
            return
        for a in config.admin_ids:
            await self._send(a, lambda a=a: self.bot.send_message(a, text, **kw))

    async def health_loop(self, every: float = 10) -> None:
        """Админам: ошибки из логов, долгий сбой проверки рынка, работа на запасной цене."""
        stall = Watch(config.alert_stall_min * 60)
        backup_price = Watch(config.alert_stall_min * 60)
        tg = Watch(config.alert_tg_min * 60)
        tg_since = 0.0
        while True:
            try:
                if self.alerts:
                    for text in self.alerts.take():
                        await self.notify_admins("⚠️ <b>Ошибка в боте</b>\n<code>" + html.escape(text) + "</code>")
                if self.alerts:
                    down = self.alerts.net_down()
                    if down and tg.bad_since is None:
                        tg_since = time.monotonic()
                    if tg.update(down) == "up":   # пока связи нет, сообщение всё равно не дойдёт — пишем после
                        mins = (time.monotonic() - tg_since) / 60
                        await self.notify_admins(
                            f"⚠️ <b>Связи с Telegram не было около {mins:.0f} мин</b>, бот в это время не отвечал.\n"
                            "Сейчас связь вернулась. Если это повторяется часто, хостинг режет Telegram: "
                            "укажите прокси в TELEGRAM_PROXY в .env.\n"
                            f"Ошибка: <code>{html.escape(self.alerts.net_error[:300])}</code>")
                now = pd.Timestamp.now(tz="UTC")
                idle = time.monotonic() - self.engine.last_ok
                ev = stall.update(market_open(now) and idle > config.check_interval * 2)
                if ev == "down":
                    await self.notify_admins(
                        f"⛔️ <b>Бот не может проверить рынок уже {idle / 60:.0f} мин</b>\nСигналы сейчас не приходят.\n"
                        f"Последняя ошибка: <code>{html.escape(self.engine.last_error or '—')}</code>")
                elif ev == "up":
                    await self.notify_admins("✅ Проверка рынка снова работает, сигналы идут.")
                on_backup = bool(getattr(self.provider, "on_backup", False))
                ev = backup_price.update(market_open(now) and on_backup)
                if ev == "down":
                    err = html.escape(getattr(self.provider, "last_error", "") or "—")
                    await self.notify_admins(
                        "⚠️ <b>Цена брокера (MetaApi) не приходит</b>, бот берёт запасную цену с поправкой.\n"
                        f"Ошибка: <code>{err}</code>\nПроверьте счёт админа в 🤖 Автоторговля и /feed.")
                elif ev == "up":
                    await self.notify_admins("✅ Цена брокера снова приходит.")
            except Exception:  # noqa: BLE001
                log.warning("health loop", exc_info=True)
            await asyncio.sleep(every)

    async def backup(self, now: pd.Timestamp | None = None) -> bool:
        """Раз в день в BACKUP_TIME (местное время): копия базы в backups и файлом админам."""
        at = parse_hhmm(config.backup_time)
        now = now or pd.Timestamp.now(tz="UTC")
        local = now.tz_convert(config.display_tz)
        if at is None or local < local.normalize() + at:
            return False
        key = f"backup:{local:%Y-%m-%d}"
        if await self.db.get_kv(key):
            return False
        await self.db.set_kv(key, "1")
        path = await asyncio.to_thread(backup_db, config.db_path, config.backup_keep, local.to_pydatetime())
        log.info("database backup: %s", path)
        if config.backup_to_admin:
            data = path.read_bytes()
            for a in config.admin_ids:
                await self._send(a, lambda a=a: self.bot.send_document(
                    a, BufferedInputFile(data, path.name), disable_notification=True,
                    caption=f"💾 Копия базы бота за {local:%d.%m.%Y}. Восстановить: положить файл вместо "
                            f"botdata/{Path(config.db_path).name} и перезапустить бота."))
        return True

    async def backup_loop(self) -> None:
        while True:
            try:
                await self.backup()
            except Exception:  # noqa: BLE001
                log.exception("database backup failed")
            await asyncio.sleep(300)

    async def weekly_report(self, now: pd.Timestamp | None = None) -> bool:
        """В воскресенье в WEEKLY_REPORT (местное время) — итоги недели всем: картинка и текст, у кого был лот —
        его результат в $."""
        at = parse_hhmm(config.weekly_report)
        now = now or pd.Timestamp.now(tz="UTC")
        local = now.tz_convert(config.display_tz)
        if at is None or local.weekday() != 6 or local < local.normalize() + at:
            return False
        key = f"weekly:{local:%Y-%m-%d}"
        if await self.db.get_kv(key):
            return False
        await self.db.set_kv(key, "1")
        start = (local.normalize() - pd.Timedelta(days=6))   # понедельник 00:00
        rows = await self.db.signals_between(start.to_pydatetime(), now.to_pydatetime())
        span = dict(start=f"{start:%d.%m}", end=f"{local:%d.%m}")
        res = {r["id"]: signal_pips(r) for r in rows}
        closed = [r for r in rows if r["status"] in WIN + ("sl", "news") and res[r["id"]] is not None]
        win = [r for r in closed if res[r["id"]] > 0]
        sl = [r for r in rows if r["status"] == "sl"]
        n_open = sum(1 for r in rows if r["status"] == "open")
        total = sum(res[r["id"]] for r in closed)
        best = max(win, key=lambda r: res[r["id"]], default=None)

        def text(lang: str) -> str:
            if not rows:
                return t(lang, "weekly_none", **span)
            out = t(lang, "weekly_head", n=len(rows), win=len(win), sl=len(sl), **span,
                    open=t(lang, "weekly_open", n=n_open) if n_open else "",
                    wr=f"{100 * len(win) / len(closed):.0f}%" if closed else "—", pips=f"{total:+.0f}")
            if best:
                out += t(lang, "weekly_best", id=best["id"], side="BUY" if best["direction"] == 1 else "SELL",
                         pips=f"{res[best['id']]:.0f}")
            return out

        pnl: dict[int, float] = {}
        for x in await self.db.lots_between(start.to_pydatetime(), now.to_pydatetime()):
            v = res.get(x["signal_id"])
            if v is not None:
                pnl[x["user_id"]] = pnl.get(x["user_id"], 0.0) + money(x["lot"], abs(v)) * (1 if v >= 0 else -1)
        images: dict[str, bytes] = {}
        if rows:
            for lang in ("ru", "en", "uz"):
                try:
                    images[lang] = await asyncio.to_thread(render_stats, list(reversed(rows)), lang,
                                                           config.display_tz, PIP, 10, t(lang, "weekly_title"))
                except Exception:  # noqa: BLE001
                    log.warning("weekly chart", exc_info=True)
        active = set(await self.db.active_user_ids())
        langs = await self.db.user_langs()

        def make(u: int):
            lang = norm(langs.get(u))
            body = text(lang)
            if u in pnl:
                v = pnl[u]
                body += t(lang, "weekly_lot", pnl=f"{'+' if v >= 0 else '−'}${fmt_usd(abs(v))}")
            if u not in active:
                body += t(lang, "weekly_cta")
            if lang in images:
                return self.bot.send_photo(u, BufferedInputFile(images[lang], "week.png"), caption=body)
            return self.bot.send_message(u, body)

        async def chan_week(cid, lang):
            body = text(lang) + await self.chan_cta(lang)
            if lang in images:
                return await self.bot.send_photo(cid, BufferedInputFile(images[lang], "week.png"), caption=body)
            return await self.bot.send_message(cid, body)
        await self.to_channel(chan_week)
        n = await self.broadcast(await self.db.all_user_ids(), make)
        log.info("weekly report sent to %s users", n)
        return True

    async def weekly_report_loop(self) -> None:
        while True:
            try:
                await self.weekly_report()
            except Exception:  # noqa: BLE001
                log.exception("weekly report failed")
            await asyncio.sleep(120)

    async def daily_report(self, now: pd.Timestamp | None = None) -> bool:
        """Итоги торгового дня, когда рынок золота закрывается (пн–пт 17:00 по Нью-Йорку): сколько сделок в плюсе
        и в минусе, пипсы, каждый сигнал. Всем подписчикам и в канал, всегда картинкой с подписью на языке
        получателя; у кого был лот — его результат за день в $."""
        if not config.daily_report:
            return False
        now = now or pd.Timestamp.now(tz="UTC")
        close = dr.day_close(now - pd.Timedelta(minutes=config.daily_report_delay_min))
        if close is None:
            return False
        key = f"daily:{close:%Y-%m-%d}"
        if await self.db.get_kv(key):
            return False
        await self.db.set_kv(key, "1")
        start, end = dr.day_open(close).to_pydatetime(), close.to_pydatetime()
        # сигнал мог открыться раньше, а закрыться сегодня: берём неделю назад и фильтруем по закрытию
        recent = await self.db.signals_between(start - timedelta(days=7), end)
        day = dr.summarize(recent, start, end)
        if not day.rows and not config.daily_report_empty:
            return False
        date = f"{close:%d.%m.%Y}"
        res = {r.s["id"]: r.pips for r in day.closed if r.pips is not None}
        pnl: dict[int, float] = {}
        for x in await self.db.lots_between(start - timedelta(days=7), end):
            v = res.get(x["signal_id"])
            if v is not None:
                pnl[x["user_id"]] = pnl.get(x["user_id"], 0.0) + money(x["lot"], abs(v)) * (1 if v >= 0 else -1)
        images: dict[str, bytes] = {}
        for lang in ("ru", "en", "uz"):
            try:
                images[lang] = await asyncio.to_thread(dr.render_daily, day, lang, config.display_tz, date)
            except Exception:  # noqa: BLE001
                log.warning("daily report chart", exc_info=True)
        local = now.tz_convert(config.display_tz)
        silent = local.hour < 8 or local.hour >= 23
        active = set(await self.db.active_user_ids())
        langs = await self.db.user_langs()

        def send(chat, lang: str, body: str):
            if lang in images:
                return self.bot.send_photo(chat, BufferedInputFile(images[lang], f"day_{close:%Y%m%d}.png"),
                                           caption=body, disable_notification=silent)
            return self.bot.send_message(chat, body, disable_notification=silent)

        def make(u: int):
            lang = norm(langs.get(u))
            tail = ""
            if u in pnl:
                v = pnl[u]
                tail += t(lang, "daily_lot", pnl=f"{'+' if v >= 0 else '−'}${fmt_usd(abs(v))}")
            if u not in active:
                tail += t(lang, "daily_cta")
            return send(u, lang, dr.caption(lang, day, date, tail))

        async def chan_day(cid, lang):
            return await send(cid, lang, dr.caption(lang, day, date, await self.chan_cta(lang)))
        await self.to_channel(chan_day)
        n = await self.broadcast(await self.db.all_user_ids(), make)
        log.info("daily report %s: %s signals, sent to %s users", date, len(day.rows), n)
        return True

    async def daily_report_loop(self) -> None:
        while True:
            try:
                await self.daily_report()
            except Exception:  # noqa: BLE001
                log.exception("daily report failed")
            await asyncio.sleep(60)

    async def calendar_loop(self) -> None:
        while True:
            try:
                n = await econ_calendar.refresh(self.db)
                log.info("calendar refreshed: %s events", n)
            except Exception:  # noqa: BLE001
                log.exception("calendar refresh")
            await asyncio.sleep(1800)

    async def news_alert_loop(self) -> None:
        async def fetch(e: dict):
            return await news_alerts.claude_fetch_actual(e, config.anthropic_model)

        while True:
            try:
                await news_alerts.process(self.db, config.display_tz, self.broadcast_all, fetch)
            except Exception:  # noqa: BLE001
                log.exception("news alerts")
            await asyncio.sleep(30)

    async def market_status(self, now=None) -> None:
        """Рынок открылся или закрылся — сообщаем всем. Ночью по местному времени — без звука."""
        import pandas as pd
        now = now or pd.Timestamp.now(tz="UTC")
        state = "open" if market_open(now) else "closed"
        prev = await self.db.get_kv("market_state")
        if prev == state:
            return
        await self.db.set_kv("market_state", state)
        if prev is None:
            return  # первый запуск: только запоминаем
        local = now.tz_convert(config.display_tz)
        silent = local.hour < 8 or local.hour >= 23
        if state == "open":
            make_text = lambda lang: t(lang, "market_open")  # noqa: E731
        else:
            nxt = next_open(now).tz_convert(config.display_tz)
            weekend = (nxt - now).total_seconds() > 6 * 3600
            when = nxt.strftime("%d.%m %H:%M")
            make_text = lambda lang: t(lang, "market_closed_week" if weekend else "market_closed", when=when)  # noqa: E731
        langs = await self.db.user_langs()

        def make(u: int):
            return self.bot.send_message(u, make_text(norm(langs.get(u))), disable_notification=silent)

        await self.chan_text(make_text, disable_notification=silent)
        n = await self.broadcast(await self.db.all_user_ids(), make)
        log.info("market %s: sent to %s users", state, n)

    async def market_status_loop(self) -> None:
        while True:
            try:
                await self.market_status()
            except Exception:  # noqa: BLE001
                log.exception("market status")
            await asyncio.sleep(60)

    async def morning_review(self, now: pd.Timestamp | None = None) -> bool:
        """Утренний разбор рынка всем подписчикам в MORNING_REVIEW по местному времени (пн–пт), раз в день."""
        at = parse_hhmm(config.morning_review)
        now = now or pd.Timestamp.now(tz="UTC")
        local = now.tz_convert(config.display_tz)
        if at is None or local.weekday() > 4 or not market_open(now) or local < local.normalize() + at:
            return False
        key = f"morning_review:{local:%Y-%m-%d}"
        if await self.db.get_kv(key):
            return False
        await self.db.set_kv(key, "1")
        news = None
        try:
            news = await self.news.bias(await self.engine.market_text(now))
        except Exception:  # noqa: BLE001
            log.exception("morning news")
        texts = {lang: await self.engine.morning_review(lang, now, news) for lang in ("ru", "en", "uz")}
        langs = await self.db.user_langs()
        await self.chan_text(lambda lang: texts.get(lang, texts["ru"]))
        n = await self.broadcast(await self.db.active_user_ids(),
                                 lambda u: self.bot.send_message(u, texts.get(norm(langs.get(u)), texts["ru"])))
        log.info("morning review sent to %s users", n)
        return True

    async def morning_review_loop(self) -> None:
        while True:
            try:
                await self.morning_review()
            except Exception:  # noqa: BLE001
                log.exception("morning review")
            await asyncio.sleep(60)

    async def autotrade_billing(self) -> None:
        """Напоминание за сутки до конца оплаты автоторговли; после конца — счёт отключается из MetaApi
        (иначе он продолжает стоить денег)."""
        if not self.autotrader:
            return
        exempt = frozenset(config.admin_ids)
        for acc in await self.db.autotrade_expiring(timedelta(days=1), exempt):
            uid, until = acc["user_id"], acc["paid_until"]
            key = f"at_remind:{acc['id']}:{until}"
            if await self.db.get_kv(key):
                continue
            await self.db.set_kv(key, "1")
            lang = await self.lang_of(uid)
            await self._send(uid, lambda u=uid, lg=lang, un=until, lo=acc["login"]: self.bot.send_message(
                u, t(lg, "at_expiring_acc", login=lo, until=self.fmt_dt(un)) + "\n\n" + self.price_line(lg)))
            await self._send(uid, lambda u=uid, lg=lang, a=acc: self.send_auto_invoice(u, lg, a))
        for acc in await self.db.autotrade_expired_accounts(exempt):
            uid = acc["user_id"]
            if uid in self._connecting:
                continue
            await self.autotrader.disconnect(acc["id"])
            log.info("autotrade expired for %s: account %s disconnected", uid, acc["login"])
            lang = await self.lang_of(uid)
            await self._send(uid, lambda u=uid, lg=lang, lo=acc["login"]: self.bot.send_message(
                u, t(lg, "at_expired_acc", login=lo)))

    async def autotrade_billing_loop(self) -> None:
        while True:
            try:
                await self.autotrade_billing()
            except Exception:  # noqa: BLE001
                log.exception("autotrade billing")
            await asyncio.sleep(600)

    async def trial_reminder_loop(self) -> None:
        while True:
            try:
                for uid in await self.db.expiring_trials(timedelta(hours=1)):
                    key = f"trial_reminded:{uid}"
                    if await self.db.get_kv(key):
                        continue
                    await self.db.set_kv(key, "1")
                    lang = await self.lang_of(uid)
                    await self._send(uid, lambda u=uid, lg=lang: self.bot.send_message(u, t(lg, "trial_reminder")))
            except Exception:  # noqa: BLE001
                log.exception("trial reminder")
            await asyncio.sleep(600)

    async def offer_release(self, admin_id: int, rel: dict) -> None:
        """Админу — готовое сообщение об обновлении (как его увидят подписчики) и кнопки."""
        sent = bool(await self.db.get_kv(changelog.sent_key(rel["version"])))
        n = len(await self.db.all_user_ids())
        note = (f"🆕 <b>Обновление {rel['version']}</b>\n"
                + ("Эта версия уже разослана. " if sent else "")
                + f"Ниже — сообщение, которое получат подписчики ({n} чел., каждый на своём языке). "
                "Отправить всем?")
        await self._send(admin_id, lambda: self.bot.send_message(admin_id, note))
        lang = await self.lang_of(admin_id)
        caption = changelog.release_text(rel, lang)
        await self._send(admin_id, lambda: self.bot.send_photo(
            admin_id, BufferedInputFile(changelog.LOGO.read_bytes(), "logo.jpg"),
            caption=caption, reply_markup=release_kb(rel["version"], sent)))

    async def broadcast_release(self, rel: dict) -> int:
        """Всем подписчикам — логотип и что нового, каждому на его языке."""
        langs = await self.db.user_langs()
        photo: dict = {}  # file_id после первой загрузки, чтобы не грузить картинку каждому

        async def send(u: int):
            m = await self.bot.send_photo(
                u, photo.get("id") or BufferedInputFile(changelog.LOGO.read_bytes(), "logo.jpg"),
                caption=changelog.release_text(rel, langs.get(u)))
            if m.photo and "id" not in photo:
                photo["id"] = m.photo[-1].file_id
            return m

        n = await self.broadcast(await self.db.all_user_ids(), send)
        log.info("release %s sent to %s users", rel["version"], n)
        return n

    async def release_offer_on_start(self) -> None:
        """После обновления — один раз предложить админам разослать новость о новой версии."""
        try:
            await asyncio.sleep(10)  # дать боту спокойно запуститься
            rel = await changelog.to_offer(self.db)
            if rel:
                for admin_id in config.admin_ids:
                    await self.offer_release(admin_id, rel)
        except Exception:  # noqa: BLE001
            log.exception("release offer")

    async def run(self) -> None:
        await self.db.connect()
        cap = await self.db.get_kv("stars_cap")
        if cap and cap.isdigit() and int(cap) < self.stars_cap:   # Telegram раньше не принял большую сумму
            await self.set_stars_cap(int(cap))
        if config.admin_alerts and config.admin_ids:
            self.alerts = AlertHandler(config.alert_repeat_min * 60)
            logging.getLogger().addHandler(self.alerts)
            rel = changelog.latest()
            await self.notify_admins("🔄 <b>Бот запущен</b>" + (f" (версия {rel['version']})" if rel else "")
                                     + ". Если вы его не перезапускали, значит он упал и Docker поднял его снова.",
                                     disable_notification=True)
        tasks = [
            asyncio.create_task(self.health_loop()),
            asyncio.create_task(self.partial_loop()),
            asyncio.create_task(self.backup_loop()),
            asyncio.create_task(self.weekly_report_loop()),
            asyncio.create_task(self.daily_report_loop()),
            asyncio.create_task(self.engine.run_forever(config.check_interval)),
            asyncio.create_task(self.calendar_loop()),
            asyncio.create_task(self.trial_reminder_loop()),
            asyncio.create_task(self.news_alert_loop()),
            asyncio.create_task(self.market_status_loop()),
            asyncio.create_task(self.morning_review_loop()),
            asyncio.create_task(self.autotrade_billing_loop()),
            asyncio.create_task(self.prop_loop()),
            asyncio.create_task(self.live_card_loop()),
            asyncio.create_task(self.reconcile_loop()),
            asyncio.create_task(self.release_offer_on_start()),
        ]
        try:
            await self.dp.start_polling(self.bot)
        finally:
            for task in tasks:
                task.cancel()
            await self.provider.close()
            if self.autotrader:
                await self.autotrader.api.close()
            await self.db.close()
