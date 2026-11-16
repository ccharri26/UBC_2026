// View code for the plain-HTML dashboard. Each render* function takes plain data
// from api.js and redraws one panel, so each maps 1:1 to a future React component.
// All text from the API goes in via textContent (never innerHTML).

import { getDecisions, getPayments, getSignals, getStatus, getWallet, setKillSwitch } from "./api.js";

const FAST_MS = 5_000; // status, payments, signals
const SLOW_MS = 30_000; // wallet balance (an RPC call)

let lastStatus = null;
let lastWallet = null;

// --- tiny DOM helper --------------------------------------------------------
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}
const fill = (id, ...nodes) =>
  document.getElementById(id).replaceChildren(...nodes.flat().filter((n) => n !== null && n !== undefined && n !== false));
const usd = (x, digits = 2) => {
  if (x === null || x === undefined) return "—";
  const abs = Math.abs(Number(x)).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${Number(x) < 0 ? "−" : ""}$${abs}`;
};
const num = (x) => (x === null || x === undefined ? "—" : Math.round(x).toLocaleString());
const time = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
const badge = (text, kind) => el("span", { class: `badge ${kind}` }, text);

function showError(message) {
  const box = document.getElementById("error");
  box.textContent = message;
  box.hidden = !message;
}

// --- panels ------------------------------------------------------------------
function renderBadges(s) {
  fill("mode-badges",
    s.stub_mode ? badge("STUB DATA", "warn") : badge("LIVE DATA", "good"),
    " ",
    s.kill_switch ? badge("SPENDING OFF", "bad") : badge("SPENDING ON", "good"),
    s.paused_after_failures ? [" ", badge("PAUSED: FAILURES", "bad")] : null,
  );
}

function renderSpending(s, wallet) {
  const pct = s.daily_budget_usd ? Math.min(100, (100 * s.spent_today_usd) / s.daily_budget_usd) : 0;
  fill("spending-body",
    el("div", { class: "big" }, usd(s.spent_today_usd)),
    el("div", { class: "muted" }, `spent today of ${usd(s.daily_budget_usd)} daily budget`),
    el("div", { class: `meter ${pct >= 80 ? "high" : ""}` }, el("div", { style: `width:${pct}%` })),
    el("div", { class: "row" }, el("span", {}, "Remaining today"), el("span", { class: "num" }, usd(s.remaining_today_usd))),
    el("div", { class: "row" }, el("span", {}, "Wallet balance (USDC)"),
      el("span", { class: "num" }, wallet ? usd(wallet.usdc, 4) : "—")),
    el("div", { class: "row" }, el("span", {}, "Wallet"),
      s.wallet_address
        ? el("a", { href: `https://basescan.org/address/${s.wallet_address}`, target: "_blank", rel: "noopener" },
            `${s.wallet_address.slice(0, 6)}…${s.wallet_address.slice(-4)}`)
        : el("span", { class: "muted" }, "not set")),
  );
}

function renderControls(s) {
  // Stopping always works. Resuming only clears the dashboard switch; the .env lock
  // can only be cleared by editing .env by hand.
  const button = s.dashboard_stopped
    ? el("button", { onclick: () => toggle(false), disabled: s.env_lock }, "Resume spending")
    : el("button", { class: "danger", onclick: () => toggle(true) }, "Stop all spending");
  fill("controls-body",
    el("div", { class: "row" }, el("span", {}, "Kill switch (dashboard)"), s.dashboard_stopped ? badge("ON", "bad") : badge("off", "good")),
    el("div", { class: "row" }, el("span", {}, "Kill switch (.env lock)"), s.env_lock ? badge("ON", "bad") : badge("off", "good")),
    el("div", { class: "row" }, el("span", {}, "Max per call"), el("span", { class: "num" }, usd(s.max_per_call_usd))),
    el("div", { class: "row" }, el("span", {}, "Per-run budget"), el("span", { class: "num" }, usd(s.per_run_budget_usd))),
    el("div", { class: "row" }, el("span", {}, "Paused after failures"), s.paused_after_failures ? badge("yes", "bad") : badge("no", "good")),
    s.config_error ? el("div", { class: "badge bad" }, `Config: ${s.config_error}`) : null,
    s.ledger_error ? el("div", { class: "badge bad" }, `Ledger: ${s.ledger_error}`) : null,
    s.env_lock ? el("div", { class: "muted" }, "Locked in .env: set KILL_SWITCH=false there by hand to allow spending.") : null,
    button,
  );
}

function renderSignals(data) {
  if (!data.signals.length) {
    fill("signals-body", el("div", { class: "muted" },
      data.mode === "live" ? "No signals cached yet (live mode shows only what the agent already bought)." : "No signals."));
    return;
  }
  const head = el("tr", {}, ["Asset", "Tier", "Horizons", "Smart trader flow", "Whale flow", "Exchange flow",
    "SM 1h flow", "SM traders", "Cost", "Fetched"].map((h, i) => el("th", { class: i >= 3 && i <= 8 ? "num" : "" }, h)));
  const rows = data.signals.map((s) => el("tr", {},
    el("td", {}, s.asset),
    el("td", {}, s.tier === "smart_money" ? "Smart Money" : "Basic"),
    el("td", {}, (s.horizons ?? []).join(", ") || "—"),
    el("td", { class: "num" }, s.tier === "basic" ? usd(s.smart_trader_net_flow_usd, 0) : ""),
    el("td", { class: "num" }, s.tier === "basic" ? usd(s.whale_net_flow_usd, 0) : ""),
    el("td", { class: "num" }, s.tier === "basic" ? usd(s.exchange_net_flow_usd, 0) : ""),
    el("td", { class: "num" }, s.tier === "smart_money" ? usd(s.sm_net_flow_1h_usd, 0) : ""),
    el("td", { class: "num" }, s.tier === "smart_money" ? num(s.sm_trader_count) : ""),
    el("td", { class: "num" }, usd(s.cost_usd)),
    el("td", {}, time(s.fetched_at)),
  ));
  fill("signals-body",
    el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, head), el("tbody", {}, rows))),
    data.errors.length ? el("div", { class: "muted" }, `${data.errors.length} unavailable`) : null,
  );
}

