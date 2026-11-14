import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from goldbot import autotrade as at
from goldbot import prop as pr
from tests.test_autotrade import FakeApi, make_db


def acc(plan="2step", size=50_000, day_balance=None, peak=None, stage="phase1", days=0):
    return {"prop_plan": plan, "prop_size": size, "prop_day_balance": day_balance or size,
            "prop_peak": peak or size, "prop_stage": stage, "prop_days": days}


class PropMathTests(unittest.TestCase):
    def test_limits_static(self):
        lim = pr.limits(acc("2step", 50_000), 50_000)
        self.assertEqual(lim.total_floor, 45_000)
        self.assertEqual(lim.day_limit, 1_500)          # дневной стоп бота 3 %, строже 5 % FundedNext
        self.assertEqual(lim.daily_floor, 48_500)
        self.assertEqual(lim.binding, "daily")
        self.assertEqual(lim.hard_room, 2_500)          # до дневного лимита FundedNext ($2 500)
        # минус $500 за сегодня (закрытые + открытые): до лимита FundedNext остаётся $2 000
        lim = pr.limits(acc("2step", 50_000), 49_500)
        self.assertEqual((lim.day_loss, lim.hard_room, lim.room), (500, 2_000, 1_000))
        # 1-Step: дневной лимит FundedNext 3 % — он и есть дневной стоп
        self.assertEqual(pr.limits(acc("1step", 25_000), 25_000).day_limit, 750)
        # счёт уже в просадке: ближе общий лимит
        lim = pr.limits(acc("2step", 50_000, day_balance=45_100), 45_100)
        self.assertEqual(lim.binding, "total")
        self.assertAlmostEqual(lim.room, 100)

    def test_limits_instant_trailing_locks_at_start(self):
        a = acc("instant", 10_000, peak=10_300, stage="funded")
        self.assertAlmostEqual(pr.limits(a, 10_300).total_floor, 9_700)   # 10 300 − 600
        a = acc("instant", 10_000, peak=11_000, stage="funded")
        self.assertEqual(pr.limits(a, 11_000).total_floor, 10_000)       # не выше начального баланса

    def test_budget_and_volume(self):
        a = acc("2step", 25_000)
        budget, reason = pr.risk_budget(a, 25_000, [], 0.5, 0.5)
        self.assertEqual((budget, reason), (125, "risk"))         # 0.5 % от $25 000
        budget, _ = pr.risk_budget(a, 25_000, [], 10, 0.5)
        self.assertEqual(budget, 700)                             # больше 2.8 % не бывает
        # открытые сделки уже рискуют $650 до стопов: вместе не больше 2.8 % ($700) — остаётся $50
        pos = [{"type": "POSITION_TYPE_SELL", "volume": 0.65, "currentPrice": 2650, "stopLoss": 2660}]
        budget, reason = pr.risk_budget(a, 25_000, pos, 1, 0.5)
        self.assertEqual((round(budget, 2), reason), (50, "open"))
        # сегодня уже −$700: до дневного стопа бота ($750) остаётся $50
        budget, reason = pr.risk_budget(a, 24_300, [], 1, 0.5)
        self.assertEqual((round(budget, 2), reason), (50, "daily"))
        self.assertEqual(pr.volume_for(125, 20), 0.06)
        self.assertEqual(pr.volume_for(1, 20), 0)                 # даже 0.01 не помещается — сделки нет

    def test_phase_and_next_stage(self):
        a = acc("2step", 10_000, stage="phase1", days=5)
        self.assertEqual(pr.target_balance(a), 10_800)
        self.assertTrue(pr.phase_passed(a, 10_800))
        self.assertFalse(pr.phase_passed({**a, "prop_days": 4}, 10_900))   # мало торговых дней
        self.assertEqual(pr.next_stage(a), "phase2")
        self.assertEqual(pr.next_stage({**a, "prop_stage": "phase2"}), "funded")
        self.assertIsNone(pr.target_balance({**a, "prop_stage": "funded"}))
        self.assertEqual(pr.next_stage(acc("1step", stage="phase1")), "funded")

    def test_reset_time_in_tashkent(self):
        winter = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
        summer = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
        self.assertEqual(pr.reset_time("Asia/Tashkent", winter), "03:00")   # GMT+2 → 03:00 по Ташкенту
        self.assertEqual(pr.reset_time("Asia/Tashkent", summer), "02:00")   # летом GMT+3 → 02:00

    def test_day_key_fundednext_midnight(self):
        # 22:30 UTC зимой — уже 00:30 следующего дня в Афинах (GMT+2)
        self.assertEqual(pr.day_key(datetime(2026, 11, 14, 22, 30, tzinfo=timezone.utc)), "2026-11-15")
        self.assertEqual(pr.day_key(datetime(2026, 11, 14, 21, 30, tzinfo=timezone.utc)), "2026-11-14")


