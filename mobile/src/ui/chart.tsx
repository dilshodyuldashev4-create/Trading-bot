import React, { useState } from "react";
import { type LayoutChangeEvent, View } from "react-native";
import Svg, { Circle, Defs, Line, LinearGradient, Path, Stop } from "react-native-svg";

import { C } from "../theme";
import { T } from "./kit";

type Pt = { v: number };

/** Кривая доходности в пипсах: линия и заливка. Плюс — золото, минус — красный. */
export function EquityChart({ pts, height = 170, empty }: { pts: Pt[]; height?: number; empty?: string }) {
  const [w, setW] = useState(0);
  const onLayout = (e: LayoutChangeEvent) => setW(Math.round(e.nativeEvent.layout.width));
  if (pts.length < 2) {
    return (
      <View style={{ height: height * 0.6, alignItems: "center", justifyContent: "center" }}>
        <T v="sub">{empty ?? "—"}</T>
      </View>
    );
  }
  const data = [{ v: 0 }, ...pts];
  const vals = data.map((p) => p.v);
  const min = Math.min(0, ...vals), max = Math.max(0, ...vals);
  const span = max - min || 1;
  const pad = 8;
  const x = (i: number) => pad + (i / (data.length - 1)) * (w - pad * 2);
  const y = (v: number) => pad + (1 - (v - min) / span) * (height - pad * 2);
  const line = data.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(data.length - 1).toFixed(1)} ${y(min).toFixed(1)} L${x(0).toFixed(1)} ${y(min).toFixed(1)} Z`;
  const last = data[data.length - 1].v;
  const col = last >= 0 ? C.gold2 : C.red;
  return (
    <View onLayout={onLayout} style={{ height, marginTop: 8 }}>
      {w > 0 ? (
        <Svg width={w} height={height}>
          <Defs>
            <LinearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
              <Stop offset="0" stopColor={col} stopOpacity={0.35} />
              <Stop offset="1" stopColor={col} stopOpacity={0} />
            </LinearGradient>
          </Defs>
          <Line x1={pad} x2={w - pad} y1={y(0)} y2={y(0)} stroke="rgba(255,255,255,0.12)" strokeDasharray="4 5" />
          <Path d={area} fill="url(#eq)" />
          <Path d={line} stroke={col} strokeWidth={2.4} fill="none" strokeLinejoin="round" strokeLinecap="round" />
          <Circle cx={x(data.length - 1)} cy={y(last)} r={4.5} fill={col} />
          <Circle cx={x(data.length - 1)} cy={y(last)} r={9} fill={col} opacity={0.2} />
        </Svg>
      ) : null}
    </View>
  );
}
