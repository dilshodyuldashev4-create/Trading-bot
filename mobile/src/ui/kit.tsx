import { LinearGradient } from "expo-linear-gradient";
import React, { useEffect, useRef } from "react";
import {
  ActivityIndicator, Animated, Easing, Platform, Pressable, StyleSheet, Text, View,
  type StyleProp, type TextProps, type TextStyle, type ViewStyle,
} from "react-native";
import Svg, { Circle, Defs, Stop, LinearGradient as SvgGrad, Text as SvgText } from "react-native-svg";

import { C, GOLD, GOLD_STOPS, R, num } from "../theme";
import { Icon, type IconName } from "./icons";

const native = Platform.OS !== "web";

// ── текст ───────────────────────────────────────────────────────────────────
type TProps = TextProps & { v?: "h1" | "h2" | "h3" | "body" | "sub" | "small" | "cap" | "num"; color?: string; center?: boolean };

export function T({ v = "body", color, center, style, ...p }: TProps) {
  return <Text {...p} style={[st[v], color ? { color } : null, center ? { textAlign: "center" } : null, style]} />;
}

/** Золотой текст с градиентом (цена, заголовки) */
export function GoldText({ text, size = 44, weight = "800" }: { text: string; size?: number; weight?: "700" | "800" | "900" }) {
  const w = Math.ceil(text.length * size * 0.62) + 4;
  const h = Math.ceil(size * 1.22);
  return (
    <Svg width={w} height={h}>
      <Defs>
        <SvgGrad id="g" x1="0" y1="0" x2="1" y2="1">
          {GOLD.map((c, i) => <Stop key={c} offset={GOLD_STOPS[i]} stopColor={c} />)}
        </SvgGrad>
      </Defs>
      <SvgText x="0" y={size} fontSize={size} fontWeight={weight} fill="url(#g)" letterSpacing={-0.5}
        fontFamily={Platform.OS === "web" ? "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif" : undefined}>{text}</SvgText>
    </Svg>
  );
}

// ── появление с анимацией ───────────────────────────────────────────────────
export function FadeIn({ delay = 0, children, style }: { delay?: number; children: React.ReactNode; style?: StyleProp<ViewStyle> }) {
  const a = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.timing(a, { toValue: 1, duration: 420, delay, easing: Easing.out(Easing.cubic), useNativeDriver: native }).start();
  }, [a, delay]);
  return (
    <Animated.View style={[style, { opacity: a, transform: [{ translateY: a.interpolate({ inputRange: [0, 1], outputRange: [14, 0] }) }] }]}>
      {children}
    </Animated.View>
  );
}

// ── карточки ────────────────────────────────────────────────────────────────
export function Card({ children, gold, style, onPress }: { children: React.ReactNode; gold?: boolean; style?: StyleProp<ViewStyle>; onPress?: () => void }) {
  const inner = gold ? (
    <LinearGradient colors={["rgba(247,212,107,0.16)", "rgba(166,109,16,0.05)", "rgba(255,255,255,0.02)"]}
      start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={[s.card, s.cardGold, style]}>
      {children}
    </LinearGradient>
  ) : <View style={[s.card, style]}>{children}</View>;
  if (!onPress) return inner;
  return <Press onPress={onPress}>{inner}</Press>;
}

export function CardTitle({ icon, children, right }: { icon?: IconName; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <View style={s.cardTitle}>
      {icon ? <Icon name={icon} size={17} color={C.gold2} /> : null}
      <T v="cap" style={{ flex: 1, marginLeft: icon ? 8 : 0 }}>{children}</T>
      {right}
    </View>
  );
}

/** Нажатие с лёгким «пружинящим» уменьшением */
export function Press({ onPress, children, disabled, style, scale = 0.97, dim = true }: { onPress?: () => void; children: React.ReactNode; disabled?: boolean; style?: StyleProp<ViewStyle>; scale?: number; dim?: boolean }) {
  const a = useRef(new Animated.Value(1)).current;
  const to = (v: number) => Animated.spring(a, { toValue: v, useNativeDriver: native, speed: 40, bounciness: 6 }).start();
  return (
    <Pressable onPress={disabled ? undefined : onPress} onPressIn={() => to(scale)} onPressOut={() => to(1)} disabled={disabled}
      accessibilityRole="button" style={style}>
      <Animated.View style={{ transform: [{ scale: a }], opacity: disabled && dim ? 0.45 : 1 }}>{children}</Animated.View>
    </Pressable>
  );
}

// ── кнопки ──────────────────────────────────────────────────────────────────
type BtnProps = {
  title: string; onPress?: () => void; kind?: "gold" | "ghost" | "red" | "dark"; icon?: IconName; loading?: boolean;
  disabled?: boolean; style?: StyleProp<ViewStyle>; small?: boolean;
};

