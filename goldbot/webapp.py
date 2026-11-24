"""Telegram Mini App: проп-панель, статистика, настройки и оплата в одном окне.

Приложение — дополнительный способ пользоваться ботом: кнопки в чате работают как раньше, сигналы по-прежнему
приходят сообщениями. Сервер (aiohttp) работает в том же процессе, что и бот, и отдаёт страницу goldbot/webapp/
и JSON API. Каждый запрос подписан Telegram (initData): без верной подписи бот ничего не отдаёт и не меняет.

Адрес приложения: WEBAPP_URL (свой домен или именованный туннель) либо адрес быстрого туннеля Cloudflare,
который бот сам узнаёт у контейнера cloudflared (WEBAPP_TUNNEL) и ставит в кнопку меню бота.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl

from aiohttp import ClientSession, ClientTimeout, web
from aiogram.types import LabeledPrice, MenuButtonWebApp, WebAppInfo

from . import prop as pr
from . import prop_signals as ps
from .config import config
from .data import PIP
from .db import now
from .i18n import LANGS, norm, t
from .results import WIN, signal_pips
from .webapp_lessons import lessons, lessons_vars
from .webapp_texts import texts

if TYPE_CHECKING:
    from .bot import App

log = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "webapp"
MAX_AGE = 24 * 3600          # initData старше суток не принимаем
_TAG = re.compile(r"<[^>]+>")


# ── проверка подписи Telegram ───────────────────────────────────────────────
def check_init_data(init_data: str, token: str, max_age: int = MAX_AGE, now_ts: float | None = None) -> dict | None:
    """Проверяет initData Mini App (core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app).
    Возвращает поля с разобранным user или None, если подпись неверна или данные устарели."""
    if not init_data or not token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    got = pairs.pop("hash", "")
    if not got:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    want = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, got):
        return None
    try:
        auth = int(pairs.get("auth_date", "0"))
    except ValueError:
        return None
    if max_age and (now_ts if now_ts is not None else time.time()) - auth > max_age:
        return None
    try:
        user = json.loads(pairs.get("user", "null"))
    except ValueError:
        return None
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        return None
    return {**pairs, "user": user}


def plain(s: str) -> str:
    """Текст бота (с HTML-разметкой) → простой текст для приложения."""
    return _TAG.sub("", s).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").strip()


def _num(v, lo: float, hi: float) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if lo <= x <= hi and x == x else None


# ── статистика сигналов ─────────────────────────────────────────────────────
def stats_payload(rows: list[dict], lang: str) -> dict:
    """Сигналы для экрана статистики: сделки (новые сверху), кривая доходности в пипсах и итоги по стратегиям.
    Итоги за период (7 / 30 дней / всё) приложение считает само из списка сделок."""
    trades = []
    for r in rows:
        v = signal_pips(r)
        trades.append({
            "id": r["id"], "ts": r["created_at"], "closed": r.get("closed_at"), "dir": r["direction"],
            "entry": r["entry"], "sl": r["sl"], "tp": r["tp"], "status": r["status"],
            "pips": round(v, 1) if v is not None else None, "strategy": r.get("strategy") or "",
            "part": bool(r.get("part_at")),
        })
    names = {}
    for key in {x["strategy"] for x in trades}:
        try:
            names[key] = plain(t(lang, f"strat_{key}"))
        except KeyError:
            names[key] = key
    return {"trades": trades, "strategies": names, "win": list(WIN)}


# ── проп ────────────────────────────────────────────────────────────────────
def plans_payload(lang: str, stage_name) -> list[dict]:
    return [{"key": k, "name": p.name, "daily": p.daily_pct, "total": p.total_pct, "trailing": p.trailing,
             "min_days": p.min_days, "targets": p.targets,
             "stages": [{"key": s, "name": plain(stage_name(lang, s))} for s in p.stages]}
            for k, p in pr.PLANS.items()]


def prop_sub_payload(sub: dict, lang: str, cfg: dict, stage_name, day_stopped: bool, reset: str) -> dict:
    st = ps.state(sub, **cfg)
    plan = st["plan"]
    size = st["size"]
    nxt = pr.next_stage(ps.acc_view(sub)) if st["passed"] else None
    return {
        "plan": sub["plan"], "plan_name": plan.name, "stage": sub.get("stage"),
        "stage_name": plain(stage_name(lang, sub.get("stage"))), "size": size, "balance": st["balance"],
        "profit_pct": (st["balance"] / size - 1) * 100, "goal": st["goal"], "to_goal": st["to_goal"],
        "target_pct": plan.targets.get(sub.get("stage"), 0),
        "progress": max(0.0, min(st["progress"] or 0.0, 1.0)) if st["goal"] is not None else None,
        "day_left": st["day_left"], "day_limit": st["day_limit"], "day_floor": st["day_floor"],
        "total_left": st["total_left"], "total_floor": st["total_floor"],
        "total_limit": size * plan.total_pct / 100, "daily_pct": plan.daily_pct, "total_pct": plan.total_pct,
        "trailing": plan.trailing,
        "risk_pct": st["risk_pct"], "risk_usd": st["risk_usd"], "low_risk": st["low_risk"],
        "passed": st["passed"], "failed": st["failed"], "days": st["days"], "min_days": st["min_days"],
        "only_prop": bool(sub.get("only_prop")), "enabled": bool(sub.get("enabled")),
        "day_stopped": day_stopped, "reset": reset, "next_stage": nxt,
        "next_stage_name": plain(stage_name(lang, nxt)) if nxt else None,
    }


def account_payload(acc: dict, cap: float, is_admin: bool, stage_name, lang: str) -> dict:
    out = {"id": acc["id"], "login": acc["login"], "server": acc["server"], "broker": acc.get("broker") or "",
           "platform": acc.get("platform") or "", "demo": bool(acc.get("demo")), "enabled": bool(acc.get("enabled")),
           "balance": acc.get("balance"), "equity": acc.get("equity"), "currency": acc.get("currency") or "USD",
           "paid_until": acc.get("paid_until"), "admin": is_admin, "read_only": bool(acc.get("read_only")),
           "prop": None}
    if acc.get("prop_plan") in pr.PLANS:
        plan = pr.PLANS[acc["prop_plan"]]
        size = float(acc["prop_size"])
        eq = acc.get("equity")
        lim = pr.limits(acc, float(eq if eq is not None else size), cap)
        goal = pr.target_balance(acc)
        bal = acc.get("balance")
        frac = pr.progress(acc, float(bal)) if bal is not None and goal is not None else None
        out["prop"] = {
            "plan_name": plan.name, "stage": acc.get("prop_stage"), "stage_name": plain(stage_name(lang, acc.get("prop_stage"))),
            "size": size, "goal": goal, "progress": max(0.0, min(frac, 1.0)) if frac is not None else None,
            "to_goal": max(0.0, goal - float(bal)) if goal is not None and bal is not None else None,
            "day_loss": lim.day_loss, "day_limit": lim.day_limit, "day_left": max(0.0, lim.day_limit - lim.day_loss),
            "total_floor": lim.total_floor, "days": int(acc.get("prop_days") or 0), "min_days": plan.min_days,
            "halt": acc.get("prop_halt") or "", "target_pct": plan.targets.get(acc.get("prop_stage"), 0),
        }
    return out


# ── сервер ──────────────────────────────────────────────────────────────────
class WebApp:
    def __init__(self, app: "App") -> None:
        self.app = app
        self.url: str | None = config.webapp_url or None
        self._runner: web.AppRunner | None = None
        self._button_url: str | None = None

    # авторизация: каждый запрос несёт initData в заголовке X-Init-Data
    async def _auth(self, request: web.Request) -> tuple[int, dict]:
        data = check_init_data(request.headers.get("X-Init-Data", ""), config.bot_token)
        if not data:
            raise web.HTTPUnauthorized(text=json.dumps({"error": "auth"}), content_type="application/json")
        tg = data["user"]
        uid = tg["id"]
        db = self.app.db
        u = await db.get_user(uid)
        if not u:   # открыл приложение раньше, чем бота: заводим как по /start (пробный период)
            await db.add_user(uid, tg.get("username"), tg.get("first_name"), config.trial_days)
            code = (tg.get("language_code") or "").split("-")[0]
            await db.set_lang(uid, code if code in LANGS else "en" if code else "ru")
            u = await db.get_user(uid)
        return uid, {**u, "tg": tg}

    @staticmethod
    async def _body(request: web.Request) -> dict:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            raise web.HTTPBadRequest(text='{"error":"json"}', content_type="application/json")
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text='{"error":"json"}', content_type="application/json")
        return body

    # ── данные ──────────────────────────────────────────────────────────────
    async def state(self, uid: int, u: dict) -> dict:
        a, db = self.app, self.app.db
        lang = norm(u.get("lang"))
        admin = a.is_admin(uid)
        if db.is_paid(u):
            sub = {"kind": "paid", "until": u["paid_until"]}
        elif db.has_access(u):
            sub = {"kind": "trial", "until": u["trial_until"]}
        else:
            sub = {"kind": "expired", "until": None}
        cap = u.get("capital")
        from .bot import lot_plan  # noqa: PLC0415 — bot импортирует этот модуль
        lot = lot_plan(cap) if cap else None

        rows = await db.last_signals(1000)
        open_sig = [s for s in rows if s["status"] == "open"]

        psub = await db.get_prop_sub(uid)
        prop = None
        if psub and psub.get("enabled"):
            psub = await a.ps_roll(psub)
            prop = prop_sub_payload(psub, lang, a.ps_cfg(), a.stage_name, await a.ps_day_stopped(), a.ps_reset())

        accounts = []
        if a.autotrader:
            try:
                accs = await asyncio.wait_for(a.autotrader.statuses(uid), 10)
            except Exception:  # noqa: BLE001 — MetaApi долго отвечает: показываем без баланса
                accs = await db.user_accounts(uid)
            accounts = [account_payload(x, config.prop_risk_cap, admin, a.stage_name, lang) for x in accs if x]

        days, stars, month_stars = a.at_plan()
        return {
            "lang": lang, "langs": [{"code": c, "name": plain(t(c, "lang_name"))} for c in LANGS],
            "t": texts(lang), "tz": config.display_tz,
            "user": {"id": uid, "name": u["tg"].get("first_name") or u.get("first_name") or "",
                     "photo": u["tg"].get("photo_url"), "admin": admin, "capital": cap,
                     "lot": lot["lot"] if lot else None, "lot_loss": lot["loss"] if lot else None,
                     "lot_profit": lot["profit"] if lot else None},
            "sub": {**sub, "stars": config.sub_price_stars, "days": config.sub_days},
            "auto": {"enabled": bool(a.autotrader), "usd": config.autotrade_month_usd, "days": days, "stars": stars,
                     "month_stars": month_stars, "credits": await db.credits(uid) if a.autotrader else 0},
            "market": self.market(open_sig),
            "stats": stats_payload(rows, lang),
            "prop": prop, "plans": plans_payload(lang, a.stage_name), "sizes": list(ps.SIZE_PRESETS),
            "size_min": ps.MIN_SIZE, "size_max": ps.MAX_SIZE,
            "accounts": accounts, "myfxbook": config.myfxbook_url or None,
            "fundednext": config.fundednext_url or None, "pip": PIP,
            "learn": {"lessons": lessons(lang), "vars": lessons_vars()},
        }

    def market(self, open_sig: list[dict]) -> dict:
        price = self.app.engine.last_price
        return {"price": round(price, 2) if price else None,
                "open": [{"id": s["id"], "dir": s["direction"], "entry": s["entry"], "sl": s["sl"], "tp": s["tp"],
                          "ts": s["created_at"], "tp1": s.get("tp1"), "part": bool(s.get("part_at"))}
                         for s in open_sig]}

    # ── обработчики ─────────────────────────────────────────────────────────
    async def h_state(self, request: web.Request) -> web.Response:
        uid, u = await self._auth(request)
        return web.json_response(await self.state(uid, u))

    async def h_market(self, request: web.Request) -> web.Response:
        """Живая цена и открытые сигналы — приложение спрашивает раз в несколько секунд."""
        await self._auth(request)
        return web.json_response(self.market(await self.app.db.open_signals()))

    async def h_settings(self, request: web.Request) -> web.Response:
        uid, u = await self._auth(request)
        body = await self._body(request)
        db = self.app.db
        if "lang" in body:
            if body["lang"] not in LANGS:
                return web.json_response({"error": "lang"}, status=400)
            await db.set_lang(uid, body["lang"])
        if "capital" in body:
            cap = _num(body["capital"], 0, 100_000_000)
            if cap is None:
                return web.json_response({"error": "capital"}, status=400)
            await db.set_capital(uid, round(cap, 2))
        return web.json_response(await self.state(uid, await self._user(uid, u)))

    async def _user(self, uid: int, u: dict) -> dict:
        return {**(await self.app.db.get_user(uid) or {}), "tg": u["tg"]}

    async def h_prop(self, request: web.Request) -> web.Response:
        """Анкета и состояние проп-сигналов — то же, что кнопка «Сигналы для проп-фирм» в боте."""
        uid, u = await self._auth(request)
        body = await self._body(request)
        db = self.app.db
        act = body.get("action")
        sub = await db.get_prop_sub(uid)
        if act == "save":
            plan, stage = body.get("plan"), body.get("stage")
            size = _num(body.get("size"), ps.MIN_SIZE, ps.MAX_SIZE)
            if plan not in pr.PLANS or stage not in pr.PLANS[plan].stages or size is None:
                return web.json_response({"error": "form"}, status=400)
            await db.save_prop_sub(uid, plan, stage, size)
            if "only" in body:
                await db.update_prop_sub(uid, only_prop=int(bool(body["only"])))
            log.info("prop signals (app): user %s %s %s $%s", uid, plan, stage, size)
        elif act == "balance":
            v = _num(body.get("balance"), 0, ps.MAX_SIZE * 10)
            if not sub or v is None:
                return web.json_response({"error": "balance"}, status=400)
            await db.update_prop_sub(uid, balance=round(v, 2), peak=max(float(sub.get("peak") or 0), v), enabled=1)
        elif act == "only":
            if not sub:
                return web.json_response({"error": "nosub"}, status=400)
            await db.update_prop_sub(uid, only_prop=int(bool(body.get("value"))))
        elif act == "off":
            if sub:
                await db.update_prop_sub(uid, enabled=0)
        elif act == "next":
            nxt = pr.next_stage(ps.acc_view(sub)) if sub else None
            if not nxt:
                return web.json_response({"error": "next"}, status=400)
            await db.save_prop_sub(uid, sub["plan"], nxt, float(sub["size"]))
        else:
            return web.json_response({"error": "action"}, status=400)
        return web.json_response(await self.state(uid, await self._user(uid, u)))

    async def h_account(self, request: web.Request) -> web.Response:
        """Пауза и запуск автоторговли на счёте (как кнопки в меню автоторговли)."""
        uid, u = await self._auth(request)
        body = await self._body(request)
        db = self.app.db
        aid = body.get("id")
        acc = await db.get_account(aid) if isinstance(aid, int) else None
        if not acc or acc["user_id"] != uid or body.get("action") not in ("pause", "resume"):
            return web.json_response({"error": "account"}, status=400)
        resume = body["action"] == "resume"
        await db.set_trade_enabled(acc["id"], resume)
        if resume:
            await db.update_prop_state(acc["id"], prop_halt="")
        return web.json_response(await self.state(uid, await self._user(uid, u)))

    async def h_invoice(self, request: web.Request) -> web.Response:
        """Ссылка на оплату ⭐ для WebApp.openInvoice. Оплату обрабатывает тот же код бота, что и счёт в чате."""
        uid, u = await self._auth(request)
        body = await self._body(request)
        a = self.app
        lang = norm(u.get("lang"))
        kind = body.get("kind")
        if kind == "sub":
            link = await a.bot.create_invoice_link(
                title=t(lang, "inv_title", days=config.sub_days), description=t(lang, "inv_desc"), payload="sub",
                currency="XTR", prices=[LabeledPrice(label=t(lang, "inv_label", days=config.sub_days),
                                                     amount=config.sub_price_stars)])
            return web.json_response({"link": link})
        if kind == "auto" and a.autotrader and not a.is_admin(uid):
            aid = body.get("id")
            acc = await a.db.get_account(aid) if isinstance(aid, int) else None
            if acc and acc["user_id"] != uid:
                acc = None
            days, stars, _ = a.at_plan()
            if not acc:
                await a.db.set_kv(f"pay_intent:{uid}", "real")
            title = (t(lang, "inv_auto_acc_title", login=acc["login"], days=days) if acc
                     else t(lang, "inv_auto_title", days=days))
            link = await a.bot.create_invoice_link(
                title=title, description=t(lang, "inv_auto_desc"), payload=f"auto:{acc['id']}" if acc else "auto",
                currency="XTR", prices=[LabeledPrice(label=t(lang, "inv_label", days=days), amount=stars)])
            return web.json_response({"link": link})
        return web.json_response({"error": "kind"}, status=400)

    async def h_action(self, request: web.Request) -> web.Response:
        """Действия, которые идут в чате бота (подключение счёта с паролем, FundedNext, статистика картинкой):
        бот присылает нужное сообщение, приложение закрывается и пользователь продолжает в чате."""
        uid, u = await self._auth(request)
        body = await self._body(request)
        a = self.app
        lang = norm(u.get("lang"))
        what = body.get("do")
        if what == "autotrade":
            await a.autotrade_menu(uid, uid, lang)
        elif what == "connect" and a.autotrader:
            if await a.can_connect(uid):
                await a.show_risks(uid, lang)
            else:
                await a.ask_payment(uid, uid, lang, "real")
        elif what == "fundednext" and a.autotrader:
            await a.prop_intro(uid, lang)
        elif what == "propsig":
            await a.propsig_menu(uid, uid, lang)
        else:
            return web.json_response({"error": "do"}, status=400)
        return web.json_response({"ok": True})

    async def h_health(self, request: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def h_index(self, request: web.Request) -> web.Response:
        resp = web.FileResponse(STATIC / "index.html")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    def make_app(self) -> web.Application:
        app = web.Application(client_max_size=64 * 1024)
        app.router.add_get("/", self.h_index)
        app.router.add_get("/health", self.h_health)
        app.router.add_post("/api/state", self.h_state)
        app.router.add_post("/api/market", self.h_market)
        app.router.add_post("/api/settings", self.h_settings)
        app.router.add_post("/api/prop", self.h_prop)
        app.router.add_post("/api/account", self.h_account)
        app.router.add_post("/api/invoice", self.h_invoice)
        app.router.add_post("/api/action", self.h_action)
        app.router.add_static("/static/", STATIC, show_index=False)
        return app

    # ── запуск и кнопка меню ────────────────────────────────────────────────
    async def start(self) -> None:
        self._runner = web.AppRunner(self.make_app(), access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, "0.0.0.0", config.webapp_port).start()
        log.info("mini app: listening on :%s", config.webapp_port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    async def tunnel_url(self) -> str | None:
        """Адрес быстрого туннеля у cloudflared (его metrics-сервер отвечает на /quicktunnel)."""
        if not config.webapp_tunnel:
            return None
        try:
            async with ClientSession(timeout=ClientTimeout(total=5)) as s:
                async with s.get(config.webapp_tunnel.rstrip("/") + "/quicktunnel") as r:
                    host = (await r.json(content_type=None)).get("hostname")
        except Exception:  # noqa: BLE001
            return None
        return f"https://{host}" if host else None

    async def set_button(self, url: str) -> None:
        await self.app.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text=config.webapp_button, web_app=WebAppInfo(url=url)))
        self._button_url = url
        log.info("mini app: menu button -> %s", url)

    async def loop(self, every: float = 60) -> None:
        """Ставит кнопку «Открыть приложение» в меню бота и обновляет её, если адрес туннеля сменился."""
        await self.start()
        while True:
            try:
                url = config.webapp_url or await self.tunnel_url()
                if url:
                    self.url = url
                    if url != self._button_url:
                        await self.set_button(url)
            except Exception:  # noqa: BLE001
                log.exception("mini app: menu button")
            await asyncio.sleep(every if self._button_url else 10)


def fmt_until(iso: str | None) -> str:
    return datetime.fromisoformat(iso).strftime("%d.%m.%Y") if iso else ""
