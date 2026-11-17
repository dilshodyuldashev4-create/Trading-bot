"""Торговля от уровней поддержки и сопротивления (боковик): проверка на истории XAUUSD 12.2023–08.2026.

Идея: цена несколько раз отбилась от одного верха и одного низа на H1 → продаём от верха, покупаем от низа,
цель — середина или противоположная граница. Всё без заглядывания вперёд:
* уровни — по закрытым свечам H1: верх/низ окна W часов, и к каждой границе должно быть не меньше T
  подтверждённых разворотов (пивот 2/2) в зоне ± tol·ATR(H1);
* вход на M15: свеча зашла в зону и закрылась обратно внутрь диапазона (отбой), вход по open следующей;
* стоп — за границей на stop_k·ATR(H1) (за зоной), цель — середина диапазона или другая граница;
* спред учтён, стоп и цель в одной свече — стоп, одна сделка за раз, сделка дольше 2 суток закрывается по рынку.
R — результат в рисках сделки (стоп = −1R).

    python scripts/range_research.py     # отчёт в reports/range_research.md
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goldbot.data import PIP, load_mt5_csv, resample  # noqa: E402
from goldbot.indicators import adx, atr, pivot_high, pivot_low  # noqa: E402

SPLIT = pd.Timestamp("2025-07-01")
PIV = 2


@dataclass(frozen=True)
class Cfg:
    win: int = 72          # окно диапазона, часов H1
    touches: int = 2       # разворотов у каждой границы
    tol: float = 0.3       # ширина зоны, ATR(H1)
    hmin: float = 2.0      # высота диапазона, ATR(H1): от
    hmax: float = 99.0     # до
    stop_k: float = 0.5    # стоп за границей, ATR(H1)
    target: str = "mid"    # mid — середина, far — у другой границы (минус зона)
    adx_max: float = 0.0   # 0 — без фильтра, иначе только при ADX(H1) < adx_max
    one_dir_day: bool = False  # правило PR 49: одно направление в день


def prepare():
    m5 = load_mt5_csv()
    m15 = resample(m5, "15min")
    h1 = resample(m5, "1h")
    return m15, h1


def levels(h1: pd.DataFrame, cfg: Cfg):
    """По каждой закрытой H1: (верх, низ, ATR) или NaN, если боковика нет."""
    h, l = h1.high.to_numpy(), h1.low.to_numpy()
    a = atr(h1, 14).to_numpy()
    ad = adx(h1, 14)
    ph, pl = pivot_high(h, PIV), pivot_low(l, PIV)   # значение на баре подтверждения
    n = len(h1)
    top = np.full(n, np.nan)
    bot = np.full(n, np.nan)
    hi = pd.Series(h).rolling(cfg.win).max().to_numpy()
    lo = pd.Series(l).rolling(cfg.win).min().to_numpy()
    for i in range(cfg.win + PIV, n):
        H, L, A = hi[i], lo[i], a[i]
        if not (cfg.hmin * A <= H - L <= cfg.hmax * A):
            continue
        if cfg.adx_max and ad[i] >= cfg.adx_max:
            continue
        w0 = i - cfg.win + PIV + 1
        p_h = ph[w0:i + 1]
        p_l = pl[w0:i + 1]
        th = np.sum(p_h >= H - cfg.tol * A)
        tl = np.sum(p_l <= L + cfg.tol * A)
        if th >= cfg.touches and tl >= cfg.touches:
            top[i], bot[i] = H, L
    return top, bot, a


def simulate(m15: pd.DataFrame, h1: pd.DataFrame, cfg: Cfg):
    top, bot, a = levels(h1, cfg)
    # уровни последней ЗАКРЫТОЙ H1 для каждой M15: H1 с меткой t закрыта в t+1h
    lv = pd.DataFrame({"top": top, "bot": bot, "a": a}, index=h1.index + pd.Timedelta(hours=1))
    lv = lv.reindex(m15.index, method="ffill")
    T, B, A = lv.top.to_numpy(), lv.bot.to_numpy(), lv.a.to_numpy()
    o, h, l, c, spr = (m15[k].to_numpy() for k in ("open", "high", "low", "close", "spread"))
    idx = m15.index
    day = idx.normalize().asi8
    n = len(o)
    out = []
    i = 0
    day_dir = {}
    while i < n - 2:
        if np.isnan(T[i]):
            i += 1
            continue
        tz = cfg.tol * A[i]
        d = 0
        if h[i] >= T[i] - tz and c[i] < T[i] - 0.0 and c[i] > T[i] - 2 * tz and h[i] <= T[i] + cfg.stop_k * A[i]:
            d = -1
        elif l[i] <= B[i] + tz and c[i] > B[i] and c[i] < B[i] + 2 * tz and l[i] >= B[i] - cfg.stop_k * A[i]:
            d = 1
        if d == 0:
            i += 1
            continue
        if cfg.one_dir_day and day_dir.get(day[i + 1], d) != d:
            i += 1
            continue
        e_i = i + 1
        e = o[e_i] + (spr[e_i] if d == 1 else 0.0)
        stop = (T[i] + cfg.stop_k * A[i]) if d == -1 else (B[i] - cfg.stop_k * A[i])
        mid = (T[i] + B[i]) / 2
        tgt = mid if cfg.target == "mid" else (B[i] + tz if d == -1 else T[i] - tz)
        risk = (e - stop) * d
        if risk <= 0 or (tgt - e) * d <= 0:
            i += 1
            continue
        day_dir.setdefault(day[e_i], d)
        r = None
        j = e_i
        while j < n and j < e_i + 192:
            bad = l[j] if d == 1 else h[j] + spr[j]
            good = h[j] if d == 1 else l[j] + spr[j]
            if (bad - stop) * d <= 0:
                r = -1.0
                break
            if (good - tgt) * d >= 0:
                r = (tgt - e) * d / risk
                break
            j += 1
        if r is None:
            if j >= n:
                break
            px = c[j - 1] + (spr[j - 1] if d == -1 else 0.0)
            r = (px - e) * d / risk
            j -= 1
        out.append(dict(t=idx[e_i], d=d, r=r, risk_pips=risk / PIP, win=r > 0))
        i = j + 1
    return pd.DataFrame(out)


def stats(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return dict(n=0, wr=0, R=0, avg=0, dd=0, pips=0)
    eq = tr.r.cumsum().to_numpy()
    dd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    return dict(n=len(tr), wr=100 * tr.win.mean(), R=tr.r.sum(), avg=tr.r.mean(), dd=dd,
                pips=(tr.r * tr.risk_pips).sum())


def cell(tr):
    s = stats(tr)
    return f"{s['n']} / {s['wr']:.0f}% / {s['R']:+.1f}R"


def main():
    m15, h1 = prepare()
    grid = list(product((48, 60, 66, 72, 78, 84, 96, 120), (2,), (0.5, 0.7), (0.3, 0.6), ("mid", "far"), (0.0,)))
    rows = []
    for win, tch, tol, sk, tg, ax in grid:
        cfg = Cfg(win=win, touches=tch, tol=tol, stop_k=sk, target=tg, adx_max=ax)
        tr = simulate(m15, h1, cfg)
        if tr.empty:
            continue
        a, b = tr[tr.t < SPLIT], tr[tr.t >= SPLIT]
        rows.append((cfg, tr, stats(a), stats(b), stats(tr)))
        pass
    rows.sort(key=lambda x: x[2]["R"], reverse=True)   # выбираем по первой половине
    best = rows[0][0]
    pos_a = sum(r[2]["R"] > 0 for r in rows)
    pos_b = sum(r[3]["R"] > 0 for r in rows)
    lines = [
        "# Торговля от уровней поддержки и сопротивления (боковик на H1, вход на M15)", "",
        "Данные: свечи M5 XAUUSD (MetaTrader 5), 01.12.2023 – 21.08.2026, спред учтён, стоп и цель в одной "
        "свече — стоп. Уровни: верх и низ последних W часов H1, к каждой границе не меньше T разворотов в зоне "
        "± tol·ATR(H1), высота диапазона не меньше 2 ATR. Вход: свеча M15 зашла в зону и закрылась обратно внутрь, "
        "вход по open следующей. Стоп за границей на stop·ATR(H1). Цель — середина (mid) или другая граница (far). "
        "R — в рисках сделки.", "",
        f"Перебрано вариантов: {len(rows)}. В плюсе на 12.2023–06.2025: {pos_a}, на 07.2025–08.2026: {pos_b}.", "",
        "Колонки: сделок / винрейт / итог в R. Варианты отсортированы по первой половине "
        "(так выбирали бы настройки), вторая половина — честная проверка.", "",
        "| Окно, ч | Касаний | Зона, ATR | Стоп, ATR | Цель | ADX<25 | 12.2023–06.2025 | 07.2025–08.2026 | Всё | Просадка, R |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for cfg, tr, sa, sb, s in rows:
        lines.append(f"| {cfg.win} | {cfg.touches} | {cfg.tol} | {cfg.stop_k} | {cfg.target} | "
                     f"{'да' if cfg.adx_max else 'нет'} | {sa['n']} / {sa['wr']:.0f}% / {sa['R']:+.1f} | "
                     f"{sb['n']} / {sb['wr']:.0f}% / {sb['R']:+.1f} | {s['n']} / {s['wr']:.0f}% / {s['R']:+.1f} | "
                     f"{s['dd']:.1f} |")
    tr = simulate(m15, h1, best)
    tr1 = simulate(m15, h1, Cfg(**{**best.__dict__, "one_dir_day": True}))
    lines += ["", f"## Лучший по первой половине: {best}", ""]
    lines.append(f"Средний стоп {tr.risk_pips.mean():.0f} пипсов, сделок в неделю {len(tr) / 140:.1f}, "
                 f"просадка {stats(tr)['dd']:.1f}R.")
    lines.append("")
    for y in sorted(set(tr.t.dt.year)):
        lines.append(f"* {y}: {cell(tr[tr.t.dt.year == y])}")
    lines += ["", f"С правилом «одно направление в день»: {cell(tr1)} (без него {cell(tr)}).", ""]
    Path(__file__).resolve().parent.parent.joinpath("reports", "range_research.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[-12:]))


if __name__ == "__main__":
    main()
