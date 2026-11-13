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
    # откуда брать текущую цену каждые CHECK_INTERVAL секунд: пусто — тот же источник,
    # goldapi — gold-api.com (бесплатно, без ключа), finnhub — Finnhub (золото только в платном тарифе)
    price_provider: str = os.getenv("PRICE_PROVIDER", "")
    finnhub_key: str = os.getenv("FINNHUB_API_KEY", "")
    finnhub_symbol: str = os.getenv("FINNHUB_SYMBOL", "OANDA:XAU_USD")
    check_interval: int = int(os.getenv("CHECK_INTERVAL", "15"))     # секунд
    strategy: str = os.getenv("STRATEGY", "all")  # all | ключ стратегии | несколько через запятую (см. .env.example)
    sl_pips: float = float(os.getenv("SL_PIPS", "100"))
    tp_pips: float = float(os.getenv("TP_PIPS", "200"))
    # стоп и тейк по волатильности: SL_ATR × ATR(14) и TP_ATR × ATR(14) свечей стратегии, у каждого сигнала свои.
    # 0 — фиксированные SL_PIPS / TP_PIPS. Стоп не меньше SL_MIN_PIPS.
    sl_atr: float = float(os.getenv("SL_ATR", "2"))
    tp_atr: float = float(os.getenv("TP_ATR", "3"))
    sl_min_pips: float = float(os.getenv("SL_MIN_PIPS", "50"))
    # лот по капиталу подписчика (по умолчанию risk 2%): table — таблица ($50→0.01, $100→0.02, $200→0.03, +0.01 за $100),
    # risk — стоп забирает не больше LOT_RISK_PCT % капитала
    # «вы опоздали»: если цена ушла от входа в сторону тейка на столько пипсов — предупреждаем не входить
    late_pips: float = float(os.getenv("LATE_PIPS", "30"))
    # после стольких стопов подряд за день бот закрывает торговый день (0 — не закрывать)
    max_sl_streak: int = int(os.getenv("MAX_SL_STREAK", "0"))
    lot_mode: str = os.getenv("LOT_MODE", "risk")
    lot_risk_pct: float = float(os.getenv("LOT_RISK_PCT", "2"))

    # подписка
    trial_days: int = int(os.getenv("TRIAL_DAYS", "3"))
    sub_days: int = int(os.getenv("SUB_DAYS", "30"))
    sub_price_stars: int = int(os.getenv("SUB_PRICE_STARS", "500"))

    # пауза сигналов вокруг важных новостей США (минуты до и после; 0 — выключено)
    news_pause_min: int = int(os.getenv("NEWS_PAUSE_MIN", "30"))
    news_pause_impact: tuple[str, ...] = tuple(
        x.strip() for x in os.getenv("NEWS_PAUSE_IMPACT", "High").split(",") if x.strip())

    # 1 — не давать сигнал против сильного фона новостей (оценка Claude раз в час); 0 — только писать фон
    news_filter: bool = os.getenv("NEWS_FILTER", "0") not in ("0", "false", "no", "")

    # за сколько минут до важной новости США закрывать открытые сделки и предупреждать всех (0 — выкл.)
    news_close_min: int = int(os.getenv("NEWS_CLOSE_MIN", "30"))
    # 1 — торговать и во время важных новостей: без паузы и без закрытия сделок перед новостью,
    # сигнал проверяется свежей оценкой новости и геополитики; админ переключает /newstrade on|off
    news_trade: bool = os.getenv("NEWS_TRADE", "1") not in ("0", "false", "no", "")
    # утренний разбор рынка в это местное время (пн–пт); пусто — выключен
    morning_review: str = os.getenv("MORNING_REVIEW", "08:00")

    # новости
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
    news_feeds: tuple[str, ...] = tuple(
        u.strip() for u in os.getenv(
            "NEWS_FEEDS",
            # Google News отдаёт свежие заголовки и серверам в дата-центрах (FXStreet отвечает 403)
            "https://news.google.com/rss/search?q=gold+price+OR+XAUUSD+OR+bullion+when:1d"
            "&hl=en-US&gl=US&ceid=US:en,"
            "https://news.google.com/rss/search?q=%22Federal+Reserve%22+OR+Fed+OR+dollar+OR+inflation"
            "+OR+%22Treasury+yields%22+when:1d&hl=en-US&gl=US&ceid=US:en,"
            # геополитика: войны, санкции, конфликты, пошлины
            "https://news.google.com/rss/search?q=war+OR+sanctions+OR+geopolitical+OR+missile+OR+ceasefire"
            "+OR+Iran+OR+Israel+OR+Ukraine+OR+Taiwan+OR+tariffs+when:1d&hl=en-US&gl=US&ceid=US:en,"
            "https://www.investing.com/rss/news_11.rss,"
            "https://www.investing.com/rss/news_95.rss",
        ).split(",") if u.strip()
    )
    display_tz: str = os.getenv("DISPLAY_TZ", "Asia/Tashkent")

    # автоторговля на счетах подписчиков через MetaApi (metaapi.cloud); без токена функция выключена
    metaapi_token: str = os.getenv("METAAPI_TOKEN", "")
    metaapi_region: str = os.getenv("METAAPI_REGION", "")           # пусто — регион по умолчанию MetaApi
    autotrade_demo_only: bool = os.getenv("AUTOTRADE_DEMO_ONLY", "1") not in ("0", "false", "no", "")
    autotrade_risk_pct: float = float(os.getenv("AUTOTRADE_RISK_PCT", os.getenv("LOT_RISK_PCT", "2")))
    autotrade_max_lot: float = float(os.getenv("AUTOTRADE_MAX_LOT", "1"))
    autotrade_symbol: str = os.getenv("AUTOTRADE_SYMBOL", "")       # пусто — бот сам находит XAUUSD/GOLD у брокера
    # автоторговля платная: цена в Telegram Stars за AUTOTRADE_DAYS дней (1500 ⭐ ≈ $30 для подписчика)
    autotrade_price_stars: int = int(os.getenv("AUTOTRADE_PRICE_STARS", "1500"))
    autotrade_price_usd: str = os.getenv("AUTOTRADE_PRICE_USD", "30")  # только для текста «≈ $30»
    autotrade_days: int = int(os.getenv("AUTOTRADE_DAYS", "30"))
    # 1 — анализировать рынок по свечам и цене с подключённого в боте счёта админа (через MetaApi), а
    # Twelve Data / goldapi — запасной источник, на который бот переключается сразу, если MetaApi не ответил
    market_from_broker: bool = os.getenv("MARKET_FROM_BROKER", "1") not in ("0", "false", "no", "")


config = Config()
