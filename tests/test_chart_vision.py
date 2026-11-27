"""Разбор графика по скриншоту: лимит в день, контекст бота, языки, ошибки."""
import asyncio
import io
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from goldbot import bot as botmod
from goldbot import chart_vision
from goldbot.config import config
from goldbot.db import DB
from goldbot.i18n import TEXTS, t
from tests.test_channel import make_app

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


class FakeMsg:
    def __init__(self, uid, caption=None):
        self.from_user = SimpleNamespace(id=uid, username=None, first_name="U")
        self.chat = SimpleNamespace(id=uid, type="private")
        self.photo = [SimpleNamespace(file_id="small"), SimpleNamespace(file_id="big")]
        self.document = None
        self.caption = caption
        self.message_id = 7
        self.answers = []

    async def answer(self, text, **kw):
        self.answers.append(text)
        return SimpleNamespace(delete=self._noop)

    async def _noop(self):
        return None


class Eng:
    async def fresh_price(self):
        return 4123.45

    async def daily_trend(self, now):
        return 1


async def make(d):
    db = DB(os.path.join(d, "t.db"))
    await db.connect()
    app = make_app(db)
    app.engine = Eng()
    app.news = SimpleNamespace(_bias=(0, {"bias": "bullish", "strength": "strong"}))
    app._chart_busy = set()
    app.is_admin = lambda uid: uid == 1

    async def download(file_id):
        app.downloaded = file_id
        return io.BytesIO(PNG)
    app.bot.download = download
    await db.add_user(5, None, "U")
    await db.set_lang(5, "uz")
    return db, app


