"""Свечной анализ: поглощение, пин-бар (молот / падающая звезда), утренняя / вечерняя звезда.

Повод — 18.11.2026: бот продал у дна после падения на ~100 $, а на откате можно было купить.
Проверка на XAUUSD 12.2023–08.2026 двумя способами:
1) вход по свечному развороту (M15 или H1), в т.ч. только после растянутого движения (≥ k ATR H1 за 12 / 24 ч);
2) фильтр сигналов бота: не входить, если на последних свечах H1 есть разворотный паттерн против сделки.

База — обычный счёт как в боте сейчас (overextended_research.base, стоп дня после 4-го SL).

    python scripts/candle_research.py   # отчёт в reports/candle_research.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import day_guard_research as G  # noqa: E402
import profit_research as P  # noqa: E402
from challenge_research import KEYS, load  # noqa: E402
from goldbot.indicators import pin_bar  # noqa: E402
from ideas_research import adx  # noqa: E402
from overextended_research import base, features, resample_h1  # noqa: E402


def patterns(x: pd.DataFrame) -> dict[str, np.ndarray]:
    """+1 бычий / −1 медвежий паттерн на закрытой свече."""
    o, h, l, c = (x[k].to_numpy() for k in ("open", "high", "low", "close"))
    body = np.abs(c - o)
    rng = h - l + 1e-9
    up_w, lo_w = h - np.maximum(o, c), np.minimum(o, c) - l
    po, pc = np.r_[np.nan, o[:-1]], np.r_[np.nan, c[:-1]]
    ppo, ppc = np.r_[np.nan, np.nan, o[:-2]], np.r_[np.nan, np.nan, c[:-2]]
    avg = pd.Series(rng).rolling(20).mean().to_numpy()
    engulf = np.where((c > o) & (pc < po) & (c >= po) & (o <= pc) & (body > np.abs(pc - po)), 1,
                      np.where((c < o) & (pc > po) & (c <= po) & (o >= pc) & (body > np.abs(pc - po)), -1, 0))
    pin = pin_bar(x)   # как в боте (goldbot/indicators.py)
    mid_small = np.abs(pc - po) <= 0.3 * np.abs(ppc - ppo)
    star = np.where((ppc < ppo) & mid_small & (c > o) & (c >= (ppo + ppc) / 2), 1,
                    np.where((ppc > ppo) & mid_small & (c < o) & (c <= (ppo + ppc) / 2), -1, 0))
    anyp = np.where(engulf != 0, engulf, np.where(pin != 0, pin, star))
    return dict(engulf=engulf, pin=pin, star=star, any=anyp)


def main():
    D0 = load()
    df, a, trades, sizes = base()
    idx = df.index
    f = features(df, a)
    g = G.Guard(day_sl=4)
    ad = adx(df, 14)
    D = dict(D0)
    D["sig"] = dict(D0["sig"])
    for k in P.BREAKOUTS:
        D["sig"][k] = np.where(ad >= 25, 0, D0["sig"][k]).astype(np.int8)
    opp = np.zeros(len(df), dtype=int)
    for k in KEYS:
        opp = np.where(opp == 0, D["sig"][k], opp)
    ctx = dict(c=df.close.to_numpy(), atr=a.to_numpy(), opp=opp)

    m15 = patterns(df)
    h1 = resample_h1(df)
    ph = patterns(h1)
    # H1 свеча с началом T известна после закрытия M15 свечи T+45 мин
    on_m15 = {k: pd.Series(v, index=h1.index + pd.Timedelta(minutes=45)).reindex(idx).fillna(0).to_numpy()
              for k, v in ph.items()}
    # «паттерн H1 был в последние n закрытых H1 свечах»: ffill на 4n свечей M15
    def recent(name, n):
        s = pd.Series(on_m15[name], index=idx).replace(0, np.nan)
        return s.ffill(limit=4 * n - 1).fillna(0).to_numpy()

    base_t, _ = G.portfolio(trades, idx, g, sizes)
    b = G.report(base_t, idx)
    L = ["# Свечной анализ: разворотные паттерны", "",
         "Повод — 18.11.2026: бот продал у дна после падения на ~100 $. Свечи XAUUSD 01.12.2023 – 21.08.2026,",
         "обычный счёт как в боте сейчас (5 стратегий, 50 % на +1R, безубыток, тейк 3R, стоп дня после 4-го SL),",
         "риск 1 % от старта. Паттерны: поглощение, пин-бар (тень ≥ 2 тела и ≥ 60 % свечи), утренняя/вечерняя звезда.",
         "Повторить: `python scripts/candle_research.py`.", "",
         "## 1. Вход по свечному развороту (6-я стратегия, лот ×0.75, стоп 2 ATR, как у остальных)", "",
         "| Вариант | Своих сделок | Средний R | " + G.HEAD.split("\n")[0].split("| Вариант | ")[1],
         "|---|---|---|" + "|".join(["---"] * 8) + "|",
         f"| **как сейчас** | — | — | " + G.row("", b).split("|  | ")[1]]
    NK = KEYS + ("pat",)
    G.KEYS = NK
    saved = P.KEYS

    def add(sig, label):
        P.KEYS = ("pat",)
        D2 = dict(D)
        D2["sig"] = {"pat": np.asarray(sig, dtype=np.int8)}
        pt = P.simulate(D2, ctx)
        P.KEYS = saved
        for x in pt:
            sizes[id(x)] = 0.75
        r = np.array([x["r"] for x in pt]) if pt else np.zeros(1)
        t, _ = G.portfolio(trades + pt, idx, g, sizes)
        L.append(f"| {label} | {len(pt)} | {r.mean():+.2f} | " + G.row("", G.report(t, idx)).split("|  | ")[1])

    for tf, P_ in (("M15", m15), ("H1", on_m15)):
        for name in ("engulf", "pin", "star", "any"):
            s = P_[name]
            add(s, f"{tf} {name}, без условий")
            for n, k in (("mv48", 4), ("mv48", 6), ("mv96", 5), ("mv96", 8)):
                ext = -f[n] * s      # движение против паттерна (падение перед бычьим)
                add(np.where(ext >= k, s, 0), f"{tf} {name} после хода ≥ {k} ATR за {int(n[2:]) // 4} ч")
                add(np.where((ext >= k) & (s == 1), 1, 0), f"{tf} {name} после падения ≥ {k} ATR за {int(n[2:]) // 4} ч, только BUY")

    L += ["", "## 2. Фильтр сигналов бота по свечам H1", "", G.HEAD, G.row("**как сейчас**", b)]
    for name in ("engulf", "pin", "star", "any"):
        for n in (1, 2, 3):
            rp = recent(name, n)
            keep = [x for x in trades if rp[x["sig"]] != -x["d"]]
            t, _ = G.portfolio(keep, idx, g, sizes)
            L.append(G.row(f"пропуск, если за {n} ч H1 {name} против сделки", G.report(t, idx)))
            keep = [x for x in trades if not (rp[x["sig"]] == -x["d"] and f["mv96"][x["sig"]] * x["d"] >= 4)]
            t, _ = G.portfolio(keep, idx, g, sizes)
            L.append(G.row(f"то же, только после хода ≥ 4 ATR за 24 ч", G.report(t, idx)))
            keep = [x for x in trades if rp[x["sig"]] == x["d"]]
            t, _ = G.portfolio(keep, idx, g, sizes)
            L.append(G.row(f"только с {name} H1 по сделке за {n} ч", G.report(t, idx)))
    L += ["", "## Вывод", "",
          "* Вход по свечному развороту после сильного падения (покупка на откате) — сделки в среднем около 0R",
          "  или в минусе, прибыль портфеля не растёт. Паттерны «без условий» дают больше % только за счёт",
          "  сотен лишних сделок с худшей просадкой — не добавлено.",
          "* **Фильтр: пин-бар H1 против сигнала за последние 2 ч — сигнал пропускается.** Прибыль +359 % против",
          "  +331 %, просадка 30.0 % вместо 35.1 %, лучше в обеих половинах истории и на зеркальном графике;",
          "  окна 1 и 3 ч тоже в плюсе (+340 %, +351 %). Добавлено в бот: CANDLE_PIN_HOURS=2 (0 — выключить).",
          "* Фильтр по любому паттерну за 3 ч: +340 %, просадка 23 % — запасной вариант, если важнее просадка.",
          "* Фильтр по поглощению режет прибыль; «только с паттерном по сделке» — прибыль сильно ниже."]
    out = Path(__file__).resolve().parent.parent / "reports" / "candle_research.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
