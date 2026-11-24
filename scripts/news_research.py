"""Фильтр важных новостей США (NFP, CPI, решение ФРС): помогает ли он боту? Проверка на истории
XAUUSD M15 01.12.2023 – 21.08.2026 (свечи MT5, время UTC — проверено по всплескам в 8:30 и 14:00 Нью-Йорка).

База — бот как сейчас: 10 стратегий, стоп 2 ATR, 50 % на +1R и безубыток, тейк 3R, ADX-фильтр пробоев,
лот ×0.75 / ×1.5 по согласию, стоп дня после 4-го SL, пин-бар H1 против сигнала — пропуск. Риск 1 %.
Проп — симуляция челленджей FundedNext из challenge_research.py (0.5 %, стоп дня после 1-го SL,
риск ×0.25 при −2 %, тейк 1.5R).

Варианты: не входить за X минут до и Y минут после новости; закрывать открытые сделки за N минут до неё.
В свечах записан обычный спред, а не скачок спреда и проскальзывание в момент новости, поэтому отдельная
колонка «стресс новостей»: вход или выход в окне −5…+15 мин от новости стоит ещё 1 $ (и +0.30 $ на любую сделку).

    python scripts/news_research.py      # отчёт: reports/news_table.md
"""
from __future__ import annotations

import dataclasses
import inspect
import sys
import warnings
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
warnings.filterwarnings("ignore")

import challenge_research as C  # noqa: E402
import day_guard_research as G  # noqa: E402
import indicator_research as R  # noqa: E402
import profit3_research as P3  # noqa: E402
from challenge_research import KEYS  # noqa: E402
from goldbot.data import PIP, load_mt5_csv, resample  # noqa: E402
from goldbot.indicators import atr  # noqa: E402
from goldbot.strategies.popular import days_breakout, donchian_h1, kama_h4, klinger_h4  # noqa: E402
from goldbot.strategies.research import htf_trend  # noqa: E402
from goldbot.strategies.sessions import asian_breakout_day  # noqa: E402
from ideas_research import SPLIT  # noqa: E402

# Даты по официальным графикам BLS и ФРС (с переносами из-за shutdown осенью 2025 и в начале 2026).
NFP = ("2023-12-08 2024-01-05 2024-02-02 2024-03-08 2024-04-05 2024-05-03 2024-06-07 2024-07-05 2024-08-02 "
       "2024-09-06 2024-10-04 2024-11-01 2024-12-06 2025-01-10 2025-02-07 2025-03-07 2025-04-04 2025-05-02 "
       "2025-06-06 2025-07-03 2025-08-01 2025-09-05 2025-11-20 2025-12-16 2026-01-09 2026-02-11 2026-03-06 "
       "2026-04-03 2026-05-08 2026-06-05 2026-07-02 2026-08-07").split()
CPI = ("2023-12-12 2024-01-11 2024-02-13 2024-03-12 2024-04-10 2024-05-15 2024-06-12 2024-07-11 2024-08-14 "
       "2024-09-11 2024-10-10 2024-11-13 2024-12-11 2025-01-15 2025-02-12 2025-03-12 2025-04-10 2025-05-13 "
       "2025-06-11 2025-07-15 2025-08-12 2025-09-11 2025-10-24 2025-12-18 2026-01-13 2026-02-13 2026-03-11 "
       "2026-04-10 2026-05-12 2026-06-10 2026-07-14 2026-08-12").split()
FOMC = ("2023-12-13 2024-01-31 2024-03-20 2024-05-01 2024-06-12 2024-07-31 2024-09-18 2024-11-07 2024-12-18 "
        "2025-01-29 2025-03-19 2025-05-07 2025-06-18 2025-07-30 2025-09-17 2025-10-29 2025-12-10 2026-01-28 "
        "2026-03-18 2026-04-29 2026-06-17 2026-07-29").split()

KEYS10 = KEYS + ("asia", "donchian_h1", "days5", "kama_h4", "klinger_h4")


