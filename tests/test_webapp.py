import hashlib
import hmac
import json
import os
import re
import tempfile
import time
import unittest
from datetime import timedelta
from urllib.parse import urlencode

from aiohttp.test_utils import TestClient, TestServer

from goldbot import bot as botmod
from goldbot import prop as pr
from goldbot import webapp as wa
from goldbot.config import config
from goldbot.db import DB, now
from goldbot.webapp_lessons import LESSONS, lessons_vars
from goldbot.webapp_texts import TEXTS

TOKEN = "123456:TEST-token"


def sign(user: dict, token: str = TOKEN, auth_date: int | None = None, **extra) -> str:
    fields = {"auth_date": str(auth_date if auth_date is not None else int(time.time())),
              "query_id": "AAH", "user": json.dumps(user, separators=(",", ":")), **extra}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class FakeBot:
    def __init__(self):
        self.sent, self.invoices = [], []

    async def create_invoice_link(self, **kw):
        self.invoices.append(kw)
        return "https://t.me/$invoice" + str(len(self.invoices))

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


class Eng:
    last_price = 2650.55


class InitDataTests(unittest.TestCase):
    def test_valid(self):
        d = wa.check_init_data(sign({"id": 42, "first_name": "Ali"}), TOKEN)
        self.assertEqual(d["user"]["id"], 42)

    def test_tampered_wrong_token_and_old(self):
        good = sign({"id": 42})
        self.assertIsNone(wa.check_init_data(good.replace("42", "43"), TOKEN))
        self.assertIsNone(wa.check_init_data(good, "999:other"))
        self.assertIsNone(wa.check_init_data(sign({"id": 42}, auth_date=int(time.time()) - 2 * 86400), TOKEN))
        self.assertIsNone(wa.check_init_data("", TOKEN))
        self.assertIsNone(wa.check_init_data("garbage", TOKEN))
        self.assertIsNone(wa.check_init_data(sign({"name": "no id"}), TOKEN))

    def test_texts_same_keys(self):
        keys = set(TEXTS["ru"])
        for lang, tx in TEXTS.items():
            self.assertEqual(set(tx), keys, lang)

    def test_lessons_same_structure_all_langs(self):
        """Уроки на всех языках: одинаковые id, иконки, порядок и типы блоков, число вариантов ответа."""
        def shape(ls):
            return [(x["id"], x["icon"], x["min"], len(x["quiz"]["a"]),
                     [(b["t"], b.get("to"), len(b.get("x")) if isinstance(b.get("x"), list) else None,
                       len(b.get("rows") or [])) for b in x["blocks"]]) for x in ls]
        base = shape(LESSONS["ru"])
        self.assertGreaterEqual(len(base), 7)
        for lang in TEXTS:
            self.assertEqual(shape(LESSONS[lang]), base, lang)

    def test_lessons_content_valid(self):
        allowed = {"p", "h", "list", "tip", "warn", "ex", "plans", "calc", "go"}
        keys = set(lessons_vars())
        for lang, ls in LESSONS.items():
            ids = [x["id"] for x in ls]
            self.assertEqual(len(ids), len(set(ids)), lang)
            for x in ls:
                self.assertTrue(x["title"] and x["sub"] and x["quiz"]["q"] and x["quiz"]["why"], (lang, x["id"]))
                self.assertEqual(len(set(x["quiz"]["a"])), len(x["quiz"]["a"]), (lang, x["id"]))
                for b in x["blocks"]:
                    self.assertIn(b["t"], allowed)
                    if b["t"] == "go":
                        self.assertIn(b["to"], {"profile", "prop", "stats", "connect"})
                    text = json.dumps(b, ensure_ascii=False)
                    for ph in re.findall(r"\{(\w+)\}", text):
                        self.assertIn(ph, keys, (lang, x["id"], ph))   # подстановка знакомая приложению

    def test_lesson_numbers_match_plans(self):
        """Числа в уроках о FundedNext совпадают с правилами в goldbot/prop.py."""
        p = pr.PLANS
        self.assertEqual(p["2step"].targets["phase1"], 8)           # урок prop: $10 000 → $10 800
        self.assertEqual((p["2step"].daily_pct, p["2step"].total_pct), (5, 10))   # урок limits: $25 000
        self.assertEqual(p["1step"].daily_pct, 3)                    # квиз limits: $300
        self.assertTrue(p["instant"].trailing and p["instant"].total_pct == 6)   # $9 400 → $9 900
        self.assertEqual(pr.DD_PCT, 2.0)
        self.assertEqual(pr.DD_MULT, 0.25)
        self.assertEqual(pr.MAX_OPEN_PCT, 1.5)
        self.assertEqual(pr.DAILY_CAP_PCT, 3.0)

    def test_index_present(self):
        html = (wa.STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn("telegram-web-app.js", html)
        self.assertTrue((wa.STATIC / "logo.png").exists())


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._token = config.bot_token
        object.__setattr__(config, "bot_token", TOKEN)
        self.dir = tempfile.TemporaryDirectory()
        self.db = DB(os.path.join(self.dir.name, "t.db"))
        await self.db.connect()
        app = botmod.App.__new__(botmod.App)
        app.db, app.bot, app.engine, app.autotrader = self.db, FakeBot(), Eng(), None
        app.stars_cap = config.stars_invoice_max
        app._tasks = set()
        self.app = app
        self.web = wa.WebApp(app)
        self.client = TestClient(TestServer(self.web.make_app()))
        await self.client.start_server()
        self.hdr = {"X-Init-Data": sign({"id": 7, "first_name": "Dilshod", "language_code": "uz"})}
        # сигналы: тейк, стоп, открытый
        for d, st in ((1, "tp"), (-1, "sl"), (1, "open")):
            sid = await self.db.add_signal("combo", d, 2600.0, 2600.0 - d * 5, 2600.0 + d * 10)
            if st != "open":
                await self.db.close_signal(sid, st)

    async def asyncTearDown(self):
        await self.client.close()
        await self.db.close()
        self.dir.cleanup()
        object.__setattr__(config, "bot_token", self._token)

    async def post(self, path, body=None, hdr=None):
        r = await self.client.post("/api/" + path, json=body or {}, headers=self.hdr if hdr is None else hdr)
        return r.status, await r.json()

    async def test_no_auth(self):
        st, _ = await self.post("state", hdr={})
        self.assertEqual(st, 401)
        st, _ = await self.post("state", hdr={"X-Init-Data": sign({"id": 7}, token="1:bad")})
        self.assertEqual(st, 401)

    async def test_index_and_static(self):
        r = await self.client.get("/")
        self.assertEqual(r.status, 200)
        self.assertIn("XAUUSD", await r.text())
        r = await self.client.get("/static/logo.png")
        self.assertEqual(r.status, 200)
        r = await self.client.get("/static/../webapp.py")
        self.assertNotEqual(r.status, 200)

    async def test_state_new_user_gets_free_signals_and_lang(self):
        st, j = await self.post("state")
        self.assertEqual(st, 200)
        self.assertEqual(j["lang"], "uz")
        self.assertEqual(j["t"]["tab_home"], TEXTS["uz"]["tab_home"])
        self.assertEqual(j["sub"]["kind"], "free")
        self.assertEqual(j["user"]["name"], "Dilshod")
        self.assertEqual(j["market"]["price"], 2650.55)
        self.assertEqual(len(j["market"]["open"]), 1)
        trades = {x["status"]: x for x in j["stats"]["trades"]}
        self.assertEqual(trades["tp"]["pips"], 100.0)
        self.assertEqual(trades["sl"]["pips"], -50.0)
        self.assertIsNone(trades["open"]["pips"])
        self.assertIn("combo", j["stats"]["strategies"])
        self.assertIsNone(j["prop"])
        self.assertFalse(j["auto"]["enabled"])
        self.assertEqual(len(j["plans"]), 4)
        self.assertEqual(j["learn"]["lessons"], LESSONS["uz"])
        self.assertEqual(set(j["learn"]["vars"]), set(lessons_vars()))

    async def test_settings(self):
        st, j = await self.post("settings", {"lang": "en", "capital": 2500})
        self.assertEqual(st, 200)
        self.assertEqual(j["lang"], "en")
        self.assertEqual(j["user"]["capital"], 2500)
        self.assertGreater(j["user"]["lot"], 0)
        self.assertEqual((await self.db.get_user(7))["lang"], "en")
        st, _ = await self.post("settings", {"lang": "xx"})
        self.assertEqual(st, 400)
        st, _ = await self.post("settings", {"capital": "abc"})
        self.assertEqual(st, 400)
        st, _ = await self.post("settings", {"capital": -5})
        self.assertEqual(st, 400)

    async def test_prop_flow(self):
        st, _ = await self.post("prop", {"action": "save", "plan": "2step", "stage": "bad", "size": 10000})
        self.assertEqual(st, 400)
        st, _ = await self.post("prop", {"action": "save", "plan": "2step", "stage": "phase1", "size": 10})
        self.assertEqual(st, 400)
        st, j = await self.post("prop", {"action": "save", "plan": "2step", "stage": "phase1", "size": 10000,
                                         "only": True})
        self.assertEqual(st, 200)
        p = j["prop"]
        self.assertEqual(p["plan_name"], "Stellar 2-Step")
        self.assertEqual(p["balance"], 10000)
        self.assertAlmostEqual(p["goal"], 10800)
        self.assertTrue(p["only_prop"])
        self.assertGreater(p["day_left"], 0)
        self.assertGreater(p["risk_pct"], 0)
        # баланс выше цели → цель выполнена, следующий этап доступен
        st, j = await self.post("prop", {"action": "balance", "balance": 10850})
        self.assertTrue(j["prop"]["passed"])
        self.assertEqual(j["prop"]["next_stage"], "phase2")
        st, j = await self.post("prop", {"action": "next"})
        self.assertEqual(j["prop"]["stage"], "phase2")
        self.assertEqual(j["prop"]["balance"], 10000)
        st, j = await self.post("prop", {"action": "only", "value": False})
        self.assertFalse(j["prop"]["only_prop"])
        st, j = await self.post("prop", {"action": "off"})
        self.assertIsNone(j["prop"])
        st, _ = await self.post("prop", {"action": "nope"})
        self.assertEqual(st, 400)

    async def test_prop_funded_instant(self):
        st, j = await self.post("prop", {"action": "save", "plan": "instant", "stage": "funded", "size": 5000})
        self.assertEqual(st, 200)
        p = j["prop"]
        self.assertIsNone(p["goal"])
        self.assertIsNone(p["progress"])
        self.assertFalse(p["passed"])
        self.assertTrue(p["trailing"])

    async def test_no_signal_subscription_invoice(self):
        st, _ = await self.post("invoice", {"kind": "sub"})   # сигналы бесплатные — счёта за них нет
        self.assertEqual(st, 400)
        st, _ = await self.post("invoice", {"kind": "auto"})   # автоторговли нет — счёт не выдаём
        self.assertEqual(st, 400)
        self.assertEqual(self.app.bot.invoices, [])

    async def test_account_ownership(self):
        aid = await self.db.save_trade_account(99, "m1", "london", "mt5", "Srv", "111", "XAUUSD", "B", "USD", True)
        st, _ = await self.post("account", {"id": aid, "action": "pause"})
        self.assertEqual(st, 400)          # чужой счёт
        self.assertEqual((await self.db.get_account(aid))["enabled"], 1)
        mine = await self.db.save_trade_account(7, "m2", "london", "mt5", "Srv", "222", "XAUUSD", "B", "USD", True)
        st, _ = await self.post("account", {"id": mine, "action": "pause"})
        self.assertEqual(st, 200)
        self.assertEqual((await self.db.get_account(mine))["enabled"], 0)
        st, _ = await self.post("account", {"id": mine, "action": "resume"})
        self.assertEqual((await self.db.get_account(mine))["enabled"], 1)

    async def test_action_propsig_sends_to_chat(self):
        st, j = await self.post("action", {"do": "propsig"})
        self.assertEqual(st, 200)
        self.assertEqual(self.app.bot.sent[0][0], 7)
        st, _ = await self.post("action", {"do": "rm -rf"})
        self.assertEqual(st, 400)

    async def test_market(self):
        st, j = await self.post("market")
        self.assertEqual(st, 200)
        self.assertEqual(j["price"], 2650.55)
        self.assertEqual(len(j["open"]), 1)

    async def test_old_expired_trial_still_free(self):
        await self.post("state")
        await self.db.conn.execute("UPDATE users SET trial_until=? WHERE id=7",
                                   ((now() - timedelta(days=1)).isoformat(),))
        await self.db.conn.commit()
        _, j = await self.post("state")
        self.assertEqual(j["sub"]["kind"], "free")

if __name__ == "__main__":
    unittest.main()


class MenuButtonTests(unittest.TestCase):
    def test_app_button_first_in_menu_all_langs(self):
        for lang in ("ru", "en", "uz"):
            kb = botmod.menu(lang)
            first = kb.keyboard[0][0].text
            self.assertEqual(first, botmod.t(lang, "btn_app_menu"))
            self.assertIn(first, botmod.MENU_TEXTS)   # нажатие не попадёт во ввод капитала/баланса

    def test_inline_button_uses_current_url(self):
        app = botmod.App.__new__(botmod.App)
        app.webapp = None
        self.assertIsNone(app.app_button("ru"))
        app.webapp = wa.WebApp.__new__(wa.WebApp)
        app.webapp.url = "https://abc.trycloudflare.com"
        btn = app.app_button("uz")
        self.assertEqual(btn.web_app.url, "https://abc.trycloudflare.com")
