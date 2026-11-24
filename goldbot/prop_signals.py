"""Сигналы для проп-фирм (FundedNext и похожие) для тех, кто торгует руками.

Подписчик заполняет анкету: тип счёта, этап (челлендж 1, 2 или финансируемый) и размер счёта. Дальше вместо
обычных сигналов он получает отдельный проп-поток — те же сделки, что бот открывает на проп-счетах автоторговли
(симуляция челленджей: /mnt/project-files/backtest/challenge_research.md, «обе защиты»):

* риск на сделку 0.5 % от размера счёта (PROP_RISK_PCT), сильный сигнал — PROP_STRONG_RISK_PCT, не больше 1 %;
* все открытые проп-сделки вместе — не больше 1.5 %, за день — не больше 3 % и дневного лимита фирмы;
* баланс ниже начального на 2 % — риск × 0.25, пока не вернётся;
* **первая сделка за день закрылась по Stop Loss — до полуночи FundedNext проп-сигналов больше нет**
  (после первого стопа результат следующих сделок того дня в среднем отрицательный);
* тейк — PROP_TP_R стопов, без фиксации части и безубытка (как на проп-счетах автоторговли);
* цель этапа выполнена, а торговых дней не хватает — минимальный лот.

Баланс бот ведёт сам по результатам проп-сигналов, которые подписчик не отклонил; подписчик может в любой момент
ввести свой настоящий баланс. После каждой закрытой сделки и каждое утро бот напоминает: баланс, сколько до цели,
сколько можно потерять до дневного и общего лимита и сколько рисковать на следующую сделку.
"""
from __future__ import annotations

from datetime import datetime

from . import prop as pr
from .data import PIP
from .lots import fmt_usd

SIZE_PRESETS = (5_000, 10_000, 25_000, 50_000, 100_000, 200_000)
MIN_SIZE, MAX_SIZE = 1_000, 2_000_000
MIN_LOT = 0.01
MAX_LOT = 50.0


def acc_view(sub: dict) -> dict:
    """Строка prop_subs в виде, который понимают функции goldbot.prop."""
    size = float(sub["size"])
    return {"prop_plan": sub["plan"], "prop_stage": sub.get("stage"), "prop_size": size,
            "prop_day_balance": float(sub.get("day_balance") or sub.get("balance") or size),
            "prop_peak": float(sub.get("peak") or size), "prop_days": int(sub.get("days") or 0)}


def prop_tp(entry: float, sl: float, tp: float, direction: int, partial_r: float, prop_tp_r: float) -> float:
    """Тейк проп-сделки: PROP_TP_R стопов (как на проп-счетах автоторговли, где нет фиксации части и безубытка).
    Если фиксация части у обычных сигналов выключена (PARTIAL_R=0) — тейк сигнала."""
    if partial_r <= 0 or prop_tp_r <= 0:
        return tp
    return round(entry + direction * abs(entry - sl) * prop_tp_r, 2)


def roll_day(sub: dict, t: datetime, tz: str) -> dict:
    """Новый торговый день фирмы: баланс на начало дня = текущий. Возвращает поля, которые надо обновить."""
    today = pr.day_key(t, tz)
    if sub.get("day") == today:
        return {}
    return {"day": today, "day_balance": float(sub.get("balance") or sub["size"])}


def open_positions(trades: list[dict]) -> list[dict]:
    """Открытые проп-сделки подписчика в формате позиций для pr.open_risk (цена — вход: риск до стопа)."""
    return [{"volume": tr["lot"], "stopLoss": tr["sl"], "currentPrice": tr["entry"],
             "type": "BUY" if tr["direction"] == 1 else "SELL"} for tr in trades]


