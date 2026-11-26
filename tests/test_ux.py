"""Удобство: короткие подписи меню (старые тоже работают) и короткий текст сигнала."""
import re
import unittest

from goldbot import bot as botmod
from goldbot import engine
from goldbot.i18n import OLD_BUTTONS, TEXTS, t, variants
from goldbot.live_strategy import STRATEGIES


class MenuTests(unittest.TestCase):
    def test_old_labels_still_work(self):
        for key, old in OLD_BUTTONS.items():
            for label in old:
                self.assertIn(label, variants(key))
                self.assertIn(label, botmod.MENU_TEXTS)   # не попадёт во ввод капитала / баланса

    def test_menu_labels_short(self):
        for lang in TEXTS:
            for row in botmod.menu(lang).keyboard:
                for b in row:
                    self.assertLessEqual(len(b.text), 20, b.text)


class SignalTextTests(unittest.TestCase):
    def caption(self, lang):
        strat = next(iter(STRATEGIES.values()))
        txt = engine.format_signal(strat, 1, 2650.4, 2645.4, 2662.9, 50, 125, "26.11 14:30", lang)
        txt = engine.with_partial(txt, 2655.4, 50, 0.5, lang)
        return botmod.signal_caption(lang, txt, 1000, 1, 2650.4, 50, 125, 50, 0.5, 1.0)

    def test_signal_keeps_key_info_and_is_short(self):
        for lang in TEXTS:
            cap = self.caption(lang)
            for s in ("2650.40", "2645.40", "2662.90", "2655.40", "0.02", "2653.40"):
                self.assertIn(s, cap)
            self.assertLess(len(re.sub("<[^>]+>", "", cap)), 680, lang)
            self.assertLess(cap.index("⚖️"), cap.index("📦"))   # лот — после уровней
            self.assertTrue(cap.rstrip().endswith("</i>"))      # приписка — в самом конце

    def test_prop_signal_stop_rule_on_own_line(self):
        for lang in TEXTS:
            txt = t(lang, "ps_signal", id=1, side="🟢 BUY", entry="1", sl="1", tp="1", sl_pips="1", tp_pips="1",
                    lot="0.10", size="10 000", risk_usd="$1", risk_pct="1", profit_usd="$2", note="", reset="02:00")
            last = txt.rstrip().split("\n")[-1]
            self.assertIn("02:00", last)


if __name__ == "__main__":
    unittest.main()
