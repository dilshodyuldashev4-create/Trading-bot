import { LinearGradient } from "expo-linear-gradient";
import React, { useEffect, useRef, useState } from "react";
import {
  Animated, KeyboardAvoidingView, Modal, Platform, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useApp, type Tab } from "../store";
import { C, GOLD, GOLD_STOPS } from "../theme";
import { Icon, type IconName } from "./icons";
import { Btn, IconBtn, T } from "./kit";

const native = Platform.OS !== "web";

/** Фон приложения: тёмный с золотым свечением сверху */
export function Backdrop() {
  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none">
      <View style={{ flex: 1, backgroundColor: C.bg }} />
      <LinearGradient colors={["rgba(247,212,107,0.13)", "rgba(226,169,48,0.04)", "transparent"]}
        start={{ x: 0.15, y: 0 }} end={{ x: 0.6, y: 0.55 }} style={StyleSheet.absoluteFill} />
    </View>
  );
}

/** Прокручиваемый экран с «потянуть, чтобы обновить» */
export function Screen({ children, title, onBack, onRefresh, right, tabbar = true }: {
  children: React.ReactNode; title?: string; onBack?: () => void; onRefresh?: () => Promise<void>; right?: React.ReactNode; tabbar?: boolean;
}) {
  const ins = useSafeAreaInsets();
  const [busy, setBusy] = useState(false);
  const refresh = onRefresh ? async () => {
    setBusy(true);
    try {
      await onRefresh();
    } catch {
      // ошибка уже показана
    } finally {
      setBusy(false);
    }
  } : undefined;
  return (
    <View style={{ flex: 1 }}>
      {title || onBack ? (
        <View style={[s.header, { paddingTop: ins.top + 6 }]}>
          {onBack ? <IconBtn name="back" onPress={onBack} /> : <View style={{ width: 40 }} />}
          <T v="h3" style={{ flex: 1, textAlign: "center", marginHorizontal: 8 }} numberOfLines={1}>{title ?? ""}</T>
          {right ?? <View style={{ width: 40 }} />}
        </View>
      ) : null}
      <ScrollView
        contentContainerStyle={{
          paddingHorizontal: 16, paddingTop: title || onBack ? 8 : ins.top + 12,
          paddingBottom: (tabbar ? 96 : 32) + ins.bottom,
        }}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
        refreshControl={refresh ? <RefreshControl refreshing={busy} onRefresh={refresh} tintColor={C.gold2} colors={[C.gold3]} progressBackgroundColor={C.bg2} /> : undefined}
      >
        {children}
      </ScrollView>
    </View>
  );
}

const TABS: [Tab, IconName, string][] = [
  ["home", "home", "tab_home"], ["stats", "stats", "tab_stats"], ["prop", "shield", "tab_prop"],
  ["learn", "book", "tab_learn"], ["profile", "user", "tab_profile"],
];

