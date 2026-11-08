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
        "close_cta": "\n\n💎 Чтобы получать сигналы, оформите подписку: /subscribe",
        "signal": ("<b>{side} XAUUSD</b>\n\n"
                   "📍 Вход: <b>{entry}</b>\n"
                   "🛑 Stop Loss: <b>{sl}</b> ({sl_pips} пипсов)\n"
                   "🎯 Take Profit: <b>{tp}</b> ({tp_pips} пипсов)\n"
                   "⚖️ Риск/прибыль 1:{rr}\n\n"
                   "📊 Стратегия: {strategy}\n"
                   "🕒 {when}\n\n"
                   "<i>{note}. Прошлые результаты не гарантируют будущих. "
                   "Рискуйте не больше 1–2% депозита на сделку.</i>"),
        "strat_combo": "ICT Silver Bullet + пробой азиатского диапазона",
        "strat_fvg": "OB + FVG + BOS по тренду EMA200",
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
        "close_cta": "\n\n💎 To receive signals, subscribe: /subscribe",
        "signal": ("<b>{side} XAUUSD</b>\n\n"
                   "📍 Entry: <b>{entry}</b>\n"
                   "🛑 Stop Loss: <b>{sl}</b> ({sl_pips} pips)\n"
                   "🎯 Take Profit: <b>{tp}</b> ({tp_pips} pips)\n"
                   "⚖️ Risk/reward 1:{rr}\n\n"
                   "📊 Strategy: {strategy}\n"
                   "🕒 {when}\n\n"
                   "<i>{note}. Past results do not guarantee future ones. "
                   "Risk no more than 1–2% of your deposit per trade.</i>"),
        "strat_combo": "ICT Silver Bullet + Asian range breakout",
        "strat_fvg": "OB + FVG + BOS with the EMA200 trend",
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
        "close_cta": "\n\n💎 Signallarni olish uchun obuna boʻling: /subscribe",
        "signal": ("<b>{side} XAUUSD</b>\n\n"
                   "📍 Kirish: <b>{entry}</b>\n"
                   "🛑 Stop Loss: <b>{sl}</b> ({sl_pips} pips)\n"
                   "🎯 Take Profit: <b>{tp}</b> ({tp_pips} pips)\n"
                   "⚖️ Risk/foyda 1:{rr}\n\n"
                   "📊 Strategiya: {strategy}\n"
                   "🕒 {when}\n\n"
                   "<i>{note}. Oʻtgan natijalar kelajakdagi natijalarni kafolatlamaydi. "
                   "Bitta savdoda depozitning 1–2% idan koʻp tavakkal qilmang.</i>"),
        "strat_combo": "ICT Silver Bullet + Osiyo diapazonini yorib oʻtish",
        "strat_fvg": "EMA200 trendi boʻyicha OB + FVG + BOS",
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
