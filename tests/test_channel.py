import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace

from goldbot import bot as botmod
from goldbot.db import DB
from goldbot.engine import NewSignal, format_signal
from goldbot.i18n import per_lang
from goldbot.live_strategy import STRATEGIES

CHAN = -1001234567890


class FakeBot:
    def __init__(self):
        self.sent = []      # (chat, text, kw)
        self.edits = []
        self.n = 100

    def _msg(self):
        self.n += 1
        return SimpleNamespace(message_id=self.n)

    async def send_photo(self, chat, photo, caption=None, **kw):
        self.sent.append((chat, caption, kw))
        return self._msg()

    async def send_message(self, chat, text, **kw):
        self.sent.append((chat, text, kw))
        return self._msg()

    async def edit_message_caption(self, chat_id=None, message_id=None, caption=None, **kw):
        self.edits.append((chat_id, message_id, caption))

    async def get_me(self):
        return SimpleNamespace(username="GoldTestBot")


class Eng:
    last_df = None

    def df_for(self, key=None):
        return None


def make_app(db):
    app = botmod.App.__new__(botmod.App)
    app.db, app.bot, app.engine = db, FakeBot(), Eng()
    app._bot_name = None
    app.autotrader = None
    app._tasks = set()
    return app


class ChannelTests(unittest.TestCase):
    def test_target_parsing_and_off(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                app = make_app(db)
                self.assertIsNone(await app.chan_target())          # по умолчанию канала нет
                await db.set_kv("channel_id", str(CHAN))
                self.assertEqual(await app.chan_target(), CHAN)
                await db.set_kv("channel_id", "https://t.me/goldchan")
                self.assertEqual(await app.chan_target(), "@goldchan")
                await db.set_kv("channel_id", "off")
                self.assertIsNone(await app.chan_target())
                self.assertEqual(await app.chan_lang(), "ru")
                await db.close()
        asyncio.run(go())

    def test_signal_partial_close_go_to_channel(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                await db.add_user(1, None, None, 3)
                await db.set_capital(1, 1000)
                await db.set_kv("channel_id", str(CHAN))
                await db.set_kv("channel_lang", "en")
                app = make_app(db)
                st = STRATEGIES["combo"]
                sid = await db.add_signal("combo", 1, 2900, 2890, 2920)
                s = NewSignal(sid, 1, 2900, 2890, 2920, b"PNG",
                              per_lang(lambda lang: format_signal(st, 1, 2900, 2890, 2920, 100, 200, "now", lang)))
                await app.broadcast_signal(s)
                chan = [x for x in app.bot.sent if x[0] == CHAN]
                self.assertEqual(len(chan), 1)
                caption = chan[0][1]
                self.assertIn("XAUUSD", caption)
                self.assertIn("@GoldTestBot", caption)
                self.assertNotIn("/capital", caption)               # без личного лота
                self.assertNotIn("reply_markup", chan[0][2])        # без кнопок «Принять / Отклонить»
                self.assertTrue(any(x[0] == 1 for x in app.bot.sent))  # подписчику по-прежнему
                card = await app.chan_card(sid)

                sig = await db.get_signal(sid)
                app.bot.sent.clear()
                await app.broadcast_late(sig, 2904, 40)
                late = [x for x in app.bot.sent if x[0] == CHAN]
                self.assertEqual(late[0][2]["reply_parameters"].message_id, card["m"])

                app.bot.sent.clear()
                await db.close_signal(sid, "tp")
                await app.broadcast_close(sig, "tp", 2920)
                chan = [x for x in app.bot.sent if x[0] == CHAN]
                self.assertEqual(len(chan), 1)
                self.assertNotIn("💼", chan[0][1])                  # без чужого баланса
                self.assertEqual(chan[0][2]["reply_parameters"].message_id, card["m"])
                self.assertTrue(any(e[0] == CHAN and e[1] == card["m"] for e in app.bot.edits))  # живая карточка
                await db.close()
        asyncio.run(go())

    def test_reports_and_news_go_to_channel(self):
        import pandas as pd

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                await db.add_user(1, None, None, 3)
                await db.set_kv("channel_id", "@goldchan")
                app = make_app(db)
                await app.broadcast_day_closed(2)
                await app.broadcast_all(lambda lang: f"news {lang}")
                await app.weekly_report(pd.Timestamp("2026-11-15 12:00", tz="UTC"))
                chan = [x[1] for x in app.bot.sent if x[0] == "@goldchan"]
                self.assertEqual(len(chan), 3, chan)
                self.assertIn("Торговый день закрыт", chan[0])
                self.assertEqual(chan[1], "news ru")
                self.assertIn("Итоги недели", chan[2])
                await db.close()
        asyncio.run(go())

    def test_no_channel_nothing_extra(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                await db.add_user(1, None, None, 3)
                app = make_app(db)
                await app.broadcast_day_closed(2)
                self.assertEqual([x[0] for x in app.bot.sent], [1])
                await db.close()
        asyncio.run(go())

    def test_channel_error_does_not_stop_subscribers(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                await db.add_user(1, None, None, 3)
                await db.set_kv("channel_id", str(CHAN))
                app = make_app(db)
                orig = app.bot.send_message

                async def send(chat, text, **kw):
                    if chat == CHAN:
                        raise RuntimeError("bot is not a member of the channel chat")
                    return await orig(chat, text, **kw)
                app.bot.send_message = send
                with self.assertLogs("goldbot.bot", "ERROR"):
                    await app.broadcast_day_closed(2)
                self.assertEqual([x[0] for x in app.bot.sent], [1])
                await db.close()
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
