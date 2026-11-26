import * as Haptics from "expo-haptics";
import { getLocales } from "expo-localization";
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Alert, AppState, BackHandler, Platform } from "react-native";

import { api, ApiError, setToken, setUnauthorizedHandler } from "./api";
import { deviceLang, translate } from "./i18n";
import { onNotificationTap, pushToken, registerPush, type PushStatus } from "./push";
import { getItem, setItem } from "./storage";
import type { Lang, Market, State } from "./types";

export type Tab = "home" | "stats" | "prop" | "learn" | "profile";
export type Route =
  | { name: "analysis" } | { name: "news" } | { name: "calendar" }
  | { name: "lesson"; id: string } | { name: "video"; n: number } | { name: "chart"; id: number };

type Toast = { id: number; text: string; kind: "ok" | "err" | "info" };
type PromptReq = {
  title: string; hint?: string; value?: string; keyboard?: "numeric" | "email" | "default"; secure?: boolean;
  resolve: (v: string | null) => void;
};

type Ctx = {
  booting: boolean;
  authed: boolean;
  state: State | null;
  lang: Lang;
  tr: (key: string, vars?: Record<string, string | number>) => string;
  setLang: (l: Lang) => Promise<void>;
  login: (token: string) => Promise<void>;
  logout: (silent?: boolean) => Promise<void>;
  refresh: () => Promise<void>;
  apply: (s: State) => void;
  call: <T = State>(path: string, body?: object, okMsg?: string) => Promise<T | null>;
  offline: boolean;
  tab: Tab; setTab: (t: Tab) => void;
  stack: Route[]; push: (r: Route) => void; back: () => void;
  toast: Toast | null; showToast: (text: string, kind?: Toast["kind"]) => void;
  prompt: PromptReq | null; ask: (p: Omit<PromptReq, "resolve">) => Promise<string | null>; closePrompt: (v: string | null) => void;
  confirm: (text: string, danger?: boolean) => Promise<boolean>;
  haptic: (k?: "light" | "medium" | "sel" | "success" | "error") => void;
  pushStatus: PushStatus | null; enablePush: () => Promise<PushStatus>;
  errText: (e: unknown) => string;
};

const AppCtx = createContext<Ctx | null>(null);

export function useApp(): Ctx {
  const c = useContext(AppCtx);
  if (!c) throw new Error("useApp outside provider");
  return c;
}

