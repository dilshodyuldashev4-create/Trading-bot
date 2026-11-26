import os
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer

from goldbot import bot as botmod
from goldbot import mobile as mb
from goldbot import webapp as wa
from goldbot.config import config
from goldbot.db import DB


class FakeBot:
    def __init__(self):
        self.sent = []

    async def get_me(self):
        class Me:
            username = "GoldTestBot"
        return Me()

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))

    async def send_photo(self, chat_id, *a, **kw):
        self.sent.append((chat_id, kw.get("caption")))


class Eng:
    last_price = 2650.55

    async def expected(self, lang):
        return f"<b>analysis {lang}</b>"

    async def market_text(self):
        return "XAUUSD 2650"

    def df_for(self, key=None):
        return None


class News:
    async def digest(self, lang, market=""):
        return f"<b>news {lang}</b>"


class PushSpy(mb.Mobile):
    def __init__(self, app):
        super().__init__(app)
        self.pushed = []

    async def send_push(self, messages):
        self.pushed.extend(messages)
        return len(messages)


class PasswordTests(unittest.TestCase):
    def test_hash_and_check(self):
        h = mb.hash_password("secret1", iterations=1000)
        self.assertTrue(mb.check_password("secret1", h))
        self.assertFalse(mb.check_password("secret2", h))
        self.assertFalse(mb.check_password("x", None))
        self.assertFalse(mb.check_password("x", "garbage"))

    def test_email(self):
        self.assertEqual(mb.norm_email(" Ali@Mail.UZ "), "ali@mail.uz")
        for bad in ("", "ali", "ali@", "@mail.uz", "a b@mail.uz", None, 5):
            self.assertIsNone(mb.norm_email(bad))

    def test_push_texts_all_langs(self):
        keys = set(mb.PUSH["ru"])
        for lang, tx in mb.PUSH.items():
            self.assertEqual(set(tx), keys, lang)
        title, body = mb.signal_push("uz", {"id": 5, "direction": -1, "entry": 2650, "sl": 2655, "tp": 2640})
        self.assertIn("SELL", title)
        self.assertIn("2640.00", body)
        self.assertIn("+120", mb.close_push("ru", {"id": 5}, "tp", 120)[1])


class MobileApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = DB(os.path.join(self.dir.name, "t.db"))
        await self.db.connect()
        app = botmod.App.__new__(botmod.App)
        app.db, app.bot, app.engine, app.autotrader, app.news = self.db, FakeBot(), Eng(), None, News()
        app.stars_cap = config.stars_invoice_max
        app._tasks = set()
        app._bot_name = None
        app.mobile = PushSpy(app)
        await app.mobile.init_db()
        app.webapp = wa.WebApp(app)
        self.app = app
        self.client = TestClient(TestServer(app.webapp.make_app()))
        await self.client.start_server()
        for d, st in ((1, "tp"), (-1, "sl"), (1, "open")):
            sid = await self.db.add_signal("combo", d, 2600.0, 2600.0 - d * 5, 2600.0 + d * 10)
            if st != "open":
                await self.db.close_signal(sid, st)

    async def asyncTearDown(self):
        await self.client.close()
        await self.db.close()
        self.dir.cleanup()

    async def post(self, path, body=None, token=None):
        hdr = {"Authorization": f"Bearer {token}"} if token else {}
        r = await self.client.post(path, json=body or {}, headers=hdr)
        return r.status, await r.json()

    async def register(self, email="ali@mail.uz", pw="secret12", lang="uz"):
        st, d = await self.post("/m/api/register", {"email": email, "password": pw, "name": "Ali", "lang": lang})
        self.assertEqual(st, 200, d)
        return d["token"]

    async def test_register_login_state(self):
        tok = await self.register()
        st, d = await self.post("/m/api/state", token=tok)
        self.assertEqual(st, 200)
        self.assertEqual(d["lang"], "uz")
        self.assertEqual(d["user"]["name"], "Ali")
        self.assertIsNone(d["user"]["id"])
        self.assertEqual(d["me"]["email"], "ali@mail.uz")
        self.assertFalse(d["me"]["telegram"])
        self.assertEqual(d["me"]["bot"], "GoldTestBot")
        self.assertEqual(len(d["market"]["open"]), 1)
        self.assertEqual(len(d["stats"]["trades"]), 3)
        self.assertTrue(d["learn"]["lessons"])
        # повторная регистрация и вход
        self.assertEqual((await self.post("/m/api/register", {"email": "ALI@mail.uz", "password": "secret12"}))[0], 409)
        self.assertEqual((await self.post("/m/api/login", {"email": "ali@mail.uz", "password": "wrong"}))[0], 401)
        st, d = await self.post("/m/api/login", {"email": "Ali@Mail.uz", "password": "secret12"})
        self.assertEqual(st, 200)
        self.assertTrue(d["token"])

    async def test_bad_input_and_auth(self):
        self.assertEqual((await self.post("/m/api/state"))[0], 401)
        self.assertEqual((await self.post("/m/api/state", token="nope"))[0], 401)
        self.assertEqual((await self.post("/m/api/register", {"email": "bad", "password": "secret12"}))[1]["error"], "email")
        self.assertEqual((await self.post("/m/api/register", {"email": "a@b.uz", "password": "123"}))[1]["error"], "password")
        r = await self.client.post("/m/api/login", data="[1,2]", headers={"Content-Type": "application/json"})
        self.assertEqual(r.status, 400)

    async def test_login_rate_limit(self):
        await self.register()
        for _ in range(mb.FAIL_LIMIT):
            await self.post("/m/api/login", {"email": "ali@mail.uz", "password": "wrong"})
        self.assertEqual((await self.post("/m/api/login", {"email": "ali@mail.uz", "password": "secret12"}))[0], 429)

    async def test_settings_and_password(self):
        tok = await self.register()
        st, d = await self.post("/m/api/settings", {"lang": "en", "capital": 1500}, tok)
        self.assertEqual(st, 200)
        self.assertEqual(d["lang"], "en")
        self.assertEqual(d["user"]["capital"], 1500)
        self.assertIsNotNone(d["user"]["lot"])
        self.assertEqual((await self.post("/m/api/settings", {"lang": "xx"}, tok))[0], 400)
        self.assertEqual((await self.post("/m/api/settings", {"capital": -5}, tok))[0], 400)
        self.assertEqual((await self.post("/m/api/settings", {"password": "newpass1", "old_password": "bad"}, tok))[0], 403)
        self.assertEqual((await self.post("/m/api/settings", {"password": "newpass1", "old_password": "secret12"}, tok))[0], 200)
        self.assertEqual((await self.post("/m/api/login", {"email": "ali@mail.uz", "password": "newpass1"}))[0], 200)

    async def test_logout_and_delete(self):
        tok = await self.register()
        await self.post("/m/api/push", {"token": "ExponentPushToken[abcdefghij]", "platform": "ios"}, tok)
        await self.post("/m/api/prop", {"action": "save", "plan": "2step", "stage": "phase1", "size": 10000}, tok)
        self.assertEqual((await self.post("/m/api/logout", token=tok))[0], 200)
        self.assertEqual((await self.post("/m/api/state", token=tok))[0], 401)
        tok = (await self.post("/m/api/login", {"email": "ali@mail.uz", "password": "secret12"}))[1]["token"]
        self.assertEqual((await self.post("/m/api/delete", token=tok))[0], 200)
        self.assertEqual((await self.post("/m/api/login", {"email": "ali@mail.uz", "password": "secret12"}))[0], 401)
        self.assertEqual(await self.db.prop_subs(enabled_only=False), [])
        self.assertEqual(await self.app.mobile.devices(), [])

    async def test_prop_for_app_user(self):
        tok = await self.register()
        st, d = await self.post("/m/api/prop", {"action": "save", "plan": "2step", "stage": "phase1", "size": 10000}, tok)
        self.assertEqual(st, 200, d)
        self.assertEqual(d["prop"]["size"], 10000)
        self.assertTrue(d["prop"]["enabled"])
        sub = (await self.db.prop_subs())[0]
        self.assertLess(sub["user_id"], 0)
        # app-аккаунт без Telegram попадает в проп-рассылку, но не в Telegram
        self.assertIn(sub["user_id"], [x["user_id"] for x in await self.app.ps_active_subs()])
        self.assertEqual((await self.post("/m/api/prop", {"action": "zzz"}, tok))[0], 400)

    async def test_account_needs_telegram(self):
        tok = await self.register()
        self.assertEqual((await self.post("/m/api/account", {"id": 1, "action": "pause"}, tok))[0], 400)

    async def test_analysis_news_calendar(self):
        tok = await self.register(lang="en")
        st, d = await self.post("/m/api/analysis", token=tok)
        self.assertEqual(d["text"], "analysis en")
        self.assertEqual(d["price"], 2650.55)
        st, d = await self.post("/m/api/news", token=tok)
        self.assertEqual(d["text"], "news en")
        st, d = await self.post("/m/api/calendar", token=tok)
        self.assertEqual(st, 200)
        self.assertIsInstance(d["events"], list)
        st, d = await self.post("/m/api/market", token=tok)
        self.assertEqual(d["price"], 2650.55)
        r = await self.client.get("/m/api/chart/3.png", headers={"Authorization": f"Bearer {tok}"})
        self.assertEqual(r.status, 404)   # нет свечей у тестового движка

    async def test_telegram_login_flow(self):
        await self.db.add_user(777, "dilshod", "Dilshod")
        await self.db.set_lang(777, "ru")
        await self.db.set_capital(777, 3000)
        st, d = await self.post("/m/api/tg/start")
        self.assertEqual(st, 200)
        self.assertIn("t.me/GoldTestBot?start=app_", d["url"])
        code = d["code"]
        self.assertEqual((await self.post("/m/api/tg/poll", {"code": code}))[1], {"pending": True})
        self.assertEqual(await self.app.mobile.tg_confirm(code, 777, "dilshod", "Dilshod"), "login")
        self.assertEqual(await self.app.mobile.tg_confirm(code, 777, "dilshod", "Dilshod"), "bad")
        st, d = await self.post("/m/api/tg/poll", {"code": code})
        tok = d["token"]
        st, d = await self.post("/m/api/state", token=tok)
        self.assertEqual(d["user"]["id"], 777)
        self.assertEqual(d["user"]["capital"], 3000)
        self.assertTrue(d["me"]["telegram"])
        self.assertEqual((await self.post("/m/api/tg/poll", {"code": code}))[0], 404)
        self.assertEqual(await self.app.mobile.tg_confirm("nonexistent", 777, None, None), "bad")
        # без почты отвязать Telegram нельзя
        self.assertEqual((await self.post("/m/api/tg/unlink", token=tok))[1]["error"], "no_email")

    async def test_link_telegram_moves_prop_and_settings(self):
        tok = await self.register()
        await self.post("/m/api/settings", {"capital": 2000}, tok)
        await self.post("/m/api/prop", {"action": "save", "plan": "2step", "stage": "phase1", "size": 25000}, tok)
        code = (await self.post("/m/api/tg/start", token=tok))[1]["code"]
        self.assertEqual(await self.app.mobile.tg_confirm(code, 555, "u", "U"), "linked")
        self.assertEqual((await self.post("/m/api/tg/poll", {"code": code}))[1], {"linked": True})
        u = await self.db.get_user(555)
        self.assertEqual(u["lang"], "uz")
        self.assertEqual(u["capital"], 2000)
        self.assertEqual((await self.db.get_prop_sub(555))["size"], 25000)
        st, d = await self.post("/m/api/state", token=tok)
        self.assertEqual(d["user"]["id"], 555)
        self.assertEqual(d["prop"]["size"], 25000)
        # тот же Telegram к другому аккаунту — нельзя
        tok2 = await self.register("b@mail.uz")
        code2 = (await self.post("/m/api/tg/start", token=tok2))[1]["code"]
        self.assertEqual(await self.app.mobile.tg_confirm(code2, 555, "u", "U"), "taken")
        # отвязка (есть почта)
        st, d = await self.post("/m/api/tg/unlink", token=tok)
        self.assertFalse(d["me"]["telegram"])

    async def test_push_register_and_broadcast(self):
        tok = await self.register(lang="en")
        self.assertEqual((await self.post("/m/api/push", {"token": "bad"}, tok))[0], 400)
        self.assertEqual((await self.post("/m/api/push", {"token": "ExponentPushToken[abcdefghij]"}, tok))[0], 200)
        tok2 = await self.register("b@mail.uz", lang="ru")
        await self.post("/m/api/push", {"token": "ExponentPushToken[zzzzzzzzzz]"}, tok2)
        n = await self.app.mobile.push_all(lambda lang: mb.signal_push(
            lang, {"id": 9, "direction": 1, "entry": 2650, "sl": 2645, "tp": 2660}), {"type": "signal", "id": 9})
        self.assertEqual(n, 2)
        by = {m["to"]: m for m in self.app.mobile.pushed}
        self.assertIn("New signal", by["ExponentPushToken[abcdefghij]"]["title"])
        self.assertIn("Новый сигнал", by["ExponentPushToken[zzzzzzzzzz]"]["title"])
        # «только проп-сигналы» — обычный сигнал не шлём
        self.app.mobile.pushed.clear()
        uid = -(await self.app.mobile._one("SELECT id FROM app_users WHERE email='b@mail.uz'"))["id"]
        await self.app.mobile.push_all(lambda lang: ("t", "b"), {}, {uid})
        self.assertEqual([m["to"] for m in self.app.mobile.pushed], ["ExponentPushToken[abcdefghij]"])

    async def test_deliver_and_send_guard(self):
        tok = await self.register()
        await self.post("/m/api/push", {"token": "ExponentPushToken[abcdefghij]"}, tok)
        uid = -(await self.app.mobile._one("SELECT id FROM app_users"))["id"]
        self.assertFalse(await self.app._send(uid, lambda: self.app.bot.send_message(uid, "x")))
        self.assertEqual(self.app.bot.sent, [])
        self.assertTrue(await self.app.deliver(uid, lambda: self.app.bot.send_message(uid, "x"), ("T", "B")))
        self.assertEqual(self.app.bot.sent, [])
        self.assertEqual(self.app.mobile.pushed[-1]["title"], "T")
        self.assertEqual(await self.app.lang_of(uid), "uz")

    async def test_revenuecat_webhook(self):
        tok = await self.register()
        aid = (await self.app.mobile._one("SELECT id FROM app_users"))["id"]
        old = config.revenuecat_secret
        object.__setattr__(config, "revenuecat_secret", "s3cret")
        try:
            r = await self.client.post("/m/api/revenuecat", json={"event": {"type": "INITIAL_PURCHASE"}})
            self.assertEqual(r.status, 401)
            hdr = {"Authorization": "Bearer s3cret"}
            ev = {"event": {"type": "INITIAL_PURCHASE", "app_user_id": f"app_{aid}"}}
            r = await self.client.post("/m/api/revenuecat", json=ev, headers=hdr)
            self.assertEqual((await r.json())["pending"], 1)
            code = (await self.post("/m/api/tg/start", token=tok))[1]["code"]
            await self.app.mobile.tg_confirm(code, 901, "u", "U")
            self.assertEqual(await self.db.credits(901), 1)   # оплата перешла при привязке Telegram
            r = await self.client.post("/m/api/revenuecat", json=ev, headers=hdr)
            self.assertEqual((await r.json())["credits"], 2)
        finally:
            object.__setattr__(config, "revenuecat_secret", old)

    async def test_privacy_page(self):
        r = await self.client.get("/privacy")
        self.assertEqual(r.status, 200)
        self.assertIn("Delete account", await r.text())

    async def test_ping(self):
        r = await self.client.get("/m/api/ping")
        self.assertEqual((await r.json())["app"], "xauusd-gold")


if __name__ == "__main__":
    unittest.main()
