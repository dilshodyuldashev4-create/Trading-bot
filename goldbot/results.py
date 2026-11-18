"""Результат сигнала в пипсах с учётом фиксации части прибыли."""
from __future__ import annotations

from .data import PIP

WIN = ("tp", "be", "rev")   # закрыт в плюсе: тейк, безубыток после фиксации, закрытие при развороте


def part_pips(s: dict) -> float:
    """Сколько пипсов принесла зафиксированная часть (0 — фиксации не было)."""
    if not s.get("part_at") or not s.get("tp1"):
        return 0.0
    return (s.get("part") or 0) * s["direction"] * (s["tp1"] - s["entry"]) / PIP


def exit_level(s: dict, status: str) -> float | None:
    """Цена, по которой закрылся остаток."""
    if status == "tp":
        return s["tp"]
    if status == "sl":
        return s["sl"]
    if status == "be":
        return s["entry"]
    return s.get("exit_price")


def signal_pips(s: dict, status: str | None = None) -> float | None:
    """Итог сигнала в пипсах на весь лот: зафиксированная часть + остаток. None — сделка ещё открыта
    или закрыта без цены выхода."""
    status = status or s.get("status")
    level = exit_level(s, status)
    if status == "open" or level is None:
        return None
    rest = 1 - (s.get("part") or 0) if s.get("part_at") else 1.0
    return part_pips(s) + rest * s["direction"] * (level - s["entry"]) / PIP


def move_pips(s: dict, status: str | None = None) -> float | None:
    """Сколько пипсов прошла цена от входа до выхода остатка (без учёта фиксации части).
    Для сигнала без фиксации совпадает с signal_pips."""
    status = status or s.get("status")
    level = exit_level(s, status)
    if status == "open" or level is None:
        return None
    return s["direction"] * (level - s["entry"]) / PIP


def tp1_move_pips(s: dict) -> float:
    """Сколько пипсов было до уровня фиксации части (на зафиксированный объём)."""
    if not s.get("tp1"):
        return 0.0
    return s["direction"] * (s["tp1"] - s["entry"]) / PIP
