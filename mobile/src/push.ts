import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

import { api } from "./api";

// Пока приложение открыто — уведомление тоже показываем (баннер со звуком)
if (Platform.OS !== "web") {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false,
    }),
  });
}

export type PushStatus = "on" | "denied" | "unavailable";

function projectId(): string | undefined {
  const extra = Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined;
  return extra?.eas?.projectId ?? Constants.easConfig?.projectId ?? undefined;
}

let lastToken: string | null = null;
export const pushToken = () => lastToken;

/** Разрешение на уведомления и регистрация телефона на сервере. ask=false — только проверить, без запроса. */
export async function registerPush(ask = true): Promise<PushStatus> {
  if (Platform.OS === "web" || !Device.isDevice) return "unavailable";
  try {
    if (Platform.OS === "android") {
      await Notifications.setNotificationChannelAsync("signals", {
        name: "Signals", importance: Notifications.AndroidImportance.HIGH, sound: "default",
        vibrationPattern: [0, 200, 120, 200], lightColor: "#f7d46b",
      });
    }
    let { status } = await Notifications.getPermissionsAsync();
    if (status !== "granted" && ask) status = (await Notifications.requestPermissionsAsync()).status;
    if (status !== "granted") return "denied";
    const pid = projectId();
    if (!pid) return "unavailable";   // проект ещё не привязан к Expo (eas init)
    const token = (await Notifications.getExpoPushTokenAsync({ projectId: pid })).data;
    lastToken = token;
    await api("push", { token, platform: Platform.OS });
    return "on";
  } catch {
    return "unavailable";
  }
}

/** Нажали на уведомление — data из сервера: {type, id} */
export function onNotificationTap(fn: (data: Record<string, unknown>) => void): () => void {
  if (Platform.OS === "web") return () => {};
  const sub = Notifications.addNotificationResponseReceivedListener((r) => {
    fn((r.notification.request.content.data ?? {}) as Record<string, unknown>);
  });
  return () => sub.remove();
}
