"""Поиск стратегий для XAUUSD при риске 1:2 (SL 100 / TP 200 пипсов) с проверкой «каждые 10 сигналов в плюсе».

При 1:2 десять сделок в плюсе, если в них хотя бы 4 тейка (4×200 − 6×100 = +200 пипсов);
3 тейка из 10 — уже минус 100 пипсов.

    python scripts/research_strategies.py      # отчёт в reports/strategy_research.md
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goldbot.backtest import run_backtest  # noqa: E402
from goldbot.data import load_mt5_csv, resample  # noqa: E402
from goldbot.strategies import STRATEGIES as BASE  # noqa: E402
from goldbot.strategies import research as R  # noqa: E402
from goldbot.strategies.sessions import asian_range_breakout, ny_opening_range, silver_bullet  # noqa: E402
from goldbot.strategies.fvg_bos import fvg_bos_signals  # noqa: E402

SL, TP = 100, 200
TIMEFRAMES = {"M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h"}
MIN_TRADES = 60

EXTRA = {
    "Combo (живая): Silver Bullet + Азия": R.combo,
    "Combo + NY ORB": R.combo3,
    "Combo по дневному тренду": R.with_trend(R.combo),
    "Combo по тренду H4": R.with_trend(R.combo, "4h", 50),
    "Пробой Азии по дневному тренду": R.with_trend(asian_range_breakout),
    "Silver Bullet по дневному тренду": R.with_trend(silver_bullet),
    "NY ORB по дневному тренду": R.with_trend(ny_opening_range),
    "FVG+BOS по дневному тренду": R.with_trend(lambda df: fvg_bos_signals(df)),
    "Пробой хая/лоя прошлого дня": R.prev_day_breakout,
    "Пробой прошлого дня по дневному тренду": R.with_trend(R.prev_day_breakout),
    "Вход на открытии Лондона по тренду": R.london_open_trend,
    "RSI-откат по дневному тренду": R.rsi_pullback,
    "Inside bar + EMA200": R.inside_bar,
    "Squeeze (Боллинджер в Кельтнере)": R.squeeze_breakout,
    "Squeeze по дневному тренду": R.with_trend(R.squeeze_breakout),
    "VWAP-откат по дневному тренду": R.vwap_pullback,
    "Поглощение у EMA50": R.engulfing_ema,
    "Combo только BUY": R.buy_only(R.combo),
    "Фибоначчи 50–61.8%": R.fibonacci_retracement,
    "Фибоначчи 50–61.8% по дневному тренду": R.with_trend(R.fibonacci_retracement),
    "Фибоначчи 38.2–61.8% по дневному тренду": R.with_trend(lambda df: R.fibonacci_retracement(df, lo_lvl=0.382)),
    "Пробой трендовой линии": R.trendline_breakout,
    "Пробой трендовой линии по дневному тренду": R.with_trend(R.trendline_breakout),
    "Отскок от трендовой линии": lambda df: R.trendline_breakout(df, bounce=True),
    "Отскок от трендовой линии по дневному тренду": R.with_trend(lambda df: R.trendline_breakout(df, bounce=True)),
}

# стратегии, добавленные в бота (ключ STRATEGY → название и ТФ в таблице)
IN_BOT = {
    ("Squeeze по дневному тренду", "M15"): "squeeze",
    ("Пробой Дончиана 20 + EMA200", "M15"): "donchian",
    ("FVG+BOS по дневному тренду", "M15"): "fvg_m15",
}


def stats(trades):
    w = np.array([t.result == "TP" for t in trades], dtype=int)
    n = len(w)
    out = {"n": n, "wr": 100 * w.mean() if n else 0, "pips": int(sum(t.pips for t in trades))}
    if n < 10:
        out.update(slide=0.0, block=0.0, worst=0, streak=0, blocks=0)
        return out
    win10 = np.convolve(w, np.ones(10, dtype=int), "valid")          # тейков в каждом окне из 10 подряд
    blocks = w[: n // 10 * 10].reshape(-1, 10).sum(1)                 # блоки 1–10, 11–20, …
    streak = best = 0
    for x in w:
        streak = streak + 1 if x == 0 else 0
        best = max(best, streak)
    out.update(slide=100 * (win10 >= 4).mean(), block=100 * (blocks >= 4).mean(),
               blocks=len(blocks), worst=int(win10.min()), streak=best)
    return out


def by_year(trades):
    res = {}
    for y in (2024, 2025, 2026):
        tt = [t for t in trades if t.entry_time.year == y]
        res[y] = (len(tt), 100 * np.mean([t.result == "TP" for t in tt]) if tt else 0.0,
                  int(sum(t.pips for t in tt)))
    return res


def main() -> None:
    m5 = load_mt5_csv()
    strategies = {**BASE, **EXTRA}
    rows = []
    for tf, rule in TIMEFRAMES.items():
        df = resample(m5, rule)
        for name, fn in strategies.items():
            t0 = time.time()
            rep = run_backtest(df, fn(df), SL, TP)
            rows.append((name, tf, stats(rep.trades), by_year(rep.trades), rep))
            print(f"{tf:4} {name:45} {time.time() - t0:5.1f}s n={rep.n} wr={rep.win_rate:.1f}", flush=True)

    period = f"{m5.index[0]:%d.%m.%Y} – {m5.index[-1]:%d.%m.%Y}"
    ok = [r for r in rows if r[2]["n"] >= MIN_TRADES]
    ok.sort(key=lambda r: (-r[2]["block"], -r[2]["pips"]))
    L = [
        "# Поиск стратегий по золоту: риск 1:2 и «каждые 10 сигналов в плюсе»",
        "",
        f"Данные: реальные свечи M5 XAUUSD (MetaTrader 5), {period}, спред брокера учтён.",
        f"SL {SL} / TP {TP} пипсов (10 $ / 20 $). Вход по open следующей свечи, одна сделка за раз,",
        "если в одной свече задеты SL и TP — считается стоп.",
        "",
        "Десять сделок при 1:2 закрываются в плюсе, если в них **не меньше 4 тейков**.",
        "* **Блоки 10** — доля блоков «сделки 1–10, 11–20, …» с 4+ тейками;",
        "* **Окна 10** — то же для любых 10 сделок подряд (строже);",
        "* **Худшие 10** — минимум тейков в 10 сделках подряд; **Стопов подряд** — самая длинная серия.",
        "",
        "## Коротко",
        "",
        "* Ни одна стратегия не закрыла в плюсе **каждые** 10 сигналов: при 1:2 для этого нужен винрейт 70%+,",
        "  а у реальных стратегий на золоте он 35–40%.",
        "* В бота (`STRATEGY=all`) поставлены 5 самых прибыльных стратегий 2026 года на таймфреймах M5–H4,",
        "  без привязки к сессиям: RSI-откат (M5), Squeeze (M15), пробой Дончиана (M15), FVG/BOS (M5),",
        "  пробой трендовой линии (M5). Сигналы идут от каждой; у каждой не больше одной открытой сделки.",
        "  Итог по всем пяти вместе — в разделе «Все 5 стратегий вместе» ниже.",
        "* H1 и H4 при SL 100 / TP 200 в 2026 году заметно слабее M5/M15 (стоп слишком короткий для этих ТФ).",
        "* Фибоначчи (откат 50–61.8% и 38.2–61.8%) в 2026 году в минусе на всех таймфреймах, в бота не добавлен.",
        "* Учтите: золото в 2024–2026 почти всё время росло, поэтому стратегии «по тренду» выглядят",
        "  хорошо. При развороте рынка результаты будут хуже.",
        "",
        f"Стратегии с {MIN_TRADES}+ сделками, отсортированы по «Блоки 10».",
        "",
        "| Стратегия | ТФ | Сделок | Винрейт | Итог, пипс | Блоки 10 в плюсе | Окна 10 в плюсе | Худшие 10 | Стопов подряд | 2024 | 2025 | 2026 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, tf, s, y, _ in ok:
        ys = " | ".join(f"{y[k][1]:.0f}% / {y[k][2]:+d}" for k in (2024, 2025, 2026))
        L.append(f"| {name} | {tf} | {s['n']} | {s['wr']:.1f}% | {s['pips']:+d} | {s['block']:.0f}% из {s['blocks']} | "
                 f"{s['slide']:.0f}% | {s['worst']} из 10 | {s['streak']} | {ys} |")
    # плюс в 2026 году, по максимальной прибыли
    y26 = sorted((r for r in ok if r[3][2026][2] > 0 and r[2]["pips"] > 0),
                 key=lambda r: (-r[3][2026][2], -r[2]["pips"]))
    L += ["", "## В плюсе в 2026 году — по прибыли за 2026 год", "",
          "Только стратегии с плюсом и за весь период, и в 2026 году (январь–август), M5–H4. "
          "✅ — плюс в каждом году 2024–2026; в скобках — ключ STRATEGY, если стратегия есть в боте.", "",
          "| Стратегия | ТФ | Итог, пипс | 2026, пипс | Винрейт 2026 | Сделок | Винрейт | Макс. просадка | Блоки 10 в плюсе |",
          "|---|---|---|---|---|---|---|---|---|"]
    for name, tf, s, y, rep in y26:
        mark = " ✅" if all(y[k][2] > 0 for k in (2024, 2025, 2026)) else ""
        key = IN_BOT.get((name, tf))
        label = f"{name} (`{key}`)" if key else name
        L.append(f"| {label}{mark} | {tf} | {s['pips']:+d} | {y[2026][2]:+d} | {y[2026][1]:.0f}% | {s['n']} | "
                 f"{s['wr']:.1f}% | {rep.max_drawdown_pips():.0f} | {s['block']:.0f}% |")
    # все стратегии бота вместе: каждая сама по себе, плюс правило «2 стопа подряд — день закрыт»
    import pandas as pd
    from goldbot.live_strategy import PORTFOLIO, STRATEGIES as LIVE
    tr = []
    for k in PORTFOLIO:
        st = LIVE[k]
        d = resample(m5, st.timeframe)
        f = R.with_trend(st.signals) if st.daily_trend else st.signals
        tr += [(t.entry_time, t.exit_time, t.pips) for t in run_backtest(d, f(d), SL, TP).trades]
    tr = pd.DataFrame(tr, columns=["ent", "ex", "pips"]).sort_values("ent")
    tr["day"] = tr.ent.dt.tz_localize("UTC").dt.tz_convert("Asia/Tashkent").dt.date
    kept = []
    for _, g in tr.groupby("day"):
        today = []
        for _, r in g.iterrows():
            done = sorted((x.ex, x.pips) for x in today if x.ex <= r.ent)
            streak = 0
            for _, p in reversed(done):
                if p >= 0:
                    break
                streak += 1
            if streak >= 2:
                break
            today.append(r)
        kept += today
    days26 = pd.bdate_range("2026-01-01", m5.index[-1]).size
    L += ["", "## Все 5 стратегий вместе (`STRATEGY=all`), 2026 год", "",
          "| Режим | Сигналов в день | В неделю | Винрейт | Итог 2026, пипс | Макс. просадка 2026 | Итог 12.2023–08.2026 |",
          "|---|---|---|---|---|---|---|"]
    for label, t in (("без остановки дня (MAX_SL_STREAK=0)", tr),
                     ("2 стопа подряд — день закрыт (MAX_SL_STREAK=2, как в боте)", pd.DataFrame(kept))):
        t26 = t[t.ent.dt.year == 2026]
        eq = t26.sort_values("ex").pips.cumsum()
        dd = (eq.cummax().clip(lower=0) - eq).max()
        L.append(f"| {label} | {len(t26) / days26:.1f} | {5 * len(t26) / days26:.0f} | "
                 f"{100 * (t26.pips > 0).mean():.1f}% | {t26.pips.sum():+.0f} | {dd:.0f} | {t.pips.sum():+.0f} |")
    perfect = [r for r in ok if r[2]["block"] == 100]
    L += ["", "## Вывод", ""]
    if perfect:
        L.append("100% блоков в плюсе: " + ", ".join(f"{a} {b}" for a, b, *_ in perfect))
    else:
        L.append("Ни одна стратегия не дала плюс в **каждом** блоке из 10 сигналов.")

    # математика: доля десяток с 4+ тейками при данном винрейте
    from math import comb
    L += ["", "### Почему «каждые 10 в плюсе» недостижимо при 1:2", "",
          "Шанс, что 10 сделок подряд закроются в плюсе (4+ тейков), при разном винрейте:", "",
          "| Винрейт | 35% | 40% | 45% | 50% | 60% | 70% |", "|---|---|---|---|---|---|---|",
          "| Десятка в плюсе | " + " | ".join(
              f"{100 * sum(comb(10, k) * p**k * (1 - p)**(10 - k) for k in range(4, 11)):.0f}%"
              for p in (.35, .40, .45, .50, .60, .70)) + " |",
          "", "Реальные стратегии 1:2 на золоте дают 35–40% винрейта, поэтому в плюсе примерно 50–65% десяток."]

    # устойчивость фильтра дневного тренда: разные EMA и ТФ
    df15 = resample(m5, "15min")
    L += ["", "### Combo + фильтр тренда при разных настройках (M15)", "",
          "| Фильтр | Сделок | Винрейт | Итог, пипс | Блоки 10 в плюсе | Стопов подряд | 2024 | 2025 | 2026 |",
          "|---|---|---|---|---|---|---|---|---|"]
    base = run_backtest(df15, R.combo(df15), SL, TP)
    variants = [("без фильтра (сейчас)", base)] + [
        (f"{'день' if rule == '1D' else 'H4'}, EMA{n}", run_backtest(df15, R.with_trend(R.combo, rule, n)(df15), SL, TP))
        for rule in ("1D", "4h") for n in (20, 50, 100, 200)]
    for label, rep in variants:
        s, y = stats(rep.trades), by_year(rep.trades)
        ys = " | ".join(f"{y[k][1]:.0f}% / {y[k][2]:+d}" for k in (2024, 2025, 2026))
        L.append(f"| {label} | {s['n']} | {s['wr']:.1f}% | {s['pips']:+d} | {s['block']:.0f}% | {s['streak']} | {ys} |")
    out = Path(__file__).resolve().parent.parent / "reports" / "strategy_research.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
