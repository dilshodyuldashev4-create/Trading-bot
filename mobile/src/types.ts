// Ответ сервера /m/api/state — те же данные, что у Mini App, плюс me/links
export type Lang = "ru" | "uz" | "en";

export type Trade = {
  id: number; ts: string; closed: string | null; dir: 1 | -1; entry: number; sl: number; tp: number;
  status: string; pips: number | null; strategy: string; part: boolean;
};

export type OpenSignal = {
  id: number; dir: 1 | -1; entry: number; sl: number; tp: number; ts: string; tp1: number | null; part: boolean;
};

export type Market = { price: number | null; open: OpenSignal[] };

export type PropSub = {
  plan: string; plan_name: string; stage: string; stage_name: string; size: number; balance: number;
  profit_pct: number; goal: number | null; to_goal: number | null; target_pct: number; progress: number | null;
  day_left: number; day_limit: number; day_floor: number; total_left: number; total_floor: number; total_limit: number;
  daily_pct: number; total_pct: number; trailing: boolean; risk_pct: number; risk_usd: number; low_risk: boolean;
  passed: boolean; failed: boolean; days: number; min_days: number; only_prop: boolean; enabled: boolean;
  day_stopped: boolean; reset: string; next_stage: string | null; next_stage_name: string | null;
};

export type Plan = {
  key: string; name: string; daily: number; total: number; trailing: boolean; min_days: number;
  targets: Record<string, number>; stages: { key: string; name: string }[];
};

export type Account = {
  id: number; login: string; server: string; broker: string; platform: string; demo: boolean; enabled: boolean;
  balance: number | null; equity: number | null; currency: string; paid_until: string | null; admin: boolean;
  read_only: boolean;
  prop: null | {
    plan_name: string; stage: string; stage_name: string; size: number; goal: number | null; progress: number | null;
    to_goal: number | null; day_loss: number; day_limit: number; day_left: number; total_floor: number; days: number;
    min_days: number; halt: string; target_pct: number;
  };
};

export type Block =
  | { t: "p" | "h" | "tip" | "warn"; x: string }
  | { t: "list"; x: string[] }
  | { t: "ex"; h: string; rows: [string, string][] }
  | { t: "plans" } | { t: "calc" }
  | { t: "go"; to: "profile" | "prop" | "stats" | "connect"; x: string };

export type Lesson = {
  id: string; icon: string; min: number; title: string; sub: string; blocks: Block[];
  quiz: { q: string; a: string[]; why: string };
};

export type Video = {
  n: number; level: number; yt: string; channel: string; tested: boolean; title: string; sub: string; url: string;
};

export type State = {
  lang: Lang; langs: { code: Lang; name: string }[]; t: Record<string, string>; tz: string;
  user: { id: number | null; name: string; admin: boolean; capital: number | null; lot: number | null;
    lot_loss: number | null; lot_profit: number | null };
  auto: { enabled: boolean; usd: number; days: number; stars: number; month_stars: number; credits: number };
  market: Market;
  stats: { trades: Trade[]; strategies: Record<string, string>; win: string[] };
  prop: PropSub | null; plans: Plan[]; sizes: number[]; size_min: number; size_max: number;
  accounts: Account[]; myfxbook: string | null; fundednext: string | null; pip: number;
  learn: { lessons: Lesson[]; vars: Record<string, string> };
  video: { levels: { id: number; icon: string; title: string }[]; videos: Video[] };
  me: { email: string | null; telegram: boolean; bot: string | null; bot_url: string | null };
  links: { broker: string | null; broker_name: string | null; fundednext: string | null; myfxbook: string | null };
};

export type CalEvent = {
  ts: string; title: string; impact: string; country: string; forecast: string; previous: string; actual: string;
  effect: string;
};
