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


class ChartVisionError(Exception):
    """Разбор не получился; текст — причина для админа и лога (ошибка API, баланс, модель…)."""


def _reason(e: Exception) -> str:
    import anthropic
    if isinstance(e, anthropic.APIStatusError):
        msg = str(getattr(e, "message", "") or e)
        low = msg.lower()
        if "credit balance" in low or "billing" in low:
            return f"на счёте Claude закончились деньги (HTTP {e.status_code}): {msg}"
        if e.status_code == 401:
            return f"неверный ANTHROPIC_API_KEY (HTTP 401): {msg}"
        if e.status_code == 404 or "model" in low:
            return f"модель недоступна (ANTHROPIC_MODEL), HTTP {e.status_code}: {msg}"
        return f"HTTP {e.status_code}: {msg}"
    if isinstance(e, anthropic.APIConnectionError):
        return f"нет связи с api.anthropic.com: {e}"
    return f"{type(e).__name__}: {e}"


async def analyze(image: bytes, language: str, market: str, model: str, caption: str = "") -> str:
    """Текст разбора (уже экранирован для HTML). Ошибка — ChartVisionError с причиной."""
    if not available():
        raise ChartVisionError("нет ANTHROPIC_API_KEY в .env")
    import anthropic

    content: list[dict] = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type(image),
                                     "data": base64.standard_b64encode(image).decode()}},
        {"type": "text", "text": ("Subscriber's note: " + caption[:500]) if caption else "Analyze this chart."},
    ]
    kw = dict(model=model, max_tokens=3000, system=PROMPT.format(language=language, market=market or "no data"),
              messages=[{"role": "user", "content": content}])
    client = anthropic.AsyncAnthropic(timeout=120, max_retries=2)
    try:
        try:   # как в новостях: с запасной моделью на стороне API
            resp = await client.beta.messages.create(**kw, output_config={"effort": "low"},
                                                     betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        except (TypeError, anthropic.BadRequestError) as e:
            # старая библиотека anthropic или API не принял бета-параметры — обычный запрос без них
            log.warning("chart vision: beta request failed (%s), retrying plain", _reason(e))
            resp = await client.messages.create(**kw)
    except Exception as e:  # noqa: BLE001
        reason = _reason(e)
        log.warning("chart vision failed: %s", reason)
        raise ChartVisionError(reason) from e
    if resp.stop_reason == "refusal":
        raise ChartVisionError("Claude отказался разбирать эту картинку")
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    if not text:
        raise ChartVisionError(f"пустой ответ Claude (stop_reason={resp.stop_reason})")
    return html.escape(text)
