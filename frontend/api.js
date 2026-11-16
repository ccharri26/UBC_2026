// The only file that knows the API's URLs. A future React (or any) UI can import
// this module unchanged; everything else in frontend/ is replaceable view code.
// Full schemas: http://127.0.0.1:8000/docs (FastAPI generates them from api/app.py).

const BASE = "/api";

async function request(path, options = {}) {
  const resp = await fetch(BASE + path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {}
    throw new Error(`${resp.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  }
  return resp.json();
}

// { kill_switch (effective: true = no spending), env_lock (KILL_SWITCH in .env), dashboard_stopped, stub_mode, paused_after_failures,
//   wallet_address, spent_today_usd, daily_budget_usd, remaining_today_usd,
//   per_run_budget_usd, per_market_budget_usd, max_per_call_usd, config_error, ledger_error (string or null: bad payments ledger, spending blocked) }
export const getStatus = () => request("/status");

// { address, usdc }
export const getWallet = () => request("/wallet");

// [{ at, status: "settled"|"failed"|"pending", tier, amount_usd, market, tx_hash, tx_url, detail }]
export const getPayments = (limit = 50) => request(`/payments?limit=${limit}`);

// { mode: "stub"|"live", signals: [NansenSignals + cost_usd, horizons], errors: [...] }
export const getSignals = () => request("/signals");

// on=true stops all spending. Turning it back on requires confirm=true, and fails (409)
// while env_lock is set: only a hand edit of .env clears that.
export const setKillSwitch = (on, confirm = false) =>
  request("/kill-switch", { method: "POST", body: JSON.stringify({ on, confirm }) });
