import asyncio
import os
import tempfile
import unittest

from goldbot import autotrade as at
from datetime import timedelta

from goldbot.db import DB, now


def run(coro):
    return asyncio.run(coro)


class FakeApi:
    """Подмена MetaApi: запоминает запросы, отвечает как настоящий REST API."""

    def __init__(self, acc_type="ACCOUNT_TRADE_MODE_DEMO", symbols=("EURUSD", "XAUUSDm", "XAUUSD.ecn"),
                 create_error=None, bid=2650.0, ask=2650.3, equity=1000.0, currency="USD"):
        self.acc_type, self.symbols_list, self.create_error = acc_type, list(symbols), create_error
        self.bid, self.ask, self.equity, self.currency = bid, ask, equity, currency
        self.calls, self.trades, self.removed = [], [], []
        self.open_positions: dict[str, set[str]] = {}
        self.n = 0
        self.polls = 0
        self.orphans = []

    async def create_account(self, **kw):
        self.calls.append(("create", kw))
        if self.create_error:
            raise at.MetaApiError("bad", self.create_error, 400)
        self.n += 1
        return {"id": f"acc{self.n}", "state": "UNDEPLOYED"}

    async def deploy(self, acc_id):
        self.calls.append(("deploy", acc_id))

    async def undeploy(self, acc_id):
        self.calls.append(("undeploy", acc_id))

    async def remove(self, acc_id):
        self.removed.append(acc_id)

    async def get_account(self, acc_id):
        self.polls += 1  # первый опрос — ещё подключается
        status = "CONNECTED" if self.polls > 1 else "DISCONNECTED"
        return {"_id": acc_id, "state": "DEPLOYED", "connectionStatus": status, "region": "london"}

    async def list_accounts(self, query):
        return [a for a in self.orphans if query in a["name"]]

    async def account_info(self, acc_id, region, timeout=90):
        assert region == "london"
        return {"broker": "Exness", "currency": self.currency, "balance": self.equity, "equity": self.equity,
                "type": self.acc_type}

    async def symbols(self, acc_id, region):
        return self.symbols_list

    async def specification(self, acc_id, region, symbol):
        return {"contractSize": 100, "minVolume": 0.01, "maxVolume": 200, "volumeStep": 0.01, "digits": 2}

    async def price(self, acc_id, region, symbol):
        return {"bid": self.bid, "ask": self.ask}

    async def positions(self, acc_id, region):
        return [{"id": p} for p in self.open_positions.get(acc_id, set())]

    async def trade(self, acc_id, region, req):
        self.trades.append((acc_id, req))
        if req["actionType"].startswith("ORDER_TYPE"):
            pid = str(1000 + len(self.trades))
            self.open_positions.setdefault(acc_id, set()).add(pid)
            return {"stringCode": "TRADE_RETCODE_DONE", "orderId": pid, "positionId": pid}
        self.open_positions[acc_id].discard(req["positionId"])
        return {"stringCode": "TRADE_RETCODE_DONE"}

    async def deals_by_position(self, acc_id, region, pid):
        return [{"profit": 0}, {"profit": 25.5, "commission": -0.7, "swap": 0}]


async def make_db(d):
    db = DB(os.path.join(d, "t.db"))
    await db.connect()
    for uid in (1, 2):
        await db.add_user(uid, None, None, 3)
        await db.extend_autotrade(uid, 30)   # автоторговля оплачена
    return db


def trader(db, api, **kw):
    kw.setdefault("retry_delays", (0, 0))
    return at.AutoTrader(db, api, poll=0, **kw)


