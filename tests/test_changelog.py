import asyncio
import os
import tempfile
import unittest

from goldbot import changelog
from goldbot.db import DB
from goldbot.i18n import LANGS


class ChangelogTests(unittest.TestCase):
    def test_every_release_has_all_languages(self):
        seen = set()
        for rel in changelog.RELEASES:
            self.assertNotIn(rel["version"], seen, "версии не должны повторяться")
            seen.add(rel["version"])
            for lang in LANGS:
                self.assertTrue(rel.get(lang), f"{rel['version']}: нет текста на {lang}")

    def test_text_has_items_and_start(self):
        rel = changelog.latest()
        for lang in LANGS:
            txt = changelog.release_text(rel, lang)
            self.assertIn("/start", txt)
            self.assertIn(rel[lang][0], txt)
        self.assertIn(rel["ru"][0], changelog.release_text(rel, "xx"))  # неизвестный язык → русский

    def test_caption_fits_telegram_photo(self):
        for rel in changelog.RELEASES:
            for lang in LANGS:
                self.assertLessEqual(len(changelog.release_text(rel, lang)), changelog.CAPTION_LIMIT,
                                     f"{rel['version']} {lang}: слишком длинно для подписи к фото")
        self.assertTrue(changelog.LOGO.exists())

    def test_offer_once_and_send_once(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                db = DB(os.path.join(d, "t.db"))
                await db.connect()
                v = changelog.latest()["version"]
                self.assertEqual((await changelog.to_offer(db))["version"], v)
                # перезапуск / падение — админу второй раз не предлагаем
                self.assertIsNone(await changelog.to_offer(db))
                # «Отправить всем» срабатывает один раз, повтор — только явно
                self.assertTrue(await changelog.claim_send(db, v))
                self.assertFalse(await changelog.claim_send(db, v))
                self.assertTrue(await changelog.claim_send(db, v, force=True))
                # новая версия — снова одно предложение
                old = list(changelog.RELEASES)
                try:
                    changelog.RELEASES.insert(0, {"version": "next", "ru": ["x"], "en": ["x"], "uz": ["x"]})
                    self.assertEqual((await changelog.to_offer(db))["version"], "next")
                    self.assertIsNone(await changelog.to_offer(db))
                    self.assertTrue(await changelog.claim_send(db, "next"))
                finally:
                    changelog.RELEASES[:] = old
                await db.close()
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
