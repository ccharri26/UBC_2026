"""The tools the LLM agent calls: thin wrappers over the deterministic cycle's steps.

One CycleState holds a single agent cycle (one Gemini snapshot). The LLM looks
(scan_markets), asks (estimate_data_value, wallet_status), maybe buys
(buy_nansen_data) and maybe bets (propose_trade). Code keeps every decision that
touches money:
  - purchases go through fetch_reading() -> get_signals() -> pay() and every guardrail;
  - trade size comes from pick_trades(), never from the LLM;
  - one trade per Event, and only on a side with edge above MIN_EDGE.
finish() then writes the decision log exactly like run_cycle().

Every tool returns a small JSON-safe dict of numbers and fixed labels, and never raises:
problems come back as {"error": "..."} so the LLM can adjust.

When the LLM buys data that decide() said to skip, the logged row shows it:
info.buy is False but info.source is "paid" or "cached".

`uv run python -m pennywise.agent.tools` drives the tools by hand (stub mode only).
"""

import sys
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from functools import wraps

from pennywise.agent.cycle import (
    NO_DATA,
    NansenResult,
    build_row,
    fetch_reading,
    forecast_quotes,
    last_rows,
)
from pennywise.decisions import (
    DecisionRow,
    QuoteRecord,
    RecordError,
    TradeRecord,
    append_decision,
    traded_events,
    worth_logging,
)
from pennywise.info.value import InfoDecision, decide
from pennywise.markets.gemini import MarketSnapshot, fetch_snapshot
from pennywise.nansen import Tier, stub_mode
from pennywise.payments import control, guardrails
from pennywise.payments.config import ConfigError, load_limits
from pennywise.trading.edge import MIN_EDGE
from pennywise.trading.shadow import pick_trades

# MVP: the LLM may buy Nansen data for ETH only (SOL is untested on both tiers).
LLM_BUY_ASSETS = frozenset({"ETH"})
# decide() reasons where buying anyway can't help, so the LLM may not override them.
NO_OVERRIDE = frozenset({"no nansen coverage", "no two-sided contracts", "already paid this slot, no usable data"})
# Contracts shown per Event in scan_markets (best edge first), to keep the LLM's input small.
CONTRACTS_PER_EVENT = 5

Group = tuple[str, Tier]


class ToolError(Exception):
    """A bad request from the LLM. The message goes back to it as {"error": ...}."""


@dataclass
class CycleState:
    """Everything for one agent cycle. Tools read and update it; finish() logs it."""

    snap: MarketSnapshot
    cycle: int
    stub: bool
    traded: set[str]  # Events traded in earlier cycles or this one: never traded again
    previous: dict[tuple[str, str], DecisionRow]  # newest logged row per (asset, tier name)
    decisions: dict[Group, InfoDecision]  # decide() per group, computed once at the start
    results: dict[Group, NansenResult] = field(default_factory=dict)
    trades: dict[Group, list[TradeRecord]] = field(default_factory=dict)


def start_cycle() -> CycleState:
    """Fetch the free Gemini snapshot and run decide() on every group. Spends nothing."""
    snap = fetch_snapshot()
    stub = stub_mode()
    last_cycle, previous = last_rows()
    decisions = {
        (asset, tier): decide(asset, tier, quotes, snap.spots[asset], snap.vols[asset])
        for (asset, tier), quotes in snap.groups.items()
    }
    return CycleState(
        snap=snap,
        cycle=last_cycle + 1,
        stub=stub,
        traded=traded_events(include_stub=stub),
        previous=previous,
        decisions=decisions,
    )


# --- helpers -----------------------------------------------------------------------


def _tool(fn):
    """Turn ToolError and unexpected exceptions into {"error": ...} for the LLM."""

    @wraps(fn)
    def wrapper(*args, **kwargs) -> dict:
        try:
            return fn(*args, **kwargs)
        except ToolError as e:
            return {"error": str(e)}
        except Exception as e:  # never crash the loop; the type name is a fixed label
            return {"error": f"internal error ({type(e).__name__})"}

    return wrapper


def _group(state: CycleState, asset: str, tier: str) -> Group:
    try:
        key = (asset.upper(), Tier(tier))
    except ValueError:
        raise ToolError(f"unknown tier {tier!r}; use one of {[t.value for t in Tier]}") from None
    if key not in state.decisions:
        raise ToolError(f"no {key[0]} {tier} markets this cycle")
    return key


