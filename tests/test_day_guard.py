"""Защита обычного счёта: стоп дня после Stop Loss, одна сторона за день, меньший риск в просадке."""
import asyncio
import tempfile
import unittest

from tests.test_autotrade import FakeApi, make_db, trader


def run(coro):
    return asyncio.run(coro)


class DayGuardTests(unittest.TestCase):
    def test_two_stops_end_the_day(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = FakeApi(equity=5000)
                tr = trader(db, api, day_side=False, day_losses=2)
                await tr.connect(1, "mt5", "S", "1", "p")
                s1 = await db.add_signal("squeeze", -1, 2650, 2670, 2620)
                self.assertTrue((await tr.open_signal(s1, -1, 20, 30))[0].ok)
                await db.close_signal(s1, "sl")
                s2 = await db.add_signal("amd", -1, 2650, 2670, 2620)
                self.assertTrue((await tr.open_signal(s2, -1, 20, 30))[0].ok)   # один стоп — ещё торгуем
                await db.close_signal(s2, "sl")
                s3 = await db.add_signal("donchian", -1, 2650, 2670, 2620)
                self.assertEqual((await tr.open_signal(s3, -1, 20, 30))[0].error, "DAY_LOSS")
                # вчерашние стопы не считаются
                await db.conn.execute("UPDATE signals SET closed_at='2000-01-01T00:00:00+00:00'")
                s4 = await db.add_signal("fvg_m15", -1, 2650, 2670, 2620)
                self.assertTrue((await tr.open_signal(s4, -1, 20, 30))[0].ok)
                # выключено
                tr.day_losses = 0
                await db.close_signal(s4, "sl")
                await db.close_signal(s3, "sl")
                s5 = await db.add_signal("liq_m15", -1, 2650, 2670, 2620)
                self.assertTrue((await tr.open_signal(s5, -1, 20, 30))[0].ok)
                await db.close()
        run(go())

    def test_one_side_per_day(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = FakeApi(equity=5000)
                tr = trader(db, api, day_side=True)
                await tr.connect(1, "mt5", "S", "1", "p")
                s1 = await db.add_signal("squeeze", -1, 2650, 2670, 2620)
                self.assertTrue((await tr.open_signal(s1, -1, 20, 30))[0].ok)
                await db.close_signal(s1, "tp")
                s2 = await db.add_signal("amd", 1, 2650, 2630, 2680)
                self.assertEqual((await tr.open_signal(s2, 1, 20, 30))[0].error, "DAY_SIDE")
                s3 = await db.add_signal("donchian", -1, 2650, 2670, 2620)
                self.assertTrue((await tr.open_signal(s3, -1, 20, 30))[0].ok)
                tr.day_side = False
                s4 = await db.add_signal("fvg_m15", 1, 2650, 2630, 2680)
                self.assertTrue((await tr.open_signal(s4, 1, 20, 30))[0].ok)
                await db.close()
        run(go())

    def test_risk_halves_below_peak(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = FakeApi(equity=10000)
                tr = trader(db, api, risk_pct=1.0, day_side=False, day_losses=0, dd_pct=3, dd_mult=0.5)
                await tr.connect(1, "mt5", "S", "1", "p")
                # стоп $20, риск 1 % от 10000 = $100 → 0.05 лота
                self.assertEqual((await tr.open_signal(1, -1, 20, 30))[0].volume, 0.05)
                # баланс −3 % от максимума: риск 0.5 % от 9700 = $48.5 → 0.02 лота
                api.equity = 9700
                self.assertEqual((await tr.open_signal(2, -1, 20, 30))[0].volume, 0.02)
                # −2 % — ещё обычный риск
                api.equity = 9800
                self.assertEqual((await tr.open_signal(3, -1, 20, 30))[0].volume, 0.04)
                await db.close()
        run(go())


if __name__ == "__main__":
    unittest.main()