export function Btn({ title, onPress, kind = "gold", icon, loading, disabled, style, small }: BtnProps) {
  const color = kind === "gold" ? "#1a1204" : kind === "red" ? C.red : C.text;
  const content = (
    <View style={[s.btnRow, small && { paddingVertical: 10 }]}>
      {loading ? <ActivityIndicator color={color} /> : (
        <>
          {icon ? <Icon name={icon} size={small ? 16 : 19} color={color} stroke={2} /> : null}
          <Text style={[s.btnText, { color }, small && { fontSize: 14 }, icon ? { marginLeft: 8 } : null]} numberOfLines={1}>{title}</Text>
        </>
      )}
    </View>
  );
  return (
    <Press onPress={loading ? undefined : onPress} disabled={disabled} style={style}>
      {kind === "gold" ? (
        <LinearGradient colors={[...GOLD]} locations={[...GOLD_STOPS]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={[s.btn, s.btnGold]}>
          {content}
        </LinearGradient>
      ) : (
        <View style={[s.btn, kind === "red" ? s.btnRed : kind === "dark" ? s.btnDark : s.btnGhost]}>{content}</View>
      )}
    </Press>
  );
}

export function IconBtn({ name, onPress, size = 40 }: { name: IconName; onPress: () => void; size?: number }) {
  return (
    <Press onPress={onPress} scale={0.9}>
      <View style={[s.iconBtn, { width: size, height: size, borderRadius: size / 2 }]}>
        <Icon name={name} size={size * 0.5} />
      </View>
    </Press>
  );
}

// ── чипы, сегменты, переключатель ───────────────────────────────────────────
export function Chip({ text, kind = "gold" }: { text: string; kind?: "gold" | "ok" | "bad" | "warn" | "dim" }) {
  const col = { gold: C.gold2, ok: C.green, bad: C.red, warn: C.warn, dim: C.muted }[kind];
  return (
    <View style={[s.chip, { borderColor: col + "55", backgroundColor: col + "1a" }]}>
      <Text style={[s.chipText, { color: col }]} numberOfLines={2}>{text}</Text>
    </View>
  );
}

export function Seg<K extends string | number>({ items, value, onChange }: { items: [K, string][]; value: K; onChange: (k: K) => void }) {
  return (
    <View style={s.seg}>
      {items.map(([k, label]) => {
        const on = k === value;
        return (
          <Pressable key={String(k)} onPress={() => onChange(k)} style={{ flex: 1 }} accessibilityRole="button" accessibilityState={{ selected: on }}>
            {on ? (
              <LinearGradient colors={[...GOLD]} locations={[...GOLD_STOPS]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={s.segOn}>
                <Text style={[s.segText, { color: "#1a1204" }]} numberOfLines={1}>{label}</Text>
              </LinearGradient>
            ) : (
              <View style={s.segOff}><Text style={s.segText} numberOfLines={1}>{label}</Text></View>
            )}
          </Pressable>
        );
      })}
    </View>
  );
}

export function Pills<K extends string | number>({ items, value, onChange }: { items: [K, string][]; value: K | null; onChange: (k: K) => void }) {
  return (
    <View style={s.pills}>
      {items.map(([k, label]) => {
        const on = k === value;
        return (
          <Press key={String(k)} onPress={() => onChange(k)} scale={0.94}>
            <View style={[s.pill, on && s.pillOn]}>
              <Text style={[s.pillText, on && { color: C.gold1 }]}>{label}</Text>
            </View>
          </Press>
        );
      })}
    </View>
  );
}

export function Toggle({ on, title, hint, onPress }: { on: boolean; title: string; hint?: string; onPress: () => void }) {
  const a = useRef(new Animated.Value(on ? 1 : 0)).current;
  useEffect(() => {
    Animated.spring(a, { toValue: on ? 1 : 0, useNativeDriver: false, speed: 24, bounciness: 8 }).start();
  }, [on, a]);
  return (
    <Pressable onPress={onPress} style={s.toggle} accessibilityRole="switch" accessibilityState={{ checked: on }}>
      <View style={{ flex: 1, paddingRight: 12 }}>
        <T style={{ fontWeight: "700" }}>{title}</T>
        {hint ? <T v="sub" style={{ marginTop: 2 }}>{hint}</T> : null}
      </View>
      <Animated.View style={[s.sw, { backgroundColor: a.interpolate({ inputRange: [0, 1], outputRange: ["rgba(255,255,255,0.12)", C.gold3] }) }]}>
        <Animated.View style={[s.knob, { transform: [{ translateX: a.interpolate({ inputRange: [0, 1], outputRange: [0, 20] }) }] }]} />
      </Animated.View>
    </Pressable>
  );
}

// ── прогресс ────────────────────────────────────────────────────────────────
export function Bar({ frac, color, height = 8 }: { frac: number; color?: "gold" | "g" | "y" | "r"; height?: number }) {
  const a = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.timing(a, { toValue: Math.max(0, Math.min(1, frac)), duration: 900, easing: Easing.out(Easing.cubic), useNativeDriver: false }).start();
  }, [a, frac]);
  const width = a.interpolate({ inputRange: [0, 1], outputRange: ["0%", "100%"] });
  const solid = { g: C.green, y: C.warn, r: C.red }[color as "g" | "y" | "r"];
  return (
    <View style={[s.bar, { height, borderRadius: height / 2 }]}>
      <Animated.View style={{ width, height: "100%", borderRadius: height / 2, overflow: "hidden" }}>
        {solid ? <View style={{ flex: 1, backgroundColor: solid }} /> : (
          <LinearGradient colors={[...GOLD]} locations={[...GOLD_STOPS]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={{ flex: 1 }} />
        )}
      </Animated.View>
    </View>
  );
}

const ACircle = Animated.createAnimatedComponent(Circle);

/** Кольцо прогресса (винрейт, прогресс этапа) */
export function Ring({ frac, size = 128, stroke = 11, label, sub }: { frac: number; size?: number; stroke?: number; label: string; sub?: string }) {
  const r = (size - stroke) / 2;
  const len = 2 * Math.PI * r;
  const a = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.timing(a, { toValue: Math.max(0, Math.min(1, frac)), duration: 1100, easing: Easing.out(Easing.cubic), useNativeDriver: false }).start();
  }, [a, frac]);
  const offset = a.interpolate({ inputRange: [0, 1], outputRange: [len, 0] });
  return (
    <View style={{ width: size, height: size, alignItems: "center", justifyContent: "center" }}>
      <Svg width={size} height={size} style={StyleSheet.absoluteFill}>
        <Defs>
          <SvgGrad id="rg" x1="0" y1="0" x2="1" y2="1">
            {GOLD.map((c, i) => <Stop key={c} offset={GOLD_STOPS[i]} stopColor={c} />)}
          </SvgGrad>
        </Defs>
        <Circle cx={size / 2} cy={size / 2} r={r} stroke="rgba(255,255,255,0.07)" strokeWidth={stroke} fill="none" />
        <ACircle cx={size / 2} cy={size / 2} r={r} stroke="url(#rg)" strokeWidth={stroke} fill="none" strokeLinecap="round"
          strokeDasharray={`${len} ${len}`} strokeDashoffset={offset} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      </Svg>
      <Text style={[st.num, { fontSize: size * 0.2, fontWeight: "800", color: C.gold1 }]}>{label}</Text>
      {sub ? <T v="small" style={{ marginTop: 2 }}>{sub}</T> : null}
    </View>
  );
}

