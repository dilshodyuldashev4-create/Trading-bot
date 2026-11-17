"""Фиксация части прибыли, безубыток, закрытие при развороте, итоги недели, оповещения админу, копия базы."""
import asyncio
import logging
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime

import pandas as pd

from goldbot.autotrade import split_volume
from goldbot.db import DB
from goldbot.engine import SignalEngine, with_partial
from goldbot.health import AlertHandler, Watch, backup_db
from goldbot.results import signal_pips


def run(coro):
    return asyncio.run(coro)


async def make_db(d):
    db = DB(os.path.join(d, "t.db"))
    await db.connect()
    return db


class TargetsTests(unittest.TestCase):
    def test_partial_and_far_take(self):
        eng = SignalEngine(None, None, "combo", 100, 150, "UTC", None, None)
        self.assertEqual(eng.targets(pd.DataFrame()), (100, 150, 0.0))    # выключено — как раньше
        eng.partial_r, eng.final_r = 1.0, 3.0
        self.assertEqual(eng.targets(pd.DataFrame()), (100, 300, 100))
        eng.final_r = 0      # тейк из настроек, фиксация ближе тейка
        self.assertEqual(eng.targets(pd.DataFrame()), (100, 150, 100))

    def test_signal_text_line(self):
        txt = with_partial("A\n⚖️ Риск/прибыль 1:3", 4010.0, 100, 0.5, "ru")
        self.assertIn("Фиксация 50%: <b>4010.00</b>", txt)
        self.assertLess(txt.index("Фиксация"), txt.index("⚖️"))
        self.assertEqual(with_partial("A", None, 0, 0), "A")