def _quotes(state: CycleState, key: Group) -> list[QuoteRecord]:
    """Forecasts and edges for a group, using its reading so far (None = baseline)."""
    asset, tier = key
    reading = state.results.get(key, NO_DATA).reading
    return forecast_quotes(state.snap.groups[key], state.snap.spots[asset], state.snap.vols[asset], tier, reading)


def _r(x: float | None, digits: int = 4) -> float | None:
    return None if x is None else round(x, digits)


# --- tools -------------------------------------------------------------------------


@_tool
def scan_markets(state: CycleState) -> dict:
    """Open markets per (asset, tier) with baseline (or informed) odds and edges. Free."""
    groups = []
    for key, quotes in state.snap.groups.items():
        asset, tier = key
        result = state.results.get(key, NO_DATA)
        events: dict[str, list[QuoteRecord]] = {}
        for q in _quotes(state, key):
            events.setdefault(q.event, []).append(q)
        best = lambda q: max(q.yes_edge or -1.0, q.no_edge or -1.0)  # noqa: E731
        groups.append({
            "asset": asset,
            "tier": tier.value,
            "spot": _r(state.snap.spots[asset], 2),
            "minute_vol": _r(state.snap.vols[asset], 6),
            "nansen_reading": _r(result.reading, 3),  # None = no data yet, forecasts are baseline
            "events": [
                {
                    "event": event,
                    "mins_left": _r(qs[0].mins_left, 1),
                    "already_traded": event in state.traded,
                    "contracts_total": len(qs),
                    "contracts": [
                        {
                            "strike": q.strike,
                            "bid": q.bid,
                            "ask": q.ask,
                            "prob": _r(q.informed if q.informed is not None else q.baseline),
                            "yes_edge": _r(q.yes_edge),
                            "no_edge": _r(q.no_edge),
                            "call": q.call,
                        }
                        for q in sorted(qs, key=best, reverse=True)[:CONTRACTS_PER_EVENT]
                    ],
                }
                for event, qs in events.items()
            ],
        })
    return {"at": state.snap.at.isoformat(), "min_edge": MIN_EDGE, "stub": state.stub, "groups": groups}


@_tool
def estimate_data_value(state: CycleState, asset: str, tier: str) -> dict:
    """The value-of-information check for one (asset, tier). Advice only."""
    d = state.decisions[_group(state, asset, tier)]
    return {
        "asset": d.asset,
        "tier": d.tier.value,
        "value_usd": _r(d.value_usd),
        "price_usd": _r(d.price_usd),
        "recommend_buy": d.buy,
        "reason": d.reason,
        "already_cached": d.from_cache,
        "llm_may_buy": d.asset in LLM_BUY_ASSETS and d.reason not in NO_OVERRIDE,
    }


@_tool
def buy_nansen_data(state: CycleState, asset: str, tier: str) -> dict:
    """Buy (or read cached) Nansen data for one (asset, tier). Guardrails have the final say."""
    key = _group(state, asset, tier)
    if key[0] not in LLM_BUY_ASSETS:
        raise ToolError(f"buying is limited to {sorted(LLM_BUY_ASSETS)} for now")
    if key in state.results and state.results[key].source != "none":
        prior = state.results[key]
        return {"source": prior.source, "reading": _r(prior.reading, 3), "cost_usd": 0.0, "note": "already have data this cycle"}
    if state.trades.get(key):
        raise ToolError("already traded this group on the baseline this cycle; buy data before trading")
    d = state.decisions[key]
    if not d.buy:
        if d.reason in NO_OVERRIDE:
            raise ToolError(f"can't buy: {d.reason}")
        d = replace(d, buy=True)  # the LLM overrides the value check; the log shows it (buy=False, source=paid)
    n = fetch_reading(key[0], key[1], d)
    state.results[key] = n
    return {
        "source": n.source,
        "reading": _r(n.reading, 3),
        "cost_usd": _r(n.cost_usd),
        "error": n.error,
        "money_spent_despite_error": n.spent,
        "overrode_value_check": not state.decisions[key].buy,
    }


