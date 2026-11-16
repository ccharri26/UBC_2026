"""Thin HTTP layer for the dashboard. The agent itself never needs this to run.

Run (from the repo root):
    uv run uvicorn pennywise.api.app:app --reload
Then open http://127.0.0.1:8000/docs to try every endpoint.

Rules:
- GET endpoints never spend money. /api/signals only buys in stub mode (free);
  in live mode it shows what is already cached.
- Never return the private key. Only the wallet address leaves this process.
- Turning spending back ON needs {"confirm": true}; turning it OFF never does.
- Never writes .env. The kill switch lives in data/control.json (payments/control.py);
  KILL_SWITCH=true in .env is a hand-set lock the dashboard can't override.
"""

from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pennywise.nansen import (
    Horizon,
    NansenSignals,
    NansenUnavailable,
    cached_signals,
    get_signals,
    horizons_for,
    stub_mode,
    supported_assets,
    tier_for_url,
)
from pennywise.payments import control, expected, guardrails, wallet
from pennywise.payments.config import ROOT, ConfigError, env, load_limits

app = FastAPI(title="PennyWise", description="Read-only views of payments and Nansen signals, plus a kill switch.")

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

    Stub mode: fetched fresh (fake, free). Live mode: what the agent already bought
    (data/nansen_cache.json); this endpoint never pays.
    """
    if not stub_mode():
        live = sorted(cached_signals(), key=lambda s: (s.asset, s.tier.value))
        return {"mode": "live", "signals": [_signals_dict(s) for s in live], "errors": []}
    out, errors, seen = [], [], set()
    for asset in supported_assets():
        for horizon in Horizon:
            try:
                s = get_signals(asset, horizon)
            except NansenUnavailable as e:
                errors.append({"asset": asset, "horizon": horizon.value, "error": str(e)})
                continue
            if id(s) not in seen:  # 5M and 15M share one result
                seen.add(id(s))
                out.append(_signals_dict(s))
    return {"mode": "stub", "signals": out, "errors": errors}


class KillSwitch(BaseModel):
    on: bool  # true = stop all spending
    confirm: bool = False  # required to turn spending back on


@app.post("/api/kill-switch")
def kill_switch(body: KillSwitch, request: Request) -> dict:
    # JSON only: a plain HTML form on another site can't send application/json without
    # a CORS preflight, which this server never approves. Blocks drive-by toggles.
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "send application/json")
    if not body.on:
        if not body.confirm:
            raise HTTPException(400, 'turning spending back on needs {"on": false, "confirm": true}')
        if (env("KILL_SWITCH") or "true").lower() != "false":
            raise HTTPException(409, "locked by KILL_SWITCH in .env; set KILL_SWITCH=false there by hand to allow spending")
    control.set_spending(on=not body.on)
    return status()


# The dashboard (frontend/) is served at / once it exists. Mounted last so /api wins.
_FRONTEND = ROOT / "frontend"
if (_FRONTEND / "index.html").exists():
    app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="frontend")
