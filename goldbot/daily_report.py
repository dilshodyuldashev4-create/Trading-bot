"""Итоги торгового дня: какие сигналы попали в день, их результат (с учётом фиксации части и безубытка),
картинка-отчёт и подпись к ней. Отправляет App.daily_report в момент закрытия рынка золота."""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from .i18n import t
from .results import signal_pips

CAPTION_MAX = 1024          # лимит подписи к фото в Telegram
FLAT = 0.5                  # |итог| меньше полупипса — безубыток, не плюс и не минус


def day_close(now: pd.Timestamp) -> pd.Timestamp | None:
    """Закрытие торгового дня золота, к которому относится момент now: 17:00 по Нью-Йорку пн–пт
    (21:00 UTC летом, 22:00 UTC зимой). None — сегодня торгового дня нет (сб, вс) или он ещё не закрылся."""
    ny = (now if now.tzinfo else now.tz_localize("UTC")).tz_convert("America/New_York")
    close = ny.normalize() + pd.Timedelta(hours=17)
    if ny.weekday() > 4 or ny < close:
        return None
    return close


def day_open(close: pd.Timestamp) -> pd.Timestamp:
    """Начало этого торгового дня: 18:00 по Нью-Йорку накануне (у понедельника — воскресенье)."""
    return close - pd.Timedelta(hours=23)


@dataclass
class DayRow:
    s: dict
    pips: float | None          # итог на весь лот; None — ещё в работе
    kind: str                   # win | loss | flat | open

    @property
    def tag(self) -> str:
        st = self.s["status"]
        if st == "be" or (st == "tp" and self.s.get("part_at")):
            return "TP1+BE" if st == "be" else "TP1+TP"
        return {"tp": "TP", "sl": "SL", "rev": "REV", "news": "NEWS", "open": "…"}.get(st, st.upper())


@dataclass
class DaySummary:
    rows: list[DayRow] = field(default_factory=list)

    @property
    def closed(self) -> list[DayRow]:
        return [r for r in self.rows if r.kind != "open"]

    def count(self, kind: str) -> int:
        return sum(1 for r in self.rows if r.kind == kind)

    @property
    def pips(self) -> float:
        return sum(r.pips for r in self.closed if r.pips is not None)

    @property
    def winrate(self) -> str:
        decided = self.count("win") + self.count("loss")
        return f"{100 * self.count('win') / decided:.0f}%" if decided else "—"


def summarize(signals: list[dict], start: datetime, end: datetime) -> DaySummary:
    """Сигналы дня: закрытые в [start, end) и открытые в этот день, которые ещё в работе.

    Результат считает results.signal_pips: зафиксированная часть + остаток (тейк, безубыток, стоп, разворот),
    поэтому «фиксация 50% + безубыток» идёт в плюс, а не в ноль и не в минус."""
    out = DaySummary()
    for s in sorted(signals, key=lambda x: x["id"]):
        if s["status"] == "open":
            if start <= datetime.fromisoformat(s["created_at"]) < end:
                out.rows.append(DayRow(s, None, "open"))
            continue
        closed = s.get("closed_at")
        if not closed or not (start <= datetime.fromisoformat(closed) < end):
            continue
        v = signal_pips(s)
        kind = "flat" if v is None or abs(v) < FLAT else ("win" if v > 0 else "loss")
        out.rows.append(DayRow(s, v, kind))
    return out


def _pips(v: float) -> str:
    return f"{'+' if v >= 0 else '−'}{abs(v):.0f}"


def row_text(lang: str, r: DayRow) -> str:
    s = r.s
    side = "BUY" if s["direction"] == 1 else "SELL"
    base = dict(id=s["id"], side=side, entry=f"{s['entry']:.2f}")
    if r.kind == "open":
        key = "daily_row_open_part" if s.get("part_at") else "daily_row_open"
        return t(lang, key, **base)
    icon = {"win": "✅", "loss": "❌", "flat": "➖"}[r.kind]
    st = s["status"]
    if st == "tp":
        how = t(lang, "daily_how_tp_part" if s.get("part_at") else "daily_how_tp", exit=f"{s['tp']:.2f}")
    elif st == "be":
        how = t(lang, "daily_how_be", tp1=f"{s['tp1']:.2f}")
    elif st == "sl":
        how = t(lang, "daily_how_sl", exit=f"{s['sl']:.2f}")
    elif st == "rev":
        how = t(lang, "daily_how_rev", exit=f"{s.get('exit_price') or 0:.2f}")
    else:
        how = t(lang, "daily_how_news", exit=f"{s['exit_price']:.2f}" if s.get("exit_price") else "—")
    pips = _pips(r.pips) if r.pips is not None else "0"
    return t(lang, "daily_row", icon=icon, how=how, pips=pips, **base)


