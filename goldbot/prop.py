"""Проп-счета FundedNext: правила по типам счетов и расчёты риска.

Правила FundedNext (CFD, Stellar), проверено по fundednext.com/general-rules/cfds/trading-objectives:
* Stellar 2-Step — дневной лимит 5 %, общий 10 % (статичный, от начального баланса);
* Stellar 1-Step — дневной 3 %, общий 6 % (статичный);
* Stellar Lite   — дневной 4 %, общий 8 % (статичный);
* Stellar Instant — дневного лимита нет, общий 6 % «плавающий»: поднимается вслед за прибылью
  и останавливается на начальном балансе.
Цели челленджа: 2-Step 8 % и 5 %, 1-Step 10 %, Lite 8 % и 4 %; минимум торговых дней 5 / 2 / 2.
Цель считается только по закрытым сделкам; торговый день — день, когда была сделка с ненулевым P&L.
Дневной лимит считается от баланса на начало дня (00:00 по времени сервера FundedNext — Афины,
GMT+2 / GMT+3 летом) и включает закрытые и открытые сделки, своп и комиссию. Проценты — всегда от
начального размера счёта. На финансируемом счёте суммарный риск всех открытых сделок — не больше 3 %.
EA/боты FundedNext разрешает только на MT4/MT5, на счетах меньше $50 000 и с дополнением «EA»
(или «VPS & EA»), купленным вместе со счётом.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Plan:
    name: str
    daily_pct: float      # 0 — дневного лимита нет
    total_pct: float
    trailing: bool        # общий лимит поднимается за прибылью (Instant)
    sizes: tuple[int, ...]  # только размеры, где FundedNext разрешает ботов (до $50 000)
    targets: dict         # этап → цель по прибыли, % (только по закрытым сделкам)
    min_days: int         # минимум торговых дней на этапе челленджа

    @property
    def stages(self) -> tuple[str, ...]:
        return (*self.targets, "funded")


PLANS: dict[str, Plan] = {
    "2step": Plan("Stellar 2-Step", 5, 10, False, (6_000, 15_000, 25_000),
                  {"phase1": 8, "phase2": 5}, 5),
    "1step": Plan("Stellar 1-Step", 3, 6, False, (6_000, 15_000, 25_000),
                  {"phase1": 10}, 2),
    "lite": Plan("Stellar Lite", 4, 8, False, (5_000, 10_000, 25_000),
                 {"phase1": 8, "phase2": 4}, 2),
    "instant": Plan("Stellar Instant", 0, 6, True, (2_000, 5_000, 10_000, 20_000), {}, 0),
}
# Риск-менеджмент бота (строже FundedNext), всё — в % от размера счёта:
# * на одну сделку — не больше 2.8 % (по умолчанию бот ставит меньше, PROP_RISK_PCT): у FundedNext
#   предел 3 %, а при резком скачке стоп может исполниться хуже — 0.2 % оставляем на проскальзывание;
# * все открытые сделки вместе (что они ещё могут потерять до своих стопов) — тоже не больше 2.8 %
#   (правило FundedNext: суммарный риск открытых сделок не больше 3 %);
# * за день — закрытые убытки + плавающий убыток + стопы открытых сделок — не больше 3 % и не больше
#   дневного лимита FundedNext; до лимитов самой FundedNext бот держит подушку (PROP_GUARD_PCT).
# Действует и в челлендже, и на финансируемом счёте.
MAX_TRADE_PCT = 2.8
MAX_OPEN_PCT = 2.8
DAILY_CAP_PCT = 3.0


def day_key(t: datetime, tz: str = "Europe/Athens") -> str:
    """Торговый день FundedNext: дата по времени сервера (полночь по Афинам)."""
    return t.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d")


# Защита по итогам симуляции челленджей (reports/challenge_research.md, история XAUUSD 12.2023–08.2026):
# * после первого Stop Loss за торговый день бот до полуночи FundedNext новые сделки на проп-счёте не открывает
#   (убытки идут сериями внутри дня: после первого стопа средний результат следующих сделок того дня в минусе);
# * баланс ниже начального на DD_PCT % — риск на сделку × DD_MULT, пока баланс не вернётся выше.
# 2-Step при 0.5 %: без защиты не проходит ~1 попытка из 5, с ней — 0 из ~640 попыток в истории.
DAY_LOSSES = 1
DD_PCT = 2.0
DD_MULT = 0.25


def day_start(t: datetime, tz: str = "Europe/Athens") -> datetime:
    """Начало текущего торгового дня FundedNext (полночь по времени сервера) — для сравнения с временем сделок."""
    local = t.astimezone(ZoneInfo(tz))
    return datetime(local.year, local.month, local.day, tzinfo=ZoneInfo(tz))


def scaled_risk(risk_pct: float, balance: float, size: float, dd_pct: float = DD_PCT,
                mult: float = DD_MULT) -> float:
    """Риск на сделку с учётом просадки: баланс ниже размера счёта на dd_pct % — риск × mult (dd_pct 0 — выкл.)."""
    if dd_pct > 0 and size > 0 and balance <= size * (1 - dd_pct / 100):
        return risk_pct * mult
    return risk_pct


def reset_time(tz_show: str, t: datetime, tz: str = "Europe/Athens") -> str:
    """Во сколько по часам tz_show начинается следующий торговый день FundedNext (например «03:00»)."""
    from datetime import timedelta
    z = ZoneInfo(tz)
    local = t.astimezone(z)
    midnight = datetime(local.year, local.month, local.day, tzinfo=z) + timedelta(days=1)
    return midnight.astimezone(ZoneInfo(tz_show)).strftime("%H:%M")


@dataclass
class Limits:
    daily_floor: float          # ниже этих средств сегодня опускаться нельзя (правило бота или FundedNext)
    total_floor: float          # общий лимит FundedNext: ниже — никогда
    floor: float                # строже из двух
    binding: str                # "daily" или "total" — какой лимит ближе
    room: float                 # сколько ещё можно потерять до ближайшего лимита (может быть < 0)
    hard_room: float            # сколько до лимитов самой FundedNext (здесь держим подушку)
    day_loss: float             # потеряно сегодня от баланса на начало дня (≥ 0)
    day_limit: float            # дневной лимит в $, по которому работает бот


def limits(acc: dict, equity: float, cap: float = DAILY_CAP_PCT) -> Limits:
    """acc — строка trade_accounts с полями prop_plan, prop_size, prop_day_balance, prop_peak."""
    plan = PLANS[acc["prop_plan"]]
    size = float(acc["prop_size"])
    if plan.trailing:  # Instant: от максимума, но не выше начального баланса
        peak = max(float(acc.get("prop_peak") or size), size)
        total_floor = min(peak - size * plan.total_pct / 100, size)
    else:
        total_floor = size * (1 - plan.total_pct / 100)
    day_bal = float(acc.get("prop_day_balance") or size)
    fn_daily = size * plan.daily_pct / 100 if plan.daily_pct else float("inf")
    day_limit = min(fn_daily, size * cap / 100)
    daily_floor = day_bal - day_limit
    if daily_floor >= total_floor:
        floor, binding = daily_floor, "daily"
    else:
        floor, binding = total_floor, "total"
    hard = max(day_bal - fn_daily, total_floor)
    return Limits(daily_floor, total_floor, floor, binding, equity - floor, equity - hard,
                  max(0.0, day_bal - equity), day_limit)


def open_risk(positions: list[dict], contract: float = 100) -> float:
    """Сколько ещё могут потерять открытые сделки до своих Stop Loss (в $). Сделка без стопа
    считается по своему текущему убытку — бот такие сделки сам не открывает."""
    total = 0.0
    for p in positions:
        vol = float(p.get("volume") or 0)
        sl = float(p.get("stopLoss") or 0)
        cur = float(p.get("currentPrice") or 0)
        buy = "BUY" in str(p.get("type", "")).upper()
        if vol <= 0 or cur <= 0 or sl <= 0:
            continue
        dist = (cur - sl) if buy else (sl - cur)
        total += max(0.0, dist) * vol * contract
    return total


def risk_budget(acc: dict, equity: float, positions: list[dict], risk_pct: float, guard_pct: float,
                contract: float = 100, cap: float = DAILY_CAP_PCT,
                max_trade: float = MAX_TRADE_PCT) -> tuple[float, str]:
    """Сколько $ можно поставить на новую сделку на проп-счёте и почему столько. Меньшее из:
    risk_pct % счёта (не больше 2.8 %); 2.8 % на все открытые сделки вместе; остатка дневного риска
    (3 % вместе с сегодняшними убытками и стопами открытых сделок); запаса до лимитов FundedNext
    минус подушка guard_pct % счёта."""
    size = float(acc["prop_size"])
    lim = limits(acc, equity, cap)
    already = open_risk(positions, contract)
    options = {
        "risk": size * min(risk_pct, max_trade, MAX_TRADE_PCT) / 100,
        "open": size * MAX_OPEN_PCT / 100 - already,
        lim.binding: lim.room - already,
        "fundednext": lim.hard_room - size * guard_pct / 100 - already,
    }
    reason = min(options, key=options.get)
    return max(0.0, options[reason]), reason


def volume_for(budget_usd: float, sl_dist: float, spec: dict | None = None, max_lot: float = 100) -> float:
    """Лот, при котором стоп забирает не больше budget_usd. 0 — даже минимальный лот не помещается."""
    spec = spec or {}
    contract = float(spec.get("contractSize") or 100)
    step = float(spec.get("volumeStep") or 0.01)
    vmin = float(spec.get("minVolume") or 0.01)
    vmax = float(spec.get("maxVolume") or 100)
    if budget_usd <= 0 or sl_dist <= 0:
        return 0.0
    vol = math.floor(budget_usd / (contract * sl_dist) / step + 1e-9) * step
    vol = min(vol, vmax, max_lot)
    return round(vol, 2) if vol + 1e-9 >= vmin else 0.0


def target_balance(acc: dict) -> float | None:
    """Баланс, при котором цель этапа выполнена (None — у этапа нет цели: финансируемый счёт)."""
    pct = PLANS[acc["prop_plan"]].targets.get(acc.get("prop_stage") or "")
    return float(acc["prop_size"]) * (1 + pct / 100) if pct else None


def next_stage(acc: dict) -> str | None:
    stages = PLANS[acc["prop_plan"]].stages
    st = acc.get("prop_stage") or ""
    return stages[stages.index(st) + 1] if st in stages[:-1] else None


def phase_passed(acc: dict, balance: float) -> bool:
    goal = target_balance(acc)
    plan = PLANS[acc["prop_plan"]]
    return goal is not None and balance + 1e-6 >= goal and int(acc.get("prop_days") or 0) >= plan.min_days
