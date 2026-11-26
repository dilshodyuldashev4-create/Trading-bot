import { Image as ExpoImage } from "expo-image";
import * as WebBrowser from "expo-web-browser";
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { StyleSheet, Text, TextInput, View } from "react-native";

import { usd2 } from "../format";
import { calcLot, shuffled } from "../stats";
import { getItem, setItem } from "../storage";
import { useApp } from "../store";
import { C, num } from "../theme";
import type { Block, Lesson, State, Video } from "../types";
import { Icon } from "../ui/icons";
import { Bar, Between, Btn, Card, Chip, FadeIn, Press, Row, Seg, T } from "../ui/kit";
import { Screen } from "../ui/layout";

// ── прогресс обучения (на телефоне) ─────────────────────────────────────────
type Progress = { lessons: Set<string>; videos: Set<string>; markLesson: (id: string) => void; markVideo: (yt: string, on?: boolean) => void; reset: () => void };
const ProgressCtx = createContext<Progress | null>(null);

export function LearnProvider({ children }: { children: React.ReactNode }) {
  const [lessons, setLessons] = useState<Set<string>>(new Set());
  const [videos, setVideos] = useState<Set<string>>(new Set());
  useEffect(() => {
    getItem("learn_done").then((v) => setLessons(new Set((v || "").split(",").filter(Boolean))));
    getItem("video_done").then((v) => setVideos(new Set((v || "").split(",").filter(Boolean))));
  }, []);
  const markLesson = useCallback((id: string) => setLessons((s) => {
    const n = new Set(s).add(id);
    setItem("learn_done", [...n].join(","));
    return n;
  }), []);
  const markVideo = useCallback((yt: string, on = true) => setVideos((s) => {
    const n = new Set(s);
    if (on) n.add(yt);
    else n.delete(yt);
    setItem("video_done", [...n].join(","));
    return n;
  }), []);
  const reset = useCallback(() => {
    setLessons(new Set());
    setItem("learn_done", "");
  }, []);
  const v = useMemo(() => ({ lessons, videos, markLesson, markVideo, reset }), [lessons, videos, markLesson, markVideo, reset]);
  return <ProgressCtx.Provider value={v}>{children}</ProgressCtx.Provider>;
}

function useProgress() {
  const c = useContext(ProgressCtx);
  if (!c) throw new Error("no LearnProvider");
  return c;
}

/** Подстановка чисел из настроек бота ({risk} и т.п.) */
function fillVars(s: string, vars: Record<string, string>) {
  for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(v);
  return s;
}