/** Нижняя панель вкладок со «стеклянным» фоном и золотой подсветкой активной */
export function TabBar() {
  const { tab, setTab, tr } = useApp();
  const ins = useSafeAreaInsets();
  return (
    <View style={[s.tabbar, { paddingBottom: Math.max(ins.bottom, 10) }]}>
      {TABS.map(([k, icon, label]) => {
        const on = tab === k;
        return (
          <Pressable key={k} onPress={() => setTab(k)} style={s.tab} accessibilityRole="tab" accessibilityState={{ selected: on }}>
            <View style={[s.tabIcon, on && s.tabIconOn]}>
              <Icon name={icon} size={22} color={on ? C.gold2 : C.dim} stroke={on ? 2.1 : 1.8} />
            </View>
            <Text style={[s.tabText, on && { color: C.gold2 }]} numberOfLines={1}>{tr(label)}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Всплывающее сообщение сверху */
export function ToastView() {
  const { toast } = useApp();
  const ins = useSafeAreaInsets();
  const a = useRef(new Animated.Value(0)).current;
  const [shown, setShown] = useState(toast);
  useEffect(() => {
    if (toast) setShown(toast);
    Animated.spring(a, { toValue: toast ? 1 : 0, useNativeDriver: native, speed: 18, bounciness: 7 }).start();
  }, [toast, a]);
  if (!shown) return null;
  const col = shown.kind === "err" ? C.red : shown.kind === "ok" ? C.green : C.gold2;
  return (
    <Animated.View pointerEvents="none" style={[s.toast, {
      top: ins.top + 8, opacity: a,
      transform: [{ translateY: a.interpolate({ inputRange: [0, 1], outputRange: [-30, 0] }) }],
    }]}>
      <View style={[s.toastDot, { backgroundColor: col }]} />
      <Text style={s.toastText}>{shown.text}</Text>
    </Animated.View>
  );
}

/** Окно ввода (капитал, баланс, пароль) */
export function PromptSheet() {
  const { prompt, closePrompt, tr } = useApp();
  const [val, setVal] = useState("");
  useEffect(() => {
    setVal(prompt?.value ?? "");
  }, [prompt]);
  return (
    <Modal visible={!!prompt} transparent animationType="fade" onRequestClose={() => closePrompt(null)}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={s.modalWrap}>
        <Pressable style={StyleSheet.absoluteFill} onPress={() => closePrompt(null)} />
        <View style={s.sheet}>
          <LinearGradient colors={[...GOLD]} locations={[...GOLD_STOPS]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={s.sheetLine} />
          <T v="h3">{prompt?.title ?? ""}</T>
          {prompt?.hint ? <T v="sub" style={{ marginTop: 4 }}>{prompt.hint}</T> : null}
          <TextInput
            value={val} onChangeText={setVal} autoFocus style={s.input} placeholderTextColor={C.dim}
            keyboardType={prompt?.keyboard === "numeric" ? "decimal-pad" : prompt?.keyboard === "email" ? "email-address" : "default"}
            secureTextEntry={prompt?.secure} autoCapitalize="none" autoCorrect={false}
            onSubmitEditing={() => closePrompt(val)} returnKeyType="done" selectionColor={C.gold2}
          />
          <View style={{ flexDirection: "row", gap: 10, marginTop: 14 }}>
            <Btn title={tr("cancel")} kind="ghost" onPress={() => closePrompt(null)} style={{ flex: 1 }} />
            <Btn title={tr("save")} onPress={() => closePrompt(val)} style={{ flex: 1 }} />
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

/** Плашка «нет связи» */
export function OfflineBar() {
  const { offline, tr } = useApp();
  const ins = useSafeAreaInsets();
  if (!offline) return null;
  return (
    <View style={[s.offline, { top: ins.top + 4 }]} pointerEvents="none">
      <Icon name="info" size={14} color={C.warn} />
      <Text style={s.offlineText}>{tr("offline")}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingBottom: 8 },
  tabbar: {
    position: "absolute", left: 0, right: 0, bottom: 0, flexDirection: "row", paddingTop: 8,
    backgroundColor: "rgba(9,12,21,0.96)", borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: C.line,
  },
  tab: { flex: 1, alignItems: "center" },
  tabIcon: { width: 46, height: 30, borderRadius: 15, alignItems: "center", justifyContent: "center" },
  tabIconOn: { backgroundColor: "rgba(247,212,107,0.12)" },
  tabText: { color: C.dim, fontSize: 10.5, fontWeight: "700", marginTop: 3 },
  toast: {
    position: "absolute", left: 16, right: 16, zIndex: 50, flexDirection: "row", alignItems: "center",
    backgroundColor: "rgba(20,24,36,0.98)", borderRadius: 16, paddingHorizontal: 16, paddingVertical: 13,
    borderWidth: StyleSheet.hairlineWidth, borderColor: C.line, elevation: 12,
    shadowColor: "#000", shadowOpacity: 0.5, shadowRadius: 18, shadowOffset: { width: 0, height: 8 },
  },
  toastDot: { width: 8, height: 8, borderRadius: 4, marginRight: 10 },
  toastText: { color: C.text, fontSize: 14.5, fontWeight: "600", flex: 1 },
  modalWrap: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.6)" },
  sheet: {
    backgroundColor: "#0f1422", borderTopLeftRadius: 26, borderTopRightRadius: 26, padding: 20, paddingBottom: 34,
    borderWidth: StyleSheet.hairlineWidth, borderColor: C.line, overflow: "hidden",
  },
  sheetLine: { position: "absolute", top: 0, left: 0, right: 0, height: 2 },
  input: {
    marginTop: 14, backgroundColor: "rgba(255,255,255,0.06)", borderRadius: 14, paddingHorizontal: 16, paddingVertical: 14,
    color: C.text, fontSize: 18, fontWeight: "700", borderWidth: 1, borderColor: C.line,
  },
  offline: {
    position: "absolute", alignSelf: "center", zIndex: 40, flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "rgba(247,184,75,0.14)", borderColor: "rgba(247,184,75,0.4)", borderWidth: 1, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 5,
  },
  offlineText: { color: C.warn, fontSize: 12, fontWeight: "700" },
});