def ny(d, hm):
    return pd.Timestamp(f"{d} {hm}", tz="America/New_York").tz_convert("UTC").tz_localize(None)


def tier1():
    return sorted([ny(d, "08:30") for d in NFP + CPI] + [ny(d, "14:00") for d in FOMC])


def high_approx(idx):
    """Приближение «всех важных (High) новостей США» из Forex Factory, как в живом боте: топ-3 + пособия по
    безработице (четверг 8:30), ISM производство (1-й рабочий день, 10:00) и услуги (3-й рабочий день, 10:00)."""
    ev = set(tier1())
    days = pd.bdate_range(idx[0].normalize(), idx[-1].normalize())
    for d in days:
        if d.weekday() == 3:
            ev.add(ny(d.date(), "08:30"))
    for _, g in pd.Series(days, index=days).groupby(days.to_period("M")):
        g = list(g)
        ev.add(ny(g[0].date(), "10:00"))
        if len(g) > 2:
            ev.add(ny(g[2].date(), "10:00"))
    return sorted(ev)


def window_mask(idx, events, before, after):
    """True на баре, время открытия которого в [событие − before, событие + after)."""
    m = np.zeros(len(idx), dtype=bool)
    for e in events:
        lo, hi = idx.searchsorted(e - pd.Timedelta(minutes=before)), idx.searchsorted(e + pd.Timedelta(minutes=after))
        m[lo:hi] = True
    return m


def cut_mask(idx, events, mins):
    """True на первом баре, открытие которого ≥ событие − mins (там закрываем открытые сделки по open)."""
    m = np.zeros(len(idx), dtype=bool)
    for e in events:
        k = idx.searchsorted(e - pd.Timedelta(minutes=mins))
        if k < len(idx) and idx[k] < e + pd.Timedelta(minutes=15):
            m[k] = True
    return m


def simulate(D, ctx, keys, cut=None):
    """profit_research.simulate + закрытие остатка по open бара, где cut=True (перед новостью)."""
    o, h, l, c, spr = D["o"], D["h"], D["l"], ctx["c"], D["spr"]
    sl_p, opp = D["sl"], ctx["opp"]
    n = len(o)
    out = []
    for k in keys:
        s = D["sig"][k]
        i = 0
        while i < n - 2:
            d = int(s[i])
            if d == 0:
                i += 1
                continue
            dist = sl_p[i] * PIP
            ent = i + 1
            e = o[ent] + (spr[ent] if d == 1 else 0.0)
            stop, tp, part_px = e - d * dist, e + d * 3.0 * dist, e + d * dist
            rest, res, part_done, new_stop = 1.0, 0.0, False, None
            j = ent
            cut_hit = False
            while j < n:
                if new_stop is not None:
                    stop, new_stop = new_stop, None
                if cut is not None and cut[j] and j > ent:
                    px = o[j] + (spr[j] if d == -1 else 0.0)
                    res += rest * (px - e) * d / dist
                    cut_hit = True
                    break
                bad = l[j] if d == 1 else h[j] + spr[j]
                good = h[j] if d == 1 else l[j] + spr[j]
                if (bad - stop) * d <= 0:
                    res += rest * (stop - e) * d / dist
                    break
                if not part_done and (good - part_px) * d >= 0:
                    res += 0.5 * (part_px - e) * d / dist
                    rest -= 0.5
                    part_done = True
                    new_stop = e + d * spr[j]
                if (good - tp) * d >= 0:
                    res += rest * (tp - e) * d / dist
                    break
                cl = c[j] + (spr[j] if d == -1 else 0.0)
                if part_done and (cl - e) * d > 0 and opp[j] == -d:
                    res += rest * (cl - e) * d / dist
                    break
                j += 1
            else:
                break
            out.append(dict(key=k, i=ent, j=j, d=d, r=res, sig=i, cut=cut_hit, dist=dist))
            i = j + 1
    return out


