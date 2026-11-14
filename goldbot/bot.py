"""Telegram-бот: меню, подписка (Telegram Stars), пробный период, админ-панель, рассылка сигналов."""
from __future__ import annotations

import asyncio
import csv
import html
import io
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, KeyboardButton, LabeledPrice, Message,
                           PreCheckoutQuery, ReplyKeyboardMarkup)

import json

from . import econ_calendar, news_alerts
from . import prop as pr
from .autotrade import BROKERS, AutoTrader, BrokerMarket, MetaApi, demo_servers, sl_tp_dist
from .config import config
from .db import DB, now
from .chart import render_signal, render_stats
from .engine import NewSignal, SignalEngine, market_open, next_open, parse_hhmm
from .i18n import CHOOSE, LANG_BUTTONS, norm, t, variants
from .data import PIP
from .lots import fmt_usd, lot_for, money, parse_capital
from .market import Failover, make_provider
from .news import NewsService

log = logging.getLogger(__name__)


def menu(lang: str) -> ReplyKeyboardMarkup:
    b = lambda key: KeyboardButton(text=t(lang, key))  # noqa: E731
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [b("btn_signal")],
        [b("btn_fund"), b("btn_cal")],
        [b("btn_stats")],
        [b("btn_sub"), b("btn_profile")],
        *([[b("btn_auto")]] if config.metaapi_token else []),
    ])


LANG_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text=label, callback_data=f"lang:{code}")] for code, label in LANG_BUTTONS])

ADMIN_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📈 Статистика", callback_data="adm:stats"),
     InlineKeyboardButton(text="📣 Рассылка", callback_data="adm:broadcast")],
    [InlineKeyboardButton(text="👥 Подписчики (CSV)", callback_data="adm:export"),
     InlineKeyboardButton(text="🧾 Последние сигналы", callback_data="adm:signals")],
    [InlineKeyboardButton(text="🎁 Выдать / забрать подписку", callback_data="adm:granthelp")],
])


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
    key = {"E_AUTH": "at_err_auth", "E_SRV_NOT_FOUND": "at_err_server", "REAL_NOT_ALLOWED": "at_err_real",
           "NO_GOLD": "at_err_gold", "TIMEOUT": "at_err_timeout"}.get(code)
    if not key and isinstance(e, asyncio.TimeoutError):
        key = "at_err_timeout"
    if key:
        return t(lang, key, server=html.escape(server)) if key == "at_err_server" else t(lang, key)
    return t(lang, "at_err_other", error=html.escape(code or str(e) or type(e).__name__)[:150])


def usd(x: float) -> str:
    return f"${x:,.2f}".replace(",", " ")


def trade_error_text(lang: str, error: str) -> str:
    if error == "PROP_LIMIT":
        return t(lang, "at_e_prop")
    if error == "PROP_DAY_LOSS":
        return t(lang, "at_e_prop_loss")
    if error in ("NO_MONEY", "TRADE_RETCODE_NO_MONEY"):
        return t(lang, "at_e_money")
    if error in ("TRADE_RETCODE_MARKET_CLOSED", "TRADE_RETCODE_TRADE_DISABLED"):
        return t(lang, "at_e_market")
    if error in ("TRADE_RETCODE_CONNECTION", "TRADE_RETCODE_NO_CONNECTION") or "connect" in error.lower():
        return t(lang, "at_e_conn")
    return html.escape(error)[:150]


CAPITAL_PRESETS = (50, 100, 200, 300, 500, 1000, 2000, 5000)


