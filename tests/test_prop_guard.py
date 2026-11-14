"""Защита проп-счёта: стоп дня после Stop Loss и меньший риск в просадке."""
import asyncio
import tempfile
import unittest
from datetime import datetime, timezone

from goldbot import autotrade as at
from goldbot import prop as pr
from tests.test_autotrade import make_db
from tests.test_prop import PropApi


def run(coro):
    return asyncio.run(coro)


class GuardMathTests(unittest.TestCase):
    def test_scaled_risk(self):
        self.assertEqual(pr.scaled_risk(0.5, 25_000, 25_000), 0.5)
        self.assertEqual(pr.scaled_risk(0.5, 24_600, 25_000), 0.5)        # −1.6 % — ещё обычный риск
        self.assertEqual(pr.scaled_risk(0.5, 24_500, 25_000), 0.125)      # −2 % — риск в 4 раза меньше
        self.assertEqual(pr.scaled_risk(1.0, 24_000, 25_000, 2, 0.5), 0.5)
        self.assertEqual(pr.scaled_risk(0.5, 20_000, 25_000, 0), 0.5)     # 0 — выключено

    def test_day_start_is_athens_midnight(self):
        # 14.11.2026 01:30 UTC = 03:30 по Афинам (GMT+2): день начался в 22:00 UTC 13.11
        t = datetime(2026, 11, 14, 1, 30, tzinfo=timezone.utc)
        self.assertEqual(pr.day_start(t).astimezone(timezone.utc), datetime(2026, 11, 13, 22, 0, tzinfo=timezone.utc))


class GuardTraderTests(unittest.TestCase):
    def test_stop_loss_stops_the_day_and_new_day_resumes(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = PropApi(equity=25_000.0)
                tr = at.AutoTrader(db, api, poll=0, retry_delays=(0, 0))
                await tr.connect(1, "mt5", "FundedNext-Server", "123", "pw",
                                 prop={"plan": "2step", "stage": "phase1", "size": 25_000})
                s1 = await db.add_signal("squeeze", 1, 2650, 2630, 2680)
                s2 = await db.add_signal("donchian", 1, 2650, 2630, 2680)
                self.assertTrue((await tr.open_signal(s1, 1, 20.0, 30.0, uids={1}))[0].ok)
                self.assertTrue((await tr.open_signal(s2, 1, 20.0, 30.0, uids={1}))[0].ok)
                # тейк — день продолжается
                await db.close_signal(s2, "tp")
                self.assertEqual(await tr.prop_check(), [])
                # стоп — до полуночи FundedNext новых сделок нет, открытые сделки не трогаем
                await db.close_signal(s1, "sl")
                api.pos = api.pos[:1]
                events = await tr.prop_check()
                self.assertEqual([e["kind"] for e in events], ["loss_stop"])
                self.assertEqual((await db.get_trade_account(1))["prop_halt"], "loss")
                self.assertEqual(len(api.pos), 1)
                self.assertEqual(await tr.prop_check(), [])                 # сообщение — один раз
                s3 = await db.add_signal("amd", 1, 2650, 2630, 2680)
                self.assertEqual(await tr.open_signal(s3, 1, 20.0, 30.0, uids={1}), [])
                # новый торговый день — снова торгует (вчерашний стоп не считается)
                await db.conn.execute("UPDATE signals SET closed_at='2000-01-01T00:00:00+00:00'")
                await db.update_prop_state(1, prop_day="2000-01-01")
                events = await tr.prop_check()
                self.assertIn("new_day", [e["kind"] for e in events])
                self.assertEqual((await db.get_trade_account(1))["prop_halt"], "")
                await db.close()
        run(go())

    def test_stop_loss_before_check_blocks_next_open(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = PropApi(equity=25_000.0)
                tr = at.AutoTrader(db, api, poll=0, retry_delays=(0, 0))
                await tr.connect(1, "mt5", "FundedNext-Server", "123", "pw",
                                 prop={"plan": "2step", "stage": "phase1", "size": 25_000})
                s1 = await db.add_signal("squeeze", 1, 2650, 2630, 2680)
                await tr.open_signal(s1, 1, 20.0, 30.0, uids={1})
                await db.close_signal(s1, "sl")
                # сигнал пришёл раньше, чем проверка счёта заметила стоп: сделку всё равно не открываем
                s2 = await db.add_signal("amd", 1, 2650, 2630, 2680)
                res = await tr.open_signal(s2, 1, 20.0, 30.0, uids={1})
                self.assertEqual(res[0].error, "PROP_DAY_LOSS")
                self.assertEqual((await db.get_trade_account(1))["prop_halt"], "loss")
                # выключено (PROP_DAY_LOSSES=0) — торгует дальше
                await db.update_prop_state(1, prop_halt="")
                tr.prop_day_losses = 0
                s3 = await db.add_signal("liq_m15", 1, 2650, 2630, 2680)
                self.assertTrue((await tr.open_signal(s3, 1, 20.0, 30.0, uids={1}))[0].ok)
                await db.close()
        run(go())

    def test_risk_drops_in_drawdown(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = PropApi(equity=25_000.0)
                tr = at.AutoTrader(db, api, poll=0, retry_delays=(0, 0))
                await tr.connect(1, "mt5", "FundedNext-Server", "123", "pw",
                                 prop={"plan": "2step", "stage": "phase1", "size": 25_000})
                s1 = await db.add_signal("squeeze", 1, 2650, 2645, 2660)
                # стоп $5: обычный риск 0.5 % = $125 → 0.25 лота
                self.assertEqual((await tr.open_signal(s1, 1, 5.0, 7.5, uids={1}))[0].volume, 0.25)
                api.pos = []
                # баланс −2.4 % (вчерашние убытки, сегодня новый день): риск 0.125 % = $30 → 0.06 лота
                api.balance = api.equity = 24_400.0
                await db.update_prop_state(1, prop_day="2000-01-01")
                s2 = await db.add_signal("amd", 1, 2650, 2645, 2660)
                self.assertEqual((await tr.open_signal(s2, 1, 5.0, 7.5, uids={1}))[0].volume, 0.06)
                await db.close()
        run(go())

    def test_rules_and_events_mention_guard(self):
        from goldbot.bot import App, trade_error_text

        sent = []

        class FakeBot:
            async def send_message(self, chat_id, text, **kw):
                sent.append(text)

        app = App.__new__(App)
        app.bot = FakeBot()

        async def lang_of(uid):
            return "ru"

        async def _send(uid, factory):
            await factory()
            return True

        app.lang_of, app._send = lang_of, _send

        class FakeDB:
            async def trade_accounts(self):
                return []

        app.db = FakeDB()

        async def go():
            await app.prop_rules(1, "ru", "2step", "phase1", 25_000)
            await app.prop_events([{"uid": 1, "kind": "loss_stop"}])
        asyncio.run(go())
        rules, stop = sent
        self.assertIn("после 1-го Stop Loss", rules)
        self.assertIn("с 0.5% до 0.125%", rules)
        self.assertIn("$500", rules)                         # 2 % от $25 000
        self.assertIn("Stop Loss", stop)
        acc = {"prop_plan": "2step", "prop_size": 25_000, "prop_day_balance": 25_000, "prop_peak": 25_000,
               "prop_stage": "phase1", "equity": 24_900, "prop_halt": "loss"}
        self.assertIn("Сегодня был Stop Loss", app.prop_status(acc, "ru"))
        for lang in ("ru", "en", "uz"):
            self.assertTrue(trade_error_text(lang, "PROP_DAY_LOSS"))


if __name__ == "__main__":
    unittest.main()