@_tool
def propose_trade(state: CycleState, event: str, side: str) -> dict:
    """Propose a shadow trade on one Event. Code checks the edge and picks contract and size."""
    side = side.upper()
    if side not in ("YES", "NO"):
        raise ToolError("side must be YES or NO")
    if event in state.traded:
        raise ToolError(f"{event} was already traded; one trade per Event")
    key = next((k for k, qs in state.snap.groups.items() if any(q.event == event for q in qs)), None)
    if key is None:
        raise ToolError(f"unknown event {event!r}; use a ticker from scan_markets")
    wanted = [q for q in _quotes(state, key) if q.event == event and q.call == f"BUY {side}"]
    trades = pick_trades(wanted, state.traded)
    if not trades:
        return {"accepted": False, "reason": f"no contract in {event} has {side} edge above {MIN_EDGE}"}
    t = trades[0]
    state.trades.setdefault(key, []).append(t)
    state.traded.add(t.event)
    return {
        "accepted": True,
        "event": t.event,
        "strike": t.strike,
        "side": t.side,
        "contracts": t.contracts,
        "price": t.price,
        "fee_usd": _r(t.fee_usd),
        "edge_per_contract": _r(t.edge),
        "mode": t.mode,
    }


@_tool
def wallet_status(state: CycleState) -> dict:
    """Spend so far today, budgets, and whether spending is blocked. Read-only."""
    now = datetime.now(timezone.utc)
    spent = guardrails.spent_today(now) / 1_000_000
    try:
        limits = load_limits()
    except ConfigError as e:
        return {"spent_today_usd": _r(spent), "spending_allowed": False, "blocked_by": f"config: {e}"}
    blocked = [
        label for label, on in (
            ("kill switch", limits.kill_switch),
            ("dashboard stop", control.dashboard_stopped()),
            ("paused after failures", guardrails.paused()),
            ("ledger problem", guardrails.ledger_error() is not None),
        ) if on
    ]
    return {
        "stub_mode": state.stub,
        "spent_today_usd": _r(spent),
        "daily_budget_usd": _r(limits.daily / 1_000_000),
        "daily_left_usd": _r(max(0.0, limits.daily / 1_000_000 - spent)),
        "per_run_budget_usd": _r(limits.per_run / 1_000_000),
        "per_market_budget_usd": _r(limits.per_market / 1_000_000),
        "spending_allowed": not blocked,
        "blocked_by": blocked,
    }


def finish(state: CycleState, decided_by: str = "llm") -> dict:
    """Write the decision log for this cycle, like run_cycle(). Not an LLM tool.

    Rows are labelled `decided_by` ("llm" for the Grok loop) so scoring can compare it with the rule cycle.
    """
    logged, trades = 0, 0
    for key, d in state.decisions.items():
        asset, tier = key
        n = state.results.get(key, NO_DATA)
        group_trades = state.trades.get(key, [])
        try:
            row = build_row(
                state.snap, state.cycle, state.stub, asset, tier, d, n, _quotes(state, key), group_trades, decided_by
            )
        except RecordError as e:
            print(f"  could not log {asset} {tier.value}: {e}")
            continue
        if worth_logging(row, state.previous.get((asset, tier.value))):
            append_decision(row)
            logged += 1
        trades += len(group_trades)
    return {"cycle": state.cycle, "groups": len(state.decisions), "logged": logged, "trades": trades}


TOOLS = {
    "scan_markets": scan_markets,
    "estimate_data_value": estimate_data_value,
    "buy_nansen_data": buy_nansen_data,
    "propose_trade": propose_trade,
    "wallet_status": wallet_status,
}


if __name__ == "__main__":
    # Drive the tools by hand, like the LLM would. Stub mode only; --log also writes decisions.jsonl.
    import json

    if not stub_mode():
        sys.exit("Set NANSEN_STUB=true first: this demo must not spend real money.")
    show = lambda name, out: print(f"\n{name}\n{json.dumps(out, indent=2)[:1500]}")  # noqa: E731
    state = start_cycle()
    scan = scan_markets(state)
    show("scan_markets", scan)
    show("wallet_status", wallet_status(state))
    for key in state.decisions:
        show(f"estimate_data_value {key[0]} {key[1].value}", estimate_data_value(state, key[0], key[1].value))
    eth = [k for k in state.decisions if k[0] == "ETH"]
    if eth:
        show(f"buy_nansen_data ETH {eth[0][1].value}", buy_nansen_data(state, "ETH", eth[0][1].value))
    show("buy_nansen_data BTC basic (should refuse)", buy_nansen_data(state, "BTC", "basic"))
    for g in scan.get("groups", []):
        for e in g["events"]:
            for c in e["contracts"]:
                if c["call"] != "pass" and not e["already_traded"]:
                    side = c["call"].split()[1]
                    show(f"propose_trade {e['event']} {side}", propose_trade(state, e["event"], side))
                    show("propose_trade again (should refuse)", propose_trade(state, e["event"], side))
                    break
            else:
                continue
            break
    if "--log" in sys.argv:
        show("finish", finish(state))
