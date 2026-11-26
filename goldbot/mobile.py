"""API мобильного приложения XAUUSD Gold (iPhone и Android, папка mobile/).

Приложение самостоятельное: вход по почте и паролю, без Telegram. По желанию можно войти через Telegram или
привязать Telegram позже — тогда в приложении тот же профиль, капитал, проп-анкета и счета автоторговли, что в боте.

Как устроены пользователи:
* таблица app_users — аккаунты приложения; app_tokens — сессии (храним только хэш токена);
* uid пользователя для общих таблиц (проп-анкета и т.п.) — его Telegram id, если Telegram привязан,
  иначе отрицательное число −id. Отрицательные uid не попадают в таблицу users, поэтому рассылки бота в
  Telegram их не трогают; сигналы им приходят push-уведомлением (Expo push, ключи не нужны).

Все ответы — JSON. Авторизация: заголовок «Authorization: Bearer <токен>».
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import secrets
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Awaitable, Callable

from aiohttp import ClientSession, ClientTimeout, web

from .config import config
from .data import PIP
from .db import now
from .i18n import LANGS, norm, t

if TYPE_CHECKING:
    from .bot import App

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE,
    pass_hash TEXT,
    name TEXT,
    lang TEXT,
    capital REAL,
    tg_id INTEGER UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_tokens (
    token_hash TEXT PRIMARY KEY,
    app_user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    seen_at TEXT
);
CREATE TABLE IF NOT EXISTS app_push (
    token TEXT PRIMARY KEY,
    app_user_id INTEGER NOT NULL,
    platform TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_tglogin (
    code TEXT PRIMARY KEY,
    app_user_id INTEGER,
    tg_id INTEGER,
    created_at TEXT NOT NULL
);
"""

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s.]{2,24}$")
PBKDF2_ITER = 200_000
TG_CODE_TTL = 15 * 60            # код входа через Telegram живёт 15 минут
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
FAIL_LIMIT, FAIL_WINDOW = 8, 15 * 60   # неверных паролей подряд на одну почту за 15 минут


# ── пароли и токены ─────────────────────────────────────────────────────────
def hash_password(password: str, salt: bytes | None = None, iterations: int = PBKDF2_ITER) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2${iterations}${salt.hex()}${dk.hex()}"


def check_password(password: str, stored: str | None) -> bool:
    try:
        algo, it, salt, want = (stored or "").split("$")
        if algo != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(it))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), want)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def norm_email(s) -> str | None:
    s = (s or "").strip().lower() if isinstance(s, str) else ""
    return s if EMAIL_RE.match(s) else None


def uid_of(user: dict) -> int:
    """uid для общих таблиц бота: Telegram id или −id аккаунта приложения."""
    return int(user["tg_id"]) if user.get("tg_id") else -int(user["id"])


def is_app_uid(uid: int) -> bool:
    return uid < 0


# ── тексты push-уведомлений ────────────────────────────────────────────────
PUSH = {
    "ru": {"signal": "Новый сигнал", "entry": "Вход", "close_tp": "Take Profit", "close_sl": "Stop Loss",
           "close_be": "Безубыток", "close_rev": "Закрыт при развороте", "close_news": "Закрыт перед новостью",
           "closed": "Сигнал #{id} закрыт", "pips": "пипсов", "partial": "Сигнал #{id}: TP1 достигнут",
           "partial_body": "Закройте {pct}% и перенесите стоп в безубыток",
           "prop": "Проп-сигнал", "lot": "лот", "prop_closed": "Проп-сделка #{id} закрыта",
           "prop_skip": "Проп-сигнал #{id} пропущен: лимит риска на сегодня"},
    "en": {"signal": "New signal", "entry": "Entry", "close_tp": "Take Profit", "close_sl": "Stop Loss",
           "close_be": "Breakeven", "close_rev": "Closed on reversal", "close_news": "Closed before news",
           "closed": "Signal #{id} closed", "pips": "pips", "partial": "Signal #{id}: TP1 reached",
           "partial_body": "Close {pct}% and move the stop to breakeven",
           "prop": "Prop signal", "lot": "lot", "prop_closed": "Prop trade #{id} closed",
           "prop_skip": "Prop signal #{id} skipped: today's risk limit"},
    "uz": {"signal": "Yangi signal", "entry": "Kirish", "close_tp": "Take Profit", "close_sl": "Stop Loss",
           "close_be": "Zararsiz", "close_rev": "Burilishda yopildi", "close_news": "Yangilikdan oldin yopildi",
           "closed": "#{id} signal yopildi", "pips": "pips", "partial": "#{id} signal: TP1 ga yetdi",
           "partial_body": "{pct}% ni yoping va stopni zararsizga o'tkazing",
           "prop": "Prop-signal", "lot": "lot", "prop_closed": "#{id} prop-savdo yopildi",
           "prop_skip": "#{id} prop-signal o'tkazib yuborildi: bugungi risk limiti"},
}


