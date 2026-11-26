import Constants from "expo-constants";
import { LinearGradient } from "expo-linear-gradient";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";
import React from "react";
import { StyleSheet, Text, View } from "react-native";

import { api } from "../api";
import { PRIVACY_URL, SUPPORT_EMAIL } from "../config";
import { parseNum, usd2 } from "../format";
import { useTelegramLink } from "../hooks";
import { LANG_NAMES } from "../i18n";
import { useApp } from "../store";
import { C, GOLD, GOLD_STOPS, num } from "../theme";
import type { Lang } from "../types";
import { Btn, Card, CardTitle, Chip, FadeIn, ListRow, Pills, Row, T } from "../ui/kit";
import { Screen } from "../ui/layout";

export default function Profile() {
  const { state, tr, refresh, call, ask, confirm, setLang, logout, showToast, errText, pushStatus, enablePush, lang } = useApp();
  const link = useTelegramLink();
  const S = state!;
  const u = S.user;
  const initial = (u.name || S.me.email || "?").trim().charAt(0).toUpperCase();

  const setCapital = async () => {
    const v = await ask({ title: tr("capital"), hint: tr("capital_hint"), value: u.capital ? String(u.capital) : "", keyboard: "numeric" });
    if (v == null) return;
    const n = parseNum(v);
    if (n == null || n < 0) return showToast(tr("bad_number"), "err");
    await call("settings", { capital: n }, tr("saved"));
  };
  const setName = async () => {
    const v = await ask({ title: tr("name"), value: u.name });
    if (v != null) await call("settings", { name: v }, tr("saved"));
  };
  const changePassword = async () => {
    const old = await ask({ title: tr("old_password"), secure: true });
    if (old == null) return;
    const pw = await ask({ title: tr("new_password"), hint: tr("password_hint"), secure: true });
    if (pw == null) return;
    if (pw.length < 6) return showToast(tr("err_password"), "err");
    await call("settings", { password: pw, old_password: old }, tr("saved"));
  };
  const unlink = async () => {
    if (await confirm(tr("tg_unlink_q"))) await call("tg/unlink", {}, tr("saved"));
  };
  const del = async () => {
    if (!(await confirm(tr("delete_q"), true))) return;
    try {
      await api("delete");
      showToast(tr("delete_done"), "ok");
      await logout(true);
    } catch (e) {
      showToast(errText(e), "err");
    }
  };

  const langs: [Lang, string][] = (["uz", "ru", "en"] as Lang[]).map((l) => [l, LANG_NAMES[l]]);
  const version = Constants.expoConfig?.version ?? "1.0.0";

  return (
    <Screen onRefresh={refresh}>
      <FadeIn>
        <Row style={{ marginBottom: 18 }}>
          <LinearGradient colors={[...GOLD]} locations={[...GOLD_STOPS]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={s.avatar}>
            <Text style={s.avatarText}>{initial}</Text>
          </LinearGradient>
          <View style={{ flex: 1, marginLeft: 14 }}>
            <T v="h2" numberOfLines={1}>{u.name || tr("trader")}</T>
            <T v="sub" numberOfLines={1}>{S.me.email || (u.id ? `Telegram ID ${u.id}` : "")}</T>
          </View>
        </Row>
      </FadeIn>

      <FadeIn delay={50}>
        <Card gold onPress={setCapital}>
          <CardTitle icon="wallet" right={<Chip text={tr("edit")} />}>{tr("capital")}</CardTitle>
          <Text style={[num, { color: C.text, fontSize: 30, fontWeight: "900" }]}>{u.capital ? usd2(u.capital) : tr("capital_none")}</Text>
          {u.lot != null ? (
            <T v="sub" style={{ marginTop: 6 }}>{tr("lot")}: <Text style={{ color: C.gold2, fontWeight: "800" }}>{u.lot.toFixed(2)}</Text>
              {u.lot_loss != null && u.lot_profit != null ? ` · ${tr("risk_trade", { loss: Math.round(u.lot_loss), profit: Math.round(u.lot_profit) })}` : ""}</T>
          ) : <T v="sub" style={{ marginTop: 6 }}>{tr("capital_hint")}</T>}
        </Card>
      </FadeIn>

      <FadeIn delay={90}>
        <Card>
          <CardTitle icon="globe">{tr("language")}</CardTitle>
          <Pills items={langs} value={lang} onChange={(l) => setLang(l)} />
        </Card>
      </FadeIn>

      <FadeIn delay={130}>
        <Card>
          <CardTitle icon="bell">{tr("push_title")}</CardTitle>
          <T v="sub">{tr("push_hint")}</T>
          {pushStatus === "on" || pushStatus === "denied" ? (
            <Row style={{ marginTop: 10 }}>
              <Chip kind={pushStatus === "on" ? "ok" : "warn"} text={pushStatus === "on" ? `● ${tr("push_on")}` : tr("push_off")} />
            </Row>
          ) : null}
          {pushStatus !== "on" ? (
            <Btn title={tr("push_enable")} icon="bell" small kind="ghost" style={{ marginTop: 12 }}
              onPress={async () => { if ((await enablePush()) === "denied") Linking.openSettings().catch(() => {}); }} />
          ) : null}
        </Card>
      </FadeIn>

      <FadeIn delay={170}>
        <Card>
          <CardTitle icon="telegram" right={<Chip kind={S.me.telegram ? "ok" : "dim"} text={S.me.telegram ? tr("tg_linked") : tr("tg_not_linked")} />}>
            {tr("telegram")}
          </CardTitle>
          <T v="sub">{tr("tg_link_hint")}</T>
          {S.me.telegram ? (
            S.me.email ? <Btn title={tr("tg_unlink")} kind="ghost" small onPress={unlink} style={{ marginTop: 12 }} /> : null
          ) : (
            <Btn title={link.waiting ? tr("tg_wait") : tr("tg_link")} icon="telegram" loading={link.waiting} onPress={link.start} style={{ marginTop: 12 }} />
          )}
        </Card>
      </FadeIn>

      <FadeIn delay={210}>
        <Card style={{ paddingVertical: 4 }}>
          <ListRow icon="user" title={tr("name")} value={u.name || "—"} onPress={setName} />
          {S.me.email ? <ListRow icon="lock" title={tr("change_password")} onPress={changePassword} /> : null}
          {S.links.fundednext ? <ListRow icon="trophy" title="FundedNext" onPress={() => WebBrowser.openBrowserAsync(S.links.fundednext!).catch(() => {})} /> : null}
          {S.links.broker ? <ListRow icon="bank" title={S.links.broker_name || tr("btn_broker")} onPress={() => WebBrowser.openBrowserAsync(S.links.broker!).catch(() => {})} /> : null}
          {PRIVACY_URL ? <ListRow icon="shield" title={tr("privacy")} onPress={() => WebBrowser.openBrowserAsync(PRIVACY_URL).catch(() => {})} /> : null}
          {SUPPORT_EMAIL ? <ListRow icon="mail" title={tr("support")} value={SUPPORT_EMAIL} onPress={() => Linking.openURL(`mailto:${SUPPORT_EMAIL}`).catch(() => {})} /> : null}
          {S.me.bot_url ? <ListRow icon="telegram" title={`@${S.me.bot}`} onPress={() => Linking.openURL(S.me.bot_url!).catch(() => {})} /> : null}
          <ListRow icon="logout" title={tr("logout")} onPress={async () => { if (await confirm(tr("logout_q"))) await logout(); }} />
          <ListRow icon="trash" title={tr("delete_account")} danger onPress={del} last />
        </Card>
      </FadeIn>
      <T v="small" center style={{ marginTop: 4 }}>{tr("version", { v: version })}</T>
      <T v="small" center style={{ marginTop: 6, paddingHorizontal: 12 }}>{tr("risk_note")}</T>
    </Screen>
  );
}

const s = StyleSheet.create({
  avatar: { width: 62, height: 62, borderRadius: 31, alignItems: "center", justifyContent: "center" },
  avatarText: { color: "#1a1204", fontSize: 26, fontWeight: "900" },
});
