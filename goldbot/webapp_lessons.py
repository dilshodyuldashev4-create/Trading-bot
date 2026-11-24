"""Уроки раздела «Обучение» в Mini App (ru, en, uz).

У каждого урока одинаковые id, иконки и порядок блоков во всех языках (проверяет тест), меняется только текст.
Блоки: p — абзац, h — подзаголовок, list — список, tip — совет, warn — предупреждение, ex — пример-таблица
(h — заголовок, rows — строки «название — значение»), plans — таблица счетов FundedNext из goldbot/prop.py,
calc — калькулятор лота, go — кнопка перехода (to: profile / prop / stats / connect).
В тексте подставляются {risk} {prop_risk} {prop_strong} {at_risk} {usd} — настройки бота (см. lessons_vars).

Правила FundedNext сверены с fundednext.com/general-rules/cfds/trading-objectives (11.2026).
Числа защиты проп-счёта — из goldbot/prop.py и reports/challenge_research.md.
"""
from __future__ import annotations

from .config import config


def lessons_vars() -> dict:
    return {"risk": f"{config.lot_risk_pct:g}", "prop_risk": f"{config.prop_risk_pct:g}",
            "prop_strong": f"{config.prop_strong_risk_pct:g}", "at_risk": f"{config.autotrade_risk_pct:g}",
            "usd": f"{config.autotrade_month_usd:g}"}


def _l(id_: str, icon: str, minutes: int, title: str, sub: str, blocks: list, q: str, answers: list, why: str) -> dict:
    """answers[0] — верный ответ (приложение перемешивает варианты)."""
    return {"id": id_, "icon": icon, "min": minutes, "title": title, "sub": sub, "blocks": blocks,
            "quiz": {"q": q, "a": answers, "why": why}}