def capital_kb(lang: str) -> InlineKeyboardMarkup:
    btn = lambda v: InlineKeyboardButton(text=f"${v:,}".replace(",", " "), callback_data=f"cap:{v}")  # noqa: E731
    rows = [[btn(v) for v in CAPITAL_PRESETS[i:i + 4]] for i in range(0, len(CAPITAL_PRESETS), 4)]
    rows.append([InlineKeyboardButton(text=t(lang, "btn_skip"), callback_data="cap:skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lot_plan(capital: float, sl_pips: float = 0, tp_pips: float = 0) -> dict:
    """Лот подписчика и что он теряет/зарабатывает по стопу/тейку (пипсы сигнала; 0 — из настроек)."""
    sl_pips, tp_pips = sl_pips or config.sl_pips, tp_pips or config.tp_pips
    lot = lot_for(capital, config.lot_mode, config.lot_risk_pct, sl_pips)
    loss, profit = money(lot, sl_pips), money(lot, tp_pips)
    return {"lot": lot, "loss": loss, "profit": profit, "loss_pct": 100 * loss / capital}


def lot_text(lang: str, capital: float | None, sl_pips: float = 0, tp_pips: float = 0) -> str:
    """Блок «Ваш лот» для подписи сигнала."""
    if not capital:
        return t(lang, "sig_nocap")
    p = lot_plan(capital, sl_pips, tp_pips)
    pct = f"{p['loss_pct']:.1f}".rstrip("0").rstrip(".")
    text = t(lang, "sig_lot", lot=f"{p['lot']:.2f}", cap=fmt_usd(capital), loss=fmt_usd(p["loss"]),
             loss_pct=pct, profit=fmt_usd(p["profit"]))
    limit = config.lot_risk_pct if config.lot_mode == "risk" else None
    if limit and p["loss_pct"] > limit + 1e-9:
        text += t(lang, "sig_lot_warn", loss_pct=pct, pct=f"{limit:g}")
    return text


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


def stats_text(lang: str, rows: list[dict], tz: str) -> str:
    """Статистика для подписчиков: итоги и последние сигналы со входом, выходом и результатом."""
    from datetime import datetime
    if not rows:
        return t(lang, "stats_empty")
    tp = [r for r in rows if r["status"] == "tp"]
    sl = [r for r in rows if r["status"] == "sl"]
    nw = [r for r in rows if r["status"] == "news" and r.get("exit_price")]
    pips = lambda a, b: abs(a - b) / PIP  # noqa: E731
    news_pips = lambda r: r["direction"] * (r["exit_price"] - r["entry"]) / PIP  # noqa: E731
    total = (sum(pips(r["tp"], r["entry"]) for r in tp) - sum(pips(r["sl"], r["entry"]) for r in sl)
             + sum(news_pips(r) for r in nw))
    closed = len(tp) + len(sl)
    n_open = sum(1 for r in rows if r["status"] == "open")
    out = t(lang, "stats_head", total=len(rows), tp=len(tp), sl=len(sl), open=n_open,
            wr=f"{100 * len(tp) / closed:.0f}%" if closed else "—", pips=f"{total:+.0f}")
    for r in rows[:15]:
        if r["status"] == "tp":
            res = t(lang, "stats_tp", exit=f"{r['tp']:.2f}", pips=f"{pips(r['tp'], r['entry']):.0f}")
        elif r["status"] == "sl":
            res = t(lang, "stats_sl", exit=f"{r['sl']:.2f}", pips=f"{pips(r['sl'], r['entry']):.0f}")
        elif r["status"] == "news" and r.get("exit_price"):
            res = t(lang, "stats_news", exit=f"{r['exit_price']:.2f}", pips=f"{news_pips(r):+.0f}")
        else:
            res = t(lang, "stats_open")
        when = datetime.fromisoformat(r["created_at"]).astimezone(ZoneInfo(tz)).strftime("%d.%m %H:%M")
        out += t(lang, "stats_row", id=r["id"], when=when, side="🟢 BUY" if r["direction"] == 1 else "🔴 SELL",
                 entry=f"{r['entry']:.2f}", sl=f"{r['sl']:.2f}", tp=f"{r['tp']:.2f}", result=res)
    return out


def signal_caption(lang: str, text: str, capital: float | None, direction: int, entry: float,
                   sl_pips: float = 0, tp_pips: float = 0) -> str:
    """Подпись к фото сигнала для конкретного подписчика: его лот, до какой цены входить, правила."""
    rules = t(lang, "sig_rules", n=config.max_sl_streak) if config.max_sl_streak > 0 else ""
    return with_lot(text, lot_text(lang, capital, sl_pips, tp_pips) + late_hint(lang, direction, entry)) + rules


def with_lot(caption: str, block: str) -> str:
    """Вставляет блок лота (и подсказку «до какой цены входить») перед курсивной припиской внизу сигнала."""
    mark = "\n\n<i>"
    return caption.replace(mark, block + mark, 1) if mark in caption else caption + block


class App:
    autotrader: AutoTrader | None = None

    def __init__(self) -> None:
        self.bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dp = Dispatcher()
        self.db = DB(config.db_path)
        self.news = NewsService(config.news_feeds, config.anthropic_model)
        self.provider = make_provider(config)
        self.engine = SignalEngine(self.db, self.provider, config.strategy, config.sl_pips, config.tp_pips,
                                   config.display_tz, self.broadcast_signal, self.broadcast_close,
                                   self.broadcast_late, config.late_pips,
                                   self.broadcast_day_closed, config.max_sl_streak)
        self.engine.sl_atr, self.engine.tp_atr = config.sl_atr, config.tp_atr
        self.engine.sl_min_pips = config.sl_min_pips
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
        if config.metaapi_token:
            self.autotrader = AutoTrader(self.db, MetaApi(config.metaapi_token), config.autotrade_demo_only,
                                         config.autotrade_risk_pct, config.autotrade_max_lot,
                                         config.autotrade_symbol, config.metaapi_region,
                                         exempt=frozenset(config.admin_ids),
                                         prop_risk_pct=config.prop_risk_pct,
                                         prop_strong_risk_pct=config.prop_strong_risk_pct, prop_guard_pct=config.prop_guard_pct,
                                         prop_max_lot=config.prop_max_lot, prop_risk_cap=config.prop_risk_cap,
                                         prop_max_trade=config.prop_max_trade_pct,
                                         prop_day_tz=config.prop_day_tz,
                                         prop_close=config.prop_close,
                                         prop_day_losses=config.prop_day_losses,
                                         prop_dd_pct=config.prop_dd_pct, prop_dd_mult=config.prop_dd_mult)
        if self.autotrader and config.market_from_broker:
            # анализ по графику брокера с подключённого счёта админа; запасной — прежний источник
            self.provider = Failover(BrokerMarket(self.autotrader.api, self.market_account), self.provider)
            self.engine.provider = self.provider
        self._market_src: tuple[float, dict | None] = (0.0, None)
        self._connecting: set[int] = set()   # чьи счета сейчас подключаются
        self._tasks: set[asyncio.Task] = set()
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

    async def broadcast_signal(self, s: NewSignal) -> None:
        """Каждому подписчику — картинка и текст с его лотом (по его капиталу)."""
        self.spawn(self.autotrade_open(s))   # на подключённых счетах сделка открывается сразу
        uids = await self.db.active_user_ids()
        langs = await self.db.user_langs()
        caps = await self.db.user_capitals()
        images: dict[float, bytes] = {}  # лот → картинка (рисуем один раз на каждый разный лот)

        async def image_for(capital: float | None) -> bytes:
            if not capital or s.render is None:
                return s.image
            p = lot_plan(capital, s.sl_pips, s.tp_pips)
            if p["lot"] not in images:
                try:
                    images[p["lot"]] = await asyncio.to_thread(
                        s.render, lot=f"LOT {p['lot']:.2f}",
                        sl_note=f"−${fmt_usd(p['loss'])}", tp_note=f"+${fmt_usd(p['profit'])}")
                except Exception:  # noqa: BLE001
                    log.exception("lot chart")
                    images[p["lot"]] = s.image
            return images[p["lot"]]

        ok = 0
        for u in uids:
            lang, capital = norm(langs.get(u)), caps.get(u)
            img = await image_for(capital)
            caption = signal_caption(lang, s.texts[lang], capital, s.direction, s.entry, s.sl_pips, s.tp_pips)
            sent = await self._send(u, lambda u=u, img=img, caption=caption, lang=lang: self.bot.send_photo(
                u, BufferedInputFile(img, filename=f"signal_{s.id}.png"), caption=caption,
                reply_markup=decision_kb(lang, s.id)))
            if sent:  # запоминаем, кто получил сигнал и с каким лотом (0 — капитал не указан)
                await self.db.add_signal_lot(s.id, u, lot_plan(capital, s.sl_pips, s.tp_pips)["lot"] if capital else 0)
            ok += sent
            await asyncio.sleep(0.04)
        log.info("signal #%s sent to %s users", s.id, ok)

    async def broadcast_news_close(self, s: dict, price: float, ev: dict, mins: int) -> None:
        """Перед важной новостью: всем — закрыть сделку по рынку."""
        self.spawn(self.autotrade_close(s["id"]))
        side = "BUY" if s["direction"] == 1 else "SELL"
        res = s["direction"] * (price - s["entry"]) / PIP
        langs = await self.db.user_langs()

        def text(lang: str) -> str:
            return t(lang, "news_close", id=s["id"], side=side, entry=f"{s['entry']:.2f}", mins=mins,
                     title=html.escape(ev.get("title", "")), price=f"{price:.2f}", pips=f"{res:+.0f}")

        n = await self.broadcast(await self.db.all_user_ids(),
                                 lambda u: self.bot.send_message(u, text(norm(langs.get(u)))))
        log.info("news close #%s sent to %s users", s["id"], n)

    async def broadcast_close(self, s: dict, status: str, price: float) -> None:
        """Итог сигнала — всем участникам бота (подписчикам и тем, у кого доступ закончился)."""
        self.spawn(self.autotrade_close(s["id"]))   # что не закрыл брокер по своим SL/TP — закрываем
        side = "BUY" if s["direction"] == 1 else "SELL"
        level = s["tp"] if status == "tp" else s["sl"]
        pips = abs(level - s["entry"]) / PIP   # у каждого сигнала свои стоп и тейк
        st = await self.db.stats()
        closed = st["tp"] + st["sl"]

        def text(lang: str) -> str:
            return (t(lang, "close_tp" if status == "tp" else "close_sl", id=s["id"], side=side, pips=f"{pips:.0f}")
                    + "\n\n" + excursion_text(lang, s, status)
                    + t(lang, "close_body", entry=f"{s['entry']:.2f}", exit=f"{level:.2f}",
                                  sl=f"{s['sl']:.2f}", tp=f"{s['tp']:.2f}", tp_n=st["tp"], sl_n=st["sl"])
                    + (t(lang, "winrate", wr=f"{100 * st['tp'] / closed:.0f}") if closed else ""))

        image = None
        df = self.engine.df_for(s.get("strategy"))
        if df is not None:
            try:
                image = render_signal(df, s["direction"], s["entry"], s["sl"], s["tp"],
                                      f"XAUUSD · #{s['id']} · {'TAKE PROFIT' if status == 'tp' else 'STOP LOSS'}",
                                      tz=config.display_tz, mfe=s.get("mfe"), mae=s.get("mae"), pip=PIP)
            except Exception:  # noqa: BLE001
                log.exception("close chart")
        active = set(await self.db.active_user_ids())
        langs = await self.db.user_langs()

        # у кого был лот в этом сигнале — пересчитываем баланс и пишем результат в $
        results: dict[int, str] = {}
        for u, lot in (await self.db.signal_lots(s["id"])).items():
            if not lot:
                continue
            pnl = money(lot, pips) * (1 if status == "tp" else -1)
            bal = await self.db.add_capital(u, pnl)
            results[u] = (lot, pnl, bal)

        def balance_text(lang: str, u: int) -> str:
            if u not in results:
                return ""
            lot, pnl, bal = results[u]
            sign = "+" if pnl >= 0 else "−"
            return t(lang, "close_balance", lot=f"{lot:.2f}", pnl=f"{sign}${fmt_usd(abs(pnl))}", bal=fmt_usd(bal))

        declined = await self.db.declined_users(s["id"])

        def make(u: int):
            lang = norm(langs.get(u))
            body = text(lang) + balance_text(lang, u)
            if u not in active:
                body += t(lang, "close_cta")
            if image:
                return self.bot.send_photo(u, BufferedInputFile(image, f"result_{s['id']}.png"), caption=body)
            return self.bot.send_message(u, body)

        # кто нажал «Отклонить» под этим сигналом — результат по нему не присылаем
        await self.broadcast([u for u in await self.db.all_user_ids() if u not in declined], make)

    async def broadcast_late(self, s: dict, price: float, moved: float) -> None:
        """Цена уже ушла от входа к тейку — тем, кто получил сигнал: не входите, вы опоздали."""
        langs = await self.db.user_langs()
        side = "BUY" if s["direction"] == 1 else "SELL"
        uids = list(await self.db.signal_lots(s["id"]))

        def make(u: int):
            lang = norm(langs.get(u))
            return self.bot.send_message(u, t(lang, "late", id=s["id"], side=side, entry=f"{s['entry']:.2f}",
                                              price=f"{price:.2f}", pips=f"{moved:.0f}"))

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

    async def send_auto_invoice(self, chat_id: int, lang: str) -> None:
        """Счёт на оплату автоторговли (отдельно от подписки на сигналы)."""
        await self.bot.send_invoice(
            chat_id, title=t(lang, "inv_auto_title", days=config.autotrade_days),
            description=t(lang, "inv_auto_desc"),
            payload="auto", currency="XTR", provider_token="",
            prices=[LabeledPrice(label=t(lang, "inv_label", days=config.autotrade_days),
                                 amount=config.autotrade_price_stars)])

    async def has_autotrade(self, uid: int) -> bool:
        """Оплачена ли автоторговля (админам — всегда)."""
        if self.is_admin(uid):
            return True
        until = self.db.autotrade_until(await self.db.get_user(uid))
        return bool(until and until > now())

    def price_line(self, lang: str) -> str:
        return t(lang, "at_price", stars=config.autotrade_price_stars, usd=config.autotrade_price_usd,
                 days=config.autotrade_days)

    async def show_risks(self, chat_id: int, lang: str) -> None:
        demo = t(lang, "at_demo_note") if config.autotrade_demo_only else ""
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
        src = accs[0] if accs else None
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
                                                        strong=getattr(s, "strong", False))
        except Exception:  # noqa: BLE001
            log.exception("autotrade open #%s", s.id)
            return
        langs = await self.db.user_langs()
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
            await self._send(r.uid, lambda u=r.uid, x=text: self.bot.send_message(u, x))
        log.info("autotrade #%s: %s opened, %s failed", s.id, sum(r.ok for r in results),
                 sum(not r.ok for r in results))

    async def autotrade_close(self, sid: int, uids: set[int] | None = None) -> None:
        if not self.autotrader:
            return
        try:
            results = await self.autotrader.close_signal(sid, uids)
        except Exception:  # noqa: BLE001
            log.exception("autotrade close #%s", sid)
            return
        langs = await self.db.user_langs()
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
            await self._send(r.uid, lambda u=r.uid, x=t(lang, "at_closed", id=sid, profit=profit):
                             self.bot.send_message(u, x))

    async def ask_autotrade(self, chat_id: int, uid: int, lang: str) -> None:
        """Один раз спрашиваем подписчика, подключить ли бота к его счёту."""
        if not self.autotrader:
            return
        u = await self.db.get_user(uid)
        if not u or u.get("autotrade_asked") or await self.db.get_trade_account(uid):
            return
        await self.db.set_autotrade_asked(uid)
        text = t(lang, "at_ask") + ("" if await self.has_autotrade(uid) else "\n\n" + self.price_line(lang))
        await self.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn(t(lang, "btn_yes_connect"), "at:yes"), _btn(t(lang, "btn_no_thanks"), "at:no")],
            [_btn(t(lang, "btn_prop"), "at:prop")]]))

    async def autotrade_menu(self, chat_id: int, uid: int, lang: str) -> None:
        if not self.autotrader:
            await self.bot.send_message(chat_id, t(lang, "at_unavailable"))
            return
        acc = await self.autotrader.status(uid)
        if not acc:
            await self.bot.send_message(chat_id, t(lang, "at_none") + await self.paid_line(uid, lang),
                                        reply_markup=InlineKeyboardMarkup(
                                            inline_keyboard=[[_btn(t(lang, "btn_connect"), "at:yes")],
                                                             [_btn(t(lang, "btn_prop"), "at:prop")]]))
            return
        if await self.db.get_kv("autotrade_off") == "1":
            state = t(lang, "at_global_off")
        else:
            state = t(lang, "at_on" if acc["enabled"] else "at_paused")
        bal = acc.get("balance")
        balance = f"{bal:,.2f} {acc.get('currency') or ''}".replace(",", " ") if bal is not None else "—"
        text = t(lang, "at_status", broker=html.escape(acc.get("broker") or "—"), login=acc["login"],
                 server=html.escape(acc["server"]), kind=t(lang, "at_kind_demo" if acc["demo"] else "at_kind_real"),
                 balance=balance, state=state, risk=f"{config.autotrade_risk_pct:g}",
                 max_lot=f"{config.autotrade_max_lot:g}") + self.prop_status(acc, lang) \
            + await self.paid_line(uid, lang)
        toggle = _btn(t(lang, "btn_pause"), "at:pause") if acc["enabled"] else _btn(t(lang, "btn_resume"), "at:resume")
        rows = [[toggle], [_btn(t(lang, "btn_disconnect"), "at:disc")]]
        if not self.is_admin(uid):
            rows.insert(1, [_btn(t(lang, "btn_extend"), "at:pay")])
        await self.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

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
                 halt=t(lang, f"prop_status_halt_{halt}") if halt in ("daily", "total", "loss") else "")

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
            await self._send(uid, lambda u=uid, x=text, mk=markup: self.bot.send_message(u, x, reply_markup=mk))

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

    async def paid_line(self, uid: int, lang: str) -> str:
        """Строка «Оплачено до …» / цена — для меню автоторговли."""
        if self.is_admin(uid):
            return t(lang, "at_until_admin")
        until = self.db.autotrade_until(await self.db.get_user(uid))
        if until and until > now():
            return t(lang, "at_until", until=self.fmt_dt(until))
        return "\n\n" + self.price_line(lang)

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
                          password: str, prop: dict | None = None) -> None:
        try:
            info = await self.autotrader.connect(uid, platform, server, login, password, prop=prop)
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
            price = t(lang, "price_now", price=f"{self.engine.last_price:.2f}") if self.engine.last_price else ""
            opened = await self.db.open_signals()
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
            if p.invoice_payload == "auto":   # оплата автоторговли
                uid = m.from_user.id
                until = await self.db.extend_autotrade(uid, config.autotrade_days)
                lang = await self.lang_of(uid)
                await m.answer(t(lang, "at_paid_ok", until=self.fmt_dt(until)), reply_markup=menu(lang))
                if self.autotrader and not await self.db.get_trade_account(uid) and uid not in self._connecting:
                    await self.show_risks(m.chat.id, lang)   # сразу продолжаем подключение счёта
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
                closed = s["tp"] + s["sl"]
                wr = f"{100 * s['tp'] / closed:.1f}%" if closed else "—"
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
                    f"📊 Сигналов: {s['signals']}, TP: {s['tp']}, SL: {s['sl']}, винрейт: {wr}\n"
                    f"🌐 Языки: {langs or '—'}{auto}")
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
            elif action == "granthelp":
                await c.message.answer("/grant &lt;user_id&gt; &lt;дней&gt; — выдать подписку\n"
                                       "/revoke &lt;user_id&gt; — забрать доступ\n"
                                       "/close &lt;номер&gt; tp|sl — закрыть сигнал вручную и сообщить всем\n"
                                       "/autotrade off|on — остановить / включить автоторговлю у всех\n"
                                       "/autotrade invite — спросить про автоторговлю всех, кого ещё не спрашивали\n"
                                       "/autotrade test — тестовая сделка мин. лотом на своём счёте (откроет и закроет)\n"
                                       "/grantauto &lt;user_id&gt; &lt;дней&gt; — выдать автоторговлю без оплаты\n"
                                       "/feed — откуда сейчас берутся цены (брокер или запасной источник)")
            await c.answer()

        @r.message(Command("cancel"))
        async def cancel(m: Message, state: FSMContext):
            await state.clear()
            lang = await self.lang_of(m.from_user.id)
            await m.answer(t(lang, "cancelled"), reply_markup=menu(lang))

        @r.message(AdminStates.broadcast)
        async def do_broadcast(m: Message, state: FSMContext):
            await state.clear()
            uids = await self.db.all_user_ids()
            n = await self.broadcast(uids, lambda u: m.copy_to(u))
            await m.answer(f"📣 Отправлено: {n} из {len(uids)}")

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
            for name, prov in (("MetaApi", p.primary), ("Запасной", p.backup)):
                t0 = time.monotonic()
                try:
                    price = await asyncio.wait_for(prov.price(), 10)
                    lines.append(f"{name}: {price:.2f} ({time.monotonic() - t0:.1f} с)")
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
                if not await self.has_autotrade(uid):   # сначала оплата, потом подключение
                    await c.message.answer(t(lang, "at_pay") + "\n\n" + self.price_line(lang))
                    await self.send_auto_invoice(chat, lang)
                    return
                if uid in self._connecting:
                    await c.message.answer(t(lang, "at_busy"))
                    return
                await self.show_risks(chat, lang)
            elif action == "pay":
                await self.send_auto_invoice(chat, lang)
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
                if not await self.has_autotrade(uid):   # сначала оплата автоторговли, потом подключение
                    await c.message.answer(t(lang, "at_pay") + "\n\n" + self.price_line(lang))
                    await self.send_auto_invoice(chat, lang)
                    return
                if uid in self._connecting:
                    await c.message.answer(t(lang, "at_busy"))
                    return
                await state.clear()
                await c.message.answer(t(lang, "prop_plan_ask"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    *[[_btn(p.name, f"at:pp:{k}")] for k, p in pr.PLANS.items()],
                    [_btn(t(lang, "btn_cancel"), "at:cancel")]]))
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
                if not await self.has_autotrade(uid):
                    await c.message.answer(t(lang, "at_pay") + "\n\n" + self.price_line(lang))
                    await self.send_auto_invoice(chat, lang)
                    return
                await state.clear()
                await state.update_data(prop_plan=nxt["plan"], prop_stage=nxt["stage"],
                                        prop_size=nxt["size"], platform=nxt.get("platform") or "mt5")
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
            elif action in ("pause", "resume"):
                await self.db.set_trade_enabled(uid, action == "resume")
                if action == "resume":   # снять остановку проп-счёта у лимита (у лимита бот остановит снова)
                    await self.db.update_prop_state(uid, prop_halt="")
                await c.message.answer(t(lang, "at_resumed_ok" if action == "resume" else "at_paused_ok"))
            elif action == "disc":
                await self.autotrader.disconnect(uid)
                await c.message.answer(t(lang, "at_disconnected"), reply_markup=menu(lang))

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
            await m.answer(t(lang, "at_password"))

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
            self.spawn(self.run_connect(m.chat.id, uid, lang, platform, server, login, password, prop))

    # ── фоновые задачи ───────────────────────────────────────────────────────
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
        for uid, until in await self.db.autotrade_expiring(timedelta(days=1), exempt):
            key = f"at_remind:{uid}:{until}"
            if await self.db.get_kv(key):
                continue
            await self.db.set_kv(key, "1")
            lang = await self.lang_of(uid)
            await self._send(uid, lambda u=uid, lg=lang, un=until: self.bot.send_message(
                u, t(lg, "at_expiring", until=self.fmt_dt(un)) + "\n\n" + self.price_line(lg)))
            await self._send(uid, lambda u=uid, lg=lang: self.send_auto_invoice(u, lg))
        for uid in await self.db.autotrade_expired_accounts(exempt):
            if uid in self._connecting:
                continue
            await self.autotrader.disconnect(uid)
            log.info("autotrade expired for %s: account disconnected", uid)
            lang = await self.lang_of(uid)
            await self._send(uid, lambda u=uid, lg=lang: self.bot.send_message(u, t(lg, "at_expired")))

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

    async def run(self) -> None:
        await self.db.connect()
        tasks = [
            asyncio.create_task(self.engine.run_forever(config.check_interval)),
            asyncio.create_task(self.calendar_loop()),
            asyncio.create_task(self.trial_reminder_loop()),
            asyncio.create_task(self.news_alert_loop()),
            asyncio.create_task(self.market_status_loop()),
            asyncio.create_task(self.morning_review_loop()),
            asyncio.create_task(self.autotrade_billing_loop()),
            asyncio.create_task(self.prop_loop()),
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