// ── список ──────────────────────────────────────────────────────────────────
export default function Learn() {
  const { state, tr, push, refresh, confirm, haptic } = useApp();
  const pr = useProgress();
  const [tab, setTab] = useState<"text" | "video">("text");
  const S = state!;
  const L = S.learn.lessons;
  const done = L.filter((l) => pr.lessons.has(l.id)).length;
  const next = L.find((l) => !pr.lessons.has(l.id));
  const V = S.video.videos;
  const vDone = V.filter((v) => pr.videos.has(v.yt)).length;
  const vNext = V.find((v) => !pr.videos.has(v.yt));

  return (
    <Screen onRefresh={refresh}>
      <FadeIn><T v="h1">{tr("learn_title")}</T><T v="sub" style={{ marginTop: 4, marginBottom: 14 }}>{tr("learn_sub")}</T></FadeIn>
      <FadeIn delay={40}>
        <Seg items={[["text", tr("lessons")], ["video", tr("videos")]]} value={tab} onChange={(k) => { haptic("sel"); setTab(k); }} />
      </FadeIn>

      {tab === "text" ? (
        <>
          <FadeIn delay={80}>
            <Card gold style={{ marginTop: 12 }}>
              <Between>
                <T v="cap">{tr("learn_home")}</T>
                <Text style={[num, { color: C.gold2, fontWeight: "800" }]}>{tr("learn_progress", { n: done, m: L.length })}</Text>
              </Between>
              <Bar frac={L.length ? done / L.length : 0} />
              {next ? (
                <Btn title={done ? tr("learn_continue", { title: next.title }) : tr("learn_start")} icon="play"
                  onPress={() => push({ name: "lesson", id: next.id })} style={{ marginTop: 14 }} />
              ) : (
                <>
                  <T style={{ marginTop: 12, fontWeight: "700" }}>🏆 {tr("learn_done_all")}</T>
                  <Btn title={tr("learn_again")} kind="ghost" small style={{ marginTop: 10 }}
                    onPress={async () => { if (await confirm(tr("learn_again_q"))) pr.reset(); }} />
                </>
              )}
            </Card>
          </FadeIn>
          {L.map((l, i) => (
            <FadeIn key={l.id} delay={110 + i * 40}>
              <Card onPress={() => push({ name: "lesson", id: l.id })} style={{ paddingVertical: 14 }}>
                <Row>
                  <View style={[s.num, pr.lessons.has(l.id) && s.numDone]}>
                    {pr.lessons.has(l.id) ? <Icon name="check" size={18} color="#1a1204" stroke={3} /> : <Text style={s.emoji}>{l.icon}</Text>}
                  </View>
                  <View style={{ flex: 1, marginLeft: 12 }}>
                    <T v="small">{tr("lesson_n", { n: i + 1 })} · {tr("lesson_min", { n: l.min })}</T>
                    <T style={{ fontWeight: "800", marginTop: 1 }}>{l.title}</T>
                    <T v="small" numberOfLines={2}>{l.sub}</T>
                  </View>
                  <Icon name="chevron" size={18} color={C.dim} />
                </Row>
              </Card>
            </FadeIn>
          ))}
        </>
      ) : (
        <>
          <FadeIn delay={80}>
            <Card gold style={{ marginTop: 12 }}>
              <T v="h3">{tr("video_title")}</T>
              <T v="sub" style={{ marginTop: 4 }}>{tr("video_sub")}</T>
              <Between style={{ marginTop: 12 }}>
                <T v="small">{tr("video_progress", { n: vDone, m: V.length })}</T>
                <Text style={[num, { color: C.gold2, fontWeight: "800" }]}>{V.length ? Math.round((100 * vDone) / V.length) : 0}%</Text>
              </Between>
              <Bar frac={V.length ? vDone / V.length : 0} />
              {vNext ? <Btn title={`${tr("video_n", { n: vNext.n })}: ${vNext.title}`} icon="play" onPress={() => push({ name: "video", n: vNext.n })} style={{ marginTop: 14 }} /> : null}
            </Card>
          </FadeIn>
          {S.video.levels.map((lv) => {
            const items = V.filter((v) => v.level === lv.id);
            if (!items.length) return null;
            return (
              <View key={lv.id}>
                <T v="cap" style={{ marginTop: 10, marginBottom: 8 }}>{lv.icon} {lv.title}</T>
                {items.map((v) => (
                  <Card key={v.yt} onPress={() => push({ name: "video", n: v.n })} style={{ paddingVertical: 12 }}>
                    <Row>
                      <View style={[s.num, pr.videos.has(v.yt) && s.numDone]}>
                        {pr.videos.has(v.yt) ? <Icon name="check" size={18} color="#1a1204" stroke={3} /> : <Text style={[s.vn, num]}>{v.n}</Text>}
                      </View>
                      <View style={{ flex: 1, marginLeft: 12 }}>
                        <T style={{ fontWeight: "800" }} numberOfLines={2}>{v.title}{v.tested ? " ✅" : ""}</T>
                        <T v="small" numberOfLines={1}>{v.channel}</T>
                      </View>
                      <Icon name="play" size={22} color={C.gold2} />
                    </Row>
                  </Card>
                ))}
              </View>
            );
          })}
          <T v="small" style={{ marginTop: 6 }}>{tr("video_tested_note")}</T>
        </>
      )}
    </Screen>
  );
}