RU = [
    _l("signal", "📡", 3, "Что такое сигнал", "BUY и SELL, вход, стоп, тейк и пипсы", [
        {"t": "p", "x": "Сигнал — готовая идея сделки по золоту (XAUUSD): где входить, где выйти с небольшим убытком "
                        "и где забрать прибыль. Бот присылает его сообщением в чат — с графиком и лотом под ваш капитал."},
        {"t": "ex", "h": "Пример сигнала", "rows": [["Направление", "BUY"], ["Вход", "2650.00"],
                                                   ["SL (стоп)", "2640.00"], ["TP (тейк)", "2670.00"]]},
        {"t": "list", "x": ["BUY — покупка: зарабатываете, если цена растёт.",
                            "SELL — продажа: зарабатываете, если цена падает.",
                            "Вход — цена, по которой открывается сделка.",
                            "SL (Stop Loss) — цена, где сделка закроется с небольшим убытком.",
                            "TP (Take Profit) — цена, где сделка закроется с прибылью."]},
        {"t": "tip", "x": "Пипс на золоте — это $0.10 движения цены. От 2650.00 до 2660.00 — 100 пипсов."},
        {"t": "h", "x": "Чем заканчивается сигнал"},
        {"t": "list", "x": ["Take Profit — цена дошла до цели, прибыль зафиксирована.",
                            "Stop Loss — сделка закрыта по стопу с небольшим убытком.",
                            "Безубыток — стоп был перенесён на вход, сделка закрылась около нуля.",
                            "«Часть зафиксирована» — часть позиции уже закрыта с прибылью на промежуточной цели.",
                            "Закрыт при развороте или перед новостью — бот вышел заранее, чтобы не рисковать."]},
        {"t": "warn", "x": "Входите по цене, близкой к цене входа. Если цена уже ушла далеко к тейку — лучше "
                           "пропустить: прибыли остаётся меньше, а риск тот же."},
    ], "Сигнал SELL, вход 2650.00. Цена опустилась до 2640.00. Что со сделкой?",
        ["В плюсе: +100 пипсов", "В минусе: −100 пипсов", "Ровно в нуле"],
        "SELL зарабатывает на падении. Цена упала на $10 — это +100 пипсов."),

    _l("sltp", "🎯", 3, "Стоп и тейк", "Почему стоп обязателен и как работает 1 : 2", [
        {"t": "p", "x": "Стоп — это страховка. Без него одна неудачная сделка может съесть месяц прибыли или весь "
                        "депозит. В каждом сигнале бота стоп уже указан — ставьте его сразу при открытии сделки."},
        {"t": "ex", "h": "Риск к прибыли 1 : 2", "rows": [["Стоп", "100 пипсов"], ["Тейк", "200 пипсов"],
                                                         ["Один тейк перекрывает", "два стопа"],
                                                         ["Чтобы быть в плюсе, хватает", "34% прибыльных сделок"]]},
        {"t": "list", "x": ["Не отодвигайте стоп дальше, когда цена идёт против вас: убыток только вырастет.",
                            "Не закрывайте прибыльную сделку раньше времени из страха: тогда тейки не окупят стопы.",
                            "Стоп — нормальная часть торговли. Даже у сильной стратегии бывает 3–5 стопов подряд."]},
        {"t": "tip", "x": "Безубыток: когда цена прошла часть пути к тейку, стоп переносят на цену входа. "
                          "После этого сделка уже не принесёт убытка."},
    ], "Стоп 100 пипсов, тейк 200. Из 10 сделок 4 в плюс и 6 в минус. Какой итог?",
        ["+200 пипсов", "−200 пипсов", "0 пипсов"],
        "4 × 200 = 800, 6 × 100 = 600. Итог +200, хотя убыточных сделок больше."),

    _l("lot", "⚖️", 4, "Лот и риск", "Сколько ставить, чтобы не слить депозит", [
        {"t": "p", "x": "Лот — объём сделки. На золоте 1 лот = 100 унций, а 0.01 лота = 1 унция: движение цены "
                        "на $1 даёт $1 прибыли или убытка."},
        {"t": "ex", "h": "Сколько стоят 100 пипсов ($10 движения цены)",
         "rows": [["0.01 лота", "$10"], ["0.05 лота", "$50"], ["0.10 лота", "$100"], ["1.00 лот", "$1 000"]]},
        {"t": "p", "x": "Лот считают от риска: сколько процентов капитала вы готовы потерять, если сработает стоп. "
                        "Убыток по стопу на каждые 0.01 лота = стоп в пипсах × $0.10."},
        {"t": "calc"},
        {"t": "warn", "x": "Риск больше 2% на сделку — путь к сливу. 10 стопов подряд при риске 1% — это около −10% "
                           "депозита, при риске 5% — около −40%."},
        {"t": "tip", "x": "Бот сам считает лот в каждом сигнале — с риском {risk}% от капитала, который указан в "
                          "профиле. Меньше 0.01 лота брокер не откроет: при маленьком капитале риск может быть выше, "
                          "и бот об этом предупредит."},
        {"t": "go", "to": "profile", "x": "Указать капитал"},
    ], "Капитал $2 000, риск 1%, стоп 100 пипсов. Какой лот?",
        ["0.02", "0.20", "0.01"],
        "1% от $2 000 = $20. Стоп 100 пипсов стоит $10 на 0.01 лота, значит лот 0.02."),

    _l("prop", "🏆", 4, "Проп-челлендж", "Как получить счёт FundedNext и этапы", [
        {"t": "p", "x": "Проп-фирма (например, FundedNext) даёт торговать на своём капитале. Вы покупаете челлендж, "
                        "показываете прибыль и дисциплину и получаете финансируемый счёт. Прибыль делится с фирмой: "
                        "трейдеру обычно 80%, с дополнениями — до 95%."},
        {"t": "list", "x": ["Этап 1 — достичь цели по прибыли и не нарушить лимиты.",
                            "Этап 2 (в 2-Step и Lite) — вторая цель, поменьше.",
                            "Финансируемый счёт — цели нет: вы получаете выплаты с прибыли, главное — беречь лимиты."]},
        {"t": "plans"},
        {"t": "list", "x": ["Срока на прохождение нет — спешить не нужно.",
                            "Торговый день засчитывается, если в этот день была сделка с ненулевым результатом.",
                            "Цель считается только по закрытым сделкам.",
                            "Нарушен лимит хотя бы на цент — счёт закрывают. Поэтому риск на проп-счёте меньше обычного."]},
        {"t": "tip", "x": "Правила фирм меняются. Перед покупкой сверьтесь с личным кабинетом FundedNext."},
        {"t": "go", "to": "prop", "x": "Открыть проп-панель"},
    ], "Счёт Stellar 2-Step на $10 000, этап 1. Какой баланс нужен, чтобы выполнить цель?",
        ["$10 800", "$10 500", "$11 000"],
        "Цель первого этапа 2-Step — 8%: $10 000 + $800 = $10 800."),

    _l("limits", "🛡", 5, "Дневной и общий лимит", "И почему бот останавливает день после стопа", [
        {"t": "p", "x": "Главное в пропе — два лимита просадки. Нарушение любого из них сразу закрывает счёт."},
        {"t": "ex", "h": "Пример: Stellar 2-Step на $25 000",
         "rows": [["Дневной лимит 5%", "−$1 250 за день"], ["Общий лимит 10%", "баланс не ниже $22 500"]]},
        {"t": "list", "x": ["Дневной лимит — процент от начального размера счёта. В него входят закрытые и открытые "
                            "сделки, своп и комиссия.",
                            "Новый торговый день начинается в 00:00 по времени сервера FundedNext.",
                            "Общий лимит в 2-Step, 1-Step и Lite статичный: граница не двигается.",
                            "В Instant общий лимит плавающий: поднимается вслед за прибылью и останавливается на "
                            "начальном балансе. Счёт $10 000, граница $9 400; баланс вырос до $10 500 — граница $9 900."]},
        {"t": "h", "x": "Почему бот не торгует после стопа"},
        {"t": "p", "x": "Убытки на золоте идут сериями: после первого стопа за день следующие сделки того же дня "
                        "в среднем убыточны. Поэтому после первого Stop Loss бот до полуночи FundedNext новые "
                        "проп-сделки не открывает. На истории XAUUSD с декабря 2023 года челлендж 2-Step без этой "
                        "защиты не проходил примерно 1 раз из 5, с ней — ни разу из ~640 попыток."},
        {"t": "list", "x": ["Риск на сделку — {prop_risk}% счёта, на сильном сигнале {prop_strong}%, никогда больше 1%.",
                            "Все открытые сделки вместе — не больше 1.5% счёта.",
                            "За день — не больше 3% и всегда с запасом до лимита фирмы.",
                            "Баланс ниже начального на 2% — риск снижается в 4 раза, пока счёт не восстановится."]},
    ], "Stellar 1-Step на $10 000, дневной лимит 3% ($300). Закрыто −$150, открытая сделка в −$60. "
       "Сколько ещё можно потерять сегодня?",
        ["$90", "$150", "$240"],
        "Открытые сделки тоже считаются: 300 − 150 − 60 = $90."),

    _l("stats", "📊", 3, "Как читать статистику", "Винрейт, профит-фактор, просадка", [
        {"t": "list", "x": ["Винрейт — доля прибыльных сделок среди закрытых. Сам по себе мало что значит: важно, "
                            "сколько приносит тейк и сколько забирает стоп.",
                            "Итог — сумма пипсов всех закрытых сигналов.",
                            "Профит-фактор — вся прибыль ÷ весь убыток. Больше 1 — стратегия в плюсе, от 1.5 — хорошо.",
                            "Макс. просадка — самое глубокое падение от вершины. Будьте готовы, что оно повторится.",
                            "Серия побед — больше всего прибыльных сделок подряд.",
                            "Кривая доходности — как росла сумма пипсов. Ровный рост лучше резких скачков."]},
        {"t": "ex", "h": "Пипсы в деньги", "rows": [["+500 пипсов при 0.01 лота", "+$50"],
                                                    ["+500 пипсов при 0.10 лота", "+$500"]]},
        {"t": "tip", "x": "Смотрите период 90 дней или «Всё»: за неделю случайность решает больше, чем стратегия."},
        {"t": "warn", "x": "Прошлые результаты не гарантируют будущих. Торгуйте только деньгами, которые готовы потерять."},
        {"t": "go", "to": "stats", "x": "Открыть статистику"},
    ], "За месяц прибыльные сделки дали 3 000 пипсов, убыточные забрали 2 000. Какой профит-фактор?",
        ["1.5", "1 000", "0.67"],
        "Профит-фактор = 3 000 ÷ 2 000 = 1.5. Стратегия в плюсе."),

    _l("auto", "🤖", 4, "Автоторговля", "Как подключить счёт MT4/MT5", [
        {"t": "p", "x": "Автоторговля — бот сам открывает и закрывает сделки по своим сигналам на вашем счёте "
                        "MetaTrader 4 или 5. Не нужно сидеть у телефона."},
        {"t": "list", "x": ["Нажмите «Подключить счёт» — продолжение будет в чате бота.",
                            "Выберите MT4 или MT5, укажите сервер брокера и номер счёта.",
                            "Отправьте основной (торговый) пароль. Бот сразу удалит сообщение с паролем из чата.",
                            "Готово: бот торгует по сигналам с риском {at_risk}% от средств на сделку."]},
        {"t": "warn", "x": "Инвесторский пароль (только просмотр) для торговли не подходит: с ним бот лишь берёт цены. "
                           "Счёт с нулевым балансом тоже работает только для цен — после пополнения бот начнёт торговать сам."},
        {"t": "list", "x": ["Пароль передаётся в защищённый сервис MetaApi и не хранится в базе бота.",
                            "Пауза и запуск — в приложении на вкладке «Проп».",
                            "Отключить счёт и удалить пароль можно в любой момент."]},
        {"t": "ex", "h": "Счёт FundedNext для бота", "rows": [["Платформа", "MT4 или MT5"], ["Размер", "до $25 000"],
                                                             ["Дополнение «EA»", "обязательно при покупке"]]},
        {"t": "p", "x": "Стоимость — ${usd} в месяц за счёт, оплата Telegram Stars, можно частями."},
        {"t": "go", "to": "connect", "x": "Подключить счёт"},
    ], "Каким паролем подключать счёт для автоторговли?",
        ["Основным (торговым)", "Инвесторским", "Паролем от сайта брокера"],
        "Только основной пароль даёт боту право открывать сделки. Инвесторский — лишь для просмотра."),
]

