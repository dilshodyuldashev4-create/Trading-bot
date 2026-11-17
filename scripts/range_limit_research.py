"""Лимитные ордера у зон поддержки/сопротивления: проверка на истории XAUUSD 12.2023–08.2026.

Уровни — как в range_research.py (верх/низ последних W часов H1, к каждой границе ≥ 2 разворотов в зоне
± tol·ATR(H1)). Пока боковик есть, у верха стоит SELL LIMIT, у низа — BUY LIMIT. Цена лимита: на самом уровне
(at=0) или у края зоны со стороны цены (at=1: уровень ∓ tol·ATR). Исполнение — когда цена свечи M15 дошла
до лимита (BUY — по ask), без проскальзывания. Стоп за уровнем на stop·ATR(H1), цель — середина или
другая граница. В свече исполнения задет и стоп — считаем стоп. Одна сделка за раз, максимум 2 суток.

    python scripts/range_limit_research.py     # отчёт в reports/range_limit_research.md
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import range_research as R  # noqa: E402
from goldbot.data import PIP  # noqa: E402

R.PIV = 2


def simulate(m15, h1, cfg: R.Cfg, at: float):
    top, bot, a = R.levels(h1, cfg)
    lv = pd.DataFrame({"top": top, "bot": bot, "a": a}, index=h1.index + pd.Timedelta(hours=1))
    lv = lv.reindex(m15.index, method="ffill")    # уровни, известные к открытию свечи M15
    T, B, A = lv.top.to_numpy(), lv.bot.to_numpy(), lv.a.to_numpy()
    o, h, l, c, spr = (m15[k].to_numpy() for k in ("open", "high", "low", "close", "spread"))
    idx = m15.index
    n = len(o)
    out = []
    i = 0
    while i < n - 1:
        if np.isnan(T[i]):
            i += 1
            continue
        tz = cfg.tol * A[i]
        sell_px = T[i] - at * tz
        buy_px = B[i] + at * tz
        d = 0
        # свеча открылась уже за лимитом — исполнение по open (как у брокера), но только внутри диапазона
        if h[i] >= sell_px and o[i] < T[i] + cfg.stop_k * A[i]:
            d, e = -1, max(sell_px, o[i])
        elif l[i] + spr[i] <= buy_px and o[i] + spr[i] > B[i] - cfg.stop_k * A[i]:
            d, e = 1, min(buy_px, o[i] + spr[i])
        if d == 0:
            i += 1
            continue
        if h[i] >= sell_px and l[i] + spr[i] <= buy_px:   # обе стороны в одной свече — пропускаем
            i += 1
            continue
        stop = (T[i] + cfg.stop_k * A[i]) if d == -1 else (B[i] - cfg.stop_k * A[i])
        tgt = (T[i] + B[i]) / 2 if cfg.target == "mid" else (B[i] + tz if d == -1 else T[i] - tz)
        risk = (e - stop) * d
        if risk <= 0 or (tgt - e) * d <= 0:
            i += 1
            continue
        r = None
        j = i
        while j < n and j < i + 192:
            bad = l[j] if d == 1 else h[j] + spr[j]
            good = h[j] if d == 1 else l[j] + spr[j]
            if (bad - stop) * d <= 0:
                r = -1.0
                break
            if j > i and (good - tgt) * d >= 0:
                r = (tgt - e) * d / risk
                break
            j += 1
        if r is None:
            if j >= n:
                break
            px = c[j - 1] + (spr[j - 1] if d == -1 else 0.0)
            r = (px - e) * d / risk
            j -= 1
        out.append(dict(t=idx[i], d=d, r=r, risk_pips=risk / PIP, win=r > 0))
        i = j + 1
    return pd.DataFrame(out)


def main():
    m15, h1 = R.prepare()
    rows = []
    for win, tol, sk, tg, at in product((48, 60, 72, 84, 96), (0.5, 0.7), (0.3, 0.6), ("mid", "far"), (0.0, 1.0)):
        cfg = R.Cfg(win=win, tol=tol, hmin=2.0, hmax=99.0, stop_k=sk, target=tg)
        tr = simulate(m15, h1, cfg, at)
        if tr.empty:
            continue
        rows.append((cfg, at, tr, R.stats(tr[tr.t < R.SPLIT]), R.stats(tr[tr.t >= R.SPLIT]), R.stats(tr)))
    rows.sort(key=lambda x: x[3]["R"], reverse=True)
    pa = sum(r[3]["R"] > 0 for r in rows)
    pb = sum(r[4]["R"] > 0 for r in rows)
    both = sum(r[3]["R"] > 0 and r[4]["R"] > 0 for r in rows)
    L = ["# Лимитные ордера у зон поддержки и сопротивления", "",
         "Данные: свечи M5 XAUUSD (MetaTrader 5), 01.12.2023 – 21.08.2026, спред учтён. Уровни — как в "
         "`range_research.md`. Лимит стоит на уровне (лимит «уровень») или у края зоны (лимит «край зоны»), "
         "исполнение без проскальзывания, стоп за уровнем, в свече исполнения задет стоп — считаем стоп. "
         "Повторить: `python scripts/range_limit_research.py`.", "",
         f"Вариантов: {len(rows)}. В плюсе до 07.2025: {pa}, после: {pb}, в обеих половинах: {both}.", "",
         "Колонки: сделок / винрейт / итог в R. Отсортировано по первой половине.", "",
         "| Окно, ч | Зона, ATR | Стоп, ATR | Цель | Лимит | 12.2023–06.2025 | 07.2025–08.2026 | Всё | Просадка, R |",
         "|---|---|---|---|---|---|---|---|---|"]
    for cfg, at, tr, sa, sb, s in rows:
        L.append(f"| {cfg.win} | {cfg.tol} | {cfg.stop_k} | {cfg.target} | {'край зоны' if at else 'уровень'} | "
                 f"{sa['n']} / {sa['wr']:.0f}% / {sa['R']:+.1f} | {sb['n']} / {sb['wr']:.0f}% / {sb['R']:+.1f} | "
                 f"{s['n']} / {s['wr']:.0f}% / {s['R']:+.1f} | {s['dd']:.1f} |")
    cfg, at, tr = rows[0][:3]
    L += ["", f"## Лучший по первой половине: окно {cfg.win} ч, зона {cfg.tol}, стоп {cfg.stop_k}, "
              f"цель {cfg.target}, лимит {'край зоны' if at else 'уровень'}", ""]
    for y in (2024, 2025, 2026):
        L.append(f"* {y}: {R.cell(tr[tr.t.dt.year == y])}")
    out = Path(__file__).resolve().parent.parent / "reports/range_limit_research.md"
    out.write_text("\n".join(L) + "\n")
    print("\n".join(L[:9]))
    print("\n".join(L[9:20]))
    print("\n".join(L[-6:]))


if __name__ == "__main__":
    main()
