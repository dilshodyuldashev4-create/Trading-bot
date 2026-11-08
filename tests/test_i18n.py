import asyncio
import os
import sqlite3
import string
import tempfile
import unittest

from goldbot import i18n
from goldbot.db import DB
from goldbot.econ_calendar import impact_text
from goldbot.engine import format_signal
from goldbot.live_strategy import STRATEGIES


class I18nTests(unittest.TestCase):
    def test_all_languages_have_same_keys_and_placeholders(self):
        ru = i18n.TEXTS["ru"]
        fields = lambda s: {f for _, f, _, _ in string.Formatter().parse(s) if f}  # noqa: E731
        for lang in i18n.LANGS:
            self.assertEqual(set(i18n.TEXTS[lang]), set(ru), lang)
            for k, v in ru.items():
                self.assertEqual(fields(i18n.TEXTS[lang][k]), fields(v), f"{lang}:{k}")

    def test_menu_buttons_unique_per_language(self):
        keys = ["btn_signal", "btn_fund", "btn_cal", "btn_sub", "btn_profile"]
        for lang in i18n.LANGS:
            labels = [i18n.t(lang, k) for k in keys]
            self.assertEqual(len(set(labels)), len(labels))
        self.assertIn("📊 Signal", i18n.variants("btn_signal"))

    def test_unknown_language_falls_back_to_russian(self):
        self.assertEqual(i18n.t(None, "btn_sub"), "💎 Подписка")
        self.assertEqual(i18n.t("de", "btn_sub"), "💎 Подписка")

    def test_signal_and_impact_translated(self):
        st = STRATEGIES["combo"]
        en = format_signal(st, 1, 2900, 2890, 2920, 100, 200, "now", "en")
        uz = format_signal(st, -1, 2900, 2910, 2880, 100, 200, "now", "uz")
        self.assertIn("Entry: <b>2900.00</b>", en)
        self.assertIn("Kirish: <b>2900.00</b>", uz)
        self.assertIn("gold ⬆️", impact_text("CPI m/m", "0.3%", "0.1%", "en"))
        self.assertIn("oltin ⬆️", impact_text("CPI m/m", "0.3%", "0.1%", "uz"))


class LangDBTests(unittest.TestCase):
    def test_old_database_gets_lang_column(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "t.db")
                con = sqlite3.connect(path)
                con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, "
                            "joined_at TEXT NOT NULL, trial_until TEXT NOT NULL, paid_until TEXT, "
                            "blocked INTEGER NOT NULL DEFAULT 0)")
                con.execute("INSERT INTO users VALUES (5, 'a', 'A', '2026-01-01', '2026-01-04', NULL, 0)")
                con.commit()
                con.close()
                db = DB(path)
                await db.connect()
                self.assertIsNone((await db.get_user(5))["lang"])
                await db.set_lang(5, "uz")
                self.assertEqual(await db.user_langs(), {5: "uz"})
                self.assertEqual(await db.lang_stats(), {"uz": 1})
                await db.close()
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
