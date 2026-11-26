// Цвета и размеры — те же, что в Telegram Mini App (тёмный фон и золото)
export const C = {
  bg: "#070a12",
  bg2: "#0c111d",
  card: "rgba(255,255,255,0.045)",
  card2: "rgba(255,255,255,0.07)",
  line: "rgba(255,215,120,0.14)",
  line2: "rgba(255,255,255,0.08)",
  text: "#f4f1e8",
  muted: "#8f97a8",
  dim: "#5d6578",
  gold1: "#fff4c9",
  gold2: "#f7d46b",
  gold3: "#e2a930",
  gold4: "#a66d10",
  green: "#3ee09a",
  red: "#ff5d73",
  blue: "#62a8ff",
  warn: "#f7b84b",
};

export const GOLD = [C.gold1, C.gold2, C.gold3, C.gold4] as const;
export const GOLD_STOPS = [0, 0.3, 0.65, 1] as const;

export const R = 22;
export const PAD = 16;

export const num = { fontVariant: ["tabular-nums" as const] };

export function signColor(v: number | null | undefined): string {
  if (v == null || v === 0) return C.text;
  return v > 0 ? C.green : C.red;
}
