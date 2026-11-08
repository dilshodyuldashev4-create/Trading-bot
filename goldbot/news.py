"""Фундаментальные новости: RSS-ленты + краткий разбор влияния на золото и доллар через Claude."""
from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import time
from calendar import timegm

import aiohttp
import feedparser

log = logging.getLogger(__name__)

KEYWORDS = re.compile(
    r"\b(gold|xau|bullion|precious|fed|fomc|powell|dollar|usd|dxy|treasury|yield|inflation|cpi|pce|"
    r"payroll|nfp|jobs|unemployment|rate cut|rate hike|tariff|geopolit|war|sanction|recession|gdp)\b",
    re.I)

PROMPT = """Ты аналитик рынка золота. Ниже свежие новостные заголовки (с кратким текстом).
Выбери до 7 самых важных для золота (XAUUSD) и доллара США. Для каждой напиши по-русски одну-две
короткие строки в формате:

• <суть новости простыми словами> — Золото: ⬆️/⬇️/➡️, Доллар: ⬆️/⬇️/➡️. <почему, коротко>

В конце одной строкой общий вывод: куда, скорее всего, давит фон на золото сегодня.
Без вступлений, без markdown-заголовков. Не выдумывай факты, которых нет в заголовках."""


class NewsService:
    def __init__(self, feeds: tuple[str, ...], model: str, cache_seconds: int = 1200):
        self.feeds, self.model, self.cache_seconds = feeds, model, cache_seconds
        self._cache: tuple[float, str] | None = None
        self._lock = asyncio.Lock()

    async def _fetch_feed(self, s: aiohttp.ClientSession, url: str) -> list[dict]:
        try:
            async with s.get(url, headers={"User-Agent": "Mozilla/5.0 goldbot"}) as r:
                raw = await r.read()
        except Exception as e:  # noqa: BLE001
            log.warning("feed %s: %s", url, e)
            return []
        out = []
        for e in feedparser.parse(raw).entries:
            ts = e.get("published_parsed") or e.get("updated_parsed")
            out.append({
                "title": e.get("title", "").strip(),
                "summary": re.sub(r"<[^>]+>", "", e.get("summary", ""))[:300].strip(),
                "ts": timegm(ts) if ts else time.time(),
            })
        return out

    async def headlines(self, hours: int = 24, limit: int = 25) -> list[dict]:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            groups = await asyncio.gather(*(self._fetch_feed(s, u) for u in self.feeds))
        cutoff = time.time() - hours * 3600
        seen, items = set(), []
        for it in sorted((x for g in groups for x in g), key=lambda x: -x["ts"]):
            key = it["title"].lower()
            if it["ts"] < cutoff or key in seen or not KEYWORDS.search(it["title"] + " " + it["summary"]):
                continue
            seen.add(key)
            items.append(it)
        return items[:limit]

    async def _summarize(self, items: list[dict]) -> str | None:
        if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
            return None
        import anthropic

        text = "\n".join(f"- {i['title']}. {i['summary']}" for i in items)
        client = anthropic.AsyncAnthropic()
        try:
            resp = await client.beta.messages.create(
                model=self.model,
                max_tokens=4000,
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=PROMPT,
                messages=[{"role": "user", "content": text}],
            )
        except anthropic.APIStatusError as e:
            log.warning("claude error %s: %s", e.status_code, e.message)
            return None
        except anthropic.APIConnectionError:
            log.warning("claude connection error")
            return None
        if resp.stop_reason == "refusal":
            return None
        return "".join(b.text for b in resp.content if b.type == "text").strip() or None

    async def digest(self) -> str:
        async with self._lock:
            if self._cache and time.time() - self._cache[0] < self.cache_seconds:
                return self._cache[1]
            items = await self.headlines()
            if not items:
                return "Свежих новостей по золоту и доллару за последние сутки не найдено."
            summary = await self._summarize(items)
            if not summary:  # без ключа Claude — просто заголовки
                summary = "\n".join(f"• {i['title']}" for i in items[:10])
            summary = html.escape(summary, quote=False)
            out = "📰 <b>Фундаментальные новости: золото и доллар</b>\n\n" + summary
            self._cache = (time.time(), out)
            return out
