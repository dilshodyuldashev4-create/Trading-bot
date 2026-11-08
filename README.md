# Gold Signals Bot (XAUUSD)

Telegram-бот сигналов по золоту: проверяет рынок каждые 15 секунд, сам рассылает сигналы
с картинкой (вход, Stop Loss, Take Profit), даёт 3 дня бесплатно, потом продаёт подписку
через Telegram Stars. Есть админ-панель, разбор фундаментальных новостей и календарь событий США.

## Кнопки бота

| Кнопка | Что делает | Доступ |
|---|---|---|
| 📊 Сигнал | Анализ рынка: ожидаемый сетап и уровни. Подтверждённые сигналы приходят автоматически | 3 дня бесплатно, потом подписка |
| 📰 Фундаментальные новости | Свежие новости коротко: как влияют на золото и доллар | бесплатно |
| 🗓 Календарь новостей | CPI, NFP, FOMC и др.: время, прогноз/факт, влияние. 3 дня вперёд и 3 назад | бесплатно |
| 💎 Подписка | Оплата в Telegram Stars | — |

Админ: `/admin` (статистика, рассылка, выгрузка подписчиков, последние сигналы), `/grant <id> <дней>`, `/revoke <id>`.

## Стратегия и бэктест

В бот поставлена связка **ICT Silver Bullet + пробой азиатского диапазона** (M15, SL 100 / TP 200 пипсов).
На реальных свечах XAUUSD (декабрь 2023 – август 2026): 632 сделки, винрейт 36.6%, +6100 пипсов.
При риске 1:2 безубыточность — 33.3%. Ни одна проверенная стратегия не дала 60% при 1:2;
полная таблица — [reports/backtest.md](reports/backtest.md).

Повторить бэктест: `python scripts/run_backtest.py`.

## Запуск 24/7 на сервере (VPS)

1. Создайте бота у [@BotFather](https://t.me/BotFather), получите токен.
2. Получите ключ котировок: [Twelve Data](https://twelvedata.com) (для опроса раз в 15 секунд нужен платный тариф)
   или бесплатный демо-счёт OANDA (`DATA_PROVIDER=oanda`).
3. По желанию — ключ [Anthropic API](https://console.anthropic.com) для кратких разборов новостей.
4. На сервере с Docker:

```bash
git clone https://github.com/dilshodyuldashev4-create/Trading-bot.git && cd Trading-bot
cp .env.example .env   # заполните BOT_TOKEN, ADMIN_IDS, ключ котировок
docker compose up -d --build
docker compose logs -f
```

`restart: always` перезапускает бота при ошибке и после перезагрузки сервера.

Без Docker: `pip install -r requirements.txt && python -m goldbot`.

## Тесты

```bash
python -m unittest discover -s tests -t .
```

## Структура

* `goldbot/strategies/` — порты индикаторов TR (XADz ZigZag) и FVG (OB + FVG + BOS), популярные стратегии
* `goldbot/backtest.py`, `scripts/run_backtest.py` — бэктест с фиксированным SL/TP и спредом
* `goldbot/engine.py` — проверка рынка, создание и закрытие сигналов
* `goldbot/chart.py` — картинка сигнала
* `goldbot/bot.py` — Telegram-бот, подписка, админка
* `goldbot/news.py`, `goldbot/econ_calendar.py` — новости и календарь
