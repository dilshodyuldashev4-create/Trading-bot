"""Видеокурс «от нуля до профи»: англоязычные видео с YouTube, разложенные по уровням (ru, en, uz).

Видео смотрят с автопереводом субтитров на узбекский (CC → Настройки → Субтитры → Автоперевод → O'zbek).
Каждый id сверен 26.11.2026 по странице видео или поисковому индексу YouTube; название и канал — в комментарии.
На сервере бот дополнительно проверяет видео через YouTube oEmbed (check_videos) и прячет удалённые.
Пометка tested — подход проверяли на реальной истории XAUUSD (reports/strategy_research.md и др.);
поле — короткое имя стратегии бота. Фибоначчи в тесте был в минусе, поэтому видео о нём нет.

Курс есть в двух местах: кнопка «🎓 Уроки» в чате бота (список по номерам, урок → следующий)
и раздел «Видеокурс» во вкладке «Уроки» Mini App.
"""
from __future__ import annotations

# уровни: id, иконка, название на трёх языках
LEVELS = [
    {"id": 1, "icon": "🟢", "ru": "Основы", "en": "Basics", "uz": "Asoslar"},
    {"id": 2, "icon": "🟡", "ru": "График и риск", "en": "Charts and risk", "uz": "Grafik va risk"},
    {"id": 3, "icon": "🟠", "ru": "Стратегии", "en": "Strategies", "uz": "Strategiyalar"},
    {"id": 4, "icon": "🔴", "ru": "Профессионал", "en": "Professional", "uz": "Professional"},
]


def _v(level: int, yt: str, channel: str, ru: tuple[str, str], en: tuple[str, str], uz: tuple[str, str],
       tested: str | None = None) -> dict:
    """ru/en/uz — (название, чему научит)."""
    return {"level": level, "yt": yt, "channel": channel, "tested": tested,
            "ru": {"title": ru[0], "sub": ru[1]}, "en": {"title": en[0], "sub": en[1]},
            "uz": {"title": uz[0], "sub": uz[1]}}