class HelpersTests(unittest.TestCase):
    def test_pick_symbol(self):
        self.assertEqual(at.pick_symbol(["EURUSD", "XAUUSD.ecn", "XAUUSDm"]), "XAUUSDm")
        self.assertEqual(at.pick_symbol(["XAUUSDm", "XAUUSD"]), "XAUUSD")
        self.assertEqual(at.pick_symbol(["GOLD", "SILVER"]), "GOLD")
        self.assertIsNone(at.pick_symbol(["EURUSD"]))
        self.assertEqual(at.pick_symbol(["XAUUSD", "GOLD.x"], "GOLD.x"), "GOLD.x")

    def test_demo_servers(self):
        found = {"Exness": ["Exness-MT5Real7", "Exness-MT5Trial7", "Exness-MT5Trial8"], "Other": ["X-Demo"]}
        self.assertEqual(at.demo_servers(found, True), ["Exness-MT5Trial7", "Exness-MT5Trial8", "X-Demo"])
        self.assertEqual(at.demo_servers({"B": ["B-Live"]}, True), ["B-Live"])  # демо не нашли — показываем все
        self.assertEqual(at.demo_servers(found, False)[0], "Exness-MT5Real7")

    def test_calc_volume(self):
        # $1000, стоп $20 (200 пипсов), риск 2% = $20 → 0.01 лота
        self.assertEqual(at.calc_volume(1000, "USD", 20, 2, 1), 0.01)
        self.assertEqual(at.calc_volume(10000, "USD", 20, 2, 1), 0.1)
        self.assertEqual(at.calc_volume(10_000_000, "USD", 20, 2, 1), 1)      # потолок AUTOTRADE_MAX_LOT
        self.assertEqual(at.calc_volume(50, "USD", 20, 2, 1), 0.01)          # меньше минимального не бывает
        self.assertEqual(at.calc_volume(1_000_000, "USC", 20, 2, 5), 0.1)    # центовый счёт: $10 000
        self.assertEqual(at.calc_volume(0, "USD", 20, 2, 1), 0)

    def test_error_parsing(self):
        e = at._error(400, {"error": "ValidationError", "message": "Invalid login",
                            "details": {"code": "E_AUTH"}})
        self.assertEqual(e.code, "E_AUTH")
        e = at._error(400, {"message": "Server file not found E_SRV_NOT_FOUND", "details": [{"x": 1}]})
        self.assertEqual(e.code, "E_SRV_NOT_FOUND")
        e = at._error(400, {"error": "ValidationError", "message": "Validation failed",
                            "details": [{"parameter": "clientId", "message": "too long"}]})
        self.assertIn("clientId: too long", str(e))   # в логе видно, какое поле не прошло

    def test_sl_tp_dist(self):
        self.assertEqual(at.sl_tp_dist(2900, 2880, 2930, 0, 0), (20, 30))
        sd, td = at.sl_tp_dist(2900, 2880, 2930, 150, 250)
        self.assertAlmostEqual(sd, 15)
        self.assertAlmostEqual(td, 25)