class ChartVisionTests(unittest.TestCase):
    def setUp(self):
        os.environ["ANTHROPIC_API_KEY"] = "test"

    def tearDown(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_media_type(self):
        self.assertEqual(chart_vision.media_type(PNG), "image/png")
        self.assertEqual(chart_vision.media_type(b"RIFF\0\0\0\0WEBPxx"), "image/webp")
        self.assertEqual(chart_vision.media_type(b"\xff\xd8\xff"), "image/jpeg")

    def test_request_has_image_and_context(self):
        sent = {}

        class Msgs:
            async def create(self, **kw):
                sent.update(kw)
                return SimpleNamespace(stop_reason="end_turn",
                                       content=[SimpleNamespace(type="text", text="Trend <up>")])

        fake = SimpleNamespace(beta=SimpleNamespace(messages=Msgs()))
        with mock.patch("anthropic.AsyncAnthropic", lambda **k: fake):
            out = asyncio.run(chart_vision.analyze(PNG, "Russian", "price 4100", "m", "где стоп?"))
        self.assertEqual(out, "Trend &lt;up&gt;")   # экранировано для HTML
        img, note = sent["messages"][0]["content"]
        self.assertEqual(img["source"]["media_type"], "image/png")
        self.assertIn("где стоп?", note["text"])
        self.assertIn("price 4100", sent["system"])
        self.assertIn("Russian", sent["system"])

    def test_api_error_reason_and_plain_retry(self):
        import anthropic

        def err(status, msg):
            cls = anthropic.BadRequestError if status == 400 else anthropic.NotFoundError
            e = cls.__new__(cls)
            Exception.__init__(e, msg)
            e.message, e.status_code = msg, status
            return e

        calls = []

        class Beta:
            async def create(self, **kw):
                calls.append("beta")
                raise err(400, "fallbacks: unknown field")

        class Plain:
            async def create(self, **kw):
                calls.append("plain")
                raise err(404, "model: claude-x not found")

        fake = SimpleNamespace(beta=SimpleNamespace(messages=Beta()), messages=Plain())
        with mock.patch("anthropic.AsyncAnthropic", lambda **k: fake):
            with self.assertRaises(chart_vision.ChartVisionError) as cm:
                asyncio.run(chart_vision.analyze(PNG, "Russian", "", "claude-x"))
        self.assertEqual(calls, ["beta", "plain"])
        self.assertIn("модель недоступна", str(cm.exception))
        e = err(400, "Your credit balance is too low to access the Anthropic API.")
        self.assertIn("закончились деньги", chart_vision._reason(e))

    def test_texts_and_menu_button(self):
        for lang in TEXTS:
            self.assertIn("{limit}", TEXTS[lang]["chart_hint"])
            self.assertIn(t(lang, "btn_chart"), botmod.MENU_TEXTS)
            texts = [b.text for row in botmod.menu(lang).keyboard for b in row]
            self.assertIn(t(lang, "btn_chart"), texts)

    def test_daily_limit_context_and_language(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db, app = await make(d)
                calls = []

                async def fake(image, language, market, model, caption=""):
                    calls.append((image, language, market, caption))
                    return "📈 Trend: up &lt;test&gt;"
                with mock.patch.object(chart_vision, "analyze", fake):
                    for _ in range(config.chart_ai_daily):
                        await app.chart_review(FakeMsg(5, caption="buy?"))
                    m = FakeMsg(5)
                    await app.chart_review(m)   # лимит исчерпан
                self.assertEqual(len(calls), config.chart_ai_daily)
                self.assertEqual(app.downloaded, "big")   # самое большое фото
                image, language, market, caption = calls[0]
                self.assertEqual(image, PNG)
                self.assertEqual(language, "Uzbek (Latin script)")
                self.assertEqual(caption, "buy?")
                for s in ("4123.45", "daily trend", "up", "no open signal", "bullish"):
                    self.assertIn(s, market)
                self.assertIn(t("uz", "chart_limit", limit=config.chart_ai_daily), m.answers)
                reply = app.bot.sent[0][1]
                self.assertIn("Trend: up", reply)
                self.assertIn(t("uz", "chart_disclaimer"), reply)
                self.assertIn(t("uz", "chart_left", left=config.chart_ai_daily - 1, limit=config.chart_ai_daily),
                              reply)
                await db.close()
        asyncio.run(go())

    def test_admin_unlimited_and_failure_not_charged(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db, app = await make(d)

                async def ok(*a, **k):
                    return "ok"

                async def fail(*a, **k):
                    raise chart_vision.ChartVisionError("на счёте Claude закончились деньги")
                with mock.patch.object(chart_vision, "analyze", ok):
                    for _ in range(config.chart_ai_daily + 2):
                        await app.chart_review(FakeMsg(1))
                self.assertEqual(len(app.bot.sent), config.chart_ai_daily + 2)
                self.assertNotIn("🎁", app.bot.sent[-1][1])   # админу без счётчика
                with mock.patch.object(chart_vision, "analyze", fail):
                    m = FakeMsg(5)
                    await app.chart_review(m)
                self.assertEqual(m.answers[-1], t("uz", "chart_fail"))   # подписчику причину не показываем
                with mock.patch.object(chart_vision, "analyze", fail):
                    adm = FakeMsg(1)
                    await app.chart_review(adm)
                self.assertIn("закончились деньги", adm.answers[-1])      # админу — причина
                self.assertEqual(await app.chart_left(5), config.chart_ai_daily)   # неудача не списана
                await db.close()
        asyncio.run(go())

    def test_no_key_says_unavailable(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db, app = await make(d)
                os.environ.pop("ANTHROPIC_API_KEY", None)
                m = FakeMsg(5)
                await app.chart_review(m)
                self.assertEqual(m.answers, [t("uz", "chart_off")])
                await db.close()
        asyncio.run(go())

    def test_open_signal_in_context(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db, app = await make(d)

                async def opened():
                    return [{"id": 9, "direction": -1, "entry": 4130.0, "sl": 4140.0, "tp": 4100.0}]
                db.open_signals = opened
                ctx = await app.chart_context(5)
                self.assertIn("#9: SELL entry 4130.00, SL 4140.00, TP 4100.00", ctx)
                await db.close()
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
