"""Порт сигнала LONG/SHORT «OB + FVG + BOS» из FVG.txt.

* Свинги — ta.pivothigh/pivotlow(5, 5).
* BOS вверх — close пересёк последний swing high (close[1] <= swing); сигнал на следующем
  баре, как в оригинале (bosBull = bosBullNow[1]).
* FVG — три однонаправленные свечи, разрыв >= ATR(14)/5, «Combine zones», FVG гаснет при
  закрытии сквозь зону; для сигнала нужен активный FVG того же направления не старше 20 баров.
* Order Block в оригинале строится почти на каждом BOS (якорь по POC-свече); здесь эта
  проверка опущена, поэтому сигналов может быть немного больше, чем в TradingView.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators import atr, ema, pivot_high, pivot_low


def fvg_bos_signals(df: pd.DataFrame, swing_len: int = 5, sensitivity: int = 5,
                    window: int = 20, max_stored: int = 20, trend_filter: bool = False):
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    n = len(df)
    ph, pl = pivot_high(h, swing_len), pivot_low(l, swing_len)
    min_gap = (atr(df, 14) / sensitivity).to_numpy()
    trend = ema(df["close"], 200).to_numpy()

    sig = np.zeros(n, dtype=np.int8)
    sh_p = sh_i = sl_p = sl_i = None
    bos_bull_now = bos_bear_now = False
    fvgs: list[list] = []  # [left, top, bottom, is_bull, active]

    for i in range(n):
        if not np.isnan(ph[i]):
            sh_p, sh_i = ph[i], i - swing_len
        if not np.isnan(pl[i]):
            sl_p, sl_i = pl[i], i - swing_len

        prev_bull, prev_bear = bos_bull_now, bos_bear_now
        bos_bear_now = sl_p is not None and i > sl_i and c[i] < sl_p and c[i - 1] >= sl_p
        bos_bull_now = sh_p is not None and i > sh_i and c[i] > sh_p and c[i - 1] <= sh_p

        # FVG
        if i >= 2:
            if (l[i] > h[i - 2] and l[i] - h[i - 2] >= min_gap[i]
                    and c[i] > o[i] and c[i - 1] > o[i - 1] and c[i - 2] > o[i - 2]):
                if not any(f[4] and f[3] and l[i] >= f[2] and h[i - 2] <= f[1] for f in fvgs):
                    fvgs.insert(0, [i - 2, l[i], h[i - 2], True, True])
            if (h[i] < l[i - 2] and l[i - 2] - h[i] >= min_gap[i]
                    and c[i] < o[i] and c[i - 1] < o[i - 1] and c[i - 2] < o[i - 2]):
                if not any(f[4] and not f[3] and l[i - 2] >= f[2] and h[i] <= f[1] for f in fvgs):
                    fvgs.insert(0, [i - 2, l[i - 2], h[i], False, True])
        for f in fvgs:
            if f[4] and ((f[3] and c[i] <= f[2]) or (not f[3] and c[i] >= f[1])):
                f[4] = False
        del fvgs[max_stored:]

        def recent(bull: bool) -> bool:
            return any(f[4] and f[3] == bull and i - f[0] <= window for f in fvgs)

        if prev_bull:
            if recent(True) and (not trend_filter or c[i] > trend[i]):
                sig[i] = 1
            sh_p = sh_i = None
        if prev_bear:
            if recent(False) and (not trend_filter or c[i] < trend[i]):
                sig[i] = -1
            sl_p = sl_i = None
    return sig
