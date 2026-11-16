"""Тренд или боковик (ADX), согласие стратегий, защита от спреда, сверка счетов, живая карточка, прогноз челленджа."""
import asyncio
import os
import tempfile
import unittest
from datetime import timedelta

import numpy as np
import pandas as pd

from goldbot import autotrade as at
from goldbot import prop as pr
from goldbot.db import DB, _iso, now
from goldbot.engine import SignalEngine
from goldbot.indicators import adx
from tests.test_autotrade import FakeApi, make_db, trader
from tests.test_prop import PropApi


def run(coro):
    return asyncio.run(coro)


def frame(trend: float, n: int = 200, noise: float = 1.0, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 2000 + np.cumsum(trend + rng.normal(0, noise, n))
    idx = pd.date_range("2025-03-03", periods=n, freq="15min")
    return pd.DataFrame({"open": close - trend, "high": close + 1.5, "low": close - 1.5, "close": close,
                         "volume": 100}, index=idx)


class AdxAndConfluenceTests(unittest.TestCase):
    def test_adx_strong_trend_vs_range(self):
        self.assertGreater(adx(frame(3.0))[-1], 40)
        self.assertLess(adx(frame(0.0, noise=1.0))[-1], 30)

    def test_engine_filters_breakouts_and_sizes_by_agreement(self):
        eng = SignalEngine.__new__(SignalEngine)
        eng.adx_max, eng.adx_keys, eng.recent = 25.0, ("squeeze", "donchian"), {}
        eng.confluence_min, eng.confluence_single, eng.confluence_strong = 60, 0.75, 1.5

        class St:
            key = "donchian"
        trend = frame(3.0)
        self.assertTrue(eng.adx_filtered(St, trend))
        St.key = "fvg_m15"   # не пробой — фильтр не касается
        self.assertFalse(eng.adx_filtered(St, trend))
        eng.adx_max = 0       # выключено
        St.key = "donchian"
        self.assertFalse(eng.adx_filtered(St, trend))

        bar = pd.Timestamp("2025-03-03 10:00")
        self.assertEqual(eng.size_for("amd", bar, 1), 0.75)           # одна стратегия
        eng.recent["liq_m15"] = (bar - pd.Timedelta(minutes=45), 1)   # другая — в ту же сторону 45 мин назад
        self.assertEqual(eng.size_for("amd", bar, 1), 1.5)
        self.assertEqual(eng.size_for("amd", bar, -1), 0.75)          # в другую сторону — не согласие
        eng.recent["liq_m15"] = (bar - pd.Timedelta(minutes=60), 1)   # час назад — уже не считается
        self.assertEqual(eng.size_for("amd", bar, 1), 0.75)
        eng.recent = {"amd": (bar, 1)}                                # сама с собой не согласие
        self.assertEqual(eng.size_for("amd", bar, 1), 0.75)


class PropOnlySignalsTests(unittest.TestCase):
    def test_prop_only_hidden_from_public_stats(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                a = await db.add_signal("fvg_m15", 1, 2000, 1990, 2030)
                b = await db.add_signal("donchian", 1, 2000, 1990, 2030, prop_only=True, size=1.5)
                await db.close_signal(a, "sl")
                await db.close_signal(b, "sl")
                st = await db.stats()
                self.assertEqual((st["signals"], st["sl"]), (1, 1))
                self.assertEqual([r["id"] for r in await db.last_signals(10)], [a])
                self.assertEqual(await db.closed_since(now() - timedelta(hours=1)), ["sl"])
                self.assertEqual(len(await db.open_signals()), 0)
                self.assertEqual((await db.get_signal(b))["size"], 1.5)
                await db.close()
        run(go())

    def test_prop_only_opens_only_on_prop_and_size_scales_regular_lot(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = PropApi(equity=10_000.0)
                tr = trader(db, api, demo_only=False)
                await tr.connect(1, "mt5", "S", "1", "p")   # обычный счёт
                await tr.connect(2, "mt5", "FundedNext-Server", "2", "p",
                                 prop={"plan": "2step", "stage": "phase1", "size": 10_000})
                res = await tr.open_signal(1, 1, 20.0, 60.0, prop_only=True)
                self.assertEqual([r.uid for r in res], [2])
                # обычный счёт: 2 % от $10 000 = $200 при стопе $20 → 0.1; × 1.5 → 0.15; × 0.75 → 0.07
                res = await tr.open_signal(2, 1, 20.0, 60.0, uids={1}, size=1.5)
                self.assertEqual(res[0].volume, 0.15)
                res = await tr.open_signal(3, 1, 20.0, 60.0, uids={1}, size=0.75)
                self.assertEqual(res[0].volume, 0.07)
                await db.close()
        run(go())


class SpreadApi(FakeApi):
    def __init__(self, spreads, **kw):
        super().__init__(**kw)
        self.spreads = list(spreads)

    async def price(self, acc_id, region, symbol):
        sp = self.spreads.pop(0) if len(self.spreads) > 1 else self.spreads[0]
        return {"bid": self.bid, "ask": self.bid + sp}


class SpreadGuardTests(unittest.TestCase):
    def test_waits_for_normal_spread_then_skips(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                # стоп $20, предел 10 % = $2: сначала $5, потом $0.3 — входим по нормальной цене
                api = SpreadApi([5.0, 0.3], equity=10_000)
                tr = trader(db, api, max_spread_pct=10, spread_wait=10, spread_poll=0.01)
                await tr.connect(1, "mt5", "S", "1", "p")
                res = await tr.open_signal(1, 1, 20.0, 30.0)
                self.assertTrue(res[0].ok, res[0].error)
                self.assertEqual(res[0].price, 2650.3)
                # спред так и не стал нормальным — сделки нет, ошибка SPREAD
                api.spreads = [6.0]
                tr.spread_wait = 0.03
                res = await tr.open_signal(2, 1, 20.0, 30.0)
                self.assertFalse(res[0].ok)
                self.assertEqual(res[0].error, "SPREAD")
                await db.close()
        run(go())


class ReconcileApi(FakeApi):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.pos: dict[str, dict] = {}
        self.fail_next = False

    async def positions(self, acc_id, region):
        return list(self.pos.values())

    async def trade(self, acc_id, region, req):
        self.trades.append((acc_id, req))
        if req["actionType"].startswith("ORDER_TYPE"):
            if self.fail_next:
                self.fail_next = False
                raise at.MetaApiError("requote", "TRADE_RETCODE_REQUOTE", 400)
            pid = str(1000 + len(self.trades))
            self.pos[pid] = {"id": pid, "type": "POSITION_TYPE_BUY" if req["actionType"].endswith("BUY")
                             else "POSITION_TYPE_SELL", "openPrice": self.ask, "stopLoss": req["stopLoss"],
                             "takeProfit": req["takeProfit"], "volume": req["volume"], "comment": req["comment"]}
            return {"stringCode": "TRADE_RETCODE_DONE", "orderId": pid, "positionId": pid}
        if req["actionType"] == "POSITION_MODIFY":
            self.pos[req["positionId"]]["stopLoss"] = req["stopLoss"]
            return {"stringCode": "TRADE_RETCODE_DONE"}
        self.pos.pop(req["positionId"], None)
        return {"stringCode": "TRADE_RETCODE_DONE"}


class ReconcileTests(unittest.TestCase):
    def test_fixes_stop_closes_zombie_and_reopens(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = ReconcileApi(equity=10_000)
                tr = trader(db, api)
                await tr.connect(1, "mt5", "S", "1", "p")
                s1 = await db.add_signal("fvg_m15", 1, 2650.0, 2630.0, 2710.0)
                await tr.open_signal(s1, 1, 20.0, 60.0)
                pid = next(iter(api.pos))
                api.pos[pid]["stopLoss"] = 0          # стоп у брокера пропал
                ev = await tr.reconcile(2650.0)
                self.assertEqual([e["kind"] for e in ev], ["sl_fixed"])
                self.assertEqual(api.pos[pid]["stopLoss"], 2630.3)   # 20 $ от цены входа у брокера
                self.assertEqual(await tr.reconcile(2650.0), [])      # всё в порядке — ничего не делаем

                # сигнал закрылся давно, а сделка осталась — закрываем
                await db.close_signal(s1, "sl")
                await db.conn.execute("UPDATE signals SET closed_at=? WHERE id=?",
                                      (_iso(now() - timedelta(minutes=5)), s1))
                await db.conn.commit()
                ev = await tr.reconcile(2650.0)
                self.assertEqual([e["kind"] for e in ev], ["zombie"])
                self.assertEqual(api.pos, {})

                # сделка не открылась (реквот) — сверка открывает её снова, пока цена у входа
                s2 = await db.add_signal("amd", 1, 2650.0, 2630.0, 2710.0, size=1.5)
                api.fail_next = True
                res = await tr.open_signal(s2, 1, 20.0, 60.0, size=1.5)
                self.assertFalse(res[0].ok)
                ev = await tr.reconcile(2700.0)      # цена ушла к тейку больше чем на 0.3 стопа — поздно
                self.assertEqual(ev, [])
                ev = await tr.reconcile(2652.0)
                self.assertEqual([e["kind"] for e in ev], ["reopened"])
                self.assertEqual(ev[0]["result"].volume, 0.15)        # с тем же множителем лота
                self.assertEqual((await db.get_auto_trade(s2, 1))["status"], "open")
                await db.close()
        run(go())


class CardAndPropTextTests(unittest.TestCase):
    def test_card_status_and_lot_size(self):
        from goldbot import bot as botmod
        s = {"id": 5, "direction": 1, "entry": 2000.0, "sl": 1990.0, "tp": 2030.0, "tp1": 2010.0, "part": 0.5,
             "part_at": None}
        live = botmod.card_status("ru", s, None, 2005.0, "Asia/Tashkent")
        self.assertIn("+0.5R", live)
        self.assertIn("+50 пипсов", live)
        done = botmod.card_status("ru", {**s, "part_at": "x"}, "be", 2000.0, "Asia/Tashkent")
        self.assertIn("Зафиксировано 50%", done)
        self.assertIn("безубыток", done)
        self.assertNotIn("Сделка идёт", done)
        self.assertIn("Stop Loss", botmod.card_status("en", s, "sl", 1990.0, "UTC"))
        one = botmod.lot_plan(1000, 100, 300)["lot"]
        self.assertGreater(botmod.lot_plan(1000, 100, 300, size=1.5)["lot"], one)
        self.assertIn("Сильный сигнал", botmod.lot_text("ru", 1000, 100, 300, size=1.5))
        self.assertNotIn("Сильный сигнал", botmod.lot_text("ru", 1000, 100, 300, size=0.75))

    def test_prop_progress_and_milestones(self):
        a = {"prop_plan": "2step", "prop_stage": "phase1", "prop_size": 10_000}
        self.assertAlmostEqual(pr.progress(a, 10_400), 0.5)
        self.assertEqual(pr.progress_bar(0.5), "▰▰▰▰▰▱▱▱▱▱")
        self.assertIsNone(pr.progress({**a, "prop_stage": "funded"}, 10_400))

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = PropApi(equity=10_000.0)
                tr = at.AutoTrader(db, api, poll=0, retry_delays=(0, 0))
                await tr.connect(1, "mt5", "FundedNext-Server", "1", "p",
                                 prop={"plan": "2step", "stage": "phase1", "size": 10_000})
                api.balance = api.equity = 10_450.0
                ev = await tr.prop_check()
                self.assertEqual([(e["kind"], e.get("pct")) for e in ev], [("milestone", 50)])
                self.assertEqual(await tr.prop_check(), [])          # второй раз не пишем
                api.balance = api.equity = 10_750.0
                ev = await tr.prop_check()
                self.assertEqual([(e["kind"], e.get("pct")) for e in ev], [("milestone", 90)])
                await db.close()
        run(go())

        from goldbot.bot import App
        app = App.__new__(App)
        text = app.prop_status({**a, "prop_day_balance": 10_000, "prop_peak": 10_400, "equity": 10_400,
                                "balance": 10_400}, "ru")
        self.assertIn("▰▰▰▰▰▱▱▱▱▱ 50%", text)
        self.assertIn("около 45 дней", text)


if __name__ == "__main__":
    unittest.main()


class BroadcastCardTests(unittest.TestCase):
    def test_prop_only_not_sent_and_card_updates(self):
        from goldbot.bot import App
        from goldbot.engine import NewSignal

        class Msg:
            def __init__(self, mid):
                self.message_id = mid

        class FakeBot:
            def __init__(self):
                self.photos, self.edits, self.messages = [], [], []

            async def send_photo(self, chat_id, photo, caption=None, **kw):
                self.photos.append((chat_id, caption))
                return Msg(100 + len(self.photos))

            async def edit_message_caption(self, chat_id, message_id, caption, reply_markup=None):
                self.edits.append((chat_id, message_id, caption, reply_markup))

            async def send_message(self, chat_id, text, **kw):
                self.messages.append((chat_id, text, kw))

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                await db.add_user(7, None, None, 3)
                app = App.__new__(App)
                app.db, app.bot, app.autotrader = db, FakeBot(), None
                app.spawn = lambda coro: coro.close()

                async def _send(uid, factory):
                    await factory()
                    return True
                app._send = _send
                texts = {"ru": "BUY <i>x</i>", "en": "BUY", "uz": "BUY"}
                sid = await db.add_signal("donchian", 1, 2000, 1990, 2030, prop_only=True)
                await app.broadcast_signal(NewSignal(sid, 1, 2000, 1990, 2030, b"png", texts, prop_only=True))
                self.assertEqual(app.bot.photos, [])           # подписчикам не шлём
                sid = await db.add_signal("fvg_m15", 1, 2000, 1990, 2030, 2010, 0.5)
                await app.broadcast_signal(NewSignal(sid, 1, 2000, 1990, 2030, b"png", texts, sl_pips=100,
                                                     tp_pips=300, tp1=2010, tp1_pips=100, part=0.5))
                self.assertEqual(len(app.bot.photos), 1)
                cards = await db.signal_cards(sid)
                self.assertEqual(cards[0]["msg_id"], 101)
                s = await db.get_signal(sid)
                self.assertEqual(await app.update_cards(s, None, 2005.0), 1)
                chat, mid, caption, kb = app.bot.edits[-1]
                self.assertEqual((chat, mid), (7, 101))
                self.assertIn("Сделка идёт", caption)
                self.assertIsNotNone(kb)                       # кнопки остаются, пока не нажал
                await db.set_decision(sid, 7, False)
                await app.update_cards(s, None, 2006.0)
                self.assertIsNone(app.bot.edits[-1][3])
                await app.update_cards({**s, "part_at": "x"}, "be", 2000.0)
                self.assertIn("безубыток", app.bot.edits[-1][2])
                await db.close()
        run(go())
