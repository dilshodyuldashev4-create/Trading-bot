import { LinearGradient } from "expo-linear-gradient";
import React, { useEffect, useRef } from "react";
import { Animated, StyleSheet, Text, View } from "react-native";

import { fmtDate, pips } from "../format";
import { C, num, signColor } from "../theme";
import type { OpenSignal } from "../types";
import { Icon } from "./icons";
import { Between, Press, Row, T } from "./kit";

/** Карточка открытого сигнала: направление, уровни, живой результат и положение цены между стопом и тейком */
export function SignalCard({ s, price, pip, tz, tr, onChart }: {
  s: OpenSignal; price: number | null; pip: number; tz: string; tr: (k: string) => string; onChart?: () => void;
}) {
  const buy = s.dir === 1;
  const now = price != null ? (s.dir * (price - s.entry)) / pip : null;
  const lo = Math.min(s.sl, s.tp), hi = Math.max(s.sl, s.tp);
  const pos = price != null && hi > lo ? Math.max(0, Math.min(1, (price - lo) / (hi - lo))) : null;
  const toTp = pos == null ? null : buy ? pos : 1 - pos;   // слева стоп, справа тейк
  const side = buy ? C.green : C.red;
  const x = useRef(new Animated.Value(toTp ?? 0.5)).current;
  useEffect(() => {
    if (toTp != null) Animated.spring(x, { toValue: toTp, useNativeDriver: false, speed: 10, bounciness: 4 }).start();
  }, [toTp, x]);

  return (
    <View style={[ss.card, { borderColor: side + "40" }]}>
      <LinearGradient colors={[side + "22", "transparent"]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0.8 }} style={StyleSheet.absoluteFill} />
      <Between>
        <Row>
          <View style={[ss.side, { backgroundColor: side + "22", borderColor: side + "66" }]}>
            <View style={buy ? null : { transform: [{ scaleY: -1 }] }}><Icon name="signal" size={14} color={side} stroke={2.2} /></View>
            <Text style={[ss.sideText, { color: side }]}>{buy ? "BUY" : "SELL"}</Text>
          </View>
          <Text style={ss.id}>#{s.id}</Text>
          <T v="small" style={{ marginLeft: 8 }}>{fmtDate(s.ts, tz)}</T>
        </Row>
        {now != null ? (
          <View style={{ alignItems: "flex-end" }}>
            <Text style={[ss.pnl, { color: signColor(now) }]}>{pips(now)}</Text>
            <T v="small">{tr("pips")} · {tr("now_pnl")}</T>
          </View>
        ) : null}
      </Between>
      <View style={ss.levels}>
        <Level label={tr("entry")} value={s.entry} color={C.text} />
        <Level label="SL" value={s.sl} color={C.red} />
        {s.tp1 ? <Level label="TP1" value={s.tp1} color={C.gold2} /> : null}
        <Level label="TP" value={s.tp} color={C.green} />
      </View>
      {toTp != null ? (
        <View style={ss.track}>
          <LinearGradient colors={[C.red, "rgba(255,255,255,0.15)", C.green]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={ss.trackLine} />
          <Animated.View style={[ss.dot, { left: x.interpolate({ inputRange: [0, 1], outputRange: ["0%", "100%"] }) }]} />
        </View>
      ) : null}
      <Between style={{ marginTop: 10 }}>
        {s.part ? <T v="small" style={{ color: C.gold2 }}>✓ {tr("part_done")}</T> : <View />}
        {onChart ? (
          <Press onPress={onChart} scale={0.92}>
            <Row style={ss.chartBtn}><Icon name="chart" size={15} color={C.gold2} /><T v="small" style={{ color: C.gold2, marginLeft: 6, fontWeight: "700" }}>{tr("show_chart")}</T></Row>
          </Press>
        ) : null}
      </Between>
    </View>
  );
}

function Level({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <View style={{ flex: 1 }}>
      <T v="small">{label}</T>
      <Text style={[num, { color, fontWeight: "800", fontSize: 15, marginTop: 2 }]}>{value.toFixed(2)}</Text>
    </View>
  );
}

const ss = StyleSheet.create({
  card: { borderRadius: 18, borderWidth: 1, padding: 14, marginTop: 10, overflow: "hidden", backgroundColor: "rgba(255,255,255,0.03)" },
  side: { flexDirection: "row", alignItems: "center", gap: 4, borderWidth: 1, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 3 },
  sideText: { fontWeight: "900", fontSize: 12.5, letterSpacing: 0.6 },
  id: { color: C.text, fontWeight: "800", marginLeft: 8, ...num },
  pnl: { fontSize: 20, fontWeight: "900", ...num },
  levels: { flexDirection: "row", marginTop: 14 },
  track: { height: 14, marginTop: 14, justifyContent: "center" },
  trackLine: { height: 4, borderRadius: 2, opacity: 0.8 },
  dot: {
    position: "absolute", width: 14, height: 14, marginLeft: -7, borderRadius: 7, backgroundColor: C.gold1,
    borderWidth: 3, borderColor: C.gold3, shadowColor: C.gold2, shadowOpacity: 0.8, shadowRadius: 6, elevation: 4,
  },
  chartBtn: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 10, backgroundColor: "rgba(247,212,107,0.1)" },
});