def plan_trade(sub: dict, trades: list[dict], sl_dist: float, *, risk_pct: float, strong_pct: float,
               strong: bool, guard_pct: float, cap: float, max_trade: float, dd_pct: float,
               dd_mult: float) -> dict:
    """Лот проп-сигнала для подписчика. {"lot", "risk_usd", "risk_pct", "reason"}; lot 0 — сигнал не даём.
    reason: risk/open/daily/total/fundednext — что ограничило лот, goal — цель есть, минимальный лот."""
    acc = acc_view(sub)
    size = acc["prop_size"]
    balance = float(sub.get("balance") or size)
    goal = pr.target_balance(acc)
    if goal is not None and balance + 1e-6 >= goal:
        return {"lot": MIN_LOT, "risk_usd": round(MIN_LOT * 100 * sl_dist, 2),
                "risk_pct": MIN_LOT * 100 * sl_dist / size * 100, "reason": "goal"}
    risk = pr.scaled_risk(strong_pct if strong else risk_pct, balance, size, dd_pct, dd_mult)
    budget, reason = pr.risk_budget(acc, balance, open_positions(trades), risk, guard_pct, 100,
                                    min(cap, pr.DAILY_CAP_PCT), max_trade)
    lot = pr.volume_for(budget, sl_dist, None, MAX_LOT)
    risk_usd = round(lot * 100 * sl_dist, 2)
    return {"lot": lot, "risk_usd": risk_usd, "risk_pct": risk_usd / size * 100, "reason": reason}


def trade_pips(tr: dict, status: str, price: float | None = None) -> float:
    """Пипсы проп-сделки на выходе: sl — до стопа, tp — до своего тейка, иначе — до цены."""
    d = tr["direction"]
    level = {"sl": tr["sl"], "tp": tr["tp"]}.get(status, price if price is not None else tr["entry"])
    return d * (level - tr["entry"]) / PIP


def hit(tr: dict, price: float) -> str | None:
    """Задела ли цена стоп или тейк проп-сделки."""
    d = tr["direction"]
    if d * (price - tr["sl"]) <= 0:
        return "sl"
    if d * (price - tr["tp"]) >= 0:
        return "tp"
    return None


def apply_result(sub: dict, pnl: float, t: datetime, tz: str) -> dict:
    """Результат закрытой сделки → новые поля подписчика (баланс, максимум, торговые дни)."""
    bal = round(float(sub.get("balance") or sub["size"]) + pnl, 2)
    upd = {"balance": bal, "peak": max(float(sub.get("peak") or sub["size"]), bal)}
    day = pr.day_key(t, tz)
    if abs(pnl) > 1e-9 and sub.get("last_day") != day:   # торговый день — день со сделкой с ненулевым P&L
        upd["days"] = int(sub.get("days") or 0) + 1
        upd["last_day"] = day
    return upd


def state(sub: dict, *, risk_pct: float, cap: float, max_trade: float, dd_pct: float, dd_mult: float) -> dict:
    """Всё для напоминания: баланс, цель, запас до дневного и общего лимита, риск на следующую сделку."""
    acc = acc_view(sub)
    size = acc["prop_size"]
    balance = float(sub.get("balance") or size)
    plan = pr.PLANS[sub["plan"]]
    lim = pr.limits(acc, balance, min(cap, pr.DAILY_CAP_PCT))
    goal = pr.target_balance(acc)
    risk = min(pr.scaled_risk(risk_pct, balance, size, dd_pct, dd_mult), max_trade, pr.MAX_TRADE_PCT)
    passed = goal is not None and balance + 1e-6 >= goal
    return {
        "plan": plan, "size": size, "balance": balance, "goal": goal,
        "to_goal": max(0.0, goal - balance) if goal is not None else None,
        "progress": pr.progress(acc, balance),
        "day_left": max(0.0, balance - lim.daily_floor),
        "day_limit": lim.day_limit, "day_floor": lim.daily_floor,
        "total_floor": lim.total_floor, "total_left": max(0.0, balance - lim.total_floor),
        "risk_pct": 0.0 if passed else risk, "risk_usd": size * (0.0 if passed else risk) / 100,
        "low_risk": risk < min(risk_pct, max_trade) - 1e-9,
        "passed": passed, "days": int(sub.get("days") or 0), "min_days": plan.min_days if goal else 0,
        "failed": balance <= lim.total_floor + 1e-6,
    }


def usd(x: float) -> str:
    return ("−$" if x < 0 else "$") + fmt_usd(abs(round(x, 2)))
