"""Бэктест стратегий ликвидности по XAUUSD на M5–H4 при SL 100 / TP 200 пипсов.

    python scripts/liquidity_research.py      # отчёт в reports/liquidity_research.md
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goldbot.backtest import run_backtest  # noqa: E402
from goldbot.data import load_mt5_csv, resample  # noqa: E402
from goldbot.strategies import research as R  # noqa: E402
from goldbot.strategies.sessions import liquidity_sweep  # noqa: E402
from research_strategies import SL, TP, TIMEFRAMES, by_year, stats  # noqa: E402

LIQ = {
    "Sweep хая/лоя прошлого дня": liquidity_sweep,
    "Sweep хая/лоя прошлого дня по дневному тренду": R.with_trend(liquidity_sweep),
    "Sweep азиатского диапазона (Judas)": R.asian_sweep,
    "Sweep азиатского диапазона по дневному тренду": R.with_trend(R.asian_sweep),
    "Sweep свинга": R.swing_sweep,
    "Sweep свинга по дневному тренду": R.with_trend(R.swing_sweep),
    "Sweep равных хаёв/лоёв": R.equal_levels_sweep,
    "Sweep равных хаёв/лоёв по дневному тренду": R.with_trend(R.equal_levels_sweep),
    "Sweep + слом структуры (MSS)": R.sweep_mss,
    "Sweep + MSS по дневному тренду": R.with_trend(R.sweep_mss),
}


def main() -> None:
    m5 = load_mt5_csv()
    rows = []
    for tf, rule in TIMEFRAMES.items():
        df = resample(m5, rule)
        for name, fn in LIQ.items():
            rep = run_backtest(df, fn(df), SL, TP)
            s, y = stats(rep.trades), by_year(rep.trades)
            rows.append((name, tf, s, y, rep))
            print(f"{tf:4} {name:48} n={s['n']:5} wr={s['wr']:5.1f} pips={s['pips']:+6d} 2026={y[2026][2]:+6d}",
                  flush=True)
    rows.sort(key=lambda r: -r[3][2026][2])
    period = f"{m5.index[0]:%d.%m.%Y} – {m5.index[-1]:%d.%m.%Y}"
    L = ["# Стратегии ликвидности: бэктест XAUUSD M5–H4", "",
         f"Данные: свечи M5 XAUUSD (MetaTrader 5), {period}, спред учтён. SL {SL} / TP {TP} пипсов, "
         "одна сделка за раз, вход по open следующей свечи. Отсортировано по прибыли за 2026 год.", "",
         "| Стратегия | ТФ | Сделок | Винрейт | Итог, пипс | Макс. просадка | Блоки 10 в плюсе | 2024 | 2025 | 2026 |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for name, tf, s, y, rep in rows:
        ys = " | ".join(f"{y[k][1]:.0f}% / {y[k][2]:+d}" for k in (2024, 2025, 2026))
        L.append(f"| {name} | {tf} | {s['n']} | {s['wr']:.1f}% | {s['pips']:+d} | {rep.max_drawdown_pips():.0f} | "
                 f"{s['block']:.0f}% | {ys} |")
    out = Path(__file__).resolve().parent.parent / "reports" / "liquidity_research.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("written", out)


if __name__ == "__main__":
    main()