// ── урок ────────────────────────────────────────────────────────────────────
export function LessonScreen({ id }: { id: string }) {
  const { state, tr, back, push, setTab, haptic } = useApp();
  const pr = useProgress();
  const S = state!;
  const L = S.learn.lessons;
  const i = L.findIndex((x) => x.id === id);
  const l = L[i];
  if (!l) return <Screen title="" onBack={back} tabbar={false}><T v="sub">—</T></Screen>;
  const vars = S.learn.vars;
  const go = (to: string) => {
    if (to === "profile" || to === "prop" || to === "stats") setTab(to);
    else if (to === "connect") setTab("prop");
  };
  return (
    <Screen title={tr("lesson_n", { n: i + 1 })} onBack={back} tabbar={false}>
      <FadeIn>
        <Row><Text style={{ fontSize: 34 }}>{l.icon}</Text><Chip text={tr("lesson_min", { n: l.min })} kind="dim" /></Row>
        <T v="h1" style={{ marginTop: 10 }}>{l.title}</T>
        <T v="sub" style={{ marginTop: 4, marginBottom: 16 }}>{l.sub}</T>
      </FadeIn>
      {l.blocks.map((b, k) => <FadeIn key={k} delay={Math.min(k, 8) * 40}><BlockView b={b} S={S} vars={vars} onGo={go} /></FadeIn>)}
      <Quiz l={l} vars={vars} solvedBefore={pr.lessons.has(l.id)} onSolved={() => { pr.markLesson(l.id); haptic("success"); }}
        next={L[i + 1]} onNext={(nid) => { back(); push({ name: "lesson", id: nid }); }} onFinish={back} tr={tr} />
    </Screen>
  );
}

function BlockView({ b, S, vars, onGo }: { b: Block; S: State; vars: Record<string, string>; onGo: (to: string) => void }) {
  const f = (x: string) => fillVars(x, vars);
  switch (b.t) {
    case "p": return <T style={s.p}>{f(b.x)}</T>;
    case "h": return <T v="h3" style={{ marginTop: 8, marginBottom: 8 }}>{f(b.x)}</T>;
    case "list": return (
      <View style={{ marginBottom: 14 }}>
        {b.x.map((x, k) => (
          <Row key={k} style={{ alignItems: "flex-start", marginBottom: 8 }}>
            <View style={s.bullet} /><T style={{ flex: 1, lineHeight: 22 }}>{f(x)}</T>
          </Row>
        ))}
      </View>
    );
    case "tip":
    case "warn": return (
      <View style={[s.callout, b.t === "warn" ? s.warn : s.tip]}>
        <Text style={{ fontSize: 18, marginRight: 10 }}>{b.t === "warn" ? "⚠️" : "💡"}</Text>
        <T style={{ flex: 1, lineHeight: 21 }}>{f(b.x)}</T>
      </View>
    );
    case "ex": return (
      <View style={s.ex}>
        <View style={s.exHead}><T style={{ fontWeight: "800", color: C.gold1 }}>{f(b.h)}</T></View>
        {b.rows.map(([k, v], i) => (
          <Between key={i} style={[s.exRow, i ? { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: C.line2 } : null]}>
            <T v="sub" style={{ flex: 1, marginRight: 10 }}>{f(k)}</T><T style={{ fontWeight: "800" }}>{f(v)}</T>
          </Between>
        ))}
      </View>
    );
    case "plans": return <PlansTable S={S} />;
    case "calc": return <LotCalc S={S} />;
    case "go":
      if (b.to === "connect" && !S.auto.enabled) return null;
      return <Btn title={`${f(b.x)} →`} kind="ghost" onPress={() => onGo(b.to)} style={{ marginBottom: 14 }} />;
  }
  return null;
}

