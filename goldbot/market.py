"""Живые котировки XAU/USD: Twelve Data или OANDA. Плюс CSV-реплей для тестов."""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod

import aiohttp
import pandas as pd

TF_MINUTES = {"5min": 5, "15min": 15, "30min": 30, "1h": 60, "4h": 240}

log = logging.getLogger(__name__)


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
    GRAN = {"5min": "M5", "15min": "M15", "30min": "M30", "1h": "H1", "4h": "H4", "1day": "D"}

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


class FinnhubPrice(_Http):
    """https://finnhub.io — только текущая цена (бесплатно ~60 запросов в минуту), свечи берём у другого источника.
    Символ по умолчанию OANDA:XAU_USD."""
    URL = "https://finnhub.io/api/v1/quote"

    def __init__(self, api_key: str, symbol: str = "OANDA:XAU_USD"):
        super().__init__()
        self.key, self.symbol = api_key, symbol

    async def candles(self, tf: str, count: int) -> pd.DataFrame:
        raise NotImplementedError("Finnhub используется только для цены")

    async def price(self) -> float:
        j = await self._get(self.URL, params={"symbol": self.symbol, "token": self.key})
        p = float(j.get("c") or 0)
        if p <= 0:
            raise RuntimeError(f"Finnhub: нет цены для {self.symbol}: {j}")
        return p


class GoldApiPrice(_Http):
    """https://gold-api.com — бесплатная цена XAU/USD без ключа (проверено с сервера бота)."""
    URL = "https://api.gold-api.com/price/XAU"

    async def candles(self, tf: str, count: int) -> pd.DataFrame:
        raise NotImplementedError("gold-api.com используется только для цены")

    async def price(self) -> float:
        j = await self._get(self.URL)
        p = float(j.get("price") or 0)
        if p <= 0:
            raise RuntimeError(f"gold-api.com: нет цены: {j}")
        return p


class Hybrid(Provider):
    """Свечи от одного источника (например, бесплатный Twelve Data: запрос только при закрытии свечи),
    цена каждые CHECK_INTERVAL секунд от другого (например, Finnhub)."""

    def __init__(self, candles_from: Provider, price_from: Provider):
        self.c, self.p = candles_from, price_from

    async def candles(self, tf: str, count: int) -> pd.DataFrame:
        return await self.c.candles(tf, count)

    async def price(self) -> float:
        return await self.p.price()

    async def close(self) -> None:
        await self.c.close()
        await self.p.close()


