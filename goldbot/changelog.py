"""Что нового в каждой версии бота — и рассылка об этом подписчикам.

КАК ДОБАВИТЬ НОВУЮ ВЕРСИЮ: допишите запись В НАЧАЛО списка RELEASES —
новый номер версии и по пунктам, что появилось, на каждом языке бота (ru, en, uz).
После `git pull` и `docker compose up -d --build` бот один раз пришлёт админу
готовое сообщение (логотип + список новинок) с кнопками «Отправить всем» /
«Не отправлять». Подписчики получат его только после нажатия «Отправить всем».
Отправить последнее обновление можно и позже: /admin → «🆕 Обновление».
Обычный перезапуск или падение бота не присылают предложение повторно, а одну
версию нельзя случайно разослать дважды.
Если обновление без новых функций (мелкий фикс) — новую запись не добавляйте.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .i18n import DEFAULT, norm

log = logging.getLogger(__name__)

LOGO = Path(__file__).parent / "assets" / "logo.jpg"
CAPTION_LIMIT = 1024  # подпись к фото в Telegram

RELEASES: list[dict] = [
    {
        "version": "2026-11-24.4",
        "ru": [
            "🛡 Риск по умолчанию снижен с 2 % до 1 % на сделку: лот в сигналах и в автоторговле стал вдвое меньше. "
            "Прибыль меньше, но и просадки вдвое мельче",
        ],
        "en": [
            "🛡 Default risk lowered from 2% to 1% per trade: the lot in signals and in auto-trading is now half as big. "
            "Smaller profit, but drawdowns are half as deep",
        ],
        "uz": [
            "🛡 Standart risk savdo uchun 2 % dan 1 % gacha kamaytirildi: signallar va avtosavdodagi lot ikki baravar kichik. "
            "Foyda kamroq, lekin pasayishlar ham ikki baravar kichik",
        ],
    },
    {
        "version": "2026-11-24.3",
        "ru": [
            "🏆 Новая кнопка «Сигналы для проп-фирм»: выберите тип счёта, этап (челлендж 1, 2 или финансируемый) "
            "и размер счёта — бот будет присылать отдельные проп-сигналы с лотом и риском по вашему счёту",
            "⛔️ После первого стопа за день проп-сигналов до полуночи FundedNext больше нет — так бот на истории "
            "не провалил ни одного 2-Step",
            "💰 Бот сам ведёт баланс проп-счёта и напоминает, сколько осталось до цели, до дневного и общего лимита "
            "и сколько рисковать на следующую сделку. Обычные сигналы можно отключить, чтобы не путаться",
        ],
        "en": [
            "🏆 New button “Prop firm signals”: pick your account type, stage (challenge 1, 2 or funded) and size — "
            "the bot sends separate prop signals with the lot and risk sized to your account",
            "⛔️ After the first stop of the day there are no more prop signals until FundedNext midnight — with this "
            "rule the bot failed no 2-Step in history",
            "💰 The bot tracks your prop balance and reminds you how far you are from the target, the daily and "
            "overall limits and how much to risk on the next trade. Regular signals can be turned off",
        ],
        "uz": [
            "🏆 Yangi tugma «Prop-firma signallari»: hisob turi, bosqich (challenge 1, 2 yoki moliyalashtirilgan) "
            "va hajmni tanlang — bot hisobingizga mos lot va risk bilan alohida prop-signallar yuboradi",
            "⛔️ Kunning birinchi stopidan keyin FundedNext yarim tunigacha prop-signal boʻlmaydi — shu qoida bilan "
            "bot tarixda birorta ham 2-Step ni boy bermagan",
            "💰 Bot prop-hisob balansini oʻzi yuritadi va maqsad, kunlik va umumiy limitgacha qancha qolganini hamda "
            "keyingi bitimda qancha risk qilishni eslatadi. Oddiy signallarni oʻchirib qoʻyish mumkin",
        ],
    },
    {
        "version": "2026-11-24.2",
        "ru": [
            "📊 Новая стратегия: объёмный осциллятор Klinger на H4 по дневному тренду. "
            "На истории 2023–2026 прибыль бота выросла с +613 % до +660 %, а просадка стала меньше",
        ],
        "en": [
            "📊 New strategy: Klinger volume oscillator on H4 with the daily trend. "
            "On 2023–2026 history the bot's profit grew from +613% to +660% with a smaller drawdown",
        ],
        "uz": [
            "📊 Yangi strategiya: kunlik trend boʻyicha H4 da Klinger hajm ostsillyatori. "
            "2023–2026 tarixida bot foydasi +613 % dan +660 % gacha oshdi, pasayish esa kamaydi",
        ],
    },
    {
        "version": "2026-11-24.1",
        "ru": [
            "📊 Новая стратегия: пересечение адаптивной средней KAMA на H4 по дневному тренду. "
            "На истории 2023–2026 прибыль бота выросла с +583 % до +613 %",
        ],
        "en": [
            "📊 New strategy: KAMA adaptive moving average cross on H4 with the daily trend. "
            "On 2023–2026 history the bot's profit grew from +583% to +613%",
        ],
        "uz": [
            "📊 Yangi strategiya: kunlik trend boʻyicha H4 da KAMA moslashuvchan oʻrtachasi kesishishi. "
            "2023–2026 tarixida bot foydasi +583 % dan +613 % gacha oshdi",
        ],
    },
    {
        "version": "2026-11-18.2",
        "ru": [
            "📊 Новая стратегия: пробой максимума или минимума последних 5 дней по дневному тренду. "
            "На истории 2023–2026 прибыль бота выросла с +517 % до +583 %",
        ],
        "en": [
            "📊 New strategy: breakout of the last 5 days' high or low with the daily trend. "
            "On 2023–2026 history the bot's profit grew from +517% to +583%",
        ],
        "uz": [
            "📊 Yangi strategiya: kunlik trend boʻyicha oxirgi 5 kunning maksimumi yoki minimumini yorib oʻtish. "
            "2023–2026 tarixida bot foydasi +517 % dan +583 % gacha oshdi",
        ],
    },
    {
        "version": "2026-11-18.1",
        "ru": [
            "📊 Две новые стратегии: пробой азиатского диапазона на Лондоне и пробой канала Дончиана 100 часов "
            "по дневному тренду. На истории 2023–2026 прибыль бота выросла с +359 % до +517 %",
        ],
        "en": [
            "📊 Two new strategies: Asian range breakout in London and a 100-hour Donchian channel breakout "
            "with the daily trend. On 2023–2026 history the bot's profit grew from +359% to +517%",
        ],
        "uz": [
            "📊 Ikki yangi strategiya: Londonda Osiyo diapazonini yorib oʻtish va kunlik trend boʻyicha 100 soatlik "
            "Donchian kanalini yorib oʻtish. 2023–2026 tarixida bot foydasi +359 % dan +517 % gacha oshdi",
        ],
    },
    {
        "version": "2026-11-17.3",
        "ru": [
            "🏆 FundedNext: риск на одну сделку теперь не больше 1 % счёта (обычно 0.5 %), на все открытые вместе — "
            "не больше 1.5 %. Даже несколько стопов подряд не доводят до лимитов FundedNext",
        ],
        "en": [
            "🏆 FundedNext: risk per trade is now at most 1% of the account (usually 0.5%), all open trades together "
            "at most 1.5%. Even several stops in a row do not reach the FundedNext limits",
        ],
        "uz": [
            "🏆 FundedNext: bitta savdoga xavf endi hisobning 1 % dan oshmaydi (odatda 0.5 %), barcha ochiq savdolar "
            "birga — 1.5 % dan oshmaydi. Ketma-ket bir nechta stop ham FundedNext limitlariga yetkazmaydi",
        ],
    },
    {
        "version": "2026-11-17.2",
        "ru": [
            "📈 Пробои больше не входят, когда рынок уже сильно разогнан: на истории так меньше лишних стопов",
            "💪 Сильный сигнал: если две стратегии согласны, лот больше, одиночный сигнал — меньше",
            "🃏 Живая карточка: сигнал сам обновляется — ход сделки, фиксация части, итог",
            "🛡 Автоторговля не входит при слишком широком спреде и раз в минуту проверяет сделки на счетах",
            "🏆 FundedNext: в профиле видно, сколько цели этапа уже набрано, и сообщения на 50 % и 90 %",
        ],
        "en": [
            "📈 Breakouts no longer enter when the market is already overextended: fewer needless stops on history",
            "💪 Strong signal: when two strategies agree the lot is bigger, a single signal uses a smaller lot",
            "🃏 Live card: the signal updates itself with the trade progress, partial take and result",
            "🛡 Auto trading skips entries at a too wide spread and checks the trades on accounts every minute",
            "🏆 FundedNext: the profile shows how much of the phase target is done, plus messages at 50% and 90%",
        ],
        "uz": [
            "📈 Bozor juda tezlashganda breakout strategiyalari kirmaydi: tarixda ortiqcha stoplar kamaydi",
            "💪 Kuchli signal: ikki strategiya bir xil boʻlsa lot kattaroq, yakka signalda kichikroq",
            "🃏 Jonli karta: signal oʻzi yangilanadi — bitim holati, qisman olish va natija",
            "🛡 Avtosavdo spred juda keng boʻlsa kirmaydi va har daqiqada hisoblardagi bitimlarni tekshiradi",
            "🏆 FundedNext: profilda bosqich maqsadining qancha qismi bajarilgani va 50 % hamda 90 % da xabar",
        ],
    },
    {
        "version": "2026-11-17",
        "ru": [
            "💰 Фиксация прибыли: когда цена проходит столько же, сколько до стопа, бот пишет «закройте половину "
            "и перенесите стоп в безубыток», остаток идёт к дальнему тейку",
            "🔄 Если начинается разворот (сигнал в обратную сторону), бот пишет закрыть сделку в прибыли",
            "🤖 На счетах автоторговли бот делает всё это сам",
            "📅 Каждое воскресенье — итоги недели с картинкой",
        ],
        "en": [
            "💰 Profit taking: when price has moved as far as the stop distance, the bot says “close half and move "
            "the stop to breakeven”, the rest goes to a farther take profit",
            "🔄 If a reversal starts (a signal in the opposite direction), the bot says to close the trade in profit",
            "🤖 On auto trading accounts the bot does all of this itself",
            "📅 Every Sunday: weekly results with a picture",
        ],
        "uz": [
            "💰 Foydani olish: narx stopgacha boʻlgan masofaga yetganda bot «yarmini yoping va stopni zararsizlikka "
            "oʻtkazing» deb yozadi, qolgani uzoqroq takega boradi",
            "🔄 Burilish boshlansa (teskari signal), bot bitimni foyda bilan yopishni yozadi",
            "🤖 Avtosavdo hisoblarida bot bularning hammasini oʻzi qiladi",
            "📅 Har yakshanba — rasmli hafta natijalari",
        ],
    },
    {
        "version": "2026-11-14.2",
        "ru": [
            "➕ Можно подключить сколько угодно счетов: обычные у брокера и проп-счета FundedNext",
            "💳 Каждый счёт оплачивается отдельно, у каждого своя дата оплаты и свои кнопки "
            "«Пауза», «Продлить» и «Отключить» в «Автоторговле»",
        ],
        "en": [
            "➕ Connect as many accounts as you like: regular broker accounts and FundedNext prop accounts",
            "💳 Each account is paid separately and has its own paid-until date and its own "
            "“Pause”, “Extend” and “Disconnect” buttons in “Auto trading”",
        ],
        "uz": [
            "➕ Istalgancha hisob ulash mumkin: brokerdagi oddiy hisoblar va FundedNext prop hisoblari",
            "💳 Har bir hisob alohida to‘lanadi, har birining o‘z to‘lov sanasi va «Avtosavdo»da "
            "o‘z «Pauza», «Uzaytirish» va «Uzish» tugmalari bor",
        ],
    },
    {
        "version": "2026-11-14",
        "ru": [
            "🏆 Отдельная кнопка «FundedNext» в меню: бот торгует на проп-счёте по правилам FundedNext "
            "(риск на сделку, дневной стоп, учёт этапов челленджа)",
            "🔁 В «Автоторговле» можно переключаться между обычным и проп-счётом",
            "📰 Сигналы с учётом свежих новостей: бот не входит в рынок в момент выхода новости",
        ],
        "en": [
            "🏆 A separate “FundedNext” button in the menu: the bot trades your prop account by FundedNext rules "
            "(risk per trade, daily stop, challenge phase tracking)",
            "🔁 In “Auto trading” you can switch between your regular and prop account",
            "📰 Signals take fresh news into account: no entries at the moment a news release comes out",
        ],
        "uz": [
            "🏆 Menyuda alohida «FundedNext» tugmasi: bot prop hisobingizda FundedNext qoidalari bo‘yicha savdo qiladi "
            "(har bir bitim riski, kunlik stop, challenge bosqichlarini kuzatish)",
            "🔁 «Avtosavdo» bo‘limida oddiy va prop hisob o‘rtasida almashish mumkin",
            "📰 Signallar yangi yangiliklarni hisobga oladi: yangilik chiqqan paytda bot bozorga kirmaydi",
        ],
    },
]

HEAD = {
    "ru": "🚀 <b>XAUUSD GOLD — новая версия бота!</b>\n\nЧто нового:",
    "en": "🚀 <b>XAUUSD GOLD — a new version of the bot!</b>\n\nWhat's new:",
    "uz": "🚀 <b>XAUUSD GOLD — botning yangi versiyasi!</b>\n\nNimalar yangi:",
}
FOOT = {
    "ru": "👉 Чтобы пользоваться новыми функциями, нажмите /start",
    "en": "👉 To use the new features, press /start",
    "uz": "👉 Yangi funksiyalardan foydalanish uchun /start ni bosing",
}


def latest() -> dict | None:
    return RELEASES[0] if RELEASES else None


def release_text(release: dict, lang: str | None) -> str:
    lang = norm(lang)
    items = release.get(lang) or release[DEFAULT]
    lines = "\n".join(f"• {x}" for x in items)
    return f"{HEAD.get(lang, HEAD[DEFAULT])}\n\n{lines}\n\n{FOOT.get(lang, FOOT[DEFAULT])}"


def find(version: str) -> dict | None:
    return next((r for r in RELEASES if r["version"] == version), None)


def offered_key() -> str:
    return "release_offered"


def sent_key(version: str) -> str:
    return f"release_sent:{version}"


async def to_offer(db) -> dict | None:
    """Новая версия, которую ещё не предлагали админу, — и сразу пометить как предложенную.

    Пометка ставится до отправки: перезапуск или падение бота не присылают предложение снова.
    """
    rel = latest()
    if not rel or await db.get_kv(offered_key()) == rel["version"]:
        return None
    await db.set_kv(offered_key(), rel["version"])
    return rel


async def claim_send(db, version: str, force: bool = False) -> bool:
    """True — можно рассылать (и версия сразу помечена как разосланная). False — уже разослана.

    Двойное нажатие кнопки или кнопка у второго админа не разошлёт одно и то же дважды.
    """
    if not force and await db.get_kv(sent_key(version)):
        return False
    await db.set_kv(sent_key(version), "1")
    return True
