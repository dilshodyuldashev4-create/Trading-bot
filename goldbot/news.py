"""Фундаментальные новости: RSS-ленты + краткий разбор влияния на золото и доллар через Claude."""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import time
from calendar import timegm

import aiohttp
import feedparser

from .i18n import t

log = logging.getLogger(__name__)

KEYWORDS = re.compile(
    r"\b(gold|xau|bullion|precious|fed|fomc|powell|dollar|usd|dxy|treasury|yield|inflation|cpi|pce|"
    r"payroll|nfp|jobs|unemployment|rate cut|rate hike|tariffs?|geopolit\w*|wars?|sanctions?|recession|gdp|"
    r"iran|israel|gaza|russia|ukraine|china|taiwan|north korea|missiles?|attacks?|conflict|nato|ceasefire|"
    r"strikes?|middle east|oil|opec|safe.haven|central banks?)\b",
    re.I)

# без Claude показываем только то, что прямо про золото, ФРС, ставки и доходности
CORE = re.compile(r"\b(gold|xau|bullion|precious|fed|fomc|powell|dxy|treasur\w*|yields?|rate cuts?|rate hikes?|"
                  r"interest rates?|cpi|pce|payrolls?|nfp|wars?|sanctions?|missiles?|ceasefire|geopolit\w*|"
                  r"tariffs?|safe.haven)\b", re.I)
GT_LANG = {"ru": "ru", "uz": "uz", "en": "en"}
GT_URL = "https://translate.googleapis.com/translate_a/single"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

PROMPT = """Ты аналитик рынка золота. Ниже свежие новостные заголовки (с кратким текстом): экономика США,
ФРС, доллар и геополитика (войны, санкции, конфликты, пошлины).
Выбери до 8 самых важных для золота (XAUUSD) и доллара США, обязательно включи важные геополитические.
Для каждой напиши одну-две короткие строки в формате:

• <суть новости простыми словами> — Золото: ⬆️/⬇️/➡️, Доллар: ⬆️/⬇️/➡️. <почему, коротко>

Затем отдельным абзацем «Что дальше»: 2–3 короткие строки — куда фон, скорее всего, двинет золото
в ближайшие дни, какой сценарий основной и что может его сломать. Учитывай данные рынка ниже
(цена и дневной тренд), но не придумывай уровни, которых нет в данных.
В конце одной строкой общий вывод: фон для золота ⬆️/⬇️/➡️ и насколько сильный.
Без вступлений, без markdown-заголовков. Не выдумывай факты, которых нет в заголовках.
Пиши весь ответ на языке: {language} (подписи «Золото», «Доллар», «Что дальше» тоже переведи).

Данные рынка: {market}"""

BIAS_PROMPT = """Ты аналитик рынка золота (XAUUSD). По свежим заголовкам (экономика США, ФРС, доллар,
геополитика) оцени общий фундаментальный фон для золота на ближайшие часы.
bias: bullish — фон толкает золото вверх, bearish — вниз, neutral — смешанный или слабый.
strength: strong — только если есть явный крупный драйвер (решение ФРС, сильные данные, эскалация войны,
крупные санкции и т.п.), иначе moderate или weak. Не выдумывай факты, которых нет в заголовках.
Данные рынка: {market}"""

EVENT_PROMPT = """Ты аналитик рынка золота (XAUUSD). Скоро (или только что) выходит важная новость:
{event}
Оцени, куда золото, скорее всего, пойдёт на ближайшие 1–3 часа. Учитывай вместе:
- саму новость: ожидания (прогноз против прошлого значения, а если есть — факт против прогноза);
- свежие заголовки ниже: ФРС, доллар, доходности и обязательно геополитику (войны, санкции, конфликты,
  пошлины, эскалация или перемирие) — она может перевесить экономические данные;
- данные рынка (цена и дневной тренд).
bias: bullish — вверх, bearish — вниз, neutral — неясно или силы уравновешены.
strength: strong — только если драйвер явный и все факторы в одну сторону; moderate — перевес есть, но
не однозначный; weak — перевеса нет. При сомнениях выбирай weak или neutral.
В reason коротко: что решает (новость или геополитика) и главный риск. Не выдумывай факты.
Данные рынка: {market}"""

BIAS_SCHEMA = {
    "type": "object",
    "properties": {
        "bias": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
        "strength": {"type": "string", "enum": ["strong", "moderate", "weak"]},
        "reason": {"type": "string"},
    },
    "required": ["bias", "strength", "reason"],
    "additionalProperties": False,
}


