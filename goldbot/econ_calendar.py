"""Экономический календарь (CPI, NFP, FOMC…) и влияние на золото/доллар."""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiohttp

from .db import DB

log = logging.getLogger(__name__)

FEEDS = (
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
)

# (шаблон, «рост показателя хорош для доллара?», пояснение)
RULES = [
    (r"non-farm|nfp", True, "Сильная занятость → ФРС дольше держит ставку → доллар ⬆️, золото ⬇️"),
    (r"unemployment rate", False, "Рост безработицы → ждут снижения ставки → доллар ⬇️, золото ⬆️"),
    (r"unemployment claims|jobless", False, "Больше заявок на пособие → слабый рынок труда → доллар ⬇️, золото ⬆️"),
    (r"\bcpi\b|inflation", True, "Инфляция выше прогноза → ставка дольше высокая → доллар ⬆️, золото ⬇️"),
    (r"\bpce\b", True, "Любимый индикатор инфляции ФРС: выше прогноза → доллар ⬆️, золото ⬇️"),
    (r"\bppi\b", True, "Цены производителей выше прогноза → доллар ⬆️, золото ⬇️"),
    (r"federal funds rate|fomc statement|interest rate", True,
     "Решение по ставке ФРС: повышение/жёсткий тон → доллар ⬆️, золото ⬇️; снижение → наоборот"),
    (r"fomc|powell|fed chair", None, "Речь ФРС: жёсткий тон → доллар ⬆️, золото ⬇️; мягкий → золото ⬆️"),
    (r"\bgdp\b", True, "Сильный ВВП → доллар ⬆️, золото ⬇️"),
    (r"retail sales", True, "Сильные продажи → доллар ⬆️, золото ⬇️"),
    (r"ism|pmi", True, "Деловая активность выше прогноза → доллар ⬆️, золото ⬇️"),
    (r"jolts|job openings|adp", True, "Больше вакансий/занятости → доллар ⬆️, золото ⬇️"),
    (r"consumer sentiment|consumer confidence", True, "Оптимизм потребителей → доллар ⬆️, золото ⬇️"),
]


def _num(s: str | None) -> float | None:
    if not s:
        return None
    m = re.search(r"-?\d+(\.\d+)?", s.replace(",", ""))
    if not m:
        return None
    v = float(m.group())
    return v * {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(s.strip()[-1:].upper(), 1)


def impact_text(title: str, forecast: str | None, actual: str | None) -> str:
    for pat, good_for_usd, text in RULES:
        if re.search(pat, title, re.I):
            a, f = _num(actual), _num(forecast)
            if good_for_usd is not None and a is not None and f is not None and a != f:
                usd_up = (a > f) == good_for_usd
                verdict = ("факт выше прогноза" if a > f else "факт ниже прогноза") + \
                    (" → доллар ⬆️, золото ⬇️" if usd_up else " → доллар ⬇️, золото ⬆️")
                return f"Итог: {verdict}"
            return text
    return "Может вызвать волатильность в долларе и золоте"


def _parse_ff(items: list[dict]) -> list[dict]:
    out = []
    for e in items:
        if e.get("country") != "USD" or e.get("impact") not in ("High", "Medium"):
            continue
        try:
            ts = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
        except (KeyError, ValueError):
            continue
        out.append({
            "key": f"{e['title']}|{ts.isoformat()}", "ts": ts.isoformat(), "country": "USD",
            "title": e["title"], "impact": e["impact"], "forecast": e.get("forecast") or "",
            "previous": e.get("previous") or "", "actual": e.get("actual") or "",
        })
    return out


async def refresh(db: DB) -> int:
    n = 0
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
        for url in FEEDS:
            try:
                async with s.get(url, headers={"User-Agent": "Mozilla/5.0 goldbot"}) as r:
                    if r.status != 200:
                        continue
                    events = _parse_ff(await r.json(content_type=None))
            except Exception as e:  # noqa: BLE001
                log.warning("calendar %s: %s", url, e)
                continue
            await db.upsert_events(events)
            n += len(events)
    return n


async def render(db: DB, tz: str, days: int = 3) -> str:
    now = datetime.now(timezone.utc)
    z = ZoneInfo(tz)
    past = await db.events_between(now - timedelta(days=days), now)
    future = await db.events_between(now, now + timedelta(days=days))

    def line(e: dict) -> str:
        t = datetime.fromisoformat(e["ts"]).astimezone(z)
        star = "🔴" if e["impact"] == "High" else "🟠"
        nums = " | ".join(x for x in (
            f"факт {e['actual']}" if e["actual"] else "",
            f"прогноз {e['forecast']}" if e["forecast"] else "",
            f"пред. {e['previous']}" if e["previous"] else "") if x)
        return (f"{star} <b>{t:%d.%m %H:%M}</b> {html.escape(e['title'])}\n"
                f"   {nums + chr(10) + '   ' if nums else ''}{impact_text(e['title'], e['forecast'], e['actual'])}")

    parts = [f"🗓 <b>Календарь новостей США</b> (время: {tz})\n"]
    parts.append("<b>⏭ Ближайшие 3 дня</b>")
    parts += [line(e) for e in future] or ["Важных новостей нет"]
    parts.append("\n<b>⏮ Прошедшие 3 дня</b>")
    parts += [line(e) for e in reversed(past)] or ["Нет данных"]
    parts.append("\n🔴 высокая важность  🟠 средняя")
    return "\n".join(parts)
