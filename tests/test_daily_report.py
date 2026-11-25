import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone

import pandas as pd

from goldbot import daily_report as dr
from goldbot.db import DB

UTC = timezone.utc


def run(coro):
    return asyncio.run(coro)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_photo(self, chat, photo, caption=None, **kw):
        self.sent.append((chat, "photo", caption, kw))

    async def send_message(self, chat, text, **kw):
        self.sent.append((chat, "text", text, kw))

    async def get_me(self):
        class Me:
            username = "goldbot"
        return Me()


async def put(db, direction, created, closed=None, status="open", partial=False, exit_price=None):
    sid = await db.add_signal("combo", direction, 4000.0, 4000.0 - 10 * direction, 4000.0 + 30 * direction,
                              4000.0 + 10 * direction, 0.5)
    if partial:
        await db.set_partial(sid)
    if status != "open":
        await db.close_signal(sid, status, exit_price)
    await db.conn.execute("UPDATE signals SET created_at=?, closed_at=? WHERE id=?",
                          (created.isoformat(), closed.isoformat() if closed else None, sid))
    await db.conn.commit()
    return sid


def ts(s):
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


class DayWindowTests(unittest.TestCase):
    def test_close_time_follows_new_york(self):
        # зима: 17:00 Нью-Йорк = 22:00 UTC; лето: 21:00 UTC
        self.assertIsNone(dr.day_close(pd.Timestamp("2026-11-18 21:59", tz="UTC")))
        self.assertEqual(dr.day_close(pd.Timestamp("2026-11-18 22:00", tz="UTC")).tz_convert("UTC"),
                         pd.Timestamp("2026-11-18 22:00", tz="UTC"))
        self.assertEqual(dr.day_close(pd.Timestamp("2026-07-15 21:01", tz="UTC")).tz_convert("UTC"),
                         pd.Timestamp("2026-07-15 21:00", tz="UTC"))
        self.assertIsNone(dr.day_close(pd.Timestamp("2026-11-21 23:00", tz="UTC")))   # суббота
        self.assertIsNone(dr.day_close(pd.Timestamp("2026-11-22 23:30", tz="UTC")))   # воскресенье
        close = dr.day_close(pd.Timestamp("2026-11-16 22:30", tz="UTC"))              # понедельник
        self.assertEqual(dr.day_open(close).tz_convert("UTC"), pd.Timestamp("2026-11-15 23:00", tz="UTC"))


class DailyReportTests(unittest.TestCase):
    def test_report_counts_partial_and_goes_everywhere(self):
        import goldbot.bot as botmod

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                app = botmod.App.__new__(botmod.App)
                app.db, app.bot, app._bot_name = db, FakeBot(), None
                await db.add_user(1, "u", "U")
                await db.add_user(2, "v", "V")
                await db.set_lang(2, "en")
                await db.set_kv("channel_id", "@goldchan")
                be = await put(db, 1, ts("2026-11-18T10:00"), ts("2026-11-18T12:00"), "be", partial=True)   # +50
                await db.add_signal_lot(be, 1, 0.1)
                await put(db, -1, ts("2026-11-18T13:00"), ts("2026-11-18T14:00"), "sl")                    # −100
                await put(db, 1, ts("2026-11-18T15:00"), ts("2026-11-18T18:00"), "tp", partial=True)       # +200
                await put(db, 1, ts("2026-11-17T10:00"), ts("2026-11-18T03:00"), "sl")                    # вчерашний, −100
                await put(db, 1, ts("2026-11-17T10:00"), ts("2026-11-17T21:00"), "tp")                    # прошлый день
                await put(db, 1, ts("2026-11-18T20:00"))                                                  # в работе
                wed = pd.Timestamp("2026-11-18 22:00", tz="UTC")
                self.assertFalse(await app.daily_report(wed))                          # ждём 5 минут
                self.assertTrue(await app.daily_report(wed + pd.Timedelta(minutes=5)))
                self.assertFalse(await app.daily_report(wed + pd.Timedelta(minutes=30)))  # один раз
                sent = app.bot.sent
                self.assertEqual([x[0] for x in sent], ["@goldchan", 1, 2])
                self.assertTrue(all(x[1] == "photo" for x in sent))
                chan, ru, en = (x[2] for x in sent)
                self.assertIn("Итоги торгового дня 18.11.2026", ru)
                self.assertIn("В плюсе: <b>2</b>", ru)
                self.assertIn("В минусе: <b>2</b>", ru)
                self.assertIn("в работе: 1", ru)
                self.assertIn("Итог дня: <b>+50 пипсов</b>", ru)
                self.assertIn("фиксация 4010.00 + безубыток: <b>+50</b>", ru)
                self.assertIn("<b>+$50</b>", ru)            # 0.1 лота × 50 пипсов
                self.assertIn("Trading day results", en)
                self.assertNotIn("💼", en)
                self.assertNotIn("💼", chan)
                self.assertIn("@goldbot", chan)
                self.assertTrue(sent[1][3]["disable_notification"])   # в Ташкенте 03:05 — без звука
                await db.close()
        run(go())

    def test_empty_day(self):
        import goldbot.bot as botmod

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                app = botmod.App.__new__(botmod.App)
                app.db, app.bot, app._bot_name = db, FakeBot(), None
                await db.add_user(1, "u", "U")
                self.assertTrue(await app.daily_report(pd.Timestamp("2026-11-18 22:10", tz="UTC")))
                (uid, kind, text, _), = app.bot.sent
                self.assertEqual(kind, "photo")
                self.assertIn("сделок не было", text)
                await db.close()
        run(go())


class CaptionTests(unittest.TestCase):
    def test_caption_fits_telegram_limit(self):
        rows = [{"id": i, "direction": 1, "entry": 4000.0, "sl": 3990.0, "tp": 4030.0, "tp1": 4010.0,
                 "part": 0.5, "part_at": None, "status": "sl", "exit_price": None,
                 "created_at": "2026-11-18T10:00:00+00:00", "closed_at": "2026-11-18T11:00:00+00:00"}
                for i in range(1, 60)]
        day = dr.summarize(rows, ts("2026-11-17T23:00"), ts("2026-11-18T22:00"))
        text = dr.caption("ru", day, "18.11.2026", "\n\nхвост")
        self.assertLessEqual(len(text), dr.CAPTION_MAX)
        self.assertIn("на картинке", text)
        self.assertTrue(text.endswith("хвост"))
        png = dr.render_daily(day, "ru", "Asia/Tashkent", "18.11.2026")
        self.assertTrue(png.startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
