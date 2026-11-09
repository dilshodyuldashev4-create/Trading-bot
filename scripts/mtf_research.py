"""Мульти-таймфрейм: сигналы стратегий бота (M5/M15) проходят, только если тренд на старших ТФ
(M15, M30, H1, H4 — close последней закрытой свечи выше/ниже EMA50) в ту же сторону.

    python scripts/mtf_research.py      # отчёт в reports/mtf_research.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goldbot.backtest import run_backtest  # noqa: E402
from goldbot.data import load_mt5_csv, resample  # noqa: E402
from goldbot.live_strategy import PORTFOLIO, STRATEGIES as LIVE  # noqa: E402
from goldbot.strategies import research as R  # noqa: E402

SL, TP = 100, 200
FILTERS = {
    "как сейчас (только дневной тренд)": (),
    "+ H4": ("4h",),
    "+ H1": ("1h",),
    "+ H1 и H4": ("1h", "4h"),
    "+ M30, H1, H4": ("30min", "1h", "4h"),
    "+ M15, M30, H1, H4 (все)": ("15min", "30min", "1h", "4h"),
    "большинство из M15/M30/H1/H4 (3 из 4)": "majority",
}


def year(tr, y):
    tt = [t for t in tr if t.entry_time.year == y]
    return sum(t.pips for t in tt), len(tt), (100 * np.mean([t.result == "TP" for t in tt]) if tt else 0)


def main() -> None:
    m5 = load_mt5_csv()
    tot = {f: [0, 0, 0, 0] for f in FILTERS}   # 2026 пипсы, 2026 сделки, 2025 пипсы, весь период
    L = ["# Мульти-таймфрейм фильтр (M15 / M30 / H1 / H4) для стратегий бота", "",
         "Сигнал стратегии проходит, только если на старших ТФ тренд в ту же сторону "
         "(close последней закрытой свечи выше EMA50 — вверх, ниже — вниз). SL 100 / TP 200.", "",
         "| Стратегия | Фильтр | Сделок 2026 | Винрейт 2026 | 2026, пипс | 2025, пипс | Весь период |",
         "|---|---|---|---|---|---|---|"]
    for k in PORTFOLIO:
        st = LIVE[k]
        d = resample(m5, st.timeframe)
        base = (R.with_trend(st.signals) if st.daily_trend else st.signals)(d)
        trends = {rule: R.htf_trend(d, rule, 50) for rule in ("15min", "30min", "1h", "4h")}
        for name, rules in FILTERS.items():
            s = base.copy()
            if rules == "majority":
                votes = sum(trends.values())
                s = np.where(((s == 1) & (votes >= 2)) | ((s == -1) & (votes <= -2)), s, 0).astype(np.int8)
            else:
                for r in rules:
                    if r != st.timeframe:
                        s = np.where(s == trends[r], s, 0).astype(np.int8)
            tr = run_backtest(d, s, SL, TP).trades
            p26, n26, w26 = year(tr, 2026)
            p25 = year(tr, 2025)[0]
            allp = sum(t.pips for t in tr)
            tot[name][0] += p26; tot[name][1] += n26; tot[name][2] += p25; tot[name][3] += allp
            L.append(f"| {k} | {name} | {n26} | {w26:.0f}% | {p26:+.0f} | {p25:+.0f} | {allp:+.0f} |")
            print(k, name, n26, f"{w26:.0f}%", p26, p25, allp, flush=True)
    L += ["", "## Все 7 стратегий вместе", "", "| Фильтр | Сделок 2026 | 2026, пипс | 2025, пипс | Весь период |",
          "|---|---|---|---|---|"]
    for name, (p26, n26, p25, allp) in tot.items():
        L.append(f"| {name} | {n26} | {p26:+.0f} | {p25:+.0f} | {allp:+.0f} |")
    out = Path(__file__).resolve().parent.parent / "reports" / "mtf_research.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[-9:]))


if __name__ == "__main__":
    main()
