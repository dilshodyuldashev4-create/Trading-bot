"""Картинка сигнала: свечи, зона входа, SL и TP."""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import mplfinance as mpf  # noqa: E402
import pandas as pd  # noqa: E402

BG, GRID, TXT = "#0f141c", "#1f2633", "#d1d4dc"
GREEN, RED, GOLD, CYAN = "#26c281", "#f23645", "#ffd600", "#00bcd4"


def render_signal(df: pd.DataFrame, direction: int, entry: float, sl: float, tp: float,
                  title: str, bars: int = 70, tz: str | None = None, lot: str | None = None,
                  sl_note: str = "", tp_note: str = "",
                  mfe: float | None = None, mae: float | None = None, pip: float = 0.10) -> bytes:
    """lot — «LOT 0.02» у линии входа для конкретного подписчика; sl_note/tp_note — суммы в $ у линий.
    mfe/mae — макс. ход в плюс и в минус по закрытой сделке (пипсы): рисуются пунктиром с подписью."""
    data = df.iloc[-bars:].copy()
    if tz:
        idx = data.index.tz_localize("UTC") if data.index.tz is None else data.index
        data.index = idx.tz_convert(tz).tz_localize(None)
    mc = mpf.make_marketcolors(up=GREEN, down=RED, edge="inherit", wick="inherit")
    style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mc, facecolor=BG,
                               figcolor=BG, gridcolor=GRID, gridstyle=":", rc={"axes.labelcolor": TXT,
                                                                                "xtick.color": TXT, "ytick.color": TXT})
    pad = 12
    fig, axes = mpf.plot(data, type="candle", style=style, returnfig=True, figsize=(11, 6.2),
                         xlim=(0, len(data) + pad), ylim=(min(data.low.min(), sl, tp) - 1,
                                                         max(data.high.max(), sl, tp) + 1),
                         tight_layout=True, datetime_format="%d.%m %H:%M", xrotation=0)
    ax = axes[0]
    x0, x1 = len(data) - 1, len(data) + pad - 1
    ax.fill_between([x0, x1], entry, tp, color=GREEN, alpha=0.18)
    ax.fill_between([x0, x1], entry, sl, color=RED, alpha=0.18)
    for y, c, label, note in ((tp, CYAN, "TP", tp_note), (entry, GOLD, "ВХОД", lot or ""), (sl, RED, "SL", sl_note)):
        ax.hlines(y, x0, x1, colors=c, linewidth=1.6)
        ax.text(x1, y, f" {label} {y:.2f}" + (f"  {note}" if note else ""), color="black", fontsize=10, fontweight="bold", va="center",
                ha="left", bbox=dict(boxstyle="round,pad=0.3", fc=c, ec="none"))
    for v, sign, c in ((mfe, 1, GREEN), (mae, -1, "#ff9f43")):
        if v is None or v < 1:
            continue
        y = entry + sign * direction * v * pip
        if min(abs(y - sl), abs(y - tp)) < 3 * pip:
            continue  # совпадает с линией SL/TP — не дублируем
        ax.hlines(y, 0, x1, colors=c, linewidth=1.3, linestyles="--")
        ax.text(1, y, f" MAX {'+' if sign > 0 else '−'}{v:.0f} pips  {y:.2f} ", color="black", fontsize=10,
                fontweight="bold", va="bottom" if sign * direction > 0 else "top", ha="left",
                bbox=dict(boxstyle="round,pad=0.3", fc=c, ec="none"))
    arrow = "▲ BUY" if direction == 1 else "▼ SELL"
    ax.annotate(arrow, (x0, entry), xytext=(x0 - 8, entry + (-1 if direction == 1 else 1) * (abs(tp - entry) * 0.6)),
                color=GREEN if direction == 1 else RED, fontsize=14, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=GREEN if direction == 1 else RED, lw=1.5))
    ax.set_title(title, color=TXT, fontsize=13, loc="left")
    ax.set_ylabel("")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


STATS_LABELS = {
    "ru": {"title": "Статистика сигналов", "signals": "Сигналов", "wr": "Винрейт", "tpsl": "TP / SL",
           "pips": "Итог, пипсов", "equity": "Рост результата (пипсы)", "last": "Последние сигналы",
           "cols": ("#", "Дата", "Сделка", "Вход", "SL", "TP", "Результат"), "open": "в работе"},
    "en": {"title": "Signal statistics", "signals": "Signals", "wr": "Win rate", "tpsl": "TP / SL",
           "pips": "Result, pips", "equity": "Equity curve (pips)", "last": "Latest signals",
           "cols": ("#", "Date", "Trade", "Entry", "SL", "TP", "Result"), "open": "open"},
    "uz": {"title": "Signallar statistikasi", "signals": "Signallar", "wr": "Winrate", "tpsl": "TP / SL",
           "pips": "Natija, pips", "equity": "Natija oʻsishi (pips)", "last": "Oxirgi signallar",
           "cols": ("#", "Sana", "Savdo", "Kirish", "SL", "TP", "Natija"), "open": "ochiq"},
}