class Failover(Provider):
    """Основной источник (цены брокера через MetaApi) с переключением на запасной.

    Свечи: если основной не ответил за candle_timeout секунд или ответил ошибкой, этот же запрос сразу идёт
    в запасной, и следующие cooldown секунд свечи берутся только из запасного, без ожидания.

    Цена: запасной источник (спот-котировка) стабильно отличается от графика брокера на несколько долларов,
    поэтому из-за одного медленного ответа MetaApi на него не уходим:
    - ждём ответа брокера до price_timeout секунд;
    - если брокер не ответил, но его цена моложе hold секунд — отдаём её и через price_cooldown секунд
      снова спрашиваем брокера;
    - только если брокер молчит дольше hold — берём запасной, но с поправкой на разницу между источниками
      (раз в offset_every секунд, пока брокер отвечает, бот сверяет обе цены и запоминает разницу).
    Цена и свечи переключаются отдельно: сбой при загрузке свечей не уводит цену с графика брокера.

    Если брокер не отдаёт цену дольше heal_after секунд, а у основного источника есть heal() (BrokerMarket),
    в фоне вызывается heal(): он включает или перезапускает счёт в MetaApi. Не чаще раза в heal_every секунд."""

    def __init__(self, primary: Provider, backup: Provider, price_timeout: float = 8,
                 candle_timeout: float = 15, cooldown: float = 60, price_cooldown: float | None = None,
                 hold: float = 60, offset_every: float = 300, offset_ttl: float = 6 * 3600,
                 heal_after: float = 900, heal_every: float = 1800):
        self.primary, self.backup = primary, backup
        self.price_timeout, self.candle_timeout, self.cooldown = price_timeout, candle_timeout, cooldown
        self.price_cooldown = cooldown if price_cooldown is None else price_cooldown
        self.hold, self.offset_every, self.offset_ttl = hold, offset_every, offset_ttl
        self._skip_until: dict[str, float] = {}
        self.backup_for: set[str] = set()   # что сейчас берётся из запасного: "price", "candles"
        self.last_error = ""                # последняя ошибка основного источника (для /feed)
        self.last_error_at = 0.0
        self.last_ok_at = 0.0               # когда основной последний раз ответил на запрос цены
        self._broker: tuple[float, float] | None = None   # (последняя цена брокера, time.monotonic())
        self.offset: float | None = None    # цена брокера минус цена запасного источника
        self.offset_at = 0.0                # time.time() последней сверки
        self._offset_mono = -1e18
        self.heal_after, self.heal_every = heal_after, heal_every
        self._down_since: float | None = None   # time.monotonic() первого сбоя цены после последнего ответа
        self._heal_mono = -1e18
        self._heal_task: asyncio.Task | None = None
        self.manual_offset: float | None = None   # поправка, заданная админом по цене из MT5 (/offset), без срока
        self.heal_note = ""                 # итог последнего heal() (для /feed)
        self.heal_at = 0.0

    @property
    def on_backup(self) -> bool:
        return "price" in self.backup_for

    def _fail(self, name: str, e: Exception, cooldown: float, timeout: float | None = None) -> None:
        self._skip_until[name] = time.monotonic() + cooldown
        text = str(e) or (f"нет ответа за {timeout:g} с" if timeout and isinstance(e, asyncio.TimeoutError) else "")
        self.last_error, self.last_error_at = f"{name}: {type(e).__name__}: {text}"[:300], time.time()

    def _maybe_heal(self) -> None:
        """Брокер молчит долго — в фоне просим основной источник починить подключение (heal)."""
        heal = getattr(self.primary, "heal", None)
        now = time.monotonic()
        if (heal is None or self._down_since is None or now - self._down_since < self.heal_after
                or now - self._heal_mono < self.heal_every or (self._heal_task and not self._heal_task.done())):
            return
        self._heal_mono = now

        async def run() -> None:
            try:
                note = await heal()
            except Exception as e:  # noqa: BLE001
                note = f"не удалось: {type(e).__name__}: {e}"
            self.heal_note, self.heal_at = str(note)[:300], time.time()
            log.warning("market data: heal broker connection: %s", self.heal_note)
        self._heal_task = asyncio.get_running_loop().create_task(run())

    @property
    def offset_fresh(self) -> bool:
        """Поправка измерена недавно и применяется к запасной цене."""
        return self.offset is not None and time.time() - self.offset_at < self.offset_ttl

    async def _call(self, name: str, timeout: float, *args):
        if time.monotonic() >= self._skip_until.get(name, 0):
            try:
                res = await asyncio.wait_for(getattr(self.primary, name)(*args), timeout)
                if name in self.backup_for:
                    log.warning("market data: broker %s is back", name)
                    self.backup_for.discard(name)
                return res
            except Exception as e:  # noqa: BLE001 — любая ошибка: сразу запасной источник
                self._fail(name, e, self.cooldown, timeout)
                if name not in self.backup_for:
                    log.warning("market data: broker %s failed (%s: %s), switching to backup",
                                name, type(e).__name__, e)
                self.backup_for.add(name)
        res = await getattr(self.backup, name)(*args)
        off = self.current_offset()
        if name == "candles" and off and isinstance(res, pd.DataFrame):
            # свечи запасного источника сдвигаем к графику брокера, чтобы уровни совпадали с MT5
            res = res.copy()
            for c in ("open", "high", "low", "close"):
                if c in res:
                    res[c] = res[c] + off
        return res

    async def candles(self, tf: str, count: int) -> pd.DataFrame:
        return await self._call("candles", self.candle_timeout, tf, count)

    async def _measure_offset(self, broker: float) -> None:
        """Сверка с запасным источником, пока брокер отвечает: на сколько запасной выше или ниже."""
        if self.offset_every <= 0 or time.monotonic() - self._offset_mono < self.offset_every:
            return
        self._offset_mono = time.monotonic()
        try:
            b = await asyncio.wait_for(self.backup.price(), 3)
        except Exception as e:  # noqa: BLE001 — сверка не обязательна
            log.info("market data: backup price for offset failed: %s: %s", type(e).__name__, e)
            return
        self.offset, self.offset_at = broker - b, time.time()

    def current_offset(self) -> float | None:
        """Поправка к запасному источнику: свежая сверка с брокером, иначе заданная админом (/offset)."""
        if self.offset_fresh:
            return self.offset
        return self.manual_offset

    def backup_adjusted(self, p: float) -> float:
        """Цена запасного источника, приведённая к графику брокера."""
        off = self.current_offset()
        return p + off if off is not None else p

    async def price(self) -> float:
        if time.monotonic() >= self._skip_until.get("price", 0):
            try:
                p = await asyncio.wait_for(self.primary.price(), self.price_timeout)
                self.last_ok_at = time.time()
                self._broker = (p, time.monotonic())
                self._down_since = None
                if "price" in self.backup_for:
                    log.warning("market data: broker price is back")
                    self.backup_for.discard("price")
                await self._measure_offset(p)
                return p
            except Exception as e:  # noqa: BLE001
                self._fail("price", e, self.price_cooldown, self.price_timeout)
                if self._down_since is None:
                    self._down_since = time.monotonic()
                self._maybe_heal()
                log.info("market data: broker price failed (%s: %s)", type(e).__name__, e)
        if self._broker and time.monotonic() - self._broker[1] < self.hold:
            return self._broker[0]   # брокер ответил недавно — его цена точнее запасного источника
        if "price" not in self.backup_for:
            log.warning("market data: no broker price for %ss, switching to backup (offset %s)",
                        self.hold, self.offset)
            self.backup_for.add("price")
        return self.backup_adjusted(await self.backup.price())

    async def close(self) -> None:
        await self.primary.close()
        await self.backup.close()


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
        base: Provider = Oanda(cfg.oanda_token, cfg.oanda_live)
    else:
        if not cfg.twelvedata_key:
            raise RuntimeError("TWELVEDATA_API_KEY не задан")
        base = TwelveData(cfg.twelvedata_key)
    if cfg.price_provider == "goldapi":
        return Hybrid(base, GoldApiPrice())
    if cfg.price_provider == "finnhub":
        if not cfg.finnhub_key:
            raise RuntimeError("FINNHUB_API_KEY не задан")
        return Hybrid(base, FinnhubPrice(cfg.finnhub_key, cfg.finnhub_symbol))
    return base
