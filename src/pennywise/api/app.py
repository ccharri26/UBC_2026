"""Thin HTTP layer for the dashboard. The agent itself never needs this to run.

Run (from the repo root):
    uv run uvicorn pennywise.api.app:app
(Add --reload only for backend work: a reload restarts the server and ends any Run.)
Then open http://127.0.0.1:8000/docs to try every endpoint.

Rules:
- GET endpoints never spend money. /api/signals only buys in stub mode (free);
  in live mode it shows what is already cached.
- Never return the private key. Only the wallet address leaves this process.
- Turning spending back ON needs {"confirm": true}; turning it OFF never does.
- Raising the Approval Threshold needs {"confirm": true}; lowering it never does.
- The Run button starts the agent inside this process (agent/runner.py). A Run that would
  spend real USDC (NANSEN_STUB=false in .env) needs {"live": true}; the dashboard can't
  switch stub mode. A Run's budget can be lowered, never raised above BUDGET_PER_RUN_USD.
- Every POST accepts application/json only (see _json_only).
- Never writes .env. The kill switch lives in data/control.json (payments/control.py);
  KILL_SWITCH=true in .env is a hand-set lock the dashboard can't override.
- A background Settler (scoring/settle.py) records settled Events every SETTLE_EVERY
  seconds while the server runs, Run or no Run. It spends nothing.
"""

from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pennywise.agent.runner import MAX_EVERY, MIN_EVERY, Runner, RunnerBusy
from pennywise.decisions import read_decisions, read_outcomes
from pennywise.nansen import (
    Horizon,
    NansenSignals,
    Tier,
    cached_signals,
    horizons_for,
    stub_mode,
    supported_assets,
    tier_for_url,
    tier_of,
    tier_price,
)
from pennywise.nansen.stub import stub_signals
from pennywise.payments import approval, control, expected, guardrails, wallet
from pennywise.payments.config import DATA_DIR, ROOT, ConfigError, env, load_limits, usd_to_units
from pennywise.scoring.score import score, trade_pnl
from pennywise.scoring.settle import Settler

_settler = Settler()


@asynccontextmanager
async def _lifespan(_: FastAPI):
    _settler.start()
    yield
    _settler.stop()


app = FastAPI(
    title="PennyWise",
    description="Read-only views of payments and Nansen signals, plus a kill switch.",
    lifespan=_lifespan,
)

_BASESCAN_TX = "https://basescan.org/tx/"


def _usd(units: int) -> float:
    return round(units / 1_000_000, 6)


def _signals_dict(s: NansenSignals) -> dict:
    d = asdict(s)
    d["tier"] = s.tier.value
    d["fetched_at"] = s.fetched_at.isoformat()
    d["cost_usd"] = _usd(s.cost_usdc)
    d["horizons"] = [h.value for h in horizons_for(s.tier)]  # 5M and 15M share Basic
    return d


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/status")
def status() -> dict:
    """Guardrail state: kill switch, stub mode, budgets and today's spend."""
    now = datetime.now(timezone.utc)
    try:
        limits = load_limits()
        config_error = None
    except ConfigError as e:
        limits, config_error = None, str(e)
    spent = guardrails.spent_today(now)
    env_lock = (env("KILL_SWITCH") or "true").lower() != "false"  # same rule as payments
    dashboard_stopped = control.dashboard_stopped()
    return {
        "kill_switch": env_lock or dashboard_stopped,  # effective: true = no spending
        "env_lock": env_lock,  # KILL_SWITCH in .env; only a hand edit clears it
        "dashboard_stopped": dashboard_stopped,  # data/control.json
        "stub_mode": stub_mode(),
        "paused_after_failures": guardrails.paused(),
        "wallet_address": env("WALLET_ADDRESS"),
        "spent_today_usd": _usd(spent),
        "daily_budget_usd": _usd(limits.daily) if limits else None,
        "remaining_today_usd": _usd(max(limits.daily - spent, 0)) if limits else None,
        "per_run_budget_usd": _usd(limits.per_run) if limits else None,
        "per_market_budget_usd": _usd(limits.per_market) if limits else None,  # per (asset, tier) per UTC day
        "max_per_call_usd": _usd(expected.MAX_PRICE_PER_CALL),
        "config_error": config_error,
        "ledger_error": guardrails.ledger_error(),  # bad data/payments.jsonl: spending blocked
    }


@app.get("/api/wallet")
def wallet_balance() -> dict:
    """USDC balance on Base (a free RPC read)."""
    address = env("WALLET_ADDRESS")
    if not address:
        raise HTTPException(404, "WALLET_ADDRESS is not set")
    try:
        units = wallet.usdc_balance(address)
    except Exception as e:  # RPC down or rate-limited: show it, don't crash the dashboard
        raise HTTPException(502, f"could not read balance: {type(e).__name__}") from None
    return {"address": address, "usdc": _usd(units)}


