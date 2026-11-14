"""Автоторговля на счетах подписчиков MT4/MT5 через MetaApi (metaapi.cloud).

Подписчик присылает боту номер счёта, пароль и сервер брокера. Бот один раз передаёт их в MetaApi
(облако с терминалами MetaTrader), а у себя хранит только id счёта в MetaApi, номер счёта и сервер —
пароль в базу бота не попадает. Дальше по каждому сигналу бот открывает сделку на счёте подписчика
по рынку и сразу ставит у брокера Stop Loss и Take Profit (от цены брокера, а не от котировок бота:
они отличаются на несколько долларов). Когда сигнал закрывается в боте (TP/SL, новость, вручную,
«Отклонить»), бот закрывает то, что ещё открыто на счёте.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import secrets
from dataclasses import dataclass
from typing import Any

import aiohttp

from . import prop as pr
from .data import PIP
from .market import Provider, _frame

log = logging.getLogger(__name__)

PROVISIONING = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"
CLIENT = "https://mt-client-api-v1.{region}.agiliumtrade.ai"
MARKET = "https://mt-market-data-client-api-v1.{region}.agiliumtrade.ai"
MT_TF = {"5min": "5m", "15min": "15m", "30min": "30m", "1h": "1h", "4h": "4h", "1day": "1d"}
OK_CODES = {"TRADE_RETCODE_DONE", "TRADE_RETCODE_DONE_PARTIAL", "TRADE_RETCODE_PLACED",
            "TRADE_RETCODE_NO_CHANGES", "ERR_NO_ERROR"}
CENT_CURRENCIES = {"USC", "USX", "USc", "UScent"}

# брокеры кнопками (название на кнопке, что искать в списке серверов MetaApi); любой другой — «Другой брокер»
BROKERS: tuple[tuple[str, str], ...] = (
    ("Exness", "Exness"), ("XM", "XMGlobal"), ("RoboForex", "RoboForex"), ("Alpari", "Alpari"),
    ("FBS", "FBS"), ("IC Markets", "ICMarkets"), ("Pepperstone", "Pepperstone"), ("Tickmill", "Tickmill"),
    ("FxPro", "FxPro"), ("Octa", "Octa"), ("JustMarkets", "JustMarkets"), ("InstaForex", "InstaForex"),
    ("HFM", "HFMarkets"), ("FreshForex", "FreshForex"), ("AMarkets", "AMarkets"), ("Grand Capital", "GrandCapital"),
    ("FXTM", "ForexTime"), ("Admirals", "Admirals"), ("Vantage", "Vantage"), ("FXOpen", "FXOpen"),
)

GOLD = re.compile(r"^(XAUUSD|GOLD)", re.I)


class MetaApiError(Exception):
    def __init__(self, message: str, code: str = "", status: int = 0):
        super().__init__(message)
        self.code, self.status = code, status


def _error(status: int, body: Any) -> MetaApiError:
    if isinstance(body, dict):
        details = body.get("details")
        code = details.get("code", "") if isinstance(details, dict) else (details if isinstance(details, str) else "")
        msg = body.get("message") or body.get("error") or str(body)
        if isinstance(details, list):  # ValidationError: какие поля не прошли проверку
            parts = [f"{d.get('parameter', '')}: {d.get('message', '')}".strip(": ") for d in details
                     if isinstance(d, dict) and (d.get("parameter") or d.get("message"))]
            if parts:
                msg = f"{msg} ({'; '.join(parts)})"[:300]
        if not code:
            m = re.search(r"\bE_[A-Z_]+\b", str(body))
            code = m.group(0) if m else ""
        return MetaApiError(msg, code, status)
    m = re.search(r"\bE_[A-Z_]+\b", str(body))
    return MetaApiError(str(body)[:300], m.group(0) if m else "", status)


class MetaApi:
    """Тонкий клиент REST API MetaApi (без тяжёлого SDK)."""

    def __init__(self, token: str):
        self.token = token
        self._session: aiohttp.ClientSession | None = None

    async def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90))
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def request(self, method: str, url: str, json: Any = None,
                      headers: dict | None = None, timeout: float = 90) -> tuple[int, Any, dict]:
        """Запрос к MetaApi. Таймаут и обрыв связи — MetaApiError с кодом TIMEOUT / NETWORK."""
        h = {"auth-token": self.token, "Accept": "application/json", **(headers or {})}
        s = await self._http()
        try:
            async with s.request(method, url, json=json, headers=h,
                                 timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                try:
                    body = await r.json(content_type=None)
                except Exception:  # noqa: BLE001
                    body = await r.text()
                return r.status, body, dict(r.headers)
        except asyncio.TimeoutError as e:
            raise MetaApiError(f"MetaApi did not answer in {timeout:.0f}s", "TIMEOUT") from e
        except aiohttp.ClientError as e:
            raise MetaApiError(f"{type(e).__name__}: {e}", "NETWORK") from e

    async def _ok(self, method: str, url: str, json: Any = None, timeout: float = 90) -> Any:
        status, body, _ = await self.request(method, url, json, timeout=timeout)
        if status >= 400:
            raise _error(status, body)
        return body

    # ── provisioning ────────────────────────────────────────────────────────
    async def search_servers(self, version: int, query: str) -> dict[str, list[str]]:
        from urllib.parse import quote
        body = await self._ok("GET", f"{PROVISIONING}/known-mt-servers/{version}/search?query={quote(query)}")
        return body if isinstance(body, dict) else {}

    async def create_account(self, *, name: str, login: str, password: str, server: str, platform: str,
                             magic: int, region: str = "", max_wait: float = 300) -> dict:
        """Создаёт счёт в MetaApi. 202 — MetaApi ещё определяет настройки брокера: ждём и повторяем
        с тем же transaction-id."""
        body = {"name": name, "login": login, "password": password, "server": server, "platform": platform,
                "magic": magic, "type": "cloud-g2", "reliability": "regular"}
        if region:
            body["region"] = region
        tid = secrets.token_hex(16)
        loop = asyncio.get_running_loop()
        start = loop.time()
        while True:
            try:  # MetaApi может долго проверять логин у брокера — ждём долго
                status, resp, headers = await self.request("POST", f"{PROVISIONING}/users/current/accounts", body,
                                                           {"transaction-id": tid}, timeout=180)
            except MetaApiError as e:
                # ответ не дошёл: повторяем с тем же transaction-id, MetaApi вернёт уже созданный счёт, а не второй
                if e.code in ("TIMEOUT", "NETWORK") and loop.time() - start < max_wait:
                    log.info("create account: %s, retrying", e)
                    await asyncio.sleep(5)
                    continue
                raise
            waited = loop.time() - start
            if status in (200, 201):
                return resp
            if status == 202 and waited < max_wait:
                delay = min(max(float(headers.get("Retry-After", 10) or 10), 3), 60)
                await asyncio.sleep(delay)
                continue
            raise _error(status, resp)

    async def list_accounts(self, query: str) -> list[dict]:
        from urllib.parse import quote
        body = await self._ok("GET", f"{PROVISIONING}/users/current/accounts?query={quote(query)}&limit=100")
        if isinstance(body, dict):  # в новых версиях API список лежит в items
            body = body.get("items", [])
        return body or []

    async def get_account(self, account_id: str) -> dict:
        return await self._ok("GET", f"{PROVISIONING}/users/current/accounts/{account_id}")

    async def deploy(self, account_id: str) -> None:
        await self._ok("POST", f"{PROVISIONING}/users/current/accounts/{account_id}/deploy")

    async def undeploy(self, account_id: str) -> None:
        await self._ok("POST", f"{PROVISIONING}/users/current/accounts/{account_id}/undeploy")

    async def remove(self, account_id: str) -> None:
        await self._ok("DELETE", f"{PROVISIONING}/users/current/accounts/{account_id}")

    # ── терминал ────────────────────────────────────────────────────────────
    def _client(self, account_id: str, region: str) -> str:
        return f"{CLIENT.format(region=region or 'new-york')}/users/current/accounts/{account_id}"

    async def account_info(self, account_id: str, region: str, timeout: float = 90) -> dict:
        return await self._ok("GET", f"{self._client(account_id, region)}/account-information", timeout=timeout)

    async def symbols(self, account_id: str, region: str) -> list[str]:
        body = await self._ok("GET", f"{self._client(account_id, region)}/symbols")
        return [x if isinstance(x, str) else x.get("symbol", "") for x in body or []]

    async def specification(self, account_id: str, region: str, symbol: str) -> dict:
        return await self._ok("GET", f"{self._client(account_id, region)}/symbols/{symbol}/specification")

    async def price(self, account_id: str, region: str, symbol: str) -> dict:
        return await self._ok("GET", f"{self._client(account_id, region)}/symbols/{symbol}/current-price")

    async def positions(self, account_id: str, region: str) -> list[dict]:
        return await self._ok("GET", f"{self._client(account_id, region)}/positions") or []

    async def deals_by_position(self, account_id: str, region: str, position_id: str) -> list[dict]:
        body = await self._ok("GET", f"{self._client(account_id, region)}/history-deals/position/{position_id}")
        return body.get("deals", []) if isinstance(body, dict) else (body or [])

    async def trade(self, account_id: str, region: str, req: dict) -> dict:
        resp = await self._ok("POST", f"{self._client(account_id, region)}/trade", req)
        if not isinstance(resp, dict) or resp.get("stringCode") not in OK_CODES:
            code = resp.get("stringCode", "") if isinstance(resp, dict) else ""
            msg = resp.get("message", str(resp)) if isinstance(resp, dict) else str(resp)
            raise MetaApiError(msg, code)
        return resp


# ── расчёты ──────────────────────────────────────────────────────────────────
def pick_symbol(symbols: list[str], override: str = "") -> str | None:
    """Символ золота у брокера: XAUUSD, XAUUSDm, XAUUSD.r, GOLD …"""
    if override and override in symbols:
        return override
    gold = [s for s in symbols if GOLD.match(s or "")]
    if not gold:
        return None
    # сначала ровно XAUUSD, потом самое короткое (XAUUSDm лучше XAUUSD.ecn.pro)
    gold.sort(key=lambda s: (s.upper() != "XAUUSD", not s.upper().startswith("XAUUSD"), len(s)))
    return gold[0]


def demo_servers(servers: dict[str, list[str]], demo_only: bool) -> list[str]:
    """Плоский список серверов; при demo_only — сначала (или только) демо-серверы."""
    flat: list[str] = []
    for lst in servers.values():
        for s in lst:
            if s not in flat:
                flat.append(s)
    is_demo = lambda s: bool(re.search(r"demo|trial|contest", s, re.I))  # noqa: E731
    if demo_only:
        demo = [s for s in flat if is_demo(s)]
        return demo or flat
    return sorted(flat, key=is_demo)


def calc_volume(equity: float, currency: str, sl_dist: float, risk_pct: float, max_lot: float,
                spec: dict | None = None) -> float:
    """Лот: стоп забирает не больше risk_pct % средств, с шагом и пределами брокера и не больше max_lot."""
    spec = spec or {}
    contract = float(spec.get("contractSize") or 100)
    step = float(spec.get("volumeStep") or 0.01)
    vmin = float(spec.get("minVolume") or 0.01)
    vmax = float(spec.get("maxVolume") or 100)
    usd = equity / 100 if currency in CENT_CURRENCIES else equity
    if usd <= 0 or sl_dist <= 0:
        return 0.0
    raw = usd * risk_pct / 100 / (contract * sl_dist)
    vol = math.floor(raw / step + 1e-9) * step
    vol = max(vmin, min(vol, vmax, max_lot))
    return round(vol, 2)


def _retryable(e: MetaApiError) -> bool:
    """Временные сбои: нет связи, MetaApi перегружен, терминал не развёрнут/не синхронизирован."""
    if e.code in ("TIMEOUT", "NETWORK"):
        return True
    if e.status == 429 or e.status >= 500 or e.status == 404:
        return True
    text = str(e).lower()
    return any(w in text for w in ("undeployed", "not connected", "not synchronized", "notfound", "timed out"))


def round_price(x: float, digits: int | None) -> float:
    return round(x, digits if digits is not None else 2)


@dataclass
class OpenResult:
    uid: int
    ok: bool
    volume: float = 0
    price: float = 0
    sl: float = 0
    tp: float = 0
    symbol: str = ""
    error: str = ""


@dataclass
class CloseResult:
    uid: int
    ok: bool
    profit: float | None = None
    currency: str = ""
    already: bool = False   # брокер уже закрыл сам (по своему SL/TP)
    error: str = ""


@dataclass
class AutoTrader:
    db: Any
    api: MetaApi
    demo_only: bool = True
    risk_pct: float = 2.0
    max_lot: float = 1.0
    symbol_override: str = ""
    region: str = ""
    magic: int = 7501
    connect_timeout: float = 240
    poll: float = 5
    concurrency: int = 10
    retry_delays: tuple[float, ...] = (5.0, 20.0)
    exempt: frozenset = frozenset()   # админы: автоторговля без оплаты
    # проп-счета FundedNext
    prop_risk_pct: float = 0.5        # риск на сделку, % от размера счёта (больше 2.8 % не бывает)
    prop_strong_risk_pct: float = 1.0  # риск на сильный сигнал (сильный фон новостей в ту же сторону)
    prop_guard_pct: float = 0.5       # подушка до лимитов FundedNext, % от размера счёта
    prop_max_lot: float = 5.0
    prop_risk_cap: float = 3.0        # за день все сделки вместе — не больше 3 % счёта
    prop_max_trade: float = 2.8       # потолок риска одной сделки, % счёта
    prop_day_tz: str = "Europe/Athens"  # полночь сервера FundedNext
    prop_close: str = "all"           # что закрывать у лимита: all — всё на счёте, bot — только свои, none — ничего

    # ── подключение ────────────────────────────────────────────────────────
    async def connect(self, uid: int, platform: str, server: str, login: str, password: str,
                      prop: dict | None = None) -> dict:
        """Подключает счёт подписчика. Возвращает данные счёта; при ошибке — MetaApiError с кодом:
        E_AUTH (неверный логин/пароль/сервер), E_SRV_NOT_FOUND, REAL_NOT_ALLOWED, NO_GOLD, TIMEOUT …
        prop — {"plan", "stage", "size"} для проп-счёта FundedNext (там свои лимиты просадки)."""
        old = await self.db.get_trade_account(uid)
        if old:  # повторное подключение — старый счёт убираем из MetaApi
            await self.disconnect(uid)
        await self._remove_orphans(uid)
        acc = await self.api.create_account(name=f"tg{uid}-{login}", login=login, password=password,
                                            server=server, platform=platform, magic=self.magic, region=self.region)
        acc_id = acc.get("id") or acc.get("_id")
        try:
            if acc.get("state") != "DEPLOYED":
                await self.api.deploy(acc_id)
            info = await self._wait_connected(acc_id)
            region = info.pop("_region")
            # проп-счёт — деньги фирмы, а не подписчика: его подключаем и при AUTOTRADE_DEMO_ONLY
            if self.demo_only and not prop and info.get("type") not in ("ACCOUNT_TRADE_MODE_DEMO", "ACCOUNT_TRADE_MODE_CONTEST"):
                raise MetaApiError("real account", "REAL_NOT_ALLOWED")
            symbol = pick_symbol(await self.api.symbols(acc_id, region), self.symbol_override)
            if not symbol:
                raise MetaApiError("no gold symbol", "NO_GOLD")
        except Exception:
            await self._remove_quietly(acc_id)
            raise
        await self.db.save_trade_account(uid, acc_id, region, platform, server, login, symbol,
                                         info.get("broker") or "", info.get("currency") or "USD",
                                         info.get("type") == "ACCOUNT_TRADE_MODE_DEMO")
        if prop:
            bal = float(info.get("balance") or prop["size"])
            eq = float(info.get("equity") or bal)
            await self.db.set_prop(uid, prop["plan"], prop["stage"], float(prop["size"]),
                                   pr.day_key(_now(), self.prop_day_tz), bal, max(float(prop["size"]), eq))
        return {**info, "symbol": symbol, "server": server, "login": login}

    async def _remove_orphans(self, uid: int) -> None:
        """Счета этого подписчика в MetaApi, которых нет в базе бота (прошлая попытка оборвалась), — удаляем,
        чтобы не платить за них и не держать там пароль."""
        prefix = f"tg{uid}-"
        try:
            accounts = await self.api.list_accounts(prefix)
        except Exception as e:  # noqa: BLE001
            log.info("list accounts for %s: %s", uid, e)
            return
        for a in accounts:
            if str(a.get("name", "")).startswith(prefix):
                log.info("removing leftover MetaApi account %s of user %s", a.get("_id") or a.get("id"), uid)
                await self._remove_quietly(a.get("_id") or a.get("id"))

    async def _wait_connected(self, acc_id: str) -> dict:
        waited = 0.0
        last = ""
        while waited <= self.connect_timeout:
            try:
                a = await self.api.get_account(acc_id)
            except MetaApiError as e:  # MetaApi ответил с ошибкой или не ответил — пробуем ещё
                log.info("get account %s: %s", acc_id, e)
                a = {}
            last = a.get("connectionStatus", last)
            if a.get("state") == "DEPLOYED" and last == "CONNECTED":
                region = a.get("region") or self.region or "new-york"
                try:
                    info = await self.api.account_info(acc_id, region, timeout=30)
                    return {**info, "_region": region}
                except MetaApiError as e:  # терминал ещё синхронизируется
                    log.info("account info not ready for %s: %s", acc_id, e)
            await asyncio.sleep(self.poll)
            waited += self.poll
        if last == "DISCONNECTED_FROM_BROKER":
            raise MetaApiError("cannot connect to broker", "E_AUTH")
        raise MetaApiError("connection timeout", "TIMEOUT")

    async def _remove_quietly(self, acc_id: str) -> None:
        for call in (self.api.undeploy, self.api.remove):
            try:
                await call(acc_id)
            except Exception as e:  # noqa: BLE001
                log.info("cleanup %s %s: %s", call.__name__, acc_id, e)

    async def disconnect(self, uid: int) -> bool:
        acc = await self.db.get_trade_account(uid)
        if not acc:
            return False
        await self._remove_quietly(acc["meta_id"])  # пароль удаляется из MetaApi вместе со счётом
        await self.db.delete_trade_account(uid)
        return True

    async def status(self, uid: int) -> dict | None:
        acc = await self.db.get_trade_account(uid)
        if not acc:
            return None
        try:
            info = await self.api.account_info(acc["meta_id"], acc["region"])
            acc = {**acc, "balance": info.get("balance"), "equity": info.get("equity"),
                   "currency": info.get("currency") or acc.get("currency")}
        except Exception as e:  # noqa: BLE001
            acc = {**acc, "info_error": str(e)}
        return acc

    # ── сделки ─────────────────────────────────────────────────────────────
    async def open_signal(self, sid: int, direction: int, sl_dist: float, tp_dist: float,
                          uids: set[int] | None = None, strong: bool = False) -> list[OpenResult]:
        """Открывает сделку по сигналу на всех включённых счетах (uids — только у этих подписчиков).
        strong — сильный сигнал: на проп-счетах риск prop_strong_risk_pct вместо prop_risk_pct."""
        if await self.db.get_kv("autotrade_off") == "1":
            return []
        accounts = [a for a in await self.db.trade_accounts(enabled_only=True, exempt=self.exempt)
                    if (uids is None or a["user_id"] in uids)
                    and not (a.get("prop_plan") and a.get("prop_halt"))]  # проп-счёт у лимита — не торгуем
        sem = asyncio.Semaphore(self.concurrency)

        async def one(acc: dict) -> OpenResult:
            async with sem:
                try:
                    return await self._open_retry(acc, sid, direction, sl_dist, tp_dist, strong=strong)
                except Exception as e:  # noqa: BLE001
                    log.warning("autotrade open #%s for %s failed: %s", sid, acc["user_id"], e)
                    err = getattr(e, "code", "") or str(e)[:200]
                    if err != "DUPLICATE":  # уже открытую сделку не затираем
                        await self.db.save_auto_trade(sid, acc["user_id"], None, 0, "error", err)
                    return OpenResult(acc["user_id"], False, error=err)

        return list(await asyncio.gather(*(one(a) for a in accounts)))

    async def _open_retry(self, acc: dict, sid: int, direction: int, sl_dist: float,
                          tp_dist: float, min_lot: bool = False, strong: bool = False) -> OpenResult:
        """Сбой связи с MetaApi или терминал не в сети — проверяем, что счёт развёрнут, и пробуем ещё."""
        for attempt in range(len(self.retry_delays) + 1):
            try:
                if attempt:  # прошлый ордер мог дойти до брокера, хоть ответ и потерялся — не открываем второй
                    found = await self._find_open(acc, sid)
                    if found:
                        return found
                return await self._open_one(acc, sid, direction, sl_dist, tp_dist, min_lot, strong)
            except MetaApiError as e:
                if not _retryable(e) or attempt == len(self.retry_delays):
                    raise
                log.info("autotrade open #%s for %s: %s, retrying", sid, acc["user_id"], e)
                await self._ensure_deployed(acc["meta_id"])
                await asyncio.sleep(self.retry_delays[attempt])
        raise AssertionError("unreachable")

    async def test_trade(self, uid: int, hold: float = 5) -> tuple[OpenResult, CloseResult | None]:
        """Проверка для админа: та же заявка, что по сигналу, но минимальным лотом; через hold секунд закрываем."""
        acc = await self.db.get_trade_account(uid)
        if not acc:
            return OpenResult(uid, False, error="NO_ACCOUNT"), None
        sid = -int(asyncio.get_running_loop().time())  # отрицательный id — не путается с сигналами
        try:
            res = await self._open_retry({**acc}, sid, 1, 10.0, 10.0, min_lot=True)
        except MetaApiError as e:
            return OpenResult(uid, False, error=f"{e.code} {e}".strip()), None
        await asyncio.sleep(hold)
        tr = await self.db.get_auto_trade(sid, uid)
        try:
            closed = await self._close_one(tr) if tr else None
        except MetaApiError as e:
            closed = CloseResult(uid, False, error=f"{e.code} {e}".strip())
        return res, closed

    async def _find_open(self, acc: dict, sid: int) -> OpenResult | None:
        for p in await self.api.positions(acc["meta_id"], acc["region"]):
            if p.get("comment") == f"goldbot #{sid}":
                vol = float(p.get("volume") or 0)
                await self.db.save_auto_trade(sid, acc["user_id"], str(p.get("id")), vol, "open", "")
                return OpenResult(acc["user_id"], True, vol, float(p.get("openPrice") or 0),
                                  float(p.get("stopLoss") or 0), float(p.get("takeProfit") or 0), acc["symbol"])
        return None

    async def _ensure_deployed(self, acc_id: str) -> None:
        try:
            a = await self.api.get_account(acc_id)
        except MetaApiError as e:
            log.info("get account %s: %s", acc_id, e)
            return
        if a.get("state") in ("UNDEPLOYED", "UNDEPLOYING"):
            log.warning("account %s was %s, deploying again", acc_id, a.get("state"))
            try:
                await self.api.deploy(acc_id)
            except MetaApiError as e:
                log.warning("deploy %s: %s", acc_id, e)

    async def _open_one(self, acc: dict, sid: int, direction: int, sl_dist: float, tp_dist: float,
                        min_lot: bool = False, strong: bool = False) -> OpenResult:
        if await self.db.get_auto_trade(sid, acc["user_id"]):
            raise MetaApiError("already opened", "DUPLICATE")
        mid, region, symbol = acc["meta_id"], acc["region"], acc["symbol"]
        info = await self.api.account_info(mid, region)
        try:
            spec = await self.api.specification(mid, region, symbol)
        except Exception:  # noqa: BLE001
            spec = {}
        if acc.get("prop_plan") and not min_lot:
            vol = await self._prop_volume(acc, info, spec, sl_dist, strong)
        else:
            vol = calc_volume(float(info.get("equity") or info.get("balance") or 0),
                              info.get("currency") or "USD", sl_dist, self.risk_pct, self.max_lot, spec)
        if min_lot and vol > 0:
            vol = round(float(spec.get("minVolume") or 0.01), 2)
        if vol <= 0:
            raise MetaApiError("no money", "NO_MONEY")
        px = await self.api.price(mid, region, symbol)
        # SL/TP от цены брокера: у бота и у брокера котировки отличаются на несколько долларов
        open_px = float(px["ask"] if direction == 1 else px["bid"])
        digits = spec.get("digits")
        sl = round_price(open_px - direction * sl_dist, digits)
        tp = round_price(open_px + direction * tp_dist, digits)
        req = {"actionType": "ORDER_TYPE_BUY" if direction == 1 else "ORDER_TYPE_SELL", "symbol": symbol,
               "volume": vol, "stopLoss": sl, "takeProfit": tp, "comment": f"goldbot #{sid}"[:26]}
        resp = await self.api.trade(mid, region, req)
        pos = str(resp.get("positionId") or resp.get("orderId") or "")
        await self.db.save_auto_trade(sid, acc["user_id"], pos, vol, "open", "")
        return OpenResult(acc["user_id"], True, vol, open_px, sl, tp, symbol)

    # ── проп-счета ──────────────────────────────────────────────────────────
    async def _prop_volume(self, acc: dict, info: dict, spec: dict, sl_dist: float, strong: bool = False) -> float:
        """Лот на проп-счёте: не больше prop_risk_pct % (≤ 2.8 %) и так, чтобы стоп этой сделки вместе со
        стопами уже открытых не довёл счёт до дневного или общего лимита FundedNext."""
        balance = float(info.get("balance") or 0)
        equity = float(info.get("equity") or balance)
        acc = await self._prop_roll(acc, balance)
        goal = pr.target_balance(acc)
        if goal is not None and balance + 1e-6 >= goal:
            # цель этапа уже есть: дальше только минимальный лот, чтобы набрать торговые дни и не потерять результат
            return round(float(spec.get("minVolume") or 0.01), 2)
        positions = [p for p in await self.api.positions(acc["meta_id"], acc["region"])
                     if not p.get("symbol") or p.get("symbol") == acc["symbol"]]
        contract = float(spec.get("contractSize") or 100)
        risk = self.prop_strong_risk_pct if strong else self.prop_risk_pct
        budget, reason = pr.risk_budget(acc, equity, positions, risk, self.prop_guard_pct, contract,
                                        min(self.prop_risk_cap, pr.DAILY_CAP_PCT), self.prop_max_trade)
        vol = pr.volume_for(budget, sl_dist, spec, self.prop_max_lot)
        if vol <= 0:
            raise MetaApiError(f"prop limit ({reason}, budget {budget:.2f})", "PROP_LIMIT")
        return vol

    async def _prop_roll(self, acc: dict, balance: float) -> dict:
        """Новый торговый день FundedNext: запоминаем баланс на начало дня, снимаем дневную остановку."""
        today = pr.day_key(_now(), self.prop_day_tz)
        if acc.get("prop_day") == today:
            return acc
        upd = {"prop_day": today, "prop_day_balance": balance}
        if acc.get("prop_halt") == "daily":
            upd["prop_halt"] = ""
        await self.db.update_prop_state(acc["user_id"], **upd)
        return {**acc, **upd, "_new_day": acc.get("prop_halt") == "daily"}

    async def _close_all(self, acc: dict) -> int:
        """Закрывает позиции на счёте (prop_close: all — все, bot — только открытые ботом)."""
        if self.prop_close == "none":
            return 0
        n = 0
        for p in await self.api.positions(acc["meta_id"], acc["region"]):
            if self.prop_close == "bot" and not str(p.get("comment") or "").startswith("goldbot"):
                continue
            try:
                await self.api.trade(acc["meta_id"], acc["region"],
                                     {"actionType": "POSITION_CLOSE_ID", "positionId": str(p.get("id"))})
                n += 1
            except MetaApiError as e:
                log.warning("prop close %s for %s: %s", p.get("id"), acc["user_id"], e)
        await self.db.close_user_auto_trades(acc["user_id"])
        return n

    async def prop_check(self) -> list[dict]:
        """Проверка проп-счетов (раз в ~20 с). Следит за средствами с учётом открытых сделок; у лимита
        закрывает сделки и останавливает торговлю; отмечает торговые дни и прохождение этапа.
        Возвращает события для сообщений подписчикам: halt / new_day / passed."""
        events: list[dict] = []
        accounts = [a for a in await self.db.trade_accounts(enabled_only=True, exempt=self.exempt)
                    if a.get("prop_plan") in pr.PLANS]
        for acc in accounts:
            try:
                events += await self._prop_check_one(acc)
            except Exception as e:  # noqa: BLE001
                log.info("prop check for %s: %s", acc["user_id"], e)
        return events

    async def _prop_check_one(self, acc: dict) -> list[dict]:
        uid, events = acc["user_id"], []
        info = await self.api.account_info(acc["meta_id"], acc["region"], timeout=30)
        balance = float(info.get("balance") or 0)
        equity = float(info.get("equity") or balance)
        if balance <= 0:
            return events
        acc = await self._prop_roll(acc, balance)
        if acc.pop("_new_day", False):
            events.append({"uid": uid, "kind": "new_day"})
        today = acc["prop_day"]
        upd: dict = {}
        if abs(balance - float(acc.get("prop_day_balance") or balance)) > 0.005 and acc.get("prop_last_day") != today:
            upd["prop_days"] = int(acc.get("prop_days") or 0) + 1   # сегодня была закрытая сделка
            upd["prop_last_day"] = today
        if equity > float(acc.get("prop_peak") or 0):
            upd["prop_peak"] = equity
        if equity < float(acc.get("prop_min_equity") or equity + 1):
            upd["prop_min_equity"] = equity
        day_loss = float(acc.get("prop_day_balance") or balance) - equity
        if day_loss > float(acc.get("prop_worst_day") or 0):
            upd["prop_worst_day"] = day_loss
        acc = {**acc, **upd}
        lim = pr.limits(acc, equity, min(self.prop_risk_cap, pr.DAILY_CAP_PCT))
        if not acc.get("prop_halt"):
            if lim.room <= 0 or lim.hard_room <= float(acc["prop_size"]) * self.prop_guard_pct / 100:
                upd["prop_halt"] = lim.binding
                closed = await self._close_all(acc)
                events.append({"uid": uid, "kind": "halt", "limit": lim.binding, "equity": equity,
                               "floor": lim.floor, "closed": closed, "acc": {**acc, **upd}})
            elif pr.phase_passed(acc, balance) and not await self.api.positions(acc["meta_id"], acc["region"]):
                # этап пройден и всё закрыто: отключаемся от этого счёта, бот попросит счёт следующего этапа
                report = {**acc, **upd, "balance": balance}
                await self.disconnect(uid)
                nxt = pr.next_stage(acc)
                await self.db.set_kv(f"prop_next:{uid}", json.dumps(
                    {"plan": acc["prop_plan"], "stage": nxt, "size": acc["prop_size"],
                     "platform": acc.get("platform") or "mt5"}))
                events.append({"uid": uid, "kind": "passed", "acc": report, "next": nxt})
                return events
        if upd:
            await self.db.update_prop_state(uid, **upd)
        return events

    async def close_signal(self, sid: int, uids: set[int] | None = None) -> list[CloseResult]:
        """Закрывает по рынку всё, что ещё открыто по сигналу (uids — только у этих подписчиков)."""
        trades = [tr for tr in await self.db.auto_trades(sid, status="open") if uids is None or tr["user_id"] in uids]
        sem = asyncio.Semaphore(self.concurrency)

        async def one(tr: dict) -> CloseResult:
            async with sem:
                try:
                    return await self._close_one(tr)
                except Exception as e:  # noqa: BLE001
                    log.warning("autotrade close #%s for %s failed: %s", sid, tr["user_id"], e)
                    return CloseResult(tr["user_id"], False, error=getattr(e, "code", "") or str(e)[:200])

        return list(await asyncio.gather(*(one(tr) for tr in trades)))

    async def _close_one(self, tr: dict) -> CloseResult:
        uid, sid = tr["user_id"], tr["signal_id"]
        acc = await self.db.get_trade_account(uid)
        if not acc:
            await self.db.set_auto_trade_status(sid, uid, "closed")
            return CloseResult(uid, False, error="NO_ACCOUNT")
        mid, region, pos = acc["meta_id"], acc["region"], tr["position_id"]
        open_ids = {str(p.get("id")) for p in await self.api.positions(mid, region)}
        already = pos not in open_ids
        if not already:
            await self.api.trade(mid, region, {"actionType": "POSITION_CLOSE_ID", "positionId": pos})
        await self.db.set_auto_trade_status(sid, uid, "closed")
        profit = None
        try:
            await asyncio.sleep(1)
            deals = await self.api.deals_by_position(mid, region, pos)
            if deals:
                profit = round(sum(float(d.get(k) or 0) for d in deals for k in ("profit", "commission", "swap")), 2)
        except Exception as e:  # noqa: BLE001
            log.info("deals for %s: %s", pos, e)
        return CloseResult(uid, True, profit, acc.get("currency") or "USD", already)


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


class BrokerMarket(Provider):
    """Свечи и цена XAUUSD прямо с MetaTrader-счёта через MetaApi (тот же график, что в MT5 у брокера).
    source() → {"meta_id", "region", "symbol"} счёта, с которого берём данные (None — счёта нет)."""

    def __init__(self, api: MetaApi, source):
        self.api, self.source = api, source

    async def _src(self) -> dict:
        src = await self.source()
        if not src:
            raise MetaApiError("no market data account", "NO_ACCOUNT")
        return src

    async def candles(self, tf: str, count: int):
        src = await self._src()
        url = (f"{MARKET.format(region=src['region'] or 'new-york')}/users/current/accounts/{src['meta_id']}"
               f"/historical-market-data/symbols/{src['symbol']}/timeframes/{MT_TF[tf]}/candles"
               f"?limit={min(count, 1000)}")
        body = await self.api._ok("GET", url, timeout=20)
        if not body:
            raise MetaApiError("no candles", "NO_DATA")
        rows = [{"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"],
                 "close": c["close"], "volume": c.get("tickVolume") or 0} for c in body]
        df = _frame(rows)
        return df[~df.index.duplicated(keep="last")].iloc[-count:]

    async def price(self) -> float:
        src = await self._src()
        body = await self.api._ok(
            "GET", f"{self.api._client(src['meta_id'], src['region'])}/symbols/{src['symbol']}/current-price"
                   f"?keepSubscription=true", timeout=10)
        p = float(body.get("bid") or 0)   # графики в MetaTrader строятся по bid
        if p <= 0:
            raise MetaApiError(f"no price: {body}", "NO_DATA")
        return p


def sl_tp_dist(entry: float, sl: float, tp: float, sl_pips: float = 0, tp_pips: float = 0) -> tuple[float, float]:
    """Расстояние до стопа и тейка в $ цены (пипсы сигнала × PIP или из уровней)."""
    sd = sl_pips * PIP if sl_pips else abs(entry - sl)
    td = tp_pips * PIP if tp_pips else abs(tp - entry)
    return sd, td
