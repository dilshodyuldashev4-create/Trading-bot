"""Порт индикатора TR.txt «XAD-style ZigZag» (режим Confirmed, без перерисовки).

* SELL — high закрытого бара стал максимумом последних N баров (после BUY или первая метка);
* BUY  — low стал минимумом последних N баров;
* если цена обновляет экстремум в сторону последней метки, в режиме Confirmed это
  повторный вход (``reentry=True``) — бэктестер возьмёт его, только если позиция закрыта.
Родные уровни индикатора: ENTRY = close, SL = экстремум ± 0.001, TP1 = ENTRY ± 5 $.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def xadz_signals(df: pd.DataFrame, chan_len: int = 190, reentry: bool = False,
                 return_levels: bool = False):
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    hh = df["high"].rolling(chan_len).max().to_numpy()
    ll = df["low"].rolling(chan_len).min().to_numpy()
    sig = np.zeros(len(df), dtype=np.int8)
    ext = np.full(len(df), np.nan)
    p_dir, p_ext = 0, np.nan
    for i in range(len(df)):
        if np.isnan(hh[i]):
            continue
        c_s, c_b = h[i] >= hh[i], l[i] <= ll[i]
        if c_s and c_b:
            order = [1, -1] if p_dir == 1 else [-1, 1]
        elif c_s:
            order = [-1]
        elif c_b:
            order = [1]
        else:
            continue
        for t in order:
            x = h[i] if t == -1 else l[i]
            if p_dir == 0 or t != p_dir:
                p_dir, p_ext = t, x
                sig[i], ext[i] = t, x
            elif (t == -1 and h[i] > p_ext) or (t == 1 and l[i] < p_ext):
                p_ext = x
                if reentry and sig[i] == 0:
                    sig[i], ext[i] = t, x
    return (sig, ext) if return_levels else sig