VIDEOS = [
    # ── 1. Основы ──
    # "Forex Trading for Beginners #4: Common Forex Trading Terminologies" — Rayner Teo
    _v(1, "WiJCR1Nvl6A", "Rayner Teo",
       ("Главные слова форекса", "Валютная пара, bid/ask, спред, лонг и шорт — словарь новичка"),
       ("Key forex terms", "Currency pair, bid/ask, spread, long and short — the beginner's dictionary"),
       ("Forexning asosiy so'zlari", "Valyuta juftligi, bid/ask, spred, long va short — yangi boshlovchi lug'ati")),
    # "Forex Pips, Lot Size, Leverage, Spread Explained for Beginners" — AB Amrani
    _v(1, "ob-1EaYeTnY", "AB Amrani",
       ("Пипсы, лоты и плечо", "Сколько стоит движение цены и почему большое плечо опасно"),
       ("Pips, lots and leverage", "What a price move is worth and why high leverage is dangerous"),
       ("Pips, lot va leverage", "Narx harakati qancha turadi va katta leverage nega xavfli")),
    # "Forex Trading for Beginners #3: When is the Best Time to Trade Forex" — Rayner Teo
    _v(1, "PYMNXfepIlc", "Rayner Teo",
       ("Когда торговать", "Азия, Лондон, Нью-Йорк: в какие часы рынок двигается сильнее"),
       ("When to trade", "Asia, London, New York: the hours when the market moves most"),
       ("Qachon savdo qilish kerak", "Osiyo, London, Nyu-York: bozor qaysi soatlarda kuchliroq harakatlanadi")),
    # "Candlestick Patterns For Beginners (The Ultimate Guide)" — Rayner Teo
    _v(1, "_McKwJrKtHM", "Rayner Teo",
       ("Японские свечи", "Как читать свечу и какие свечные модели действительно полезны"),
       ("Candlesticks", "How to read a candle and which patterns are actually useful"),
       ("Yapon shamlari", "Shamni qanday o'qish va qaysi sham modellari haqiqatan foydali")),
    # "How To Use MetaTrader 5 Mobile App (Tutorial For Beginners - Android & iPhone)"
    _v(1, "o20mdBkJCaQ", "MT5 tutorial",
       ("MetaTrader 5 на телефоне", "Как открыть сделку, поставить стоп и тейк в приложении MT5"),
       ("MetaTrader 5 on your phone", "How to open a trade and set stop and take profit in the MT5 app"),
       ("Telefonda MetaTrader 5", "MT5 ilovasida bitim ochish, stop va teyk qo'yish")),
    # "How to Trade Gold (XAUUSD)"
    _v(1, "TpKHmhDHFk0", "Gold trading",
       ("Как торговать золотом", "Чем XAUUSD отличается от валют и что двигает цену золота"),
       ("How to trade gold", "How XAUUSD differs from currencies and what moves the gold price"),
       ("Oltin savdosi", "XAUUSD valyutalardan nimasi bilan farq qiladi va oltin narxini nima harakatlantiradi")),

    # ── 2. График и риск ──
    # "Support and Resistance For Beginners (The Ultimate Guide)" — Rayner Teo
    _v(2, "nuVv0ZWUfs4", "Rayner Teo",
       ("Поддержка и сопротивление", "Где цена чаще разворачивается и как правильно рисовать уровни"),
       ("Support and resistance", "Where price tends to turn and how to draw levels properly"),
       ("Qo'llab-quvvatlash va qarshilik", "Narx qayerda ko'proq qaytadi va darajalarni to'g'ri chizish")),
    # "Market Structure for Beginners - A Simple Tutorial"
    _v(2, "kwTUJ2KtiWo", "Stock Trading for Beginners",
       ("Структура рынка", "Тренд через максимумы и минимумы: HH, HL, LH, LL"),
       ("Market structure", "Reading the trend through highs and lows: HH, HL, LH, LL"),
       ("Bozor tuzilishi", "Trendni cho'qqi va chuqurliklar orqali o'qish: HH, HL, LH, LL")),
    # "How To Draw Trendlines Like A Pro (My Secret Technique)" — Rayner Teo
    _v(2, "BONTuuxhujk", "Rayner Teo",
       ("Трендовые линии", "Как рисовать трендовую линию и не обманывать себя"),
       ("Trendlines", "How to draw a trendline without fooling yourself"),
       ("Trend chiziqlari", "Trend chizig'ini o'zingizni aldamasdan chizish")),
    # "PRICE ACTION Trading Made Simple (Full Course)" — Mind Math Money, 1 ч 12 мин
    _v(2, "tWiErAItlpY", "Mind Math Money",
       ("Price action: полный курс", "Торговля по чистому графику: уровни, свечи, тренд — всё вместе"),
       ("Price action: full course", "Trading the clean chart: levels, candles and trend together"),
       ("Price action: to'liq kurs", "Toza grafik bo'yicha savdo: darajalar, shamlar va trend birga")),
    # "How To Calculate Position Size & Risk Per Trade" — ACY Securities
    _v(2, "sp3IN6MXzVI", "ACY Securities",
       ("Размер позиции", "Как посчитать лот, чтобы стоп стоил ровно 1% счёта"),
       ("Position size", "How to size the lot so a stop costs exactly 1% of the account"),
       ("Pozitsiya hajmi", "Stop hisobning aynan 1% bo'lishi uchun lotni hisoblash")),
    # "Trading Risk Management Explained for Beginners" — Ahead of the Trade
    _v(2, "OjF8RjYqmqo", "Ahead of the Trade",
       ("Управление риском", "Почему профессионалы думают сначала об убытке, а потом о прибыли"),
       ("Risk management", "Why professionals think about the loss first and the profit second"),
       ("Riskni boshqarish", "Nega professionallar avval zarar, keyin foyda haqida o'ylaydi")),

    # ── 3. Стратегии ──
    # "The BEST Moving Average Strategy for Beginner Traders" — FxScouts
    _v(3, "sWNEwPZzF6Q", "FxScouts",
       ("Тренд по скользящим средним", "Как скользящие средние показывают тренд и когда входить по нему"),
       ("Trend with moving averages", "How moving averages show the trend and when to trade with it"),
       ("Sirpanuvchi o'rtachalar bilan trend", "Sirpanuvchi o'rtachalar trendni qanday ko'rsatadi va qachon kirish kerak")),
    # "The Turtle Trading Strategy Explained: Breakouts Made Simple" — Funded Trading Plus
    _v(3, "DMv2JwsANFY", "Funded Trading Plus",
       ("Пробой канала (черепахи)", "Знаменитая стратегия «черепах»: вход на пробое максимума за N свечей"),
       ("Channel breakout (Turtles)", "The famous Turtle strategy: enter on a break of the N-bar high"),
       ("Kanal yorib o'tishi (toshbaqalar)", "Mashhur «toshbaqalar» strategiyasi: N sham maksimumi yorilganda kirish"),
       tested="donchian"),
    # "Bollinger Band Squeeze Breakout Strategy! [Backtested]" — Trading Tact
    _v(3, "G6MVccESQqM", "Trading Tact",
       ("Сжатие Боллинджера", "Рынок затих — жди сильного выхода: пробой после сужения полос"),
       ("Bollinger squeeze", "A quiet market before a big move: the breakout after the bands narrow"),
       ("Bollinger siqilishi", "Bozor tinchidi — kuchli chiqishni kuting: polosalar torayganidan keyingi yorilish"),
       tested="squeeze"),
    # "Simple Pullback Trading Strategy That Actually Works"
    _v(3, "xLwAUF5qe7o", "Pullback strategy",
       ("Вход на откате", "Не догонять цену: ждать отката в тренде и входить по лучшей цене"),
       ("Pullback entry", "Don't chase price: wait for a pullback in the trend and enter at a better price"),
       ("Otkatda kirish", "Narxni quvmang: trenddagi otkatni kuting va yaxshiroq narxda kiring"),
       tested="rsi"),
    # "Simple Trendline Breakout Strategy for Swing Trading Explained"
    _v(3, "HksbfkkxWBw", "Trendline breakout",
       ("Пробой трендовой линии", "Подтверждение, вход и цель после пробоя линии"),
       ("Trendline breakout", "Confirmation, entry and target after a trendline break"),
       ("Trend chizig'i yorilishi", "Chiziq yorilgandan keyin tasdiq, kirish va maqsad"),
       tested="trendline"),
    # "The ULTIMATE Smart Money Concepts Guide (Full Course)" — Lewis Kelly
    _v(3, "OhE__u454wo", "Lewis Kelly",
       ("Smart Money (SMC)", "Слом структуры (BOS), ордер-блоки, имбаланс (FVG) и ликвидность — как торгуют «крупные деньги»"),
       ("Smart Money Concepts", "Break of structure, order blocks, fair value gaps and liquidity — how big money trades"),
       ("Smart Money (SMC)", "Tuzilma buzilishi (BOS), order bloklar, imbalans (FVG) va likvidlik — «katta pul» qanday savdo qiladi"),
       tested="fvg"),

    # ── 4. Профессионал ──
    # "Why Your Mind Tricks You to Remain a Losing Trader (Trading Psychology)" — Rayner Teo
    _v(4, "7wKE70sKAcU", "Rayner Teo",
       ("Психология трейдера", "Почему голова мешает зарабатывать и как держать дисциплину"),
       ("Trading psychology", "Why your mind keeps you losing and how to stay disciplined"),
       ("Treyder psixologiyasi", "Nega fikringiz pul topishga xalaqit beradi va intizomni qanday saqlash")),
    # "How to Backtest a Trading Strategy in 2026 (Step-by-Step Guide)" — Trade With Jem
    _v(4, "IqR17Bwa8aY", "Trade With Jem",
       ("Как проверить стратегию", "Бэктест шаг за шагом: стратегия без проверки — это лотерея"),
       ("How to backtest", "Step-by-step backtesting: an untested strategy is a lottery"),
       ("Strategiyani tekshirish", "Bosqichma-bosqich bektest: tekshirilmagan strategiya — lotereya")),
    # "TradingView Replay Trading & Backtesting Tutorial (2026)" — Mind Math Money
    _v(4, "DFu9yRCChKM", "Mind Math Money",
       ("Тренировка в TradingView Replay", "Прокручивайте историю свечей и тренируйтесь без риска"),
       ("Practice with TradingView Replay", "Replay past candles and practise with zero risk"),
       ("TradingView Replay'da mashq", "Shamlar tarixini aylantiring va xavfsiz mashq qiling")),
    # "How To Pass Any Prop Firm Challenge And Get Payouts (Step-By-Step FULL Course)" — Ndemazeah Godlove
    _v(4, "sfyAZe8Dyrg", "Ndemazeah Godlove",
       ("Как пройти проп-челлендж", "Правила, риск и план, чтобы получить счёт и выплаты"),
       ("How to pass a prop challenge", "Rules, risk and a plan to get funded and paid"),
       ("Prop-chellenjdan o'tish", "Hisob va to'lov olish uchun qoidalar, risk va reja")),
]

