import * as WebBrowser from "expo-web-browser";
import React, { useEffect, useRef, useState } from "react";
import { Animated, StyleSheet, Text, View } from "react-native";

import { pips, usd2 } from "../format";
import { calc, periodTrades } from "../stats";
import { useApp } from "../store";
import { C, num, signColor } from "../theme";
import type { State } from "../types";
import { EquityChart } from "../ui/chart";
import { Icon, type IconName } from "../ui/icons";
import { Bar, Between, Btn, Card, CardTitle, Chip, FadeIn, GoldText, Press, Ring, Row, Skeleton, T } from "../ui/kit";
import { Screen } from "../ui/layout";
import { SignalCard } from "../ui/signal";

export default function Home() {
  const { state, tr, refresh, push, setTab } = useApp();
  if (!state) return <HomeSkeleton />;
  const S = state;
  const m = S.market;
  const c30 = calc(periodTrades(S.stats.trades, 30), S.stats.win);
  const name = S.user.name || tr("trader");

  const tiles: [IconName, string, string, () => void][] = [
    ["signal", "btn_signal", "signal_sub", () => push({ name: "analysis" })],
    ["news", "btn_news", "news_sub", () => push({ name: "news" })],
    ["calendar", "btn_cal", "cal_sub", () => push({ name: "calendar" })],
    ["trophy", "btn_fundednext", "fn_sub", () => setTab("prop")],
  ];
  if (S.links.broker) {
    tiles.push(["bank", "btn_broker", "broker_sub", () => WebBrowser.openBrowserAsync(S.links.broker!).catch(() => {})]);
  }

  return (
    <Screen onRefresh={refresh}>
      <FadeIn>
        <Between style={{ marginBottom: 14 }}>
          <View style={{ flex: 1 }}>
            <T v="sub">{tr("hello", { name })} 👋</T>
            <T v="h2" style={{ marginTop: 2 }}>{tr("app_name")}</T>
          </View>
          <Chip text={`● ${tr("sub_free")}`} kind="ok" />
        </Between>
      </FadeIn>

      <FadeIn delay={60}><PriceHero price={m.price} tr={tr} /></FadeIn>

      <FadeIn delay={120}>
        <View style={s.tiles}>
          {tiles.map(([ic, title, sub, fn]) => (
            <View key={title} style={{ width: tiles.length === 5 && title === "btn_broker" ? "100%" : "50%", padding: 5 }}>
              <Press onPress={fn}>
                <View style={s.tile}>
                  <View style={s.tileIcon}><Icon name={ic} size={21} color={C.gold2} /></View>
                  <View style={{ flex: 1, marginLeft: 10 }}>
                    <T style={{ fontWeight: "800" }} numberOfLines={1}>{tr(title)}</T>
                    <T v="small" numberOfLines={1}>{tr(sub)}</T>
                  </View>
                </View>
              </Press>
            </View>
          ))}
        </View>
      </FadeIn>

      <FadeIn delay={180}>
        <Card>
          <CardTitle icon="bolt" right={m.open.length ? <Chip text={String(m.open.length)} kind="warn" /> : undefined}>{tr("open_trades")}</CardTitle>
          {m.open.length ? m.open.map((x) => (
            <SignalCard key={x.id} s={x} price={m.price} pip={S.pip} tz={S.tz} tr={tr} onChart={() => push({ name: "chart", id: x.id })} />
          )) : <T v="sub">{tr("no_open")}</T>}
        </Card>
      </FadeIn>

      <FadeIn delay={240}>
        <Card onPress={() => setTab("stats")}>
          <CardTitle icon="stats" right={<T v="small">{tr("stats_30")}</T>}>{tr("tab_stats")}</CardTitle>
          <Row>
            <Ring frac={(c30.wr ?? 0) / 100} size={112} stroke={10} label={c30.wr != null ? `${Math.round(c30.wr)}%` : "—"} sub={tr("wr")} />
            <View style={s.stat2}>
              <Mini label={tr("total_pips")} value={pips(c30.total)} color={signColor(c30.total)} />
              <Mini label={tr("signals")} value={String(c30.n)} />
              <Mini label={tr("wins")} value={String(c30.w)} color={C.green} />
              <Mini label={tr("losses")} value={String(c30.l)} color={C.red} />
            </View>
          </Row>
          <EquityChart pts={c30.pts} height={110} empty={tr("no_trades")} />
        </Card>
      </FadeIn>

      {S.prop ? <FadeIn delay={300}><PropMini S={S} /></FadeIn> : null}

      <FadeIn delay={340}>
        <Card onPress={() => setTab("learn")}>
          <Row>
            <View style={[s.tileIcon, { width: 46, height: 46, borderRadius: 14 }]}><Icon name="book" size={24} color={C.gold2} /></View>
            <View style={{ flex: 1, marginLeft: 12 }}>
              <T style={{ fontWeight: "800" }}>{tr("learn_title")}</T>
              <T v="small">{tr("lessons")}: {S.learn.lessons.length} · {tr("videos")}: {S.video.videos.length}</T>
            </View>
            <Icon name="chevron" size={20} color={C.dim} />
          </Row>
        </Card>
      </FadeIn>
      <T v="small" center style={{ marginTop: 4 }}>{tr("app_note")}</T>
    </Screen>
  );
}

