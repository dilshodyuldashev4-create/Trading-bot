import { Image } from "expo-image";
import * as Linking from "expo-linking";
import React, { useEffect, useRef, useState } from "react";
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, ApiError } from "../api";
import { LANG_NAMES } from "../i18n";
import { useApp } from "../store";
import { C } from "../theme";
import type { Lang } from "../types";
import { Icon, type IconName } from "../ui/icons";
import { Btn, Card, FadeIn, Pills, Row, T } from "../ui/kit";

const LOGO = require("../../assets/logo.png");

type Mode = "welcome" | "signin" | "signup";

export default function Auth() {
  const { tr, lang, setLang, login, errText, haptic } = useApp();
  const ins = useSafeAreaInsets();
  const [mode, setMode] = useState<Mode>("welcome");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [tgCode, setTgCode] = useState<{ code: string; url: string } | null>(null);
  const poll = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => {
    if (poll.current) clearInterval(poll.current);
  }, []);

  const submit = async () => {
    setError("");
    const e = email.trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s.]{2,}$/.test(e)) return setError(tr("err_email"));
    if (password.length < 6) return setError(tr("err_password"));
    setBusy(true);
    try {
      const path = mode === "signup" ? "register" : "login";
      const r = await api<{ token: string }>(path, { email: e, password, name: name.trim(), lang });
      haptic("success");
      await login(r.token);
    } catch (err) {
      haptic("error");
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  };

  const stopTg = () => {
    if (poll.current) clearInterval(poll.current);
    poll.current = null;
    setTgCode(null);
  };

  const telegram = async () => {
    setError("");
    setBusy(true);
    try {
      const r = await api<{ code: string; url: string }>("tg/start");
      setTgCode(r);
      Linking.openURL(r.url).catch(() => {});
      const started = Date.now();
      poll.current = setInterval(async () => {
        if (Date.now() - started > 15 * 60 * 1000) {
          stopTg();
          setError(tr("err_code"));
          return;
        }
        try {
          const p = await api<{ token?: string; pending?: boolean }>("tg/poll", { code: r.code }, 8000);
          if (p.token) {
            stopTg();
            haptic("success");
            await login(p.token);
          }
        } catch (err) {
          if (err instanceof ApiError && err.status === 404) {
            stopTg();
            setError(tr("err_code"));
          }
        }
      }, 2000);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  };

  const langs: [Lang, string][] = (["uz", "ru", "en"] as Lang[]).map((l) => [l, LANG_NAMES[l]]);

  return (
    <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
      <ScrollView contentContainerStyle={[s.wrap, { paddingTop: ins.top + 18, paddingBottom: ins.bottom + 24 }]} keyboardShouldPersistTaps="handled">
        <FadeIn><View style={{ alignItems: "center" }}><Pills items={langs} value={lang} onChange={(l) => setLang(l)} /></View></FadeIn>

        <FadeIn delay={80} style={{ alignItems: "center", marginTop: 26 }}>
          <View style={s.logoGlow}>
            <Image source={LOGO} style={s.logo} contentFit="cover" />
          </View>
          <T v="h1" style={{ marginTop: 18 }}>{tr("app_name")}</T>
          <T v="sub" center style={{ marginTop: 6, maxWidth: 300 }}>{tr("tagline")}</T>
        </FadeIn>

        {tgCode ? (
          <FadeIn style={{ marginTop: 28 }}>
            <Card gold>
              <Row><Icon name="telegram" size={26} color={C.blue} /><T v="h3" style={{ marginLeft: 10, flex: 1 }}>{tr("tg_wait")}</T></Row>
              <T v="sub" style={{ marginTop: 8 }}>{tr("tg_wait_sub")}</T>
              <Btn title={tr("tg_open")} icon="telegram" onPress={() => Linking.openURL(tgCode.url).catch(() => {})} style={{ marginTop: 16 }} />
              <Btn title={tr("tg_cancel")} kind="ghost" onPress={stopTg} style={{ marginTop: 10 }} />
            </Card>
          </FadeIn>
        ) : mode === "welcome" ? (
          <FadeIn delay={160} style={{ marginTop: 28 }}>
            <Card>
              {([["bell", "welcome_1"], ["stats", "welcome_2"], ["shield", "welcome_3"]] as [IconName, string][]).map(([ic, k], i) => (
                <Row key={k} style={{ paddingVertical: 8, borderTopWidth: i ? StyleSheet.hairlineWidth : 0, borderTopColor: C.line2 }}>
                  <View style={s.feat}><Icon name={ic} size={18} color={C.gold2} /></View>
                  <T style={{ flex: 1, marginLeft: 12, fontWeight: "600" }}>{tr(k)}</T>
                </Row>
              ))}
            </Card>
            <Btn title={tr("sign_up")} onPress={() => setMode("signup")} style={{ marginTop: 6 }} />
            <Btn title={tr("sign_in")} kind="ghost" onPress={() => setMode("signin")} style={{ marginTop: 10 }} />
            <Or text={tr("or")} />
            <Btn title={tr("continue_tg")} kind="dark" icon="telegram" loading={busy} onPress={telegram} />
          </FadeIn>
        ) : (
          <FadeIn style={{ marginTop: 26 }}>
            <T v="h2" style={{ marginBottom: 14 }}>{mode === "signup" ? tr("sign_up") : tr("sign_in")}</T>
            {mode === "signup" ? <Field icon="user" value={name} onChange={setName} placeholder={tr("name")} /> : null}
            <Field icon="mail" value={email} onChange={setEmail} placeholder={tr("email")} keyboard="email-address" />
            <Field icon="lock" value={password} onChange={setPassword} placeholder={tr("password")} secure onSubmit={submit} />
            {mode === "signup" ? <T v="small" style={{ marginTop: -4, marginBottom: 8, marginLeft: 4 }}>{tr("password_hint")}</T> : null}
            {error ? <T style={{ color: C.red, marginBottom: 8 }}>{error}</T> : null}
            <Btn title={mode === "signup" ? tr("sign_up") : tr("sign_in")} loading={busy} onPress={submit} style={{ marginTop: 6 }} />
            <Btn title={mode === "signup" ? tr("have_account") : tr("no_account")} kind="ghost" small
              onPress={() => { setError(""); setMode(mode === "signup" ? "signin" : "signup"); }} style={{ marginTop: 10 }} />
            <Or text={tr("or")} />
            <Btn title={tr("continue_tg")} kind="dark" icon="telegram" onPress={telegram} />
            <Btn title="←" kind="ghost" small onPress={() => { setError(""); setMode("welcome"); }} style={{ marginTop: 10, alignSelf: "center", width: 80 }} />
          </FadeIn>
        )}
        {error && mode === "welcome" ? <T center style={{ color: C.red, marginTop: 12 }}>{error}</T> : null}
        <T v="small" center style={{ marginTop: 24, opacity: 0.8 }}>{tr("risk_note")}</T>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function Or({ text }: { text: string }) {
  return (
    <Row style={{ marginVertical: 16 }}>
      <View style={s.orLine} /><T v="small" style={{ marginHorizontal: 10 }}>{text}</T><View style={s.orLine} />
    </Row>
  );
}

function Field({ icon, value, onChange, placeholder, secure, keyboard, onSubmit }: {
  icon: IconName; value: string; onChange: (s: string) => void; placeholder: string; secure?: boolean;
  keyboard?: "email-address"; onSubmit?: () => void;
}) {
  const [focus, setFocus] = useState(false);
  return (
    <View style={[s.field, focus && { borderColor: C.gold3 }]}>
      <Icon name={icon} size={19} color={focus ? C.gold2 : C.dim} />
      <TextInput value={value} onChangeText={onChange} placeholder={placeholder} placeholderTextColor={C.dim}
        secureTextEntry={secure} keyboardType={keyboard} autoCapitalize="none" autoCorrect={false}
        autoComplete={secure ? "password" : keyboard ? "email" : "name"} onFocus={() => setFocus(true)}
        onBlur={() => setFocus(false)} onSubmitEditing={onSubmit} style={s.input} selectionColor={C.gold2} />
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { paddingHorizontal: 20, flexGrow: 1 },
  logoGlow: {
    borderRadius: 34, shadowColor: C.gold3, shadowOpacity: 0.55, shadowRadius: 30, shadowOffset: { width: 0, height: 10 },
    elevation: 14, backgroundColor: "#000",
  },
  logo: { width: 112, height: 112, borderRadius: 30, borderWidth: 1, borderColor: C.line },
  feat: { width: 34, height: 34, borderRadius: 11, backgroundColor: "rgba(247,212,107,0.1)", alignItems: "center", justifyContent: "center" },
  orLine: { flex: 1, height: StyleSheet.hairlineWidth, backgroundColor: C.line2 },
  field: {
    flexDirection: "row", alignItems: "center", backgroundColor: "rgba(255,255,255,0.05)", borderRadius: 16,
    paddingHorizontal: 14, marginBottom: 10, borderWidth: 1, borderColor: C.line2,
  },
  input: { flex: 1, color: C.text, fontSize: 16, paddingVertical: 15, marginLeft: 10, ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as object) : null) },
});
