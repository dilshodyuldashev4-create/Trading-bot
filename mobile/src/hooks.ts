import * as Linking from "expo-linking";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "./api";
import { useApp } from "./store";

/** Привязать Telegram к открытому аккаунту: открываем бота с кодом и ждём подтверждения */
export function useTelegramLink() {
  const { tr, refresh, showToast, errText } = useApp();
  const [waiting, setWaiting] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const stop = useCallback(() => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    setWaiting(false);
  }, []);
  useEffect(() => stop, [stop]);

  const start = useCallback(async () => {
    try {
      const r = await api<{ code: string; url: string }>("tg/start");
      setWaiting(true);
      Linking.openURL(r.url).catch(() => {});
      const t0 = Date.now();
      timer.current = setInterval(async () => {
        if (Date.now() - t0 > 15 * 60 * 1000) return stop();
        try {
          const p = await api<{ linked?: boolean; pending?: boolean }>("tg/poll", { code: r.code }, 8000);
          if (p.linked) {
            stop();
            await refresh().catch(() => {});
            showToast(tr("tg_linked"), "ok");
          }
        } catch (e) {
          if (e instanceof ApiError && e.status === 404) stop();
        }
      }, 2000);
    } catch (e) {
      showToast(errText(e), "err");
    }
  }, [errText, refresh, showToast, stop, tr]);

  return { waiting, start, stop };
}

/** Открыть Telegram-бота (подключение счёта автоторговли идёт там) */
export function openBot(botUrl: string | null | undefined, start?: string) {
  if (!botUrl) return;
  Linking.openURL(start ? `${botUrl}?start=${start}` : botUrl).catch(() => {});
}