function PlansTable({ S }: { S: State }) {
  const { tr } = useApp();
  const pct = (v: number) => `${String(+v).replace(".", S.lang === "en" ? "." : ",")}%`;
  const head = [tr("pl_plan"), tr("pl_target"), tr("pl_daily"), tr("pl_total"), tr("pl_days")];
  return (
    <View style={[s.ex, { padding: 0 }]}>
      <View style={[s.plRow, { backgroundColor: "rgba(247,212,107,0.08)" }]}>
        {head.map((h, i) => <Text key={h} style={[s.plCell, i === 0 && s.plFirst, { color: C.gold2, fontWeight: "800", fontSize: 11.5 }]}>{h}</Text>)}
      </View>
      {S.plans.map((p) => {
        const tg = Object.values(p.targets);
        return (
          <View key={p.key} style={[s.plRow, { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: C.line2 }]}>
            <Text style={[s.plCell, s.plFirst, { fontWeight: "700" }]}>{p.name.replace(/^Stellar\s+/, "")}</Text>
            <Text style={[s.plCell, num]}>{tg.length ? tg.map(pct).join(" + ") : "—"}</Text>
            <Text style={[s.plCell, num, !p.daily && { color: C.muted }]}>{p.daily ? pct(p.daily) : tr("pl_none")}</Text>
            <Text style={[s.plCell, num]}>{pct(p.total)}{p.trailing ? " ↗" : ""}</Text>
            <Text style={[s.plCell, num]}>{p.min_days || "—"}</Text>
          </View>
        );
      })}
      <T v="small" style={{ padding: 10 }}>{tr("pl_note")} · ↗ {tr("trailing")}</T>
    </View>
  );
}

function LotCalc({ S }: { S: State }) {
  const { tr } = useApp();
  const [cap, setCap] = useState(String(S.user.capital || 1000));
  const [stop, setStop] = useState("100");
  const [risk, setRisk] = useState(+S.learn.vars.risk || 1);
  const capN = parseFloat(cap.replace(",", ".")), stopN = parseFloat(stop.replace(",", "."));
  const r = calcLot(capN, risk, stopN);
  return (
    <View style={[s.ex, { padding: 14 }]}>
      <T style={{ fontWeight: "800", color: C.gold1, marginBottom: 10 }}>🧮 {tr("calc_title")}</T>
      <Row style={{ gap: 10 }}>
        <View style={{ flex: 1 }}>
          <T v="small">{tr("calc_capital")}, $</T>
          <TextInput value={cap} onChangeText={setCap} keyboardType="decimal-pad" style={s.calcIn} selectionColor={C.gold2} />
        </View>
        <View style={{ flex: 1 }}>
          <T v="small">{tr("calc_stop")}</T>
          <TextInput value={stop} onChangeText={setStop} keyboardType="decimal-pad" style={s.calcIn} selectionColor={C.gold2} />
        </View>
      </Row>
      <T v="small" style={{ marginTop: 12, marginBottom: 6 }}>{tr("calc_risk")}</T>
      <Seg items={[[0.5, "0.5%"], [1, "1%"], [2, "2%"]]} value={risk} onChange={setRisk} />
      <View style={{ alignItems: "center", marginTop: 14 }}>
        <T v="small">{tr("calc_lot")}</T>
        <Text style={[num, { color: C.gold2, fontSize: 34, fontWeight: "900" }]}>{r ? r.lot.toFixed(2) : "—"}</Text>
        <T v="small">{r ? tr("calc_loss", { loss: usd2(r.loss) }) : tr("bad_number")}</T>
        {r?.tooSmall ? <T v="small" style={{ color: C.warn, marginTop: 4 }} center>{tr("calc_min", { pct: +r.real.toFixed(1) })}</T> : null}
      </View>
    </View>
  );
}

