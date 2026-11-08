import unittest

import numpy as np
import pandas as pd

from goldbot.backtest import run_backtest
from goldbot.strategies.sessions import asian_range_breakout, silver_bullet
from goldbot.strategies.xadz import xadz_signals


def make_df(prices, start="2025-03-10 00:00", freq="15min", spread=0.0):
    idx = pd.date_range(start, periods=len(prices), freq=freq)
    p = np.asarray(prices, dtype=float)
    return pd.DataFrame({"open": p, "high": p + 0.5, "low": p - 0.5, "close": p,
                         "volume": 1.0, "spread": spread}, index=idx)


class BacktestTests(unittest.TestCase):
    def test_tp_and_sl(self):
        df = make_df([100] * 5 + [100 + i for i in range(1, 40)])
        sig = np.zeros(len(df), dtype=np.int8)
        sig[3] = 1
        r = run_backtest(df, sig, sl_pips=30, tp_pips=60)
        self.assertEqual((r.n, r.wins, r.total_pips), (1, 1, 60))
        sig[3] = -1
        r = run_backtest(df, sig, sl_pips=30, tp_pips=60)
        self.assertEqual((r.n, r.wins, r.total_pips), (1, 0, -30))

    def test_both_hit_counts_as_loss(self):
        df = make_df([100] * 10)
        df.iloc[5, df.columns.get_loc("high")] = 110
        df.iloc[5, df.columns.get_loc("low")] = 90
        sig = np.zeros(len(df), dtype=np.int8)
        sig[2] = 1
        self.assertEqual(run_backtest(df, sig, 30, 60).trades[0].result, "SL")


class StrategyTests(unittest.TestCase):
    def test_xadz_alternates(self):
        p = list(np.linspace(100, 50, 300)) + list(np.linspace(50, 150, 600)) + list(np.linspace(150, 60, 600))
        sig = xadz_signals(make_df(p), chan_len=190)
        flips = sig[sig != 0]
        self.assertTrue(len(flips) >= 2)
        self.assertTrue(all(a != b for a, b in zip(flips, flips[1:])))

    def test_asian_breakout_once_per_day(self):
        # 10.03.2025 Лондон = UTC (до перехода на летнее время)
        p = [100.0] * 28 + [100.0 + i for i in range(1, 30)]  # 00:00–07:00 флэт, потом рост
        sig = asian_range_breakout(make_df(p))
        self.assertEqual(int((sig != 0).sum()), 1)
        self.assertEqual(int(sig[sig != 0][0]), 1)

    def test_silver_bullet_window(self):
        df = make_df([100.0] * 96, start="2025-03-12 00:00")  # NY = UTC-4 после 9 марта
        # бычий FVG на 14:15 UTC = 10:15 NY
        i = df.index.get_loc(pd.Timestamp("2025-03-12 14:15"))
        df.iloc[i, df.columns.get_loc("low")] = 102
        df.iloc[i, df.columns.get_loc("close")] = 103
        sig = silver_bullet(df)
        self.assertEqual(int(sig[i]), 1)
        self.assertEqual(int((sig != 0).sum()), 1)


if __name__ == "__main__":
    unittest.main()


class DailyTrendTests(unittest.TestCase):
    def test_daily_trend_side_uses_closed_days_only(self):
        from goldbot.live_strategy import daily_trend_side
        idx = pd.date_range("2025-01-01", periods=80, freq="1D")
        up = pd.DataFrame({"close": np.linspace(2000, 2800, 80)}, index=idx)
        now = pd.Timestamp("2025-03-21 10:00", tz="UTC")       # 80-й день ещё не закрыт
        self.assertEqual(daily_trend_side(up, now), 1)
        down = up.copy()
        down["close"] = down["close"].to_numpy()[::-1]
        self.assertEqual(daily_trend_side(down, now), -1)
        # резкий провал в текущий (незакрытый) день тренд не меняет
        spike = up.copy()
        spike.iloc[-1, 0] = 100
        self.assertEqual(daily_trend_side(spike, now), 1)

    def test_research_trend_filter(self):
        from goldbot.strategies.research import htf_trend, with_trend
        df = make_df(np.linspace(100, 300, 96 * 70), start="2025-01-01 00:00")
        tr = htf_trend(df, "1D", 50)
        self.assertEqual(int(tr[-1]), 1)
        sig = np.zeros(len(df), dtype=np.int8)
        sig[-10], sig[-5] = 1, -1
        out = with_trend(lambda _: sig)(df)
        self.assertEqual((int(out[-10]), int(out[-5])), (1, 0))
