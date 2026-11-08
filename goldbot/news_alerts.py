"""Авторассылка по важным новостям США: за 15 минут до выхода и сразу после (факт vs прогноз)."""
from __future__ import annotations

import html
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from .db import DB
from .econ_calendar import impact_text
from .i18n import t

log = logging.getLogger(__name__)

PRE_ALERT = timedelta(minutes=15)
RESULT_WINDOW = timedelta(hours=2)      # сколько ждём появления факта после выхода
RETRY_EVERY = timedelta(minutes=3)

FetchActual = Callable[[dict], Awaitable[str | None]]
SendAll = Callable[[Callable[[str], str]], Awaitable[None]]


def _when(e: dict, tz: str) -> str:
    return datetime.fromisoformat(e["ts"]).astimezone(ZoneInfo(tz)).strftime("%d.%m %H:%M")


def pre_alert_text(e: dict, tz: str, lang: str = "ru") -> str:
    nums = " | ".join(x for x in (t(lang, "pre_forecast", v=e["forecast"]) if e["forecast"] else "",
                                  t(lang, "n_prev", v=e["previous"]) if e["previous"] else "") if x)
    return (t(lang, "pre_head")
            + f"🔴 {html.escape(e['title'])} — {_when(e, tz)}\n"
            f"{nums + chr(10) if nums else ''}"
            f"💡 {impact_text(e['title'], e['forecast'], None, lang)}\n\n"
            + t(lang, "pre_warn"))


def result_text(e: dict, actual: str, tz: str, lang: str = "ru") -> str:
    rows = [t(lang, "res_fact", v=html.escape(actual))]
    if e["forecast"]:
        rows.append(t(lang, "res_forecast", v=e["forecast"]))
    if e["previous"]:
        rows.append(t(lang, "res_prev", v=e["previous"]))
    return (t(lang, "res_head", title=html.escape(e["title"]), when=_when(e, tz))
            + "\n".join(rows) + "\n\n"
            f"💡 {impact_text(e['title'], e['forecast'], actual, lang)}")


async def claude_fetch_actual(e: dict, model: str) -> str | None:
    """Ищет фактическое значение показателя через Claude с веб-поиском."""
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        return None
    import anthropic

    when = datetime.fromisoformat(e["ts"]).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    prompt = (f"US economic release: \"{e['title']}\" scheduled {when}. Forecast {e['forecast'] or 'n/a'}, "
              f"previous {e['previous'] or 'n/a'}. Find the ACTUAL released value from this release "
              f"(not the previous one). Answer with one line exactly: ACTUAL: <value as published, e.g. 0.3% or 256K>. "
              f"If it is not published yet or you are not sure, answer: ACTUAL: NONE")
    client = anthropic.AsyncAnthropic()
    messages = [{"role": "user", "content": prompt}]
    try:
        for _ in range(3):  # pause_turn: продолжаем, если поиск прервался
            resp = await client.beta.messages.create(
                model=model, max_tokens=4000, output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}],
                messages=messages)
            if resp.stop_reason != "pause_turn":
                break
            messages.append({"role": "assistant", "content": resp.content})
    except anthropic.APIStatusError as err:
        log.warning("claude error %s: %s", err.status_code, err.message)
        return None
    except anthropic.APIConnectionError:
        return None
    if resp.stop_reason == "refusal":
        return None
    text = "".join(b.text for b in resp.content if b.type == "text")
    m = re.search(r"ACTUAL:\s*([^\n]+)", text)
    if not m or "NONE" in m.group(1).upper():
        return None
    return m.group(1).strip().strip(".")[:20]


async def process(db: DB, tz: str, send_all: SendAll,
                  fetch_actual: FetchActual, now: datetime | None = None) -> None:
    """Один проход: шлёт предупреждения и результаты, которые пора отправить.

    send_all получает функцию «язык → текст», чтобы каждый получил сообщение на своём языке.
    """
    now = now or datetime.now(timezone.utc)
    events = [e for e in await db.events_between(now - RESULT_WINDOW, now + PRE_ALERT)
              if e["impact"] == "High"]
    for e in events:
        ts = datetime.fromisoformat(e["ts"])
        if now < ts:
            key = f"alert_pre:{e['key']}"
            if not await db.get_kv(key):
                await db.set_kv(key, "1")
                await send_all(lambda lang, e=e: pre_alert_text(e, tz, lang))
            continue
        key = f"alert_res:{e['key']}"
        if await db.get_kv(key):
            continue
        actual = e["actual"]
        if not actual:
            tkey = f"alert_try:{e['key']}"
            last = await db.get_kv(tkey)
            if last and now - datetime.fromisoformat(last) < RETRY_EVERY:
                continue
            if now - ts < timedelta(minutes=1):
                continue  # даём цифре появиться
            await db.set_kv(tkey, now.isoformat())
            actual = await fetch_actual(e)
            if not actual:
                continue
            await db.upsert_events([{**e, "actual": actual}])
        await db.set_kv(key, "1")
        await send_all(lambda lang, e=e, a=actual: result_text(e, a, tz, lang))
