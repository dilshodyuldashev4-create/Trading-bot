"""Telegram-бот: меню, подписка (Click / Payme или вручную), пробный период, админ-панель, рассылка сигналов."""
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
from .market import make_provider
from .news import NewsService

log = logging.getLogger(__name__)

BTN_SIGNAL = "📊 Сигнал"
BTN_FUND = "📰 Фундаментальные новости"
BTN_CAL = "🗓 Календарь новостей"
BTN_SUB = "💎 Подписка"
BTN_PROFILE = "👤 Профиль"

MENU = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [KeyboardButton(text=BTN_SIGNAL)],
    [KeyboardButton(text=BTN_FUND), KeyboardButton(text=BTN_CAL)],
    [KeyboardButton(text=BTN_SUB), KeyboardButton(text=BTN_PROFILE)],
])

ADMIN_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📈 Статистика", callback_data="adm:stats"),
     InlineKeyboardButton(text="📣 Рассылка", callback_data="adm:broadcast")],
    [InlineKeyboardButton(text="👥 Подписчики (CSV)", callback_data="adm:export"),
     InlineKeyboardButton(text="🧾 Последние сигналы", callback_data="adm:signals")],
    [InlineKeyboardButton(text="🎁 Выдать / забрать подписку", callback_data="adm:granthelp")],
])