class AutoTraderTests(unittest.TestCase):
    def test_retry_after_undeployed_and_no_double_open(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = FakeApi()
                tr = trader(db, api)
                await tr.connect(1, "mt5", "Exness-MT5Trial7", "1", "p")
                fails = {"n": 1}
                orig_price, orig_get = api.price, api.get_account

                async def price(*a):
                    if fails["n"]:
                        fails["n"] -= 1
                        raise at.MetaApiError("It seems like you are trying to access too many unexisting or "
                                              "undeployed trading accounts", "", 429)
                    return await orig_price(*a)

                async def get_account(acc_id):
                    return {**await orig_get(acc_id), "state": "UNDEPLOYED"}
                api.price, api.get_account = price, get_account
                res = await tr.open_signal(5, 1, 20, 30)
                self.assertTrue(res[0].ok, res[0].error)
                self.assertEqual(api.calls.count(("deploy", "acc1")), 2)   # при подключении и после сбоя
                req = api.trades[-1][1]
                self.assertNotIn("clientId", req)
                self.assertLessEqual(len(req["comment"]), 26)

                # ордер дошёл, но ответ потерялся — повтор находит позицию и второй не открывает
                orig_trade, orig_pos = api.trade, api.positions

                async def trade(acc_id, region, rq):
                    await orig_trade(acc_id, region, rq)
                    raise at.MetaApiError("MetaApi did not answer in 90s", "TIMEOUT")

                async def positions(acc_id, region):
                    return [{"id": p, "comment": "goldbot #6", "volume": 0.05}
                            for p in api.open_positions.get(acc_id, set()) if p == str(1000 + len(api.trades))]
                api.trade, api.positions = trade, positions
                n = len(api.trades)
                res = await tr.open_signal(6, 1, 20, 30)
                self.assertTrue(res[0].ok, res[0].error)
                self.assertEqual(len(api.trades), n + 1)
                api.trade, api.positions = orig_trade, orig_pos
                await db.close()
        run(go())

    def test_validation_error_not_retried_and_admin_test_trade(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = FakeApi(equity=100000)
                tr = trader(db, api)
                await tr.connect(1, "mt5", "Exness-MT5Trial7", "1", "p")
                res, closed = await tr.test_trade(1, hold=0)
                self.assertTrue(res.ok)
                self.assertEqual(res.volume, 0.01)      # тест всегда минимальным лотом
                self.assertTrue(closed and closed.ok)
                self.assertEqual(api.trades[-1][1]["actionType"], "POSITION_CLOSE_ID")
                n = len(api.trades)

                async def bad(*a):
                    raise at.MetaApiError("Validation failed (volume: bad)", "", 400)
                api.trade = bad
                res = await tr.open_signal(8, 1, 20, 30)
                self.assertFalse(res[0].ok)
                self.assertIn("volume: bad", res[0].error)
                self.assertEqual(len(api.trades), n)
                res, closed = await tr.test_trade(2, hold=0)
                self.assertEqual(res.error, "NO_ACCOUNT")
                await db.close()
        run(go())

    def test_connect_demo_account(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = FakeApi()
                info = await trader(db, api).connect(1, "mt5", "Exness-MT5Trial7", "123456", "secret")
                self.assertEqual(info["symbol"], "XAUUSDm")
                acc = await db.get_trade_account(1)
                self.assertEqual((acc["meta_id"], acc["region"], acc["symbol"], acc["demo"]),
                                 ("acc1", "london", "XAUUSDm", 1))
                self.assertNotIn("secret", str(acc))   # пароль в базе бота не хранится
                self.assertIn(("deploy", "acc1"), api.calls)
                await db.close()
        run(go())

    def test_real_account_rejected_and_removed(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = FakeApi(acc_type="ACCOUNT_TRADE_MODE_REAL")
                with self.assertRaises(at.MetaApiError) as cm:
                    await trader(db, api).connect(1, "mt5", "Exness-MT5Real7", "1", "p")
                self.assertEqual(cm.exception.code, "REAL_NOT_ALLOWED")
                self.assertEqual(api.removed, ["acc1"])        # счёт убран из MetaApi
                self.assertIsNone(await db.get_trade_account(1))
                # с AUTOTRADE_DEMO_ONLY=0 реальный счёт подключается
                await trader(db, FakeApi(acc_type="ACCOUNT_TRADE_MODE_REAL"), demo_only=False).connect(
                    1, "mt5", "Exness-MT5Real7", "1", "p")
                self.assertEqual((await db.get_trade_account(1))["demo"], 0)
                await db.close()
        run(go())

    def test_wrong_password_and_no_gold(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                with self.assertRaises(at.MetaApiError) as cm:
                    await trader(db, FakeApi(create_error="E_AUTH")).connect(1, "mt5", "S", "1", "p")
                self.assertEqual(cm.exception.code, "E_AUTH")
                api = FakeApi(symbols=["EURUSD"])
                with self.assertRaises(at.MetaApiError) as cm:
                    await trader(db, api).connect(1, "mt5", "S", "1", "p")
                self.assertEqual(cm.exception.code, "NO_GOLD")
                self.assertEqual(api.removed, ["acc1"])
                await db.close()
        run(go())

    def test_open_uses_broker_price_and_close(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = FakeApi(equity=10000)
                tr = trader(db, api)
                await tr.connect(1, "mt5", "S", "1", "p")
                await tr.connect(2, "mt5", "S", "2", "p")
                await db.set_trade_enabled(2, False)   # на паузе — сделку не открываем

                # сигнал SELL: вход у бота 2655, но у брокера bid 2650.0 → SL/TP от 2650.0
                res = await tr.open_signal(7, -1, 20, 30)
                self.assertEqual(len(res), 1)
                r = res[0]
                self.assertTrue(r.ok, r.error)
                self.assertEqual((r.uid, r.volume, r.price, r.sl, r.tp), (1, 0.1, 2650.0, 2670.0, 2620.0))
                req = api.trades[-1][1]
                self.assertEqual((req["actionType"], req["symbol"], req["stopLoss"], req["takeProfit"]),
                                 ("ORDER_TYPE_SELL", "XAUUSDm", 2670.0, 2620.0))
                # повторный вызов по тому же сигналу сделку не дублирует
                again = await tr.open_signal(7, -1, 20, 30)
                self.assertEqual([x.error for x in again], ["DUPLICATE"])
                self.assertEqual(sum(1 for _, q in api.trades if q["actionType"].startswith("ORDER")), 1)

                closed = await tr.close_signal(7)
                self.assertEqual(len(closed), 1)
                self.assertTrue(closed[0].ok)
                self.assertFalse(closed[0].already)
                self.assertEqual(closed[0].profit, 24.8)
                self.assertEqual(api.trades[-1][1]["actionType"], "POSITION_CLOSE_ID")
                self.assertEqual(await tr.close_signal(7), [])   # второй раз закрывать нечего
                await db.close()
        run(go())

    def test_close_when_broker_already_closed(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = FakeApi(equity=10000)
                tr = trader(db, api)
                await tr.connect(1, "mt5", "S", "1", "p")
                await tr.open_signal(3, 1, 20, 30)
                self.assertEqual(api.trades[-1][1]["stopLoss"], 2630.3)   # BUY: от ask 2650.3
                api.open_positions["acc1"].clear()     # брокер сам закрыл по своему TP
                closed = await tr.close_signal(3)
                self.assertTrue(closed[0].already)
                self.assertEqual(api.trades[-1][1]["actionType"], "ORDER_TYPE_BUY")  # закрывать не пытались
                await db.close()
        run(go())

    def test_kill_switch_and_expired_access(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = FakeApi(equity=10000)
                tr = trader(db, api)
                await tr.connect(1, "mt5", "S", "1", "p")
                await db.set_kv("autotrade_off", "1")
                self.assertEqual(await tr.open_signal(1, 1, 20, 30), [])
                await db.set_kv("autotrade_off", "0")
                await db.conn.execute("UPDATE users SET autotrade_until='2020-01-01T00:00:00+00:00' WHERE id=1")
                await db.conn.commit()                   # оплата автоторговли кончилась — не торгуем
                self.assertEqual(await tr.open_signal(2, 1, 20, 30), [])
                self.assertEqual(await db.autotrade_expired_accounts(), [1])
                self.assertEqual(await db.autotrade_expired_accounts(frozenset({1})), [])  # админ
                tr.exempt = frozenset({1})               # админу оплата не нужна
                self.assertEqual(len(await tr.open_signal(2, 1, 20, 30)), 1)
                tr.exempt = frozenset()
                await db.close()
        run(go())

    def test_disconnect_removes_account(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = FakeApi()
                tr = trader(db, api)
                await tr.connect(1, "mt5", "S", "1", "p")
                await tr.connect(1, "mt4", "S2", "9", "p")   # переподключение убирает старый счёт
                self.assertEqual(api.removed, ["acc1"])
                self.assertTrue(await tr.disconnect(1))
                self.assertEqual(api.removed, ["acc1", "acc2"])
                self.assertIsNone(await db.get_trade_account(1))
                self.assertFalse(await tr.disconnect(1))
                await db.close()
        run(go())

    def test_leftover_account_removed_before_new_one(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = FakeApi()
                # прошлая попытка оборвалась: в MetaApi остался счёт, которого нет в базе бота
                api.orphans = [{"_id": "old1", "name": "tg1-474908173"}, {"_id": "other", "name": "tg12-5"}]
                await trader(db, api).connect(1, "mt5", "S", "474908173", "p")
                self.assertEqual(api.removed, ["old1"])
                await db.close()
        run(go())

    def test_ask_once_list(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                self.assertEqual(sorted(await db.not_asked_autotrade()), [1, 2])
                await db.set_autotrade_asked(1)
                self.assertEqual(await db.not_asked_autotrade(), [2])
                await db.close()
        run(go())


class BillingTests(unittest.TestCase):
    def test_reminder_then_disconnect_when_paid_period_ends(self):
        from goldbot import bot as botmod

        class FakeBot:
            def __init__(self):
                self.sent = []

            async def send_message(self, uid, text, **kw):
                self.sent.append((uid, text))

            async def send_invoice(self, uid, **kw):
                self.sent.append((uid, "INVOICE " + kw["payload"]))

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = FakeApi()
                app = botmod.App.__new__(botmod.App)
                app.db, app.bot, app._connecting = db, FakeBot(), set()
                app.autotrader = trader(db, api)
                await app.autotrader.connect(1, "mt5", "S", "1", "p")
                await db.conn.execute("UPDATE users SET autotrade_until=? WHERE id=1",
                                      ((now() + timedelta(hours=5)).isoformat(),))
                await db.conn.commit()
                await app.autotrade_billing()
                await app.autotrade_billing()   # напоминание только один раз
                self.assertEqual([x for u, x in app.bot.sent if u == 1 and x.startswith("INVOICE")], ["INVOICE auto"])
                self.assertEqual(len([x for u, x in app.bot.sent if "заканчивается" in x]), 1)
                self.assertIsNotNone(await db.get_trade_account(1))
                await db.conn.execute("UPDATE users SET autotrade_until=? WHERE id=1",
                                      ((now() - timedelta(minutes=1)).isoformat(),))
                await db.conn.commit()
                await app.autotrade_billing()
                self.assertIsNone(await db.get_trade_account(1))   # счёт отключён из MetaApi
                self.assertIn("acc1", api.removed)
                self.assertTrue(any("закончилась" in x for u, x in app.bot.sent))
                await db.close()
        run(go())


class BotFlowTests(unittest.TestCase):
    def test_signal_opens_and_close_reports(self):
        from goldbot import bot as botmod
        from goldbot.engine import NewSignal

        class FakeBot:
            def __init__(self):
                self.sent = []

            async def send_photo(self, uid, photo, caption=None, **kw):
                self.sent.append((uid, caption))

            async def send_message(self, uid, text, **kw):
                self.sent.append((uid, text))

        class Eng:
            def df_for(self, key=None):
                return None

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = FakeApi(equity=10000)
                app = botmod.App.__new__(botmod.App)
                app.db, app.bot, app.engine = db, FakeBot(), Eng()
                app.autotrader = trader(db, api)
                await app.autotrader.connect(1, "mt5", "S", "1", "p")
                sid = await db.add_signal("combo", 1, 2900, 2880, 2930)
                s = NewSignal(sid, 1, 2900, 2880, 2930, b"PNG", {"ru": "x", "en": "x", "uz": "x"},
                              sl_pips=200, tp_pips=300)
                await app.broadcast_signal(s)
                await asyncio.gather(*app._tasks)
                texts = [x for u, x in app.bot.sent if u == 1 and x and "🤖" in x]
                self.assertTrue(any("XAUUSDm" in x and "0.10" in x and "2630.30" in x for x in texts), texts)
                app.bot.sent.clear()
                sig = await db.get_signal(sid)
                await db.close_signal(sid, "tp")
                await app.broadcast_close(sig, "tp", 2930)
                await asyncio.gather(*app._tasks)
                self.assertTrue(any("+24.80 USD" in (x or "") for u, x in app.bot.sent if u == 1))
                await db.close()
        run(go())


if __name__ == "__main__":
    unittest.main()


class RestClientTests(unittest.TestCase):
    """Настоящий клиент MetaApi против локального сервера с ответами как у MetaApi."""

    def test_create_with_202_then_trade(self):
        from aiohttp import web

        async def go():
            seen = {"tids": [], "posts": 0}

            async def create(req):
                seen["tids"].append(req.headers.get("transaction-id"))
                assert req.headers.get("auth-token") == "tok"
                seen["posts"] += 1
                n = seen["posts"]
                body = await req.json()
                if n == 1:  # ответ не успел прийти — клиент должен повторить с тем же id
                    await asyncio.sleep(3)
                    return web.json_response({}, status=500)
                if n == 2:  # MetaApi ещё определяет настройки брокера
                    return web.json_response({"message": "retry"}, status=202, headers={"Retry-After": "0"})
                assert body["login"] == "123" and body["platform"] == "mt5"
                return web.json_response({"id": "abc", "state": "UNDEPLOYED"}, status=201)

            async def trade(req):
                body = await req.json()
                if body["volume"] > 5:
                    return web.json_response({"numericCode": 10019, "stringCode": "TRADE_RETCODE_NO_MONEY",
                                              "message": "No money"})
                return web.json_response({"numericCode": 10009, "stringCode": "TRADE_RETCODE_DONE",
                                          "orderId": "77", "positionId": "77"})

            async def search(req):
                return web.json_response({"Exness": ["Exness-MT5Trial7"]})

            async def bad_auth(req):
                return web.json_response({"error": "ValidationError", "message": "Invalid credentials",
                                          "details": {"code": "E_AUTH"}}, status=400)

            app = web.Application()
            app.router.add_post("/users/current/accounts", create)
            app.router.add_post("/users/current/accounts/abc/trade", trade)
            app.router.add_get("/known-mt-servers/5/search", search)
            app.router.add_post("/users/current/accounts/bad/deploy", bad_auth)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            old = at.PROVISIONING, at.CLIENT
            at.PROVISIONING = at.CLIENT = f"http://127.0.0.1:{port}"
            api = at.MetaApi("tok")
            orig = api.request

            async def short(method, url, json=None, headers=None, timeout=90):
                return await orig(method, url, json, headers, timeout=min(timeout, 1))
            api.request = short
            try:
                acc = await api.create_account(name="n", login="123", password="p", server="S", platform="mt5",
                                               magic=1)
                self.assertEqual(acc["id"], "abc")
                self.assertEqual(seen["posts"], 3)
                self.assertEqual(len(set(seen["tids"])), 1)   # повтор с тем же transaction-id
                self.assertEqual(len(seen["tids"][0]), 32)
                r = await api.trade("abc", "x", {"actionType": "ORDER_TYPE_BUY", "volume": 0.1})
                self.assertEqual(r["positionId"], "77")
                with self.assertRaises(at.MetaApiError) as cm:
                    await api.trade("abc", "x", {"actionType": "ORDER_TYPE_BUY", "volume": 10})
                self.assertEqual(cm.exception.code, "TRADE_RETCODE_NO_MONEY")
                self.assertEqual(await api.search_servers(5, "Exness"), {"Exness": ["Exness-MT5Trial7"]})
                with self.assertRaises(at.MetaApiError) as cm:
                    await api.deploy("bad")
                self.assertEqual(cm.exception.code, "E_AUTH")
            finally:
                at.PROVISIONING, at.CLIENT = old
                await api.close()
                await runner.cleanup()
        run(go())


class TelegramDialogTests(unittest.TestCase):
    """Весь диалог через диспетчер aiogram: /start → язык → капитал → «Да» → брокер → сервер → логин → пароль."""

    def test_full_dialog(self):
        from aiogram.client.session.base import BaseSession
        from aiogram.methods import DeleteMessage, EditMessageReplyMarkup, SendInvoice, SendMessage
        from aiogram.types import Update

        from goldbot import bot as botmod
        from goldbot.config import config

        class Session(BaseSession):
            def __init__(self):
                super().__init__()
                self.log = []

            async def make_request(self, bot, method, timeout=None):
                self.log.append(method)
                if isinstance(method, (SendMessage, SendInvoice)):
                    return {"message_id": len(self.log), "date": 0, "chat": {"id": method.chat_id, "type": "private"},
                            "text": getattr(method, "text", None) or "invoice"}
                if isinstance(method, (DeleteMessage, EditMessageReplyMarkup)):
                    return True
                return True

            async def close(self):
                pass

            async def stream_content(self, *a, **kw):
                yield b""

        texts = lambda s: [m.text for m in s.log if isinstance(m, SendMessage)]  # noqa: E731

        def kb_data(s):
            for m in reversed(s.log):
                if isinstance(m, SendMessage) and m.reply_markup is not None and hasattr(m.reply_markup, "inline_keyboard"):
                    return [b.callback_data for row in m.reply_markup.inline_keyboard for b in row]
            return []

        async def go():
            with tempfile.TemporaryDirectory() as d:
                patch = {"metaapi_token": "tok", "autotrade_price_stars": 1500, "admin_ids": set(), "db_path": os.path.join(d, "t.db"), "bot_token": "123:ABC",
                         "twelvedata_key": "x", "data_provider": "twelvedata", "autotrade_demo_only": True}
                saved = {k: getattr(config, k) for k in patch}
                for k, v in patch.items():
                    object.__setattr__(config, k, v)
                try:
                    app = botmod.App()
                    session = Session()
                    app.bot.session = session
                    api = FakeApi(equity=5000)

                    async def search(version, q):
                        return {"Exness Technologies": ["Exness-MT5Real8", "Exness-MT5Trial7"]}
                    api.search_servers = search
                    app.autotrader.api = api
                    app.autotrader.poll = 0
                    await app.db.connect()
                    n = [0]
                    user = {"id": 42, "is_bot": False, "first_name": "Ali"}
                    chat = {"id": 42, "type": "private"}

                    async def msg(text):
                        n[0] += 1
                        await app.dp.feed_update(app.bot, Update.model_validate({"update_id": n[0], "message": {
                            "message_id": 1000 + n[0], "date": 0, "chat": chat, "from": user, "text": text}}))

                    async def tap(data):
                        n[0] += 1
                        await app.dp.feed_update(app.bot, Update.model_validate({"update_id": n[0], "callback_query": {
                            "id": str(n[0]), "from": user, "chat_instance": "x", "data": data,
                            "message": {"message_id": 5, "date": 0, "chat": chat, "text": "q"}}}))

                    await msg("/start")
                    await tap("lang:ru")
                    await tap("cap:1000")
                    self.assertIn("Подключить бота к вашему торговому счёту", texts(session)[-1])
                    self.assertEqual(kb_data(session), ["at:yes", "at:no", "at:prop"])
                    self.assertIn("1500 ⭐", texts(session)[-1])          # в вопросе есть цена
                    await tap("at:yes")
                    # без оплаты подключать нельзя: сначала счёт на оплату автоторговли
                    self.assertIn("платная", texts(session)[-1])
                    inv = [m for m in session.log if isinstance(m, SendInvoice)][-1]
                    self.assertEqual((inv.payload, inv.prices[0].amount, inv.currency), ("auto", 1500, "XTR"))
                    n[0] += 1
                    await app.dp.feed_update(app.bot, Update.model_validate({"update_id": n[0], "message": {
                        "message_id": 900, "date": 0, "chat": chat, "from": user, "successful_payment": {
                            "currency": "XTR", "total_amount": 1500, "invoice_payload": "auto",
                            "telegram_payment_charge_id": "ch1", "provider_payment_charge_id": "p1"}}}))
                    self.assertTrue(app.db.autotrade_until(await app.db.get_user(42)))
                    self.assertIn("демо-счета", texts(session)[-1])     # после оплаты сразу шаг подключения
                    await tap("at:agree")
                    await tap("at:pf:mt5")
                    self.assertIn("at:br:0", kb_data(session))
                    await tap("at:br:0")                            # Exness
                    self.assertEqual(kb_data(session)[:1], ["at:sv:0"])
                    self.assertNotIn("Exness-MT5Real8", str(session.log[-1].reply_markup))  # только демо
                    await tap("at:sv:0")
                    self.assertIn("Exness-MT5Trial7", texts(session)[-1])
                    await msg("abc")                                # не цифры
                    self.assertIn("только цифры", texts(session)[-1])
                    await msg("98765432")
                    self.assertIn("пароль", texts(session)[-1])
                    await msg("Secret#Pass1")
                    self.assertTrue(any(isinstance(m, DeleteMessage) and m.message_id == 1000 + n[0]
                                        for m in session.log))      # сообщение с паролем удалено
                    await asyncio.gather(*app._tasks)
                    self.assertIn("Счёт подключён", texts(session)[-1])
                    self.assertEqual(api.calls[0][1]["password"], "Secret#Pass1")
                    self.assertEqual(api.calls[0][1]["server"], "Exness-MT5Trial7")
                    acc = await app.db.get_trade_account(42)
                    self.assertEqual((acc["login"], acc["symbol"]), ("98765432", "XAUUSDm"))
                    self.assertNotIn("Secret", str(await app.db.all_users()))

                    await msg("🤖 Автоторговля")                     # кнопка меню: статус и управление
                    self.assertIn("98765432", texts(session)[-1])
                    self.assertEqual(kb_data(session), ["at:pause", "at:pay", "at:disc"])
                    self.assertIn("Оплачено до", texts(session)[-1])
                    await tap("at:pause")
                    self.assertEqual((await app.db.get_trade_account(42))["enabled"], 0)
                    await tap("at:disc")
                    self.assertIsNone(await app.db.get_trade_account(42))
                    self.assertIn("acc1", api.removed)

                    # /start ещё раз — вопрос про автоторговлю второй раз не задаётся
                    before = len(texts(session))
                    await msg("/start")
                    self.assertFalse(any("Подключить бота" in x for x in texts(session)[before:]))
                    await app.db.close()
                finally:
                    for k, v in saved.items():
                        object.__setattr__(config, k, v)
        run(go())


class MarketFeedTests(unittest.TestCase):
    def test_failover_switches_at_once_and_comes_back(self):
        import pandas as pd

        from goldbot.market import Failover, Provider

        class Slow(Provider):
            def __init__(self):
                self.hang, self.fail, self.calls = False, False, 0

            async def candles(self, tf, count):
                return pd.DataFrame({"close": [1.0]})

            async def price(self):
                self.calls += 1
                if self.hang:
                    await asyncio.sleep(30)
                if self.fail:
                    raise RuntimeError("down")
                return 2650.0

        class Backup(Provider):
            async def candles(self, tf, count):
                return pd.DataFrame({"close": [2.0]})

            async def price(self):
                return 2653.5

        async def go():
            loop = asyncio.get_running_loop()
            p, b = Slow(), Backup()
            f = Failover(p, b, price_timeout=0.2, cooldown=0.5)
            self.assertEqual(await f.price(), 2650.0)
            p.hang = True
            t0 = loop.time()
            self.assertEqual(await f.price(), 2653.5)          # не ответил за 0.2 с — сразу запасной
            self.assertLess(loop.time() - t0, 1)
            calls = p.calls
            self.assertEqual(await f.price(), 2653.5)          # в паузе основной даже не спрашиваем
            self.assertEqual(p.calls, calls)
            # свечи переключаются отдельно: сбой цены не уводит свечи с графика брокера
            self.assertEqual((await f.candles("5min", 1))["close"].iloc[0], 1.0)
            self.assertEqual(f.backup_for, {"price"})
            self.assertIn("price: TimeoutError", f.last_error)
            p.hang = False
            await asyncio.sleep(0.6)
            self.assertEqual(await f.price(), 2650.0)          # вернулся — снова цены брокера
            self.assertFalse(f.on_backup)
            p.fail = True
            self.assertEqual(await f.price(), 2653.5)          # ошибка — тоже сразу запасной
        run(go())

    def test_broker_market_reads_candles_and_bid(self):
        from aiohttp import web

        async def go():
            async def candles(req):
                assert req.match_info["tf"] == "15m" and req.query["limit"] == "3"
                # MetaApi может вернуть свечи от новых к старым — бот сортирует сам
                return web.json_response([
                    {"time": "2026-11-12T10:30:00.000Z", "open": 3, "high": 4, "low": 2, "close": 3.5, "tickVolume": 9},
                    {"time": "2026-11-12T10:15:00.000Z", "open": 2, "high": 3, "low": 1, "close": 2.5, "tickVolume": 8},
                    {"time": "2026-11-12T10:00:00.000Z", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "tickVolume": 7}])

            async def price(req):
                assert req.query.get("keepSubscription") == "true"
                return web.json_response({"symbol": "XAUUSD", "bid": 4131.8, "ask": 4132.0})

            app = web.Application()
            app.router.add_get("/users/current/accounts/m1/historical-market-data/symbols/XAUUSD/timeframes/{tf}/candles",
                               candles)
            app.router.add_get("/users/current/accounts/m1/symbols/XAUUSD/current-price", price)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            old = at.CLIENT, at.MARKET
            at.CLIENT = at.MARKET = f"http://127.0.0.1:{port}"
            api = at.MetaApi("tok")

            async def src():
                return {"meta_id": "m1", "region": "london", "symbol": "XAUUSD"}
            try:
                bm = at.BrokerMarket(api, src)
                df = await bm.candles("15min", 3)
                self.assertEqual(list(df["close"]), [1.5, 2.5, 3.5])
                self.assertEqual(str(df.index[0]), "2026-11-12 10:00:00")
                self.assertEqual(await bm.price(), 4131.8)

                async def none():
                    return None
                with self.assertRaises(at.MetaApiError):
                    await at.BrokerMarket(api, none).price()   # счёта нет → запасной источник
            finally:
                at.CLIENT, at.MARKET = old
                await api.close()
                await runner.cleanup()
        run(go())
