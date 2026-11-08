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
from .chart import render_signal
from .engine import NewSignal, SignalEngine
from .i18n import CHOOSE, LANG_BUTTONS, norm, t, variants
from .market import make_provider
from .news import NewsService

log = logging.getLogger(__name__)


def menu(lang: str) -> ReplyKeyboardMarkup:
    b = lambda key: KeyboardButton(text=t(lang, key))  # noqa: E731
    return ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [b("btn_signal")],
        [b("btn_fund"), b("btn_cal")],
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


class App:
    def __init__(self) -> None:
        self.bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dp = Dispatcher()
        self.db = DB(config.db_path)
        self.news = NewsService(config.news_feeds, config.anthropic_model)
        self.provider = make_provider(config)
        self.engine = SignalEngine(self.db, self.provider, config.strategy, config.sl_pips, config.tp_pips,
                                   config.display_tz, self.broadcast_signal, self.broadcast_close)
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
        uids = await self.db.active_user_ids()
        langs = await self.db.user_langs()
        photo = BufferedInputFile(s.image, filename=f"signal_{s.id}.png")
        n = await self.broadcast(uids, lambda u: self.bot.send_photo(u, photo, caption=s.texts[norm(langs.get(u))]))
        log.info("signal #%s sent to %s users", s.id, n)

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
                    + "\n\n" + t(lang, "close_body", entry=f"{s['entry']:.2f}", exit=f"{level:.2f}",
                                  sl=f"{s['sl']:.2f}", tp=f"{s['tp']:.2f}", tp_n=st["tp"], sl_n=st["sl"])
                    + (t(lang, "winrate", wr=f"{100 * st['tp'] / closed:.0f}") if closed else ""))

        image = None
        if self.engine.last_df is not None:
            try:
                image = render_signal(self.engine.last_df, s["direction"], s["entry"], s["sl"], s["tp"],
                                      f"XAUUSD · #{s['id']} · {'TAKE PROFIT' if status == 'tp' else 'STOP LOSS'}",
                                      tz=config.display_tz)
            except Exception:  # noqa: BLE001
                log.exception("close chart")
        active = set(await self.db.active_user_ids())
        langs = await self.db.user_langs()

        def make(u: int):
            lang = norm(langs.get(u))
            body = text(lang) if u in active else text(lang) + t(lang, "close_cta")
            if image:
                return self.bot.send_photo(u, BufferedInputFile(image, f"result_{s['id']}.png"), caption=body)
            return self.bot.send_message(u, body)

        await self.broadcast(await self.db.all_user_ids(), make)

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
                await state.update_data(new_user=False)
                await self.send_hello(c.message.chat.id, uid, c.from_user.first_name, lang,
                                      new or bool(data.get("new_user")))
            else:
                await c.message.answer(t(lang, "lang_set"), reply_markup=menu(lang))

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

        @r.message(F.text.in_(variants("btn_fund")))
        @r.message(Command("news"))
        async def fundamental(m: Message):
            lang = await self.lang_of(m.from_user.id)
            await m.answer(t(lang, "news_wait"))
            try:
                await self.send_long(m.chat.id, await self.news.digest(lang))
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
            lang = await self.lang_of(m.from_user.id)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "btn_lang"), callback_data="lang:menu")]])
            await m.answer(t(lang, "profile", id=m.from_user.id, status=await self.sub_status(m.from_user.id, lang),
                             language=t(lang, "lang_name")), reply_markup=kb)

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
        ]
        try:
            await self.dp.start_polling(self.bot)
        finally:
            for task in tasks:
                task.cancel()
            await self.provider.close()
            await self.db.close()
