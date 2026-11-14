import asyncio
import os
import sqlite3
import tempfile
import unittest

from goldbot.db import DB


class MigrationTests(unittest.TestCase):
    def test_old_single_account_base_moves_to_many_accounts(self):
        async def go():
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "t.db")
                con = sqlite3.connect(path)
                con.executescript("""
                CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, joined_at TEXT NOT NULL,
                    trial_until TEXT NOT NULL, paid_until TEXT, blocked INTEGER NOT NULL DEFAULT 0, lang TEXT,
                    capital REAL, autotrade_until TEXT, autotrade_asked INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE trade_accounts (user_id INTEGER PRIMARY KEY, meta_id TEXT NOT NULL, region TEXT NOT NULL,
                    platform TEXT NOT NULL, server TEXT NOT NULL, login TEXT NOT NULL, symbol TEXT NOT NULL,
                    broker TEXT, currency TEXT, demo INTEGER NOT NULL DEFAULT 1, enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL);
                CREATE TABLE auto_trades (signal_id INTEGER NOT NULL, user_id INTEGER NOT NULL, position_id TEXT,
                    volume REAL NOT NULL DEFAULT 0, status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL,
                    PRIMARY KEY (signal_id, user_id));
                INSERT INTO users (id, joined_at, trial_until, autotrade_until)
                    VALUES (1, '2026-01-01', '2026-01-04', '2099-01-01T00:00:00+00:00'),
                           (2, '2026-01-01', '2026-01-04', '2099-01-01T00:00:00+00:00');
                INSERT INTO trade_accounts VALUES (1, 'm1', 'london', 'mt5', 'S', '777', 'XAUUSD', 'Exness', 'USD',
                    1, 1, '2026-01-02');
                INSERT INTO auto_trades VALUES (5, 1, 'p1', 0.1, 'open', '', '2026-01-03');
                """)
                con.commit()
                con.close()
                db = DB(path)
                await db.connect()
                acc = (await db.user_accounts(1))[0]
                self.assertEqual((acc["id"], acc["login"], acc["paid_until"]), (1, "777", "2099-01-01T00:00:00+00:00"))
                tr = await db.get_auto_trade(5, acc["id"])
                self.assertEqual((tr["user_id"], tr["position_id"], tr["status"]), (1, "p1", "open"))
                self.assertEqual(await db.credits(1), 0)
                self.assertEqual(await db.credits(2), 1)   # оплатил, но счёт ещё не подключил
                # теперь можно добавить второй счёт тому же подписчику
                aid = await db.save_trade_account(1, "m2", "london", "mt5", "S", "888", "XAUUSD", "X", "USD", True)
                self.assertEqual([a["id"] for a in await db.user_accounts(1)], [1, aid])
                self.assertTrue(await db.use_credit(2))
                self.assertFalse(await db.use_credit(2))
                await db.close()
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