# подсказка: как включить узбекские субтитры (один и тот же текст в боте и приложении)
HINT = {
    "ru": "🇺🇿 Узбекские субтитры: в плеере нажмите ⚙️ → Субтитры → Автоперевод → O'zbek (если нет CC — сначала включите CC).",
    "en": "🇺🇿 Uzbek subtitles: in the player tap ⚙️ → Subtitles/CC → Auto-translate → Uzbek (O'zbek) (turn on CC first if needed).",
    "uz": "🇺🇿 O'zbekcha subtitr: pleyerda ⚙️ → Subtitrlar → Avtotarjima → O'zbek ni bosing (kerak bo'lsa avval CC ni yoqing).",
}

TEXTS = {
    "ru": {
        "list_head": "🎓 <b>Видеокурс: трейдинг с нуля до профи</b>\n\nЛучшие англоязычные видео трейдеров, по порядку. "
                     "Выберите номер урока, посмотрите и переходите к следующему.",
        "tested_note": "✅ — стратегия проверена ботом на реальной истории золота 2023–2026",
        "lesson_head": "🎬 <b>Урок {n} из {m}</b> · {icon} {level}",
        "tested": "✅ Проверено ботом на истории XAUUSD: этот подход входит в стратегии бота",
        "channel": "Автор: {channel}",
        "btn_prev": "◀ Урок {n}", "btn_next": "Урок {n} ▶", "btn_list": "📋 Все уроки",
        "btn_watch": "▶️ Смотреть на YouTube",
        "done": "🏆 Это последний урок. Курс пройден — теперь тренируйтесь на демо-счёте!",
    },
    "en": {
        "list_head": "🎓 <b>Video course: trading from zero to pro</b>\n\nThe best English videos by traders, in order. "
                     "Pick a lesson number, watch it, then move on to the next one.",
        "tested_note": "✅ — strategy tested by the bot on real gold history 2023–2026",
        "lesson_head": "🎬 <b>Lesson {n} of {m}</b> · {icon} {level}",
        "tested": "✅ Tested by the bot on XAUUSD history: this approach is one of the bot's strategies",
        "channel": "By: {channel}",
        "btn_prev": "◀ Lesson {n}", "btn_next": "Lesson {n} ▶", "btn_list": "📋 All lessons",
        "btn_watch": "▶️ Watch on YouTube",
        "done": "🏆 That's the last lesson. Course complete — now practise on a demo account!",
    },
    "uz": {
        "list_head": "🎓 <b>Videokurs: treyding noldan professionalgacha</b>\n\nTreyderlarning eng yaxshi inglizcha videolari, "
                     "tartib bilan. Dars raqamini tanlang, ko'ring va keyingisiga o'ting.",
        "tested_note": "✅ — strategiya bot tomonidan oltinning 2023–2026 real tarixida tekshirilgan",
        "lesson_head": "🎬 <b>{m} darsdan {n}-dars</b> · {icon} {level}",
        "tested": "✅ Bot XAUUSD tarixida tekshirgan: bu yondashuv bot strategiyalaridan biri",
        "channel": "Muallif: {channel}",
        "btn_prev": "◀ {n}-dars", "btn_next": "{n}-dars ▶", "btn_list": "📋 Barcha darslar",
        "btn_watch": "▶️ YouTube'da ko'rish",
        "done": "🏆 Bu oxirgi dars. Kurs tugadi — endi demo-hisobda mashq qiling!",
    },
}