class PropApi(FakeApi):
    """FakeApi с балансом/средствами и позициями как у MetaApi."""

    def __init__(self, **kw):
        super().__init__(acc_type="ACCOUNT_TRADE_MODE_LIVE", symbols=("XAUUSD",), **kw)
        self.balance = self.equity
        self.pos: list[dict] = []

    async def account_info(self, acc_id, region, timeout=90):
        return {"broker": "FundedNext", "currency": "USD", "balance": self.balance, "equity": self.equity,
                "type": self.acc_type}

    async def positions(self, acc_id, region):
        return list(self.pos)

    async def trade(self, acc_id, region, req):
        self.trades.append((acc_id, req))
        if req["actionType"].startswith("ORDER_TYPE"):
            pid = str(1000 + len(self.trades))
            self.pos.append({"id": pid, "symbol": req["symbol"], "volume": req["volume"],
                             "type": "POSITION_TYPE_BUY" if req["actionType"] == "ORDER_TYPE_BUY" else "POSITION_TYPE_SELL",
                             "currentPrice": self.bid, "stopLoss": req["stopLoss"], "comment": req["comment"]})
            return {"stringCode": "TRADE_RETCODE_DONE", "orderId": pid, "positionId": pid}
        self.pos = [p for p in self.pos if p["id"] != req["positionId"]]
        return {"stringCode": "TRADE_RETCODE_DONE"}


def run(coro):
    return asyncio.run(coro)