class NewsService:
    def __init__(self, feeds: tuple[str, ...], model: str, cache_seconds: int = 1200):
        self.feeds, self.model, self.cache_seconds = feeds, model, cache_seconds
        self._cache: dict[str, tuple[float, str]] = {}
        self._lock = asyncio.Lock()
        self._bias: tuple[float, dict | None] | None = None   # (время, оценка фона) — кэш на час
        self._bias_lock = asyncio.Lock()
        self._event_bias: dict[str, tuple[float, dict | None]] = {}   # оценка перед конкретной новостью

    async def _fetch_feed(self, s: aiohttp.ClientSession, url: str) -> list[dict]:
        try:
            async with s.get(url, headers={"User-Agent": UA}) as r:
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

    async def headlines(self, hours: int = 24, limit: int = 35) -> list[dict]:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            groups = await asyncio.gather(*(self._fetch_feed(s, u) for u in self.feeds))
        everything = sorted((x for g in groups for x in g), key=lambda x: -x["ts"])
        # в выходные свежих новостей мало — тогда берём последние 3 дня
        return self._select(everything, hours, limit) or self._select(everything, 72, limit)

    @staticmethod
    def _select(items: list[dict], hours: int, limit: int) -> list[dict]:
        cutoff = time.time() - hours * 3600
        seen, out = set(), []
        for it in items:
            key = it["title"].lower()
            if it["ts"] < cutoff or key in seen or not KEYWORDS.search(it["title"] + " " + it["summary"]):
                continue
            seen.add(key)
            out.append(it)
        return out[:limit]

    async def _summarize(self, items: list[dict], lang: str = "ru", market: str = "") -> str | None:
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
                system=PROMPT.format(language=t(lang, "news_lang"), market=market or "нет данных"),
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

    async def _translate(self, titles: list[str], lang: str) -> list[str]:
        """Бесплатный перевод заголовков (Google Translate без ключа). При ошибке — оригинал."""
        tl = GT_LANG.get(lang, "en")
        if tl == "en" or not titles:
            return titles
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                async with s.get(GT_URL, params={"client": "gtx", "sl": "en", "tl": tl, "dt": "t",
                                                 "q": "\n".join(titles)}, headers={"User-Agent": UA}) as r:
                    r.raise_for_status()
                    j = await r.json(content_type=None)
            out = "".join(seg[0] for seg in j[0] if seg and seg[0]).strip().split("\n")
            out = [x.strip() for x in out if x.strip()]
            return out if len(out) == len(titles) else titles
        except Exception as e:  # noqa: BLE001
            log.warning("translate: %s", e)
            return titles

    async def bias(self, market: str = "", ttl: int = 3600) -> dict | None:
        """Оценка фона новостей для золота через Claude (кэш на час). None — нет ключа, баланса или новостей."""
        if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
            return None
        async with self._bias_lock:
            if self._bias and time.time() - self._bias[0] < ttl:
                return self._bias[1]
            result = None
            try:
                items = await self.headlines()
                if items:
                    result = await self._ask_bias(items, market)
            except Exception:  # noqa: BLE001 — без оценки работаем только по графику
                log.exception("news bias")
            # при ошибке повторяем не раньше чем через 10 минут, чтобы не тратить баланс
            self._bias = (time.time() if result else time.time() - ttl + 600, result)
            return result

    async def event_bias(self, market: str, ev: dict, ttl: int = 600) -> dict | None:
        """Свежая оценка рынка перед/во время важной новости: сама новость + геополитика (кэш 10 минут)."""
        if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
            return None
        key = f"{ev.get('ts')}|{ev.get('title')}|{ev.get('actual')}"
        async with self._bias_lock:
            hit = self._event_bias.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
            result = None
            try:
                items = await self.headlines(hours=12) or await self.headlines()
                event = "; ".join(f"{k}: {ev[k]}" for k in ("title", "ts", "country", "forecast", "previous", "actual")
                                  if ev.get(k))
                result = await self._ask_bias(items or [{"title": "нет свежих заголовков", "summary": ""}],
                                              market, EVENT_PROMPT.format(event=event, market=market or "нет данных"))
            except Exception:  # noqa: BLE001
                log.exception("event bias")
            # при ошибке повторим через 3 минуты
            self._event_bias = {key: (time.time() if result else time.time() - ttl + 180, result)}
            return result

    async def _ask_bias(self, items: list[dict], market: str, system: str | None = None) -> dict | None:
        import anthropic

        text = "\n".join(f"- {i['title']}. {i['summary']}" for i in items)
        client = anthropic.AsyncAnthropic()
        try:
            resp = await client.beta.messages.create(
                model=self.model,
                max_tokens=2000,
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": BIAS_SCHEMA}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=system or BIAS_PROMPT.format(market=market or "нет данных"),
                messages=[{"role": "user", "content": text}],
            )
        except anthropic.APIStatusError as e:
            log.warning("claude bias error %s: %s", e.status_code, e.message)
            return None
        except anthropic.APIConnectionError:
            log.warning("claude bias connection error")
            return None
        if resp.stop_reason in ("refusal", "max_tokens"):
            return None
        try:
            data = json.loads(next(b.text for b in resp.content if b.type == "text"))
        except (StopIteration, ValueError):
            return None
        log.info("news bias: %s", data)
        return data

    async def strong_bias(self, market: str = "") -> int:
        """+1 — сильный бычий фон, -1 — сильный медвежий, 0 — нет сильного фона или нет оценки."""
        b = await self.bias(market)
        if not b or b.get("strength") != "strong":
            return 0
        return {"bullish": 1, "bearish": -1}.get(b.get("bias"), 0)

    async def digest(self, lang: str = "ru", market: str = "") -> str:
        async with self._lock:
            cached = self._cache.get(lang)
            if cached and time.time() - cached[0] < self.cache_seconds:
                return cached[1]
            items = await self.headlines()
            if not items:
                return t(lang, "news_none")
            summary = await self._summarize(items, lang, market)
            if not summary:  # без Claude (нет ключа или баланса) — заголовки с бесплатным переводом
                core = [i for i in items if CORE.search(i["title"])]
                titles = [i["title"] for i in (core if len(core) >= 3 else items)[:10]]
                titles = await self._translate(titles, lang)
                summary = "\n".join(f"• {x}" for x in titles)
            summary = html.escape(summary, quote=False)
            out = t(lang, "news_head") + summary
            self._cache[lang] = (time.time(), out)
            return out