@app.get("/api/payments")
def payments(limit: int = 50) -> list[dict]:
    """Payment history, newest first."""
    rows = guardrails.history()[::-1][: max(limit, 0)]
    return [
        {
            "at": r.get("at"),
            "status": r["status"],
            "tier": tier.value if (tier := tier_for_url(r.get("url"))) else "unknown",
            "amount_usd": _usd(r.get("amount", 0)),
            "market": r.get("market"),  # e.g. "ETH-smart_money"; None on rows from before markets
            "tx_hash": r.get("tx_hash"),
            "tx_url": _BASESCAN_TX + r["tx_hash"] if r.get("tx_hash") else None,
            "detail": r.get("detail"),
        }
        for r in rows
    ]


@app.get("/api/signals")
def signals() -> dict:
    """Latest Nansen signals per asset and Horizon.

    Stub mode: made fresh (fake, free, no approval). Live mode: what the agent already bought
    (data/nansen_cache.json); this endpoint never pays.
    """
    if not stub_mode():
        live = sorted(cached_signals(), key=lambda s: (s.asset, s.tier.value))
        return {"mode": "live", "signals": [_signals_dict(s) for s in live], "errors": []}
    # Fake data straight from the stub, never get_signals(): that path asks a human for
    # approval, and a dashboard poll must never create an Approval Request.
    now = datetime.now(timezone.utc)
    out, errors = [], []
    for asset in supported_assets():
        for tier in dict.fromkeys(tier_of(h) for h in Horizon):  # 5M and 15M share Basic
            out.append(_signals_dict(stub_signals(asset, tier, now)))
    return {"mode": "stub", "signals": out, "errors": errors}


@app.get("/api/decisions")
def decisions(limit: int = 50) -> dict:
    """Decision log (data/decisions.jsonl), newest first: one row per (asset, tier) per cycle.

    Each trade gets `result` ("won", "lost", or null until its Event settles) and `pnl_usd`.
    `llm_override` is true when the LLM bought data the value check said to skip.
    `skipped` counts log lines that failed to load.
    """
    loaded = read_decisions(limit=max(limit, 0))
    outcomes = {o.event: o for o in read_outcomes().rows}
    out = []
    for row in reversed(loaded.rows):
        d = row.to_dict()
        d["llm_override"] = row.decided_by == "llm" and not row.info.buy and row.info.source != "none"
        for t, td in zip(row.trades, d["trades"]):
            o = outcomes.get(t.event)
            yes = o.result_for(t.strike) if o else None
            if yes is None:
                td["result"], td["pnl_usd"] = None, None
            else:
                td["result"] = "won" if (t.side == "YES") == yes else "lost"
                td["pnl_usd"] = round(trade_pnl(t, yes), 4)
        out.append(d)
    return {"rows": out, "skipped": loaded.skipped}


@app.get("/api/score")
def score_report(include_stub: bool | None = None) -> dict:
    """Scoring report from the decision log and data/outcomes.jsonl (see scoring/score.py).

    Profit is `net_pnl_usd`: settled shadow-trade P&L minus Nansen spend. Groups: overall,
    by_decided_by, by_tier, by_asset. `include_stub` defaults to the current NANSEN_STUB, so a
    stub run scores its own rows (their Nansen readings are fake, so informed numbers and
    trades on paid-data assets mean nothing). Reads local files only; the Settler settles Events.
    """
    return score(include_stub=stub_mode() if include_stub is None else include_stub)


@app.get("/api/settle")
def settle_status() -> dict:
    """The background Settler: when it last settled, what it found, when it runs next."""
    return _settler.status()


@app.post("/api/settle")
def settle_now(request: Request) -> dict:
    """Settle now (free Gemini lookups, no spending). Waits for a settle already in progress."""
    _json_only(request)
    return _settler.run_now()


class KillSwitch(BaseModel):
    on: bool  # true = stop all spending
    confirm: bool = False  # required to turn spending back on


def _json_only(request: Request) -> None:
    # A plain HTML form on another site can't send application/json without a CORS
    # preflight, which this server never approves. Blocks drive-by POSTs.
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "send application/json")


@app.post("/api/kill-switch")
def kill_switch(body: KillSwitch, request: Request) -> dict:
    _json_only(request)
    if not body.on:
        if not body.confirm:
            raise HTTPException(400, 'turning spending back on needs {"on": false, "confirm": true}')
        if (env("KILL_SWITCH") or "true").lower() != "false":
            raise HTTPException(409, "locked by KILL_SWITCH in .env; set KILL_SWITCH=false there by hand to allow spending")
    control.set_spending(on=not body.on)
    return status()


def _approval_settings() -> dict:
    return {
        "threshold_usd": _usd(approval.threshold()),
        "ceiling_usd": _usd(approval.ceiling()),
        "ceiling_problem": approval.ceiling_problem(),
        "wait_seconds": approval.WAIT_SECONDS,
        "prices_usd": {t.value: _usd(tier_price(t)) for t in Tier},
    }


@app.get("/api/approval/settings")
def approval_settings() -> dict:
    """The Approval Threshold: purchases at or above it wait for a human."""
    return _approval_settings()


class ApprovalSettings(BaseModel):
    threshold_usd: float
    confirm: bool = False  # required to raise the threshold


