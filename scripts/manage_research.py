"""Безубыток, частичная фиксация прибыли и соотношение стоп/тейк: проверка на истории XAUUSD 12.2023–08.2026.

5 стратегий бота (STRATEGY=all) на M15, у каждой одна сделка за раз, вход по open следующей свечи,
спред учтён. Если в одной свече задеты и стоп, и цель — считается стоп (худший случай). Безубыток
после частичной фиксации начинает действовать со следующей свечи. R — результат в рисках сделки (стоп = −1R).

    python scripts/manage_research.py     # отчёт в reports/manage_research.md
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from challenge_research import KEYS, load  # noqa: E402
from goldbot.data import PIP  # noqa: E402
from goldbot.indicators import atr  # noqa: E402


@dataclass(frozen=True)
class M:
    name: str
    be_r: float = 0.0        # стоп в безубыток, когда цена прошла столько R (0 — нет)
    part_r: float = 0.0      # закрыть часть позиции на столько R (0 — нет)
    part: float = 0.5        # какую часть закрыть
    zone: bool = False       # частичная фиксация у ближайшего уровня (свинг), а не на part_r
    tp_r: float | None = None  # тейк в R (None — как в правиле стоп/тейк)
    rev: str = ""            # закрыть остаток при развороте: ema20 / swing / opp / candle (пусто — нет)
    rev_any: bool = False    # и до фиксации части, если сделка в плюсе


def swings(h, l, n=3):
    """Свинг-хаи и свинг-лои (фрактал n свечей с каждой стороны); известны через n свечей после вершины."""
    sh = np.full(len(h), np.nan)
    sl = np.full(len(l), np.nan)
    for i in range(n, len(h) - n):
        if h[i] == h[i - n:i + n + 1].max():
            sh[i + n] = h[i]
        if l[i] == l[i - n:i + n + 1].min():
            sl[i + n] = l[i]
    return sh, sl


def zone_level(i, d, e, dist, tp, sh, sl, look=200):
    """Ближайший неснятый свинг между входом +0.5R и тейком — туда, скорее всего, цена дойдёт и упрётся."""
    lo = max(0, i - look)
    if d == 1:
        lv = sh[lo:i + 1]
        lv = lv[(lv >= e + 0.5 * dist) & (lv < tp)]
        return float(lv.min()) if len(lv) else None
    lv = sl[lo:i + 1]
    lv = lv[(lv <= e - 0.5 * dist) & (lv > tp)]
    return float(lv.max()) if len(lv) else None


def reversal(D, ctx, j, d, e, ent_i):
    """Разворот на закрытии свечи j против сделки d (вход на свече ent_i)."""
    c = ctx["c"][j]
    kind = ctx["rev"]
    if kind == "ema20":
        return (c - ctx["ema20"][j]) * d < 0
    if kind == "swing":   # закрытие за последним свингом против сделки, сформированным после входа
        lv = (ctx["swl"] if d == 1 else ctx["sh"])[ent_i:j + 1]
        lv = lv[~np.isnan(lv)]
        return len(lv) > 0 and (c - lv[-1]) * d < 0
    if kind == "opp":     # любая из 5 стратегий дала сигнал в обратную сторону
        return ctx["opp"][j] == -d
    if kind == "candle":  # сильная свеча против: тело больше 1 ATR
        return (c - D["o"][j]) * d < -ctx["atr"][j]
    return False


def run(D, sl_pips, tp_pips, m: M, sh, swl, ctx=None, tag=None):
    o, h, l, spr = D["o"], D["h"], D["l"], D["spr"]
    if m.rev:
        ctx = {**ctx, "rev": m.rev}
    n = len(o)
    out = []   # (год, R, был ли тейк/частичная прибыль)
    for k in KEYS:
        s = D["sig"][k]
        i = 0
        while i < n - 2:
            d = int(s[i])
            if d == 0:
                i += 1
                continue
            e = o[i + 1] + (spr[i + 1] if d == 1 else 0.0)
            dist = sl_pips[i] * PIP
            tp_d = (m.tp_r * dist) if m.tp_r else tp_pips[i] * PIP
            stop, tp = e - d * dist, e + d * tp_d
            part_px = None
            if m.zone:
                part_px = zone_level(i, d, e, dist, tp, sh, swl) or (e + d * dist if dist < tp_d else None)
            elif m.part_r:
                part_px = e + d * m.part_r * dist
            rest, res, part_done, be_done = 1.0, 0.0, False, False
            new_stop = None
            j = i + 1
            while j < n:
                if new_stop is not None:
                    stop, new_stop = new_stop, None
                bad = l[j] if d == 1 else h[j] + spr[j]
                good = h[j] if d == 1 else l[j] + spr[j]
                if (bad - stop) * d <= 0:
                    res += rest * (stop - e) * d / dist
                    break
                if part_px is not None and not part_done and (good - part_px) * d >= 0:
                    res += m.part * (part_px - e) * d / dist
                    rest -= m.part
                    part_done = True
                    new_stop = e + d * spr[j]
                if (good - tp) * d >= 0:
                    res += rest * (tp - e) * d / dist
                    break
                if m.be_r and not be_done and (good - e) * d >= m.be_r * dist:
                    be_done = True
                    new_stop = e + d * spr[j]
                if m.rev and (part_done or m.rev_any):
                    c = ctx["c"][j] + (spr[j] if d == -1 else 0.0)
                    if (c - e) * d > 0 and reversal(D, ctx, j, d, e, i + 1):
                        res += rest * (c - e) * d / dist
                        break
                j += 1
            else:
                break
            out.append((D["idx"][i].year, res) if tag is None else (D["idx"][i].year, res, i + 1, j, d))
            i = j + 1
    return out


def stats(rows):
    r = np.array([x[1] for x in rows])
    yrs = np.array([x[0] for x in rows])
    eq = np.cumsum(r)
    dd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    loss = r < -0.05
    streak = cur = 0
    for x in loss:
        cur = cur + 1 if x else 0
        streak = max(streak, cur)
    win = r > 0.05
    y26 = yrs == 2026
    return dict(n=len(r), win=100 * win.mean(), be=100 * (~win & ~loss).mean(), loss=100 * loss.mean(),
                tot=r.sum(), dd=dd, streak=streak, win26=100 * win[y26].mean(), tot26=r[y26].sum())


def row(name, x, be_col=True):
    mid = f"{x['win']:.0f}% / {x['be']:.0f}% / {x['loss']:.0f}%" if be_col else f"{x['win']:.0f}%"
    return (f"| {name} | {x['n']} | {mid} | {x['tot']:+.0f}R | {x['dd']:.0f}R | {x['streak']} "
            f"| {x['win26']:.0f}% | {x['tot26']:+.0f}R |")


def main():
    import bisect
    from goldbot.data import load_mt5_csv, resample
    D = load()
    df = resample(load_mt5_csv(), "15min")
    a = (atr(df, 14) / PIP).to_numpy()
    sh, swl = swings(df.high.to_numpy(), df.low.to_numpy())
    opp = np.zeros(len(a), dtype=int)
    for k in KEYS:
        opp = np.where(opp == 0, D["sig"][k], opp)
    ctx = dict(c=df.close.to_numpy(), ema20=df.close.ewm(span=20, adjust=False).mean().to_numpy(),
               sh=sh, swl=swl, opp=opp, atr=atr(df, 14).to_numpy())

    def atr_rule(k_sl, k_tp):
        sl = np.maximum(50, np.round(k_sl * a / 10) * 10)
        return sl, np.round(sl * k_tp / k_sl / 10) * 10

    fixed = lambda s, t: (np.full(len(a), float(s)), np.full(len(a), float(t)))  # noqa: E731
    head = ("| {} | Сделок | {} | Итог | Макс. просадка | Убытков подряд | 2026: в плюсе | 2026: итог |\n"
            "|---|---|---|---|---|---|---|---|")
    lines = ["# Безубыток, частичная фиксация, разворот и стоп/тейк: проверка на истории", "",
             "Свечи XAUUSD M15 01.12.2023 – 21.08.2026, 5 стратегий бота (у каждой одна сделка за раз), спред учтён,",
             "стоп и цель в одной свече — считается стоп. R — результат в рисках сделки: стоп = −1R.",
             "При лоте по риску R — это деньги. «Плюс / 0 / минус» — доля сделок с прибылью, в ноль и с убытком.",
             "Повторить: `python scripts/manage_research.py`.", "",
             "## 1. Соотношение стопа и тейка (без сопровождения)", "", head.format("Стоп / тейк", "В плюсе")]
    rr = [
        ("2 ATR / 3 ATR (было в боте, 1:1.5)", atr_rule(2, 3)),
        ("100 / 150 пипсов (1:1.5)", fixed(100, 150)),
        ("100 / 200 пипсов (1:2)", fixed(100, 200)),
        ("50 / 150 пипсов (1:3)", fixed(50, 150)),
        ("50 / 100 пипсов (1:2)", fixed(50, 100)),
        ("1 ATR / 3 ATR (1:3)", atr_rule(1, 3)),
        ("2 ATR / 6 ATR (1:3)", atr_rule(2, 6)),
    ]
    for name, (s_, t_) in rr:
        lines.append(row(name, stats(run(D, s_, t_, M(""), sh, swl, ctx)), be_col=False))
    s, t = atr_rule(2, 3)
    ms = [
        M("Без сопровождения (было в боте)"),
        M("Безубыток на +0.5R", be_r=0.5),
        M("Безубыток на +1R", be_r=1.0),
        M("50% на +0.5R, остальное в безубыток", part_r=0.5),
        M("50% на +1R, остальное в безубыток", part_r=1.0),
        M("30% на +1R, остальное в безубыток", part_r=1.0, part=0.3),
        M("50% на +1R, остальное в безубыток, тейк 2R", part_r=1.0, tp_r=2.0),
        M("**50% на +1R, остальное в безубыток, тейк 3R**", part_r=1.0, tp_r=3.0),
        M("50% у ближайшего уровня (свинг), остальное в безубыток", zone=True),
        M("50% у ближайшего уровня, остальное в безубыток, тейк 3R", zone=True, tp_r=3.0),
    ]
    lines += ["", "## 2. Фиксация части прибыли и безубыток (стоп 2 ATR)", "",
              "1R — расстояние до стопа. Тейк, если не указан, 3 ATR = 1.5R.", "",
              head.format("Вариант", "Плюс / 0 / минус")]
    for m in ms:
        lines.append(row(m.name, stats(run(D, s, t, m, sh, swl, ctx))))
    rv = {"ema20": "закрытие свечи за EMA20", "swing": "закрытие за свингом после входа",
          "opp": "встречный сигнал любой из 5 стратегий", "candle": "свеча против больше 1 ATR"}
    lines += ["", "## 3. Закрытие в прибыли при развороте (50% на +1R, безубыток, тейк 3R)", "",
              head.format("Признак разворота", "Плюс / 0 / минус"),
              row("нет (только стоп/тейк)", stats(run(D, s, t, M("", part_r=1.0, tp_r=3.0), sh, swl, ctx)))]
    for k, name in rv.items():
        lines.append(row(f"{name}, после фиксации", stats(run(D, s, t, M("", part_r=1.0, tp_r=3.0, rev=k), sh, swl, ctx))))
        lines.append(row(f"{name}, любая сделка в плюсе",
                         stats(run(D, s, t, M("", part_r=1.0, tp_r=3.0, rev=k, rev_any=True), sh, swl, ctx))))
    # повторный сигнал в ту же сторону сразу после тейка
    rows = sorted(run(D, s, t, M(""), sh, swl, ctx, tag=True), key=lambda r: r[2])
    ex = sorted((r[3], r[4]) for r in rows if r[1] > 0)
    rep, oth = [], []
    for _, res, ei, _, d in rows:
        lo = bisect.bisect_left(ex, (ei - 8, -9))
        hit = any(ex[q][1] == d for q in range(lo, len(ex)) if ex[q][0] < ei)
        (rep if hit else oth).append(res)
    lines += ["", "## 4. Сигнал в ту же сторону сразу после тейка (вход в пределах 2 часов после тейка)", "",
              "| Сделки | Сколько | Тейков | Средний результат |", "|---|---|---|---|"]
    for name, v in (("после тейка в ту же сторону", rep), ("остальные", oth)):
        v = np.array(v)
        lines.append(f"| {name} | {len(v)} | {100 * (v > 0).mean():.0f}% | {v.mean():+.2f}R |")
    out = Path(__file__).resolve().parent.parent / "reports/manage_research.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
