"""Telegram-бот: меню, подписка (Telegram Stars), пробный период, админ-панель, рассылка сигналов."""
from __future__ import annotations

import asyncio
import csv
import html
import io
import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

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

from . import econ_calendar, news_alerts
from .config import config
from .db import DB
from .chart import render_signal, render_stats
from .engine import NewSignal, SignalEngine, market_open, next_open
from .i18n import CHOOSE, LANG_BUTTONS, norm, t, variants
from .data import PIP
from .lots import fmt_usd, lot_for, money, parse_capital
from .market import make_provider
from .news import NewsService

log = logging.getLogger(__name__)


def menu(lang: str) -> ReplyKeyboardMarkup:
    b = lambda key: KeyboardButton(text=t(lang, key))  # noqa: E731
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [b("btn_signal")],
        [b("btn_fund"), b("btn_cal")],
        [b("btn_stats")],
        [b("btn_sub"), b("btn_profile")],
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


CAPITAL_PRESETS = (50, 100, 200, 300, 500, 1000, 2000, 5000)


def capital_kb(lang: str) -> InlineKeyboardMarkup:
    btn = lambda v: InlineKeyboardButton(text=f"${v:,}".replace(",", " "), callback_data=f"cap:{v}")  # noqa: E731
    rows = [[btn(v) for v in CAPITAL_PRESETS[i:i + 4]] for i in range(0, len(CAPITAL_PRESETS), 4)]
    rows.append([InlineKeyboardButton(text=t(lang, "btn_skip"), callback_data="cap:skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lot_plan(capital: float) -> dict:
    """Лот подписчика и что он теряет/зарабатывает по стопу/тейку."""
    lot = lot_for(capital, config.lot_mode, config.lot_risk_pct, config.sl_pips)
    loss, profit = money(lot, config.sl_pips), money(lot, config.tp_pips)
    return {"lot": lot, "loss": loss, "profit": profit, "loss_pct": 100 * loss / capital}


def lot_text(lang: str, capital: float | None) -> str:
    """Блок «Ваш лот» для подписи сигнала."""
    if not capital:
        return t(lang, "sig_nocap")
    p = lot_plan(capital)
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
    pips = lambda a, b: abs(a - b) / PIP  # noqa: E731
    total = sum(pips(r["tp"], r["entry"]) for r in tp) - sum(pips(r["sl"], r["entry"]) for r in sl)
    closed = len(tp) + len(sl)
    out = t(lang, "stats_head", total=len(rows), tp=len(tp), sl=len(sl), open=len(rows) - closed,
            wr=f"{100 * len(tp) / closed:.0f}%" if closed else "—", pips=f"{total:+.0f}")
    for r in rows[:15]:
        if r["status"] == "tp":
            res = t(lang, "stats_tp", exit=f"{r['tp']:.2f}", pips=f"{pips(r['tp'], r['entry']):.0f}")
        elif r["status"] == "sl":
            res = t(lang, "stats_sl", exit=f"{r['sl']:.2f}", pips=f"{pips(r['sl'], r['entry']):.0f}")
        else:
            res = t(lang, "stats_open")
        when = datetime.fromisoformat(r["created_at"]).astimezone(ZoneInfo(tz)).strftime("%d.%m %H:%M")
        out += t(lang, "stats_row", id=r["id"], when=when, side="🟢 BUY" if r["direction"] == 1 else "🔴 SELL",
                 entry=f"{r['entry']:.2f}", sl=f"{r['sl']:.2f}", tp=f"{r['tp']:.2f}", result=res)
    return out


def signal_caption(lang: str, text: str, capital: float | None, direction: int, entry: float) -> str:
    """Подпись к фото сигнала для конкретного подписчика: его лот, до какой цены входить, правила."""
    rules = t(lang, "sig_rules", n=config.max_sl_streak) if config.max_sl_streak > 0 else ""
    return with_lot(text, lot_text(lang, capital) + late_hint(lang, direction, entry)) + rules


def with_lot(caption: str, block: str) -> str:
    """Вставляет блок лота (и подсказку «до какой цены входить») перед курсивной припиской внизу сигнала."""
    mark = "\n\n<i>"
    return caption.replace(mark, block + mark, 1) if mark in caption else caption + block


class App:
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
        self.engine.news_pause_min = config.news_pause_min
        self.engine.news_pause_impact = config.news_pause_impact
        self.engine.news_bias = self.news.bias       # строка о фоне новостей в сигнале
        self.engine.news_block = config.news_filter  # блокировать сигнал против сильного фона
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
        uids = await self.db.active_user_ids()
        langs = await self.db.user_langs()
        caps = await self.db.user_capitals()
        images: dict[float, bytes] = {}  # лот → картинка (рисуем один раз на каждый разный лот)

        async def image_for(capital: float | None) -> bytes:
            if not capital or s.render is None:
                return s.image
            p = lot_plan(capital)
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
            caption = signal_caption(lang, s.texts[lang], capital, s.direction, s.entry)
            sent = await self._send(u, lambda u=u, img=img, caption=caption, lang=lang: self.bot.send_photo(
                u, BufferedInputFile(img, filename=f"signal_{s.id}.png"), caption=caption,
                reply_markup=decision_kb(lang, s.id)))
            if sent:  # запоминаем, кто получил сигнал и с каким лотом (0 — капитал не указан)
                await self.db.add_signal_lot(s.id, u, lot_plan(capital)["lot"] if capital else 0)
            ok += sent
            await asyncio.sleep(0.04)
        log.info("signal #%s sent to %s users", s.id, ok)

    async def broadcast_close(self, s: dict, status: str, price: float) -> None:
        """Итог сигнала — всем участникам бота (подписчикам и тем, у кого доступ закончился)."""
        side = "BUY" if s["direction"] == 1 else "SELL"
        if status == "tp":
            pips, level = config.tp_pips, s["tp"]
        else:
            pips, level = config.sl_pips, s["sl"]
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
        if data.get("onboard"):  # новый пользователь: дальше приветствие с меню
            await self.bot.send_message(chat_id, text)
            await self.send_hello(chat_id, user.id, user.first_name, lang, bool(data.get("new_user")))
        else:
            await self.bot.send_message(chat_id, text, reply_markup=menu(lang))

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
                [InlineKeyboardButton(text=t(lang, "btn_lang"), callback_data="lang:menu")]])
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
                await c.message.answer(
                    f"👥 Всего: {s['total']} (заблокировали: {s['blocked']})\n"
                    f"💎 Платных: {s['paid']}\n🎁 На пробном: {s['trial']}\n"
                    f"⭐ Выручка: {s['revenue']}\n\n"
                    f"📊 Сигналов: {s['signals']}, TP: {s['tp']}, SL: {s['sl']}, винрейт: {wr}\n"
                    f"🌐 Языки: {langs or '—'}")
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
                                       "/revoke &lt;user_id&gt; — забрать доступ")
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
        ]
        try:
            await self.dp.start_polling(self.bot)
        finally:
            for task in tasks:
                task.cancel()
            await self.provider.close()
            await self.db.close()
