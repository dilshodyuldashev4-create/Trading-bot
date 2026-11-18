"""Сообщения админу о сбоях бота и ежедневная копия базы."""
from __future__ import annotations

import logging
import sqlite3
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# короткие обрывы связи сервера с Telegram: aiogram сам переподключается, админу о каждом — не пишем
NET_ERRORS = ("TelegramNetworkError", "TelegramServerError", "ClientConnectorError", "ServerDisconnectedError")


def is_net_error(text: str) -> bool:
    return any(x in text for x in NET_ERRORS)


class AlertHandler(logging.Handler):
    """Собирает ошибки (ERROR и выше) из логов бота; App раз в несколько секунд отправляет их админам.
    Одна и та же ошибка (то же место и тот же текст шаблона) — не чаще раза в repeat секунд.
    Ошибки связи с Telegram в очередь не попадают: только время последней (net_at) — App сообщит,
    если связь не работала дольше нескольких минут."""

    def __init__(self, repeat: float = 1800, maxlen: int = 200):
        super().__init__(logging.ERROR)
        self.repeat = repeat
        self.queue: deque[tuple[str, str]] = deque(maxlen=maxlen)
        self.sent: dict[str, float] = {}      # ключ ошибки → когда отправили
        self.skipped: dict[str, int] = {}     # сколько раз повторилась после отправки
        self.net_at: float | None = None      # когда была последняя ошибка связи с Telegram (time.monotonic)
        self.net_error = ""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            key = f"{record.name}:{record.msg}"
            text = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                e = record.exc_info[1]
                text += f"\n{type(e).__name__}: {e}"
            if is_net_error(text):
                self.net_at, self.net_error = time.monotonic(), text[:500]
                return
            self.queue.append((key, text[:1500]))
        except Exception:  # noqa: BLE001 — логирование не должно ронять бота
            pass

    def take(self, now: float | None = None) -> list[str]:
        """Что отправить сейчас: новые ошибки и те, что повторились после паузы (с числом повторов)."""
        now = time.monotonic() if now is None else now
        out = []
        while self.queue:
            key, text = self.queue.popleft()
            last = self.sent.get(key)
            if last is not None and now - last < self.repeat:
                self.skipped[key] = self.skipped.get(key, 0) + 1
                continue
            n = self.skipped.pop(key, 0)
            self.sent[key] = now
            out.append(text + (f"\n(повторялась ещё {n} раз)" if n else ""))
        return out

    def net_down(self, quiet: float = 90, now: float | None = None) -> bool:
        """Связь с Telegram сейчас сбоит: ошибка связи была за последние quiet секунд."""
        now = time.monotonic() if now is None else now
        return self.net_at is not None and now - self.net_at < quiet


@dataclass
class Watch:
    """Состояние «что-то не работает дольше limit секунд»: сообщить один раз и сообщить, когда починилось."""
    limit: float
    bad_since: float | None = None
    alerted: bool = False

    def update(self, bad: bool, now: float | None = None) -> str | None:
        """'down' — пора сообщить о сбое, 'up' — снова работает, None — ничего."""
        now = time.monotonic() if now is None else now
        if bad:
            if self.bad_since is None:
                self.bad_since = now
            if not self.alerted and now - self.bad_since >= self.limit:
                self.alerted = True
                return "down"
            return None
        self.bad_since = None
        if self.alerted:
            self.alerted = False
            return "up"
        return None


def backup_db(db_path: str, keep: int = 7, when: datetime | None = None) -> Path:
    """Копия базы SQLite (безопасно на ходу) в папку backups рядом с базой; старые сверх keep удаляются."""
    src_path = Path(db_path)
    folder = src_path.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{src_path.stem}-{(when or datetime.now()):%Y-%m-%d}.db"
    src, dst = sqlite3.connect(src_path), sqlite3.connect(out)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    old = sorted(folder.glob(f"{src_path.stem}-*.db"))
    for p in old[:-keep] if keep > 0 else []:
        p.unlink(missing_ok=True)
    return out
