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
