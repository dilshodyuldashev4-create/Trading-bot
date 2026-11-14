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
