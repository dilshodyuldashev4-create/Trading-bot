import { Image } from "expo-image";
import React, { useCallback, useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { api, authHeaders, chartUrl } from "../api";
import { dayKey, fmtTime } from "../format";
import { useApp } from "../store";
import { C, num } from "../theme";
import type { CalEvent } from "../types";
import { Icon } from "../ui/icons";
import { Btn, Card, Chip, FadeIn, GoldText, Row, Skeleton, T } from "../ui/kit";
import { Screen } from "../ui/layout";
import { SignalCard } from "../ui/signal";

/** Текст бота: строки-заголовки (с эмодзи в начале или «:» в конце) выделяем */
function RichText({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <View>
      {lines.map((ln, i) => {
        const t = ln.trim();
        if (!t) return <View key={i} style={{ height: 10 }} />;
        const head = (/^[^\p{L}\p{N}\s«"(•\-–]/u.test(t) && t.length < 70) || /:$/.test(t);
        const bullet = /^[•\-–]\s/.test(t);
        if (bullet) {
          return (
            <Row key={i} style={{ alignItems: "flex-start", marginBottom: 6 }}>
              <View style={s.bullet} /><T style={{ flex: 1, lineHeight: 22 }}>{t.replace(/^[•\-–]\s/, "")}</T>
            </Row>
          );
        }
        return <T key={i} style={[{ lineHeight: 22, marginBottom: 4 }, head && { fontWeight: "800", color: C.gold1, marginTop: 4 }]}>{t}</T>;
      })}
    </View>
  );
}

function TextScreen({ title, path, wait, hint }: { title: string; path: string; wait: string; hint?: string }) {
  const { back, tr, errText, state } = useApp();
  const [text, setText] = useState<string | null>(null);
  const [price, setPrice] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(async () => {
    setErr("");
    setText(null);
    try {
      const r = await api<{ text: string; price?: number | null }>(path, undefined, 95000);
      setText(r.text);
      if (r.price != null) setPrice(r.price);
    } catch (e) {
      setErr(errText(e));
    }
  }, [path, errText]);
  useEffect(() => {
    load();
  }, [load]);
  const open = path === "analysis" ? state?.market.open ?? [] : [];
  return (
    <Screen title={title} onBack={back} tabbar={false} onRefresh={load}>
      {path === "analysis" ? (
        <FadeIn>
          <Card gold>
            <T v="cap">{tr("live")}</T>
            <View style={{ marginTop: 6 }}>{(state?.market.price ?? price) != null
              ? <GoldText text={(state?.market.price ?? price)!.toFixed(2)} size={38} /> : <T v="sub">{tr("price_wait")}</T>}</View>
          </Card>
        </FadeIn>
      ) : null}
      {err ? (
        <Card><T style={{ color: C.red }}>{err}</T><Btn title={tr("retry")} icon="refresh" kind="ghost" onPress={load} style={{ marginTop: 12 }} /></Card>
      ) : text == null ? (
        <Card>
          <Row style={{ marginBottom: 14 }}><Icon name="spark" size={18} color={C.gold2} /><T v="sub" style={{ marginLeft: 8 }}>{wait}</T></Row>
          {[90, 100, 75, 95, 60, 85].map((w, i) => <Skeleton key={i} h={14} w={`${w}%`} style={{ marginBottom: 10 }} />)}
        </Card>
      ) : (
        <FadeIn><Card><RichText text={text} /></Card></FadeIn>
      )}
      {open.length && state ? (
        <FadeIn delay={80}>
          <Card>
            <T v="cap">{tr("open_trades")}</T>
            {open.map((x) => <SignalCard key={x.id} s={x} price={state.market.price} pip={state.pip} tz={state.tz} tr={tr} />)}
          </Card>
        </FadeIn>
      ) : null}
      {hint ? <T v="small" center>{hint}</T> : null}
    </Screen>
  );
}

export function AnalysisScreen() {
  const { tr } = useApp();
  return <TextScreen title={tr("analysis_title")} path="analysis" wait={tr("analysis_wait")} />;
}

export function NewsScreen() {
  const { tr } = useApp();
  return <TextScreen title={tr("news_title")} path="news" wait={tr("news_wait")} hint={tr("news_hint")} />;
}

export function CalendarScreen() {
  const { back, tr, errText, state } = useApp();
  const [events, setEvents] = useState<CalEvent[] | null>(null);
  const [err, setErr] = useState("");
  const tz = state?.tz;
  const load = useCallback(async () => {
    setErr("");
    try {
      setEvents((await api<{ events: CalEvent[] }>("calendar")).events);
    } catch (e) {
      setErr(errText(e));
    }
  }, [errText]);
  useEffect(() => {
    load();
  }, [load]);
  const today = dayKey(new Date().toISOString(), tz);
  const tomorrow = dayKey(new Date(Date.now() + 864e5).toISOString(), tz);
  const yesterday = dayKey(new Date(Date.now() - 864e5).toISOString(), tz);
  const groups: [string, CalEvent[]][] = [];
  for (const e of events ?? []) {
    const k = dayKey(e.ts, tz);
    const g = groups.find((x) => x[0] === k);
    if (g) g[1].push(e);
    else groups.push([k, [e]]);
  }
  const label = (k: string) => (k === today ? tr("today") : k === tomorrow ? tr("tomorrow") : k === yesterday ? tr("yesterday")
    : k.split("-").reverse().slice(0, 2).join("."));
  return (
    <Screen title={tr("cal_title")} onBack={back} tabbar={false} onRefresh={load}>
      {err ? <Card><T style={{ color: C.red }}>{err}</T><Btn title={tr("retry")} kind="ghost" onPress={load} style={{ marginTop: 12 }} /></Card>
        : events == null ? [0, 1, 2].map((i) => <Skeleton key={i} h={90} r={18} style={{ marginBottom: 12 }} />)
          : !events.length ? <Card><T v="sub" center>{tr("cal_empty")}</T></Card>
            : groups.map(([k, list], gi) => (
              <FadeIn key={k} delay={gi * 60}>
                <Row style={{ marginTop: gi ? 8 : 0, marginBottom: 8 }}>
                  <T v="cap" style={{ color: k === today ? C.gold2 : C.muted }}>{label(k)}</T>
                </Row>
                {list.map((e, i) => {
                  const high = e.impact === "High";
                  const past = new Date(e.ts).getTime() < Date.now();
                  return (
                    <Card key={i} style={[{ paddingVertical: 14 }, past && !e.actual ? { opacity: 0.75 } : null]}>
                      <Row style={{ alignItems: "flex-start" }}>
                        <View style={{ alignItems: "center", width: 56 }}>
                          <Text style={[num, { color: C.text, fontWeight: "800", fontSize: 16 }]}>{fmtTime(e.ts, tz)}</Text>
                          <View style={[s.dot, { backgroundColor: high ? C.red : C.warn }]} />
                        </View>
                        <View style={{ flex: 1 }}>
                          <Row style={{ gap: 6, flexWrap: "wrap" }}>
                            <Chip kind={high ? "bad" : "warn"} text={`${e.country} · ${high ? tr("cal_high") : tr("cal_medium")}`} />
                          </Row>
                          <T style={{ fontWeight: "800", marginTop: 6 }}>{e.title}</T>
                          {e.forecast || e.previous || e.actual ? (
                            <Row style={{ marginTop: 8, gap: 14 }}>
                              {e.actual ? <Val k={tr("cal_actual")} v={e.actual} gold /> : null}
                              {e.forecast ? <Val k={tr("cal_forecast")} v={e.forecast} /> : null}
                              {e.previous ? <Val k={tr("cal_previous")} v={e.previous} /> : null}
                            </Row>
                          ) : null}
                          {e.effect ? <T v="small" style={{ marginTop: 8 }}>{e.effect}</T> : null}
                        </View>
                      </Row>
                    </Card>
                  );
                })}
              </FadeIn>
            ))}
    </Screen>
  );
}

function Val({ k, v, gold }: { k: string; v: string; gold?: boolean }) {
  return (
    <View>
      <T v="small">{k}</T>
      <Text style={[num, { color: gold ? C.gold2 : C.text, fontWeight: "800" }]}>{v}</Text>
    </View>
  );
}

export function ChartScreen({ id }: { id: number }) {
  const { back, state, tr } = useApp();
  const [failed, setFailed] = useState(false);
  const sig = state?.market.open.find((x) => x.id === id);
  return (
    <Screen title={`XAUUSD · #${id}`} onBack={back} tabbar={false}>
      <FadeIn>
        <View style={s.chart}>
          {failed ? <T v="sub" center>{tr("err_generic")}</T> : (
            <Image source={{ uri: chartUrl(id), headers: authHeaders() }} style={StyleSheet.absoluteFill} contentFit="contain"
              transition={300} onError={() => setFailed(true)} />
          )}
        </View>
      </FadeIn>
      {sig && state ? <FadeIn delay={80}><SignalCard s={sig} price={state.market.price} pip={state.pip} tz={state.tz} tr={tr} /></FadeIn> : null}
    </Screen>
  );
}

const s = StyleSheet.create({
  bullet: { width: 6, height: 6, borderRadius: 3, backgroundColor: C.gold2, marginTop: 8, marginRight: 10 },
  dot: { width: 6, height: 6, borderRadius: 3, marginTop: 6 },
  chart: {
    aspectRatio: 11 / 6.2, borderRadius: 20, overflow: "hidden", backgroundColor: "#0b0f19", borderWidth: 1, borderColor: C.line,
    alignItems: "center", justifyContent: "center",
  },
});