def caption(lang: str, day: DaySummary, date: str, tail: str = "") -> str:
    """Подпись к картинке: итоги дня и каждый сигнал. Не длиннее лимита Telegram: лишние строки уходят
    («остальные на картинке»), итоги и хвост (лот подписчика, ссылка) остаются всегда."""
    if not day.rows:
        return t(lang, "daily_none", date=date) + tail
    head = t(lang, "daily_head", date=date, win=day.count("win"), loss=day.count("loss"),
             flat=t(lang, "daily_flat", n=day.count("flat")) if day.count("flat") else "",
             open=t(lang, "daily_open", n=day.count("open")) if day.count("open") else "",
             wr=day.winrate, pips=_pips(day.pips))
    lines = [row_text(lang, r) for r in day.rows]
    for k in range(len(lines), -1, -1):
        more = t(lang, "daily_more", n=len(lines) - k) if k < len(lines) else ""
        text = head + "\n\n" + "\n".join(lines[:k]) + more + tail
        if len(text) <= CAPTION_MAX:
            return text
    return (head + tail)[:CAPTION_MAX]


LABELS = {
    "ru": {"title": "Итоги торгового дня", "trades": "Сделок", "wl": "Плюс / Минус", "wr": "Винрейт",
           "pips": "Итог, пипсов", "bars": "Результат каждой сделки (пипсы)",
           "cols": ("#", "Время", "Сделка", "Вход", "Выход", "Результат"), "open": "в работе",
           "none": "Сегодня сетапов не было, сделок нет"},
    "en": {"title": "Trading day results", "trades": "Trades", "wl": "Win / Loss", "wr": "Win rate",
           "pips": "Result, pips", "bars": "Result of each trade (pips)",
           "cols": ("#", "Time", "Trade", "Entry", "Exit", "Result"), "open": "open",
           "none": "No setups today, no trades"},
    "uz": {"title": "Savdo kuni natijalari", "trades": "Bitimlar", "wl": "Foyda / Zarar", "wr": "Winrate",
           "pips": "Natija, pips", "bars": "Har bir bitim natijasi (pips)",
           "cols": ("#", "Vaqt", "Savdo", "Kirish", "Chiqish", "Natija"), "open": "ochiq",
           "none": "Bugun setap boʻlmadi, bitim yoʻq"},
}


def exit_price(s: dict) -> float | None:
    st = s["status"]
    return {"tp": s["tp"], "sl": s["sl"], "be": s["entry"]}.get(st, s.get("exit_price"))