function Quiz({ l, vars, solvedBefore, onSolved, next, onNext, onFinish, tr }: {
  l: Lesson; vars: Record<string, string>; solvedBefore: boolean; onSolved: () => void; next?: Lesson;
  onNext: (id: string) => void; onFinish: () => void; tr: (k: string, v?: Record<string, string | number>) => string;
}) {
  const [pick, setPick] = useState<number | null>(null);
  const [ok, setOk] = useState(false);
  const order = useMemo(() => shuffled(l.id, l.quiz.a.length), [l.id, l.quiz.a.length]);
  const f = (x: string) => fillVars(x, vars);
  return (
    <Card gold style={{ marginTop: 8 }}>
      <Row><Icon name="spark" size={18} color={C.gold2} /><T v="cap" style={{ marginLeft: 8 }}>{tr("quiz")}</T></Row>
      <T style={{ fontWeight: "700", fontSize: 16, lineHeight: 23, marginTop: 10 }}>{f(l.quiz.q)}</T>
      {order.map((i, k) => {
        const right = ok && i === 0, wrong = pick === i && i !== 0;
        return (
          <Press key={i} disabled={ok} dim={false} onPress={() => { setPick(i); if (i === 0) { setOk(true); onSolved(); } }}>
            <View style={[s.q, right && s.qOk, wrong && s.qNo]}>
              <View style={[s.qk, right && { backgroundColor: C.green }, wrong && { backgroundColor: C.red }]}>
                <Text style={{ color: right || wrong ? "#fff" : C.gold2, fontWeight: "900" }}>{right ? "✓" : wrong ? "✕" : "ABC"[k]}</Text>
              </View>
              <T style={{ flex: 1, marginLeft: 10 }}>{f(l.quiz.a[i])}</T>
            </View>
          </Press>
        );
      })}
      {ok ? <T style={{ marginTop: 10, color: C.green }}><Text style={{ fontWeight: "800" }}>✅ {tr("quiz_ok")} </Text>{f(l.quiz.why)}</T>
        : pick != null ? <T style={{ marginTop: 10, color: C.warn }}>{tr("quiz_no")}. {tr("quiz_retry")}</T> : null}
      {ok || solvedBefore ? (next
        ? <Btn title={`${tr("next_lesson")}: ${next.title}`} onPress={() => onNext(next.id)} style={{ marginTop: 14 }} />
        : <Btn title={`🏆 ${tr("finish")}`} onPress={onFinish} style={{ marginTop: 14 }} />) : null}
    </Card>
  );
}

// ── видео ───────────────────────────────────────────────────────────────────
export function VideoScreen({ n }: { n: number }) {
  const { state, tr, back, push, haptic } = useApp();
  const pr = useProgress();
  const V = state!.video.videos;
  const i = V.findIndex((v) => v.n === n);
  const v: Video | undefined = V[i];
  if (!v) return <Screen title="" onBack={back} tabbar={false}><T v="sub">—</T></Screen>;
  const watched = pr.videos.has(v.yt);
  const nx = V[i + 1];
  const level = state!.video.levels.find((x) => x.id === v.level);
  return (
    <Screen title={tr("video_n", { n: v.n })} onBack={back} tabbar={false}>
      <FadeIn>
        <Press onPress={() => WebBrowser.openBrowserAsync(v.url).catch(() => {})}>
          <View style={s.thumb}>
            <Thumb yt={v.yt} />
            <View style={s.play}><Icon name="play" size={44} color={C.gold1} stroke={1.6} /></View>
          </View>
        </Press>
        {level ? <T v="cap" style={{ marginTop: 14 }}>{level.icon} {level.title}</T> : null}
        <T v="h2" style={{ marginTop: 6 }}>{v.title}</T>
        <T v="sub" style={{ marginTop: 6 }}>{v.sub}</T>
        <T v="small" style={{ marginTop: 8 }}>{tr("video_by", { channel: v.channel })}</T>
        {v.tested ? <View style={{ marginTop: 10 }}><Chip kind="ok" text={`✅ ${tr("video_tested")}`} /></View> : null}
        <Btn title={tr("watch_yt")} icon="play" onPress={() => WebBrowser.openBrowserAsync(v.url).catch(() => {})} style={{ marginTop: 18 }} />
        <T v="small" style={{ marginTop: 8 }} center>{tr("subs_hint")}</T>
        <Btn title={watched ? `✓ ${tr("video_watched")}` : tr("video_mark")} kind={watched ? "ghost" : "dark"}
          onPress={() => { pr.markVideo(v.yt, !watched); haptic(watched ? "sel" : "success"); }} style={{ marginTop: 14 }} />
        {nx ? <Btn title={`${tr("video_next")} →`} kind="ghost" onPress={() => { back(); push({ name: "video", n: nx.n }); }} style={{ marginTop: 10 }} /> : null}
      </FadeIn>
    </Screen>
  );
}

