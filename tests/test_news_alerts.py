import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from goldbot import news_alerts
from goldbot.db import DB


def event(ts: datetime, actual: str = "") -> dict:
    return {"key": f"CPI m/m|{ts.isoformat()}", "ts": ts.isoformat(), "country": "USD",
            "title": "CPI m/m", "impact": "High", "forecast": "0.3%", "previous": "0.2%", "actual": actual}


class NewsAlertTests(unittest.TestCase):
    def test_pre_and_result_alerts_sent_once(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                release = datetime(2026, 11, 12, 13, 30, tzinfo=timezone.utc)
                await db.upsert_events([event(release)])
                sent, calls = [], []

                async def send_all(text):
                    sent.append(text)

                async def fetch(e):
                    calls.append(e["title"])
                    return None if len(calls) == 1 else "0.5%"

                tz = "Asia/Tashkent"
                # за 10 минут — предупреждение, повтор не шлётся
                for _ in range(2):
                    await news_alerts.process(db, tz, send_all, fetch, release - timedelta(minutes=10))
                self.assertEqual(len(sent), 1)
                self.assertIn("Через 15 минут", sent[0])
                self.assertIn("0.3%", sent[0])
                # после выхода: первая попытка без цифры, повтор через 3 минуты находит факт
                await news_alerts.process(db, tz, send_all, fetch, release + timedelta(minutes=2))
                await news_alerts.process(db, tz, send_all, fetch, release + timedelta(minutes=3))
                self.assertEqual(len(calls), 1)  # не чаще раза в 3 минуты
                await news_alerts.process(db, tz, send_all, fetch, release + timedelta(minutes=6))
                self.assertEqual(len(sent), 2)
                self.assertIn("Факт: <b>0.5%</b>", sent[1])
                self.assertIn("золото ⬇️", sent[1])  # инфляция выше прогноза
                await news_alerts.process(db, tz, send_all, fetch, release + timedelta(minutes=10))
                self.assertEqual(len(sent), 2)
                await db.close()
        asyncio.run(go())

    def test_known_actual_used_without_fetch(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                release = datetime(2026, 11, 12, 13, 30, tzinfo=timezone.utc)
                await db.upsert_events([event(release, actual="0.1%")])
                sent = []

                async def send_all(text):
                    sent.append(text)

                async def fetch(e):
                    raise AssertionError("не должен искать")

                await news_alerts.process(db, "UTC", send_all, fetch, release + timedelta(minutes=5))
                self.assertIn("золото ⬆️", sent[0])
                await db.close()
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