function renderPayments(rows) {
  if (!rows.length) {
    fill("payments-body", el("div", { class: "muted" }, "No payments yet."));
    return;
  }
  const kind = { settled: "good", failed: "bad", pending: "warn" };
  const head = el("tr", {}, ["Time", "Tier", "Amount", "Status", "Transaction"]
    .map((h) => el("th", { class: h === "Amount" ? "num" : "" }, h)));
  const body = rows.map((p) => el("tr", {},
    el("td", {}, time(p.at)),
    el("td", {}, p.tier === "smart_money" ? "Smart Money" : p.tier === "basic" ? "Basic" : p.tier),
    el("td", { class: "num" }, usd(p.amount_usd)),
    el("td", {}, badge(p.status, kind[p.status] ?? "warn"), p.status === "failed" && p.detail ? ` ${p.detail}` : ""),
    el("td", {}, p.tx_url
      ? el("a", { href: p.tx_url, target: "_blank", rel: "noopener" }, `${p.tx_hash.slice(0, 10)}…${p.tx_hash.slice(-6)}`)
      : el("span", { class: "muted" }, "—")),
  ));
  fill("payments-body", el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, head), el("tbody", {}, body))));
}

function renderDecisions(data) {
  if (!data.rows.length) {
    fill("decisions-body", el("div", { class: "muted" }, "No decisions yet. Run a cycle (pennywise.agent.cycle or pennywise.agent.llm)."));
    return;
  }
  const tierName = (t) => (t === "smart_money" ? "Smart Money" : "Basic");
  const dataCell = (r) => {
    const i = r.info;
    const verdict = i.buy ? badge("buy", "good") : badge("skip", "warn");
    const got = i.source === "paid" ? ` paid ${usd(i.cost_usd)}` : i.source === "cached" ? " cached" : "";
    return [verdict, ` ${i.reason}${got}`,
      r.llm_override ? [" ", badge("LLM OVERRIDE", "warn")] : null,
      i.error ? [" ", badge(i.error, "bad")] : null];
  };
  const tradeCell = (r) => {
    if (!r.trades.length) return el("span", { class: "muted" }, "—");
    return r.trades.map((t) => el("div", {},
      `${t.side} ${t.contracts}× ${t.event} @ ${t.strike} for ${usd(t.price)} `,
      t.result ? badge(`${t.result} ${usd(t.pnl_usd)}`, t.result === "won" ? "good" : "bad") : badge("open", "warn"),
    ));
  };
  const head = el("tr", {}, ["Time", "Cycle", "Asset", "Tier", "By", "Data decision", "Value / price", "Reading", "Contracts", "Trades"]
    .map((h) => el("th", { class: ["Cycle", "Value / price", "Reading", "Contracts"].includes(h) ? "num" : "" }, h)));
  const body = data.rows.map((r) => el("tr", {},
    el("td", {}, time(r.at), r.stub ? [" ", badge("stub", "warn")] : null),
    el("td", { class: "num" }, r.cycle),
    el("td", {}, r.asset),
    el("td", {}, tierName(r.tier)),
    el("td", {}, r.decided_by === "llm" ? badge("LLM", "good") : "rule"),
    el("td", {}, dataCell(r)),
    el("td", { class: "num" }, `${usd(r.info.value_usd, 3)} / ${usd(r.info.price_usd)}`),
    el("td", { class: "num" }, r.info.reading === null ? "—" : r.info.reading.toFixed(2)),
    el("td", { class: "num" }, r.quotes.length),
    el("td", {}, tradeCell(r)),
  ));
  fill("decisions-body",
    el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, head), el("tbody", {}, body))),
    data.skipped ? el("div", { class: "muted" }, `${data.skipped} log lines could not be read`) : null,
  );
}

// --- actions -----------------------------------------------------------------
async function toggle(on) {
  if (!on && !confirm("Resume spending real USDC on Nansen data?")) return;
  try {
    lastStatus = await setKillSwitch(on, !on);
    renderAll();
    showError("");
  } catch (e) {
    showError(`Kill switch: ${e.message}`);
  }
}

// --- refresh loop ------------------------------------------------------------
function renderAll() {
  if (!lastStatus) return;
  renderBadges(lastStatus);
  renderSpending(lastStatus, lastWallet);
  renderControls(lastStatus);
}

async function refreshFast() {
  const [status, payments, signals, decisions] = await Promise.allSettled(
    [getStatus(), getPayments(), getSignals(), getDecisions()]);
  if (status.status === "fulfilled") lastStatus = status.value;
  renderAll();
  if (payments.status === "fulfilled") renderPayments(payments.value);
  if (signals.status === "fulfilled") renderSignals(signals.value);
  if (decisions.status === "fulfilled") renderDecisions(decisions.value);
  const failed = [status, payments, signals, decisions].filter((r) => r.status === "rejected");
  showError(failed.length ? `Can't reach the API: ${failed[0].reason.message}` : "");
  document.getElementById("updated").textContent = `Updated ${new Date().toLocaleTimeString()}`;
}

async function refreshWallet() {
  try {
    lastWallet = await getWallet();
  } catch {
    lastWallet = null; // RPC hiccup: show "—" rather than an error banner
  }
  renderAll();
}

refreshFast();
refreshWallet();
setInterval(refreshFast, FAST_MS);
setInterval(refreshWallet, SLOW_MS);
