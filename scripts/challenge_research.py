"""Как сигналы бота проходят челленджи FundedNext: симуляция на истории XAUUSD 12.2023–08.2026.

Каждая попытка начинается в новый торговый день и идёт свеча за свечой (M15), пока счёт не выполнит
цель этапа (с минимумом торговых дней) или не нарушит дневной / общий лимит. Учитываются:
* 5 стратегий бота (STRATEGY=all), стоп 2 ATR / тейк 3 ATR, по одной сделке на стратегию, без встречных
  сделок и без двух сделок в одну сторону на одной свече (как в engine.py);
* риск-менеджмент проп-режима: риск на сделку, все открытые сделки вместе ≤ 2.8 %, дневной стоп бота 3 %
  (или дневной лимит FundedNext, если он меньше) с подушкой 0.5 %, после цели — минимальный лот;
* дневной лимит FundedNext считается по худшей цене свечи с учётом открытых сделок (строже, чем в жизни).

    python scripts/challenge_research.py          # отчёт в reports/challenge_research.md
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goldbot.data import PIP, load_mt5_csv, resample  # noqa: E402
from goldbot.indicators import atr  # noqa: E402
from goldbot.strategies.fvg_bos import fvg_bos_signals  # noqa: E402
from goldbot.strategies.popular import donchian_breakout  # noqa: E402
from goldbot.strategies.research import htf_trend, squeeze_breakout, swing_sweep  # noqa: E402
from goldbot.strategies.sessions import bank_manipulation  # noqa: E402

KEYS = ("squeeze", "donchian", "fvg_m15", "liq_m15", "amd")


@dataclass(frozen=True)
class Plan:
    name: str
    target: float
    daily: float
    total: float
    min_days: int


PLANS = {
    "2step1": Plan("2-Step, этап 1", 8, 5, 10, 5),
    "2step2": Plan("2-Step, этап 2", 5, 5, 10, 5),
    "1step": Plan("1-Step", 10, 3, 6, 2),
    "lite1": Plan("Lite, этап 1", 8, 4, 8, 2),
}


@dataclass(frozen=True)
class Cfg:
    risk: float = 0.5            # % счёта на сделку
    keys: tuple = KEYS
    max_open: int = 9            # сколько сделок бота открыто одновременно
    day_cap: float = 3.0         # дневной стоп бота, % (вместе с плавающим убытком)
    guard: float = 0.5           # подушка до лимитов FundedNext
    day_losses: int = 0          # после стольких стопов за день — день закрыт (0 — нет)
    be_r: float = 0.0            # стоп в безубыток, когда цена прошла столько R (0 — нет)
    dd_cut: float = 0.0          # если баланс ниже старта на столько %, риск ×dd_mult (0 — нет)
    dd_mult: float = 0.5
    near_cut: float = 0.0        # осталось до цели меньше стольких % — риск ×near_mult (0 — нет)
    near_mult: float = 0.5
    day_profit_stop: float = 0.0  # за день +столько % — до конца дня новых сделок нет (0 — нет)
    friday_stop: bool = False    # в пятницу после 18:00 (время сервера) новых сделок нет, всё закрыть в 22:00
    vol_cap: float = 0.0         # ATR выше медианы 20 дней в столько раз — сигнал пропускается (0 — нет)
    one_side: bool = False       # не больше одной сделки в одну сторону
    up_at: float = 0.0           # баланс выше старта на столько % — риск up_risk (0 — нет)
    up_risk: float = 0.5
    cost_r: float = 0.0          # стресс-тест: доп. издержки (комиссия, проскальзывание) в R на каждую сделку


def load(mirror: bool = False):
    """mirror=True — зеркальный график (рост ↔ падение): проверка, что результат не держится только на росте золота."""
    m5 = load_mt5_csv()
    if mirror:
        k = 2 * m5.close.mean()
        m5 = m5.assign(open=k - m5.open, high=k - m5.low, low=k - m5.high, close=k - m5.close)
    df = resample(m5, "15min")
    sig = {
        "squeeze": squeeze_breakout(df),
        "donchian": donchian_breakout(df),
        "fvg_m15": fvg_bos_signals(df),
        "liq_m15": swing_sweep(df),
        "amd": bank_manipulation(df),
    }
    tr = htf_trend(df, "1D", 50)
    for k in ("squeeze", "fvg_m15", "liq_m15"):   # daily_trend=True в live_strategy.py
        sig[k] = np.where(sig[k] == tr, sig[k], 0)
    a = atr(df, 14)
    a_pips = (a / PIP).to_numpy()
    med = a.rolling(96 * 20, min_periods=96).median().to_numpy() / PIP
    sl = np.maximum(50, np.round(2 * a_pips / 10) * 10)
    tp = np.round(sl * 1.5 / 10) * 10
    idx = df.index
    return dict(
        idx=idx, o=df.open.to_numpy(), h=df.high.to_numpy(), l=df.low.to_numpy(),
        spr=df.spread.to_numpy(), sig={k: np.asarray(v, dtype=np.int8) for k, v in sig.items()},
        sl=sl, tp=tp, volr=a_pips / np.where(np.isnan(med), a_pips, med),
        day=np.asarray(idx.normalize().asi8), wd=idx.weekday.to_numpy(), hr=idx.hour.to_numpy(),
    )


def attempt(D, start: int, plan: Plan, cfg: Cfg, end: int | None = None, funded_days: int = 0):
    """Одна попытка с бара start. Возвращает (итог, баланс %, дней календарных, торговых дней, сделок).
    итог: pass / fail_daily / fail_total / open (данные кончились). funded_days > 0 — финансируемый счёт:
    цели нет, смотрим, нарушен ли лимит за столько календарных дней."""
    o, h, l, spr, sl_a, tp_a = D["o"], D["h"], D["l"], D["spr"], D["sl"], D["tp"]
    day, wd, hr, volr, idx = D["day"], D["wd"], D["hr"], D["volr"], D["idx"]
    n = len(o) if end is None else end
    sigs = [(k, D["sig"][k]) for k in cfg.keys]
    bal = 100.0
    day_bal, cur_day = bal, None
    halted = False
    trade_days, traded_today = 0, False
    day_sl = 0
    open_tr: list[dict] = []
    n_tr = 0
    t0 = idx[start]
    stop_at = t0 + pd.Timedelta(days=funded_days) if funded_days else None
    target = None if funded_days else 100 + plan.target
    reached = False
    for i in range(start, n - 1):
        if day[i] != cur_day:
            if traded_today:
                trade_days += 1
            cur_day, day_bal, halted, traded_today, day_sl = day[i], bal, False, False, 0
            if target is not None and bal >= target and trade_days >= plan.min_days:
                return "pass", bal, (idx[i] - t0).days, trade_days, n_tr
            if stop_at is not None and idx[i] >= stop_at:
                return "pass", bal, (idx[i] - t0).days, trade_days, n_tr
        # 1) сопровождение открытых сделок на свече i
        float_r = 0.0
        still = []
        for t in open_tr:
            d = t["d"]
            hi_b, lo_b = h[i], l[i]                      # bid
            hi_a, lo_a = h[i] + spr[i], l[i] + spr[i]    # ask
            px_bad = lo_b if d == 1 else hi_a
            px_good = hi_b if d == 1 else lo_a
            hit_sl = (px_bad <= t["sl"]) if d == 1 else (px_bad >= t["sl"])
            hit_tp = (px_good >= t["tp"]) if d == 1 else (px_good <= t["tp"])
            if hit_sl:
                pnl = (t["sl"] - t["e"]) * d / t["dist"] * t["risk"] - cfg.cost_r * t["risk"]
                bal += pnl
                traded_today = True
                if pnl < 0:
                    day_sl += 1
                continue
            if hit_tp:
                bal += (t["tp"] - t["e"]) * d / t["dist"] * t["risk"] - cfg.cost_r * t["risk"]
                traded_today = True
                continue
            if cfg.be_r and not t["be"] and (px_good - t["e"]) * d >= cfg.be_r * t["dist"]:
                t["sl"] = t["e"] + d * spr[i]
                t["be"] = True
            float_r += (px_bad - t["e"]) * d / t["dist"] * t["risk"]
            still.append(t)
        open_tr = still
        eq_low = bal + float_r
        # 2) лимиты FundedNext (по худшей цене свечи)
        if eq_low <= day_bal - plan.daily:
            return "fail_daily", eq_low, (idx[i] - t0).days, trade_days, n_tr
        if eq_low <= 100 - plan.total:
            return "fail_total", eq_low, (idx[i] - t0).days, trade_days, n_tr
        # 3) дневной стоп бота / подушка: закрыть всё и стоп до завтра
        day_limit = min(cfg.day_cap, plan.daily)
        hard_floor = max(day_bal - plan.daily, 100 - plan.total) + cfg.guard
        if open_tr and (eq_low <= day_bal - day_limit or eq_low <= hard_floor):
            bal = eq_low
            open_tr = []
            halted = True
            traded_today = True
        if not open_tr and bal - (100 - plan.total) <= cfg.guard + 0.1:
            # до общего лимита осталась только подушка: бот больше не может открыть сделку — счёт потерян
            return "fail_total", bal, (idx[i] - t0).days, trade_days, n_tr
        if cfg.friday_stop and wd[i] == 4 and hr[i] >= 22 and open_tr:
            bal += sum((o[i + 1] - t["e"]) * t["d"] / t["dist"] * t["risk"]
                       - (spr[i + 1] / t["dist"] * t["risk"] if t["d"] == 1 else 0) for t in open_tr)
            open_tr = []
            traded_today = True
        if target is not None and bal >= target:
            reached = True
        # 4) новые сигналы на закрытии свечи i, вход по open i+1
        if halted or (cfg.day_losses and day_sl >= cfg.day_losses):
            continue
        if cfg.day_profit_stop and bal - day_bal >= cfg.day_profit_stop:
            continue
        if cfg.friday_stop and wd[i] == 4 and hr[i] >= 18:
            continue
        if cfg.vol_cap and volr[i] > cfg.vol_cap:
            continue
        open_keys = {t["k"] for t in open_tr}
        open_dirs = {t["d"] for t in open_tr}
        fresh = set()
        for k, s in sigs:
            d = int(s[i])
            if d == 0 or k in open_keys or -d in open_dirs or d in fresh:
                continue
            if cfg.one_side and d in open_dirs:
                continue
            if len(open_tr) >= cfg.max_open:
                break
            r = cfg.risk
            if reached:
                r = 0.02                                   # цель есть: минимальный лот ради торговых дней
            else:
                if cfg.up_at and bal >= 100 + cfg.up_at:
                    r = cfg.up_risk
                if cfg.dd_cut and bal <= 100 - cfg.dd_cut:
                    r *= cfg.dd_mult
                if cfg.near_cut and target is not None and target - bal <= cfg.near_cut:
                    r *= cfg.near_mult
            open_risk = sum(t["risk"] * max(0.0, (t["e"] - t["sl"]) * t["d"] / t["dist"]) for t in open_tr)
            day_room = day_limit - max(0.0, day_bal - eq_low)
            hard_room = eq_low - hard_floor
            r = min(r, 2.8, 2.8 - open_risk, day_room - open_risk, hard_room - open_risk)
            if r < 0.01:
                continue
            e = o[i + 1] + (spr[i + 1] if d == 1 else 0.0)
            dist = sl_a[i] * PIP
            open_tr.append(dict(k=k, d=d, e=e, dist=dist, sl=e - d * dist, tp=e + d * tp_a[i] * PIP,
                                risk=r, be=False))
            open_keys.add(k)
            open_dirs.add(d)
            fresh.add(d)
            n_tr += 1
    return "open", bal, (idx[n - 1] - t0).days, trade_days, n_tr


def starts(D, since: str | None = None, until: str | None = None, every: int = 1):
    """Первый бар каждого торгового дня (после разгона индикаторов — с 01.02.2024)."""
    day = D["day"]
    first = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    idx = D["idx"]
    lo = pd.Timestamp(since or "2024-02-01")
    hi = pd.Timestamp(until) if until else idx[-1]
    sel = [i for i in first if lo <= idx[i] < hi]
    return sel[::every]


def summary(D, plan: Plan, cfg: Cfg, st, end=None):
    res = [attempt(D, s, plan, cfg, end) for s in st]
    done = [r for r in res if r[0] != "open"]
    p = [r for r in done if r[0] == "pass"]
    f = [r for r in done if r[0].startswith("fail")]
    return {
        "n": len(done),
        "pass": 100 * len(p) / len(done) if done else 0,
        "fail": 100 * len(f) / len(done) if done else 0,
        "fail_daily": sum(r[0] == "fail_daily" for r in done),
        "days": float(np.median([r[2] for r in p])) if p else float("nan"),
        "p30": 100 * sum(r[2] <= 30 for r in p) / len(done) if done else 0,
        "p60": 100 * sum(r[2] <= 60 for r in p) / len(done) if done else 0,
        "open": len(res) - len(done),
    }


def funded(D, cfg: Cfg, st, days=90, plan=PLANS["2step1"]):
    """Финансируемый счёт (лимиты 2-Step): доля счетов, нарушивших лимит за days дней, и средний итог."""
    res = [attempt(D, s, plan, cfg, funded_days=days) for s in st]
    res = [r for r in res if r[0] != "open"]
    lost = [r for r in res if r[0].startswith("fail")]
    return 100 * len(lost) / len(res), float(np.mean([r[1] - 100 for r in res])), \
        float(np.median([r[1] - 100 for r in res]))


VARIANTS = {
    "как сейчас: 0.5 %": Cfg(),
    "риск 0.25 %": Cfg(risk=0.25),
    "0.5 % + стоп дня после 1-го SL": Cfg(day_losses=1),
    "0.5 % + риск ×0.25 при −2 %": Cfg(dd_cut=2, dd_mult=0.25),
    "**0.5 % + обе защиты (в боте)**": Cfg(day_losses=1, dd_cut=2, dd_mult=0.25),
    "0.4 % + обе защиты": Cfg(risk=0.4, day_losses=1, dd_cut=2, dd_mult=0.25),
    "стресс: как сейчас, издержки +0.1R": Cfg(cost_r=0.1),
    "стресс: обе защиты, издержки +0.1R": Cfg(day_losses=1, dd_cut=2, dd_mult=0.25, cost_r=0.1),
}


def _row(item):
    name, cfg = item
    cells = []
    for key in ("2step1", "2step2", "1step", "lite1"):
        r = summary(_D, PLANS[key], cfg, _ST)
        cells.append(f"{r['pass']:.0f}% / {r['fail']:.1f}% / {r['days']:.0f} дн.")
    lost, _, med = funded(_D, cfg, _ST, 90)
    return f"| {name} | " + " | ".join(cells) + f" | {lost:.1f}% / {med:+.1f}% |"


if __name__ == "__main__":
    from multiprocessing import Pool
    _D = load()
    _ST = starts(_D)
    print("| Вариант | 2-Step этап 1 | 2-Step этап 2 | 1-Step | Lite этап 1 | Финансируемый, 90 дней |")
    print("|---|---|---|---|---|---|")
    with Pool() as pool:
        for row in pool.imap(_row, VARIANTS.items()):
            print(row, flush=True)
