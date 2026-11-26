import asyncio
import re
import unittest

from goldbot import bot as botmod
from goldbot import video_course as vc
from goldbot.webapp_texts import TEXTS as APP_TEXTS


class FakeResp:
    def __init__(self, status):
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    """oEmbed: 404 для удалённых видео, сетевой сбой для одного."""
    def __init__(self, gone=(), broken=()):
        self.gone, self.broken = set(gone), set(broken)

    def get(self, url, **kw):
        yt = url.rsplit("v=", 1)[1]
        if yt in self.broken:
            raise OSError("network")
        return FakeResp(404 if yt in self.gone else 200)


class VideoCourseTests(unittest.TestCase):
    def tearDown(self):
        vc.MISSING.clear()

    def test_videos_valid(self):
        ids = [v["yt"] for v in vc.VIDEOS]
        self.assertGreaterEqual(len(ids), 20)
        self.assertEqual(len(ids), len(set(ids)))
        levels = {x["id"] for x in vc.LEVELS}
        for v in vc.VIDEOS:
            self.assertRegex(v["yt"], r"^[A-Za-z0-9_-]{11}$")
            self.assertIn(v["level"], levels)
            self.assertTrue(v["channel"])
            for lang in ("ru", "en", "uz"):
                self.assertTrue(v[lang]["title"] and v[lang]["sub"], (lang, v["yt"]))
        # уровни идут по порядку: от основ к профи
        self.assertEqual([v["level"] for v in vc.VIDEOS], sorted(v["level"] for v in vc.VIDEOS))
        self.assertTrue(any(v["tested"] for v in vc.VIDEOS))   # есть стратегии, проверенные ботом

    def test_subtitles_requested_in_links(self):
        for v in vc.VIDEOS:
            self.assertIn("cc_load_policy=1", vc.embed_url(v["yt"]))
            self.assertIn("cc_lang_pref=uz", vc.watch_url(v["yt"]))
        for lang in ("ru", "en", "uz"):
            self.assertIn("O'zbek", vc.HINT[lang])

    def test_bot_texts_and_navigation(self):
        m = len(vc.VIDEOS)
        for lang in ("ru", "en", "uz"):
            lst = vc.list_text(lang)
            for n in (1, m):
                self.assertIn(f"\n{n}. ", lst)
            nums = [b for row in vc.list_buttons(lang) for b in row]
            self.assertEqual([d for _, d in nums], [f"vc:{i}" for i in range(1, m + 1)])
            first = vc.lesson_text(lang, 1)
            self.assertIn(vc.VIDEOS[0]["yt"], first)
            self.assertIn(vc.HINT[lang], first)
            # первый урок: нет «назад», есть «следующий»; последний — наоборот, плюс «курс пройден»
            d1 = [d for row in vc.lesson_buttons(lang, 1) for _, d in row]
            self.assertEqual(d1, ["vc:list", "vc:2"])
            dl = [d for row in vc.lesson_buttons(lang, m) for _, d in row]
            self.assertEqual(dl, [f"vc:{m - 1}", "vc:list"])
            self.assertIn(vc.TEXTS[lang]["done"], vc.lesson_text(lang, m))
            for k in vc.TEXTS["ru"]:
                self.assertIn(k, vc.TEXTS[lang])

    def test_menu_has_lessons_button(self):
        for lang in ("ru", "en", "uz"):
            texts = [b.text for row in botmod.menu(lang).keyboard for b in row]
            self.assertIn(botmod.t(lang, "btn_lessons"), texts)
            self.assertIn(botmod.t(lang, "btn_lessons"), botmod.MENU_TEXTS)

    def test_app_payload(self):
        c = vc.course("uz")
        self.assertEqual([v["n"] for v in c["videos"]], list(range(1, len(vc.VIDEOS) + 1)))
        self.assertTrue(c["videos"][0]["embed"].startswith("https://www.youtube-nocookie.com/embed/"))
        self.assertEqual(c["hint"], vc.HINT["uz"])
        for k in ("learn_tab_text", "learn_tab_video", "video_title", "video_mark", "video_next", "video_open_yt"):
            for lang in APP_TEXTS:
                self.assertIn(k, APP_TEXTS[lang])

    def test_missing_videos_hidden_and_renumbered(self):
        gone = vc.VIDEOS[1]["yt"]
        broken = vc.VIDEOS[2]["yt"]
        res = asyncio.run(vc.check_videos(FakeSession(gone={gone}, broken={broken})))
        self.assertEqual(res, {gone})                      # сетевой сбой не прячет видео
        c = vc.course("ru")
        self.assertNotIn(gone, [v["yt"] for v in c["videos"]])
        self.assertEqual([v["n"] for v in c["videos"]], list(range(1, len(vc.VIDEOS))))
        self.assertNotIn(gone, vc.list_text("ru"))
        self.assertEqual(vc.lesson_text("ru", 2).count(vc.VIDEOS[2]["yt"]), 1)
        # видео снова доступно — возвращается
        asyncio.run(vc.check_videos(FakeSession()))
        self.assertEqual(len(vc.active()), len(vc.VIDEOS))

    def test_html_wires_video_course(self):
        from goldbot import webapp as wa
        html = (wa.STATIC / "index.html").read_text(encoding="utf-8")
        for name in ("renderVideo", "videoView", "openVideo", "VKEY", "learnTabs"):
            self.assertTrue(re.search(r"\b" + name + r"\b", html), name)


if __name__ == "__main__":
    unittest.main()
