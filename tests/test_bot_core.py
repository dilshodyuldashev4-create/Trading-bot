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


class HybridProviderTests(unittest.TestCase):
    def test_price_and_candles_from_different_sources(self):
        from goldbot.market import Hybrid

        class Src:
            def __init__(self, p):
                self.p, self.calls = p, []

            async def candles(self, tf, count):
                self.calls.append(("candles", tf))
                return "df"

            async def price(self):
                self.calls.append(("price",))
                return self.p

            async def close(self):
                pass

        a, b = Src(1.0), Src(2.0)
        h = Hybrid(a, b)
        self.assertEqual(run(h.price()), 2.0)
        self.assertEqual(run(h.candles("5min", 10)), "df")
        self.assertEqual(a.calls, [("candles", "5min")])
        self.assertEqual(b.calls, [("price",)])


class GoldApiTests(unittest.TestCase):
    def test_parses_price(self):
        from goldbot.market import GoldApiPrice

        g = GoldApiPrice()

        async def fake_get(url, **kw):
            return {"name": "Gold", "price": 4062.899902, "symbol": "XAU"}
        g._get = fake_get
        self.assertAlmostEqual(run(g.price()), 4062.899902)

        async def empty(url, **kw):
            return {"error": "x"}
        g._get = empty
        with self.assertRaises(RuntimeError):
            run(g.price())

    def test_make_provider_goldapi(self):
        from types import SimpleNamespace
        from goldbot.market import GoldApiPrice, Hybrid, make_provider
        cfg = SimpleNamespace(data_provider="twelvedata", twelvedata_key="k", price_provider="goldapi",
                              finnhub_key="", finnhub_symbol="")
        p = make_provider(cfg)
        self.assertIsInstance(p, Hybrid)
        self.assertIsInstance(p.p, GoldApiPrice)


