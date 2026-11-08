import asyncio
import re
import os
import sqlite3
import tempfile
import unittest

from goldbot import bot as botmod
from goldbot.db import DB
from goldbot.engine import NewSignal, format_signal
from goldbot.i18n import LANGS, per_lang, t
from goldbot.live_strategy import STRATEGIES
from goldbot.lots import fmt_usd, lot_for, money, parse_capital


class LotMathTests(unittest.TestCase):
    def test_risk_2_percent(self):
        # стоп 100 пипсов = $10 на 0.01 лота → 2% риска: 0.01 лота на каждые $500
        self.assertEqual(lot_for(50, "risk", 2), 0.01)
        self.assertEqual(lot_for(499, "risk", 2), 0.01)
        self.assertEqual(lot_for(1000, "risk", 2), 0.02)
        self.assertEqual(lot_for(2600, "risk", 2), 0.05)
        self.assertEqual(lot_for(400, "risk", 5), 0.02)

    def test_owner_table(self):
        for cap, lot in ((50, 0.01), (100, 0.02), (200, 0.03), (300, 0.04), (450, 0.05)):
            self.assertEqual(lot_for(cap, "table"), lot)

    def test_money_and_parse(self):
        self.assertEqual(money(0.02, 100), 20)
        self.assertEqual(money(0.01, 200), 20)
        self.assertEqual(fmt_usd(1520.0), "1 520")
        for s, v in (("150", 150), ("$1 000", 1000), ("1,500", 1500), ("250.5$", 250.5), ("300 долларов", 300)):
            self.assertEqual(parse_capital(s), v)
        for s in ("abc", "0", "📊 Сигнал", ""):
            self.assertIsNone(parse_capital(s))


class CaptionTests(unittest.TestCase):
    def test_lot_block_in_signal_caption(self):
        st = STRATEGIES["combo"]
        for lang in LANGS:
            base = format_signal(st, 1, 2900, 2890, 2920, 100, 200, "08.11.2026 12:00", lang)
            for cap in (None, 100, 1000, 25000):
                cap_text = botmod.signal_caption(lang, base, cap, 1, 2900)
                visible = re.sub(r"<[^>]+>", "", cap_text)
                self.assertLessEqual(len(visible), 1024, (lang, cap))  # лимит подписи к фото
                self.assertIn("2903.00", cap_text)  # до какой цены входить (30 пипсов)
        ru = botmod.lot_text("ru", 1000)
        self.assertIn("0.02", ru)
        self.assertIn("−$20 (2%)", ru)
        self.assertNotIn("⚠️", ru)
        self.assertIn("⚠️", botmod.lot_text("ru", 100))  # $100: даже 0.01 — это 10%


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_photo(self, uid, photo, caption=None, **kw):
        self.sent.append((uid, caption))

    async def send_message(self, uid, text, **kw):
        self.sent.append((uid, text))