class PartialFlowTests(unittest.TestCase):
    def _engine(self, db, closed, parts):
        async def on_close(s, status, price):
            closed.append((s, status, price))

        async def on_partial(s, price):
            parts.append((s["id"], price))
        eng = SignalEngine(db, None, "combo", 100, 300, "UTC", None, on_close)
        eng.on_partial = on_partial
        return eng

    def test_partial_then_breakeven(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                closed, parts = [], []
                eng = self._engine(db, closed, parts)
                sid = await db.add_signal("combo", 1, 4000.0, 3990.0, 4030.0, 4010.0, 0.5)
                await eng.check_open(4005.0)
                self.assertEqual(parts, [])
                await eng.check_open(4010.2)                       # дошли до TP1
                self.assertEqual(parts, [(sid, 4010.2)])
                self.assertTrue((await db.get_signal(sid))["part_at"])
                await eng.check_open(4003.0)                       # откат, стоп остатка — вход
                self.assertEqual(closed, [])
                await eng.check_open(3999.9)                       # безубыток
                s, status, _ = closed[0]
                self.assertEqual(status, "be")
                await db.close_signal(sid, status)
                self.assertAlmostEqual(signal_pips(await db.get_signal(sid)), 50.0)   # 50% × 100 пипсов
                self.assertEqual((await db.stats())["be"], 1)
                await db.close()
        run(go())

    def test_take_profit_after_partial_and_straight(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                closed, parts = [], []
                eng = self._engine(db, closed, parts)
                a = await db.add_signal("combo", -1, 4000.0, 4010.0, 3970.0, 3990.0, 0.5)   # SELL
                await eng.check_open(3989.0)
                await eng.check_open(3969.5)
                self.assertEqual(closed[0][1], "tp")
                await db.close_signal(a, "tp")
                self.assertAlmostEqual(signal_pips(await db.get_signal(a)), 0.5 * 100 + 0.5 * 300)
                # цена сразу дошла до тейка, минуя проверку TP1: фиксация засчитывается по пути
                b = await db.add_signal("combo", 1, 4000.0, 3990.0, 4030.0, 4010.0, 0.5)
                await eng.check_open(4031.0)
                await db.close_signal(b, "tp")
                self.assertAlmostEqual(signal_pips(await db.get_signal(b)), 200.0)
                await db.close()
        run(go())

    def test_stop_before_partial_is_full_loss(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                closed, parts = [], []
                eng = self._engine(db, closed, parts)
                sid = await db.add_signal("combo", 1, 4000.0, 3990.0, 4030.0, 4010.0, 0.5)
                await eng.check_open(3989.0)
                self.assertEqual(closed[0][1], "sl")
                await db.close_signal(sid, "sl")
                self.assertAlmostEqual(signal_pips(await db.get_signal(sid)), -100.0)
                await db.close()
        run(go())

    def test_candles_before_partial_do_not_hit_breakeven(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                closed, parts = [], []
                eng = self._engine(db, closed, parts)
                sid = await db.add_signal("combo", 1, 4000.0, 3990.0, 4030.0, 4010.0, 0.5)
                created = pd.Timestamp((await db.get_signal(sid))["created_at"]).tz_convert(None)
                dip = pd.DataFrame({"open": [4000.0], "high": [4002.0], "low": [3995.0], "close": [4001.0]},
                                   index=[created])
                await eng.check_open(4011.0, dip)                  # просадка была до фиксации
                self.assertEqual(len(parts), 1)
                await eng.check_open(4008.0, dip)
                self.assertEqual(closed, [])
                await db.close()
        run(go())


class ReversalTests(unittest.TestCase):
    def test_closes_profitable_opposite_trade(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                closed = []

                async def on_close(s, status, price):
                    closed.append((s["id"], status, price))
                eng = SignalEngine(db, None, "combo", 100, 300, "UTC", None, on_close)
                eng.last_price, eng.last_price_at = 4005.0, __import__("time").monotonic()
                win = await db.add_signal("combo", 1, 4000.0, 3990.0, 4030.0)    # +50 пипсов
                lose = await db.add_signal("fvg", 1, 4008.0, 3998.0, 4038.0)     # в минусе — не трогаем
                keys, dirs = {"combo", "fvg"}, {1}
                n = await eng.reversal_check(-1, keys, dirs)
                self.assertEqual(n, 1)
                self.assertEqual(closed, [(win, "rev", 4005.0)])
                self.assertEqual(keys, {"fvg"})
                self.assertEqual(dirs, {1})                         # BUY ещё открыт
                s = await db.get_signal(win)
                self.assertEqual(s["status"], "rev")
                self.assertAlmostEqual(signal_pips(s), 50.0)
                self.assertEqual((await db.get_signal(lose))["status"], "open")
                await db.close()
        run(go())


class StatsTextTests(unittest.TestCase):
    def test_breakeven_and_reversal_rows(self):
        from goldbot.bot import stats_text
        rows = [
            dict(id=3, created_at="2026-11-16T10:00:00+00:00", direction=-1, entry=4000.0, sl=4010.0, tp=3970.0,
                 tp1=3990.0, part=0.5, part_at="x", status="rev", exit_price=3980.0),
            dict(id=2, created_at="2026-11-16T09:00:00+00:00", direction=1, entry=4000.0, sl=3990.0, tp=4030.0,
                 tp1=4010.0, part=0.5, part_at="x", status="be", exit_price=None),
            dict(id=1, created_at="2026-11-16T08:00:00+00:00", direction=1, entry=4000.0, sl=3990.0, tp=4030.0,
                 tp1=4010.0, part=0.5, part_at=None, status="sl", exit_price=None),
        ]
        txt = stats_text("ru", rows, "UTC")
        self.assertIn("+50 пипсов", txt)       # 50% × 100 + 50% × 0
        self.assertIn("+150", txt)             # 50 + 50% × 200
        self.assertIn("Итог: <b>+100", txt)    # 150 + 50 − 100
        self.assertIn("67%", txt)


class VolumeTests(unittest.TestCase):
    def test_split(self):
        self.assertEqual(split_volume(0.10, 0.5), 0.05)
        self.assertEqual(split_volume(0.03, 0.5), 0.02)          # округление вверх
        self.assertEqual(split_volume(0.02, 0.5), 0.01)
        self.assertEqual(split_volume(0.05, 0.5), 0.03)
        self.assertEqual(split_volume(0.01, 0.5), 0.0)             # минимальный лот не делится
        self.assertEqual(split_volume(1.0, 0.5, {"volumeStep": 0.1, "minVolume": 0.1}), 0.5)
        self.assertEqual(split_volume(0.1, 0.5, {"volumeStep": 0.1, "minVolume": 0.1}), 0.0)


class AutotradePartialTests(unittest.TestCase):
    def test_partial_and_breakeven_on_broker(self):
        from tests import test_autotrade as ta

        class Api(ta.FakeApi):
            async def positions(self, acc_id, region):
                return [{"id": p, "volume": 0.1, "openPrice": 2650.3, "takeProfit": 2710.3}
                        for p in self.open_positions.get(acc_id, set())]

            async def trade(self, acc_id, region, req):
                if req["actionType"] in ("POSITION_PARTIAL", "POSITION_MODIFY"):
                    self.trades.append((acc_id, req))
                    return {"stringCode": "TRADE_RETCODE_DONE"}
                return await super().trade(acc_id, region, req)

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await ta.make_db(d)
                api = Api(equity=10000)
                tr = ta.trader(db, api, prop_tp_r=1.5)
                await tr.connect(1, "mt5", "S", "1", "p")
                await tr.open_signal(5, 1, 20, 60)
                res = await tr.partial_signal(5, 0.5)
                self.assertTrue(res[0].ok, res[0].error)
                self.assertEqual((res[0].closed, res[0].left, res[0].stop), (0.05, 0.05, 2650.3))
                kinds = [q["actionType"] for _, q in api.trades]
                self.assertEqual(kinds[-2:], ["POSITION_PARTIAL", "POSITION_MODIFY"])
                self.assertEqual(api.trades[-2][1]["volume"], 0.05)
                self.assertEqual(api.trades[-1][1]["stopLoss"], 2650.3)
                self.assertEqual(api.trades[-1][1]["takeProfit"], 2710.3)
                # проп-счёт: тейк 1.5 стопа, без фиксации и без закрытия по безубытку/развороту
                await db.set_prop(1, "2step", "phase1", 10000, "2026-11-16", 10000, 10000)
                await tr.open_signal(6, 1, 20, 60)
                self.assertAlmostEqual(api.trades[-1][1]["takeProfit"], 2650.3 + 30)
                self.assertEqual(await tr.partial_signal(6, 0.5), [])
                self.assertEqual(await tr.close_signal(6, skip_prop=True), [])
                self.assertEqual(len(await tr.close_signal(6)), 1)
                await db.close()
        run(go())


class HealthTests(unittest.TestCase):
    def test_alert_dedup(self):
        h = AlertHandler(repeat=60)
        lg = logging.getLogger("goldbot.test_alerts")
        lg.addHandler(h)
        try:
            for _ in range(3):
                lg.error("broken %s", 1)
            lg.warning("not an alert")
            self.assertEqual(h.take(now=0), ["broken 1"])
            lg.error("broken %s", 2)
            self.assertEqual(h.take(now=10), [])
            lg.error("broken %s", 3)
            out = h.take(now=100)
            self.assertEqual(len(out), 1)
            self.assertIn("broken 3", out[0])
            self.assertIn("ещё 3", out[0])   # 2 повтора в первом окне + 1
        finally:
            lg.removeHandler(h)

    def test_watch(self):
        w = Watch(60)
        self.assertIsNone(w.update(True, 0))
        self.assertEqual(w.update(True, 61), "down")
        self.assertIsNone(w.update(True, 120))
        self.assertEqual(w.update(False, 130), "up")
        self.assertIsNone(w.update(False, 140))

    def test_backup(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "goldbot.db")
            con = sqlite3.connect(path)
            con.execute("CREATE TABLE x (a)")
            con.execute("INSERT INTO x VALUES (1)")
            con.commit()
            con.close()
            for day in range(1, 5):
                out = backup_db(path, keep=2, when=datetime(2026, 11, day))
            self.assertEqual(sorted(p.name for p in out.parent.iterdir()),
                             ["goldbot-2026-11-03.db", "goldbot-2026-11-04.db"])
            con = sqlite3.connect(out)
            self.assertEqual(con.execute("SELECT a FROM x").fetchone(), (1,))
            con.close()


class WeeklyReportTests(unittest.TestCase):
    def test_sunday_report(self):
        import goldbot.bot as botmod

        class FakeBot:
            def __init__(self):
                self.sent = []

            async def send_photo(self, uid, photo, caption=None, **kw):
                self.sent.append((uid, caption))

            async def send_message(self, uid, text, **kw):
                self.sent.append((uid, text))

        async def go():
            with tempfile.TemporaryDirectory() as d:
                app = botmod.App.__new__(botmod.App)
                app.db = await make_db(d)
                app.bot = FakeBot()
                await app.db.add_user(1, "u", "U", 3)
                sid = await app.db.add_signal("combo", 1, 4000.0, 3990.0, 4030.0, 4010.0, 0.5)
                await app.db.add_signal_lot(sid, 1, 0.1)
                await app.db.set_partial(sid)
                await app.db.close_signal(sid, "tp")
                sunday = pd.Timestamp("2026-11-22 12:00", tz=botmod.config.display_tz).tz_convert("UTC")
                self.assertFalse(await app.weekly_report(sunday - pd.Timedelta(days=1)))   # суббота
                self.assertTrue(await app.weekly_report(sunday + pd.Timedelta(minutes=1)))
                self.assertFalse(await app.weekly_report(sunday + pd.Timedelta(minutes=5)))  # один раз
                (uid, text), = app.bot.sent
                self.assertEqual(uid, 1)
                self.assertIn("+200 пипсов", text)
                self.assertIn("+$20", text)       # 0.1 лота × 200 пипсов
                await app.db.close()
        run(go())


if __name__ == "__main__":
    unittest.main()


class PropPartialSwitchTests(unittest.TestCase):
    def test_prop_partial_on(self):
        from tests import test_autotrade as ta

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await ta.make_db(d)
                api = ta.FakeApi(equity=10000)
                tr = ta.trader(db, api, prop_tp_r=1.5, prop_partial=True)
                await tr.connect(1, "mt5", "S", "1", "p")
                await db.set_prop(1, "2step", "phase1", 10000, "2026-11-16", 10000, 10000)
                await tr.open_signal(6, 1, 20, 60)
                self.assertAlmostEqual(api.trades[-1][1]["takeProfit"], 2650.3 + 60)   # тейк как в сигнале
                self.assertEqual(len(await tr.close_signal(6, skip_prop=True)), 1)       # разворот закрывает и проп
                await db.close()
        run(go())


class PartialRobustTests(unittest.TestCase):
    """Сигнал #40: фиксация не сработала на счёте Exness — позиция у брокера под другим номером."""

    def _api(self):
        from tests import test_autotrade as ta

        class Api(ta.FakeApi):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.real_id = "2790963546"
                self.volume, self.sl = 0.03, 3878.983
                self.fail_modify = 0

            async def positions(self, acc_id, region):
                if not self.open_positions.get(acc_id):
                    return []
                return [{"id": self.real_id, "type": "POSITION_TYPE_SELL", "volume": self.volume,
                         "openPrice": 3865.972, "stopLoss": self.sl, "takeProfit": 3826.983,
                         "comment": "goldbot #40"}]

            async def trade(self, acc_id, region, req):
                kind = req["actionType"]
                if kind in ("POSITION_PARTIAL", "POSITION_MODIFY", "POSITION_CLOSE_ID"):
                    assert req["positionId"] == self.real_id, req
                    self.trades.append((acc_id, req))
                    if kind == "POSITION_MODIFY" and self.fail_modify:
                        self.fail_modify -= 1
                        raise ta.at.MetaApiError("not connected", "TIMEOUT")
                    if kind == "POSITION_PARTIAL":
                        self.volume = round(self.volume - req["volume"], 2)
                    elif kind == "POSITION_MODIFY":
                        self.sl = req["stopLoss"]
                    else:
                        self.open_positions[acc_id].clear()
                    return {"stringCode": "TRADE_RETCODE_DONE"}
                return await super().trade(acc_id, region, req)
        return ta, Api

    def test_position_found_by_comment_partial_once(self):
        ta, Api = self._api()

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await ta.make_db(d)
                api = Api(equity=5000)
                api.fail_modify = 1          # первая попытка переноса стопа — сбой связи, потом получается
                tr = ta.trader(db, api)
                await tr.connect(1, "mt5", "S", "1", "p")
                await db.save_auto_trade(40, 1, 1, "111", 0.03, "open", "")   # номер ордера, не позиции
                api.open_positions["acc1"] = {"111"}
                res = await tr.partial_signal(40, 0.5)
                self.assertTrue(res[0].ok, res[0].error)
                self.assertEqual((res[0].closed, res[0].left), (0.02, 0.01))
                self.assertEqual(api.volume, 0.01)
                self.assertEqual(api.sl, 3865.97)
                partials = [q for _, q in api.trades if q["actionType"] == "POSITION_PARTIAL"]
                self.assertEqual(len(partials), 1)              # повтор после сбоя не закрыл ещё раз
                self.assertEqual((await db.get_auto_trade(40, 1))["position_id"], "2790963546")
                self.assertEqual(await tr.partial_signal(40, 0.5), [])        # уже сделано — второй раз нет
                closed = await tr.close_signal(40)
                self.assertTrue(closed[0].ok)
                self.assertFalse(closed[0].already)
                await db.close()
        run(go())

    def test_already_at_breakeven_by_hand(self):
        ta, Api = self._api()

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await ta.make_db(d)
                api = Api(equity=5000)
                api.volume, api.sl = 0.02, 3865.97    # подписчик сам закрыл часть и перенёс стоп
                tr = ta.trader(db, api)
                await tr.connect(1, "mt5", "S", "1", "p")
                await db.save_auto_trade(40, 1, 1, "2790963546", 0.03, "open", "")
                api.open_positions["acc1"] = {"2790963546"}
                res = await tr.partial_signal(40, 0.5)
                self.assertTrue(res[0].ok)
                self.assertEqual(res[0].closed, 0)
                self.assertEqual([q["actionType"] for _, q in api.trades if q["actionType"].startswith("POSITION")], [])
                await db.close()
        run(go())
