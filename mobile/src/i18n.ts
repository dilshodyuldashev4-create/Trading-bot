import type { Lang } from "./types";

// Тексты приложения. Общие с Mini App подписи (статистика, проп, уроки) приходят с сервера в state.t —
// здесь только то, чего там нет, и то, что в приложении звучит иначе (без «чата бота»).
const ru = {
  app_name: "XAUUSD Gold",
  tagline: "Сигналы по золоту, статистика и проп-панель в одном приложении",
  welcome_1: "Сигналы по XAUUSD с push-уведомлением",
  welcome_2: "Честная статистика каждой сделки",
  welcome_3: "Проп-сигналы под правила FundedNext",
  sign_in: "Войти", sign_up: "Создать аккаунт", have_account: "Уже есть аккаунт? Войти",
  no_account: "Нет аккаунта? Создать", email: "Почта", password: "Пароль", name: "Имя",
  password_hint: "Не меньше 6 символов", continue_tg: "Войти через Telegram", or: "или",
  tg_wait: "Подтвердите вход в Telegram", tg_wait_sub: "Откройте бота и нажмите «Запустить». Мы ждём…",
  tg_open: "Открыть Telegram", tg_cancel: "Отменить",
  err_email: "Проверьте почту", err_password: "Пароль — не меньше 6 символов", err_exists: "Эта почта уже занята. Войдите",
  err_login: "Неверная почта или пароль", err_too_many: "Слишком много попыток. Подождите 15 минут",
  err_network: "Нет связи с сервером. Проверьте интернет", err_no_server: "Сервер приложения ещё не настроен",
  err_generic: "Не получилось. Попробуйте ещё раз", err_code: "Ссылка устарела. Попробуйте ещё раз",
  err_old_password: "Старый пароль неверный",
  risk_note: "Торговля на рынке связана с риском. Сигналы — не инвестиционная рекомендация.",
  tab_home: "Главная", tab_stats: "Статистика", tab_prop: "Проп", tab_learn: "Уроки", tab_profile: "Профиль",
  hello: "Привет, {name}", trader: "трейдер", live: "XAUUSD сейчас", price_wait: "цена обновляется…",
  btn_signal: "Сигнал", signal_sub: "Разбор рынка", btn_news: "Новости", news_sub: "Фундаментал",
  btn_cal: "Календарь", cal_sub: "События США", btn_fundednext: "FundedNext", fn_sub: "Проп-счёт",
  btn_broker: "Открыть счёт", broker_sub: "у брокера",
  open_trades: "Открытые сигналы", no_open: "Сейчас открытых сигналов нет. Новый придёт push-уведомлением.",
  show_chart: "График", now_pnl: "сейчас",
  analysis_title: "Разбор рынка", analysis_wait: "Анализирую рынок…", refresh: "Обновить",
  news_title: "Новости и фундаментал", news_wait: "Собираю новости…", news_hint: "Сводка обновляется каждые 15–30 минут",
  cal_title: "Экономический календарь", cal_empty: "В ближайшие дни важных событий нет",
  cal_forecast: "Прогноз", cal_previous: "Пред.", cal_actual: "Факт", today: "Сегодня", tomorrow: "Завтра", yesterday: "Вчера",
  cal_high: "Сильное", cal_medium: "Среднее",
  stats_30: "за 30 дней",
  push_title: "Уведомления", push_on: "Включены", push_off: "Выключены в настройках телефона",
  push_hint: "Сигналы, итоги сделок и TP1 приходят push-уведомлением",
  push_enable: "Включить уведомления",
  profile: "Профиль", account: "Аккаунт", telegram: "Telegram", tg_linked: "Привязан", tg_not_linked: "Не привязан",
  tg_link: "Привязать Telegram", tg_link_hint: "Тот же профиль, капитал и счета автоторговли, что в боте",
  tg_unlink: "Отвязать", tg_unlink_q: "Отвязать Telegram от приложения?",
  capital: "Ваш капитал", capital_hint: "По нему считается лот в каждом сигнале", capital_none: "Не указан",
  lot: "Лот на сигнал", language: "Язык", change_password: "Сменить пароль", old_password: "Старый пароль",
  new_password: "Новый пароль", logout: "Выйти", logout_q: "Выйти из аккаунта?",
  delete_account: "Удалить аккаунт", delete_q: "Удалить аккаунт приложения? Данные приложения удалятся без возможности восстановления. Профиль в Telegram-боте останется.",
  delete_done: "Аккаунт удалён", privacy: "Политика конфиденциальности", support: "Поддержка",
  version: "Версия {v}", saved: "Сохранено", cancel: "Отмена", ok: "Готово", save: "Сохранить", yes: "Да", no: "Нет",
  bad_number: "Введите число", edit: "Изменить",
  auto_title: "Автоторговля", auto_tg_needed: "Счета автоторговли подключаются в Telegram-боте: пароль от счёта вводится только там. Привяжите Telegram, чтобы видеть счета здесь.",
  auto_connect: "Подключить счёт в боте", auto_manage: "Управлять в боте", goes_bot: "Откроется Telegram-бот",
  no_accounts: "Счетов пока нет. Подключите MT4/MT5 в боте — он будет сам открывать и закрывать сделки.",
  loading: "Загрузка…", retry: "Повторить", offline: "Нет связи. Показаны последние данные",
  learn_title: "Академия трейдера", lessons: "Уроки", videos: "Видеокурс",
  watch_yt: "Смотреть на YouTube", subs_hint: "Включите субтитры → Автоперевод → узбекский, если нужно",
  link_copy: "Ссылка", app_note: "Сигналы бесплатны для всех. Платная только автоторговля.",
};

