// The only file that knows the API's URLs and response shapes. Everything else in
// src/ is view code. Full schemas: http://127.0.0.1:8000/docs (generated from api/app.py).

const BASE = "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(BASE + path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    let detail: unknown = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {
      // not JSON: keep the status text
    }
    throw new ApiError(resp.status, `${resp.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  }
  return resp.json() as Promise<T>;
}

export type Tier = "basic" | "smart_money";

export interface Status {
  kill_switch: boolean; // effective: true = no spending
  env_lock: boolean; // KILL_SWITCH in .env; only a hand edit clears it
  dashboard_stopped: boolean;
  stub_mode: boolean;
  paused_after_failures: boolean;
  wallet_address: string | null;
  spent_today_usd: number;
  daily_budget_usd: number | null;
  remaining_today_usd: number | null;
  per_run_budget_usd: number | null;
  per_market_budget_usd: number | null; // per (asset, Tier) per UTC day
  max_per_call_usd: number;
  config_error: string | null;
  ledger_error: string | null; // bad payments ledger: spending blocked
}

export interface Wallet {
  address: string;
  usdc: number;
}

export interface Payment {
  at: string | null;
  status: "settled" | "failed" | "pending";
  tier: Tier | "unknown";
  amount_usd: number;
  market: string | null; // e.g. "ETH-smart_money"
  tx_hash: string | null;
  tx_url: string | null;
  detail: string | null;
}

export interface Signal {
  asset: string;
  tier: Tier;
  fetched_at: string;
  cost_usd: number;
  horizons: string[];
  smart_trader_net_flow_usd: number | null;
  whale_net_flow_usd: number | null;
  exchange_net_flow_usd: number | null;
  smart_trader_wallet_count: number | null;
  sm_net_flow_1h_usd: number | null;
  sm_trader_count: number | null;
}

export interface Signals {
  mode: "stub" | "live";
  signals: Signal[];
  errors: { asset: string; horizon: string; error: string }[];
}

export interface Quote {
  event: string;
  strike: number;
  mins_left: number;
  bid: number;
  ask: number;
  baseline: number;
  informed: number | null;
  yes_edge: number | null;
  no_edge: number | null;
  call: "BUY YES" | "BUY NO" | "pass";
}

export interface Trade {
  event: string;
  strike: number;
  side: "YES" | "NO";
  price: number;
  contracts: number;
  fee_usd: number;
  edge: number;
  mode: "shadow" | "sandbox";
  result: "won" | "lost" | null; // null until the Event settles
  pnl_usd: number | null;
}

export interface Decision {
  at: string;
  cycle: number;
  stub: boolean;
  asset: string;
  tier: Tier;
  spot: number;
  minute_vol: number;
  decided_by: "rule" | "llm";
  llm_override: boolean; // the LLM bought data the value check said to skip
  info: {
    value_usd: number;
    price_usd: number;
    buy: boolean;
    reason: string;
    source: "paid" | "cached" | "none";
    cost_usd: number;
    reading: number | null;
    error: string | null;
    spent: boolean;
  };
  quotes: Quote[];
  trades: Trade[];
}

export interface Decisions {
  rows: Decision[]; // newest first
  skipped: number;
}

export interface ScoreGroup {
  events: number;
  brier_baseline: number | null;
  brier_market: number | null;
  events_with_data: number;
  brier_informed: number | null;
  brier_baseline_same_events: number | null;
  trades: number;
  trades_won: number;
  pnl_usd: number;
  staked_usd: number;
  return_on_stake: number | null;
  pnl_with_data_usd: number;
  data_cost_usd: number;
  net_pnl_usd: number; // Profit
}

export interface Score {
  include_stub: boolean;
  unsettled_or_unmatched: number;
  overall: ScoreGroup;
  by_decided_by: Record<string, ScoreGroup>;
  by_tier: Record<string, ScoreGroup>;
  by_asset: Record<string, ScoreGroup>;
}

export const getStatus = () => request<Status>("/status");
export const getWallet = () => request<Wallet>("/wallet");
export const getPayments = (limit = 50) => request<Payment[]>(`/payments?limit=${limit}`);
export const getSignals = () => request<Signals>("/signals");
export const getDecisions = (limit = 50) => request<Decisions>(`/decisions?limit=${limit}`);
// include_stub defaults (server side) to the current stub mode.
export const getScore = () => request<Score>("/score");

// on=true stops all spending. Turning it back on requires confirm=true, and fails (409)
// while env_lock is set: only a hand edit of .env clears that.
export const setKillSwitch = (on: boolean, confirm = false) =>
  request<Status>("/kill-switch", { method: "POST", body: JSON.stringify({ on, confirm }) });
