"""Объём сделки (лот) по капиталу подписчика.

На XAUUSD 1 лот = 100 унций, поэтому 0.01 лота = 1 унция: движение цены на $1
даёт $1 прибыли/убытка. Стоп 100 пипсов (PIP = 0.10) = $10 на каждые 0.01 лота.

Режимы (LOT_MODE в .env):
* risk  — (по умолчанию) лот, при котором стоп забирает не больше LOT_RISK_PCT % капитала
  (по умолчанию 2%; минимум 0.01 — меньше у брокера не открыть);
* table — таблица владельца: <$100 → 0.01, $100 → 0.02, $200 → 0.03,
  дальше +0.01 за каждые следующие $100 (300 → 0.04, 400 → 0.05 …).
"""
from __future__ import annotations

import re

from .data import PIP

OZ_PER_LOT = 100
MIN_CAPITAL, MAX_CAPITAL = 1, 10_000_000
MAX_UNITS = 10_000  # 100 лотов — потолок, чтобы не показывать абсурд


def lot_units(capital: float, mode: str = "risk", risk_pct: float = 2.0, sl_pips: float = 100) -> int:
    """Лот в сотых (1 = 0.01 лота)."""
    if mode == "risk":
        loss_per_unit = sl_pips * PIP * OZ_PER_LOT / 100  # $ убытка по стопу на 0.01 лота
        units = int(capital * risk_pct / 100 / loss_per_unit + 1e-9) if loss_per_unit > 0 else 1
    elif capital < 100:
        units = 1
    elif capital < 200:
        units = 2
    else:
        units = 3 + int((capital - 200) // 100)
    return max(1, min(units, MAX_UNITS))


def lot_for(capital: float, mode: str = "risk", risk_pct: float = 2.0, sl_pips: float = 100) -> float:
    return lot_units(capital, mode, risk_pct, sl_pips) / 100


def money(lot: float, pips: float) -> float:
    """$ прибыли/убытка при движении на pips пипсов этим лотом."""
    return round(lot * OZ_PER_LOT * pips * PIP, 2)


def fmt_usd(x: float) -> str:
    s = f"{x:,.2f}".replace(",", " ")
    return s[:-3] if s.endswith(".00") else s


_NUM = re.compile(r"^\s*\$?\s*(\d[\d\s.,]*?)\s*(\$|usd|usdt|dollars?|долл\w*|доллар\w*|dollar)?\s*$", re.I)


def parse_capital(text: str | None) -> float | None:
    """'150', '$1 000', '1,500', '250.5$', '300 долларов' → число; иначе None."""
    m = _NUM.match(text or "")
    if not m:
        return None
    s = re.sub(r"\s", "", m.group(1))
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = s.replace(",", "") if len(tail) == 3 else head.replace(",", "") + "." + tail
    if s.count(".") > 1:
        s = s.replace(".", "")  # 1.000.000
    try:
        v = float(s)
    except ValueError:
        return None
    return v if MIN_CAPITAL <= v <= MAX_CAPITAL else None