export function Kpi({ value, label, color }: { value: string; label: string; color?: string }) {
  return (
    <View style={s.kpi}>
      <Text style={[st.num, { fontSize: 18, fontWeight: "800", color: color ?? C.text }]} numberOfLines={1} adjustsFontSizeToFit>{value}</Text>
      <T v="small" style={{ marginTop: 4 }} numberOfLines={2}>{label}</T>
    </View>
  );
}

export function KpiGrid({ children, cols = 3 }: { children: React.ReactNode; cols?: number }) {
  const items = React.Children.toArray(children);
  return (
    <View style={s.kpiGrid}>
      {items.map((c, i) => <View key={i} style={{ width: `${100 / cols}%`, padding: 4 }}>{c}</View>)}
    </View>
  );
}

export function Row({ children, style }: { children: React.ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[{ flexDirection: "row", alignItems: "center" }, style]}>{children}</View>;
}

export function Between({ children, style }: { children: React.ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }, style]}>{children}</View>;
}

export function Divider() {
  return <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: C.line2, marginVertical: 12 }} />;
}

/** Мерцающая заглушка, пока грузится */
export function Skeleton({ h = 18, w = "100%", r = 8, style }: { h?: number; w?: number | `${number}%`; r?: number; style?: StyleProp<ViewStyle> }) {
  const a = useRef(new Animated.Value(0.35)).current;
  useEffect(() => {
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(a, { toValue: 0.8, duration: 700, useNativeDriver: native }),
      Animated.timing(a, { toValue: 0.35, duration: 700, useNativeDriver: native }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [a]);
  return <Animated.View style={[{ height: h, width: w, borderRadius: r, backgroundColor: "rgba(255,255,255,0.08)", opacity: a }, style]} />;
}

/** Строка меню (профиль) */
export function ListRow({ icon, title, value, onPress, danger, last }: { icon: IconName; title: string; value?: string; onPress?: () => void; danger?: boolean; last?: boolean }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [s.listRow, !last && s.listRowLine, pressed && { opacity: 0.6 }]} accessibilityRole="button">
      <View style={[s.listIcon, danger && { backgroundColor: "rgba(255,93,115,0.12)" }]}>
        <Icon name={icon} size={18} color={danger ? C.red : C.gold2} />
      </View>
      <T style={{ flex: 1, marginLeft: 12, color: danger ? C.red : C.text, fontWeight: "600" }} numberOfLines={1}>{title}</T>
      {value ? <T v="sub" style={{ marginRight: 6, maxWidth: "45%" }} numberOfLines={1}>{value}</T> : null}
      {onPress ? <Icon name="chevron" size={18} color={C.dim} /> : null}
    </Pressable>
  );
}

