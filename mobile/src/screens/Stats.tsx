import * as WebBrowser from "expo-web-browser";
import React, { useMemo, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { fmtDate, pips } from "../format";
import { byStrategy, calc, filterTrades, periodTrades, type Filter } from "../stats";
import { useApp } from "../store";
import { C, num, signColor } from "../theme";
import type { Trade } from "../types";
import { EquityChart } from "../ui/chart";
import { Icon } from "../ui/icons";
import { Bar, Between, Btn, Card, CardTitle, FadeIn, Kpi, KpiGrid, Pills, Ring, Row, Seg, T } from "../ui/kit";
import { Screen } from "../ui/layout";

const STATUS: Record<string, string> = { tp: "st_tp", sl: "st_sl", be: "st_be", rev: "st_rev", news: "st_news", open: "st_open" };

export default function Stats() {
  const { state, tr, refresh, haptic } = useApp();
  const [period, setPeriod] = useState(30);
  const [filter, setFilter] = useState<Filter>("all");
  const [show, setShow] = useState(25);
  const S = state!;
  const win = S.stats.win;
  const list = useMemo(() => periodTrades(S.stats.trades, period), [S.stats.trades, period]);
  const c = useMemo(() => calc(list, win), [list, win]);
  const strat = useMemo(() => byStrategy(list, win), [list, win]);
  const fl = useMemo(() => filterTrades(list, filter, win), [list, filter, win]);
  const mx = Math.max(1, ...strat.map((r) => Math.abs(r.p)));

  return (
    <Screen onRefresh={refresh}>
      <FadeIn><T v="h1" style={{ marginBottom: 14 }}>{tr("tab_stats")}</T></FadeIn>
      <FadeIn delay={40}>
        <Seg items={[[7, tr("p7")], [30, tr("p30")], [90, tr("p90")], [0, tr("pall")]]} value={period}
          onChange={(d) => { haptic("sel"); setPeriod(d); setShow(25); }} />
      </FadeIn>

      <FadeIn delay={90}>
        <Card gold style={{ marginTop: 12 }}>
          <Row>
            <Ring frac={(c.wr ?? 0) / 100} size={128} label={c.wr != null ? `${Math.round(c.wr)}%` : "—"} sub={tr("wr")} />
            <View style={{ flex: 1, flexDirection: "row", flexWrap: "wrap" }}>
              <Big label={tr("total_pips")} value={pips(c.total)} color={signColor(c.total)} />
              <Big label={tr("signals")} value={String(c.n)} />
              <Big label={tr("wins")} value={String(c.w)} color={C.green} />
              <Big label={tr("losses")} value={String(c.l)} color={C.red} />
            </View>
          </Row>
        </Card>
      </FadeIn>

      <FadeIn delay={140}>
        <KpiGrid>
          <Kpi value={c.pf == null ? "—" : c.pf === Infinity ? "∞" : c.pf.toFixed(2)} label={tr("pf")} color={C.gold2} />
          <Kpi value={pips(c.best)} label={tr("best")} color={C.green} />
          <Kpi value={pips(c.worst)} label={tr("worst")} color={C.red} />
          <Kpi value={pips(c.avg)} label={tr("avg")} color={signColor(c.avg)} />
          <Kpi value={c.dd ? pips(-c.dd) : "0"} label={tr("max_dd")} color={C.red} />
          <Kpi value={String(c.streak)} label={tr("streak")} color={C.gold2} />
        </KpiGrid>
      </FadeIn>

      <FadeIn delay={190}>
        <Card style={{ marginTop: 8 }}>
          <CardTitle icon="spark">{tr("curve")}</CardTitle>
          <T v="small" style={{ marginTop: -6 }}>{tr("curve_note")}</T>
          <EquityChart pts={c.pts} height={190} empty={tr("no_trades")} />
        </Card>
      </FadeIn>

      {strat.length ? (
        <FadeIn delay={230}>
          <Card>
            <CardTitle icon="robot">{tr("by_strategy")}</CardTitle>
            {strat.map((r) => (
              <View key={r.key} style={{ marginBottom: 12 }}>
                <Between>
                  <T style={{ flex: 1, marginRight: 8 }} numberOfLines={1}>{S.stats.strategies[r.key] || r.key}</T>
                  <Text style={[num, { color: signColor(r.p), fontWeight: "800" }]}>{pips(r.p)}</Text>
                </Between>
                <Bar frac={Math.abs(r.p) / mx} color={r.p >= 0 ? "g" : "r"} height={6} />
                <T v="small" style={{ marginTop: 4 }}>{r.n} · {tr("wr")} {r.w + r.l ? `${Math.round((100 * r.w) / (r.w + r.l))}%` : "—"}</T>
              </View>
            ))}
          </Card>
        </FadeIn>
      ) : null}

      <FadeIn delay={260}>
        <Card>
          <CardTitle icon="news">{tr("history")}</CardTitle>
          <Pills items={[["all", tr("f_all")], ["win", tr("f_win")], ["loss", tr("f_loss")], ["open", tr("f_open")]] as [Filter, string][]}
            value={filter} onChange={(f) => { haptic("sel"); setFilter(f); setShow(25); }} />
          <View style={{ marginTop: 8 }}>
            {fl.length ? fl.slice(0, show).map((x) => <TradeRow key={x.id} x={x} win={win} tz={S.tz} tr={tr} />)
              : <T v="sub" center style={{ paddingVertical: 24 }}>{tr("no_trades")}</T>}
          </View>
          {fl.length > show ? <Btn title={tr("more")} kind="ghost" small onPress={() => setShow(show + 25)} style={{ marginTop: 10 }} /> : null}
        </Card>
      </FadeIn>
      {S.myfxbook ? <Btn title={tr("myfxbook")} kind="ghost" icon="shield" onPress={() => WebBrowser.openBrowserAsync(S.myfxbook!).catch(() => {})} /> : null}
    </Screen>
  );
}

function Big({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <View style={{ width: "50%", paddingLeft: 14, paddingVertical: 7 }}>
      <T v="small">{label}</T>
      <Text style={[num, { color: color ?? C.text, fontSize: 20, fontWeight: "800", marginTop: 2 }]} numberOfLines={1} adjustsFontSizeToFit>{value}</Text>
    </View>
  );
}

function TradeRow({ x, win, tz, tr }: { x: Trade; win: string[]; tz: string; tr: (k: string) => string }) {
  const open = x.status === "open";
  const good = win.includes(x.status);
  const col = open ? C.gold2 : good ? C.green : x.status === "sl" ? C.red : C.muted;
  return (
    <View style={s.row}>
      <View style={[s.ic, { backgroundColor: col + "1f" }]}>
        <View style={x.dir === -1 ? { transform: [{ scaleY: -1 }] } : null}><Icon name="signal" size={16} color={col} stroke={2.2} /></View>
      </View>
      <View style={{ flex: 1, marginLeft: 12 }}>
        <Text style={s.title}>{x.dir === 1 ? "BUY" : "SELL"} <Text style={{ color: C.muted }}>#{x.id}</Text></Text>
        <T v="small" numberOfLines={1}>{fmtDate(x.ts, tz)} · {tr(STATUS[x.status] ?? "st_closed")} · {x.entry.toFixed(2)}</T>
      </View>
      <View style={{ alignItems: "flex-end" }}>
        <Text style={[num, { color: open ? C.gold2 : signColor(x.pips), fontWeight: "800", fontSize: 16 }]}>{open ? "⏳" : pips(x.pips)}</Text>
        <T v="small">{tr("pips")}</T>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", paddingVertical: 11, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: C.line2 },
  ic: { width: 36, height: 36, borderRadius: 11, alignItems: "center", justifyContent: "center" },
  title: { color: C.text, fontWeight: "800", fontSize: 14.5 },
});