class NewsPauseTests(unittest.TestCase):
    def test_pause_around_high_usd_news(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                t0 = pd.Timestamp("2026-11-06 13:30", tz="UTC")
                ev = lambda title, imp, ts: {"key": title, "ts": ts.isoformat(), "country": "USD", "title": title,
                                             "impact": imp, "forecast": "", "previous": "", "actual": ""}
                await db.upsert_events([ev("Non-Farm Employment Change", "High", t0),
                                        ev("Factory Orders", "Medium", t0 + pd.Timedelta(hours=3))])
                eng = SignalEngine(db, None, "combo", 100, 200, "UTC", None, None)
                self.assertIsNone(await eng.news_pause(t0))          # по умолчанию выключено
                eng.news_pause_min = 30
                self.assertEqual((await eng.news_pause(t0 - pd.Timedelta(minutes=20)))["title"],
                                 "Non-Farm Employment Change")
                self.assertIsNotNone(await eng.news_pause(t0 + pd.Timedelta(minutes=29)))
                self.assertIsNone(await eng.news_pause(t0 + pd.Timedelta(minutes=45)))
                self.assertIsNone(await eng.news_pause(t0 + pd.Timedelta(hours=3)))  # Medium не блокирует
                eng.news_pause_impact = ("High", "Medium")
                self.assertIsNotNone(await eng.news_pause(t0 + pd.Timedelta(hours=3)))
                await db.close()
        run(go())


class ExcursionTests(unittest.TestCase):
    def test_tracks_best_and_worst_move(self):
        from goldbot.bot import excursion_text

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                closed = []

                async def on_close(s, status, price):
                    closed.append((s, status))
                eng = SignalEngine(db, None, "combo", 100, 200, "UTC", None, on_close)
                await db.add_signal("combo", -1, 4070.0, 4080.0, 4050.0)   # SELL
                for p in (4066.5, 4071.0, 4064.0, 4075.0, 4080.5):          # +60 пипсов, потом стоп
                    await eng.check_open(p)
                s, status = closed[0]
                self.assertEqual(status, "sl")
                self.assertAlmostEqual(s["mfe"], 60, places=3)
                self.assertIn("+60", excursion_text("ru", s, "sl"))
                self.assertIn("4064.00", excursion_text("ru", s, "sl"))
                await db.add_signal("combo", 1, 4000.0, 3990.0, 4020.0)    # BUY: просадка 35, потом тейк
                for p in (3996.5, 4010.0, 4020.0):
                    await eng.check_open(p)
                s, status = closed[1]
                self.assertEqual(status, "tp")
                self.assertIn("−35", excursion_text("ru", s, "tp"))
                await db.close()
        run(go())


class ExcursionChartTests(unittest.TestCase):
    def test_close_chart_with_max_lines(self):
        df = m5_frame(days=1)
        e = float(df.close.iloc[-1])
        png = render_signal(df, -1, e, e + 10, e - 20, "XAUUSD · #1 · STOP LOSS", mfe=60, mae=100)
        self.assertTrue(png.startswith(b"\x89PNG"))


class NewsBiasFilterTests(unittest.TestCase):
    def test_strong_background_blocks_opposite_signals(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                sent, seen = [], []

                async def on_signal(s):
                    sent.append(s)

                async def on_close(s, status, price):
                    pass

                async def bias(market):
                    seen.append(market)
                    return {"bias": "bullish", "strength": "strong", "reason": ""}  # SELL запрещены

                df = m5_frame(days=20, start="2025-03-03 00:00")
                prov = Replay(df, start=300)
                eng = SignalEngine(db, prov, "fvg_m5", 30, 60, "UTC", on_signal, on_close)
                eng.news_bias, eng.news_block = bias, True
                while prov.pos < len(df):
                    prov.step()
                    await eng.tick(now=(df.index[prov.pos - 1] + pd.Timedelta(minutes=5)).tz_localize("UTC"))
                self.assertTrue(seen, "фильтр должен был спрашиваться")
                self.assertIn("XAUUSD", seen[0])
                self.assertTrue(all(s.direction == 1 for s in sent))
                self.assertIn("в пользу сделки", sent[0].texts["ru"])
                await db.close()
        run(go())

    def test_strong_bias_mapping(self):
        from goldbot.news import NewsService

        async def go():
            svc = NewsService((), "m")
            old = os.environ.pop("ANTHROPIC_API_KEY", None), os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
            try:
                self.assertEqual(await svc.strong_bias(), 0)          # без ключа — не мешаем сигналам
                os.environ["ANTHROPIC_API_KEY"] = "x"

                async def headlines():
                    return [{"title": "Gold jumps as war escalates", "summary": ""}]
                answers = iter([{"bias": "bullish", "strength": "strong", "reason": "war"}])

                async def ask(items, market):
                    return next(answers)
                svc.headlines, svc._ask_bias = headlines, ask
                self.assertEqual(await svc.strong_bias("XAUUSD 4000"), 1)
                self.assertEqual(await svc.strong_bias(), 1)          # из кэша, второй раз не спрашиваем
            finally:
                os.environ.pop("ANTHROPIC_API_KEY", None)
                for k, v in zip(("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"), old):
                    if v is not None:
                        os.environ[k] = v
        run(go())


class NewsLineTests(unittest.TestCase):
    def test_line_only_writes(self):
        from goldbot.engine import news_line
        self.assertEqual(news_line(None, 1), "")
        self.assertIn("против сделки", news_line({"bias": "bearish", "strength": "strong"}, 1))
        self.assertIn("➡️", news_line({"bias": "neutral", "strength": "weak"}, -1, "en"))


class TradeStartTests(unittest.TestCase):
    def test_no_signals_before_start_and_morning_review(self):
        from goldbot.engine import parse_hhmm, session_open

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                df = m5_frame(days=6, start="2025-03-09 00:00")
                prov = Replay(df, start=len(df))
                eng = SignalEngine(db, prov, "combo", 100, 200, "Asia/Tashkent", None, None)
                ts = lambda s: pd.Timestamp(s, tz="Asia/Tashkent").tz_convert("UTC")
                self.assertFalse(eng.before_trade_start(ts("2025-03-12 05:00")))   # без настройки — всегда можно
                eng.trade_start = parse_hhmm("08:00")
                # летом в США сессия открывается в 03:00 по Ташкенту
                self.assertEqual(session_open(ts("2025-03-12 05:00")).tz_convert("Asia/Tashkent").hour, 3)
                self.assertTrue(eng.before_trade_start(ts("2025-03-12 05:00")))
                self.assertFalse(eng.before_trade_start(ts("2025-03-12 08:05")))
                self.assertFalse(eng.before_trade_start(ts("2025-03-12 23:00")))
                self.assertFalse(eng.before_trade_start(ts("2025-03-13 01:00")))   # ночь до закрытия сессии
                eng._trend = (ts("2025-03-14 08:00").normalize(), 1)
                text = await eng.morning_review("ru", ts("2025-03-14 08:00"),
                                                {"bias": "bullish", "strength": "strong"})
                for part in ("Утренний разбор", "Прошлый день", "Цена сейчас", "ценарий", "начинает давать"):
                    self.assertIn(part, text)
                await db.close()
        run(go())


class NewsCloseTests(unittest.TestCase):
    def test_open_trades_closed_before_high_news(self):
        from goldbot.bot import stats_text

        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                t0 = pd.Timestamp("2026-11-06 13:30", tz="UTC")
                await db.upsert_events([{"key": "nfp", "ts": t0.isoformat(), "country": "USD",
                                         "title": "Non-Farm Employment Change", "impact": "High",
                                         "forecast": "", "previous": "", "actual": ""}])
                got = []

                async def on_news_close(s, price, ev, mins):
                    got.append((s["id"], price, ev["title"], mins))
                eng = SignalEngine(db, None, "combo", 100, 200, "UTC", None, None)
                eng.on_news_close = on_news_close
                sid = await db.add_signal("combo", -1, 4070.0, 4080.0, 4050.0)
                self.assertEqual(await eng.news_close_check(t0 - pd.Timedelta(minutes=29), 4065.0), 0)  # выключено
                eng.news_close_min = 30
                self.assertEqual(await eng.news_close_check(t0 - pd.Timedelta(minutes=45), 4065.0), 0)  # рано
                self.assertEqual(await eng.news_close_check(t0 - pd.Timedelta(minutes=29), 4065.0), 1)
                self.assertEqual(got, [(sid, 4065.0, "Non-Farm Employment Change", 29)])
                self.assertEqual(await db.open_signals(), [])
                rows = await db.last_signals(10)
                self.assertEqual(rows[0]["status"], "news")
                self.assertIn("+50", stats_text("ru", rows, "UTC"))
                await db.close()
        run(go())