def extras(df):
    tr = htf_trend(df, "1D", 50)
    t = lambda s: np.where(np.asarray(s) == tr, s, 0).astype(np.int8)  # noqa: E731
    return {"asia": asian_breakout_day(df).astype(np.int8), "donchian_h1": t(donchian_h1(df)),
            "days5": t(days_breakout(df, 5)), "kama_h4": t(kama_h4(df)), "klinger_h4": t(klinger_h4(df))}


def run(D, df, pin, E, block=None, cut=None, slip=0.0, news_hot=None, news_slip=0.0):
    """Портфель бота. block — бары, на которых вход запрещён; cut — бары закрытия перед новостью;
    news_hot — бары ±новости, где вход/выход дороже на news_slip $."""
    D2 = dict(D)
    D2["sig"] = {**D["sig"], **E}
    opp = np.zeros(len(df), dtype=int)
    for k in KEYS10:
        opp = np.where(opp == 0, D2["sig"][k], opp)
    trades = simulate(D2, dict(c=df.close.to_numpy(), opp=opp), KEYS10, cut)
    for x in trades:
        cost = slip
        if news_hot is not None and news_slip:
            cost += news_slip * (int(news_hot[x["i"]]) + int(news_hot[x["j"]]))
        x["r"] -= cost / x["dist"]
    sigs = np.stack([D2["sig"][k] for k in KEYS10])
    trades = [x for x in trades if pin[x["sig"]] != -x["d"]]
    if block is not None:
        trades = [x for x in trades if not block[x["i"]]]
    sizes = {}
    for x in trades:
        ki = KEYS10.index(x["key"])
        lo = max(0, x["sig"] - 3)
        k = int((np.delete(sigs[:, lo:x["sig"] + 1], ki, axis=0) == x["d"]).any(axis=1).sum())
        sizes[id(x)] = 0.75 if k == 0 else 1.5
    G.KEYS = KEYS10
    t, _ = G.portfolio(trades, df.index, G.Guard(day_sl=4), sizes)
    G.KEYS = KEYS
    rep = G.report(t, df.index)
    y = df.index[[x["i"] for x in t]].year
    pnl = np.array([x["pnl"] for x in t])
    rep["y24"], rep["y2526"] = pnl[y == 2024].sum(), pnl[y >= 2025].sum()
    rep["taken"] = t
    return rep


# ---------- проп: челлендж с запретом входа и закрытием перед новостью ----------

_src = inspect.getsource(C.attempt)
_src = _src.replace("        # 1) сопровождение открытых сделок на свече i\n",
                    "        if CUT is not None and CUT[i] and open_tr:\n"
                    "            bal += sum((o[i] - t['e']) * t['d'] / t['dist'] * t['risk']\n"
                    "                       - (spr[i] / t['dist'] * t['risk'] if t['d'] == 1 else 0) for t in open_tr)\n"
                    "            open_tr = []\n"
                    "            traded_today = True\n"
                    "        # 1) сопровождение открытых сделок на свече i\n")
assert "CUT[i]" in _src
_g = dict(C.__dict__)
_g["CUT"] = None
exec(_src, _g)
attempt_cut = _g["attempt"]


def prop_data(mirror=False):
    D = C.load(mirror)
    m5 = load_mt5_csv()
    if mirror:
        k = 2 * m5.close.mean()
        m5 = m5.assign(open=k - m5.open, high=k - m5.low, low=k - m5.high, close=k - m5.close)
    df = resample(m5, "15min")
    D["sig"].update(extras(df))
    return D


PROP_BASE = C.Cfg(keys=KEYS10, day_losses=1, dd_cut=2, dd_mult=0.25)


def prop_summary(D, plan, cfg, st, funded_days=0):
    res = [attempt_cut(D, s, plan, cfg, funded_days=funded_days) for s in st]
    done = [r for r in res if r[0] != "open"]
    p = [r for r in done if r[0] == "pass"]
    f = [r for r in done if r[0].startswith("fail")]
    return (100 * len(p) / len(done), 100 * len(f) / len(done),
            float(np.median([r[2] for r in p])) if p else float("nan"),
            float(np.median([r[1] - 100 for r in done])))


_PD = {}


