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

log = logging.getLogger(__name__)

PRE_ALERT = timedelta(minutes=15)
RESULT_WINDOW = timedelta(hours=2)      # сколько ждём появления факта после выхода
RETRY_EVERY = timedelta(minutes=3)

FetchActual = Callable[[dict], Awaitable[str | None]]


def _when(e: dict, tz: str) -> str:
    return datetime.fromisoformat(e["ts"]).astimezone(ZoneInfo(tz)).strftime("%d.%m %H:%M")


def pre_alert_text(e: dict, tz: str) -> str:
    nums = " | ".join(x for x in (f"прогноз <b>{e['forecast']}</b>" if e["forecast"] else "",
                                  f"пред. {e['previous']}" if e["previous"] else "") if x)
    return (f"⏰ <b>Через 15 минут важная новость США</b>\n\n"
            f"🔴 {html.escape(e['title'])} — {_when(e, tz)}\n"
            f"{nums + chr(10) if nums else ''}"
            f"💡 {impact_text(e['title'], e['forecast'], None)}\n\n"
            f"⚠️ Возможны резкие движения золота, будьте осторожны с входами.")


def result_text(e: dict, actual: str, tz: str) -> str:
    rows = [f"📊 Факт: <b>{html.escape(actual)}</b>"]
    if e["forecast"]:
        rows.append(f"🎯 Прогноз: {e['forecast']}")
    if e["previous"]:
        rows.append(f"⏮ Предыдущее: {e['previous']}")
    return (f"🚨 <b>Вышла новость: {html.escape(e['title'])}</b> ({_when(e, tz)})\n\n"
            + "\n".join(rows) + "\n\n"
            f"💡 {impact_text(e['title'], e['forecast'], actual)}")


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


async def process(db: DB, tz: str, send_all: Callable[[str], Awaitable[None]],
                  fetch_actual: FetchActual, now: datetime | None = None) -> None:
    """Один проход: шлёт предупреждения и результаты, которые пора отправить."""
    now = now or datetime.now(timezone.utc)
    events = [e for e in await db.events_between(now - RESULT_WINDOW, now + PRE_ALERT)
              if e["impact"] == "High"]
    for e in events:
        ts = datetime.fromisoformat(e["ts"])
        if now < ts:
            key = f"alert_pre:{e['key']}"
            if not await db.get_kv(key):
                await db.set_kv(key, "1")
                await send_all(pre_alert_text(e, tz))
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
        await send_all(result_text(e, actual, tz))
