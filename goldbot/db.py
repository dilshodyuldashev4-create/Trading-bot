"""База пользователей, подписок и сигналов (SQLite)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    joined_at TEXT NOT NULL,
    trial_until TEXT NOT NULL,
    paid_until TEXT,
    blocked INTEGER NOT NULL DEFAULT 0,
    lang TEXT,
    capital REAL
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL,
    charge_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    strategy TEXT NOT NULL,
    direction INTEGER NOT NULL,
    entry REAL NOT NULL,
    sl REAL NOT NULL,
    tp REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    closed_at TEXT
);
CREATE TABLE IF NOT EXISTS calendar_events (
    key TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    country TEXT,
    title TEXT,
    impact TEXT,
    forecast TEXT,
    previous TEXT,
    actual TEXT
);
CREATE TABLE IF NOT EXISTS signal_lots (
    signal_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    lot REAL NOT NULL,
    PRIMARY KEY (signal_id, user_id)
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""


def now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


def _parse(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


class DB:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        cur = await self.conn.execute("PRAGMA table_info(users)")
        cols = [r[1] for r in await cur.fetchall()]
        if "lang" not in cols:  # старая база — добавляем колонки
            await self.conn.execute("ALTER TABLE users ADD COLUMN lang TEXT")
        if "capital" not in cols:
            await self.conn.execute("ALTER TABLE users ADD COLUMN capital REAL")
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    # ── пользователи ────────────────────────────────────────────────────────
    async def add_user(self, uid: int, username: str | None, first_name: str | None,
                       trial_days: int) -> bool:
        """Создаёт пользователя с пробным периодом. True — если новый."""
        cur = await self.conn.execute("SELECT id FROM users WHERE id=?", (uid,))
        if await cur.fetchone():
            await self.conn.execute("UPDATE users SET username=?, first_name=?, blocked=0 WHERE id=?",
                                    (username, first_name, uid))
            await self.conn.commit()
            return False
        t = now()
        await self.conn.execute(
            "INSERT INTO users (id, username, first_name, joined_at, trial_until) VALUES (?,?,?,?,?)",
            (uid, username, first_name, _iso(t), _iso(t + timedelta(days=trial_days))))
        await self.conn.commit()
        return True

    async def get_user(self, uid: int) -> dict | None:
        cur = await self.conn.execute("SELECT * FROM users WHERE id=?", (uid,))
        row = await cur.fetchone()
        return dict(row) if row else None

    @staticmethod
    def access_until(user: dict) -> datetime:
        t = _parse(user["trial_until"])
        p = _parse(user.get("paid_until"))
        return max(t, p) if p else t

    @staticmethod
    def is_paid(user: dict) -> bool:
        p = _parse(user.get("paid_until"))
        return bool(p and p > now())

    def has_access(self, user: dict | None) -> bool:
        return bool(user) and self.access_until(user) > now()

    async def extend_paid(self, uid: int, days: int) -> datetime:
        user = await self.get_user(uid)
        base = max(now(), _parse(user.get("paid_until")) or now()) if user else now()
        until = base + timedelta(days=days)
        await self.conn.execute("UPDATE users SET paid_until=? WHERE id=?", (_iso(until), uid))
        await self.conn.commit()
        return until

    async def revoke(self, uid: int) -> None:
        await self.conn.execute("UPDATE users SET paid_until=NULL, trial_until=? WHERE id=?",
                                (_iso(now()), uid))
        await self.conn.commit()

    async def set_lang(self, uid: int, lang: str) -> None:
        await self.conn.execute("UPDATE users SET lang=? WHERE id=?", (lang, uid))
        await self.conn.commit()

    async def set_capital(self, uid: int, capital: float) -> None:
        """Капитал в $; 0 — пользователь пропустил вопрос."""
        await self.conn.execute("UPDATE users SET capital=? WHERE id=?", (capital, uid))
        await self.conn.commit()

    async def add_capital(self, uid: int, delta: float) -> float:
        """Прибавляет результат сделки к капиталу (не ниже 0), возвращает новый капитал."""
        await self.conn.execute("UPDATE users SET capital=MAX(0, ROUND(COALESCE(capital,0)+?, 2)) WHERE id=?",
                                (delta, uid))
        await self.conn.commit()
        cur = await self.conn.execute("SELECT capital FROM users WHERE id=?", (uid,))
        row = await cur.fetchone()
        return row[0] if row else 0.0

    async def user_capitals(self) -> dict[int, float | None]:
        cur = await self.conn.execute("SELECT id, capital FROM users")
        return {r[0]: r[1] for r in await cur.fetchall()}

    async def user_langs(self) -> dict[int, str | None]:
        """id → выбранный язык (None, если ещё не выбирал)."""
        cur = await self.conn.execute("SELECT id, lang FROM users")
        return {r[0]: r[1] for r in await cur.fetchall()}

    async def lang_stats(self) -> dict[str, int]:
        cur = await self.conn.execute("SELECT COALESCE(lang, '—'), COUNT(*) FROM users GROUP BY 1")
        return {r[0]: r[1] for r in await cur.fetchall()}

    async def set_blocked(self, uid: int, blocked: bool = True) -> None:
        await self.conn.execute("UPDATE users SET blocked=? WHERE id=?", (int(blocked), uid))
        await self.conn.commit()

    async def active_user_ids(self) -> list[int]:
        """Кому слать сигналы: пробный период или оплаченная подписка."""
        t = _iso(now())
        cur = await self.conn.execute(
            "SELECT id FROM users WHERE blocked=0 AND (trial_until>? OR paid_until>?)", (t, t))
        return [r[0] for r in await cur.fetchall()]

    async def all_user_ids(self) -> list[int]:
        cur = await self.conn.execute("SELECT id FROM users WHERE blocked=0")
        return [r[0] for r in await cur.fetchall()]

    async def all_users(self) -> list[dict]:
        cur = await self.conn.execute("SELECT * FROM users ORDER BY joined_at")
        return [dict(r) for r in await cur.fetchall()]

    async def stats(self) -> dict:
        t = _iso(now())
        q = {
            "total": "SELECT COUNT(*) FROM users",
            "blocked": "SELECT COUNT(*) FROM users WHERE blocked=1",
            "paid": f"SELECT COUNT(*) FROM users WHERE paid_until>'{t}'",
            "trial": f"SELECT COUNT(*) FROM users WHERE trial_until>'{t}' AND (paid_until IS NULL OR paid_until<='{t}')",
            "signals": "SELECT COUNT(*) FROM signals",
            "tp": "SELECT COUNT(*) FROM signals WHERE status='tp'",
            "sl": "SELECT COUNT(*) FROM signals WHERE status='sl'",
            "revenue": "SELECT COALESCE(SUM(amount),0) FROM payments",
        }
        out = {}
        for k, sql in q.items():
            cur = await self.conn.execute(sql)
            out[k] = (await cur.fetchone())[0]
        return out

    async def expiring_trials(self, within: timedelta) -> list[int]:
        """Пользователи без оплаты, у которых пробный период кончается в ближайшее время."""
        a, b = _iso(now()), _iso(now() + within)
        cur = await self.conn.execute(
            "SELECT id FROM users WHERE blocked=0 AND trial_until>? AND trial_until<=? "
            "AND (paid_until IS NULL OR paid_until<=?)", (a, b, a))
        return [r[0] for r in await cur.fetchall()]

    # ── платежи ─────────────────────────────────────────────────────────────
    async def add_payment(self, uid: int, amount: int, currency: str, charge_id: str) -> None:
        await self.conn.execute(
            "INSERT INTO payments (user_id, amount, currency, charge_id, created_at) VALUES (?,?,?,?,?)",
            (uid, amount, currency, charge_id, _iso(now())))
        await self.conn.commit()

    # ── сигналы ─────────────────────────────────────────────────────────────
    async def add_signal(self, strategy: str, direction: int, entry: float, sl: float, tp: float) -> int:
        cur = await self.conn.execute(
            "INSERT INTO signals (created_at, strategy, direction, entry, sl, tp) VALUES (?,?,?,?,?,?)",
            (_iso(now()), strategy, direction, entry, sl, tp))
        await self.conn.commit()
        return cur.lastrowid

    async def open_signals(self) -> list[dict]:
        cur = await self.conn.execute("SELECT * FROM signals WHERE status='open'")
        return [dict(r) for r in await cur.fetchall()]

    async def close_signal(self, sid: int, status: str) -> None:
        await self.conn.execute("UPDATE signals SET status=?, closed_at=? WHERE id=?",
                                (status, _iso(now()), sid))
        await self.conn.commit()

    async def add_signal_lot(self, sid: int, uid: int, lot: float) -> None:
        """Какой лот бот показал подписчику в сигнале — по нему потом считаем его результат."""
        await self.conn.execute("INSERT OR REPLACE INTO signal_lots (signal_id, user_id, lot) VALUES (?,?,?)",
                                (sid, uid, lot))
        await self.conn.commit()

    async def signal_lots(self, sid: int) -> dict[int, float]:
        cur = await self.conn.execute("SELECT user_id, lot FROM signal_lots WHERE signal_id=?", (sid,))
        return {r[0]: r[1] for r in await cur.fetchall()}

    async def last_signals(self, n: int = 10) -> list[dict]:
        cur = await self.conn.execute("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (n,))
        return [dict(r) for r in await cur.fetchall()]

    # ── календарь ───────────────────────────────────────────────────────────
    async def upsert_events(self, events: list[dict]) -> None:
        await self.conn.executemany(
            "INSERT INTO calendar_events (key, ts, country, title, impact, forecast, previous, actual) "
            "VALUES (:key,:ts,:country,:title,:impact,:forecast,:previous,:actual) "
            "ON CONFLICT(key) DO UPDATE SET forecast=excluded.forecast, previous=excluded.previous, "
            "actual=COALESCE(NULLIF(excluded.actual,''), calendar_events.actual), ts=excluded.ts",
            events)
        await self.conn.commit()

    async def events_between(self, a: datetime, b: datetime) -> list[dict]:
        cur = await self.conn.execute(
            "SELECT * FROM calendar_events WHERE ts>=? AND ts<=? ORDER BY ts", (_iso(a), _iso(b)))
        return [dict(r) for r in await cur.fetchall()]

    # ── key-value ───────────────────────────────────────────────────────────
    async def get_kv(self, k: str, default: str | None = None) -> str | None:
        cur = await self.conn.execute("SELECT v FROM kv WHERE k=?", (k,))
        row = await cur.fetchone()
        return row[0] if row else default

    async def set_kv(self, k: str, v: str) -> None:
        await self.conn.execute("INSERT INTO kv (k, v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                                (k, v))
        await self.conn.commit()
