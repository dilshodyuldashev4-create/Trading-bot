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
                  sl_note: str = "", tp_note: str = "") -> bytes:
    """lot — подпись «LOT 0.02» для конкретного подписчика; sl_note/tp_note — суммы в $ у линий."""
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
    for y, c, label, note in ((tp, CYAN, "TP", tp_note), (entry, GOLD, "ВХОД", ""), (sl, RED, "SL", sl_note)):
        ax.hlines(y, x0, x1, colors=c, linewidth=1.6)
        ax.text(x1, y, f" {label} {y:.2f}" + (f"  {note}" if note else ""), color="black", fontsize=10, fontweight="bold", va="center",
                ha="left", bbox=dict(boxstyle="round,pad=0.3", fc=c, ec="none"))
    arrow = "▲ BUY" if direction == 1 else "▼ SELL"
    ax.annotate(arrow, (x0, entry), xytext=(x0 - 8, entry + (-1 if direction == 1 else 1) * (abs(tp - entry) * 0.6)),
                color=GREEN if direction == 1 else RED, fontsize=14, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=GREEN if direction == 1 else RED, lw=1.5))
    ax.set_title(title, color=TXT, fontsize=13, loc="left")
    if lot:
        ax.text(0.01, 0.97, lot, transform=ax.transAxes, color="black", fontsize=15, fontweight="bold",
                va="top", ha="left", bbox=dict(boxstyle="round,pad=0.4", fc=GOLD, ec="none"))
    ax.set_ylabel("")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
