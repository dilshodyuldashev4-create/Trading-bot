import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone

from goldbot import prop_signals as ps
from goldbot.db import DB
from goldbot.engine import NewSignal, format_signal
from goldbot.i18n import per_lang
from goldbot.live_strategy import STRATEGIES
from tests.test_channel import make_app

CFG = dict(risk_pct=0.5, strong_pct=1.0, strong=False, guard_pct=0.5, cap=3.0, max_trade=1.0, dd_pct=2.0,
           dd_mult=0.25)


def sub(**kw):
    base = {"user_id": 1, "plan": "2step", "stage": "phase1", "size": 10_000.0, "balance": 10_000.0,
            "day_balance": 10_000.0, "peak": 10_000.0, "days": 0, "enabled": 1, "only_prop": 0}
    return {**base, **kw}


class PureTests(unittest.TestCase):
    def test_lot_by_account_and_rules(self):
        # 0.5 % от $10 000 = $50, стоп $20 на 1 унцию → 0.02 лота
        self.assertEqual(ps.plan_trade(sub(), [], 20.0, **CFG)["lot"], 0.02)
        # $100 000: $500 → 0.25
        self.assertEqual(ps.plan_trade(sub(size=100_000.0, balance=100_000.0, day_balance=100_000.0,
                                           peak=100_000.0), [], 20.0, **CFG)["lot"], 0.25)
        # цель этапа (+8 %) уже есть — минимальный лот
        p = ps.plan_trade(sub(balance=10_800.0), [], 20.0, **CFG)
        self.assertEqual((p["lot"], p["reason"]), (0.01, "goal"))
        # баланс −2 %: риск ×0.25 → $12.5 → при стопе $5 лот 0.02
        self.assertEqual(ps.plan_trade(sub(balance=9_800.0), [], 5.0, **CFG)["lot"], 0.02)
        # открытые сделки уже держат 1.5 % — новой нет
        trades = [{"lot": 0.075, "sl": 1980.0, "entry": 2000.0, "direction": 1}]
        self.assertEqual(ps.plan_trade(sub(), trades, 20.0, **CFG)["lot"], 0.0)

    def test_take_profit_and_hits(self):
        self.assertEqual(ps.prop_tp(2000, 1990, 2030, 1, 1.0, 1.5), 2015)
        self.assertEqual(ps.prop_tp(2000, 2010, 1970, -1, 1.0, 1.5), 1985)
        self.assertEqual(ps.prop_tp(2000, 1990, 2030, 1, 0.0, 1.5), 2030)   # фиксация выключена — тейк сигнала
        tr = {"direction": 1, "entry": 2000.0, "sl": 1990.0, "tp": 2015.0}
        self.assertEqual(ps.hit(tr, 1989.9), "sl")
        self.assertEqual(ps.hit(tr, 2015.0), "tp")
        self.assertIsNone(ps.hit(tr, 2005.0))
        self.assertAlmostEqual(ps.trade_pips(tr, "tp"), 150)

    def test_state_and_trading_days(self):
        t = datetime(2026, 11, 24, 10, tzinfo=timezone.utc)
        upd = ps.apply_result(sub(), 50.0, t, "Europe/Athens")
        self.assertEqual((upd["balance"], upd["days"]), (10_050.0, 1))
        again = ps.apply_result(sub(**upd), -20.0, t, "Europe/Athens")
        self.assertNotIn("days", again)   # тот же день — торговых дней не прибавляется
        st = ps.state(sub(**upd), risk_pct=0.5, cap=3.0, max_trade=1.0, dd_pct=2.0, dd_mult=0.25)
        self.assertAlmostEqual(st["to_goal"], 750.0)
        self.assertAlmostEqual(st["total_floor"], 9_000.0)
        self.assertAlmostEqual(st["day_left"], 350.0)   # дневной стоп бота 3 % = $300 от баланса начала дня 10 000
        self.assertEqual((st["risk_pct"], st["risk_usd"]), (0.5, 50.0))
        funded = ps.state(sub(stage="funded"), risk_pct=0.5, cap=3.0, max_trade=1.0, dd_pct=2.0, dd_mult=0.25)
        self.assertIsNone(funded["goal"])


