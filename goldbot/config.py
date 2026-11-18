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
    # фиксация части прибыли (reports/manage_research.md): цена прошла PARTIAL_R стопов — закрыть PARTIAL_PCT %
    # позиции и перенести стоп остатка в безубыток; тейк остатка — FINAL_TP_R стопов (PARTIAL_R=0 — выключено,
    # тогда тейк по TP_ATR / TP_PIPS как раньше)
    partial_r: float = float(os.getenv("PARTIAL_R", "1"))
    partial_pct: float = float(os.getenv("PARTIAL_PCT", "50"))
    final_tp_r: float = float(os.getenv("FINAL_TP_R", "3"))
    # 1 — закрывать сделку в прибыли, когда стратегия бота даёт сигнал в обратную сторону (разворот)
    reversal_close: bool = os.getenv("REVERSAL_CLOSE", "1") not in ("0", "false", "no", "")
    reversal_min_pips: float = float(os.getenv("REVERSAL_MIN_PIPS", "10"))
    # тренд или боковик (reports/ideas_research.md): стратегии пробоя ADX_KEYS не дают сигнал подписчикам и
    # на обычные счета, когда ADX(14) их таймфрейма ≥ ADX_MAX (рынок уже разогнан). На проп-счетах — как раньше:
    # такой сигнал торгуется только там (по симуляции челленджей фильтр на проп-счетах хуже). 0 — выключено
    adx_max: float = float(os.getenv("ADX_MAX", "25"))
    adx_keys: tuple[str, ...] = tuple(
        x.strip() for x in os.getenv("ADX_KEYS", "squeeze,donchian").split(",") if x.strip())
    # свечной анализ (reports/candle_research.md): пин-бар H1 против сигнала на последних CANDLE_PIN_HOURS
    # закрытых свечах H1 (молот на дне — не продаём, падающая звезда на вершине — не покупаем). 0 — выключено
    candle_pin_hours: int = int(os.getenv("CANDLE_PIN_HOURS", "2"))
    # две стратегии согласны (reports/profit_research.md): другая стратегия дала сигнал в ту же сторону за
    # последние CONFLUENCE_MIN минут — лот × CONFLUENCE_STRONG, иначе × CONFLUENCE_SINGLE (обычные счета и лот
    # в сигнале; проп-счета — как раньше). 1 и 1 — выключено
    confluence_min: int = int(os.getenv("CONFLUENCE_MIN", "60"))
    confluence_single: float = float(os.getenv("CONFLUENCE_SINGLE", "0.75"))
    confluence_strong: float = float(os.getenv("CONFLUENCE_STRONG", "1.5"))
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
    # и в этом режиме не входить за NEWS_HOT_BEFORE минут до выхода новости и NEWS_HOT_AFTER минут после
    news_hot_before: int = int(os.getenv("NEWS_HOT_BEFORE", "10"))
    news_hot_after: int = int(os.getenv("NEWS_HOT_AFTER", "15"))
    # утренний разбор рынка в это местное время (пн–пт); пусто — выключен
    morning_review: str = os.getenv("MORNING_REVIEW", "08:00")
    # итоги недели всем в воскресенье в это местное время; пусто — выключено
    weekly_report: str = os.getenv("WEEKLY_REPORT", "12:00")
    # админам: сообщения об ошибках бота (не чаще раза в ALERT_REPEAT_MIN минут на одну и ту же ошибку),
    # о том, что рынок не проверяется дольше ALERT_STALL_MIN минут, и о перезапуске
    admin_alerts: bool = os.getenv("ADMIN_ALERTS", "1") not in ("0", "false", "no", "")
    alert_repeat_min: int = int(os.getenv("ALERT_REPEAT_MIN", "30"))
    alert_stall_min: int = int(os.getenv("ALERT_STALL_MIN", "5"))
    # нет связи с Telegram дольше ALERT_TG_MIN минут — админу одно сообщение, когда связь вернётся
    # (короткие обрывы бот переживает сам и о них не пишет)
    alert_tg_min: int = int(os.getenv("ALERT_TG_MIN", "5"))
    # прокси для связи с Telegram, если хостинг или провайдер её режет: http://user:pass@host:port
    # или socks5://user:pass@host:port. Пусто — напрямую
    telegram_proxy: str = os.getenv("TELEGRAM_PROXY", "").strip()
    # копия базы каждый день в BACKUP_TIME (местное время): в папку backups рядом с базой (хранится BACKUP_KEEP
    # штук) и файлом админам в Telegram (BACKUP_TO_ADMIN=0 — не присылать); пусто — выключено
    backup_time: str = os.getenv("BACKUP_TIME", "03:00")
    backup_keep: int = int(os.getenv("BACKUP_KEEP", "7"))
    backup_to_admin: bool = os.getenv("BACKUP_TO_ADMIN", "1") not in ("0", "false", "no", "")

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
    # защита обычного счёта от плохих дней (reports/day_guard_research.md), день — по времени сервера (PROP_DAY_TZ):
    # после AUTOTRADE_DAY_LOSSES Stop Loss за день — до завтра без новых сделок (0 — выкл.); AUTOTRADE_DAY_SIDE=1 —
    # за день только в сторону первой сделки дня; баланс ниже своего максимума на AUTOTRADE_DD_PCT % — риск ×
    # AUTOTRADE_DD_MULT, пока не вернётся (0 — выкл.)
    autotrade_day_losses: int = int(os.getenv("AUTOTRADE_DAY_LOSSES", "4"))
    autotrade_day_side: bool = os.getenv("AUTOTRADE_DAY_SIDE", "0") not in ("0", "false", "no", "")
    autotrade_dd_pct: float = float(os.getenv("AUTOTRADE_DD_PCT", "0"))
    autotrade_dd_mult: float = float(os.getenv("AUTOTRADE_DD_MULT", "0.5"))
    # проп-счета FundedNext, всё в % от размера счёта: риск на сделку и на сильный сигнал (больше PROP_MAX_TRADE_PCT ≤ 1 %
    # бот не ставит), за день все сделки вместе — не больше PROP_RISK_CAP ≤ 3 %, подушка до лимитов
    # FundedNext (ближе — бот закрывает сделки и останавливается), что закрывать у лимита:
    # all — всё на счёте / bot — только сделки бота / none — ничего
    prop_risk_pct: float = float(os.getenv("PROP_RISK_PCT", "0.5"))
    prop_strong_risk_pct: float = float(os.getenv("PROP_STRONG_RISK_PCT", "1"))  # сильный сигнал
    prop_max_trade_pct: float = min(float(os.getenv("PROP_MAX_TRADE_PCT", "1")), 1.0)
    prop_risk_cap: float = min(float(os.getenv("PROP_RISK_CAP", "3")), 3.0)
    prop_guard_pct: float = float(os.getenv("PROP_GUARD_PCT", "0.5"))
    prop_max_lot: float = float(os.getenv("PROP_MAX_LOT", "5"))
    prop_close: str = os.getenv("PROP_CLOSE", "all")
    prop_day_tz: str = os.getenv("PROP_DAY_TZ", "Europe/Athens")   # полночь сервера FundedNext
    # защита проп-счёта (см. reports/challenge_research.md): после стольких Stop Loss за день — до завтра без новых
    # сделок (0 — выкл.); баланс ниже размера счёта на PROP_DD_PCT % — риск × PROP_DD_MULT (0 — выкл.)
    prop_day_losses: int = int(os.getenv("PROP_DAY_LOSSES", "1"))
    prop_dd_pct: float = float(os.getenv("PROP_DD_PCT", "2"))
    prop_dd_mult: float = float(os.getenv("PROP_DD_MULT", "0.25"))
    # тейк проп-счёта в стопах, когда включена фиксация части (PARTIAL_R): 1.5 — как раньше (3 ATR при стопе 2 ATR).
    # Фиксация, безубыток и закрытие при развороте на проп-счетах не делаются — по симуляции челленджей с ними хуже
    prop_tp_r: float = float(os.getenv("PROP_TP_R", "1.5"))
    # 1 — на проп-счетах тоже фиксация части, безубыток и закрытие при развороте (тогда PROP_TP_R не используется)
    prop_partial: bool = os.getenv("PROP_PARTIAL", "0") not in ("0", "false", "no", "")
    # прогноз челленджа: медиана дней до цели этапа по симуляции (reports/challenge_research.md, обе защиты)
    # в профиле проп-счёта и сообщения, когда пройдено 50 % и 90 % цели
    prop_milestones: bool = os.getenv("PROP_MILESTONES", "1") not in ("0", "false", "no", "")
    # кнопка «Регистрация в FundedNext» и промокод на скидку при первой покупке
    fundednext_url: str = os.getenv("FUNDEDNEXT_URL", "https://fundednext.com")
    fundednext_code: str = os.getenv("FUNDEDNEXT_CODE", "REFHGUTBT")
    fundednext_discount: str = os.getenv("FUNDEDNEXT_DISCOUNT", "5%")
    # 1 — анализировать рынок по свечам и цене с подключённого в боте счёта админа (через MetaApi), а
    # Twelve Data / goldapi — запасной источник, на который бот переключается сразу, если MetaApi не ответил
    market_from_broker: bool = os.getenv("MARKET_FROM_BROKER", "1") not in ("0", "false", "no", "")
    # защита от широкого спреда: спред у брокера больше AUTOTRADE_MAX_SPREAD_PCT % стопа — бот ждёт до
    # AUTOTRADE_SPREAD_WAIT секунд, пока он станет нормальным, иначе сделку на этом счёте не открывает (0 — выкл.)
    autotrade_max_spread_pct: float = float(os.getenv("AUTOTRADE_MAX_SPREAD_PCT", "10"))
    autotrade_spread_wait: int = int(os.getenv("AUTOTRADE_SPREAD_WAIT", "60"))
    # сверка счетов: раз в столько секунд бот сверяет сделки на счетах с сигналами (0 — выкл.)
    reconcile_sec: int = int(os.getenv("RECONCILE_SEC", "60"))
    # живая карточка: сигнал у подписчика обновляется (ход сделки, фиксация, итог) раз в LIVE_CARD_MIN минут
    live_card: bool = os.getenv("LIVE_CARD", "1") not in ("0", "false", "no", "")
    live_card_min: int = int(os.getenv("LIVE_CARD_MIN", "5"))
    # ссылка на независимую статистику счёта (Myfxbook и т.п.) — кнопка в «Статистика» (пусто — нет кнопки)
    myfxbook_url: str = os.getenv("MYFXBOOK_URL", "")
    # Telegram-канал: туда же уходит всё, что получают подписчики (сигналы, итоги, отчёты, новости).
    # Обычно задавать не нужно: добавьте бота админом в канал, и он подключит его сам (/channel).
    # Можно указать вручную: @имя_канала или числовой ID (-100…). CHANNEL_LANG — язык постов: ru, en, uz
    channel_id: str = os.getenv("CHANNEL_ID", "")
    channel_lang: str = os.getenv("CHANNEL_LANG", "ru")


config = Config()