# субтитры: включить и предпочесть узбекские (сработает, если у видео есть такая дорожка; автоперевод — по подсказке)
CC = "cc_load_policy=1&cc_lang_pref=uz&hl=uz"


# id видео, которых больше нет на YouTube (заполняет check_videos при запуске бота и раз в сутки)
MISSING: set[str] = set()


def active() -> list[dict]:
    """Видео, доступные сейчас; номера уроков идут подряд без пропусков."""
    return [v for v in VIDEOS if v["yt"] not in MISSING]


async def check_videos(session, timeout: float = 10) -> set[str]:
    """Проверяет каждое видео через oEmbed: 404/401/403 — видео удалено или скрыто, такое прячем.
    Сетевые ошибки ничего не меняют (лучше показать видео, чем спрятать из-за сбоя сети)."""
    import aiohttp
    gone = set()
    for v in VIDEOS:
        url = f"https://www.youtube.com/oembed?format=json&url=https://www.youtube.com/watch?v={v['yt']}"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status in (401, 403, 404):
                    gone.add(v["yt"])
                elif r.status != 200 and v["yt"] in MISSING:
                    gone.add(v["yt"])
        except Exception:  # noqa: BLE001
            if v["yt"] in MISSING:
                gone.add(v["yt"])
    MISSING.clear()
    MISSING.update(gone)
    return gone