function Thumb({ yt }: { yt: string }) {
  return <ExpoImage source={{ uri: `https://i.ytimg.com/vi/${yt}/hqdefault.jpg` }} style={StyleSheet.absoluteFill} contentFit="cover" transition={250} />;
}

const s = StyleSheet.create({
  num: { width: 44, height: 44, borderRadius: 14, backgroundColor: "rgba(247,212,107,0.1)", alignItems: "center", justifyContent: "center" },
  numDone: { backgroundColor: C.gold2 },
  emoji: { fontSize: 21 },
  vn: { color: C.gold2, fontWeight: "900", fontSize: 16 },
  p: { marginBottom: 14, lineHeight: 23, fontSize: 15.5 },
  bullet: { width: 6, height: 6, borderRadius: 3, backgroundColor: C.gold2, marginTop: 8, marginRight: 10 },
  callout: { flexDirection: "row", padding: 14, borderRadius: 16, marginBottom: 14, borderWidth: 1 },
  tip: { backgroundColor: "rgba(98,168,255,0.08)", borderColor: "rgba(98,168,255,0.3)" },
  warn: { backgroundColor: "rgba(247,184,75,0.08)", borderColor: "rgba(247,184,75,0.3)" },
  ex: { borderRadius: 16, borderWidth: 1, borderColor: C.line, marginBottom: 14, overflow: "hidden", backgroundColor: "rgba(255,255,255,0.03)" },
  exHead: { padding: 12, backgroundColor: "rgba(247,212,107,0.08)" },
  exRow: { paddingHorizontal: 12, paddingVertical: 10 },
  plRow: { flexDirection: "row", paddingVertical: 9, paddingHorizontal: 6 },
  plCell: { flex: 1, color: C.text, fontSize: 12.5, textAlign: "center" },
  plFirst: { flex: 1.3, textAlign: "left", paddingLeft: 4 },
  calcIn: {
    marginTop: 4, backgroundColor: "rgba(255,255,255,0.06)", borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10,
    color: C.text, fontSize: 17, fontWeight: "800", borderWidth: 1, borderColor: C.line2,
  },
  q: { flexDirection: "row", alignItems: "center", padding: 12, borderRadius: 14, marginTop: 10, borderWidth: 1, borderColor: C.line2, backgroundColor: "rgba(255,255,255,0.03)" },
  qOk: { borderColor: C.green, backgroundColor: "rgba(62,224,154,0.1)" },
  qNo: { borderColor: C.red, backgroundColor: "rgba(255,93,115,0.08)" },
  qk: { width: 28, height: 28, borderRadius: 9, backgroundColor: "rgba(247,212,107,0.12)", alignItems: "center", justifyContent: "center" },
  thumb: { height: 200, borderRadius: 20, overflow: "hidden", backgroundColor: "#000", borderWidth: 1, borderColor: C.line, alignItems: "center", justifyContent: "center" },
  play: { width: 76, height: 76, borderRadius: 38, backgroundColor: "rgba(0,0,0,0.55)", alignItems: "center", justifyContent: "center" },
});
