"""Загрузка свечей XAUUSD."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "data" / "XAUUSD_M5.csv"

# 1 пип золота = 0.10 $ (стандарт большинства брокеров: 30 пипсов = 3 $)
PIP = 0.10


def load_mt5_csv(path: str | Path = DEFAULT_CSV) -> pd.DataFrame:
    """Читает экспорт MetaTrader 5 (<DATE> <TIME> <OPEN> ...), время брокера."""
    df = pd.read_csv(path, sep="\t")
    df.columns = [c.strip("<>").lower() for c in df.columns]
    df.index = pd.to_datetime(df["date"] + " " + df["time"], format="%Y.%m.%d %H:%M:%S")
    df = df.rename(columns={"tickvol": "volume"})
    # спред в пунктах (0.001 $) -> в долларах
    df["spread"] = df["spread"] * 0.001
    return df[["open", "high", "low", "close", "volume", "spread"]].astype(float)


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """M5 -> M15 / H1 и т.д."""
    if rule in ("5min", "5m", "M5"):
        return df
    agg = {"open": "first", "high": "max", "low": "min", "close": "last",
           "volume": "sum", "spread": "mean"}
    return df.resample(rule, label="left", closed="left").agg(agg).dropna()