type Keys = keyof typeof ru;

const en: Record<Keys, string> = {
  app_name: "XAUUSD Gold",
  tagline: "Gold signals, statistics and a prop dashboard in one app",
  welcome_1: "XAUUSD signals with push notifications",
  welcome_2: "Honest statistics for every trade",
  welcome_3: "Prop signals built for FundedNext rules",
  sign_in: "Sign in", sign_up: "Create account", have_account: "Already have an account? Sign in",
  no_account: "No account? Create one", email: "Email", password: "Password", name: "Name",
  password_hint: "At least 6 characters", continue_tg: "Continue with Telegram", or: "or",
  tg_wait: "Confirm sign-in in Telegram", tg_wait_sub: "Open the bot and tap “Start”. Waiting…",
  tg_open: "Open Telegram", tg_cancel: "Cancel",
  err_email: "Check the email", err_password: "Password must be at least 6 characters", err_exists: "This email is taken. Sign in",
  err_login: "Wrong email or password", err_too_many: "Too many attempts. Wait 15 minutes",
  err_network: "No connection to the server. Check the internet", err_no_server: "The app server is not set up yet",
  err_generic: "Something went wrong. Try again", err_code: "The link expired. Try again",
  err_old_password: "The old password is wrong",
  risk_note: "Trading involves risk. Signals are not investment advice.",
  tab_home: "Home", tab_stats: "Stats", tab_prop: "Prop", tab_learn: "Learn", tab_profile: "Profile",
  hello: "Hi, {name}", trader: "trader", live: "XAUUSD now", price_wait: "price updating…",
  btn_signal: "Signal", signal_sub: "Market analysis", btn_news: "News", news_sub: "Fundamentals",
  btn_cal: "Calendar", cal_sub: "US events", btn_fundednext: "FundedNext", fn_sub: "Prop account",
  btn_broker: "Open account", broker_sub: "with a broker",
  open_trades: "Open signals", no_open: "No open signals right now. The next one will arrive as a push notification.",
  show_chart: "Chart", now_pnl: "now",
  analysis_title: "Market analysis", analysis_wait: "Analysing the market…", refresh: "Refresh",
  news_title: "News and fundamentals", news_wait: "Collecting news…", news_hint: "The summary updates every 15–30 minutes",
  cal_title: "Economic calendar", cal_empty: "No major events in the coming days",
  cal_forecast: "Forecast", cal_previous: "Prev.", cal_actual: "Actual", today: "Today", tomorrow: "Tomorrow", yesterday: "Yesterday",
  cal_high: "High", cal_medium: "Medium",
  stats_30: "last 30 days",
  push_title: "Notifications", push_on: "On", push_off: "Turned off in phone settings",
  push_hint: "Signals, trade results and TP1 arrive as push notifications",
  push_enable: "Turn on notifications",
  profile: "Profile", account: "Account", telegram: "Telegram", tg_linked: "Linked", tg_not_linked: "Not linked",
  tg_link: "Link Telegram", tg_link_hint: "The same profile, capital and auto-trading accounts as in the bot",
  tg_unlink: "Unlink", tg_unlink_q: "Unlink Telegram from the app?",
  capital: "Your capital", capital_hint: "The lot in every signal is sized from it", capital_none: "Not set",
  lot: "Lot per signal", language: "Language", change_password: "Change password", old_password: "Old password",
  new_password: "New password", logout: "Sign out", logout_q: "Sign out of the account?",
  delete_account: "Delete account", delete_q: "Delete the app account? App data will be deleted permanently. Your Telegram bot profile stays.",
  delete_done: "Account deleted", privacy: "Privacy policy", support: "Support",
  version: "Version {v}", saved: "Saved", cancel: "Cancel", ok: "Done", save: "Save", yes: "Yes", no: "No",
  bad_number: "Enter a number", edit: "Edit",
  auto_title: "Auto-trading", auto_tg_needed: "Auto-trading accounts are connected in the Telegram bot: the account password is entered only there. Link Telegram to see your accounts here.",
  auto_connect: "Connect account in the bot", auto_manage: "Manage in the bot", goes_bot: "The Telegram bot will open",
  no_accounts: "No accounts yet. Connect MT4/MT5 in the bot and it will open and close trades itself.",
  loading: "Loading…", retry: "Retry", offline: "No connection. Showing the latest data",
  learn_title: "Trader academy", lessons: "Lessons", videos: "Video course",
  watch_yt: "Watch on YouTube", subs_hint: "Turn on subtitles → Auto-translate → your language if needed",
  link_copy: "Link", app_note: "Signals are free for everyone. Only auto-trading is paid.",
};

