"""Разбор графика по скриншоту: подписчик присылает картинку своего графика, Claude смотрит её вместе с живыми
данными бота (цена, дневной тренд, тренды по ТФ, открытый сигнал) и отвечает: тренд, уровни, где вход и стоп,
стоит ли входить сейчас. Не финансовый совет."""
from __future__ import annotations

import base64
import html
import logging
import os

log = logging.getLogger(__name__)

PROMPT = """You are a professional technical analyst inside a Telegram bot that gives XAUUSD (gold) signals.
A subscriber sent a screenshot of their own chart. Analyze what is visible on it and answer in {language}.

Live data from the bot (trust it over the screenshot for the current price and trend):
{market}

Rules:
- First identify the instrument and timeframe if visible. If the image is not a price chart, say so in one
  sentence and ask for a chart screenshot. Do not invent things you cannot see.
- If the chart is not gold, analyze it anyway but say that the bot's signals are only for XAUUSD.
- Keep the answer consistent with the bot: if the bot has an open signal, do not recommend the opposite
  direction; mention the bot's signal instead. If the screenshot contradicts the bot's daily trend, say that
  a trade against the daily trend is riskier.
- Be concrete: give price numbers read from the chart axis.
- Plain text only, no Markdown, no HTML, no tables. Short lines. At most ~1200 characters.
- Use exactly this structure (translate the headings into {language}, keep the emojis):
📈 Trend: ...
🧱 Levels: support ..., resistance ...
🎯 Idea: BUY/SELL or wait; entry zone ..., stop ..., take ...
⏱ Enter now? Yes / No / Wait for ... — one short reason
💡 One practical tip about what is on the chart (risk, pattern, news, etc.)"""

MEDIA = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def media_type(data: bytes) -> str:
    """Тип картинки по первым байтам (Telegram сжимает фото в JPEG, а файл может быть PNG/WebP)."""
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:3] == b"GIF":
        return "image/gif"
    return "image/jpeg"


async def analyze(image: bytes, language: str, market: str, model: str, caption: str = "") -> str | None:
    """Текст разбора (уже экранирован для HTML) или None — нет ключа, баланса или ответа."""
    if not available():
        return None
    import anthropic

    content: list[dict] = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type(image),
                                     "data": base64.standard_b64encode(image).decode()}},
        {"type": "text", "text": ("Subscriber's note: " + caption[:500]) if caption else "Analyze this chart."},
    ]
    client = anthropic.AsyncAnthropic()
    try:
        resp = await client.beta.messages.create(
            model=model,
            max_tokens=3000,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=PROMPT.format(language=language, market=market or "no data"),
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.APIStatusError as e:
        log.warning("chart vision error %s: %s", e.status_code, e.message)
        return None
    except anthropic.APIConnectionError:
        log.warning("chart vision connection error")
        return None
    if resp.stop_reason == "refusal":
        return None
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return html.escape(text) if text else None