def render_stats(rows: list[dict], lang: str = "ru", tz: str = "UTC", pip: float = 0.10,
                 last: int = 10) -> bytes:
    """Картинка-отчёт: карточки (сигналы, винрейт, TP/SL, итог), кривая результата, таблица последних сделок.

    rows — сигналы из БД, от новых к старым.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from matplotlib.patches import FancyBboxPatch

    L = STATS_LABELS.get(lang, STATS_LABELS["ru"])
    CARD, MUTED = "#171e2a", "#8a93a6"
    chron = list(reversed(rows))
    closed = [r for r in chron if r["status"] in ("tp", "sl")]
    res = [(abs(r["tp"] - r["entry"]) if r["status"] == "tp" else -abs(r["sl"] - r["entry"])) / pip for r in closed]
    n_tp = sum(1 for r in closed if r["status"] == "tp")
    n_sl = len(closed) - n_tp
    wr = f"{100 * n_tp / len(closed):.0f}%" if closed else "—"
    total = sum(res)

    fig = plt.figure(figsize=(10, 11.5), facecolor=BG)
    fig.text(0.05, 0.965, "XAUUSD", color=GOLD, fontsize=26, fontweight="bold", va="top")
    fig.text(0.05, 0.925, L["title"], color=TXT, fontsize=15, va="top")
    fig.text(0.95, 0.955, datetime.now(ZoneInfo(tz)).strftime("%d.%m.%Y %H:%M"), color=MUTED,
             fontsize=11, ha="right", va="top")

    cards = ((L["signals"], str(len(rows)), TXT), (L["wr"], wr, GOLD),
             (L["tpsl"], f"{n_tp} / {n_sl}", TXT), (L["pips"], f"{total:+.0f}", GREEN if total >= 0 else RED))
    w, gap, x = 0.2075, 0.02, 0.05
    for label, value, color in cards:
        fig.patches.append(FancyBboxPatch((x, 0.79), w, 0.1, boxstyle="round,pad=0,rounding_size=0.012",
                                          transform=fig.transFigure, fc=CARD, ec="none"))
        fig.text(x + 0.018, 0.872, label, color=MUTED, fontsize=11, va="top")
        fig.text(x + 0.018, 0.805, value, color=color, fontsize=24, fontweight="bold", va="bottom")
        x += w + gap

    ax = fig.add_axes([0.07, 0.5, 0.88, 0.24], facecolor=BG)
    eq = [0.0]
    for v in res:
        eq.append(eq[-1] + v)
    xs = list(range(len(eq)))
    ax.plot(xs, eq, color=GOLD, lw=2.2)
    ax.fill_between(xs, eq, 0, color=GOLD, alpha=0.12)
    ax.axhline(0, color=GRID, lw=1)
    for i, v in enumerate(res, start=1):
        ax.scatter(i, eq[i], s=22, color=GREEN if v > 0 else RED, zorder=3)
    ax.set_title(L["equity"], color=TXT, fontsize=12, loc="left")
    ax.tick_params(colors=MUTED, labelsize=9)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.grid(color=GRID, linestyle=":")
    ax.set_xlim(0, max(1, len(eq) - 1))

    fig.text(0.05, 0.445, L["last"], color=TXT, fontsize=12, va="top")
    cols_x = (0.05, 0.12, 0.27, 0.40, 0.53, 0.65, 0.77)
    y = 0.405
    for cx, name in zip(cols_x, L["cols"]):
        fig.text(cx, y, name, color=MUTED, fontsize=10, va="center")
    for i, r in enumerate(rows[:last]):
        y -= 0.036
        if i % 2 == 0:
            fig.patches.append(FancyBboxPatch((0.04, y - 0.016), 0.92, 0.032, boxstyle="round,pad=0,rounding_size=0.006",
                                              transform=fig.transFigure, fc=CARD, ec="none"))
        when = datetime.fromisoformat(r["created_at"]).astimezone(ZoneInfo(tz)).strftime("%d.%m %H:%M")
        buy = r["direction"] == 1
        if r["status"] == "tp":
            result, rc = f"✓ TP +{abs(r['tp'] - r['entry']) / pip:.0f}", GREEN
        elif r["status"] == "sl":
            result, rc = f"✗ SL −{abs(r['sl'] - r['entry']) / pip:.0f}", RED
        else:
            result, rc = L["open"], GOLD
        vals = ((f"#{r['id']}", TXT), (when, TXT), ("▲ BUY" if buy else "▼ SELL", GREEN if buy else RED),
                (f"{r['entry']:.2f}", TXT), (f"{r['sl']:.2f}", RED), (f"{r['tp']:.2f}", CYAN), (result, rc))
        for cx, (v, c) in zip(cols_x, vals):
            fig.text(cx, y, v, color=c, fontsize=10.5, va="center",
                     fontweight="bold" if c in (GREEN, RED) and cx == cols_x[-1] else "normal")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
