import Constants from "expo-constants";
import { Platform } from "react-native";

type Extra = { apiUrl?: string; privacyUrl?: string; supportEmail?: string };

const extra = (Constants.expoConfig?.extra ?? {}) as Extra;

// Адрес сервера бота (WEBAPP_URL). Задаётся в app.json → expo.extra.apiUrl
// В браузере (предпросмотр) без адреса — тот же сервер, с которого открыта страница
const webOrigin = Platform.OS === "web" && typeof window !== "undefined" ? window.location.origin : "";
export const API_URL = (extra.apiUrl || webOrigin).replace(/\/+$/, "");
export const PRIVACY_URL = extra.privacyUrl || (API_URL ? `${API_URL}/privacy` : "");
export const SUPPORT_EMAIL = extra.supportEmail ?? "";