EN = [
    _l("signal", "📡", 3, "What a signal is", "BUY and SELL, entry, stop, take and pips", [
        {"t": "p", "x": "A signal is a ready trade idea for gold (XAUUSD): where to enter, where to exit with a small "
                        "loss and where to take profit. The bot sends it to the chat with a chart and a lot sized for "
                        "your capital."},
        {"t": "ex", "h": "Signal example", "rows": [["Direction", "BUY"], ["Entry", "2650.00"],
                                                    ["SL (stop)", "2640.00"], ["TP (take)", "2670.00"]]},
        {"t": "list", "x": ["BUY — you earn if the price goes up.",
                            "SELL — you earn if the price goes down.",
                            "Entry — the price at which the trade is opened.",
                            "SL (Stop Loss) — the price where the trade closes with a small loss.",
                            "TP (Take Profit) — the price where the trade closes in profit."]},
        {"t": "tip", "x": "A pip on gold is $0.10 of price movement. From 2650.00 to 2660.00 is 100 pips."},
        {"t": "h", "x": "How a signal ends"},
        {"t": "list", "x": ["Take Profit — the price reached the target, profit is locked in.",
                            "Stop Loss — the trade closed at the stop with a small loss.",
                            "Breakeven — the stop was moved to entry, the trade closed near zero.",
                            "“Part secured” — part of the position was already closed in profit at an interim target.",
                            "Closed on reversal or before news — the bot exited early to avoid risk."]},
        {"t": "warn", "x": "Enter close to the entry price. If the price has already run far towards the take, "
                           "skip it: less profit is left while the risk stays the same."},
    ], "SELL signal, entry 2650.00. The price fell to 2640.00. How is the trade doing?",
        ["In profit: +100 pips", "In loss: −100 pips", "Exactly zero"],
        "SELL earns when the price falls. A $10 drop is +100 pips."),

    _l("sltp", "🎯", 3, "Stop and take", "Why a stop is a must and how 1 : 2 works", [
        {"t": "p", "x": "A stop is insurance. Without it one bad trade can wipe out a month of profit or the whole "
                        "deposit. Every bot signal already has a stop — set it right when you open the trade."},
        {"t": "ex", "h": "Risk to reward 1 : 2", "rows": [["Stop", "100 pips"], ["Take", "200 pips"],
                                                         ["One take covers", "two stops"],
                                                         ["To be in profit you need", "34% winning trades"]]},
        {"t": "list", "x": ["Never move the stop further away when the price goes against you: the loss only grows.",
                            "Don't close a winning trade early out of fear: then the takes won't cover the stops.",
                            "Stops are a normal part of trading. Even a strong strategy has 3–5 stops in a row."]},
        {"t": "tip", "x": "Breakeven: once the price has covered part of the way to the take, the stop is moved to "
                          "the entry price. After that the trade can no longer lose."},
    ], "Stop 100 pips, take 200. Out of 10 trades 4 win and 6 lose. What is the result?",
        ["+200 pips", "−200 pips", "0 pips"],
        "4 × 200 = 800, 6 × 100 = 600. The result is +200 even though there are more losing trades."),

    _l("lot", "⚖️", 4, "Lot and risk", "How much to trade without blowing the account", [
        {"t": "p", "x": "A lot is the trade size. On gold 1 lot = 100 ounces and 0.01 lot = 1 ounce: a $1 price "
                        "move gives $1 of profit or loss."},
        {"t": "ex", "h": "What 100 pips ($10 price move) are worth",
         "rows": [["0.01 lot", "$10"], ["0.05 lot", "$50"], ["0.10 lot", "$100"], ["1.00 lot", "$1,000"]]},
        {"t": "p", "x": "The lot comes from risk: what percentage of capital you are ready to lose if the stop is hit. "
                        "Loss at the stop for every 0.01 lot = stop in pips × $0.10."},
        {"t": "calc"},
        {"t": "warn", "x": "Risking more than 2% per trade is the road to a blown account. 10 stops in a row at 1% risk "
                           "is about −10% of the deposit, at 5% risk about −40%."},
        {"t": "tip", "x": "The bot sizes the lot in every signal for you — at {risk}% risk of the capital set in your "
                          "profile. Brokers won't open less than 0.01 lot: with small capital the risk can be higher, "
                          "and the bot will warn you."},
        {"t": "go", "to": "profile", "x": "Set my capital"},
    ], "Capital $2,000, risk 1%, stop 100 pips. What lot?",
        ["0.02", "0.20", "0.01"],
        "1% of $2,000 = $20. A 100-pip stop costs $10 per 0.01 lot, so the lot is 0.02."),

    _l("prop", "🏆", 4, "Prop challenge", "How to get a FundedNext account and the stages", [
        {"t": "p", "x": "A prop firm (for example FundedNext) lets you trade its capital. You buy a challenge, show "
                        "profit and discipline and get a funded account. Profit is shared with the firm: the trader "
                        "usually gets 80%, up to 95% with add-ons."},
        {"t": "list", "x": ["Stage 1 — reach the profit target without breaking the limits.",
                            "Stage 2 (in 2-Step and Lite) — a second, smaller target.",
                            "Funded account — no target: you get payouts from profit, the key is to protect the limits."]},
        {"t": "plans"},
        {"t": "list", "x": ["There is no time limit to pass — no need to rush.",
                            "A trading day counts if there was a trade with a non-zero result that day.",
                            "The target counts closed trades only.",
                            "Break a limit by even a cent and the account is closed. That's why prop risk is lower than usual."]},
        {"t": "tip", "x": "Firm rules change. Check your FundedNext dashboard before buying."},
        {"t": "go", "to": "prop", "x": "Open prop dashboard"},
    ], "Stellar 2-Step account of $10,000, stage 1. What balance reaches the target?",
        ["$10,800", "$10,500", "$11,000"],
        "The 2-Step stage 1 target is 8%: $10,000 + $800 = $10,800."),

    _l("limits", "🛡", 5, "Daily and overall limit", "And why the bot stops for the day after a stop", [
        {"t": "p", "x": "The key thing in prop trading is the two drawdown limits. Breaking either one closes the "
                        "account at once."},
        {"t": "ex", "h": "Example: Stellar 2-Step of $25,000",
         "rows": [["Daily limit 5%", "−$1,250 per day"], ["Overall limit 10%", "balance never below $22,500"]]},
        {"t": "list", "x": ["The daily limit is a percentage of the initial account size. It includes closed and open "
                            "trades, swap and commission.",
                            "A new trading day starts at 00:00 FundedNext server time.",
                            "In 2-Step, 1-Step and Lite the overall limit is static: the floor does not move.",
                            "In Instant the overall limit trails: it rises with profit and stops at the initial "
                            "balance. Account $10,000, floor $9,400; balance grew to $10,500 — floor $9,900."]},
        {"t": "h", "x": "Why the bot stops after a stop loss"},
        {"t": "p", "x": "Losses on gold come in series: after the first stop of the day, the following trades of that "
                        "day lose on average. So after the first Stop Loss the bot opens no new prop trades until "
                        "FundedNext midnight. On XAUUSD history since December 2023 the 2-Step challenge failed about "
                        "1 time in 5 without this guard, and not once in ~640 attempts with it."},
        {"t": "list", "x": ["Risk per trade — {prop_risk}% of the account, {prop_strong}% on a strong signal, never above 1%.",
                            "All open trades together — no more than 1.5% of the account.",
                            "Per day — no more than 3% and always with a buffer before the firm's limit.",
                            "Balance 2% below start — risk drops 4 times until the account recovers."]},
    ], "Stellar 1-Step of $10,000, daily limit 3% ($300). Closed −$150, an open trade at −$60. "
       "How much more can you lose today?",
        ["$90", "$150", "$240"],
        "Open trades count too: 300 − 150 − 60 = $90."),

    _l("stats", "📊", 3, "Reading the stats", "Win rate, profit factor, drawdown", [
        {"t": "list", "x": ["Win rate — share of winning trades among closed ones. On its own it says little: what "
                            "matters is how much a take brings and a stop costs.",
                            "Total — the sum of pips of all closed signals.",
                            "Profit factor — all profit ÷ all loss. Above 1 the strategy makes money, 1.5+ is good.",
                            "Max drawdown — the deepest fall from a peak. Be ready for it to happen again.",
                            "Win streak — most winning trades in a row.",
                            "Equity curve — how the pip total grew. Steady growth beats sharp jumps."]},
        {"t": "ex", "h": "Pips to money", "rows": [["+500 pips at 0.01 lot", "+$50"],
                                                   ["+500 pips at 0.10 lot", "+$500"]]},
        {"t": "tip", "x": "Look at 90 days or “All”: over one week luck matters more than the strategy."},
        {"t": "warn", "x": "Past results do not guarantee future ones. Trade only money you can afford to lose."},
        {"t": "go", "to": "stats", "x": "Open stats"},
    ], "In a month winning trades made 3,000 pips and losing trades took 2,000. What is the profit factor?",
        ["1.5", "1,000", "0.67"],
        "Profit factor = 3,000 ÷ 2,000 = 1.5. The strategy is profitable."),

    _l("auto", "🤖", 4, "Auto-trading", "How to connect an MT4/MT5 account", [
        {"t": "p", "x": "With auto-trading the bot opens and closes trades from its signals on your MetaTrader 4 or 5 "
                        "account by itself. No need to watch your phone."},
        {"t": "list", "x": ["Tap “Connect account” — it continues in the bot chat.",
                            "Choose MT4 or MT5, enter the broker server and account number.",
                            "Send the main (trading) password. The bot deletes the message with it right away.",
                            "Done: the bot trades the signals at {at_risk}% of equity per trade."]},
        {"t": "warn", "x": "An investor (read-only) password can't trade: with it the bot only reads prices. An account "
                           "with a zero balance also works for prices only — after a deposit the bot starts trading by itself."},
        {"t": "list", "x": ["The password goes to the secure MetaApi service and is not stored in the bot's database.",
                            "Pause and resume in the app on the “Prop” tab.",
                            "You can disconnect the account and delete the password at any time."]},
        {"t": "ex", "h": "FundedNext account for the bot", "rows": [["Platform", "MT4 or MT5"], ["Size", "up to $25,000"],
                                                                   ["“EA” add-on", "required at purchase"]]},
        {"t": "p", "x": "Price — ${usd} per month per account, paid in Telegram Stars, in parts if you like."},
        {"t": "go", "to": "connect", "x": "Connect account"},
    ], "Which password connects an account for auto-trading?",
        ["The main (trading) one", "The investor one", "The broker website password"],
        "Only the main password lets the bot open trades. The investor one is view-only."),
]

