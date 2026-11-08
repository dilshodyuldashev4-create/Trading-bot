"""Экономический календарь (CPI, NFP, FOMC…) и влияние на золото/доллар."""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiohttp

from .db import DB
from .i18n import t

log = logging.getLogger(__name__)

FEEDS = (
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
)

# (шаблон, «рост показателя хорош для доллара?», ключ пояснения в i18n)
RULES = [
    (r"non-farm|nfp", True, "rule_nfp"),
    (r"unemployment rate", False, "rule_unemp"),
    (r"unemployment claims|jobless", False, "rule_claims"),
    (r"\bcpi\b|inflation", True, "rule_cpi"),
    (r"\bpce\b", True, "rule_pce"),
    (r"\bppi\b", True, "rule_ppi"),
    (r"federal funds rate|fomc statement|interest rate", True, "rule_rate"),
    (r"fomc|powell|fed chair", None, "rule_fomc"),
    (r"\bgdp\b", True, "rule_gdp"),
    (r"retail sales", True, "rule_retail"),
    (r"ism|pmi", True, "rule_pmi"),
    (r"jolts|job openings|adp", True, "rule_jobs"),
    (r"consumer sentiment|consumer confidence", True, "rule_sent"),
]


def _num(s: str | None) -> float | None:
    if not s:
        return None
    m = re.search(r"-?\d+(\.\d+)?", s.replace(",", ""))
    if not m:
        return None
    v = float(m.group())
    return v * {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(s.strip()[-1:].upper(), 1)


def impact_text(title: str, forecast: str | None, actual: str | None, lang: str = "ru") -> str:
    for pat, good_for_usd, key in RULES:
        if re.search(pat, title, re.I):
            a, f = _num(actual), _num(forecast)
            if good_for_usd is not None and a is not None and f is not None and a != f:
                usd_up = (a > f) == good_for_usd
                verdict = t(lang, "fact_above" if a > f else "fact_below") + \
                    " → " + t(lang, "usd_up" if usd_up else "usd_down")
                return t(lang, "verdict", v=verdict)
            return t(lang, key)
    return t(lang, "impact_default")


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


async def render(db: DB, tz: str, days: int = 3, lang: str = "ru") -> str:
    now = datetime.now(timezone.utc)
    z = ZoneInfo(tz)
    past = await db.events_between(now - timedelta(days=days), now)
    future = await db.events_between(now, now + timedelta(days=days))

    def line(e: dict) -> str:
        tm = datetime.fromisoformat(e["ts"]).astimezone(z)
        star = "🔴" if e["impact"] == "High" else "🟠"
        nums = " | ".join(x for x in (
            t(lang, "n_fact", v=e["actual"]) if e["actual"] else "",
            t(lang, "n_forecast", v=e["forecast"]) if e["forecast"] else "",
            t(lang, "n_prev", v=e["previous"]) if e["previous"] else "") if x)
        return (f"{star} <b>{tm:%d.%m %H:%M}</b> {html.escape(e['title'])}\n"
                f"   {nums + chr(10) + '   ' if nums else ''}{impact_text(e['title'], e['forecast'], e['actual'], lang)}")

    parts = [t(lang, "cal_head", tz=tz)]
    parts.append(t(lang, "cal_next"))
    parts += [line(e) for e in future] or [t(lang, "cal_none_next")]
    parts.append(t(lang, "cal_past"))
    parts += [line(e) for e in reversed(past)] or [t(lang, "cal_none_past")]
    parts.append(t(lang, "cal_legend"))
    return "\n".join(parts)