def _lang(lang: str | None) -> str:
    return lang if lang in TEXTS else "ru"


def watch_url(yt: str) -> str:
    return f"https://www.youtube.com/watch?v={yt}&{CC}"


def embed_url(yt: str) -> str:
    return f"https://www.youtube-nocookie.com/embed/{yt}?{CC}&rel=0&playsinline=1&modestbranding=1"


def level(lid: int) -> dict:
    return next(x for x in LEVELS if x["id"] == lid)


def course(lang: str | None) -> dict:
    """Видеокурс для Mini App: уровни, видео (номер, id YouTube, адрес плеера), подсказка про субтитры."""
    lang = _lang(lang)
    return {"levels": [{"id": x["id"], "icon": x["icon"], "title": x[lang]} for x in LEVELS],
            "videos": [{"n": i + 1, "level": v["level"], "yt": v["yt"], "channel": v["channel"],
                        "tested": bool(v["tested"]), "title": v[lang]["title"], "sub": v[lang]["sub"],
                        "embed": embed_url(v["yt"]), "url": watch_url(v["yt"])} for i, v in enumerate(active())],
            "hint": HINT[lang]}


# ── тексты для чата бота (кнопка «🎓 Уроки») ─────────────────────────────────
def list_text(lang: str | None) -> str:
    lang = _lang(lang)
    tx, out, n = TEXTS[lang], [TEXTS[lang]["list_head"]], 0
    for lv in LEVELS:
        out.append(f"\n{lv['icon']} <b>{lv[lang]}</b>")
        for v in active():
            if v["level"] == lv["id"]:
                n += 1
                out.append(f"{n}. {v[lang]['title']}{' ✅' if v['tested'] else ''}")
    out.append(f"\n{tx['tested_note']}\n\n{HINT[lang]}")
    return "\n".join(out)


def lesson_text(lang: str | None, n: int) -> str:
    """Урок n (с 1): заголовок, чему научит, автор, ссылка — Telegram покажет превью с плеером."""
    lang = _lang(lang)
    vs = active()
    tx, v = TEXTS[lang], vs[n - 1]
    lv = level(v["level"])
    parts = [tx["lesson_head"].format(n=n, m=len(vs), icon=lv["icon"], level=lv[lang]),
             f"\n<b>{v[lang]['title']}</b>\n{v[lang]['sub']}", tx["channel"].format(channel=v["channel"])]
    if v["tested"]:
        parts.append(tx["tested"])
    parts.append(f"\n{HINT[lang]}")
    if n == len(vs):
        parts.append(f"\n{tx['done']}")
    parts.append(f"\n{watch_url(v['yt'])}")
    return "\n".join(parts)


def list_buttons(lang: str | None) -> list[list[tuple[str, str]]]:
    """Кнопки-номера по 5 в ряд: (текст, callback_data)."""
    nums = [(str(i + 1), f"vc:{i + 1}") for i in range(len(active()))]
    return [nums[i:i + 5] for i in range(0, len(nums), 5)]


def lesson_buttons(lang: str | None, n: int) -> list[list[tuple[str, str]]]:
    """Под уроком: назад / все уроки / следующий. Кнопка YouTube добавляется в боте (это url-кнопка)."""
    tx = TEXTS[_lang(lang)]
    row = []
    if n > 1:
        row.append((tx["btn_prev"].format(n=n - 1), f"vc:{n - 1}"))
    row.append((tx["btn_list"], "vc:list"))
    if n < len(active()):
        row.append((tx["btn_next"].format(n=n + 1), f"vc:{n + 1}"))
    return [row]