const uz: Record<Keys, string> = {
  app_name: "XAUUSD Gold",
  tagline: "Oltin signallari, statistika va prop-panel bitta ilovada",
  welcome_1: "XAUUSD signallari push-bildirishnoma bilan",
  welcome_2: "Har bir savdoning halol statistikasi",
  welcome_3: "FundedNext qoidalariga mos prop-signallar",
  sign_in: "Kirish", sign_up: "Akkaunt yaratish", have_account: "Akkauntingiz bormi? Kirish",
  no_account: "Akkaunt yoʻqmi? Yaratish", email: "Pochta", password: "Parol", name: "Ism",
  password_hint: "Kamida 6 ta belgi", continue_tg: "Telegram orqali kirish", or: "yoki",
  tg_wait: "Telegramda kirishni tasdiqlang", tg_wait_sub: "Botni oching va «Start» ni bosing. Kutyapmiz…",
  tg_open: "Telegramni ochish", tg_cancel: "Bekor qilish",
  err_email: "Pochtani tekshiring", err_password: "Parol kamida 6 ta belgi", err_exists: "Bu pochta band. Kiring",
  err_login: "Pochta yoki parol notoʻgʻri", err_too_many: "Juda koʻp urinish. 15 daqiqa kuting",
  err_network: "Server bilan aloqa yoʻq. Internetni tekshiring", err_no_server: "Ilova serveri hali sozlanmagan",
  err_generic: "Boʻlmadi. Yana urinib koʻring", err_code: "Havola eskirgan. Yana urinib koʻring",
  err_old_password: "Eski parol notoʻgʻri",
  risk_note: "Bozorda savdo qilish xavf bilan bogʻliq. Signallar investitsiya maslahati emas.",
  tab_home: "Asosiy", tab_stats: "Statistika", tab_prop: "Prop", tab_learn: "Darslar", tab_profile: "Profil",
  hello: "Salom, {name}", trader: "treyder", live: "XAUUSD hozir", price_wait: "narx yangilanmoqda…",
  btn_signal: "Signal", signal_sub: "Bozor tahlili", btn_news: "Yangiliklar", news_sub: "Fundamental",
  btn_cal: "Kalendar", cal_sub: "AQSh voqealari", btn_fundednext: "FundedNext", fn_sub: "Prop-hisob",
  btn_broker: "Hisob ochish", broker_sub: "brokerda",
  open_trades: "Ochiq signallar", no_open: "Hozir ochiq signal yoʻq. Yangisi push-bildirishnoma bilan keladi.",
  show_chart: "Grafik", now_pnl: "hozir",
  analysis_title: "Bozor tahlili", analysis_wait: "Bozorni tahlil qilyapman…", refresh: "Yangilash",
  news_title: "Yangiliklar va fundamental", news_wait: "Yangiliklarni yigʻyapman…", news_hint: "Xulosa har 15–30 daqiqada yangilanadi",
  cal_title: "Iqtisodiy kalendar", cal_empty: "Yaqin kunlarda muhim voqealar yoʻq",
  cal_forecast: "Prognoz", cal_previous: "Oldingi", cal_actual: "Fakt", today: "Bugun", tomorrow: "Ertaga", yesterday: "Kecha",
  cal_high: "Kuchli", cal_medium: "Oʻrtacha",
  stats_30: "30 kunda",
  push_title: "Bildirishnomalar", push_on: "Yoqilgan", push_off: "Telefon sozlamalarida oʻchirilgan",
  push_hint: "Signallar, savdo natijalari va TP1 push-bildirishnoma bilan keladi",
  push_enable: "Bildirishnomalarni yoqish",
  profile: "Profil", account: "Akkaunt", telegram: "Telegram", tg_linked: "Ulangan", tg_not_linked: "Ulanmagan",
  tg_link: "Telegramni ulash", tg_link_hint: "Botdagi profil, kapital va avtosavdo hisoblari bu yerda ham",
  tg_unlink: "Uzish", tg_unlink_q: "Telegramni ilovadan uzasizmi?",
  capital: "Kapitalingiz", capital_hint: "Har bir signaldagi lot shundan hisoblanadi", capital_none: "Koʻrsatilmagan",
  lot: "Signal uchun lot", language: "Til", change_password: "Parolni almashtirish", old_password: "Eski parol",
  new_password: "Yangi parol", logout: "Chiqish", logout_q: "Akkauntdan chiqasizmi?",
  delete_account: "Akkauntni oʻchirish", delete_q: "Ilova akkauntini oʻchirasizmi? Ilova maʼlumotlari butunlay oʻchadi. Telegram-botdagi profil qoladi.",
  delete_done: "Akkaunt oʻchirildi", privacy: "Maxfiylik siyosati", support: "Yordam",
  version: "Versiya {v}", saved: "Saqlandi", cancel: "Bekor qilish", ok: "Tayyor", save: "Saqlash", yes: "Ha", no: "Yoʻq",
  bad_number: "Raqam kiriting", edit: "Oʻzgartirish",
  auto_title: "Avtosavdo", auto_tg_needed: "Avtosavdo hisoblari Telegram-botda ulanadi: hisob paroli faqat u yerda kiritiladi. Hisoblarni shu yerda koʻrish uchun Telegramni ulang.",
  auto_connect: "Botda hisob ulash", auto_manage: "Botda boshqarish", goes_bot: "Telegram-bot ochiladi",
  no_accounts: "Hozircha hisob yoʻq. Botda MT4/MT5 ni ulang — u savdolarni oʻzi ochib-yopadi.",
  loading: "Yuklanmoqda…", retry: "Qayta urinish", offline: "Aloqa yoʻq. Oxirgi maʼlumotlar koʻrsatilgan",
  learn_title: "Treyder akademiyasi", lessons: "Darslar", videos: "Videokurs",
  watch_yt: "YouTubeda koʻrish", subs_hint: "Subtitrlarni yoqing → Avtotarjima → oʻzbekcha",
  link_copy: "Havola", app_note: "Signallar hamma uchun bepul. Faqat avtosavdo pullik.",
};

const APP: Record<Lang, Record<Keys, string>> = { ru, en, uz };

export const LANG_NAMES: Record<Lang, string> = { ru: "Русский", uz: "Oʻzbekcha", en: "English" };

export function fill(s: string, vars?: Record<string, string | number>): string {
  if (!vars) return s;
  for (const [a, b] of Object.entries(vars)) s = s.split(`{${a}}`).join(String(b));
  return s;
}

/** Перевод: сначала тексты приложения, потом общие с Mini App (с сервера) */
export function translate(lang: Lang, server: Record<string, string> | undefined, key: string,
  vars?: Record<string, string | number>): string {
  const s = (APP[lang] as Record<string, string>)[key] ?? server?.[key] ?? (APP.ru as Record<string, string>)[key] ?? key;
  return fill(s, vars);
}

export function deviceLang(tag: string | null | undefined): Lang {
  const c = (tag || "").toLowerCase().split(/[-_]/)[0];
  return c === "uz" ? "uz" : c === "en" ? "en" : "ru";
}

export const APP_KEYS = Object.keys(ru) as Keys[];
export const APP_TEXTS = APP;
