"""Настройки из переменных окружения (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _ids(v: str) -> set[int]:
    return {int(x) for x in v.replace(";", ",").split(",") if x.strip().isdigit()}


@dataclass(frozen=True)
class Config:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    admin_ids: set[int] = field(default_factory=lambda: _ids(os.getenv("ADMIN_IDS", "")))
    db_path: str = os.getenv("DB_PATH", "goldbot.db")

    # рынок
    data_provider: str = os.getenv("DATA_PROVIDER", "twelvedata")   # twelvedata | oanda
    twelvedata_key: str = os.getenv("TWELVEDATA_API_KEY", "")
    oanda_token: str = os.getenv("OANDA_TOKEN", "")
    oanda_live: bool = os.getenv("OANDA_LIVE", "0") == "1"
    check_interval: int = int(os.getenv("CHECK_INTERVAL", "15"))     # секунд
    strategy: str = os.getenv("STRATEGY", "combo")                   # combo | fvg
    sl_pips: float = float(os.getenv("SL_PIPS", "100"))
    tp_pips: float = float(os.getenv("TP_PIPS", "200"))

    # подписка
    trial_days: int = int(os.getenv("TRIAL_DAYS", "3"))
    sub_days: int = int(os.getenv("SUB_DAYS", "30"))
    sub_price_stars: int = int(os.getenv("SUB_PRICE_STARS", "500"))

    # новости
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
    news_feeds: tuple[str, ...] = tuple(
        u.strip() for u in os.getenv(
            "NEWS_FEEDS",
            "https://www.fxstreet.com/rss/news,"
            "https://www.investing.com/rss/news_11.rss,"
            "https://www.investing.com/rss/news_95.rss",
        ).split(",") if u.strip()
    )
    display_tz: str = os.getenv("DISPLAY_TZ", "Asia/Tashkent")


config = Config()
