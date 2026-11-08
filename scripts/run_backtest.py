"""Бэктест всех стратегий на реальных свечах XAUUSD, риск 1:2.

    python scripts/run_backtest.py            # отчёт в reports/backtest.md
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goldbot.backtest import run_backtest  # noqa: E402
from goldbot.data import load_mt5_csv, resample  # noqa: E402
from goldbot.strategies import STRATEGIES  # noqa: E402

TIMEFRAMES = {"M5": "5min", "M15": "15min", "H1": "1h"}
SL_LIST = [30, 50, 100]          # TP = 2 × SL
WIN_RATE_GOAL = 60.0


def main() -> None:
    m5 = load_mt5_csv()
    rows = []
    for tf_name, rule in TIMEFRAMES.items():
        df = resample(m5, rule)
        for name, fn in STRATEGIES.items():
            t0 = time.time()
            sig = fn(df)
            for sl in SL_LIST:
                rep = run_backtest(df, sig, sl, 2 * sl)
                rows.append((name, tf_name, sl, rep))
            print(f"{tf_name:4} {name:45} {time.time() - t0:5.1f}s", flush=True)

    period = f"{m5.index[0]:%d.%m.%Y} – {m5.index[-1]:%d.%m.%Y}"
    lines = [
        "# Бэктест стратегий по золоту (XAUUSD)",
        "",
        f"Данные: реальные свечи M5 MetaTrader 5, {period} ({len(m5):,} свечей), спред брокера учтён.",
        "Риск 1:2: TP = 2 × SL. 1 пип = 0.10 $ (30 пипсов = 3 $). Вход по open следующей свечи после сигнала,",
        "одна сделка за раз, если в одной свече задеты SL и TP — считается стоп.",
        "При риске 1:2 стратегия выходит в ноль при винрейте 33.3 %.",
        "",
        "| Стратегия | ТФ | SL/TP, пипс | Сделок | Винрейт | Итог, пипс | PF | Макс. просадка, пипс |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, tf, sl, r in rows:
        flag = " ✅" if r.win_rate >= WIN_RATE_GOAL and r.n >= 30 else ""
        lines.append(f"| {name} | {tf} | {sl}/{2*sl} | {r.n} | {r.win_rate:.1f}%{flag} | "
                     f"{r.total_pips:+.0f} | {r.profit_factor:.2f} | {r.max_drawdown_pips():.0f} |")
    best = sorted((x for x in rows if x[3].n >= 30), key=lambda x: -x[3].win_rate)[:5]
    lines += ["", "## Лучшие по винрейту (от 30 сделок)", ""]
    for name, tf, sl, r in best:
        lines.append(f"* {name}, {tf}, SL {sl}/TP {2*sl}: {r.win_rate:.1f}% на {r.n} сделках, "
                     f"итог {r.total_pips:+.0f} пипс")
    passed = [x for x in rows if x[3].win_rate >= WIN_RATE_GOAL and x[3].n >= 30]
    lines += ["", "## Вывод", ""]
    if passed:
        lines.append(f"Порог {WIN_RATE_GOAL:.0f}% прошли: " + ", ".join(f"{a} {b} SL {c}" for a, b, c, _ in passed))
    else:
        lines.append(f"Ни одна стратегия не дала винрейт {WIN_RATE_GOAL:.0f}% при риске 1:2. "
                     "Это ожидаемо: при TP вдвое дальше SL случайный вход выигрывает примерно в 33% случаев, "
                     "и рабочая стратегия 1:2 обычно даёт 35–45%.")
    out = Path(__file__).resolve().parent.parent / "reports" / "backtest.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
