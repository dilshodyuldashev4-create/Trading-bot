import asyncio
import os
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

from goldbot.config import config
from goldbot.db import DB
from tests.test_channel import make_app


def run(coro):
    return asyncio.run(coro)


async def new_db(d):
    db = DB(os.path.join(d, "t.db"))
    await db.connect()
    return db


async def join(app, uid, ref):
    """Новый подписчик пришёл по ссылке ref_<ref> и выбрал язык."""
    await app.db.add_user(uid, None, f"U{uid}")
    await app.db.set_referrer(uid, ref)
    await app.db.set_lang(uid, "ru")
    await app.ref_joined(uid)


class ReferralTests(unittest.TestCase):
    def test_set_referrer_rules(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await new_db(d)
                await db.add_user(1, "a", "A")
                await db.add_user(2, "b", "B")
                self.assertFalse(await db.set_referrer(1, 1))      # не сам себя
                self.assertFalse(await db.set_referrer(2, 999))    # пригласивший должен быть в базе
                self.assertTrue(await db.set_referrer(2, 1))
                self.assertFalse(await db.set_referrer(2, 1))      # только один раз
                self.assertEqual(await db.ref_count(1), 0)         # язык ещё не выбран — не считается
                await db.set_lang(2, "uz")
                self.assertEqual(await db.ref_count(1), 1)
                self.assertEqual((await db.top_referrers())[0]["friends"], 1)
                await db.close()
        run(go())

    def test_reward_every_n_friends_goes_to_bonus_days(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await new_db(d)
                app = make_app(db)
                app.fmt_dt = lambda dt: dt.strftime("%d.%m")
                await db.add_user(1, "a", "A")
                await db.set_lang(1, "ru")
                for i in range(config.ref_friends):
                    await join(app, 100 + i, 1)
                self.assertEqual(await db.bonus_days(1), config.ref_days)
                msgs = [x[1] for x in app.bot.sent if x[0] == 1]
                self.assertEqual(len(msgs), config.ref_friends)
                self.assertIn("Награда", msgs[-1])
                # бесплатные дни открывают подключение счёта без оплаты
                app.is_admin = lambda uid: False
                self.assertTrue(await app.can_connect(1))
                self.assertEqual(await db.take_bonus_days(1), config.ref_days)
                self.assertEqual(await db.bonus_days(1), 0)
                await db.close()
        run(go())

    def test_friend_paid_rewards_once(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await new_db(d)
                app = make_app(db)
                await db.add_user(1, "a", "A")
                await db.add_user(2, "b", "B")
                await db.set_referrer(2, 1)
                await app.ref_friend_paid(2)
                await app.ref_friend_paid(2)
                self.assertEqual(await db.bonus_days(1), config.ref_paid_days)
                await db.close()
        run(go())

    def test_invite_screen_has_link_and_share_button(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await new_db(d)
                app = make_app(db)
                await db.add_user(7, "a", "A")
                await app.invite_screen(7, 7, "ru")
                chat, text, kw = app.bot.sent[-1]
                self.assertIn("https://t.me/GoldTestBot?start=ref_7", text)
                url = kw["reply_markup"].inline_keyboard[0][0].url
                q = parse_qs(urlparse(url).query)
                self.assertEqual(q["url"], ["https://t.me/GoldTestBot?start=ref_7"])
                await db.close()
        run(go())


if __name__ == "__main__":
    unittest.main()
