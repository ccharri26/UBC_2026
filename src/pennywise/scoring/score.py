"""Score the decision log against settled outcomes: forecasts, shadow trades, and data spend.

Joins data/decisions.jsonl to data/outcomes.jsonl (written by settle.py) on (Event, strike).
Everything is counted per Event, because Contracts in one Event share an outcome.

Which forecast represents an Event (it can appear in many cycles):
  - if we traded it, the row (cycle) that made the trade;
  - otherwise the last logged row that quoted it.

Forecast accuracy uses the Brier score, (probability - result)^2 with result 1 for Yes
and 0 for No: 0 is perfect, 0.25 is a coin flip, lower is better. Per Event it is the
average over that Event's Contracts; the report averages over Events. Three forecasts
are compared: baseline (free), informed (with Nansen data, only where we had a reading)
and market (bid/ask midpoint). Informed is compared with baseline on the same Events.

Stub rows (fake Nansen readings) are left out unless include_stub=True.

Run: uv run python -m pennywise.scoring.score [--include-stub]
"""

import sys
from collections import defaultdict
from dataclasses import dataclass

from pennywise.decisions import DecisionRow, OutcomeRow, QuoteRecord, TradeRecord, read_decisions, read_outcomes


@dataclass(frozen=True)
class EventScore:
    event: str
    asset: str
    tier: str
    decided_by: str
    brier_baseline: float
    brier_market: float
    brier_informed: float | None  # None if no Nansen reading was used for this Event
    trade: TradeRecord | None
    pnl_usd: float | None  # None if no trade


def decided_by(row: DecisionRow) -> str:
    """Who made the row's decisions: "rule" or "llm" (rows predating the field load as "rule")."""
    return row.decided_by


def brier(prob: float, yes: bool) -> float:
    return (prob - (1.0 if yes else 0.0)) ** 2


def trade_pnl(t: TradeRecord, yes: bool) -> float:
    """Profit after fees: each contract pays $1 if its side wins, and costs `price`."""
    won = (t.side == "YES") == yes
    return t.contracts * ((1.0 if won else 0.0) - t.price) - t.fee_usd


def pick_rows(rows: list[DecisionRow]) -> dict[str, DecisionRow]:
    """The row that represents each Event: the one that traded it, else the last that quoted it."""
    chosen: dict[str, DecisionRow] = {}
    traded: set[str] = set()
    for row in rows:  # oldest first, so later rows overwrite earlier ones
        for t in row.trades:
            chosen[t.event] = row
            traded.add(t.event)
        for q in row.quotes:
            if q.event not in traded:
                chosen[q.event] = row
    return chosen


def score_event(event: str, row: DecisionRow, outcome: OutcomeRow) -> EventScore | None:
    """Score one Event from its chosen row, or None if no quote matches a settled strike."""
    scored: list[tuple[QuoteRecord, bool]] = []
    for q in row.quotes:
        if q.event == event:
            yes = outcome.result_for(q.strike)
            if yes is not None:
                scored.append((q, yes))
    if not scored:
        return None
    mean = lambda xs: sum(xs) / len(xs)  # noqa: E731
    informed = [brier(q.informed, y) for q, y in scored if q.informed is not None]
    trade = next((t for t in row.trades if t.event == event), None)
    trade_yes = outcome.result_for(trade.strike) if trade else None
    return EventScore(
        event=event,
        asset=row.asset,
        tier=row.tier,
        decided_by=decided_by(row),
        brier_baseline=mean([brier(q.baseline, y) for q, y in scored]),
        brier_market=mean([brier((q.bid + q.ask) / 2, y) for q, y in scored]),
        brier_informed=mean(informed) if len(informed) == len(scored) else None,
        trade=trade,
        pnl_usd=trade_pnl(trade, trade_yes) if trade and trade_yes is not None else None,
    )