def ptx(lang: str, key: str, **kw) -> str:
    return PUSH[lang if lang in PUSH else "ru"][key].format(**kw)


def signal_push(lang: str, s) -> tuple[str, str]:
    get = (lambda k: s[k]) if isinstance(s, dict) else (lambda k: getattr(s, k))
    side = "🟢 BUY" if get("direction") == 1 else "🔴 SELL"
    return (f"{side} XAUUSD · {ptx(lang, 'signal')} #{get('id')}",
            f"{ptx(lang, 'entry')} {get('entry'):.2f} · SL {get('sl'):.2f} · TP {get('tp'):.2f}")


def close_push(lang: str, s: dict, status: str, pips: float) -> tuple[str, str]:
    icon = "✅" if pips > 0 else "⚪" if pips == 0 else "❌"
    return (f"{icon} {ptx(lang, 'closed', id=s['id'])}",
            f"{ptx(lang, 'close_' + status) if 'close_' + status in PUSH['ru'] else status} · "
            f"{pips:+.0f} {ptx(lang, 'pips')}")


PRIVACY_HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>XAUUSD Gold — Privacy Policy</title>
<style>body{font:16px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;background:#070a12;color:#f4f1e8;max-width:720px;
margin:0 auto;padding:24px}h1,h2{color:#f7d46b}a{color:#f7d46b}hr{border:0;border-top:1px solid #333;margin:32px 0}</style>
</head><body>
<h1>XAUUSD Gold — Privacy Policy</h1>
<p>The XAUUSD Gold app and Telegram bot show trading signals, statistics and education about gold (XAUUSD).</p>
<h2>What we store</h2>
<ul><li>Your email, name and a password hash (we never store the password itself).</li>
<li>Your settings: language, capital you entered, prop-firm form and balance.</li>
<li>A push-notification token of your phone, to send signals.</li>
<li>If you link Telegram: your Telegram ID, so the app and the bot share one profile.</li></ul>
<h2>What we do not do</h2>
<ul><li>We do not sell or share your data with third parties for advertising.</li>
<li>We do not ask for broker passwords in the app. Auto-trading accounts are connected in the Telegram bot through
the secure MetaApi service.</li></ul>
<h2>Services we use</h2>
<p>Expo push notifications (to deliver notifications), Apple App Store and Google Play (payments, if you buy a
subscription).</p>
<h2>Deleting your data</h2>
<p>Open Profile → Delete account in the app. Your app account and its data are deleted immediately.</p>
<h2>Risk warning</h2>
<p>Trading involves risk. Signals are not investment advice.</p>
<hr>
<h1>Политика конфиденциальности</h1>
<p>Мы храним почту, имя, хэш пароля, ваши настройки (язык, капитал, проп-анкету) и токен push-уведомлений. Если вы
привязали Telegram — ваш Telegram ID. Данные не продаём и не передаём для рекламы. Пароли от брокерских счетов в
приложении не запрашиваются. Удалить аккаунт: Профиль → Удалить аккаунт. Торговля связана с риском, сигналы — не
инвестиционная рекомендация.</p>
<hr>
<h1>Maxfiylik siyosati</h1>
<p>Biz pochta, ism, parol xeshi, sozlamalaringiz (til, kapital, prop-anketa) va push-bildirishnoma tokenini saqlaymiz.
Telegram ulangan boʻlsa — Telegram ID. Maʼlumotlar sotilmaydi va reklama uchun berilmaydi. Ilovada broker hisoblari
paroli soʻralmaydi. Akkauntni oʻchirish: Profil → Akkauntni oʻchirish. Savdo xavf bilan bogʻliq, signallar investitsiya
maslahati emas.</p>
</body></html>"""


# ── сам API ─────────────────────────────────────────────────────────────────
class Mobile:
    def __init__(self, app: "App") -> None:
        self.app = app
        self._fails: dict[str, list[float]] = {}
        self._analysis: dict[str, tuple[float, str]] = {}
        self._tasks: set[asyncio.Task] = set()
        self._ready = False

    @property
    def db(self):
        return self.app.db

    async def init_db(self) -> None:
        if not self._ready:
            await self.db.conn.executescript(SCHEMA)
            await self.db.conn.commit()
            self._ready = True

    def spawn(self, coro: Awaitable) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ── пользователи ────────────────────────────────────────────────────────
    async def _one(self, sql: str, args: tuple = ()) -> dict | None:
        await self.init_db()
        cur = await self.db.conn.execute(sql, args)
        row = await cur.fetchone()
        return dict(row) if row else None

    async def _exec(self, sql: str, args: tuple = ()) -> int:
        await self.init_db()
        cur = await self.db.conn.execute(sql, args)
        await self.db.conn.commit()
        return cur.lastrowid

    async def user_by_id(self, aid: int) -> dict | None:
        return await self._one("SELECT * FROM app_users WHERE id=?", (aid,))

    async def new_token(self, aid: int) -> str:
        tok = secrets.token_urlsafe(32)
        ts = now().isoformat()
        await self._exec("INSERT INTO app_tokens (token_hash, app_user_id, created_at, seen_at) VALUES (?,?,?,?)",
                         (token_hash(tok), aid, ts, ts))
        return tok

    async def lang_for_uid(self, uid: int) -> str:
        """Язык пользователя по uid (для push и сообщений об итогах проп-сделок)."""
        if not is_app_uid(uid):
            u = await self.db.get_user(uid)
            return norm(u.get("lang") if u else None)
        row = await self.user_by_id(-uid)
        return norm(row.get("lang") if row else None)

    async def profile(self, user: dict) -> dict:
        """lang / capital / имя: у привязанных к Telegram — из профиля бота, иначе из аккаунта приложения."""
        if user.get("tg_id"):
            u = await self.db.get_user(int(user["tg_id"])) or {}
            return {"lang": norm(u.get("lang") or user.get("lang")), "capital": u.get("capital"),
                    "name": user.get("name") or u.get("first_name") or ""}
        return {"lang": norm(user.get("lang")), "capital": user.get("capital"), "name": user.get("name") or ""}

    async def _auth(self, request: web.Request) -> dict:
        h = request.headers.get("Authorization", "")
        tok = h[7:].strip() if h.lower().startswith("bearer ") else ""
        row = await self._one("SELECT u.* FROM app_tokens k JOIN app_users u ON u.id=k.app_user_id "
                              "WHERE k.token_hash=?", (token_hash(tok),)) if tok else None
        if not row:
            raise web.HTTPUnauthorized(text='{"error":"auth"}', content_type="application/json")
        return row

    @staticmethod
    async def _body(request: web.Request) -> dict:
        try:
            body = await request.json() if request.can_read_body else {}
        except Exception:  # noqa: BLE001
            raise web.HTTPBadRequest(text='{"error":"json"}', content_type="application/json")
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text='{"error":"json"}', content_type="application/json")
        return body

    @staticmethod
    def err(code: str, status: int = 400) -> web.Response:
        return web.json_response({"error": code}, status=status)

    # ── вход ────────────────────────────────────────────────────────────────
    def _too_many(self, email: str) -> bool:
        cut = time.time() - FAIL_WINDOW
        self._fails[email] = [x for x in self._fails.get(email, []) if x > cut]
        return len(self._fails[email]) >= FAIL_LIMIT

    async def h_register(self, request: web.Request) -> web.Response:
        b = await self._body(request)
        email = norm_email(b.get("email"))
        pw = b.get("password") if isinstance(b.get("password"), str) else ""
        name = (b.get("name") or "").strip()[:64] if isinstance(b.get("name"), str) else ""
        lang = b.get("lang") if b.get("lang") in LANGS else "ru"
        if not email:
            return self.err("email")
        if len(pw) < 6 or len(pw) > 128:
            return self.err("password")
        if await self._one("SELECT id FROM app_users WHERE email=?", (email,)):
            return self.err("exists", 409)
        aid = await self._exec("INSERT INTO app_users (email, pass_hash, name, lang, created_at) VALUES (?,?,?,?,?)",
                               (email, await asyncio.to_thread(hash_password, pw), name, lang, now().isoformat()))
        log.info("mobile: new account #%s", aid)
        return web.json_response({"token": await self.new_token(aid)})

    async def h_login(self, request: web.Request) -> web.Response:
        b = await self._body(request)
        email = norm_email(b.get("email"))
        pw = b.get("password") if isinstance(b.get("password"), str) else ""
        if not email or not pw:
            return self.err("login", 401)
        if self._too_many(email):
            return self.err("too_many", 429)
        row = await self._one("SELECT * FROM app_users WHERE email=?", (email,))
        if not row or not await asyncio.to_thread(check_password, pw, row.get("pass_hash")):
            self._fails.setdefault(email, []).append(time.time())
            return self.err("login", 401)
        self._fails.pop(email, None)
        return web.json_response({"token": await self.new_token(row["id"])})

    async def h_logout(self, request: web.Request) -> web.Response:
        await self._auth(request)
        tok = request.headers.get("Authorization", "")[7:].strip()
        await self._exec("DELETE FROM app_tokens WHERE token_hash=?", (token_hash(tok),))
        b = await self._body(request)
        if isinstance(b.get("push"), str):
            await self._exec("DELETE FROM app_push WHERE token=?", (b["push"],))
        return web.json_response({"ok": True})

    async def h_delete(self, request: web.Request) -> web.Response:
        """Удаление аккаунта приложения (обязательно для App Store). Профиль в Telegram-боте не трогаем."""
        user = await self._auth(request)
        aid = user["id"]
        if not user.get("tg_id"):
            await self._exec("DELETE FROM prop_subs WHERE user_id=?", (-aid,))
            await self._exec("DELETE FROM prop_trades WHERE user_id=?", (-aid,))
        for sql in ("DELETE FROM app_tokens WHERE app_user_id=?", "DELETE FROM app_push WHERE app_user_id=?",
                    "DELETE FROM app_tglogin WHERE app_user_id=?", "DELETE FROM app_users WHERE id=?"):
            await self._exec(sql, (aid,))
        log.info("mobile: account #%s deleted", aid)
        return web.json_response({"ok": True})

    # вход / привязка через Telegram: приложение открывает t.me/<бот>?start=app_<код>, бот подтверждает код
    async def bot_username(self) -> str:
        if not getattr(self.app, "_bot_name", None):
            try:
                self.app._bot_name = (await self.app.bot.get_me()).username or ""
            except Exception:  # noqa: BLE001
                return ""
        return self.app._bot_name or ""

    async def h_tg_start(self, request: web.Request) -> web.Response:
        aid = None
        if request.headers.get("Authorization"):
            aid = (await self._auth(request))["id"]     # уже вошёл — привязываем Telegram к этому аккаунту
        code = secrets.token_hex(8)
        await self._exec("DELETE FROM app_tglogin WHERE created_at<?",
                         ((now() - timedelta(seconds=TG_CODE_TTL)).isoformat(),))
        await self._exec("INSERT INTO app_tglogin (code, app_user_id, created_at) VALUES (?,?,?)",
                         (code, aid, now().isoformat()))
        name = await self.bot_username()
        if not name:
            return self.err("bot", 503)
        return web.json_response({"code": code, "url": f"https://t.me/{name}?start=app_{code}",
                                  "tg": f"tg://resolve?domain={name}&start=app_{code}"})

    async def h_tg_poll(self, request: web.Request) -> web.Response:
        b = await self._body(request)
        code = b.get("code") if isinstance(b.get("code"), str) else ""
        row = await self._one("SELECT * FROM app_tglogin WHERE code=?", (code,)) if code else None
        if not row or datetime.fromisoformat(row["created_at"]) < now() - timedelta(seconds=TG_CODE_TTL):
            return self.err("code", 404)
        if not row.get("tg_id"):
            return web.json_response({"pending": True})
        await self._exec("DELETE FROM app_tglogin WHERE code=?", (code,))
        tg_id = int(row["tg_id"])
        if row.get("app_user_id"):      # привязка к уже открытому аккаунту
            return web.json_response({"linked": True})
        acc = await self._one("SELECT * FROM app_users WHERE tg_id=?", (tg_id,))
        if not acc:
            u = await self.db.get_user(tg_id) or {}
            aid = await self._exec("INSERT INTO app_users (name, lang, tg_id, created_at) VALUES (?,?,?,?)",
                                   (u.get("first_name") or "", u.get("lang"), tg_id, now().isoformat()))
        else:
            aid = acc["id"]
        return web.json_response({"token": await self.new_token(aid)})

    async def tg_confirm(self, code: str, tg_id: int, username: str | None, first_name: str | None) -> str:
        """Бот получил /start app_<код>. Возвращает 'login', 'linked', 'taken' (Telegram уже у другого аккаунта)
        или 'bad' (код неверный или устарел)."""
        row = await self._one("SELECT * FROM app_tglogin WHERE code=?", (code,))
        if not row or row.get("tg_id") or datetime.fromisoformat(row["created_at"]) < now() - timedelta(seconds=TG_CODE_TTL):
            return "bad"
        await self.db.add_user(tg_id, username, first_name)
        aid = row.get("app_user_id")
        if aid:
            other = await self._one("SELECT id FROM app_users WHERE tg_id=?", (tg_id,))
            if other and other["id"] != aid:
                return "taken"
            acc = await self.user_by_id(aid)
            if not acc:
                return "bad"
            await self._link(acc, tg_id)
        await self._exec("UPDATE app_tglogin SET tg_id=? WHERE code=?", (tg_id, code))
        return "linked" if aid else "login"

    async def _link(self, acc: dict, tg_id: int) -> None:
        """Привязка Telegram: язык и капитал из приложения переходят в бот (если там пусто), проп-анкета —
        тоже, если в боте её нет."""
        old = -int(acc["id"])
        u = await self.db.get_user(tg_id) or {}
        if not u.get("lang") and acc.get("lang"):
            await self.db.set_lang(tg_id, acc["lang"])
        if u.get("capital") is None and acc.get("capital") is not None:
            await self.db.set_capital(tg_id, float(acc["capital"]))
        if not await self.db.get_prop_sub(tg_id) and await self.db.get_prop_sub(old):
            await self._exec("UPDATE prop_subs SET user_id=? WHERE user_id=?", (tg_id, old))
            await self._exec("UPDATE prop_trades SET user_id=? WHERE user_id=?", (tg_id, old))
        await self._exec("UPDATE app_users SET tg_id=? WHERE id=?", (tg_id, acc["id"]))
        pending = int(await self.db.get_kv(f"app_credit:{acc['id']}") or 0)   # оплатил в приложении до привязки
        if pending:
            await self.db.add_credit(tg_id, pending)
            await self.db.set_kv(f"app_credit:{acc['id']}", "0")
        log.info("mobile: account #%s linked to telegram", acc["id"])

    async def h_tg_unlink(self, request: web.Request) -> web.Response:
        user = await self._auth(request)
        if not user.get("email"):
            return self.err("no_email")     # вошёл только через Telegram — отвязать нельзя, иначе не войти
        await self._exec("UPDATE app_users SET tg_id=NULL WHERE id=?", (user["id"],))
        return await self._state(await self.user_by_id(user["id"]))

    # ── данные ──────────────────────────────────────────────────────────────
    async def _state(self, user: dict) -> web.Response:
        return web.json_response(await self.state(user))

    async def state(self, user: dict) -> dict:
        uid = uid_of(user)
        prof = await self.profile(user)
        base = await self.app.webapp.state(uid, {**prof, "tg": {"first_name": prof["name"]}})
        bot = await self.bot_username()
        base["me"] = {"email": user.get("email"), "telegram": bool(user.get("tg_id")), "bot": bot or None,
                      "bot_url": f"https://t.me/{bot}" if bot else None}
        base["links"] = {"broker": config.broker_url or None, "broker_name": config.broker_name or None,
                         "fundednext": config.fundednext_url or None, "myfxbook": config.myfxbook_url or None}
        base["store"] = {"revenuecat": bool(config.revenuecat_secret)}
        if is_app_uid(uid):
            base["user"]["id"] = None    # у аккаунта без Telegram нет id бота
        return base

    async def h_state(self, request: web.Request) -> web.Response:
        return await self._state(await self._auth(request))

    async def h_market(self, request: web.Request) -> web.Response:
        await self._auth(request)
        return web.json_response(self.app.webapp.market(await self.db.open_signals()))

    async def h_analysis(self, request: web.Request) -> web.Response:
        """Кнопка «Сигнал»: разбор рынка сейчас, как в боте (кэш 2 минуты на язык)."""
        user = await self._auth(request)
        lang = (await self.profile(user))["lang"]
        cached = self._analysis.get(lang)
        if cached and time.time() - cached[0] < 120:
            text = cached[1]
        else:
            try:
                text = await asyncio.wait_for(self.app.engine.expected(lang), 40)
                self._analysis[lang] = (time.time(), text)
            except Exception:  # noqa: BLE001
                log.exception("mobile analysis")
                text = t(lang, "quotes_fail")
        from .webapp import plain  # noqa: PLC0415
        return web.json_response({"text": plain(text), "price": self.app.engine.last_price})

    async def h_news(self, request: web.Request) -> web.Response:
        user = await self._auth(request)
        lang = (await self.profile(user))["lang"]
        from .webapp import plain  # noqa: PLC0415
        try:
            text = await asyncio.wait_for(self.app.news.digest(lang, await self.app.engine.market_text()), 90)
        except Exception:  # noqa: BLE001
            log.exception("mobile news")
            return web.json_response({"text": plain(t(lang, "news_fail")), "ok": False})
        return web.json_response({"text": plain(text), "ok": True})

    async def h_calendar(self, request: web.Request) -> web.Response:
        user = await self._auth(request)
        lang = (await self.profile(user))["lang"]
        from .econ_calendar import impact_text  # noqa: PLC0415
        from .webapp import plain  # noqa: PLC0415
        n = now()
        rows = await self.db.events_between(n - timedelta(days=3), n + timedelta(days=7))
        events = [{"ts": e["ts"], "title": e.get("title") or "", "impact": e.get("impact") or "",
                   "country": e.get("country") or "", "forecast": e.get("forecast") or "",
                   "previous": e.get("previous") or "", "actual": e.get("actual") or "",
                   "effect": plain(impact_text(e.get("title") or "", e.get("forecast"), e.get("actual"), lang))}
                  for e in rows]
        return web.json_response({"events": events, "now": n.isoformat()})

    async def h_settings(self, request: web.Request) -> web.Response:
        user = await self._auth(request)
        b = await self._body(request)
        from .webapp import _num  # noqa: PLC0415
        tg = int(user["tg_id"]) if user.get("tg_id") else None
        if "lang" in b:
            if b["lang"] not in LANGS:
                return self.err("lang")
            await self._exec("UPDATE app_users SET lang=? WHERE id=?", (b["lang"], user["id"]))
            if tg:
                await self.db.set_lang(tg, b["lang"])
        if "capital" in b:
            cap = _num(b["capital"], 0, 100_000_000)
            if cap is None:
                return self.err("capital")
            await self._exec("UPDATE app_users SET capital=? WHERE id=?", (round(cap, 2), user["id"]))
            if tg:
                await self.db.set_capital(tg, round(cap, 2))
        if "name" in b:
            if not isinstance(b["name"], str):
                return self.err("name")
            await self._exec("UPDATE app_users SET name=? WHERE id=?", (b["name"].strip()[:64], user["id"]))
        if "password" in b:
            pw, old = b.get("password"), b.get("old_password")
            if not isinstance(pw, str) or not 6 <= len(pw) <= 128:
                return self.err("password")
            if user.get("pass_hash") and not (isinstance(old, str) and check_password(old, user["pass_hash"])):
                return self.err("old_password", 403)
            await self._exec("UPDATE app_users SET pass_hash=? WHERE id=?", (hash_password(pw), user["id"]))
        if "email" in b:
            email = norm_email(b["email"])
            if not email:
                return self.err("email")
            other = await self._one("SELECT id FROM app_users WHERE email=?", (email,))
            if other and other["id"] != user["id"]:
                return self.err("exists", 409)
            await self._exec("UPDATE app_users SET email=? WHERE id=?", (email, user["id"]))
        return await self._state(await self.user_by_id(user["id"]))

    async def h_prop(self, request: web.Request) -> web.Response:
        user = await self._auth(request)
        err = await self.app.webapp.do_prop(uid_of(user), await self._body(request))
        if err:
            return self.err(err)
        return await self._state(user)

    async def h_account(self, request: web.Request) -> web.Response:
        user = await self._auth(request)
        if not user.get("tg_id") or not await self.app.webapp.do_account(int(user["tg_id"]), await self._body(request)):
            return self.err("account")
        return await self._state(user)

    async def h_chart(self, request: web.Request) -> web.Response:
        """Картинка открытого сигнала (график с уровнями), как в сообщении бота."""
        await self._auth(request)
        try:
            sid = int(request.match_info["sid"])
        except ValueError:
            return self.err("sid", 404)
        s = await self.db.get_signal(sid)
        df = self.app.engine.df_for(s.get("strategy")) if s else None
        if not s or df is None:
            return self.err("chart", 404)
        from .chart import render_signal  # noqa: PLC0415
        try:
            png = await asyncio.to_thread(render_signal, df, s["direction"], s["entry"], s["sl"], s["tp"],
                                          f"XAUUSD · #{s['id']}", tz=config.display_tz, pip=PIP, tp1=s.get("tp1"))
        except Exception:  # noqa: BLE001
            log.exception("mobile chart")
            return self.err("chart", 500)
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "max-age=60"})

    # ── push ────────────────────────────────────────────────────────────────
    async def h_push(self, request: web.Request) -> web.Response:
        user = await self._auth(request)
        b = await self._body(request)
        tok = b.get("token")
        if not isinstance(tok, str) or not re.match(r"^(Expo|Exponent)PushToken\[[^\]]{8,200}\]$", tok):
            return self.err("token")
        plat = b.get("platform") if b.get("platform") in ("ios", "android") else None
        await self._exec("INSERT OR REPLACE INTO app_push (token, app_user_id, platform, created_at) VALUES (?,?,?,?)",
                         (tok, user["id"], plat, now().isoformat()))
        return web.json_response({"ok": True})

    async def devices(self) -> list[dict]:
        """Все телефоны с push: токен, uid и язык владельца."""
        await self.init_db()
        cur = await self.db.conn.execute(
            "SELECT p.token, a.id, a.tg_id, a.lang FROM app_push p JOIN app_users a ON a.id=p.app_user_id")
        rows = [dict(r) for r in await cur.fetchall()]
        langs = await self.db.user_langs()
        out = []
        for r in rows:
            uid = int(r["tg_id"]) if r["tg_id"] else -int(r["id"])
            lang = norm((langs.get(uid) if r["tg_id"] else None) or r["lang"])
            out.append({"token": r["token"], "uid": uid, "lang": lang})
        return out

    async def send_push(self, messages: list[dict]) -> int:
        """Отправка через Expo push API пачками по 100. Удалённые приложения убираем из базы."""
        if not config.mobile_push or not messages:
            return 0
        ok = 0
        async with ClientSession(timeout=ClientTimeout(total=20)) as s:
            for i in range(0, len(messages), 100):
                chunk = messages[i:i + 100]
                try:
                    async with s.post(EXPO_PUSH_URL, json=chunk, headers={"Accept": "application/json"}) as r:
                        data = (await r.json(content_type=None)).get("data") or []
                except Exception as e:  # noqa: BLE001
                    log.warning("expo push failed: %s", e)
                    continue
                for m, res in zip(chunk, data if isinstance(data, list) else []):
                    if res.get("status") == "ok":
                        ok += 1
                    elif (res.get("details") or {}).get("error") == "DeviceNotRegistered":
                        await self._exec("DELETE FROM app_push WHERE token=?", (m["to"],))
        return ok

    @staticmethod
    def _msg(token: str, title: str, body: str, data: dict) -> dict:
        return {"to": token, "title": title, "body": body, "data": data, "sound": "default",
                "priority": "high", "channelId": "signals"}

    async def push_all(self, make: Callable[[str], tuple[str, str]], data: dict,
                       skip: set[int] | frozenset = frozenset()) -> int:
        try:
            devs = await self.devices()
            cache: dict[str, tuple[str, str]] = {}
            msgs = []
            for d in devs:
                if d["uid"] in skip:
                    continue
                if d["lang"] not in cache:
                    cache[d["lang"]] = make(d["lang"])
                msgs.append(self._msg(d["token"], *cache[d["lang"]], data))
            return await self.send_push(msgs)
        except Exception:  # noqa: BLE001
            log.exception("mobile push")
            return 0

    async def push_uid(self, uid: int, title: str, body: str, data: dict | None = None) -> int:
        try:
            msgs = [self._msg(d["token"], title, body, data or {}) for d in await self.devices() if d["uid"] == uid]
            return await self.send_push(msgs)
        except Exception:  # noqa: BLE001
            log.exception("mobile push")
            return 0

    async def app_prop_uids(self) -> set[int]:
        """Проп-подписчики из приложения без Telegram (отрицательные uid)."""
        return {x["user_id"] for x in await self.db.prop_subs() if is_app_uid(x["user_id"])}

    # ── оплата в App Store / Google Play (RevenueCat) ──────────────────────
    async def h_revenuecat(self, request: web.Request) -> web.Response:
        """Вебхук RevenueCat: покупка или продление подписки «Автоторговля» → одно оплаченное подключение счёта
        (как оплата ⭐ в боте). app_user_id в RevenueCat = id аккаунта приложения."""
        if not config.revenuecat_secret or not hmac.compare_digest(
                request.headers.get("Authorization", ""), f"Bearer {config.revenuecat_secret}"):
            return self.err("auth", 401)
        ev = (await self._body(request)).get("event") or {}
        if ev.get("type") not in ("INITIAL_PURCHASE", "RENEWAL", "NON_RENEWING_PURCHASE"):
            return web.json_response({"ok": True, "skip": ev.get("type")})
        try:
            aid = int(str(ev.get("app_user_id", "")).removeprefix("app_"))
        except ValueError:
            return web.json_response({"ok": True, "skip": "user"})
        acc = await self.user_by_id(aid)
        if not acc or not acc.get("tg_id"):
            # Telegram ещё не привязан: подключение ждёт привязки (счёт MetaTrader подключается в боте)
            if not acc:
                return web.json_response({"ok": True, "skip": "user"})
            n = int(await self.db.get_kv(f"app_credit:{aid}") or 0) + 1
            await self.db.set_kv(f"app_credit:{aid}", str(n))
            log.info("revenuecat: autotrade paid by account #%s without telegram (%s pending)", aid, n)
            return web.json_response({"ok": True, "pending": n})
        n = await self.db.add_credit(int(acc["tg_id"]))
        log.info("revenuecat: +1 autotrade credit for tg %s (%s)", acc["tg_id"], n)
        return web.json_response({"ok": True, "credits": n})

    async def h_privacy(self, request: web.Request) -> web.Response:
        """Политика конфиденциальности (ссылка нужна App Store и Google Play): /privacy"""
        return web.Response(text=PRIVACY_HTML, content_type="text/html", charset="utf-8")

    async def h_ping(self, request: web.Request) -> web.Response:
        """Приложение проверяет, что адрес сервера верный."""
        return web.json_response({"ok": True, "app": "xauusd-gold"})

    # ── маршруты ────────────────────────────────────────────────────────────
    def add_routes(self, app: web.Application) -> None:
        r = app.router
        r.add_post("/m/api/register", self.h_register)
        r.add_post("/m/api/login", self.h_login)
        r.add_post("/m/api/logout", self.h_logout)
        r.add_post("/m/api/delete", self.h_delete)
        r.add_post("/m/api/tg/start", self.h_tg_start)
        r.add_post("/m/api/tg/poll", self.h_tg_poll)
        r.add_post("/m/api/tg/unlink", self.h_tg_unlink)
        r.add_post("/m/api/state", self.h_state)
        r.add_post("/m/api/market", self.h_market)
        r.add_post("/m/api/analysis", self.h_analysis)
        r.add_post("/m/api/news", self.h_news)
        r.add_post("/m/api/calendar", self.h_calendar)
        r.add_post("/m/api/settings", self.h_settings)
        r.add_post("/m/api/prop", self.h_prop)
        r.add_post("/m/api/account", self.h_account)
        r.add_post("/m/api/push", self.h_push)
        r.add_get("/m/api/chart/{sid}.png", self.h_chart)
        r.add_post("/m/api/revenuecat", self.h_revenuecat)
        r.add_get("/m/api/ping", self.h_ping)
        r.add_get("/privacy", self.h_privacy)
