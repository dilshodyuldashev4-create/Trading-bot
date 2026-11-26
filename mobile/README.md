# XAUUSD Gold — приложение для iPhone и Android

Отдельное приложение (не Telegram): вход по почте и паролю или через Telegram, сигналы с push-уведомлениями,
живая цена, разбор рынка («Сигнал»), новости, экономический календарь, статистика, проп-панель FundedNext,
автоторговля (просмотр счетов, пауза и запуск), уроки и видеокурс, профиль. Языки: узбекский, русский, английский.

Сделано на React Native + Expo. Один код — сборка и для Android, и для iPhone, в облаке Expo (Mac не нужен).

## Как это работает

Приложение берёт данные у вашего бота: в боте добавлен API `/m/api/...` (файл `goldbot/mobile.py`). Он работает на том
же сервере и порту, что и Mini App. Поэтому приложению нужен **постоянный адрес сервера** (домен с https).

## Что нужно сделать, шаг за шагом

### 1. Домен (≈ $10 в год)
1. Купите домен, например в Cloudflare (dash.cloudflare.com → Domain Registration).
2. В Cloudflare: Zero Trust → Networks → Tunnels → Create tunnel. Скопируйте токен туннеля.
3. В туннеле добавьте Public Hostname: `app.вашдомен.com` → `http://goldbot:8080`.
4. На сервере в `docker-compose.yml` у сервиса `cloudflared` замените команду на
   `tunnel --no-autoupdate run --token <ТОКЕН>`, а в `.env` добавьте `WEBAPP_URL=https://app.вашдомен.com`.
5. `cd ~/Trading-bot && git pull && docker compose up -d --build`.
6. Проверка: откройте `https://app.вашдомен.com/m/api/ping` — должно быть `{"ok": true, ...}`.

### 2. Адрес сервера в приложении
В `mobile/app.json` впишите `"apiUrl": "https://app.вашдомен.com"` (раздел `extra`).
Там же по желанию `supportEmail` — почта поддержки (нужна магазинам).

### 3. Аккаунт Expo (бесплатно) и сборка
1. Зарегистрируйтесь на expo.dev.
2. На компьютере с Node.js: `cd mobile && npm install && npx eas-cli@latest login && npx eas-cli@latest init`
   (`init` впишет `projectId` в app.json — без него не работают push-уведомления).
3. Пробная сборка для Android (файл .apk, ставится на телефон напрямую):
   `npx eas-cli@latest build -p android --profile preview` → ссылка на скачивание придёт в консоли.

### 4. Google Play ($25 один раз)
1. play.google.com/console → создать аккаунт разработчика, оплатить $25, подтвердить личность.
2. Сборка для магазина: `npx eas-cli@latest build -p android --profile production` (.aab).
3. В консоли: создать приложение → загрузить .aab → заполнить карточку (описание, скриншоты, иконка),
   ссылку на политику конфиденциальности `https://app.вашдомен.com/privacy`, анкету «Финансовые функции».
4. Новые личные аккаунты Google сначала требуют закрытое тестирование: 12 тестировщиков в течение 14 дней.

### 5. App Store ($99 в год)
1. developer.apple.com → Apple Developer Program, оплатить $99.
2. `npx eas-cli@latest build -p ios --profile production` (EAS сам создаст сертификаты), затем
   `npx eas-cli@latest submit -p ios`.
3. В App Store Connect заполнить карточку. Apple строже проверяет приложения про трейдинг: в описании указать, что
   это сигналы и обучение, а не брокер; приложить ссылку на политику конфиденциальности. Удаление аккаунта уже есть.

### 6. Деньги
* Сигналы в приложении бесплатные, как в боте.
* Партнёрская ссылка брокера: в `.env` бота `BROKER_URL=...` и `BROKER_NAME=...` — на главной появится «Открыть счёт».
* Подписка на автоторговлю через App Store / Google Play: сервер уже принимает вебхук RevenueCat
  (`/m/api/revenuecat`, секрет `REVENUECAT_WEBHOOK_SECRET`). Покупка в приложении добавляется после регистрации в
  магазинах, когда будут созданы товары подписки.

## Для разработчика
```bash
cd mobile
npm install
npx tsc --noEmit                  # проверка типов
npx expo start                    # запуск на телефоне через Expo Go / dev build
npx expo export -p android -p ios # проверка, что код собирается
```
Код: `src/App.tsx` (вкладки и переходы), `src/store.tsx` (данные, вход, цена раз в 4 секунды),
`src/screens/*` (экраны), `src/ui/*` (кнопки, карточки, графики, иконки), `src/i18n.ts` (тексты RU/UZ/EN; общие с
Mini App подписи приходят с сервера).
