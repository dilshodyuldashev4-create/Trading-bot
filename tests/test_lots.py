import asyncio
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
                cap_text = botmod.with_lot(base, botmod.lot_text(lang, cap))
                self.assertLessEqual(len(cap_text), 1024, (lang, cap))  # лимит подписи к фото
                self.assertTrue(cap_text.rstrip().endswith("</i>"))
        ru = botmod.lot_text("ru", 1000)
        self.assertIn("0.02", ru)
        self.assertIn("−$20 (2%)", ru)
        self.assertNotIn("⚠️", ru)
        self.assertIn("⚠️", botmod.lot_text("ru", 100))  # $100: даже 0.01 — это 10%


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_photo(self, uid, photo, caption=None):
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
                self.assertEqual(await db.signal_lots(sid), {1: 0.02, 2: 0.01})

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
