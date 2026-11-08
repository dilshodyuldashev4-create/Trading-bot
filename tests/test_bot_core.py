import asyncio
import os
import tempfile
import unittest
from datetime import timedelta

import numpy as np
import pandas as pd

from goldbot.chart import render_signal
from goldbot.db import DB, now
from goldbot.econ_calendar import impact_text
from goldbot.engine import SignalEngine
from goldbot.market import Replay


def run(coro):
    return asyncio.run(coro)


def m5_frame(days=6, start="2025-03-10 00:00"):
    idx = pd.date_range(start, periods=days * 288, freq="5min")
    rng = np.random.default_rng(1)
    p = 2900 + np.cumsum(rng.normal(0, 0.8, len(idx)))
    return pd.DataFrame({"open": p, "high": p + 0.6, "low": p - 0.6, "close": p + 0.1,
                         "volume": 1.0, "spread": 0.0}, index=idx)


class DBTests(unittest.TestCase):
    def test_trial_and_paid(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                self.assertTrue(await db.add_user(1, "a", "A", 3))
                self.assertFalse(await db.add_user(1, "a", "A", 3))
                u = await db.get_user(1)
                self.assertTrue(db.has_access(u))
                self.assertEqual(await db.active_user_ids(), [1])
                await db.revoke(1)
                self.assertEqual(await db.active_user_ids(), [])
                await db.extend_paid(1, 30)
                u = await db.get_user(1)
                self.assertTrue(db.is_paid(u))
                self.assertGreater(db.access_until(u), now() + timedelta(days=29))
                await db.close()
        run(go())


class EngineTests(unittest.TestCase):
    def test_replay_generates_and_closes_signals(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                sent, closed = [], []

                async def on_signal(s):
                    sent.append(s)

                async def on_close(s, status, price):
                    closed.append(status)

                df = m5_frame()
                prov = Replay(df, start=300)
                eng = SignalEngine(db, prov, "combo", 30, 60, "Asia/Tashkent", on_signal, on_close)
                while prov.pos < len(df):
                    prov.step()
                    t = (df.index[prov.pos - 1] + pd.Timedelta(minutes=5)).tz_localize("UTC")
                    await eng.tick(now=t)
                self.assertTrue(sent, "ожидали хотя бы один сигнал")
                self.assertTrue(sent[0].image.startswith(b"\x89PNG"))
                self.assertIn("XAUUSD", sent[0].text)
                self.assertTrue(set(closed) <= {"tp", "sl"} and closed)
                text = await eng.expected()
                self.assertIn("Silver Bullet", text)
                await db.close()
        run(go())


class MiscTests(unittest.TestCase):
    def test_chart(self):
        df = m5_frame(1)
        png = render_signal(df, -1, df.close.iloc[-1], df.close.iloc[-1] + 10, df.close.iloc[-1] - 20, "t")
        self.assertTrue(png.startswith(b"\x89PNG"))

    def test_calendar_impact(self):
        self.assertIn("доллар ⬆️", impact_text("Non-Farm Employment Change", "150K", "250K"))
        self.assertIn("золото ⬆️", impact_text("CPI m/m", "0.3%", "0.1%"))
        self.assertIn("золото ⬆️", impact_text("Unemployment Rate", "4.1%", "4.3%"))
        self.assertIn("ФРС", impact_text("FOMC Statement", "", ""))


if __name__ == "__main__":
    unittest.main()


class MarketHoursTests(unittest.TestCase):
    def test_market_open(self):
        from goldbot.engine import market_open
        ts = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
        # ноябрь: Нью-Йорк = UTC-5
        self.assertTrue(market_open(ts("2026-11-06 21:59")))   # пт 16:59 NY
        self.assertFalse(market_open(ts("2026-11-06 22:30")))  # пт 17:30 NY
        self.assertFalse(market_open(ts("2026-11-07 12:00")))  # суббота
        self.assertFalse(market_open(ts("2026-11-08 22:59")))  # вс 17:59 NY
        self.assertTrue(market_open(ts("2026-11-08 23:00")))   # вс 18:00 NY — открытие
        self.assertFalse(market_open(ts("2026-11-10 22:30")))  # вт 17:30 NY — перерыв
        self.assertTrue(market_open(ts("2026-11-10 15:00")))   # вт день

    def test_tick_makes_no_requests_on_weekend(self):
        class Boom(Replay):
            async def price(self):
                raise AssertionError("запрос в выходные")

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()

                async def noop(*a):
                    pass

                eng = SignalEngine(db, Boom(m5_frame()), "combo", 30, 60, "UTC", noop, noop)
                self.assertIsNone(await eng.tick(now=pd.Timestamp("2026-11-07 12:00", tz="UTC")))
                await db.close()
        run(go())


class ComboTrendTests(unittest.TestCase):
    def test_signals_only_with_daily_trend(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                sent = []

                async def on_signal(s):
                    sent.append(s)

                async def on_close(s, status, price):
                    pass

                df = m5_frame(days=20, start="2025-03-03 00:00")
                prov = Replay(df, start=300)
                eng = SignalEngine(db, prov, "fvg_m5", 30, 60, "Asia/Tashkent", on_signal, on_close)
                trends = []
                while prov.pos < len(df):
                    prov.step()
                    t = (df.index[prov.pos - 1] + pd.Timedelta(minutes=5)).tz_localize("UTC")
                    n = len(sent)
                    await eng.tick(now=t)
                    if len(sent) > n:
                        trends.append((sent[-1].direction, await eng.daily_trend(t)))
                self.assertTrue(trends, "ожидали хотя бы один сигнал")
                self.assertTrue(all(a == b for a, b in trends))
                text = await eng.expected()
                self.assertIn("EMA50", text)
                await db.close()
        run(go())

    def test_all_strategies_at_once(self):
        from goldbot.live_strategy import PORTFOLIO

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                sent = []

                async def on_signal(s):
                    open_same = [x for x in await db.open_signals() if x["id"] != s.id and x["strategy"] == key_of[s.id]]
                    self.assertFalse(open_same, "у стратегии уже была открытая сделка")
                    sent.append(s)

                async def on_close(s, status, price):
                    pass

                key_of = {}
                orig = db.add_signal

                async def add_signal(strategy, *a):
                    sid = await orig(strategy, *a)
                    key_of[sid] = strategy
                    return sid
                db.add_signal = add_signal

                df = m5_frame(days=8, start="2025-03-03 00:00")
                prov = Replay(df, start=600)
                eng = SignalEngine(db, prov, "all", 30, 60, "Asia/Tashkent", on_signal, on_close)
                self.assertEqual([st.key for st in eng.strategies], list(PORTFOLIO))
                while prov.pos < len(df):
                    prov.step()
                    t = (df.index[prov.pos - 1] + pd.Timedelta(minutes=5)).tz_localize("UTC")
                    await eng.tick(now=t)
                self.assertGreater(len({key_of[s.id] for s in sent}), 1, "сигналы должны идти от разных стратегий")
                text = await eng.expected()
                self.assertIn(str(len(PORTFOLIO)), text)
                await db.close()
        run(go())


class AllLiveStrategiesTests(unittest.TestCase):
    def test_every_strategy_runs_and_explains_setup(self):
        from goldbot.live_strategy import STRATEGIES

        async def go(key):
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                sent = []

                async def on_signal(s):
                    sent.append(s)

                async def on_close(s, status, price):
                    pass

                df = m5_frame(days=6, start="2025-03-03 00:00")
                prov = Replay(df, start=600)
                eng = SignalEngine(db, prov, key, 30, 60, "Asia/Tashkent", on_signal, on_close)
                while prov.pos < len(df):
                    prov.step(3)
                    t = (df.index[prov.pos - 1] + pd.Timedelta(minutes=5)).tz_localize("UTC")
                    await eng.tick(now=t)
                for lang in ("ru", "en", "uz"):
                    self.assertTrue(await eng.expected(lang))
                await db.close()

        for key in STRATEGIES:
            with self.subTest(key=key):
                run(go(key))