PAID_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="✅ Я оплатил", callback_data="paid")],
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
        photo = BufferedInputFile(s.image, filename=f"signal_{s.id}.png")
        n = await self.broadcast(uids, lambda u: self.bot.send_photo(u, photo, caption=s.text))
        log.info("signal #%s sent to %s users", s.id, n)

    async def broadcast_close(self, s: dict, status: str, price: float) -> None:
        """Итог сигнала — всем участникам бота (подписчикам и тем, у кого доступ закончился)."""
        side = "BUY" if s["direction"] == 1 else "SELL"
        if status == "tp":
            head = f"✅ <b>Сигнал #{s['id']} {side} закрыт по Take Profit</b>\n💰 Результат: <b>+{config.tp_pips:.0f} пипсов</b>"
            level = s["tp"]
        else:
            head = f"❌ <b>Сигнал #{s['id']} {side} закрыт по Stop Loss</b>\n📉 Результат: −{config.sl_pips:.0f} пипсов"
            level = s["sl"]
        st = await self.db.stats()
        closed = st["tp"] + st["sl"]
        text = (f"{head}\n\n📍 Вход: {s['entry']:.2f}\n🏁 Выход: {level:.2f}\n"
                f"🛑 SL {s['sl']:.2f} · 🎯 TP {s['tp']:.2f}\n\n"
                f"📊 Статистика бота: {st['tp']} TP / {st['sl']} SL"
                + (f" (винрейт {100 * st['tp'] / closed:.0f}%)" if closed else ""))
        cta = "\n\n💎 Чтобы получать сигналы, оформите подписку: /subscribe"
        image = None
        if self.engine.last_df is not None:
            try:
                image = render_signal(self.engine.last_df, s["direction"], s["entry"], s["sl"], s["tp"],
                                      f"XAUUSD · сигнал #{s['id']} · {'TAKE PROFIT' if status == 'tp' else 'STOP LOSS'}",
                                      tz=config.display_tz)
            except Exception:  # noqa: BLE001
                log.exception("close chart")
        active = set(await self.db.active_user_ids())

        def make(u: int):
            body = text if u in active else text + cta
            if image:
                return self.bot.send_photo(u, BufferedInputFile(image, f"result_{s['id']}.png"), caption=body)
            return self.bot.send_message(u, body)

        await self.broadcast(await self.db.all_user_ids(), make)

    async def broadcast_text_all(self, text: str) -> None:
        await self.broadcast(await self.db.all_user_ids(), lambda u: self.bot.send_message(u, text))

    def is_admin(self, uid: int) -> bool:
        return uid in config.admin_ids

    async def sub_status(self, uid: int) -> str:
        u = await self.db.get_user(uid)
        if not u:
            return "Нажмите /start"
        if self.db.is_paid(u):
            return f"💎 Подписка активна до {self.fmt_dt(u['paid_until'])}"
        if self.db.has_access(u):
            return f"🎁 Бесплатный период до {self.fmt_dt(u['trial_until'])}"
        return "⛔️ Бесплатный период закончился. Оформите подписку, чтобы получать сигналы."

    @staticmethod
    def price_str() -> str:
        return f"{config.sub_price_uzs:,}".replace(",", " ") + " сум"

    def pay_text(self) -> str:
        text = f"💎 Подписка: <b>{self.price_str()}</b> за {config.sub_days} дней.\n\n"
        if config.pay_details:
            text += f"Как оплатить:\n{html.escape(config.pay_details)}\n\n"
        return text + "После оплаты нажмите «✅ Я оплатил» — администратор проверит и включит подписку."

    async def send_pay_info(self, chat_id: int) -> None:
        if config.payment_token:
            # Click / Payme через Telegram Payments: оплата картой Uzcard/Humo прямо в чате
            await self.bot.send_invoice(
                chat_id, title=f"Подписка на сигналы XAUUSD — {config.sub_days} дней",
                description="Автоматические сигналы по золоту с графиком, входом, SL и TP.",
                payload="sub", currency="UZS", provider_token=config.payment_token,
                prices=[LabeledPrice(label=f"{config.sub_days} дней", amount=config.sub_price_uzs * 100)])
        else:
            await self.bot.send_message(chat_id, self.pay_text(), reply_markup=PAID_KB)

    # ── handlers ─────────────────────────────────────────────────────────────
    def _register(self) -> None:
        r = self.router

        @r.message(CommandStart())
        async def start(m: Message):
            new = await self.db.add_user(m.from_user.id, m.from_user.username, m.from_user.first_name,
                                         config.trial_days)
            hello = (f"👋 Привет, {m.from_user.first_name or 'трейдер'}!\n\n"
                     "Я бот сигналов по <b>золоту (XAUUSD)</b>.\n"
                     "• 📊 <b>Сигнал</b> — анализ рынка и ожидаемый сетап; подтверждённые сигналы приходят сами\n"
                     "• 📰 <b>Фундаментальные новости</b> — коротко, как новости влияют на золото и доллар\n"
                     "• 🗓 <b>Календарь новостей</b> — CPI, NFP, FOMC: время и влияние\n\n")
            if new:
                hello += f"🎁 Вам открыт <b>бесплатный доступ на {config.trial_days} дня</b>: сигналы будут приходить автоматически."
            else:
                hello += await self.sub_status(m.from_user.id)
            await m.answer(hello, reply_markup=MENU)

        @r.message(F.text == BTN_SIGNAL)
        @r.message(Command("signal"))
        async def signal(m: Message):
            u = await self.db.get_user(m.from_user.id)
            if not u:
                await self.db.add_user(m.from_user.id, m.from_user.username, m.from_user.first_name,
                                       config.trial_days)
                u = await self.db.get_user(m.from_user.id)
            if not self.db.has_access(u):
                await m.answer("⛔️ Бесплатный период закончился. Сигналы доступны по подписке.")
                await self.send_pay_info(m.chat.id)
                return
            await m.answer("🔎 Анализирую рынок…")
            try:
                text = await self.engine.expected()
            except Exception:  # noqa: BLE001
                log.exception("expected setup")
                text = "Не удалось получить котировки, попробуйте через минуту."
            price = f"\n\n💰 Цена сейчас: <b>{self.engine.last_price:.2f}</b>" if self.engine.last_price else ""
            opened = await self.db.open_signals()
            active = ""
            if opened:
                s = opened[-1]
                active = (f"\n\n📌 Открытый сигнал #{s['id']}: {'BUY' if s['direction'] == 1 else 'SELL'} "
                          f"от {s['entry']:.2f}, SL {s['sl']:.2f}, TP {s['tp']:.2f}")
            await m.answer(f"📊 <b>Анализ XAUUSD</b>\n\n{text}{price}{active}")

        @r.message(F.text == BTN_FUND)
        @r.message(Command("news"))
        async def fundamental(m: Message):
            await m.answer("⏳ Собираю свежие новости…")
            try:
                await self.send_long(m.chat.id, await self.news.digest())
            except Exception:  # noqa: BLE001
                log.exception("news")
                await m.answer("Не удалось загрузить новости, попробуйте позже.")

        @r.message(F.text == BTN_CAL)
        @r.message(Command("calendar"))
        async def calendar(m: Message):
            await self.send_long(m.chat.id, await econ_calendar.render(self.db, config.display_tz))

        @r.message(F.text == BTN_SUB)
        @r.message(Command("subscribe"))
        async def subscribe(m: Message):
            await m.answer(await self.sub_status(m.from_user.id))
            await self.send_pay_info(m.chat.id)

        @r.message(F.text == BTN_PROFILE)
        async def profile(m: Message):
            await m.answer(f"🆔 {m.from_user.id}\n{await self.sub_status(m.from_user.id)}")

        @r.pre_checkout_query()
        async def pre_checkout(q: PreCheckoutQuery):
            await q.answer(ok=True)

        @r.message(F.successful_payment)
        async def paid(m: Message):
            p = m.successful_payment
            await self.db.add_payment(m.from_user.id, p.total_amount // 100, p.currency,
                                      p.telegram_payment_charge_id)
            until = await self.db.extend_paid(m.from_user.id, config.sub_days)
            await m.answer(f"✅ Спасибо! Подписка активна до {self.fmt_dt(until)}.", reply_markup=MENU)
            for a in config.admin_ids:
                await self._send(a, lambda a=a: self.bot.send_message(
                    a, f"💰 Оплата {p.total_amount // 100} {p.currency} от {m.from_user.id} @{m.from_user.username}"))

        @r.callback_query(F.data == "paid")
        async def i_paid(c: CallbackQuery):
            u = c.from_user
            name = html.escape(u.full_name or "")
            uname = f" @{u.username}" if u.username else ""
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=f"🎁 Выдать {config.sub_days} дней",
                                     callback_data=f"adm:give:{u.id}:{config.sub_days}"),
                InlineKeyboardButton(text="❌ Не пришло", callback_data=f"adm:nopay:{u.id}"),
            ]])
            for a in config.admin_ids:
                await self._send(a, lambda a=a: self.bot.send_message(
                    a, f"💰 <b>{name}</b>{uname} (ID <code>{u.id}</code>) говорит, что оплатил подписку.\n"
                       f"Проверьте поступление и нажмите кнопку.", reply_markup=kb))
            await c.answer()
            await c.message.answer("🙏 Спасибо! Администратор проверит оплату и включит подписку. "
                                   "Вы получите сообщение, как только доступ откроется.")

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
            if action.startswith("give:"):
                _, uid, days = action.split(":")
                uid, days = int(uid), int(days)
                until = await self.db.extend_paid(uid, days)
                await c.message.edit_reply_markup(reply_markup=None)
                await c.message.answer(f"✅ {uid}: подписка до {self.fmt_dt(until)}")
                await self._send(uid, lambda: self.bot.send_message(
                    uid, f"✅ Оплата получена! Подписка активна до {self.fmt_dt(until)}.", reply_markup=MENU))
            elif action.startswith("nopay:"):
                uid = int(action.split(":")[1])
                await c.message.edit_reply_markup(reply_markup=None)
                await c.message.answer(f"Ок, {uid}: подписка не выдана")
                await self._send(uid, lambda: self.bot.send_message(
                    uid, "⚠️ Оплата пока не найдена. Если вы уже перевели деньги, напишите администратору."))
            elif action == "stats":
                s = await self.db.stats()
                closed = s["tp"] + s["sl"]
                wr = f"{100 * s['tp'] / closed:.1f}%" if closed else "—"
                await c.message.answer(
                    f"👥 Всего: {s['total']} (заблокировали: {s['blocked']})\n"
                    f"💎 Платных: {s['paid']}\n🎁 На пробном: {s['trial']}\n"
                    f"💰 Оплачено через Click/Payme: {s['revenue']:,} сум\n\n".replace(",", " ") +
                    f"📊 Сигналов: {s['signals']}, TP: {s['tp']}, SL: {s['sl']}, винрейт: {wr}")
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
            await m.answer("Отменено", reply_markup=MENU)

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
            await self._send(uid, lambda: self.bot.send_message(
                uid, f"🎁 Вам выдана подписка до {self.fmt_dt(until)}"))

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
                await news_alerts.process(self.db, config.display_tz, self.broadcast_text_all, fetch)
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
                    await self._send(uid, lambda u=uid: self.bot.send_message(
                        u, "⏳ Бесплатный период заканчивается через час. "
                           "Чтобы и дальше получать сигналы, оформите подписку: 💎 Подписка"))
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
            for t in tasks:
                t.cancel()
            await self.provider.close()
            await self.db.close()