def summarize(scores: list[EventScore], data_cost_usd: float) -> dict:
    """Totals for one group of Events. Numbers and counts only."""
    def avg(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 4) if xs else None

    with_data = [s for s in scores if s.brier_informed is not None]
    trades = [s for s in scores if s.pnl_usd is not None]
    pnl = sum(s.pnl_usd for s in trades)
    staked = sum(s.trade.contracts * s.trade.price + s.trade.fee_usd for s in trades)
    return {
        "events": len(scores),
        "brier_baseline": avg([s.brier_baseline for s in scores]),
        "brier_market": avg([s.brier_market for s in scores]),
        "events_with_data": len(with_data),
        "brier_informed": avg([s.brier_informed for s in with_data]),
        "brier_baseline_same_events": avg([s.brier_baseline for s in with_data]),
        "trades": len(trades),
        "trades_won": sum(1 for s in trades if s.pnl_usd > 0),
        "pnl_usd": round(pnl, 4),
        "staked_usd": round(staked, 4),
        "return_on_stake": round(pnl / staked, 4) if staked else None,
        "pnl_with_data_usd": round(sum(s.pnl_usd for s in trades if s.brier_informed is not None), 4),
        "data_cost_usd": round(data_cost_usd, 4),
    }


def score(include_stub: bool = False) -> dict:
    """The full report: overall, by who decided, and by tier."""
    rows = [r for r in read_decisions().rows if include_stub or not r.stub]
    outcomes = {o.event: o for o in read_outcomes().rows}
    scores = [
        s for event, row in pick_rows(rows).items()
        if event in outcomes and (s := score_event(event, row, outcomes[event])) is not None
    ]
    # Nansen spend comes from every logged row, not just the chosen ones: each purchase is logged once.
    cost_by: dict[tuple[str, str], float] = defaultdict(float)
    for r in rows:
        cost_by[(decided_by(r), r.tier)] += r.info.cost_usd

    def group(key) -> dict:
        buckets: dict[str, list[EventScore]] = defaultdict(list)
        costs: dict[str, float] = defaultdict(float)
        for s in scores:
            buckets[key(s)].append(s)
        for (who, tier), c in cost_by.items():
            costs[key(EventScore("", "", tier, who, 0, 0, None, None, None))] += c
        return {k: summarize(v, costs[k]) for k, v in sorted(buckets.items())}

    return {
        "include_stub": include_stub,
        "unsettled_or_unmatched": len(pick_rows(rows)) - len(scores),
        "overall": summarize(scores, sum(cost_by.values())),
        "by_decided_by": group(lambda s: s.decided_by),
        "by_tier": group(lambda s: s.tier),
    }


def _print(name: str, s: dict) -> None:
    fmt = lambda x: "  -   " if x is None else f"{x:.4f}"  # noqa: E731
    print(f"\n{name}: {s['events']} Events")
    print(f"  Brier (lower is better)  baseline {fmt(s['brier_baseline'])}  market {fmt(s['brier_market'])}")
    print(
        f"  with Nansen data: {s['events_with_data']} Events  informed {fmt(s['brier_informed'])}"
        f"  vs baseline {fmt(s['brier_baseline_same_events'])} on the same Events"
    )
    print(
        f"  shadow trades: {s['trades']} ({s['trades_won']} won)  P&L ${s['pnl_usd']:+.2f}"
        f" on ${s['staked_usd']:.2f} staked  (with data ${s['pnl_with_data_usd']:+.2f})"
    )
    print(f"  Nansen spend: ${s['data_cost_usd']:.2f}")


if __name__ == "__main__":
    report = score(include_stub="--include-stub" in sys.argv)
    print(f"Scoring {'including' if report['include_stub'] else 'excluding'} stub rows;"
          f" {report['unsettled_or_unmatched']} logged Events not settled yet (run scoring.settle)")
    _print("Overall", report["overall"])
    for who, s in report["by_decided_by"].items():
        _print(f"Decided by {who}", s)
    for tier, s in report["by_tier"].items():
        _print(f"Tier {tier}", s)