@app.post("/api/approval/settings")
def set_approval_settings(body: ApprovalSettings, request: Request) -> dict:
    _json_only(request)
    try:
        approval.set_threshold(usd_to_units(str(body.threshold_usd)), body.confirm)
    except approval.ApprovalError as e:
        raise HTTPException(409, str(e)) from None
    return _approval_settings()


@app.get("/api/approval/requests")
def approval_requests() -> list[dict]:
    """Approval Requests waiting for an answer, oldest first."""
    return [
        {
            "id": r["id"],
            "market": r["market"],
            "amount_usd": _usd(r["amount"]),
            "stub": bool(r.get("stub")),
            "created_at": r["created_at"],
            "expires_at": r["expires_at"],
        }
        for r in approval.pending()
    ]


class ApprovalAnswer(BaseModel):
    approve: bool


@app.post("/api/approval/requests/{request_id}")
def answer_approval(request_id: str, body: ApprovalAnswer, request: Request) -> dict:
    _json_only(request)
    try:
        return {"id": request_id, "answer": approval.answer(request_id, body.approve)}
    except approval.ApprovalError as e:
        raise HTTPException(409, str(e)) from None


# --- Run button ----------------------------------------------------------------------

_runner = Runner(state_file=DATA_DIR / "runner.json")
MAX_CYCLES = 1000


def _runner_status() -> dict:
    s = _runner.status()
    try:
        limits = load_limits()
        cap, budget = limits.per_run, guardrails.run_budget(limits)
    except ConfigError:
        cap = budget = None
    return {
        **s,
        "once": s["max_cycles"] == 1,
        "kill_switch": control.kill_switch_on(),
        "run_spent_usd": _usd(guardrails.run_spent()),
        "run_budget_usd": _usd(budget) if budget is not None else None,
        "per_run_cap_usd": _usd(cap) if cap is not None else None,  # BUDGET_PER_RUN_USD in .env
        "min_every_seconds": MIN_EVERY,
        "max_every_seconds": MAX_EVERY,
    }


@app.get("/api/runner")
def runner_status() -> dict:
    """The agent's current or last Run: mode, Cycles done, next Cycle, why it stopped."""
    return _runner_status()


class RunStart(BaseModel):
    mode: Literal["rule", "llm"] = "rule"
    once: bool = False  # one Cycle, then stop
    every_seconds: int = 120  # clamped to [MIN_EVERY, MAX_EVERY]
    max_cycles: int | None = 30  # ignored when once
    budget_usd: float | None = None  # this Run's budget; None = BUDGET_PER_RUN_USD
    live: bool = False  # required when NANSEN_STUB is off: the Run may spend real USDC


@app.post("/api/runner/start")
def start_run(body: RunStart, request: Request) -> dict:
    _json_only(request)
    if control.kill_switch_on():
        raise HTTPException(409, "the kill switch is on; turn it off first")
    stub = stub_mode()
    if not stub and not body.live:
        raise HTTPException(409, 'NANSEN_STUB is off in .env, so this Run would spend real USDC; send {"live": true}')
    if not body.once and body.max_cycles is not None and not 1 <= body.max_cycles <= MAX_CYCLES:
        raise HTTPException(400, f"max_cycles must be from 1 to {MAX_CYCLES}")
    try:
        limits = load_limits()
    except ConfigError as e:
        raise HTTPException(409, str(e)) from None
    budget = None
    if body.budget_usd is not None:
        try:
            budget = usd_to_units(str(body.budget_usd))
        except ValueError:
            raise HTTPException(400, "budget_usd is not a dollar amount") from None
        if not 0 <= budget <= limits.per_run:
            raise HTTPException(409, f"a Run's budget must be from $0 to ${_usd(limits.per_run)} (BUDGET_PER_RUN_USD in .env)")
    try:
        _runner.start(
            MIN_EVERY if body.once else body.every_seconds,
            mode=body.mode,
            max_cycles=1 if body.once else body.max_cycles,
            allow_live=body.live and not stub,  # if .env flips to live mid-Run, a stub Run refuses its Cycles
            budget=budget,
        )
    except RunnerBusy as e:
        raise HTTPException(409, str(e)) from None
    return _runner_status()


@app.post("/api/runner/stop")
def stop_run(request: Request) -> dict:
    """Stop after the current Cycle. Its open Approval Requests are denied; the kill switch is untouched."""
    _json_only(request)
    _runner.stop()
    return _runner_status()


# The dashboard is a React app in frontend/; `npm run build` there writes frontend/dist,
# which is served at /. Mounted last so /api wins. Without a build, / explains how to make one.
_DIST = ROOT / "frontend" / "dist"
if (_DIST / "index.html").exists():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
else:

    @app.get("/", include_in_schema=False)
    def dashboard_not_built() -> HTMLResponse:
        return HTMLResponse(
            "<!doctype html><title>PennyWise</title><body style='font-family:system-ui;padding:40px'>"
            "<h1>Dashboard not built</h1><p>Run <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>, "
            "then restart uvicorn. For development use <code>npm run dev</code> (http://localhost:5173).</p>"
            "<p>API docs: <a href='/docs'>/docs</a></p></body>"
        )