const TOKEN_KEY = "auth_token";
const LANG_KEY = "lang";

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [booting, setBooting] = useState(true);
  const [authed, setAuthed] = useState(false);
  const [state, setState] = useState<State | null>(null);
  const [lang0, setLang0] = useState<Lang>(() => deviceLang(getLocales()[0]?.languageTag));
  const [offline, setOffline] = useState(false);
  const [tab, setTabRaw] = useState<Tab>("home");
  const [stack, setStack] = useState<Route[]>([]);
  const [toast, setToast] = useState<Toast | null>(null);
  const [prompt, setPrompt] = useState<PromptReq | null>(null);
  const [pushStatus, setPushStatus] = useState<PushStatus | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const lang: Lang = state?.lang ?? lang0;
  const tr = useCallback((key: string, vars?: Record<string, string | number>) => translate(lang, state?.t, key, vars),
    [lang, state?.t]);

  const haptic = useCallback((k: "light" | "medium" | "sel" | "success" | "error" = "light") => {
    if (Platform.OS === "web") return;
    try {
      if (k === "success") Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      else if (k === "error") Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      else if (k === "sel") Haptics.selectionAsync();
      else Haptics.impactAsync(k === "medium" ? Haptics.ImpactFeedbackStyle.Medium : Haptics.ImpactFeedbackStyle.Light);
    } catch {
      // без вибрации
    }
  }, []);

  const showToast = useCallback((text: string, kind: Toast["kind"] = "info") => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ id: Date.now(), text, kind });
    if (kind === "ok") haptic("success");
    if (kind === "err") haptic("error");
    toastTimer.current = setTimeout(() => setToast(null), 2600);
  }, [haptic]);

  const errText = useCallback((e: unknown) => {
    const code = e instanceof ApiError ? e.code : "generic";
    const key = `err_${code}`;
    const s = translate(lang, undefined, key);
    return s === key ? translate(lang, undefined, "err_generic") : s;
  }, [lang]);

  const apply = useCallback((s: State) => {
    setState(s);
    setOffline(false);
  }, []);

  const logout = useCallback(async (silent = false) => {
    if (!silent) {
      try {
        await api("logout", { push: pushToken() });
      } catch {
        // сервер недоступен — всё равно выходим на телефоне
      }
    }
    setToken(null);
    await setItem(TOKEN_KEY, null);
    setAuthed(false);
    setState(null);
    setStack([]);
    setTabRaw("home");
  }, []);

  const refresh = useCallback(async () => {
    try {
      apply(await api<State>("state"));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return;
      setOffline(true);
      throw e;
    }
  }, [apply]);

  const login = useCallback(async (token: string) => {
    setToken(token);
    await setItem(TOKEN_KEY, token);
    const s = await api<State>("state");
    // язык, выбранный до входа, переносим в профиль, если он новый
    apply(s);
    setAuthed(true);
    registerPush(true).then(setPushStatus);
  }, [apply]);

  // запуск: язык и токен из хранилища
  useEffect(() => {
    setUnauthorizedHandler(() => {
      logout(true);
    });
    (async () => {
      const l = await getItem(LANG_KEY);
      if (l === "ru" || l === "uz" || l === "en") setLang0(l);
      const tok = await getItem(TOKEN_KEY);
      if (tok) {
        setToken(tok);
        setAuthed(true);
        try {
          apply(await api<State>("state"));
        } catch (e) {
          if (!(e instanceof ApiError && e.status === 401)) setOffline(true);
        }
        registerPush(false).then(setPushStatus);
      }
      setBooting(false);
    })();
  }, [apply, logout]);

  const call = useCallback(async <T = State,>(path: string, body?: object, okMsg?: string): Promise<T | null> => {
    try {
      const j = await api<T>(path, body);
      if (j && typeof j === "object" && "user" in (j as object) && "stats" in (j as object)) apply(j as unknown as State);
      if (okMsg) showToast(okMsg, "ok");
      return j;
    } catch (e) {
      showToast(errText(e), "err");
      return null;
    }
  }, [apply, errText, showToast]);

  const setLang = useCallback(async (l: Lang) => {
    setLang0(l);
    await setItem(LANG_KEY, l);
    if (authed) await call("settings", { lang: l });
  }, [authed, call]);

  // живая цена и открытые сигналы — раз в 4 секунды, пока приложение на экране
  useEffect(() => {
    if (!authed) return;
    let active = AppState.currentState === "active";
    const tick = async () => {
      if (!active) return;
      try {
        const m = await api<Market>("market", undefined, 8000);
        setState((s) => (s ? { ...s, market: m } : s));
        setOffline(false);
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 401)) setOffline(true);
      }
    };
    const iv = setInterval(tick, 4000);
    const sub = AppState.addEventListener("change", (st) => {
      const was = active;
      active = st === "active";
      if (active && !was) refresh().catch(() => {});
    });
    return () => {
      clearInterval(iv);
      sub.remove();
    };
  }, [authed, refresh]);

  // нажали на push: новый сигнал или итог — на главную и обновить
  useEffect(() => onNotificationTap(() => {
    setStack([]);
    setTabRaw("home");
    refresh().catch(() => {});
  }), [refresh]);

  const push = useCallback((r: Route) => {
    haptic("light");
    setStack((s) => [...s, r]);
  }, [haptic]);
  const back = useCallback(() => setStack((s) => s.slice(0, -1)), []);
  const setTab = useCallback((t: Tab) => {
    haptic("sel");
    setStack([]);
    setTabRaw(t);
  }, [haptic]);

  // кнопка «Назад» на Android
  useEffect(() => {
    const sub = BackHandler.addEventListener("hardwareBackPress", () => {
      if (prompt) {
        prompt.resolve(null);
        setPrompt(null);
        return true;
      }
      if (stack.length) {
        back();
        return true;
      }
      if (tab !== "home" && authed) {
        setTabRaw("home");
        return true;
      }
      return false;
    });
    return () => sub.remove();
  }, [stack.length, tab, authed, back, prompt]);

  const ask = useCallback((p: Omit<PromptReq, "resolve">) => new Promise<string | null>((resolve) => {
    setPrompt({ ...p, resolve });
  }), []);
  const closePrompt = useCallback((v: string | null) => {
    setPrompt((p) => {
      p?.resolve(v);
      return null;
    });
  }, []);

  const confirm = useCallback((text: string, danger = false) => new Promise<boolean>((resolve) => {
    if (Platform.OS === "web") {
      resolve(typeof window !== "undefined" && typeof window.confirm === "function" ? window.confirm(text) : true);
      return;
    }
    Alert.alert("", text, [
      { text: translate(lang, undefined, "cancel"), style: "cancel", onPress: () => resolve(false) },
      { text: translate(lang, undefined, "yes"), style: danger ? "destructive" : "default", onPress: () => resolve(true) },
    ], { cancelable: true, onDismiss: () => resolve(false) });
  }), [lang]);

  const enablePush = useCallback(async () => {
    const st = await registerPush(true);
    setPushStatus(st);
    return st;
  }, []);

  const value = useMemo<Ctx>(() => ({
    booting, authed, state, lang, tr, setLang, login, logout, refresh, apply, call, offline, tab, setTab, stack, push,
    back, toast, showToast, prompt, ask, closePrompt, confirm, haptic, pushStatus, enablePush, errText,
  }), [booting, authed, state, lang, tr, setLang, login, logout, refresh, apply, call, offline, tab, setTab, stack, push,
    back, toast, showToast, prompt, ask, closePrompt, confirm, haptic, pushStatus, enablePush, errText]);

  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>;
}