class PropTraderTests(unittest.TestCase):
    def test_prop_connect_sizes_from_drawdown_and_guards_limits(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = PropApi(equity=25_000.0)
                tr = at.AutoTrader(db, api, poll=0, retry_delays=(0, 0), demo_only=True)
                # проп-счёт подключается и при «только демо» — это деньги фирмы
                await tr.connect(1, "mt5", "FundedNext-Server", "123", "pw",
                                 prop={"plan": "2step", "stage": "phase1", "size": 25_000})
                a = await db.get_trade_account(1)
                self.assertEqual((a["prop_plan"], a["prop_stage"], a["prop_size"]), ("2step", "phase1", 25_000))
                # стоп $20: $125 риска (0.5 % от $25 000) → 0.06 лота
                res = await tr.open_signal(1, 1, 20.0, 40.0, uids={1})
                self.assertTrue(res[0].ok, res)
                self.assertEqual(res[0].volume, 0.06)
                # сильный сигнал — 1 % ($250) → 0.12 лота
                res = await tr.open_signal(2, 1, 20.0, 40.0, uids={1}, strong=True)
                self.assertEqual(res[0].volume, 0.12)
                # открыто уже ≈ $355 риска; потолок на все открытые 2.8 % ($700) — третья сделка меньше
                for sid in (3, 4):
                    res = await tr.open_signal(sid, 1, 20.0, 40.0, uids={1}, strong=True)
                    self.assertTrue(res[0].ok, res)
                self.assertEqual(res[0].volume, 0.05)
                res = await tr.open_signal(5, 1, 20.0, 40.0, uids={1})
                self.assertFalse(res[0].ok)
                self.assertEqual(res[0].error, "PROP_LIMIT")
                # убыток за день дошёл до 3 % ($750): бот закрывает всё и до завтра не торгует
                api.equity = 24_250.0
                events = await tr.prop_check()
                self.assertEqual([e["kind"] for e in events], ["halt"])
                self.assertEqual(events[0]["limit"], "daily")
                self.assertEqual(api.pos, [])
                self.assertEqual((await db.get_trade_account(1))["prop_halt"], "daily")
                self.assertEqual(await tr.open_signal(6, 1, 20.0, 40.0, uids={1}), [])
                # новый торговый день — остановка снимается
                await db.update_prop_state(1, prop_day="2000-01-01")
                api.balance = api.equity
                events = await tr.prop_check()
                self.assertIn("new_day", [e["kind"] for e in events])
                self.assertEqual((await db.get_trade_account(1))["prop_halt"], "")
                await db.close()
        run(go())

    def test_phase_passed_disconnects_and_asks_next(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = await make_db(d)
                api = PropApi(equity=10_000.0)
                tr = at.AutoTrader(db, api, poll=0, retry_delays=(0, 0))
                await tr.connect(1, "mt5", "FundedNext-Server", "123", "pw",
                                 prop={"plan": "2step", "stage": "phase1", "size": 10_000})
                # цель есть, но торговых дней мало: бот торгует только минимальным лотом
                api.balance = api.equity = 10_850.0
                res = await tr.open_signal(1, 1, 20.0, 40.0, uids={1})
                self.assertEqual(res[0].volume, 0.01)
                self.assertEqual(await tr.prop_check(), [])            # сделка ещё открыта — этап не засчитан
                api.pos = []
                await db.update_prop_state(1, prop_days=5)
                events = await tr.prop_check()
                self.assertEqual([e["kind"] for e in events], ["passed"])
                self.assertEqual(events[0]["next"], "phase2")
                self.assertIsNone(await db.get_trade_account(1))          # отключился от счёта
                self.assertIn("acc1", api.removed)
                nxt = json.loads(await db.get_kv("prop_next:1"))
                self.assertEqual((nxt["plan"], nxt["stage"], nxt["size"]), ("2step", "phase2", 10_000))
                await db.close()
        run(go())


class PropTextsTests(unittest.TestCase):
    def test_bot_renders_prop_texts(self):
        from goldbot.i18n import t
        for lang in ("ru", "en", "uz"):
            self.assertIn("REFHGUTBT", t(lang, "prop_discount", code="REFHGUTBT", pct="5%"))


if __name__ == "__main__":
    unittest.main()


class PropBotTextTests(unittest.TestCase):
    def test_status_rules_and_events_render(self):
        from goldbot.bot import App

        sent = []

        class FakeBot:
            async def send_message(self, chat_id, text, **kw):
                sent.append((chat_id, text, kw.get("reply_markup")))

        app = App.__new__(App)
        app.bot = FakeBot()

        async def lang_of(uid):
            return "ru"

        async def _send(uid, factory):
            await factory()
            return True

        app.lang_of, app._send = lang_of, _send

        class FakeDB:
            async def get_trade_account(self, uid):   # уже подключён обычный счёт
                return {"user_id": uid, "prop_plan": None}

            async def trade_accounts(self):
                return [{"user_id": 1}]

        app.db = FakeDB()
        a = {**acc("2step", 25_000, day_balance=25_000), "equity": 24_800, "prop_halt": "daily"}
        status = app.prop_status(a, "ru")
        self.assertIn("−$200.00, осталось $550.00 из $750.00", status)
        self.assertIn("Дневной лимит", status)
        self.assertEqual(app.prop_status({"prop_plan": None}, "ru"), "")

        async def go():
            await app.prop_intro(1, "ru")
            await app.prop_rules(1, "ru", "2step", "phase1", 25_000)
            await app.prop_events([{"uid": 1, "kind": "passed", "next": "phase2",
                                    "acc": {**acc("2step", 10_000, days=5), "balance": 10_850,
                                            "prop_worst_day": 120, "prop_min_equity": 9_900}}])
        asyncio.run(go())
        intro, rules, passed = sent
        self.assertIn("REFHGUTBT", intro[1])
        self.assertEqual(intro[2].inline_keyboard[0][0].url, "https://fundednext.com")
        self.assertIn("$125", rules[1])                     # 0.5 % от $25 000
        self.assertIn("2.8% ($700)", rules[1])
        self.assertIn("Челлендж, этап 1 пройден", passed[1])
        self.assertIn("🔢 Счёт", passed[1])
        self.assertIn("+8.50%", passed[1])
        self.assertEqual(passed[2].inline_keyboard[0][0].callback_data, "at:pnext")
