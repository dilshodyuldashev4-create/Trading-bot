"""Тексты бота на трёх языках: русский, английский, узбекский (латиница)."""
from __future__ import annotations

DEFAULT = "ru"
LANGS = ("en", "ru", "uz")
LANG_BUTTONS = (("en", "🇬🇧 English"), ("ru", "🇷🇺 Русский"), ("uz", "🇺🇿 Oʻzbekcha"))
CHOOSE = "🌐 Выберите язык\n🌐 Choose your language\n🌐 Tilni tanlang"

TEXTS: dict[str, dict[str, str]] = {
    # ── русский ──────────────────────────────────────────────────────────────
    "ru": {
        "lang_name": "🇷🇺 Русский",
        "lang_set": "✅ Язык: Русский",
        "btn_signal": "📊 Сигнал",
        "btn_fund": "📰 Фундаментальные новости",
        "btn_cal": "🗓 Календарь новостей",
        "btn_sub": "💎 Подписка",
        "btn_profile": "👤 Профиль",
        "btn_lang": "🌐 Сменить язык",
        "btn_stats": "📈 Статистика",
        "market_open": ("🟢 <b>Рынок золота открыт</b>\n\n"
                        "Как только появится новый сетап, бот сразу пришлёт вам сигнал. Удачной торговли!"),
        "market_closed": "🔴 <b>Рынок золота закрыт</b> на ежедневный перерыв.\nОткроется {when}.",
        "market_closed_week": ("🔴 <b>Рынок золота закрыт на выходные</b>\n\n"
                               "Откроется {when}. Отдыхайте, новые сигналы будут на следующей неделе."),
        "btn_accept": "✅ Принять сигнал",
        "btn_decline": "❌ Отклонить",
        "accepted": "✅ Спасибо, что приняли наш сигнал #{id}! Мы сообщим вам о результате, когда сделка закроется.",
        "declined": "❌ Вы отклонили сигнал #{id}. Когда будет новый сигнал, мы вам сообщим. Спасибо!",
        "sig_already_closed": "Этот сигнал уже закрыт",
        "stats_head": ("📈 <b>Статистика сигналов</b>\n\n"
                       "Всего: {total} · ✅ TP: {tp} · ❌ SL: {sl} · ⏳ в работе: {open}\n"
                       "🎯 Винрейт: <b>{wr}</b>\n💰 Итог: <b>{pips} пипсов</b>\n\n"
                       "<b>Последние сигналы:</b>"),
        "stats_row": ("\n\n<b>#{id}</b> {when} {side}\n"
                      "📍 Вход {entry} · 🛑 SL {sl} · 🎯 TP {tp}\n{result}"),
        "stats_tp": "✅ Take Profit: выход {exit}, <b>+{pips} пипсов</b>",
        "stats_sl": "❌ Stop Loss: выход {exit}, −{pips} пипсов",
        "stats_open": "⏳ В работе",
        "stats_empty": "📈 Сигналов пока не было.",
        "hello": ("👋 Привет, {name}!\n\n"
                  "Я бот сигналов по <b>золоту (XAUUSD)</b>.\n"
                  "• 📊 <b>Сигнал</b> — анализ рынка и ожидаемый сетап; подтверждённые сигналы приходят сами\n"
                  "• 📰 <b>Фундаментальные новости</b> — коротко, как новости влияют на золото и доллар\n"
                  "• 🗓 <b>Календарь новостей</b> — CPI, NFP, FOMC: время и влияние\n\n"),
        "trader": "трейдер",
        "trial_new": "🎁 Вам открыт <b>бесплатный доступ на {days} дн.</b>: сигналы будут приходить автоматически.",
        "st_start": "Нажмите /start",
        "st_paid": "💎 Подписка активна до {until}",
        "st_trial": "🎁 Бесплатный период до {until}",
        "st_expired": "⛔️ Бесплатный период закончился. Оформите подписку, чтобы получать сигналы.",
        "inv_title": "Подписка на сигналы XAUUSD — {days} дней",
        "inv_desc": "Автоматические сигналы по золоту с графиком, входом, SL и TP.",
        "inv_label": "{days} дней",
        "sig_expired": "⛔️ Бесплатный период закончился. Сигналы доступны по подписке.",
        "analyzing": "🔎 Анализирую рынок…",
        "quotes_fail": "Не удалось получить котировки, попробуйте через минуту.",
        "price_now": "\n\n💰 Цена сейчас: <b>{price}</b>",
        "open_signal": "\n\n📌 Открытый сигнал #{id}: {side} от {entry}, SL {sl}, TP {tp}",
        "analysis_head": "📊 <b>Анализ XAUUSD</b>",
        "news_wait": "⏳ Собираю свежие новости…",
        "news_fail": "Не удалось загрузить новости, попробуйте позже.",
        "sub_price": "Подписка: <b>{price} ⭐</b> за {days} дней.",
        "profile": "🆔 {id}\n{status}\n🌐 Язык: {language}",
        "ask_capital": ("💰 <b>Какой у вас капитал (депозит) для торговли?</b>\n\n"
                        "Выберите кнопку или напишите сумму в долларах, например <code>150</code>. "
                        "По капиталу бот будет показывать в каждом сигнале ваш объём сделки (лот)."),
        "btn_skip": "Пропустить",
        "btn_capital": "💰 Изменить капитал",
        "cap_set": "✅ Капитал: <b>${cap}</b>\n📦 Ваш лот в сигналах: <b>{lot}</b>",
        "cap_skipped": "Хорошо. Капитал можно указать позже: 👤 Профиль или /capital",
        "cap_bad": "Напишите сумму числом, например <code>150</code>",
        "profile_cap": "\n💰 Капитал: ${cap} · лот {lot}",
        "profile_nocap": "\n💰 Капитал не указан (/capital)",
        "sig_lot": ("\n\n📦 <b>Ваш лот: {lot}</b> (капитал ${cap})\n"
                    "🛑 Если стоп: −${loss} ({loss_pct}%) · 🎯 Если тейк: +${profit}"),
        "sig_lot_warn": "\n⚠️ Капитал маленький: даже минимальный лот 0.01 — это риск {loss_pct}%, больше {pct}%.",
        "sig_nocap": "\n\n💰 Укажите свой капитал, и бот покажет ваш лот: /capital",
        "sig_rules": ("\n\n❗️ <b>Работайте строго так, как рекомендует бот</b>: этот лот, этот стоп и этот тейк. "
                      "Бывает 2–3 стопа подряд, это нормально. После {n} стопов подряд за день бот закрывает торговый день."),
        "day_closed": ("🛑 <b>Торговый день закрыт</b>\n\n"
                       "Мы взяли {n} стопа подряд. Сегодня больше не торгуем, чтобы сберечь депозит. Продолжим завтра 💪"),
        "day_closed_cap": "\n\n💰 Ваш капитал сейчас: <b>${cap}</b>",
        "late_hint_buy": "\n⏱ Входить, только пока цена не выше <b>{limit}</b>. Выше: вы опоздали, сделку не открывайте.",
        "late_hint_sell": "\n⏱ Входить, только пока цена не ниже <b>{limit}</b>. Ниже: вы опоздали, сделку не открывайте.",
        "late": ("⚠️ <b>Сигнал #{id} {side}: вход уже неактуален</b>\n\n"
                 "Цена ушла от входа {entry} на {pips} пипсов и сейчас {price}.\n"
                 "Если вы ещё не открыли сделку, <b>не входите</b>: вы опоздали, риск стал больше, а прибыль меньше.\n"
                 "Кто уже в сделке, держите по плану: стоп и тейк те же."),
        "close_balance": ("\n\n💼 Ваш лот {lot}: <b>{pnl}</b>\n💰 Ваш баланс теперь: <b>${bal}</b>\n"
                          "<i>Если вы не открывали эту сделку, обновите капитал: /capital</i>"),
        "paid_ok": "✅ Спасибо! Подписка активна до {until}.",
        "cancelled": "Отменено",
        "granted": "🎁 Вам выдана подписка до {until}",
        "trial_reminder": ("⏳ Бесплатный период заканчивается через час. "
                           "Чтобы и дальше получать сигналы, оформите подписку: 💎 Подписка"),
        "close_tp": "✅ <b>Сигнал #{id} {side} закрыт по Take Profit</b>\n💰 Результат: <b>+{pips} пипсов</b>",
        "close_sl": "❌ <b>Сигнал #{id} {side} закрыт по Stop Loss</b>\n📉 Результат: −{pips} пипсов",
        "close_body": ("📍 Вход: {entry}\n🏁 Выход: {exit}\n🛑 SL {sl} · 🎯 TP {tp}\n\n"
                       "📊 Статистика бота: {tp_n} TP / {sl_n} SL"),
        "winrate": " (винрейт {wr}%)",
        "news_close": ("⚠️ <b>Закройте сделку #{id} ({side} от {entry}) прямо сейчас</b>\n\n"
                       "Через {mins} мин выходит важная новость США: <b>{title}</b> (🔴 высокая важность). "
                       "В такие минуты золото может резко прыгнуть на $10–30 и выбить стоп.\n\n"
                       "💰 Цена сейчас {price}, результат сделки: <b>{pips} пипсов</b>. "
                       "Закройте её по рынку, не дожидаясь новости. Бот больше не ведёт эту сделку."),
        "stats_news": "⚠️ закрыт перед новостью {exit} ({pips} п.)",
        "mr_head": "🌅 <b>Утренний разбор XAUUSD — {date}</b>\n",
        "mr_price": "💰 Цена сейчас: <b>{price}</b> ({ch} пипсов с открытия сессии {open})",
        "mr_night": "🌙 За ночь (азиатская сессия): хай {hi}, лой {lo}, диапазон {rng} пипсов",
        "mr_prev": "📏 Прошлый день: хай {hi}, лой {lo}",
        "mr_swept_hi": "⚡️ Ночью сняли ликвидность над хаем прошлого дня",
        "mr_swept_lo": "⚡️ Ночью сняли ликвидность под лоем прошлого дня",
        "mr_news": "📰 Фон новостей для золота: {arrow} {strength}",
        "mr_tfs": "🕒 Тренд по таймфреймам (EMA50): {tfs}",
        "mr_up": "🧭 Основной сценарий: <b>рост</b>. Покупатели контролируют рынок, тренд вверх. Пока цена выше ночного лоя {lo}, приоритет у BUY; пробой {hi} откроет продолжение.",
        "mr_down": "🧭 Основной сценарий: <b>снижение</b>. Продавцы контролируют рынок, тренд вниз. Пока цена ниже ночного хая {hi}, приоритет у SELL; пробой {lo} откроет продолжение.",
        "mr_mixed": "🧭 Сценарий: <b>неопределённость</b>. Ночное движение против дневного тренда. Ждём выхода из диапазона {lo}–{hi}; бот даст сигнал, когда сетап подтвердится.",
        "mr_nodata": "🌅 Утренний разбор: пока нет данных за сессию.",
        "news_bg": "📰 Фон новостей и геополитики для золота: {arrow} {strength} — {rel}",
        "news_strong": "сильный", "news_moderate": "умеренный", "news_weak": "слабый",
        "news_with": "<b>в пользу сделки</b>", "news_against": "<b>против сделки, будьте осторожны</b>",
        "news_neutral": "нейтрально",
        "close_mfe": "📈 Максимум в плюсе был: <b>+{pips} пипсов</b> (до {price})",
        "close_mfe_none": "📈 В плюс сделка не выходила",
        "close_mae": "📉 Максимальная просадка была: <b>−{pips} пипсов</b> (до {price})",
        "close_mae_none": "📉 Просадки почти не было",
        "close_cta": "\n\n💎 Чтобы получать сигналы, оформите подписку: /subscribe",
        "signal": ("<b>{side} XAUUSD</b>\n\n"
                   "📍 Вход: <b>{entry}</b>\n"
                   "🛑 Stop Loss: <b>{sl}</b> ({sl_pips} пипсов)\n"
                   "🎯 Take Profit: <b>{tp}</b> ({tp_pips} пипсов)\n"
                   "⚖️ Риск/прибыль 1:{rr}\n"
                   "💡 Цена у брокеров немного отличается: ставьте SL {sl_pips} и TP {tp_pips} пипсов от <b>своей</b> цены входа.\n\n"
                   "📊 Стратегия: {strategy}\n"
                   "🕒 {when}\n\n"
                   "<i>{note}. Прошлые результаты не гарантируют будущих. "
                   "Рискуйте не больше 1–2% депозита на сделку.</i>"),
        "strat_combo": "ICT Silver Bullet + пробой азиатского диапазона",
        "strat_fvg": "OB + FVG + BOS по тренду EMA200",
        "exp_daily_trend": "📈 Дневной тренд (EMA50): {trend}.",
        "strat_donchian": "Пробой канала Дончиана 20 по тренду EMA200 (M15)",
        "note_donchian": "Бэктест XAUUSD 2023–2026, SL 100 / TP 200 пипсов: 1635 сделок, винрейт 34.7%, +6900 пипсов",
        "exp_donchian": "Сигнал появится на M15, когда свеча закроется выше максимума (BUY) или ниже минимума (SELL) последних 20 свечей по тренду EMA200.",
        "strat_rsi_m5": "RSI-откат по дневному тренду (M5)",
        "note_rsi_m5": "Бэктест XAUUSD 2023–2026, SL 100 / TP 200 пипсов: 2462 сделки, винрейт 35.0%, +12100 пипсов",
        "exp_rsi_m5": "Сигнал появится на M5, когда RSI вернётся из зоны отката (выше 40 для BUY, ниже 60 для SELL).",
        "exp_portfolio": "Бот следит сразу за {n} стратегиями:",
        "strat_fvg_m5": "OB + FVG + BOS по дневному тренду (M5)",
        "note_fvg_m5": "Бэктест XAUUSD 2023–2026, SL 100 / TP 200 пипсов: 1375 сделок, винрейт 36.7%, +14000 пипсов",
        "exp_fvg_m5": "Сигнал появится на M5, когда цена пробьёт последний свинг (BOS) и рядом будет FVG того же направления.",
        "strat_squeeze": "Squeeze (Боллинджер в Кельтнере) по дневному тренду",
        "note_squeeze": "Бэктест XAUUSD 2023–2026, SL 100 / TP 200 пипсов: 441 сделка, винрейт 40.8%, +9900 пипсов",
        "exp_squeeze": "Сигнал появится на M15, когда рынок выйдет из сжатия и свеча закроется за полосой Боллинджера.",
        "strat_trendline_m5": "Пробой трендовой линии по дневному тренду (M5)",
        "note_trendline_m5": "Бэктест XAUUSD 2023–2026, SL 100 / TP 200 пипсов: 1812 сделок, винрейт 35.2%, +9900 пипсов",
        "exp_trendline_m5": "Сигнал появится на M5, когда свеча закроется за трендовой линией, построенной по двум последним свингам.",
        "strat_liq_m5": "Снятие ликвидности за свингом по дневному тренду (M5)",
        "note_liq_m5": "Бэктест XAUUSD 2023–2026, SL 100 / TP 200 пипсов: 1917 сделок, винрейт 34.3%, +5700 пипсов (2026: +3500)",
        "exp_liq_m5": "Сигнал появится на M5, когда цена проколет последний хай/лой свинга (снимет стопы) и закроется обратно по дневному тренду.",
        "strat_eqliq_m5": "Снятие ликвидности за равными хаями/лоями по дневному тренду (M5)",
        "note_eqliq_m5": "Бэктест XAUUSD 2023–2026, SL 100 / TP 200 пипсов: 437 сделок, винрейт 38.9%, +7300 пипсов (2026: +2800)",
        "exp_eqliq_m5": "Сигнал появится на M5, когда цена проколет равные хаи или лои (пул стопов) и закроется обратно по дневному тренду.",
        "note_combo": "Бэктест XAUUSD 2023–2026, SL 100 / TP 200 пипсов: 632 сделки, винрейт 36.6%, +6100 пипсов",
        "note_fvg": "Бэктест XAUUSD 2023–2026, SL 100 / TP 200 пипсов: 283 сделки, винрейт 37.8%, +3800 пипсов",
        "exp_trend_up": "вверх (ищем только BUY)",
        "exp_trend_down": "вниз (ищем только SELL)",
        "exp_fvg": ("Тренд по EMA200 на H1: {trend}.\n"
                    "Сигнал появится, когда цена пробьёт последний свинг (BOS) и рядом будет FVG того же направления."),
        "exp_asia_forming": "🌏 Азиатский диапазон формируется: {lo} – {hi}. Окно пробоя {start}–{end}.",
        "exp_asia_broken": "🌏 Пробой азиатского диапазона сегодня уже был.",
        "exp_asia_setup": ("🌏 Ожидаемый сетап: если свеча M15 закроется выше {hi} — BUY, "
                           "ниже {lo} — SELL (до {end})."),
        "exp_asia_next": "🌏 Следующее окно пробоя азиатского диапазона: {when}.",
        "exp_sb_window": "🎯 Silver Bullet: окно {start}–{end}. Открытие дня {open}, цена {pos} — ждём FVG на {side}.",
        "exp_above": "выше",
        "exp_below": "ниже",
        "exp_sb_next": "🎯 Следующее окно Silver Bullet: {when}.",
        "exp_confirm": "Как только сетап подтвердится, бот сам пришлёт сигнал.",
        "news_lang": "Russian",
        "news_head": "📰 <b>Фундаментальные новости: золото и доллар</b>\n\n",
        "news_none": "Свежих новостей по золоту и доллару за последние сутки не найдено.",
        "cal_head": "🗓 <b>Календарь новостей США</b> (время: {tz})\n",
        "cal_next": "<b>⏭ Ближайшие 3 дня</b>",
        "cal_none_next": "Важных новостей нет",
        "cal_past": "\n<b>⏮ Прошедшие 3 дня</b>",
        "cal_none_past": "Нет данных",
        "cal_legend": "\n🔴 высокая важность  🟠 средняя",
        "n_fact": "факт {v}",
        "n_forecast": "прогноз {v}",
        "n_prev": "пред. {v}",
        "usd_up": "доллар ⬆️, золото ⬇️",
        "usd_down": "доллар ⬇️, золото ⬆️",
        "fact_above": "факт выше прогноза",
        "fact_below": "факт ниже прогноза",
        "verdict": "Итог: {v}",
        "impact_default": "Может вызвать волатильность в долларе и золоте",
        "rule_nfp": "Сильная занятость → ФРС дольше держит ставку → доллар ⬆️, золото ⬇️",
        "rule_unemp": "Рост безработицы → ждут снижения ставки → доллар ⬇️, золото ⬆️",
        "rule_claims": "Больше заявок на пособие → слабый рынок труда → доллар ⬇️, золото ⬆️",
        "rule_cpi": "Инфляция выше прогноза → ставка дольше высокая → доллар ⬆️, золото ⬇️",
        "rule_pce": "Любимый индикатор инфляции ФРС: выше прогноза → доллар ⬆️, золото ⬇️",
        "rule_ppi": "Цены производителей выше прогноза → доллар ⬆️, золото ⬇️",
        "rule_rate": "Решение по ставке ФРС: повышение/жёсткий тон → доллар ⬆️, золото ⬇️; снижение → наоборот",
        "rule_fomc": "Речь ФРС: жёсткий тон → доллар ⬆️, золото ⬇️; мягкий → золото ⬆️",
        "rule_gdp": "Сильный ВВП → доллар ⬆️, золото ⬇️",
        "rule_retail": "Сильные продажи → доллар ⬆️, золото ⬇️",
        "rule_pmi": "Деловая активность выше прогноза → доллар ⬆️, золото ⬇️",
        "rule_jobs": "Больше вакансий/занятости → доллар ⬆️, золото ⬇️",
        "rule_sent": "Оптимизм потребителей → доллар ⬆️, золото ⬇️",
        "pre_head": "⏰ <b>Через 15 минут важная новость США</b>\n\n",
        "pre_forecast": "прогноз <b>{v}</b>",
        "pre_warn": "⚠️ Возможны резкие движения золота, будьте осторожны с входами.",
        "res_head": "🚨 <b>Вышла новость: {title}</b> ({when})\n\n",
        "res_fact": "📊 Факт: <b>{v}</b>",
        "res_forecast": "🎯 Прогноз: {v}",
        "res_prev": "⏮ Предыдущее: {v}",
    },
    # ── English ──────────────────────────────────────────────────────────────
    "en": {
        "lang_name": "🇬🇧 English",
        "lang_set": "✅ Language: English",
        "btn_signal": "📊 Signal",
        "btn_fund": "📰 Fundamental news",
        "btn_cal": "🗓 News calendar",
        "btn_sub": "💎 Subscription",
        "btn_profile": "👤 Profile",
        "btn_lang": "🌐 Change language",
        "btn_stats": "📈 Statistics",
        "market_open": ("🟢 <b>The gold market is open</b>\n\n"
                        "As soon as there is a new setup, the bot will send you a signal. Good trading!"),
        "market_closed": "🔴 <b>The gold market is closed</b> for the daily break.\nIt opens {when}.",
        "market_closed_week": ("🔴 <b>The gold market is closed for the weekend</b>\n\n"
                               "It opens {when}. Have a rest, new signals next week."),
        "btn_accept": "✅ Accept signal",
        "btn_decline": "❌ Decline",
        "accepted": "✅ Thank you for accepting our signal #{id}! We'll let you know the result when the trade closes.",
        "declined": "❌ You declined signal #{id}. We'll let you know when there is a new signal. Thank you!",
        "sig_already_closed": "This signal is already closed",
        "stats_head": ("📈 <b>Signal statistics</b>\n\n"
                       "Total: {total} · ✅ TP: {tp} · ❌ SL: {sl} · ⏳ open: {open}\n"
                       "🎯 Win rate: <b>{wr}</b>\n💰 Result: <b>{pips} pips</b>\n\n"
                       "<b>Latest signals:</b>"),
        "stats_row": ("\n\n<b>#{id}</b> {when} {side}\n"
                      "📍 Entry {entry} · 🛑 SL {sl} · 🎯 TP {tp}\n{result}"),
        "stats_tp": "✅ Take Profit: exit {exit}, <b>+{pips} pips</b>",
        "stats_sl": "❌ Stop Loss: exit {exit}, −{pips} pips",
        "stats_open": "⏳ Open",
        "stats_empty": "📈 No signals yet.",
        "hello": ("👋 Hi, {name}!\n\n"
                  "I'm a <b>gold (XAUUSD)</b> signals bot.\n"
                  "• 📊 <b>Signal</b> — market analysis and the expected setup; confirmed signals arrive automatically\n"
                  "• 📰 <b>Fundamental news</b> — in short, how the news affects gold and the dollar\n"
                  "• 🗓 <b>News calendar</b> — CPI, NFP, FOMC: time and impact\n\n"),
        "trader": "trader",
        "trial_new": "🎁 You've got <b>free access for {days} days</b>: signals will arrive automatically.",
        "st_start": "Press /start",
        "st_paid": "💎 Subscription active until {until}",
        "st_trial": "🎁 Free trial until {until}",
        "st_expired": "⛔️ Your free trial has ended. Subscribe to keep receiving signals.",
        "inv_title": "XAUUSD signals subscription — {days} days",
        "inv_desc": "Automatic gold signals with a chart, entry, SL and TP.",
        "inv_label": "{days} days",
        "sig_expired": "⛔️ Your free trial has ended. Signals are available with a subscription.",
        "analyzing": "🔎 Analyzing the market…",
        "quotes_fail": "Couldn't get quotes, please try again in a minute.",
        "price_now": "\n\n💰 Current price: <b>{price}</b>",
        "open_signal": "\n\n📌 Open signal #{id}: {side} from {entry}, SL {sl}, TP {tp}",
        "analysis_head": "📊 <b>XAUUSD analysis</b>",
        "news_wait": "⏳ Gathering the latest news…",
        "news_fail": "Couldn't load the news, please try later.",
        "sub_price": "Subscription: <b>{price} ⭐</b> for {days} days.",
        "profile": "🆔 {id}\n{status}\n🌐 Language: {language}",
        "ask_capital": ("💰 <b>What is your trading capital (deposit)?</b>\n\n"
                        "Tap a button or type the amount in dollars, e.g. <code>150</code>. "
                        "The bot will use it to show your trade size (lot) in every signal."),
        "btn_skip": "Skip",
        "btn_capital": "💰 Change capital",
        "cap_set": "✅ Capital: <b>${cap}</b>\n📦 Your lot in signals: <b>{lot}</b>",
        "cap_skipped": "OK. You can set your capital later: 👤 Profile or /capital",
        "cap_bad": "Please type the amount as a number, e.g. <code>150</code>",
        "profile_cap": "\n💰 Capital: ${cap} · lot {lot}",
        "profile_nocap": "\n💰 Capital not set (/capital)",
        "sig_lot": ("\n\n📦 <b>Your lot: {lot}</b> (capital ${cap})\n"
                    "🛑 If stop: −${loss} ({loss_pct}%) · 🎯 If take: +${profit}"),
        "sig_lot_warn": "\n⚠️ Small capital: even the minimum lot 0.01 risks {loss_pct}%, more than {pct}%.",
        "sig_nocap": "\n\n💰 Set your capital and the bot will show your lot: /capital",
        "sig_rules": ("\n\n❗️ <b>Trade exactly as the bot recommends</b>: this lot, this stop and this take profit. "
                      "2–3 losses in a row can happen, that's normal. After {n} stops in a row in a day the bot closes the trading day."),
        "day_closed": ("🛑 <b>Trading day closed</b>\n\n"
                       "We took {n} stops in a row. No more trading today, to protect the deposit. We'll continue tomorrow 💪"),
        "day_closed_cap": "\n\n💰 Your capital now: <b>${cap}</b>",
        "late_hint_buy": "\n⏱ Enter only while the price is not above <b>{limit}</b>. Above it you're late, don't open the trade.",
        "late_hint_sell": "\n⏱ Enter only while the price is not below <b>{limit}</b>. Below it you're late, don't open the trade.",
        "late": ("⚠️ <b>Signal #{id} {side}: entry is no longer valid</b>\n\n"
                 "Price has moved {pips} pips from the entry {entry} and is now {price}.\n"
                 "If you haven't opened the trade yet, <b>don't enter</b>: you're late, the risk is bigger and the profit smaller.\n"
                 "If you're already in, keep to the plan: same stop and take profit."),
        "close_balance": ("\n\n💼 Your lot {lot}: <b>{pnl}</b>\n💰 Your balance now: <b>${bal}</b>\n"
                          "<i>If you didn't open this trade, update your capital: /capital</i>"),
        "paid_ok": "✅ Thank you! Subscription active until {until}.",
        "cancelled": "Cancelled",
        "granted": "🎁 You've been given a subscription until {until}",
        "trial_reminder": ("⏳ Your free trial ends in one hour. "
                           "To keep receiving signals, subscribe: 💎 Subscription"),
        "close_tp": "✅ <b>Signal #{id} {side} closed at Take Profit</b>\n💰 Result: <b>+{pips} pips</b>",
        "close_sl": "❌ <b>Signal #{id} {side} closed at Stop Loss</b>\n📉 Result: −{pips} pips",
        "close_body": ("📍 Entry: {entry}\n🏁 Exit: {exit}\n🛑 SL {sl} · 🎯 TP {tp}\n\n"
                       "📊 Bot stats: {tp_n} TP / {sl_n} SL"),
        "winrate": " (win rate {wr}%)",
        "news_close": ("⚠️ <b>Close trade #{id} ({side} from {entry}) now</b>\n\n"
                       "In {mins} min a major US release is due: <b>{title}</b> (🔴 high impact). "
                       "Gold can jump $10–30 in those minutes and hit the stop.\n\n"
                       "💰 Price now {price}, trade result: <b>{pips} pips</b>. "
                       "Close it at market before the news. The bot no longer tracks this trade."),
        "stats_news": "⚠️ closed before news {exit} ({pips} p.)",
        "mr_head": "🌅 <b>Morning XAUUSD review — {date}</b>\n",
        "mr_price": "💰 Price now: <b>{price}</b> ({ch} pips since the session open at {open})",
        "mr_night": "🌙 Overnight (Asian session): high {hi}, low {lo}, range {rng} pips",
        "mr_prev": "📏 Previous day: high {hi}, low {lo}",
        "mr_swept_hi": "⚡️ Overnight, liquidity above the previous day's high was taken",
        "mr_swept_lo": "⚡️ Overnight, liquidity below the previous day's low was taken",
        "mr_news": "📰 News background for gold: {arrow} {strength}",
        "mr_tfs": "🕒 Trend by timeframe (EMA50): {tfs}",
        "mr_up": "🧭 Main scenario: <b>up</b>. Buyers are in control, the trend is up. While price holds above the overnight low {lo}, BUY has priority; a break of {hi} opens continuation.",
        "mr_down": "🧭 Main scenario: <b>down</b>. Sellers are in control, the trend is down. While price stays below the overnight high {hi}, SELL has priority; a break of {lo} opens continuation.",
        "mr_mixed": "🧭 Scenario: <b>unclear</b>. The overnight move is against the daily trend. Waiting for a break of the {lo}–{hi} range; the bot will signal once a setup is confirmed.",
        "mr_nodata": "🌅 Morning review: no session data yet.",
        "news_bg": "📰 News and geopolitics for gold: {arrow} {strength} — {rel}",
        "news_strong": "strong", "news_moderate": "moderate", "news_weak": "weak",
        "news_with": "<b>supports the trade</b>", "news_against": "<b>against the trade, be careful</b>",
        "news_neutral": "neutral",
        "close_mfe": "📈 Best profit during the trade: <b>+{pips} pips</b> (up to {price})",
        "close_mfe_none": "📈 The trade never went into profit",
        "close_mae": "📉 Max drawdown during the trade: <b>−{pips} pips</b> (down to {price})",
        "close_mae_none": "📉 Almost no drawdown",
        "close_cta": "\n\n💎 To receive signals, subscribe: /subscribe",
        "signal": ("<b>{side} XAUUSD</b>\n\n"
                   "📍 Entry: <b>{entry}</b>\n"
                   "🛑 Stop Loss: <b>{sl}</b> ({sl_pips} pips)\n"
                   "🎯 Take Profit: <b>{tp}</b> ({tp_pips} pips)\n"
                   "⚖️ Risk/reward 1:{rr}\n"
                   "💡 Broker prices differ slightly: set SL {sl_pips} and TP {tp_pips} pips from <b>your own</b> entry price.\n\n"
                   "📊 Strategy: {strategy}\n"
                   "🕒 {when}\n\n"
                   "<i>{note}. Past results do not guarantee future ones. "
                   "Risk no more than 1–2% of your deposit per trade.</i>"),
        "strat_combo": "ICT Silver Bullet + Asian range breakout",
        "strat_fvg": "OB + FVG + BOS with the EMA200 trend",
        "exp_daily_trend": "📈 Daily trend (EMA50): {trend}.",
        "strat_donchian": "Donchian 20 channel breakout with the EMA200 trend (M15)",
        "note_donchian": "XAUUSD backtest 2023–2026, SL 100 / TP 200 pips: 1635 trades, win rate 34.7%, +6900 pips",
        "exp_donchian": "A signal appears on M15 when a candle closes above the high (BUY) or below the low (SELL) of the last 20 candles, with the EMA200 trend.",
        "strat_rsi_m5": "RSI pullback with the daily trend (M5)",
        "note_rsi_m5": "XAUUSD backtest 2023–2026, SL 100 / TP 200 pips: 2462 trades, win rate 35.0%, +12100 pips",
        "exp_rsi_m5": "A signal appears on M5 when RSI returns from a pullback (above 40 for BUY, below 60 for SELL).",
        "exp_portfolio": "The bot watches {n} strategies at once:",
        "strat_fvg_m5": "OB + FVG + BOS with the daily trend (M5)",
        "note_fvg_m5": "XAUUSD backtest 2023–2026, SL 100 / TP 200 pips: 1375 trades, win rate 36.7%, +14000 pips",
        "exp_fvg_m5": "A signal appears on M5 when price breaks the last swing (BOS) with an FVG of the same direction nearby.",
        "strat_squeeze": "Squeeze (Bollinger inside Keltner) with the daily trend",
        "note_squeeze": "XAUUSD backtest 2023–2026, SL 100 / TP 200 pips: 441 trades, win rate 40.8%, +9900 pips",
        "exp_squeeze": "A signal appears on M15 when the market leaves a squeeze and a candle closes outside the Bollinger band.",
        "strat_trendline_m5": "Trendline breakout with the daily trend (M5)",
        "note_trendline_m5": "XAUUSD backtest 2023–2026, SL 100 / TP 200 pips: 1812 trades, win rate 35.2%, +9900 pips",
        "exp_trendline_m5": "A signal appears on M5 when a candle closes beyond the trendline drawn through the last two swings.",
        "strat_liq_m5": "Swing liquidity sweep with the daily trend (M5)",
        "note_liq_m5": "XAUUSD backtest 2023–2026, SL 100 / TP 200 pips: 1917 trades, win rate 34.3%, +5700 pips (2026: +3500)",
        "exp_liq_m5": "A signal appears on M5 when price pierces the last swing high/low (takes the stops) and closes back, with the daily trend.",
        "strat_eqliq_m5": "Equal highs/lows liquidity sweep with the daily trend (M5)",
        "note_eqliq_m5": "XAUUSD backtest 2023–2026, SL 100 / TP 200 pips: 437 trades, win rate 38.9%, +7300 pips (2026: +2800)",
        "exp_eqliq_m5": "A signal appears on M5 when price pierces equal highs or lows (a stop pool) and closes back, with the daily trend.",
        "note_combo": "XAUUSD backtest 2023–2026, SL 100 / TP 200 pips: 632 trades, win rate 36.6%, +6100 pips",
        "note_fvg": "XAUUSD backtest 2023–2026, SL 100 / TP 200 pips: 283 trades, win rate 37.8%, +3800 pips",
        "exp_trend_up": "up (looking for BUY only)",
        "exp_trend_down": "down (looking for SELL only)",
        "exp_fvg": ("H1 trend by EMA200: {trend}.\n"
                    "A signal appears when price breaks the last swing (BOS) with an FVG in the same direction nearby."),
        "exp_asia_forming": "🌏 The Asian range is forming: {lo} – {hi}. Breakout window {start}–{end}.",
        "exp_asia_broken": "🌏 The Asian range has already been broken today.",
        "exp_asia_setup": ("🌏 Expected setup: if an M15 candle closes above {hi} — BUY, "
                           "below {lo} — SELL (until {end})."),
        "exp_asia_next": "🌏 Next Asian range breakout window: {when}.",
        "exp_sb_window": ("🎯 Silver Bullet: window {start}–{end}. Day open {open}, price is {pos} — "
                          "waiting for a {side} FVG."),
        "exp_above": "above",
        "exp_below": "below",
        "exp_sb_next": "🎯 Next Silver Bullet window: {when}.",
        "exp_confirm": "As soon as the setup is confirmed, the bot will send the signal itself.",
        "news_lang": "English",
        "news_head": "📰 <b>Fundamental news: gold and the dollar</b>\n\n",
        "news_none": "No fresh gold or dollar news found in the last 24 hours.",
        "cal_head": "🗓 <b>US news calendar</b> (time: {tz})\n",
        "cal_next": "<b>⏭ Next 3 days</b>",
        "cal_none_next": "No important news",
        "cal_past": "\n<b>⏮ Past 3 days</b>",
        "cal_none_past": "No data",
        "cal_legend": "\n🔴 high impact  🟠 medium",
        "n_fact": "actual {v}",
        "n_forecast": "forecast {v}",
        "n_prev": "prev. {v}",
        "usd_up": "dollar ⬆️, gold ⬇️",
        "usd_down": "dollar ⬇️, gold ⬆️",
        "fact_above": "actual above forecast",
        "fact_below": "actual below forecast",
        "verdict": "Result: {v}",
        "impact_default": "May cause volatility in the dollar and gold",
        "rule_nfp": "Strong jobs → the Fed holds rates longer → dollar ⬆️, gold ⬇️",
        "rule_unemp": "Rising unemployment → rate cuts expected → dollar ⬇️, gold ⬆️",
        "rule_claims": "More jobless claims → weak labor market → dollar ⬇️, gold ⬆️",
        "rule_cpi": "Inflation above forecast → rates stay high longer → dollar ⬆️, gold ⬇️",
        "rule_pce": "The Fed's favorite inflation gauge: above forecast → dollar ⬆️, gold ⬇️",
        "rule_ppi": "Producer prices above forecast → dollar ⬆️, gold ⬇️",
        "rule_rate": "Fed rate decision: hike/hawkish tone → dollar ⬆️, gold ⬇️; cut → the opposite",
        "rule_fomc": "Fed speech: hawkish tone → dollar ⬆️, gold ⬇️; dovish → gold ⬆️",
        "rule_gdp": "Strong GDP → dollar ⬆️, gold ⬇️",
        "rule_retail": "Strong sales → dollar ⬆️, gold ⬇️",
        "rule_pmi": "Business activity above forecast → dollar ⬆️, gold ⬇️",
        "rule_jobs": "More job openings/employment → dollar ⬆️, gold ⬇️",
        "rule_sent": "Consumer optimism → dollar ⬆️, gold ⬇️",
        "pre_head": "⏰ <b>Important US news in 15 minutes</b>\n\n",
        "pre_forecast": "forecast <b>{v}</b>",
        "pre_warn": "⚠️ Sharp moves in gold are possible, be careful with entries.",
        "res_head": "🚨 <b>News released: {title}</b> ({when})\n\n",
        "res_fact": "📊 Actual: <b>{v}</b>",
        "res_forecast": "🎯 Forecast: {v}",
        "res_prev": "⏮ Previous: {v}",
    },
    # ── oʻzbekcha (lotin) ────────────────────────────────────────────────────
    "uz": {
        "lang_name": "🇺🇿 Oʻzbekcha",
        "lang_set": "✅ Til: Oʻzbekcha",
        "btn_signal": "📊 Signal",
        "btn_fund": "📰 Fundamental yangiliklar",
        "btn_cal": "🗓 Yangiliklar taqvimi",
        "btn_sub": "💎 Obuna",
        "btn_profile": "👤 Profil",
        "btn_lang": "🌐 Tilni oʻzgartirish",
        "btn_stats": "📈 Statistika",
        "market_open": ("🟢 <b>Oltin bozori ochildi</b>\n\n"
                        "Yangi setap paydo boʻlishi bilan bot sizga darhol signal yuboradi. Omadli savdo!"),
        "market_closed": "🔴 <b>Oltin bozori yopildi</b> (kunlik tanaffus).\nOchiladi: {when}.",
        "market_closed_week": ("🔴 <b>Oltin bozori dam olish kunlariga yopildi</b>\n\n"
                               "Ochiladi: {when}. Dam oling, yangi signallar keyingi haftada."),
        "btn_accept": "✅ Signalni qabul qilish",
        "btn_decline": "❌ Rad etish",
        "accepted": "✅ Signalimiz #{id} ni qabul qilganingiz uchun rahmat! Savdo yopilganda natija haqida xabar beramiz.",
        "declined": "❌ Siz #{id} signalni rad etdingiz. Yangi signal boʻlganda sizga xabar beramiz. Rahmat!",
        "sig_already_closed": "Bu signal allaqachon yopilgan",
        "stats_head": ("📈 <b>Signallar statistikasi</b>\n\n"
                       "Jami: {total} · ✅ TP: {tp} · ❌ SL: {sl} · ⏳ ochiq: {open}\n"
                       "🎯 Winrate: <b>{wr}</b>\n💰 Natija: <b>{pips} pips</b>\n\n"
                       "<b>Oxirgi signallar:</b>"),
        "stats_row": ("\n\n<b>#{id}</b> {when} {side}\n"
                      "📍 Kirish {entry} · 🛑 SL {sl} · 🎯 TP {tp}\n{result}"),
        "stats_tp": "✅ Take Profit: chiqish {exit}, <b>+{pips} pips</b>",
        "stats_sl": "❌ Stop Loss: chiqish {exit}, −{pips} pips",
        "stats_open": "⏳ Ochiq",
        "stats_empty": "📈 Hali signallar boʻlmagan.",
        "hello": ("👋 Salom, {name}!\n\n"
                  "Men <b>oltin (XAUUSD)</b> boʻyicha signallar botiman.\n"
                  "• 📊 <b>Signal</b> — bozor tahlili va kutilayotgan setap; tasdiqlangan signallar oʻzi keladi\n"
                  "• 📰 <b>Fundamental yangiliklar</b> — yangiliklar oltin va dollarga qanday taʼsir qilishi, qisqacha\n"
                  "• 🗓 <b>Yangiliklar taqvimi</b> — CPI, NFP, FOMC: vaqti va taʼsiri\n\n"),
        "trader": "treyder",
        "trial_new": "🎁 Sizga <b>{days} kunlik bepul kirish</b> ochildi: signallar avtomatik keladi.",
        "st_start": "/start ni bosing",
        "st_paid": "💎 Obuna {until} gacha faol",
        "st_trial": "🎁 Bepul davr {until} gacha",
        "st_expired": "⛔️ Bepul davr tugadi. Signallarni olish uchun obuna boʻling.",
        "inv_title": "XAUUSD signallariga obuna — {days} kun",
        "inv_desc": "Oltin boʻyicha avtomatik signallar: grafik, kirish, SL va TP bilan.",
        "inv_label": "{days} kun",
        "sig_expired": "⛔️ Bepul davr tugadi. Signallar faqat obuna orqali.",
        "analyzing": "🔎 Bozorni tahlil qilyapman…",
        "quotes_fail": "Narxlarni olib boʻlmadi, bir daqiqadan soʻng qayta urinib koʻring.",
        "price_now": "\n\n💰 Hozirgi narx: <b>{price}</b>",
        "open_signal": "\n\n📌 Ochiq signal #{id}: {side}, kirish {entry}, SL {sl}, TP {tp}",
        "analysis_head": "📊 <b>XAUUSD tahlili</b>",
        "news_wait": "⏳ Soʻnggi yangiliklarni yigʻyapman…",
        "news_fail": "Yangiliklarni yuklab boʻlmadi, keyinroq urinib koʻring.",
        "sub_price": "Obuna: {days} kun uchun <b>{price} ⭐</b>.",
        "profile": "🆔 {id}\n{status}\n🌐 Til: {language}",
        "ask_capital": ("💰 <b>Savdo uchun kapitalingiz (depozit) qancha?</b>\n\n"
                        "Tugmani tanlang yoki summani dollarda yozing, masalan <code>150</code>. "
                        "Shu boʻyicha bot har bir signalda sizning savdo hajmingizni (lot) koʻrsatadi."),
        "btn_skip": "Oʻtkazib yuborish",
        "btn_capital": "💰 Kapitalni oʻzgartirish",
        "cap_set": "✅ Kapital: <b>${cap}</b>\n📦 Signallardagi lotingiz: <b>{lot}</b>",
        "cap_skipped": "Yaxshi. Kapitalni keyin koʻrsatish mumkin: 👤 Profil yoki /capital",
        "cap_bad": "Summani raqam bilan yozing, masalan <code>150</code>",
        "profile_cap": "\n💰 Kapital: ${cap} · lot {lot}",
        "profile_nocap": "\n💰 Kapital koʻrsatilmagan (/capital)",
        "sig_lot": ("\n\n📦 <b>Sizning lotingiz: {lot}</b> (kapital ${cap})\n"
                    "🛑 Stop boʻlsa: −${loss} ({loss_pct}%) · 🎯 Teyk boʻlsa: +${profit}"),
        "sig_lot_warn": "\n⚠️ Kapital kichik: hatto minimal lot 0.01 ham {loss_pct}% risk, bu {pct}% dan koʻp.",
        "sig_nocap": "\n\n💰 Kapitalingizni koʻrsating, bot lotingizni koʻrsatadi: /capital",
        "sig_rules": ("\n\n❗️ <b>Aynan bot tavsiya qilgandek savdo qiling</b>: shu lot, shu stop va shu teyk. "
                      "Ketma-ket 2–3 ta stop boʻlishi mumkin, bu normal. Kun davomida ketma-ket {n} ta stopdan keyin bot savdo kunini yopadi."),
        "day_closed": ("🛑 <b>Savdo kuni yopildi</b>\n\n"
                       "Ketma-ket {n} ta stop oldik. Depozitni asrash uchun bugun boshqa savdo qilmaymiz. Ertaga davom etamiz 💪"),
        "day_closed_cap": "\n\n💰 Hozirgi kapitalingiz: <b>${cap}</b>",
        "late_hint_buy": "\n⏱ Narx <b>{limit}</b> dan yuqori boʻlmaguncha kiring. Yuqori boʻlsa, kech qoldingiz, savdoni ochmang.",
        "late_hint_sell": "\n⏱ Narx <b>{limit}</b> dan past boʻlmaguncha kiring. Past boʻlsa, kech qoldingiz, savdoni ochmang.",
        "late": ("⚠️ <b>Signal #{id} {side}: kirish endi dolzarb emas</b>\n\n"
                 "Narx kirish {entry} dan {pips} pips uzoqlashdi va hozir {price}.\n"
                 "Agar savdoni hali ochmagan boʻlsangiz, <b>kirmang</b>: kech qoldingiz, risk kattaroq, foyda kamroq.\n"
                 "Savdoda boʻlsangiz, reja boʻyicha ushlab turing: stop va teyk oʻsha."),
        "close_balance": ("\n\n💼 Lotingiz {lot}: <b>{pnl}</b>\n💰 Balansingiz endi: <b>${bal}</b>\n"
                          "<i>Agar bu savdoni ochmagan boʻlsangiz, kapitalni yangilang: /capital</i>"),
        "paid_ok": "✅ Rahmat! Obuna {until} gacha faol.",
        "cancelled": "Bekor qilindi",
        "granted": "🎁 Sizga {until} gacha obuna berildi",
        "trial_reminder": ("⏳ Bepul davr bir soatdan keyin tugaydi. "
                           "Signallarni olishda davom etish uchun obuna boʻling: 💎 Obuna"),
        "close_tp": "✅ <b>Signal #{id} {side} Take Profit boʻyicha yopildi</b>\n💰 Natija: <b>+{pips} pips</b>",
        "close_sl": "❌ <b>Signal #{id} {side} Stop Loss boʻyicha yopildi</b>\n📉 Natija: −{pips} pips",
        "close_body": ("📍 Kirish: {entry}\n🏁 Chiqish: {exit}\n🛑 SL {sl} · 🎯 TP {tp}\n\n"
                       "📊 Bot statistikasi: {tp_n} TP / {sl_n} SL"),
        "winrate": " (winrate {wr}%)",
        "news_close": ("⚠️ <b>#{id} savdoni ({side}, {entry} dan) hozir yoping</b>\n\n"
                       "{mins} daqiqadan soʻng AQShning muhim yangiligi chiqadi: <b>{title}</b> (🔴 yuqori muhimlik). "
                       "Bunday daqiqalarda oltin $10–30 ga keskin sakrab, stopni urib ketishi mumkin.\n\n"
                       "💰 Hozirgi narx {price}, savdo natijasi: <b>{pips} pips</b>. "
                       "Yangilikni kutmasdan bozor narxida yoping. Bot bu savdoni endi kuzatmaydi."),
        "stats_news": "⚠️ yangilikdan oldin yopildi {exit} ({pips} p.)",
        "mr_head": "🌅 <b>XAUUSD ertalabki tahlil — {date}</b>\n",
        "mr_price": "💰 Hozirgi narx: <b>{price}</b> (sessiya ochilishidan {open} beri {ch} pips)",
        "mr_night": "🌙 Tunda (Osiyo sessiyasi): maksimum {hi}, minimum {lo}, diapazon {rng} pips",
        "mr_prev": "📏 Oldingi kun: maksimum {hi}, minimum {lo}",
        "mr_swept_hi": "⚡️ Tunda oldingi kun maksimumidan yuqoridagi likvidlik olindi",
        "mr_swept_lo": "⚡️ Tunda oldingi kun minimumidan pastdagi likvidlik olindi",
        "mr_news": "📰 Oltin uchun yangiliklar foni: {arrow} {strength}",
        "mr_tfs": "🕒 Taymfreymlar boʻyicha trend (EMA50): {tfs}",
        "mr_up": "🧭 Asosiy ssenariy: <b>oʻsish</b>. Bozorni xaridorlar boshqarmoqda, trend yuqoriga. Narx tungi minimum {lo} dan yuqori ekan, BUY ustuvor; {hi} yorib oʻtilsa davomi ochiladi.",
        "mr_down": "🧭 Asosiy ssenariy: <b>pasayish</b>. Bozorni sotuvchilar boshqarmoqda, trend pastga. Narx tungi maksimum {hi} dan past ekan, SELL ustuvor; {lo} yorib oʻtilsa davomi ochiladi.",
        "mr_mixed": "🧭 Ssenariy: <b>noaniq</b>. Tungi harakat kunlik trendga qarshi. {lo}–{hi} diapazonidan chiqishni kutamiz; setap tasdiqlanganda bot signal beradi.",
        "mr_nodata": "🌅 Ertalabki tahlil: sessiya boʻyicha hali maʼlumot yoʻq.",
        "news_bg": "📰 Oltin uchun yangiliklar va geosiyosat foni: {arrow} {strength} — {rel}",
        "news_strong": "kuchli", "news_moderate": "oʻrtacha", "news_weak": "kuchsiz",
        "news_with": "<b>savdo foydasiga</b>", "news_against": "<b>savdoga qarshi, ehtiyot boʻling</b>",
        "news_neutral": "neytral",
        "close_mfe": "📈 Savdo davomida eng koʻp foyda: <b>+{pips} pips</b> ({price} gacha)",
        "close_mfe_none": "📈 Savdo foydaga chiqmadi",
        "close_mae": "📉 Eng katta pasayish: <b>−{pips} pips</b> ({price} gacha)",
        "close_mae_none": "📉 Deyarli pasayish boʻlmadi",
        "close_cta": "\n\n💎 Signallarni olish uchun obuna boʻling: /subscribe",
        "signal": ("<b>{side} XAUUSD</b>\n\n"
                   "📍 Kirish: <b>{entry}</b>\n"
                   "🛑 Stop Loss: <b>{sl}</b> ({sl_pips} pips)\n"
                   "🎯 Take Profit: <b>{tp}</b> ({tp_pips} pips)\n"
                   "⚖️ Risk/foyda 1:{rr}\n"
                   "💡 Brokerlarda narx biroz farq qiladi: SL {sl_pips} va TP {tp_pips} pipsni <b>oʻzingizning</b> kirish narxingizdan qoʻying.\n\n"
                   "📊 Strategiya: {strategy}\n"
                   "🕒 {when}\n\n"
                   "<i>{note}. Oʻtgan natijalar kelajakdagi natijalarni kafolatlamaydi. "
                   "Bitta savdoda depozitning 1–2% idan koʻp tavakkal qilmang.</i>"),
        "strat_combo": "ICT Silver Bullet + Osiyo diapazonini yorib oʻtish",
        "strat_fvg": "EMA200 trendi boʻyicha OB + FVG + BOS",
        "exp_daily_trend": "📈 Kunlik trend (EMA50): {trend}.",
        "strat_donchian": "EMA200 trendi boʻyicha Donchian 20 kanalini yorib oʻtish (M15)",
        "note_donchian": "XAUUSD bektesti 2023–2026, SL 100 / TP 200 pips: 1635 ta savdo, winrate 34.7%, +6900 pips",
        "exp_donchian": "Sham EMA200 trendi boʻyicha oxirgi 20 ta shamning maksimumidan yuqori (BUY) yoki minimumidan past (SELL) yopilganda M15 da signal chiqadi.",
        "strat_rsi_m5": "Kunlik trend boʻyicha RSI qaytishi (M5)",
        "note_rsi_m5": "XAUUSD bektesti 2023–2026, SL 100 / TP 200 pips: 2462 ta savdo, winrate 35.0%, +12100 pips",
        "exp_rsi_m5": "RSI qaytish zonasidan chiqqanda (BUY uchun 40 dan yuqori, SELL uchun 60 dan past) M5 da signal chiqadi.",
        "exp_portfolio": "Bot birdaniga {n} ta strategiyani kuzatadi:",
        "strat_fvg_m5": "Kunlik trend boʻyicha OB + FVG + BOS (M5)",
        "note_fvg_m5": "XAUUSD bektesti 2023–2026, SL 100 / TP 200 pips: 1375 ta savdo, winrate 36.7%, +14000 pips",
        "exp_fvg_m5": "Narx oxirgi svingni yorib oʻtganda (BOS) va yonida shu yoʻnalishdagi FVG boʻlganda M5 da signal chiqadi.",
        "strat_squeeze": "Kunlik trend boʻyicha Squeeze (Keltner ichida Bollinger)",
        "note_squeeze": "XAUUSD bektesti 2023–2026, SL 100 / TP 200 pips: 441 ta savdo, winrate 40.8%, +9900 pips",
        "exp_squeeze": "Bozor siqilishdan chiqib, sham Bollinger chizigʻidan tashqarida yopilganda M15 da signal chiqadi.",
        "strat_trendline_m5": "Kunlik trend boʻyicha trend chizigʻini yorib oʻtish (M5)",
        "note_trendline_m5": "XAUUSD bektesti 2023–2026, SL 100 / TP 200 pips: 1812 ta savdo, winrate 35.2%, +9900 pips",
        "exp_trendline_m5": "Sham oxirgi ikki sving orqali chizilgan trend chizigʻidan tashqarida yopilganda M5 da signal chiqadi.",
        "strat_liq_m5": "Kunlik trend boʻyicha sving ortidagi likvidlikni olish (M5)",
        "note_liq_m5": "XAUUSD bektesti 2023–2026, SL 100 / TP 200 pips: 1917 ta savdo, winrate 34.3%, +5700 pips (2026: +3500)",
        "exp_liq_m5": "Narx oxirgi sving maksimumi/minimumini teshib (stoplarni olib) kunlik trend boʻyicha qaytib yopilganda M5 da signal chiqadi.",
        "strat_eqliq_m5": "Kunlik trend boʻyicha teng maksimum/minimumlar ortidagi likvidlikni olish (M5)",
        "note_eqliq_m5": "XAUUSD bektesti 2023–2026, SL 100 / TP 200 pips: 437 ta savdo, winrate 38.9%, +7300 pips (2026: +2800)",
        "exp_eqliq_m5": "Narx teng maksimum yoki minimumlarni (stoplar havzasi) teshib kunlik trend boʻyicha qaytib yopilganda M5 da signal chiqadi.",
        "note_combo": "XAUUSD bektesti 2023–2026, SL 100 / TP 200 pips: 632 ta savdo, winrate 36.6%, +6100 pips",
        "note_fvg": "XAUUSD bektesti 2023–2026, SL 100 / TP 200 pips: 283 ta savdo, winrate 37.8%, +3800 pips",
        "exp_trend_up": "yuqoriga (faqat BUY qidiramiz)",
        "exp_trend_down": "pastga (faqat SELL qidiramiz)",
        "exp_fvg": ("H1 da EMA200 boʻyicha trend: {trend}.\n"
                    "Narx oxirgi swingni yorib oʻtganda (BOS) va yonida shu yoʻnalishdagi FVG boʻlsa, signal chiqadi."),
        "exp_asia_forming": "🌏 Osiyo diapazoni shakllanmoqda: {lo} – {hi}. Yorib oʻtish oynasi {start}–{end}.",
        "exp_asia_broken": "🌏 Bugun Osiyo diapazoni allaqachon yorib oʻtildi.",
        "exp_asia_setup": ("🌏 Kutilayotgan setap: M15 shami {hi} dan yuqorida yopilsa — BUY, "
                           "{lo} dan pastda yopilsa — SELL ({end} gacha)."),
        "exp_asia_next": "🌏 Osiyo diapazonini yorib oʻtishning keyingi oynasi: {when}.",
        "exp_sb_window": ("🎯 Silver Bullet: oyna {start}–{end}. Kun ochilishi {open}, narx {pos} — "
                          "{side} uchun FVG kutamiz."),
        "exp_above": "yuqorida",
        "exp_below": "pastda",
        "exp_sb_next": "🎯 Silver Bulletning keyingi oynasi: {when}.",
        "exp_confirm": "Setap tasdiqlanishi bilan bot signalni oʻzi yuboradi.",
        "news_lang": "Uzbek (Latin script)",
        "news_head": "📰 <b>Fundamental yangiliklar: oltin va dollar</b>\n\n",
        "news_none": "Oxirgi bir kunda oltin va dollar boʻyicha yangi xabarlar topilmadi.",
        "cal_head": "🗓 <b>AQSh yangiliklar taqvimi</b> (vaqt: {tz})\n",
        "cal_next": "<b>⏭ Yaqin 3 kun</b>",
        "cal_none_next": "Muhim yangiliklar yoʻq",
        "cal_past": "\n<b>⏮ Oʻtgan 3 kun</b>",
        "cal_none_past": "Maʼlumot yoʻq",
        "cal_legend": "\n🔴 yuqori muhimlik  🟠 oʻrta",
        "n_fact": "fakt {v}",
        "n_forecast": "prognoz {v}",
        "n_prev": "oldingi {v}",
        "usd_up": "dollar ⬆️, oltin ⬇️",
        "usd_down": "dollar ⬇️, oltin ⬆️",
        "fact_above": "fakt prognozdan yuqori",
        "fact_below": "fakt prognozdan past",
        "verdict": "Natija: {v}",
        "impact_default": "Dollar va oltinda keskin tebranishlarga olib kelishi mumkin",
        "rule_nfp": "Kuchli bandlik → FED stavkani uzoqroq ushlab turadi → dollar ⬆️, oltin ⬇️",
        "rule_unemp": "Ishsizlik oʻsishi → stavka pasayishi kutiladi → dollar ⬇️, oltin ⬆️",
        "rule_claims": "Nafaqa arizalari koʻpaydi → mehnat bozori zaif → dollar ⬇️, oltin ⬆️",
        "rule_cpi": "Inflyatsiya prognozdan yuqori → stavka uzoqroq yuqori qoladi → dollar ⬆️, oltin ⬇️",
        "rule_pce": "FEDning asosiy inflyatsiya koʻrsatkichi: prognozdan yuqori → dollar ⬆️, oltin ⬇️",
        "rule_ppi": "Ishlab chiqaruvchi narxlari prognozdan yuqori → dollar ⬆️, oltin ⬇️",
        "rule_rate": "FED stavka qarori: oshirish/qattiq ohang → dollar ⬆️, oltin ⬇️; pasaytirish → aksincha",
        "rule_fomc": "FED nutqi: qattiq ohang → dollar ⬆️, oltin ⬇️; yumshoq → oltin ⬆️",
        "rule_gdp": "Kuchli YaIM → dollar ⬆️, oltin ⬇️",
        "rule_retail": "Kuchli chakana savdo → dollar ⬆️, oltin ⬇️",
        "rule_pmi": "Ishbilarmonlik faolligi prognozdan yuqori → dollar ⬆️, oltin ⬇️",
        "rule_jobs": "Boʻsh ish oʻrinlari/bandlik koʻpaydi → dollar ⬆️, oltin ⬇️",
        "rule_sent": "Isteʼmolchilar optimizmi → dollar ⬆️, oltin ⬇️",
        "pre_head": "⏰ <b>15 daqiqadan soʻng AQShning muhim yangiligi</b>\n\n",
        "pre_forecast": "prognoz <b>{v}</b>",
        "pre_warn": "⚠️ Oltinda keskin harakatlar boʻlishi mumkin, savdoga kirishda ehtiyot boʻling.",
        "res_head": "🚨 <b>Yangilik chiqdi: {title}</b> ({when})\n\n",
        "res_fact": "📊 Fakt: <b>{v}</b>",
        "res_forecast": "🎯 Prognoz: {v}",
        "res_prev": "⏮ Oldingi: {v}",
    },
}


def norm(lang: str | None) -> str:
    return lang if lang in TEXTS else DEFAULT


def t(lang: str | None, key: str, **kw) -> str:
    s = TEXTS[norm(lang)].get(key) or TEXTS[DEFAULT][key]
    return s.format(**kw) if kw else s


def variants(key: str) -> set[str]:
    """Все переводы ключа — чтобы ловить нажатия кнопок меню на любом языке."""
    return {TEXTS[lang][key] for lang in TEXTS}


def per_lang(make) -> dict[str, str]:
    """{язык: текст} для рассылок."""
    return {lang: make(lang) for lang in TEXTS}
