import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

// Токен входа и мелкие настройки. На телефоне — защищённое хранилище, в браузере (предпросмотр) — localStorage.
const web = Platform.OS === "web";

export async function getItem(key: string): Promise<string | null> {
  try {
    if (web) return globalThis.localStorage?.getItem(key) ?? null;
    return await SecureStore.getItemAsync(key);
  } catch {
    return null;
  }
}

export async function setItem(key: string, value: string | null): Promise<void> {
  try {
    if (web) {
      if (value == null) globalThis.localStorage?.removeItem(key);
      else globalThis.localStorage?.setItem(key, value);
      return;
    }
    if (value == null) await SecureStore.deleteItemAsync(key);
    else await SecureStore.setItemAsync(key, value);
  } catch {
    // хранилище недоступно — просто не запоминаем
  }
}