class FlowTests(unittest.TestCase):
    def test_separate_stream_day_stop_and_balance(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                for uid in (1, 2, 3):
                    await db.add_user(uid, "u", "U")
                    await db.set_lang(uid, "ru")
                await db.save_prop_sub(1, "2step", "phase1", 10_000)
                await db.update_prop_sub(1, only_prop=1)          # только проп-сигналы
                await db.save_prop_sub(3, "1step", "phase1", 25_000)  # проп + обычные
                app = make_app(db)
                st = STRATEGIES["combo"]

                async def signal(entry, sl, tp):
                    sid = await db.add_signal("combo", 1, entry, sl, tp)
                    s = NewSignal(sid, 1, entry, sl, tp, b"PNG",
                                  per_lang(lambda lang: format_signal(st, 1, entry, sl, tp, 100, 300, "now", lang)))
                    app.bot.sent.clear()
                    await app.broadcast_signal(s)
                    return sid

                sid = await signal(2900, 2890, 2930)
                by = {}
                for chat, text, _ in app.bot.sent:
                    by.setdefault(chat, []).append(text)
                self.assertEqual(len(by[1]), 1)
                self.assertIn("ПРОП-СИГНАЛ", by[1][0])              # только проп-сигнал
                self.assertIn("2915.00", by[1][0])                   # тейк проп-счёта 1.5 стопа
                self.assertIn("0.05", by[1][0])                      # $50 / $10 → 0.05 лота
                self.assertEqual(len(by[3]), 2)                      # и проп, и обычный
                self.assertTrue(all("ПРОП" not in x for x in by[2])) # обычный подписчик — без изменений
                self.assertEqual(len(by[2]), 1)

                app.bot.sent.clear()
                await app.prop_check(2889.0)                         # стоп
                self.assertEqual((await db.get_prop_sub(1))["balance"], 9_950.0)
                msg = [x for x in app.bot.sent if x[0] == 1][0][1]
                self.assertIn("Stop Loss", msg)
                self.assertIn("Торговый день для проп-счёта остановлен", msg)
                self.assertIn("До общего лимита", msg)
                self.assertTrue(await app.ps_day_stopped())

                await signal(2900, 2890, 2930)                       # после стопа — проп-сигналов нет
                chats = [x[0] for x in app.bot.sent]
                self.assertNotIn(1, chats)
                self.assertEqual(chats.count(3), 1)
                self.assertIn(2, chats)

                # итог обычного сигнала тому, кто получает только проп-сигналы, не приходит
                app.bot.sent.clear()
                await db.set_kv("ps_day_stop", "")
                s = await db.get_signal(sid)
                await db.close_signal(sid, "tp")
                await app.broadcast_close(s, "tp", 2930)
                self.assertNotIn(1, [x[0] for x in app.bot.sent])
                await db.close()
        asyncio.run(go())

    def test_target_reached_offers_next_stage(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                await db.add_user(1, "u", "U")
                await db.set_lang(1, "en")
                await db.save_prop_sub(1, "lite", "phase1", 10_000)
                await db.update_prop_sub(1, balance=10_790.0, days=5)
                app = make_app(db)
                await db.add_prop_trade(7, 1, 1, 2000.0, 1990.0, 2015.0, 0.1)
                await app.prop_check(2016.0)                         # +$150 → цель +8 % есть
                text, kw = app.bot.sent[-1][1], app.bot.sent[-1][2]
                self.assertIn("Stage target reached", text)
                self.assertEqual(kw["reply_markup"].inline_keyboard[0][0].callback_data, "ps:next")
                self.assertEqual((await db.get_prop_sub(1))["balance"], 10_940.0)
                await db.close()
        asyncio.run(go())

    def test_only_prop_gets_no_regular_messages(self):
        async def go():
            import pandas as pd
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                for uid in (1, 2):
                    await db.add_user(uid, "u", "U")
                await db.save_prop_sub(1, "2step", "phase1", 10_000)
                await db.update_prop_sub(1, only_prop=1)
                app = make_app(db)
                # серия стопов обычных сигналов: «торговый день закрыт» — только обычным подписчикам
                await app.broadcast_day_closed(3)
                self.assertEqual([x[0] for x in app.bot.sent], [2])
                # итоги дня по обычным сигналам — тоже
                app.bot.sent.clear()
                sid = await db.add_signal("combo", 1, 2900, 2890, 2930)
                await db.close_signal(sid, "sl")
                self.assertTrue(await app.daily_report(pd.Timestamp("2026-11-25 22:10", tz="UTC")))
                self.assertEqual([x[0] for x in app.bot.sent], [2])
                # выключил проп-сигналы — обычные снова приходят
                await db.update_prop_sub(1, enabled=0)
                self.assertEqual(await app.ps_only_uids(), set())
                await db.close()
        asyncio.run(go())

    def test_menu_button_wins_over_waiting_input(self):
        from goldbot import bot as botmod
        from goldbot.i18n import t
        self.assertIn(t("ru", "btn_propsig"), botmod.MENU_TEXTS)
        self.assertIn(t("uz", "btn_auto"), botmod.MENU_TEXTS)


if __name__ == "__main__":
    unittest.main()