UZ = [
    _l("signal", "📡", 3, "Signal nima", "BUY va SELL, kirish, stop, teyk va pipslar", [
        {"t": "p", "x": "Signal — oltin (XAUUSD) boʻyicha tayyor bitim gʻoyasi: qayerda kirish, qayerda kichik zarar "
                        "bilan chiqish va qayerda foydani olish. Bot uni chatga grafik va kapitalingizga mos lot bilan yuboradi."},
        {"t": "ex", "h": "Signal namunasi", "rows": [["Yoʻnalish", "BUY"], ["Kirish", "2650.00"],
                                                     ["SL (stop)", "2640.00"], ["TP (teyk)", "2670.00"]]},
        {"t": "list", "x": ["BUY — sotib olish: narx oshsa, foyda qilasiz.",
                            "SELL — sotish: narx tushsa, foyda qilasiz.",
                            "Kirish — bitim ochiladigan narx.",
                            "SL (Stop Loss) — bitim kichik zarar bilan yopiladigan narx.",
                            "TP (Take Profit) — bitim foyda bilan yopiladigan narx."]},
        {"t": "tip", "x": "Oltinda bir pips — narxning $0.10 harakati. 2650.00 dan 2660.00 gacha — 100 pips."},
        {"t": "h", "x": "Signal qanday tugaydi"},
        {"t": "list", "x": ["Take Profit — narx maqsadga yetdi, foyda qayd etildi.",
                            "Stop Loss — bitim stop boʻyicha kichik zarar bilan yopildi.",
                            "Zararsiz — stop kirish narxiga koʻchirilgan, bitim nolga yaqin yopildi.",
                            "«Qismi qayd etilgan» — pozitsiyaning bir qismi oraliq maqsadda foyda bilan yopilgan.",
                            "Burilishda yoki yangilikdan oldin yopildi — bot xavf qilmaslik uchun oldinroq chiqdi."]},
        {"t": "warn", "x": "Kirish narxiga yaqin narxda kiring. Narx teykka qarab ancha ketib qolgan boʻlsa — "
                           "oʻtkazib yuboring: foyda kamroq qoladi, xavf esa oʻsha-oʻsha."},
    ], "SELL signal, kirish 2650.00. Narx 2640.00 gacha tushdi. Bitim qanday holatda?",
        ["Foydada: +100 pips", "Zararda: −100 pips", "Aynan nolda"],
        "SELL narx tushganda foyda qiladi. $10 tushish — bu +100 pips."),

    _l("sltp", "🎯", 3, "Stop va teyk", "Nega stop shart va 1 : 2 qanday ishlaydi", [
        {"t": "p", "x": "Stop — bu sugʻurta. Usiz bitta omadsiz bitim bir oylik foydani yoki butun depozitni yeb "
                        "qoʻyishi mumkin. Botning har bir signalida stop bor — bitimni ochishingiz bilan uni qoʻying."},
        {"t": "ex", "h": "Xavf va foyda 1 : 2", "rows": [["Stop", "100 pips"], ["Teyk", "200 pips"],
                                                         ["Bitta teyk qoplaydi", "ikkita stopni"],
                                                         ["Foydada boʻlish uchun yetarli", "34% foydali bitim"]]},
        {"t": "list", "x": ["Narx sizga qarshi ketganda stopni uzoqlashtirmang: zarar faqat oshadi.",
                            "Foydali bitimni qoʻrquvdan erta yopmang: unda teyklar stoplarni qoplamaydi.",
                            "Stop — savdoning oddiy qismi. Kuchli strategiyada ham ketma-ket 3–5 ta stop boʻladi."]},
        {"t": "tip", "x": "Zararsiz: narx teykka yoʻlning bir qismini bosib oʻtganda stop kirish narxiga koʻchiriladi. "
                          "Shundan keyin bitim zarar keltirmaydi."},
    ], "Stop 100 pips, teyk 200. 10 ta bitimdan 4 tasi foyda, 6 tasi zarar. Natija qanday?",
        ["+200 pips", "−200 pips", "0 pips"],
        "4 × 200 = 800, 6 × 100 = 600. Zararli bitimlar koʻproq boʻlsa ham natija +200."),

    _l("lot", "⚖️", 4, "Lot va xavf", "Depozitni yoʻqotmaslik uchun qancha qoʻyish kerak", [
        {"t": "p", "x": "Lot — bitim hajmi. Oltinda 1 lot = 100 untsiya, 0.01 lot = 1 untsiya: narxning $1 harakati "
                        "$1 foyda yoki zarar beradi."},
        {"t": "ex", "h": "100 pips ($10 narx harakati) qancha turadi",
         "rows": [["0.01 lot", "$10"], ["0.05 lot", "$50"], ["0.10 lot", "$100"], ["1.00 lot", "$1 000"]]},
        {"t": "p", "x": "Lot xavfdan hisoblanadi: stop ishlasa, kapitalning necha foizini yoʻqotishga tayyorsiz. "
                        "Har 0.01 lot uchun stopdagi zarar = stop pipsda × $0.10."},
        {"t": "calc"},
        {"t": "warn", "x": "Bitimga 2% dan ortiq xavf — depozitni yoʻqotish yoʻli. 1% xavfda ketma-ket 10 ta stop — "
                           "depozitning taxminan −10%, 5% xavfda — taxminan −40%."},
        {"t": "tip", "x": "Bot har bir signalda lotni oʻzi hisoblaydi — profilda koʻrsatilgan kapitalning {risk}% xavfi "
                          "bilan. Broker 0.01 lotdan kamini ochmaydi: kapital kichik boʻlsa, xavf yuqoriroq boʻlishi "
                          "mumkin va bot bu haqda ogohlantiradi."},
        {"t": "go", "to": "profile", "x": "Kapitalni kiritish"},
    ], "Kapital $2 000, xavf 1%, stop 100 pips. Qaysi lot?",
        ["0.02", "0.20", "0.01"],
        "$2 000 ning 1% = $20. 100 pipslik stop har 0.01 lot uchun $10, demak lot 0.02."),

    _l("prop", "🏆", 4, "Prop-chellenj", "FundedNext hisobini qanday olish va bosqichlar", [
        {"t": "p", "x": "Prop-firma (masalan, FundedNext) oʻz kapitalida savdo qilish imkonini beradi. Siz chellenj "
                        "sotib olasiz, foyda va intizom koʻrsatasiz hamda moliyalashtirilgan hisob olasiz. Foyda firma "
                        "bilan boʻlinadi: treyderga odatda 80%, qoʻshimchalar bilan — 95% gacha."},
        {"t": "list", "x": ["1-bosqich — limitlarni buzmasdan foyda maqsadiga yetish.",
                            "2-bosqich (2-Step va Lite da) — ikkinchi, kichikroq maqsad.",
                            "Moliyalashtirilgan hisob — maqsad yoʻq: foydadan toʻlov olasiz, asosiysi — limitlarni asrash."]},
        {"t": "plans"},
        {"t": "list", "x": ["Oʻtish uchun muddat yoʻq — shoshilish shart emas.",
                            "Savdo kuni hisoblanadi, agar oʻsha kuni natijasi nol boʻlmagan bitim boʻlsa.",
                            "Maqsad faqat yopilgan bitimlar boʻyicha hisoblanadi.",
                            "Limit bir sentga boʻlsa ham buzilsa — hisob yopiladi. Shuning uchun prop-hisobda xavf odatdagidan kam."]},
        {"t": "tip", "x": "Firma qoidalari oʻzgaradi. Sotib olishdan oldin FundedNext shaxsiy kabinetida tekshiring."},
        {"t": "go", "to": "prop", "x": "Prop-panelni ochish"},
    ], "Stellar 2-Step $10 000 hisob, 1-bosqich. Maqsadga yetish uchun qanday balans kerak?",
        ["$10 800", "$10 500", "$11 000"],
        "2-Step 1-bosqich maqsadi — 8%: $10 000 + $800 = $10 800."),

    _l("limits", "🛡", 5, "Kunlik va umumiy limit", "Va nega bot stopdan keyin kunni toʻxtatadi", [
        {"t": "p", "x": "Propda asosiysi — ikkita pasayish limiti. Ulardan birini buzish hisobni darhol yopadi."},
        {"t": "ex", "h": "Misol: Stellar 2-Step $25 000",
         "rows": [["Kunlik limit 5%", "kuniga −$1 250"], ["Umumiy limit 10%", "balans $22 500 dan past emas"]]},
        {"t": "list", "x": ["Kunlik limit — hisobning boshlangʻich hajmidan foiz. Unga yopilgan va ochiq bitimlar, "
                            "svop va komissiya kiradi.",
                            "Yangi savdo kuni FundedNext server vaqti boʻyicha 00:00 da boshlanadi.",
                            "2-Step, 1-Step va Lite da umumiy limit statik: chegara qimirlamaydi.",
                            "Instant da umumiy limit suzuvchi: foyda ortidan koʻtariladi va boshlangʻich balansda "
                            "toʻxtaydi. Hisob $10 000, chegara $9 400; balans $10 500 ga oʻsdi — chegara $9 900."]},
        {"t": "h", "x": "Nega bot stopdan keyin savdo qilmaydi"},
        {"t": "p", "x": "Oltinda zararlar seriya boʻlib keladi: kundagi birinchi stopdan keyin oʻsha kunning keyingi "
                        "bitimlari oʻrtacha zararli. Shuning uchun birinchi Stop Loss dan keyin bot FundedNext yarim "
                        "tunigacha yangi prop-bitim ochmaydi. 2023-yil dekabridan beri XAUUSD tarixida 2-Step "
                        "chellenji bu himoyasiz taxminan 5 tadan 1 marta oʻtmagan, himoya bilan ~640 urinishda bir marta ham."},
        {"t": "list", "x": ["Bitimga xavf — hisobning {prop_risk}%, kuchli signalda {prop_strong}%, hech qachon 1% dan ortiq emas.",
                            "Barcha ochiq bitimlar birga — hisobning 1.5% dan oshmaydi.",
                            "Kuniga — 3% dan oshmaydi va har doim firma limitigacha zaxira bilan.",
                            "Balans boshlangʻichdan 2% past — hisob tiklanguncha xavf 4 marta kamayadi."]},
    ], "Stellar 1-Step $10 000, kunlik limit 3% ($300). Yopilgan −$150, ochiq bitim −$60 da. "
       "Bugun yana qancha yoʻqotish mumkin?",
        ["$90", "$150", "$240"],
        "Ochiq bitimlar ham hisoblanadi: 300 − 150 − 60 = $90."),

    _l("stats", "📊", 3, "Statistikani oʻqish", "Vinreyt, profit-faktor, pasayish", [
        {"t": "list", "x": ["Vinreyt — yopilgan bitimlar orasida foydalilar ulushi. Oʻzi koʻp narsa demaydi: teyk "
                            "qancha keltirishi va stop qancha olishi muhim.",
                            "Jami — barcha yopilgan signallar pipslari yigʻindisi.",
                            "Profit-faktor — butun foyda ÷ butun zarar. 1 dan katta — strategiya foydada, 1.5 dan — yaxshi.",
                            "Maks. pasayish — choʻqqidan eng chuqur tushish. U takrorlanishiga tayyor boʻling.",
                            "Yutuqlar seriyasi — ketma-ket eng koʻp foydali bitimlar.",
                            "Daromad egri chizigʻi — pipslar yigʻindisi qanday oʻsgani. Tekis oʻsish keskin sakrashlardan yaxshi."]},
        {"t": "ex", "h": "Pipslarni pulga", "rows": [["0.01 lotda +500 pips", "+$50"],
                                                     ["0.10 lotda +500 pips", "+$500"]]},
        {"t": "tip", "x": "90 kun yoki «Hammasi» davriga qarang: bir haftada tasodif strategiyadan koʻproq hal qiladi."},
        {"t": "warn", "x": "Oʻtgan natijalar kelajakni kafolatlamaydi. Faqat yoʻqotishga tayyor pulingiz bilan savdo qiling."},
        {"t": "go", "to": "stats", "x": "Statistikani ochish"},
    ], "Bir oyda foydali bitimlar 3 000 pips berdi, zararlilar 2 000 olib ketdi. Profit-faktor qancha?",
        ["1.5", "1 000", "0.67"],
        "Profit-faktor = 3 000 ÷ 2 000 = 1.5. Strategiya foydada."),

    _l("auto", "🤖", 4, "Avtosavdo", "MT4/MT5 hisobini qanday ulash", [
        {"t": "p", "x": "Avtosavdoda bot oʻz signallari boʻyicha MetaTrader 4 yoki 5 hisobingizda bitimlarni oʻzi ochadi "
                        "va yopadi. Telefon oldida oʻtirish shart emas."},
        {"t": "list", "x": ["«Hisobni ulash» tugmasini bosing — davomi bot chatida.",
                            "MT4 yoki MT5 ni tanlang, broker serveri va hisob raqamini kiriting.",
                            "Asosiy (savdo) parolini yuboring. Bot parolli xabarni chatdan darhol oʻchiradi.",
                            "Tayyor: bot signallar boʻyicha har bitimga mablagʻning {at_risk}% xavfi bilan savdo qiladi."]},
        {"t": "warn", "x": "Investor paroli (faqat koʻrish) savdoga yaramaydi: u bilan bot faqat narxlarni oladi. Balansi "
                           "nol hisob ham faqat narxlar uchun ishlaydi — toʻldirilgandan keyin bot oʻzi savdo boshlaydi."},
        {"t": "list", "x": ["Parol himoyalangan MetaApi xizmatiga uzatiladi va bot bazasida saqlanmaydi.",
                            "Pauza va ishga tushirish — ilovada «Prop» boʻlimida.",
                            "Hisobni uzish va parolni oʻchirish istalgan vaqtda mumkin."]},
        {"t": "ex", "h": "Bot uchun FundedNext hisobi", "rows": [["Platforma", "MT4 yoki MT5"], ["Hajm", "$25 000 gacha"],
                                                                 ["«EA» qoʻshimchasi", "sotib olishda shart"]]},
        {"t": "p", "x": "Narxi — har hisob uchun oyiga ${usd}, Telegram Stars bilan, qismlarga boʻlib ham mumkin."},
        {"t": "go", "to": "connect", "x": "Hisobni ulash"},
    ], "Avtosavdo uchun hisob qaysi parol bilan ulanadi?",
        ["Asosiy (savdo) paroli", "Investor paroli", "Broker sayti paroli"],
        "Faqat asosiy parol botga bitim ochish huquqini beradi. Investor paroli — faqat koʻrish uchun."),
]

LESSONS = {"ru": RU, "en": EN, "uz": UZ}


def lessons(lang: str) -> list[dict]:
    return LESSONS.get(lang) or LESSONS["ru"]