def render_daily(day: DaySummary, lang: str, tz: str, date: str) -> bytes:
    """Картинка: заголовок с датой, 4 карточки (сделок, плюс/минус, винрейт, пипсы), столбики результата
    каждой сделки и таблица сделок дня."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    from .chart import BG, CYAN, GOLD, GREEN, GRID, RED, TXT

    L = LABELS.get(lang, LABELS["ru"])
    CARD, MUTED = "#171e2a", "#8a93a6"
    closed = [r for r in day.closed if r.pips is not None]
    n = len(day.rows)
    W = 10.0
    top_h, card_h, bars_h, row_h = 1.35, 1.25, 2.6 if closed else 0.0, 0.42
    table_h = 0.9 + row_h * max(n, 1)
    H = top_h + card_h + 0.35 + bars_h + table_h + 0.25
    fig = plt.figure(figsize=(W, H), facecolor=BG)
    fy = lambda inch: 1 - inch / H  # noqa: E731  (отступ сверху в дюймах → координата фигуры)

    fig.text(0.05, fy(0.35), "XAUUSD", color=GOLD, fontsize=26, fontweight="bold", va="top")
    fig.text(0.05, fy(0.9), L["title"], color=TXT, fontsize=15, va="top")
    fig.text(0.95, fy(0.45), date, color=TXT, fontsize=15, fontweight="bold", ha="right", va="top")

    total = day.pips
    cards = ((L["trades"], str(n), TXT),
             (L["wl"], f"{day.count('win')} / {day.count('loss')}", TXT),
             (L["wr"], day.winrate, GOLD),
             (L["pips"], _pips(total), GREEN if total >= 0 else RED))
    w, gap, x = 0.2075, 0.02, 0.05
    y0 = top_h + card_h
    for label, value, color in cards:
        fig.patches.append(FancyBboxPatch((x, fy(y0)), w, card_h / H, boxstyle="round,pad=0,rounding_size=0.012",
                                          transform=fig.transFigure, fc=CARD, ec="none"))
        fig.text(x + 0.018, fy(top_h + 0.18), label, color=MUTED, fontsize=11, va="top")
        fig.text(x + 0.018, fy(y0 - 0.15), value, color=color, fontsize=24, fontweight="bold", va="bottom")
        x += w + gap

    y = y0 + 0.35
    if closed:
        ax = fig.add_axes([0.07, fy(y + bars_h - 0.2), 0.88, (bars_h - 0.6) / H], facecolor=BG)
        vals = [r.pips for r in closed]
        xs = list(range(len(vals)))
        ax.bar(xs, vals, color=[GREEN if v > FLAT else RED if v < -FLAT else MUTED for v in vals], width=0.6)
        for i, v in enumerate(vals):
            ax.text(i, v, _pips(v), color=TXT, fontsize=10, ha="center", va="bottom" if v >= 0 else "top")
        ax.axhline(0, color=GRID, lw=1)
        ax.set_xticks(xs, [f"#{r.s['id']}" for r in closed])
        lo, hi = min(vals + [0]), max(vals + [0])
        pad = (hi - lo) * 0.18 or 10
        ax.set_ylim(lo - pad, hi + pad)
        ax.set_title(L["bars"], color=TXT, fontsize=12, loc="left")
        ax.tick_params(colors=MUTED, labelsize=9)
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.grid(color=GRID, linestyle=":", axis="y")
        y += bars_h

    cols_x = (0.05, 0.13, 0.27, 0.42, 0.57, 0.72)
    y += 0.3
    for cx, name in zip(cols_x, L["cols"]):
        fig.text(cx, fy(y), name, color=MUTED, fontsize=10, va="center")
    if not day.rows:
        fig.text(0.5, fy(y + 0.6), L["none"], color=MUTED, fontsize=13, ha="center", va="center")
    zone = ZoneInfo(tz)
    for i, r in enumerate(day.rows):
        y += row_h
        s = r.s
        if i % 2 == 0:
            fig.patches.append(FancyBboxPatch((0.04, fy(y + row_h * 0.4)), 0.92, row_h * 0.8 / H,
                                              boxstyle="round,pad=0,rounding_size=0.006",
                                              transform=fig.transFigure, fc=CARD, ec="none"))
        when = datetime.fromisoformat(s["created_at"]).astimezone(zone).strftime("%H:%M")
        buy = s["direction"] == 1
        ex = exit_price(s)
        if r.kind == "open":
            result, rc = L["open"], GOLD
        else:
            mark = {"win": "✓", "loss": "✗", "flat": "•"}[r.kind]
            result = f"{mark} {r.tag} {_pips(r.pips) if r.pips is not None else '0'}"
            rc = {"win": GREEN, "loss": RED, "flat": MUTED}[r.kind]
        vals = ((f"#{s['id']}", TXT), (when, TXT), ("▲ BUY" if buy else "▼ SELL", GREEN if buy else RED),
                (f"{s['entry']:.2f}", TXT), (f"{ex:.2f}" if ex and r.kind != "open" else "—", CYAN),
                (result, rc))
        for cx, (v, c) in zip(cols_x, vals):
            fig.text(cx, fy(y), v, color=c, fontsize=10.5, va="center",
                     fontweight="bold" if cx == cols_x[-1] else "normal")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
