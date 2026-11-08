"""Живые котировки XAU/USD: Twelve Data или OANDA. Плюс CSV-реплей для тестов."""
from __future__ import annotations

from abc import ABC, abstractmethod

import aiohttp
import pandas as pd

TF_MINUTES = {"5min": 5, "15min": 15, "1h": 60}


def _frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df.pop("time"), utc=True).dt.tz_convert(None)
    df["spread"] = 0.0
    return df.sort_index().astype(float)


class Provider(ABC):
    @abstractmethod
    async def candles(self, tf: str, count: int) -> pd.DataFrame:
        """Свечи в UTC (последняя может быть незакрытой)."""

    @abstractmethod
    async def price(self) -> float:
        ...

    async def close(self) -> None:
        pass


class _Http(Provider):
    def __init__(self) -> None:
        self._s: aiohttp.ClientSession | None = None

    async def _get(self, url: str, **kw) -> dict:
        if self._s is None:
            self._s = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        async with self._s.get(url, **kw) as r:
            r.raise_for_status()
            return await r.json()

    async def close(self) -> None:
        if self._s:
            await self._s.close()


class TwelveData(_Http):
    """https://twelvedata.com — символ XAU/USD. Для опроса каждые 15 с нужен платный тариф
    (бесплатный — 800 запросов в день)."""
    URL = "https://api.twelvedata.com"

    def __init__(self, api_key: str):
        super().__init__()
        self.key = api_key

    async def candles(self, tf: str, count: int) -> pd.DataFrame:
        j = await self._get(f"{self.URL}/time_series", params={
            "symbol": "XAU/USD", "interval": tf, "outputsize": count,
            "timezone": "UTC", "apikey": self.key})
        if j.get("status") == "error":
            raise RuntimeError(j.get("message"))
        rows = [{"time": v["datetime"], "open": v["open"], "high": v["high"], "low": v["low"],
                 "close": v["close"], "volume": v.get("volume", 0)} for v in j["values"]]
        return _frame(rows)

    async def price(self) -> float:
        j = await self._get(f"{self.URL}/price", params={"symbol": "XAU/USD", "apikey": self.key})
        if "price" not in j:
            raise RuntimeError(j.get("message", "no price"))
        return float(j["price"])


class Oanda(_Http):
    """OANDA v20 (бесплатный демо-счёт подходит), инструмент XAU_USD."""
    GRAN = {"5min": "M5", "15min": "M15", "1h": "H1", "1day": "D"}

    def __init__(self, token: str, live: bool = False):
        super().__init__()
        self.base = "https://api-fxtrade.oanda.com" if live else "https://api-fxpractice.oanda.com"
        self.headers = {"Authorization": f"Bearer {token}"}

    async def _candles(self, gran: str, count: int) -> list[dict]:
        j = await self._get(f"{self.base}/v3/instruments/XAU_USD/candles", headers=self.headers,
                            params={"granularity": gran, "count": count, "price": "M"})
        return j["candles"]

    async def candles(self, tf: str, count: int) -> pd.DataFrame:
        rows = [{"time": c["time"], "open": c["mid"]["o"], "high": c["mid"]["h"], "low": c["mid"]["l"],
                 "close": c["mid"]["c"], "volume": c.get("volume", 0)}
                for c in await self._candles(self.GRAN[tf], count)]
        return _frame(rows)

    async def price(self) -> float:
        c = await self._candles("S5", 1)
        return float(c[-1]["mid"]["c"])


class Replay(Provider):
    """Проигрывает исторические свечи — для тестов и демо без API-ключа."""

    def __init__(self, df: pd.DataFrame, start: int = 500):
        self.df, self.pos = df, start

    def step(self, n: int = 1) -> None:
        self.pos = min(self.pos + n, len(self.df))

    async def candles(self, tf: str, count: int) -> pd.DataFrame:
        from .data import resample
        per = 288 if tf == "1day" else TF_MINUTES[tf] // 5   # свечей M5 в одной свече tf
        part = self.df.iloc[max(0, self.pos - (count + 1) * per): self.pos]
        return resample(part, "1D" if tf == "1day" else tf).iloc[-count:]

    async def price(self) -> float:
        return float(self.df["close"].iloc[self.pos - 1])


def make_provider(cfg) -> Provider:
    if cfg.data_provider == "oanda":
        if not cfg.oanda_token:
            raise RuntimeError("OANDA_TOKEN не задан")
        return Oanda(cfg.oanda_token, cfg.oanda_live)
    if not cfg.twelvedata_key:
        raise RuntimeError("TWELVEDATA_API_KEY не задан")
    return TwelveData(cfg.twelvedata_key)