function Mini({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <View style={{ width: "50%", paddingVertical: 6, paddingLeft: 14 }}>
      <T v="small">{label}</T>
      <Text style={[num, { color: color ?? C.text, fontWeight: "800", fontSize: 19, marginTop: 2 }]}>{value}</Text>
    </View>
  );
}

/** Живая цена: вспыхивает зелёным или красным при каждом изменении */
function PriceHero({ price, tr }: { price: number | null; tr: (k: string) => string }) {
  const prev = useRef<number | null>(price);
  const flash = useRef(new Animated.Value(0)).current;
  const [dir, setDir] = useState(0);
  const pulse = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(pulse, { toValue: 1, duration: 1100, useNativeDriver: false }),
      Animated.timing(pulse, { toValue: 0, duration: 1100, useNativeDriver: false }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [pulse]);
  useEffect(() => {
    if (price != null && prev.current != null && price !== prev.current) {
      setDir(price > prev.current ? 1 : -1);
      flash.setValue(1);
      Animated.timing(flash, { toValue: 0, duration: 1200, useNativeDriver: false }).start();
    }
    prev.current = price;
  }, [price, flash]);
  const col = dir > 0 ? C.green : C.red;
  return (
    <Card gold style={{ paddingVertical: 20 }}>
      <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, { backgroundColor: col, opacity: flash.interpolate({ inputRange: [0, 1], outputRange: [0, 0.1] }) }]} />
      <Row>
        <Animated.View style={[s.live, { opacity: pulse.interpolate({ inputRange: [0, 1], outputRange: [0.4, 1] }) }]} />
        <T v="cap" style={{ marginLeft: 8 }}>{tr("live")}</T>
      </Row>
      <Row style={{ marginTop: 10, alignItems: "flex-end" }}>
        {price != null ? <GoldText text={price.toFixed(2)} size={46} /> : <T v="sub" style={{ height: 56, paddingTop: 18 }}>{tr("price_wait")}</T>}
        {price != null && dir ? (
          <View style={{ marginLeft: 8, marginBottom: 14 }}>
            <Icon name="signal" size={22} color={col} stroke={2.4} />
          </View>
        ) : null}
      </Row>
      <T v="small" style={{ marginTop: 2 }}>XAU / USD · Gold Spot</T>
    </Card>
  );
}

function PropMini({ S }: { S: State }) {
  const { tr, setTab } = useApp();
  const p = S.prop!;
  return (
    <Card onPress={() => setTab("prop")}>
      <CardTitle icon="shield" right={<Icon name="chevron" size={18} color={C.dim} />}>{tr("prop_title")}</CardTitle>
      <T v="sub" style={{ marginTop: -6, marginBottom: 10 }}>{p.plan_name} · {p.stage_name} · {usd2(p.size)}</T>
      <Between>
        <View>
          <T v="small">{tr("balance")}</T>
          <Row>
            <Text style={[num, { color: C.text, fontSize: 22, fontWeight: "800" }]}>{usd2(p.balance)}</Text>
            <Text style={[num, { color: signColor(p.profit_pct), marginLeft: 8, fontWeight: "700" }]}>{p.profit_pct >= 0 ? "+" : ""}{p.profit_pct.toFixed(2)}%</Text>
          </Row>
        </View>
        {p.progress != null ? (
          <View style={{ alignItems: "flex-end" }}>
            <T v="small">{tr("progress")}</T>
            <Text style={[num, { color: C.gold2, fontSize: 22, fontWeight: "800" }]}>{Math.round(p.progress * 100)}%</Text>
          </View>
        ) : null}
      </Between>
      {p.progress != null ? <Bar frac={p.progress} /> : null}
      <Between style={{ marginTop: 10 }}>
        <T v="small">{tr("day_limit")}: <Text style={{ color: C.text, fontWeight: "700" }}>{usd2(p.day_left)}</Text></T>
        <T v="small">{tr("risk_next")}: <Text style={{ color: C.text, fontWeight: "700" }}>{+p.risk_pct.toFixed(2)}%</Text></T>
      </Between>
    </Card>
  );
}

function HomeSkeleton() {
  const { tr, refresh, offline } = useApp();
  return (
    <Screen>
      <Skeleton h={22} w="50%" style={{ marginBottom: 16 }} />
      <Skeleton h={140} r={22} style={{ marginBottom: 12 }} />
      <Skeleton h={70} r={18} style={{ marginBottom: 12 }} />
      <Skeleton h={180} r={22} />
      {offline ? <Btn title={tr("retry")} icon="refresh" onPress={() => refresh().catch(() => {})} style={{ marginTop: 18 }} /> : null}
    </Screen>
  );
}

const s = StyleSheet.create({
  tiles: { flexDirection: "row", flexWrap: "wrap", marginHorizontal: -5, marginBottom: 7 },
  tile: {
    flexDirection: "row", alignItems: "center", backgroundColor: C.card, borderRadius: 18, padding: 12,
    borderWidth: StyleSheet.hairlineWidth, borderColor: C.line2,
  },
  tileIcon: { width: 40, height: 40, borderRadius: 12, backgroundColor: "rgba(247,212,107,0.1)", alignItems: "center", justifyContent: "center" },
  stat2: { flex: 1, flexDirection: "row", flexWrap: "wrap" },
  live: { width: 8, height: 8, borderRadius: 4, backgroundColor: C.green },
});
