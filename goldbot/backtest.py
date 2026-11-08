"""Бэктест с фиксированным риском: SL и TP в пипсах (1 пип = 0.10 $).

Правила (консервативные):
* сигнал по закрытию бара i, вход по open бара i+1; BUY по ask (open + спред), SELL по bid;
* одна позиция за раз, новые сигналы во время сделки пропускаются;
* если в одной свече задеты и SL, и TP — считаем стоп (худший случай);
* сделка, не закрытая к концу данных, не учитывается.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .data import PIP


@dataclass
class Trade:
    entry_time: pd.Timestamp
    direction: int
    entry: float
    sl: float
    tp: float
    exit_time: pd.Timestamp | None = None
    result: str = ""        # "TP" / "SL"
    pips: float = 0.0


@dataclass
class Report:
    trades: list[Trade] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(t.result == "TP" for t in self.trades)

    @property
    def win_rate(self) -> float:
        return 100.0 * self.wins / self.n if self.n else 0.0

    @property
    def total_pips(self) -> float:
        return sum(t.pips for t in self.trades)

    @property
    def profit_factor(self) -> float:
        g = sum(t.pips for t in self.trades if t.pips > 0)
        lo = -sum(t.pips for t in self.trades if t.pips < 0)
        return g / lo if lo else float("inf")

    def max_drawdown_pips(self) -> float:
        eq = np.cumsum([t.pips for t in self.trades]) if self.trades else np.zeros(1)
        return float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())


def run_backtest(df: pd.DataFrame, signals: np.ndarray, sl_pips: float, tp_pips: float,
                 use_spread: bool = True) -> Report:
    o, h, l = (df[k].to_numpy() for k in ("open", "high", "low"))
    spr = df["spread"].to_numpy() if use_spread else np.zeros(len(df))
    idx = df.index
    sl_d, tp_d = sl_pips * PIP, tp_pips * PIP
    rep = Report()
    n = len(df)
    sig_idx = np.flatnonzero(signals)
    k = 0
    while k < len(sig_idx):
        i = sig_idx[k]
        k += 1
        e = i + 1
        if e >= n:
            break
        d = int(signals[i])
        entry = o[e] + (spr[e] if d == 1 else 0.0)
        sl, tp = entry - d * sl_d, entry + d * tp_d
        tr = Trade(idx[e], d, entry, sl, tp)
        j = e
        while j < n:
            # цена, по которой закрывается позиция: BUY — bid, SELL — ask
            hi = h[j] + (spr[j] if d == -1 else 0.0)
            lo = l[j] + (spr[j] if d == -1 else 0.0)
            hit_sl = lo <= sl if d == 1 else hi >= sl
            hit_tp = hi >= tp if d == 1 else lo <= tp
            if hit_sl or hit_tp:
                tr.result = "SL" if hit_sl else "TP"
                tr.exit_time = idx[j]
                # спред уже учтён: BUY входит по ask, SELL выходит по ask
                tr.pips = -sl_pips if hit_sl else tp_pips
                break
            j += 1
        if not tr.result:
            break
        rep.trades.append(tr)
        while k < len(sig_idx) and sig_idx[k] <= j:
            k += 1
    return rep
