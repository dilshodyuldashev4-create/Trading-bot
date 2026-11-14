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
    declined INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (signal_id, user_id)
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS trade_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    meta_id TEXT NOT NULL,
    region TEXT NOT NULL,
    platform TEXT NOT NULL,
    server TEXT NOT NULL,
    login TEXT NOT NULL,
    symbol TEXT NOT NULL,
    broker TEXT,
    currency TEXT,
    demo INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    paid_until TEXT,
    prop_plan TEXT,
    prop_stage TEXT,
    prop_size REAL,
    prop_day TEXT,
    prop_day_balance REAL,
    prop_peak REAL,
    prop_halt TEXT,
    prop_days INTEGER,
    prop_last_day TEXT,
    prop_min_equity REAL,
    prop_worst_day REAL
);
CREATE TABLE IF NOT EXISTS auto_trades (
    signal_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    position_id TEXT,
    volume REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (signal_id, account_id)
);
"""


# колонки проп-счёта (prop_plan пусто — обычный счёт)
PROP_COLUMNS = (("prop_plan", "TEXT"), ("prop_stage", "TEXT"), ("prop_size", "REAL"), ("prop_day", "TEXT"),
                ("prop_day_balance", "REAL"), ("prop_peak", "REAL"), ("prop_halt", "TEXT"),
                ("prop_days", "INTEGER"), ("prop_last_day", "TEXT"), ("prop_min_equity", "REAL"),
                ("prop_worst_day", "REAL"))


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
        if "autotrade_until" not in cols:  # оплачена автоторговля до
            await self.conn.execute("ALTER TABLE users ADD COLUMN autotrade_until TEXT")
        if "autotrade_asked" not in cols:  # бот уже спросил про автоторговлю
            await self.conn.execute("ALTER TABLE users ADD COLUMN autotrade_asked INTEGER NOT NULL DEFAULT 0")
        cur = await self.conn.execute("PRAGMA table_info(signals)")
        scols = [r[1] for r in await cur.fetchall()]
        if "exit_price" not in scols:  # цена закрытия вручную (перед важной новостью)
            await self.conn.execute("ALTER TABLE signals ADD COLUMN exit_price REAL")
        for c in ("mfe", "mae"):  # макс. ход в плюс / в минус по сделке, пипсы
            if c not in scols:
                await self.conn.execute(f"ALTER TABLE signals ADD COLUMN {c} REAL DEFAULT 0")
        if "autotrade_credits" not in cols:  # оплаченные, но ещё не подключённые счета
            await self.conn.execute("ALTER TABLE users ADD COLUMN autotrade_credits INTEGER NOT NULL DEFAULT 0")
        cur = await self.conn.execute("PRAGMA table_info(trade_accounts)")
        tcols = [r[1] for r in await cur.fetchall()]
        for c, typ in PROP_COLUMNS:  # проп-счёт FundedNext: тип, этап, размер и состояние лимитов
            if c not in tcols:
                await self.conn.execute(f"ALTER TABLE trade_accounts ADD COLUMN {c} {typ}")
        if "id" not in tcols:
            await self._migrate_many_accounts()
        await self.conn.commit()

    async def _migrate_many_accounts(self) -> None:
        """Старая база: один счёт на подписчика и оплата автоторговли в users. Переносим в новую схему:
        у счёта свой id и своя оплата (paid_until); сделки автоторговли привязаны к счёту."""
        old_cols = ("user_id, meta_id, region, platform, server, login, symbol, broker, currency, demo, enabled, "
                    "created_at, " + ", ".join(c for c, _ in PROP_COLUMNS))
        await self.conn.execute("ALTER TABLE trade_accounts RENAME TO trade_accounts_old")
        await self.conn.execute("ALTER TABLE auto_trades RENAME TO auto_trades_old")
        await self.conn.executescript(SCHEMA)
        await self.conn.execute(
            f"INSERT INTO trade_accounts ({old_cols}, paid_until) SELECT {', '.join('o.' + c.strip() for c in old_cols.split(','))}, "
            "u.autotrade_until FROM trade_accounts_old o LEFT JOIN users u ON u.id=o.user_id")
        await self.conn.execute(
            "INSERT OR IGNORE INTO auto_trades (signal_id, account_id, user_id, position_id, volume, status, error, "
            "created_at) SELECT o.signal_id, COALESCE(a.id, 0), o.user_id, o.position_id, o.volume, o.status, "
            "o.error, o.created_at FROM auto_trades_old o LEFT JOIN trade_accounts a ON a.user_id=o.user_id")
        # оплатил автоторговлю, но счёт ещё не подключил — одно оплаченное подключение
        await self.conn.execute(
            "UPDATE users SET autotrade_credits=autotrade_credits+1 WHERE autotrade_until>? "
            "AND id NOT IN (SELECT user_id FROM trade_accounts)", (_iso(now()),))
        await self.conn.execute("DROP TABLE trade_accounts_old")
        await self.conn.execute("DROP TABLE auto_trades_old")

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

    async def set_excursion(self, sid: int, mfe: float, mae: float) -> None:
        await self.conn.execute("UPDATE signals SET mfe=?, mae=? WHERE id=?", (mfe, mae, sid))
        await self.conn.commit()

    async def close_signal(self, sid: int, status: str, exit_price: float | None = None) -> None:
        await self.conn.execute("UPDATE signals SET status=?, closed_at=?, exit_price=? WHERE id=?",
                                (status, _iso(now()), exit_price, sid))
        await self.conn.commit()

    async def add_signal_lot(self, sid: int, uid: int, lot: float) -> None:
        """Какой лот бот показал подписчику в сигнале — по нему потом считаем его результат."""
        await self.conn.execute("INSERT OR REPLACE INTO signal_lots (signal_id, user_id, lot) VALUES (?,?,?)",
                                (sid, uid, lot))
        await self.conn.commit()

    async def signal_lots(self, sid: int) -> dict[int, float]:
        """Кто получил сигнал и с каким лотом — без тех, кто нажал «Отклонить»."""
        cur = await self.conn.execute("SELECT user_id, lot FROM signal_lots WHERE signal_id=? AND declined=0",
                                      (sid,))
        return {r[0]: r[1] for r in await cur.fetchall()}

    async def set_decision(self, sid: int, uid: int, declined: bool, lot: float = 0) -> None:
        """«Принять» / «Отклонить» под сигналом."""
        await self.conn.execute(
            "INSERT INTO signal_lots (signal_id, user_id, lot, declined) VALUES (?,?,?,?) "
            "ON CONFLICT(signal_id, user_id) DO UPDATE SET declined=excluded.declined",
            (sid, uid, lot, int(declined)))
        await self.conn.commit()

    async def declined_users(self, sid: int) -> set[int]:
        cur = await self.conn.execute("SELECT user_id FROM signal_lots WHERE signal_id=? AND declined=1", (sid,))
        return {r[0] for r in await cur.fetchall()}

    async def get_signal(self, sid: int) -> dict | None:
        cur = await self.conn.execute("SELECT * FROM signals WHERE id=?", (sid,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def closed_since(self, since: datetime) -> list[str]:
        """Статусы сигналов, созданных после since и уже закрытых, от последнего к первому."""
        cur = await self.conn.execute(
            "SELECT status FROM signals WHERE created_at>=? AND status!='open' ORDER BY id DESC", (_iso(since),))
        return [r[0] for r in await cur.fetchall()]

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

    # ── автоторговля ────────────────────────────────────────────────────────
    async def set_autotrade_asked(self, uid: int) -> None:
        await self.conn.execute("UPDATE users SET autotrade_asked=1 WHERE id=?", (uid,))
        await self.conn.commit()

    async def not_asked_autotrade(self) -> list[int]:
        """Активные подписчики, которых бот ещё не спрашивал про автоторговлю и у кого нет счёта."""
        t = _iso(now())
        cur = await self.conn.execute(
            "SELECT id FROM users WHERE blocked=0 AND autotrade_asked=0 AND (trial_until>? OR paid_until>?) "
            "AND id NOT IN (SELECT user_id FROM trade_accounts)", (t, t))
        return [r[0] for r in await cur.fetchall()]

    # ── счета автоторговли (у подписчика может быть несколько, у каждого своя оплата) ───────────
    async def save_trade_account(self, uid: int, meta_id: str, region: str, platform: str, server: str,
                                 login: str, symbol: str, broker: str, currency: str, demo: bool,
                                 paid_until: datetime | None = None) -> int:
        """Новый счёт подписчика; возвращает его id."""
        cur = await self.conn.execute(
            "INSERT INTO trade_accounts (user_id, meta_id, region, platform, server, login, symbol, broker, "
            "currency, demo, enabled, created_at, paid_until) VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)",
            (uid, meta_id, region, platform, server, login, symbol, broker, currency, int(demo), _iso(now()),
             _iso(paid_until) if paid_until else None))
        await self.conn.commit()
        return int(cur.lastrowid)

    async def set_prop(self, aid: int, plan: str, stage: str, size: float, day: str, day_balance: float,
                       peak: float) -> None:
        await self.conn.execute(
            "UPDATE trade_accounts SET prop_plan=?, prop_stage=?, prop_size=?, prop_day=?, prop_day_balance=?, "
            "prop_peak=?, prop_halt='', prop_days=0, prop_last_day='', prop_min_equity=?, prop_worst_day=0 "
            "WHERE id=?", (plan, stage, size, day, day_balance, peak, min(peak, day_balance), aid))
        await self.conn.commit()

    async def update_prop_state(self, aid: int, **fields) -> None:
        """prop_day, prop_day_balance, prop_peak, prop_halt, prop_days, prop_last_day, prop_min_equity …"""
        allowed = {"prop_day", "prop_day_balance", "prop_peak", "prop_halt", "prop_days", "prop_last_day",
                   "prop_min_equity", "prop_worst_day", "prop_stage"}
        keys = [k for k in fields if k in allowed]
        if not keys:
            return
        await self.conn.execute(f"UPDATE trade_accounts SET {', '.join(k + '=?' for k in keys)} WHERE id=?",
                                (*(fields[k] for k in keys), aid))
        await self.conn.commit()

    async def stop_losses_since(self, aid: int, since: datetime) -> int:
        """Сколько сделок автоторговли на счёте закрылось по Stop Loss начиная с since."""
        cur = await self.conn.execute(
            "SELECT COUNT(*) FROM auto_trades a JOIN signals s ON s.id = a.signal_id "
            "WHERE a.account_id=? AND a.position_id IS NOT NULL AND a.position_id != '' "
            "AND s.status='sl' AND s.closed_at>=?", (aid, _iso(since)))
        return int((await cur.fetchone())[0])

    async def close_account_auto_trades(self, aid: int) -> None:
        await self.conn.execute("UPDATE auto_trades SET status='closed' WHERE account_id=? AND status='open'", (aid,))
        await self.conn.commit()

    async def get_account(self, aid: int) -> dict | None:
        cur = await self.conn.execute("SELECT * FROM trade_accounts WHERE id=?", (aid,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def user_accounts(self, uid: int) -> list[dict]:
        cur = await self.conn.execute("SELECT * FROM trade_accounts WHERE user_id=? ORDER BY id", (uid,))
        return [dict(r) for r in await cur.fetchall()]

    async def get_trade_account(self, uid: int) -> dict | None:
        """Первый счёт подписчика (есть ли у него вообще подключённый счёт)."""
        accs = await self.user_accounts(uid)
        return accs[0] if accs else None

    async def delete_account(self, aid: int) -> None:
        await self.conn.execute("DELETE FROM trade_accounts WHERE id=?", (aid,))
        await self.conn.commit()

    async def set_trade_enabled(self, aid: int, enabled: bool) -> None:
        await self.conn.execute("UPDATE trade_accounts SET enabled=? WHERE id=?", (int(enabled), aid))
        await self.conn.commit()

    async def trade_accounts(self, enabled_only: bool = False, exempt: frozenset[int] = frozenset()) -> list[dict]:
        """Счета для автоторговли; enabled_only — включённые и оплаченные (exempt — админы, им оплата не нужна)."""
        if not enabled_only:
            cur = await self.conn.execute("SELECT * FROM trade_accounts ORDER BY id")
            return [dict(r) for r in await cur.fetchall()]
        cur = await self.conn.execute(
            "SELECT a.* FROM trade_accounts a JOIN users u ON u.id=a.user_id WHERE a.enabled=1 AND u.blocked=0 "
            "ORDER BY a.id")
        t = now()
        return [dict(r) for r in await cur.fetchall()
                if r["user_id"] in exempt or (_parse(r["paid_until"]) or t) > t]

    async def extend_account(self, aid: int, days: int) -> datetime:
        """Продлевает оплату счёта на days дней (от сегодня или от конца текущей оплаты)."""
        acc = await self.get_account(aid)
        base = max(now(), _parse((acc or {}).get("paid_until")) or now())
        until = base + timedelta(days=days)
        await self.conn.execute("UPDATE trade_accounts SET paid_until=? WHERE id=?", (_iso(until), aid))
        await self.conn.commit()
        return until

    async def add_credit(self, uid: int, n: int = 1) -> int:
        """+n оплаченных подключений нового счёта; возвращает, сколько их теперь."""
        await self.conn.execute("UPDATE users SET autotrade_credits=autotrade_credits+? WHERE id=?", (n, uid))
        await self.conn.commit()
        return await self.credits(uid)

    async def credits(self, uid: int) -> int:
        cur = await self.conn.execute("SELECT autotrade_credits FROM users WHERE id=?", (uid,))
        row = await cur.fetchone()
        return int(row[0] or 0) if row else 0

    async def use_credit(self, uid: int) -> bool:
        cur = await self.conn.execute(
            "UPDATE users SET autotrade_credits=autotrade_credits-1 WHERE id=? AND autotrade_credits>0", (uid,))
        await self.conn.commit()
        return cur.rowcount > 0

    async def extend_autotrade(self, uid: int, days: int) -> datetime:
        """Выдать автоторговлю (/grantauto): продлить все счета подписчика, а если счетов нет —
        одно бесплатное подключение. Возвращает, до какого времени."""
        accs = await self.user_accounts(uid)
        if not accs:
            await self.add_credit(uid)
            return now() + timedelta(days=days)
        return max([await self.extend_account(a["id"], days) for a in accs])

    @staticmethod
    def paid_until(acc: dict | None) -> datetime | None:
        return _parse((acc or {}).get("paid_until"))

    async def autotrade_expired_accounts(self, exempt: frozenset[int] = frozenset()) -> list[dict]:
        """Подключённые счета, у которых оплата закончилась (или не было)."""
        t = now()
        return [a for a in await self.trade_accounts()
                if a["user_id"] not in exempt and (_parse(a["paid_until"]) or t) <= t]

    async def autotrade_expiring(self, within: timedelta, exempt: frozenset[int] = frozenset()) -> list[dict]:
        """Счета, у которых оплата кончается в ближайшее время."""
        a, b = _iso(now()), _iso(now() + within)
        cur = await self.conn.execute(
            "SELECT * FROM trade_accounts WHERE paid_until>? AND paid_until<=?", (a, b))
        return [dict(r) for r in await cur.fetchall() if r["user_id"] not in exempt]

    # ── сделки автоторговли: по сигналу на каждом счёте ─────────────────────
    async def save_auto_trade(self, sid: int, aid: int, uid: int, position_id: str | None, volume: float,
                              status: str, error: str) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO auto_trades (signal_id, account_id, user_id, position_id, volume, status, error, "
            "created_at) VALUES (?,?,?,?,?,?,?,?)", (sid, aid, uid, position_id, volume, status, error, _iso(now())))
        await self.conn.commit()

    async def get_auto_trade(self, sid: int, aid: int) -> dict | None:
        cur = await self.conn.execute("SELECT * FROM auto_trades WHERE signal_id=? AND account_id=?", (sid, aid))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def auto_trades(self, sid: int, status: str | None = None) -> list[dict]:
        if status:
            cur = await self.conn.execute("SELECT * FROM auto_trades WHERE signal_id=? AND status=?", (sid, status))
        else:
            cur = await self.conn.execute("SELECT * FROM auto_trades WHERE signal_id=?", (sid,))
        return [dict(r) for r in await cur.fetchall()]

    async def set_auto_trade_status(self, sid: int, aid: int, status: str) -> None:
        await self.conn.execute("UPDATE auto_trades SET status=? WHERE signal_id=? AND account_id=?",
                                (status, sid, aid))
        await self.conn.commit()

    # ── key-value ───────────────────────────────────────────────────────────
    async def get_kv(self, k: str, default: str | None = None) -> str | None:
        cur = await self.conn.execute("SELECT v FROM kv WHERE k=?", (k,))
        row = await cur.fetchone()
        return row[0] if row else default

    async def set_kv(self, k: str, v: str) -> None:
        await self.conn.execute("INSERT INTO kv (k, v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                                (k, v))
        await self.conn.commit()