class FlowTests(unittest.TestCase):
    def test_signal_then_tp_updates_balance(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                for uid in (1, 2, 3):
                    await db.add_user(uid, None, None, 3)
                await db.set_capital(1, 1000)
                await db.set_capital(2, 500)
                await db.set_lang(2, "en")  # у 3 капитала нет

                app = botmod.App.__new__(botmod.App)
                app.db, app.bot = db, FakeBot()

                class Eng:
                    last_df = None

                    def df_for(self, key=None):
                        return None
                app.engine = Eng()
                st = STRATEGIES["combo"]
                sid = await db.add_signal("combo", 1, 2900, 2890, 2920)
                rendered = []
                s = NewSignal(sid, 1, 2900, 2890, 2920, b"PNG",
                              per_lang(lambda lang: format_signal(st, 1, 2900, 2890, 2920, 100, 200, "now", lang)),
                              lambda **kw: rendered.append(kw) or b"PNG2")
                await app.broadcast_signal(s)
                caps = dict(app.bot.sent)
                self.assertIn("0.02", caps[1])
                self.assertIn("Your lot: 0.01", caps[2])
                self.assertIn("/capital", caps[3])
                self.assertEqual({r["lot"] for r in rendered}, {"LOT 0.02", "LOT 0.01"})
                self.assertEqual(await db.signal_lots(sid), {1: 0.02, 2: 0.01, 3: 0})

                app.bot.sent.clear()
                sig = (await db.open_signals())[0]
                await db.close_signal(sid, "tp")
                await app.broadcast_close(sig, "tp", 2920)
                msgs = dict(app.bot.sent)
                self.assertIn("+$40", msgs[1])
                self.assertIn("$1 040", msgs[1])
                self.assertIn("$520", msgs[2])
                self.assertNotIn("💼", msgs[3])
                caps = await db.user_capitals()
                self.assertEqual((caps[1], caps[2]), (1040, 520))

                await db.add_capital(2, -10000)  # не уходим в минус
                self.assertEqual((await db.user_capitals())[2], 0)
                await db.close()
        asyncio.run(go())

    def test_late_warning_and_day_stop(self):
        from goldbot.engine import SignalEngine
        import pandas as pd

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                late, closed, days = [], [], []

                async def on_late(s, price, moved):
                    late.append((s["id"], round(moved)))

                async def on_close(s, status, price):
                    closed.append(status)

                async def on_day(n):
                    days.append(n)

                async def noop(*a):
                    pass

                eng = SignalEngine(db, None, "combo", 100, 200, "Asia/Tashkent", noop, on_close,
                                   on_late, 30, on_day, 2)
                a = await db.add_signal("combo", 1, 2900, 2890, 2920)
                await eng.check_open(2902)            # +20 пипсов — ещё можно входить
                await eng.check_open(2903.5)          # +35 — опоздали
                await eng.check_open(2904)            # второй раз не шлём
                self.assertEqual(late, [(a, 35)])
                await eng.check_open(2889)            # стоп №1
                b = await db.add_signal("combo", -1, 2890, 2900, 2870)
                self.assertFalse(await eng.day_closed())
                await eng.check_open(2901)            # стоп №2 подряд → день закрыт
                self.assertEqual(closed, ["sl", "sl"])
                self.assertEqual(days, [2])
                self.assertTrue(await eng.day_closed())
                self.assertFalse(await eng.day_closed(pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=1)))
                self.assertTrue(b)
                await db.close()
        asyncio.run(go())

    def test_day_closed_message_has_capital(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                await db.add_user(1, None, None, 3)
                await db.add_user(2, None, None, 3)
                await db.set_capital(1, 980)
                app = botmod.App.__new__(botmod.App)
                app.db, app.bot = db, FakeBot()
                await app.broadcast_day_closed(2)
                msgs = dict(app.bot.sent)
                self.assertIn("Торговый день закрыт", msgs[1])
                self.assertIn("$980", msgs[1])
                self.assertNotIn("💰", msgs[2])
                await db.close()
        asyncio.run(go())

    def test_decline_skips_result_and_stats(self):
        from goldbot.chart import render_stats

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                for uid in (1, 2):
                    await db.add_user(uid, None, None, 3)
                    await db.set_capital(uid, 1000)
                sid = await db.add_signal("combo", 1, 2900, 2890, 2920)
                await db.add_signal_lot(sid, 1, 0.02)
                await db.add_signal_lot(sid, 2, 0.02)
                await db.set_decision(sid, 2, True)        # 2 нажал «Отклонить»
                await db.set_decision(sid, 1, False)
                self.assertEqual(await db.signal_lots(sid), {1: 0.02})
                app = botmod.App.__new__(botmod.App)
                app.db, app.bot = db, FakeBot()

                class Eng:
                    last_df = None

                    def df_for(self, key=None):
                        return None
                app.engine = Eng()
                sig = await db.get_signal(sid)
                await db.close_signal(sid, "sl")
                await app.broadcast_close(sig, "sl", 2889)
                msgs = dict(app.bot.sent)
                self.assertIn("$980", msgs[1])
                self.assertNotIn(2, msgs)                  # отклонившему результат не шлём
                self.assertEqual((await db.user_capitals())[2], 1000)

                await db.add_signal("combo", -1, 2950, 2960, 2930)
                rows = await db.last_signals(100)
                text = botmod.stats_text("ru", rows, "Asia/Tashkent")
                self.assertIn("Винрейт: <b>0%</b>", text)
                self.assertIn("Stop Loss: выход 2890.00", text)
                self.assertIn("В работе", text)
                self.assertTrue(render_stats(rows, "uz", "Asia/Tashkent").startswith(b"\x89PNG"))
                await db.close()
        asyncio.run(go())

    def test_market_open_and_close_messages(self):
        import pandas as pd
        from goldbot.engine import next_open
        ts = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
        self.assertEqual(next_open(ts("2026-11-10 22:30")), ts("2026-11-10 23:00"))  # вт перерыв → через час
        self.assertEqual(next_open(ts("2026-11-06 22:30")), ts("2026-11-08 23:00"))  # пт вечер → вс 18:00 NY

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                await db.add_user(1, None, None, 3)
                app = botmod.App.__new__(botmod.App)
                app.db, app.bot = db, FakeBot()
                await app.market_status(ts("2026-11-06 21:00"))   # первый запуск — молчим
                await app.market_status(ts("2026-11-06 21:30"))
                self.assertEqual(app.bot.sent, [])
                await app.market_status(ts("2026-11-06 22:01"))   # пятница 17:01 NY — закрыт на выходные
                await app.market_status(ts("2026-11-08 23:01"))   # воскресенье 18:01 NY — открыт
                await app.market_status(ts("2026-11-10 22:01"))   # вт перерыв
                texts = [x[1] for x in app.bot.sent]
                self.assertIn("на выходные", texts[0])
                self.assertIn("09.11 04:00", texts[0])           # по Ташкенту
                self.assertIn("открыт", texts[1])
                self.assertIn("ежедневный перерыв", texts[2])
                await db.close()
        asyncio.run(go())

    def test_old_database_gets_capital_column(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "t.db")
                con = sqlite3.connect(path)
                con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, "
                            "joined_at TEXT NOT NULL, trial_until TEXT NOT NULL, paid_until TEXT, "
                            "blocked INTEGER NOT NULL DEFAULT 0, lang TEXT)")
                con.execute("INSERT INTO users VALUES (5, 'a', 'A', '2026-01-01', '2026-01-04', NULL, 0, 'ru')")
                con.commit()
                con.close()
                db = DB(path)
                await db.connect()
                self.assertIsNone((await db.get_user(5))["capital"])
                await db.set_capital(5, 300)
                self.assertEqual(await db.user_capitals(), {5: 300})
                await db.close()
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