// ── стили ───────────────────────────────────────────────────────────────────
export const st = StyleSheet.create({
  h1: { color: C.text, fontSize: 28, fontWeight: "800", letterSpacing: -0.5 },
  h2: { color: C.text, fontSize: 21, fontWeight: "800", letterSpacing: -0.3 },
  h3: { color: C.text, fontSize: 17, fontWeight: "700" },
  body: { color: C.text, fontSize: 15, lineHeight: 22 },
  sub: { color: C.muted, fontSize: 13.5, lineHeight: 19 },
  small: { color: C.muted, fontSize: 12, lineHeight: 16 },
  cap: { color: C.muted, fontSize: 12, fontWeight: "700", letterSpacing: 1.1, textTransform: "uppercase" },
  num: { color: C.text, ...num } as TextStyle,
});

const s = StyleSheet.create({
  card: {
    backgroundColor: C.card, borderRadius: R, borderWidth: StyleSheet.hairlineWidth, borderColor: C.line2,
    padding: 16, marginBottom: 12, overflow: "hidden",
  },
  cardGold: { borderColor: C.line, backgroundColor: "transparent" },
  cardTitle: { flexDirection: "row", alignItems: "center", marginBottom: 12 },
  btn: { borderRadius: 16, minHeight: 50, justifyContent: "center", paddingHorizontal: 16 },
  btnGold: { shadowColor: C.gold3, shadowOpacity: 0.35, shadowRadius: 14, shadowOffset: { width: 0, height: 6 }, elevation: 6 },
  btnGhost: { backgroundColor: C.card2, borderWidth: StyleSheet.hairlineWidth, borderColor: C.line },
  btnDark: { backgroundColor: "rgba(0,0,0,0.35)", borderWidth: StyleSheet.hairlineWidth, borderColor: C.line2 },
  btnRed: { backgroundColor: "rgba(255,93,115,0.1)", borderWidth: StyleSheet.hairlineWidth, borderColor: "rgba(255,93,115,0.35)" },
  btnRow: { flexDirection: "row", alignItems: "center", justifyContent: "center", paddingVertical: 14 },
  btnText: { fontSize: 16, fontWeight: "800", letterSpacing: 0.2 },
  iconBtn: { backgroundColor: C.card2, borderWidth: StyleSheet.hairlineWidth, borderColor: C.line2, alignItems: "center", justifyContent: "center" },
  chip: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4, alignSelf: "flex-start" },
  chipText: { fontSize: 12, fontWeight: "700" },
  seg: { flexDirection: "row", backgroundColor: C.card, borderRadius: 14, padding: 4, borderWidth: StyleSheet.hairlineWidth, borderColor: C.line2 },
  segOn: { borderRadius: 11, paddingVertical: 9, alignItems: "center" },
  segOff: { borderRadius: 11, paddingVertical: 9, alignItems: "center" },
  segText: { color: C.muted, fontWeight: "800", fontSize: 13.5 },
  pills: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  pill: { paddingHorizontal: 14, paddingVertical: 9, borderRadius: 999, backgroundColor: C.card2, borderWidth: 1, borderColor: "transparent" },
  pillOn: { borderColor: C.gold3, backgroundColor: "rgba(247,212,107,0.12)" },
  pillText: { color: C.muted, fontWeight: "700", fontSize: 14 },
  toggle: { flexDirection: "row", alignItems: "center", paddingVertical: 12 },
  sw: { width: 50, height: 30, borderRadius: 15, padding: 3 },
  knob: { width: 24, height: 24, borderRadius: 12, backgroundColor: "#fff" },
  bar: { backgroundColor: "rgba(255,255,255,0.07)", overflow: "hidden", marginTop: 8 },
  kpiGrid: { flexDirection: "row", flexWrap: "wrap", marginHorizontal: -4 },
  kpi: { backgroundColor: C.card, borderRadius: 16, padding: 12, borderWidth: StyleSheet.hairlineWidth, borderColor: C.line2, minHeight: 74 },
  listRow: { flexDirection: "row", alignItems: "center", paddingVertical: 13 },
  listRowLine: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: C.line2 },
  listIcon: { width: 34, height: 34, borderRadius: 10, backgroundColor: "rgba(247,212,107,0.1)", alignItems: "center", justifyContent: "center" },
});