def _prop_row(arg):
    name, which, blk, cut, cost = arg
    D = dict(_PD[which])
    D["sig"] = {k: np.where(np.r_[blk[1:], False], 0, v).astype(np.int8) if blk is not None else v
                for k, v in D["sig"].items()}
    _g["CUT"] = cut
    cfg = dataclasses.replace(PROP_BASE, cost_r=cost)
    out = []
    for since, until in ((None, "2025-07-01"), ("2025-07-01", None)):
        st = C.starts(D, since=since, until=until, every=2)
        p2 = prop_summary(D, C.PLANS["2step1"], cfg, st)
        p1 = prop_summary(D, C.PLANS["1step"], cfg, st)
        fu = prop_summary(D, C.PLANS["2step1"], cfg, st, funded_days=90)
        out.append((p2, p1, fu))
    return name, which, cost, out


def regular_variants(idx):
    t1, hi = tier1(), high_approx(idx)
    W = lambda ev, b, a: window_mask(idx, ev, b, a)  # noqa: E731
    days_t1 = np.isin(idx.normalize(), pd.DatetimeIndex([e.normalize() for e in t1]))
    # весь день новости: с начала суток UTC до +2 ч после выхода
    upto = W(t1, 24 * 60, 120) & days_t1
    return [
        ("без новостного правила (чистый бэктест)", None, None),
        ("**как сейчас: все High, −10…+15 мин**", W(hi, 10, 15), None),
        ("топ-3 (NFP, CPI, ФРС), −10…+15 мин", W(t1, 10, 15), None),
        ("топ-3, −30…+30 мин", W(t1, 30, 30), None),
        ("топ-3, −60…+60 мин", W(t1, 60, 60), None),
        ("топ-3, −60…+120 мин", W(t1, 60, 120), None),
        ("топ-3, −2 ч…+4 ч", W(t1, 120, 240), None),
        ("топ-3, весь день до +2 ч после", upto, None),
        ("топ-3, только до: −2 ч…0", W(t1, 120, 0), None),
        ("топ-3, только после: 0…+2 ч", W(t1, 0, 120), None),
        ("все High, −30…+30 мин", W(hi, 30, 30), None),
        ("все High, −60…+60 мин", W(hi, 60, 60), None),
        ("как сейчас + закрыть сделки за 30 мин до топ-3", W(hi, 10, 15), cut_mask(idx, t1, 30)),
        ("/newstrade off: все High ±30 мин + закрыть за 30 мин", W(hi, 30, 30), cut_mask(idx, hi, 30)),
        ("топ-3 ±60 мин + закрыть за 30 мин до топ-3", W(t1, 60, 60), cut_mask(idx, t1, 30)),
    ]


HEAD = ("| Вариант | Сделок | Итог | Макс. просадка | Итог / просадка | Худший день | 2024 | 2025–26 | до 07.2025 "
        "| после 07.2025 | Стресс новостей | Зеркало |\n|---|---|---|---|---|---|---|---|---|---|---|---|")


def row(name, s, ss, sm):
    return (f"| {name} | {s['n']} | {s['tot']:+.0f} % | {s['dd']:.1f} % | {s['ratio']:.1f} | {s['worst']:+.1f} % "
            f"| {s['y24']:+.0f} % | {s['y2526']:+.0f} % | {s['a']:+.0f} % | {s['b']:+.0f} % | {ss['tot']:+.0f} % "
            f"| {sm['tot']:+.0f} % |")


