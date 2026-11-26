import React, { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { fmtDate, money, parseNum, usd2 } from "../format";
import { openBot, useTelegramLink } from "../hooks";
import { useApp } from "../store";
import { C, num, signColor } from "../theme";
import type { Account, State } from "../types";
import { Icon } from "../ui/icons";
import { Bar, Between, Btn, Card, CardTitle, Chip, FadeIn, Kpi, KpiGrid, Pills, Press, Ring, Row, T, Toggle } from "../ui/kit";
import { Screen } from "../ui/layout";

type Form = { plan: string | null; stage: string | null; size: number | null; only: boolean };

export default function Prop() {
  const { state, tr, refresh } = useApp();
  const [edit, setEdit] = useState(false);
  const S = state!;
  return (
    <Screen onRefresh={refresh}>
      <FadeIn><T v="h1" style={{ marginBottom: 14 }}>{tr("tab_prop")}</T></FadeIn>
      {S.prop && !edit ? <Dashboard S={S} onEdit={() => setEdit(true)} /> : <PropForm S={S} onDone={() => setEdit(false)} editing={edit} />}
      <Accounts S={S} />
    </Screen>
  );
}

function LimitBar({ title, left, total, extra }: { title: string; left: number; total: number; extra: string }) {
  const { tr } = useApp();
  const t = Math.max(total, left);
  const f = t > 0 ? Math.max(0, Math.min(1, left / t)) : 0;
  return (
    <View style={{ marginTop: 14 }}>
      <Between>
        <T style={{ fontWeight: "700", flex: 1 }}>{title}</T>
        <Text style={[num, { color: C.text, fontWeight: "800" }]}>{usd2(left)} <Text style={{ color: C.muted, fontWeight: "500" }}>/ {usd2(t)}</Text></Text>
      </Between>
      <Bar frac={f} color={f > 0.5 ? "g" : f > 0.25 ? "y" : "r"} />
      <T v="small" style={{ marginTop: 6 }}>{tr("can_lose")} · {extra}</T>
    </View>
  );
}

function Dashboard({ S, onEdit }: { S: State; onEdit: () => void }) {
  const { tr, call, ask, confirm } = useApp();
  const p = S.prop!;
  const f = p.progress;
  const setBalance = async () => {
    const v = await ask({ title: tr("set_balance"), hint: tr("balance_hint"), value: String(p.balance), keyboard: "numeric" });
    if (v == null) return;
    const n = parseNum(v);
    if (n == null || n < 0) return;
    await call("prop", { action: "balance", balance: n }, tr("saved"));
  };
  return (
    <>
      <FadeIn delay={40}>
        <Card gold>
          <Between>
            <T v="h3">{tr("prop_title")}</T>
            <Chip text={p.stage_name} kind="warn" />
          </Between>
          <T v="sub" style={{ marginTop: 4 }}>{p.plan_name} · {money(p.size)}</T>
          <Row style={{ marginTop: 16 }}>
            <Ring frac={f ?? 1} size={136} label={f != null ? `${Math.round(f * 100)}%` : "★"} sub={f != null ? tr("progress") : p.stage_name} />
            <View style={{ flex: 1, paddingLeft: 16 }}>
              <T v="small">{tr("balance")}</T>
              <Text style={[num, { color: C.text, fontSize: 26, fontWeight: "800" }]} numberOfLines={1} adjustsFontSizeToFit>{usd2(p.balance)}</Text>
              <Row style={{ marginTop: 8, gap: 16 }}>
                <View>
                  <T v="small">{tr("profit")}</T>
                  <Text style={[num, { color: signColor(p.profit_pct), fontWeight: "800" }]}>{p.profit_pct >= 0 ? "+" : ""}{p.profit_pct.toFixed(2)}%</Text>
                </View>
                {p.goal != null ? (
                  <View>
                    <T v="small">{tr("to_goal")}</T>
                    <Text style={[num, { color: C.text, fontWeight: "800" }]}>{usd2(p.to_goal)}</Text>
                  </View>
                ) : null}
              </Row>
            </View>
          </Row>
          <T v="sub" style={{ marginTop: 12 }}>
            {p.goal != null ? `${tr("goal")}: ${usd2(p.goal)} (+${p.target_pct}%)` : tr("funded")}
          </T>
          {p.passed ? <View style={{ marginTop: 10 }}><Chip kind="ok" text={`🏆 ${tr("passed")} · ${tr("passed_days", { days: p.days, min: p.min_days })}`} /></View> : null}
          {p.next_stage ? <Btn title={tr("next_stage", { stage: p.next_stage_name ?? "" })} icon="trophy" onPress={() => call("prop", { action: "next" }, tr("saved"))} style={{ marginTop: 14 }} /> : null}
        </Card>
      </FadeIn>

      <FadeIn delay={90}>
        <Card>
          <CardTitle icon="shield">{`${tr("day_limit")} / ${tr("total_limit")}`}</CardTitle>
          {p.day_stopped ? <Chip kind="bad" text={`⛔ ${tr("day_stopped", { time: p.reset })}`} /> : null}
          {p.failed ? <View style={{ marginTop: 8 }}><Chip kind="bad" text={`⚠️ ${tr("failed")}`} /></View> : null}
          <LimitBar title={tr("day_limit")} left={p.day_left} total={p.day_limit} extra={`${tr("floor")} ${usd2(p.day_floor)}`} />
          <LimitBar title={tr("total_limit") + (p.trailing ? ` · ${tr("trailing")}` : "")} left={p.total_left} total={p.total_limit}
            extra={`${tr("floor")} ${usd2(p.total_floor)}`} />
          <View style={{ marginTop: 14 }}>
            <KpiGrid cols={2}>
              <Kpi value={`${+p.risk_pct.toFixed(2)}%`} label={`${tr("risk_next")} · ${usd2(p.risk_usd)}`} color={C.gold2} />
              <Kpi value={`${p.days}${p.min_days ? ` / ${p.min_days}` : ""}`} label={tr("trade_days")} />
            </KpiGrid>
          </View>
          {p.low_risk ? <T v="small" style={{ marginTop: 6 }}>↓ {tr("risk_low")}</T> : null}
        </Card>
      </FadeIn>

      <FadeIn delay={130}>
        <Card>
          <Btn title={tr("set_balance")} icon="wallet" onPress={setBalance} />
          <Toggle on={p.only_prop} title={tr("only_prop")} hint={tr("only_prop_hint")}
            onPress={() => call("prop", { action: "only", value: !p.only_prop }, tr("saved"))} />
          <Btn title={tr("edit")} kind="ghost" icon="edit" small onPress={onEdit} style={{ marginTop: 4 }} />
          <Btn title={tr("turn_off")} kind="red" small style={{ marginTop: 10 }}
            onPress={async () => { if (await confirm(tr("turn_off_q"), true)) await call("prop", { action: "off" }, tr("saved")); }} />
        </Card>
      </FadeIn>
    </>
  );
}

function PropForm({ S, onDone, editing }: { S: State; onDone: () => void; editing: boolean }) {
  const { tr, call, ask, showToast, haptic } = useApp();
  const [f, setF] = useState<Form>(() => S.prop
    ? { plan: S.prop.plan, stage: S.prop.stage, size: S.prop.size, only: S.prop.only_prop }
    : { plan: null, stage: null, size: null, only: false });
  const [busy, setBusy] = useState(false);
  const plan = S.plans.find((x) => x.key === f.plan);
  const custom = f.size != null && !S.sizes.includes(f.size);

  const customSize = async () => {
    const v = await ask({ title: tr("size"), hint: `${money(S.size_min)} – ${money(S.size_max)}`, value: f.size ? String(f.size) : "", keyboard: "numeric" });
    if (v == null) return;
    const n = parseNum(v);
    if (n == null || n < S.size_min || n > S.size_max) return showToast(tr("bad_number"), "err");
    setF({ ...f, size: n });
  };
  const save = async () => {
    setBusy(true);
    const ok = await call("prop", { action: "save", plan: f.plan, stage: f.stage, size: f.size, only: f.only }, tr("saved"));
    setBusy(false);
    if (ok) onDone();
  };

  return (
    <>
      <FadeIn delay={40}>
        <Card gold>
          <Row><Icon name="shield" size={22} color={C.gold2} /><T v="cap" style={{ marginLeft: 8 }}>{tr("prop_title")}</T></Row>
          <T v="h3" style={{ marginTop: 10 }}>{tr("prop_sub")}</T>
          <T v="sub" style={{ marginTop: 6 }}>{tr("prop_intro")}</T>
        </Card>
      </FadeIn>
      <FadeIn delay={90}>
        <Card>
          <T v="cap" style={{ marginBottom: 10 }}>{tr("plan")}</T>
          {S.plans.map((p) => {
            const on = p.key === f.plan;
            const targets = Object.values(p.targets);
            return (
              <Press key={p.key} onPress={() => { haptic("sel"); setF({ ...f, plan: p.key, stage: null }); }}>
                <View style={[s.opt, on && s.optOn]}>
                  <View style={{ flex: 1 }}>
                    <T style={{ fontWeight: "800", color: on ? C.gold1 : C.text }}>{p.name}</T>
                    <T v="small" style={{ marginTop: 3 }}>
                      {p.daily ? `${tr("day_limit")} ${p.daily}% · ` : ""}{tr("total_limit")} {p.total}%{p.trailing ? ` (${tr("trailing")})` : ""}
                      {targets.length ? ` · ${targets.map((v) => `+${v}%`).join(" / ")}` : ""}
                    </T>
                  </View>
                  <View style={[s.radio, on && s.radioOn]}>{on ? <Icon name="check" size={14} color="#1a1204" stroke={3} /> : null}</View>
                </View>
              </Press>
            );
          })}
          {plan ? (
            <>
              <T v="cap" style={{ marginTop: 16, marginBottom: 10 }}>{tr("stage")}</T>
              <Pills items={plan.stages.map((x) => [x.key, x.name] as [string, string])} value={f.stage}
                onChange={(k) => { haptic("sel"); setF({ ...f, stage: k }); }} />
            </>
          ) : null}
          {plan && f.stage ? (
            <>
              <T v="cap" style={{ marginTop: 16, marginBottom: 10 }}>{tr("size")}</T>
              <Pills items={[...S.sizes.map((z) => [z, `$${z / 1000}K`] as [number, string]), [-1, custom ? money(f.size) : tr("custom")]]}
                value={custom ? -1 : f.size} onChange={(z) => { haptic("sel"); if (z === -1) customSize(); else setF({ ...f, size: z }); }} />
              <Toggle on={f.only} title={tr("only_prop")} hint={tr("only_prop_hint")} onPress={() => setF({ ...f, only: !f.only })} />
            </>
          ) : null}
          <Btn title={S.prop ? tr("save") : tr("start_prop")} disabled={!(plan && f.stage && f.size)} loading={busy} onPress={save} style={{ marginTop: 12 }} />
          {editing ? <Btn title={tr("cancel")} kind="ghost" onPress={onDone} style={{ marginTop: 10 }} /> : null}
        </Card>
      </FadeIn>
    </>
  );
}

function Accounts({ S }: { S: State }) {
  const { tr, call } = useApp();
  const link = useTelegramLink();
  if (!S.auto.enabled) return null;
  return (
    <FadeIn delay={170}>
      <Card>
        <CardTitle icon="robot">{tr("auto_title")}</CardTitle>
        <T v="sub" style={{ marginTop: -6 }}>{tr("accounts_sub")}</T>
        {!S.me.telegram ? (
          <>
            <T v="sub" style={{ marginTop: 10 }}>{tr("auto_tg_needed")}</T>
            <Btn title={link.waiting ? tr("tg_wait") : tr("tg_link")} icon="telegram" loading={link.waiting} onPress={link.start} style={{ marginTop: 14 }} />
          </>
        ) : (
          <>
            {S.accounts.length ? S.accounts.map((a) => <AccountRow key={a.id} a={a} tz={S.tz}
              onToggle={() => call("account", { id: a.id, action: a.enabled ? "pause" : "resume" }, tr("saved"))} />)
              : <T v="sub" style={{ marginTop: 10 }}>{tr("no_accounts")}</T>}
            <Btn title={S.accounts.length ? tr("auto_manage") : tr("auto_connect")} icon="telegram" kind="ghost"
              onPress={() => openBot(S.me.bot_url)} style={{ marginTop: 14 }} />
            <Row style={{ marginTop: 10 }}><Icon name="lock" size={14} color={C.dim} /><T v="small" style={{ marginLeft: 6, flex: 1 }}>{tr("goes_bot")}</T></Row>
          </>
        )}
        {!S.user.admin ? <T v="small" style={{ marginTop: 8 }}>{tr("auto_price", { usd: S.auto.usd })}</T> : null}
      </Card>
    </FadeIn>
  );
}

function AccountRow({ a, tz, onToggle }: { a: Account; tz: string; onToggle: () => void }) {
  const { tr } = useApp();
  const pp = a.prop;
  const stText = a.read_only ? tr("price_only") : a.enabled ? tr("running") : tr("paused");
  return (
    <View style={s.acc}>
      <Between>
        <Row style={{ flex: 1, flexWrap: "wrap", gap: 6 }}>
          <Text style={[num, { color: C.text, fontWeight: "800", fontSize: 16 }]}>{a.login}</Text>
          <Chip text={a.demo ? tr("demo") : tr("real")} kind={a.demo ? "dim" : "gold"} />
          {pp ? <Chip text={pp.plan_name} kind="warn" /> : null}
        </Row>
        <Chip text={`● ${stText}`} kind={a.enabled && !a.read_only ? "ok" : "warn"} />
      </Between>
      <T v="small" style={{ marginTop: 4 }}>{a.broker || a.server} · {a.platform.toUpperCase()}</T>
      <View style={{ marginTop: 10 }}>
        <KpiGrid cols={2}>
          <Kpi value={a.balance != null ? money(a.balance, 2) : "—"} label={tr("balance")} />
          <Kpi value={a.equity != null ? money(a.equity, 2) : "—"} label={tr("equity")} />
        </KpiGrid>
      </View>
      {pp && pp.progress != null ? (
        <>
          <Between style={{ marginTop: 8 }}>
            <T v="small">{pp.stage_name} · {tr("goal")} {usd2(pp.goal)}</T>
            <Text style={[num, { color: C.gold2, fontWeight: "800" }]}>{Math.round(pp.progress * 100)}%</Text>
          </Between>
          <Bar frac={pp.progress} />
        </>
      ) : null}
      {pp?.halt ? <View style={{ marginTop: 8 }}><Chip kind="bad" text={tr(`halt_${pp.halt}`)} /></View> : null}
      <Between style={{ marginTop: 10 }}>
        <T v="small" style={{ flex: 1 }}>{a.admin ? tr("admin_free") : a.paid_until ? tr("paid_until", { date: fmtDate(a.paid_until, tz, false) }) : ""}</T>
        {!a.read_only ? <Btn small kind={a.enabled ? "ghost" : "gold"} title={a.enabled ? tr("pause") : tr("resume")} onPress={onToggle} style={{ minWidth: 120 }} /> : null}
      </Between>
    </View>
  );
}

const s = StyleSheet.create({
  opt: {
    flexDirection: "row", alignItems: "center", padding: 14, borderRadius: 16, marginBottom: 8,
    backgroundColor: "rgba(255,255,255,0.03)", borderWidth: 1, borderColor: C.line2,
  },
  optOn: { borderColor: C.gold3, backgroundColor: "rgba(247,212,107,0.08)" },
  radio: { width: 24, height: 24, borderRadius: 12, borderWidth: 2, borderColor: C.dim, alignItems: "center", justifyContent: "center", marginLeft: 10 },
  radioOn: { borderColor: C.gold2, backgroundColor: C.gold2 },
  acc: { marginTop: 14, padding: 14, borderRadius: 18, backgroundColor: "rgba(255,255,255,0.03)", borderWidth: StyleSheet.hairlineWidth, borderColor: C.line2 },
});