def main():
    D0, df = R.setup()
    D, _, pin = R.prepare(D0, df)
    m5m = load_mt5_csv()
    k = 2 * m5m.close.mean()
    m5m = m5m.assign(open=k - m5m.open, high=k - m5m.low, low=k - m5m.high, close=k - m5m.close)
    dfm = resample(m5m, "15min")
    Dm, _, pinm = R.prepare(C.load(mirror=True), dfm)
    E, Em = extras(df), extras(dfm)
    idx = df.index
    hot = window_mask(idx, high_approx(idx), 5, 15)
    variants = regular_variants(idx)
    L = ["## Обычный счёт (риск 1 %, 10 стратегий)", "", HEAD]
    base = None
    for name, blk, cut in variants:
        s = run(D, df, pin, E, blk, cut)
        ss = run(D, df, pin, E, blk, cut, slip=R.SLIP, news_hot=hot, news_slip=1.0)
        sm = run(Dm, dfm, pinm, Em, blk, cut)
        if base is None:
            base = (s, ss, sm)
        ln = row(name, s, ss, sm)
        print(ln, flush=True)
        L.append(ln)
    # сколько сделок открывается рядом с новостями и как они идут
    s0 = run(D, df, pin, E)
    t1 = tier1()
    near = window_mask(idx, t1, 60, 60)
    L += ["", "Сделки базы, открытые рядом с топ-3 новостями (±60 мин), против остальных:", "",
          "| Группа | Сделок | R на сделку | 2024 | 2025–26 |", "|---|---|---|---|---|"]
    for nm, sel in (("рядом с новостью", True), ("остальные", False)):
        tt = [x for x in s0["taken"] if near[x["i"]] == sel]
        y = idx[[x["i"] for x in tt]].year
        rr = np.array([x["r"] for x in tt])
        L.append(f"| {nm} | {len(tt)} | {rr.mean():+.3f}R | {rr[y == 2024].mean():+.3f}R | {rr[y >= 2025].mean():+.3f}R |")
    print("\n".join(L[-4:]), flush=True)

    # проп
    _PD["real"], _PD["mirror"] = prop_data(False), prop_data(True)
    pidx = _PD["real"]["idx"]
    pt1, phi = tier1(), high_approx(pidx)
    PW = lambda ev, b, a: window_mask(pidx, ev, b, a)  # noqa: E731
    pvars = [
        ("без новостного правила", None, None),
        ("**как сейчас: все High, −10…+15 мин**", PW(phi, 10, 15), None),
        ("топ-3, −30…+30 мин", PW(pt1, 30, 30), None),
        ("топ-3, −60…+60 мин", PW(pt1, 60, 60), None),
        ("топ-3, −2 ч…+4 ч", PW(pt1, 120, 240), None),
        ("все High, −60…+60 мин", PW(phi, 60, 60), None),
        ("как сейчас + закрыть сделки за 30 мин до топ-3", PW(phi, 10, 15), cut_mask(pidx, pt1, 30)),
        ("/newstrade off: все High ±30 мин + закрыть за 30 мин", PW(phi, 30, 30), cut_mask(pidx, phi, 30)),
    ]
    jobs = [(n, w, b, c, cost) for n, b, c in pvars for w, cost in (("real", 0.0), ("real", 0.1), ("mirror", 0.0))]
    res = {}
    with Pool(4) as p:
        for name, which, cost, out in p.imap(_prop_row, jobs):
            res[(name, which, cost)] = out
            print(name, which, cost, out, flush=True)
    L += ["", "## Проп (FundedNext): 2-Step этап 1 — прошло / провал / дней; 1-Step — провал; "
          "финансируемый 90 дней — провал", "",
          "| Вариант | до 07.2025 | после 07.2025 | Стресс +0.1R до / после | Зеркало до / после |",
          "|---|---|---|---|---|"]
    fmt = lambda o: f"{o[0][0]:.0f}/{o[0][1]:.0f}/{o[0][2]:.0f}д; 1st {o[1][1]:.0f}%; фин {o[2][1]:.0f}%"  # noqa: E731
    for name, _, _ in pvars:
        a = res[(name, "real", 0.0)]
        s = res[(name, "real", 0.1)]
        m = res[(name, "mirror", 0.0)]
        L.append(f"| {name} | {fmt(a[0])} | {fmt(a[1])} | {s[0][0][0]:.0f}% / {s[1][0][0]:.0f}% "
                 f"| {m[0][0][0]:.0f}% / {m[1][0][0]:.0f}% |")
    out = Path(__file__).resolve().parent.parent / "reports" / "news_table.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
