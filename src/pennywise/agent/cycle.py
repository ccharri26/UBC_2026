"""One agent cycle. Steps 1-5: snapshot, Nansen readings, a call per Contract, shadow trades, decision log.

Steps (see README):
  1. fetch_snapshot()                        free Gemini data, grouped by (asset, tier)
  2. decide() + get_signals() -> reading     buy Nansen data for groups worth it
  3. informed_prob() -> edges() -> call()    per Contract
  4. pick_trades()                           at most one shadow trade per Event
  5. append_decision()                       one row per (asset, tier), if something changed
"""

from dataclasses import dataclass
from typing import Literal

from pennywise.decisions import (
    DecisionRow,
    InfoRecord,
    QuoteRecord,
    RecordError,
    TradeRecord,
    append_decision,
    read_decisions,
    traded_events,
    worth_logging,
)
from pennywise.forecast.informed import informed_prob
from pennywise.info.value import InfoDecision, Quote, decide
from pennywise.markets.gemini import MarketSnapshot, fetch_snapshot
from pennywise.nansen import (
    NansenResponseError,
    NansenUnavailable,
    Tier,
    UnsupportedAsset,
    cached_result,
    get_signals,
    horizons_for,
    is_cached,
    reading,
    stub_mode,
)
from pennywise.payments.guardrails import PaymentRefused
from pennywise.payments.pay import PaymentFailed
from pennywise.trading.edge import call, edges
from pennywise.trading.shadow import pick_trades

Source = Literal["paid", "cached", "none"]
NansenError = Literal["unsupported", "refused", "failed", "bad_response", "expired"]


@dataclass(frozen=True)
class NansenResult:
    """What happened with Nansen for one (asset, tier) group this cycle."""

    source: Source  # bought this cycle, already cached, or no data
    reading: float | None  # nansen.reading() in [-1, 1]; None means use the baseline
    cost_usd: float = 0.0  # actually paid this cycle (0 for cached, none, or stub)
    error: NansenError | None = None  # why there's no data when we wanted it
    spent: bool = False  # with `error`: money left the wallet anyway


NO_DATA = NansenResult("none", None)


def _error_label(e: NansenUnavailable) -> NansenError:
    """Map Nansen's exception to a fixed label for the decision log."""
    if isinstance(e, UnsupportedAsset):
        return "unsupported"
    if isinstance(e.__cause__, PaymentRefused):
        return "refused"  # a guardrail said no (budget, kill switch, ...): nothing spent
    if isinstance(e.__cause__, NansenResponseError):
        return "bad_response"
    return "failed"


def fetch_reading(asset: str, tier: Tier, d: InfoDecision) -> NansenResult:
    """Get Nansen data for one group if decide() said to, else NO_DATA. Never raises NansenUnavailable."""
    if not d.buy:
        return NO_DATA
    if d.from_cache:
        # decide() priced this at $0 because it was cached, so never buy here. If the entry
        # expired since, use the baseline this cycle; the next cycle decides at the real price.
        signals = cached_result(asset, tier)
        if signals is None:
            return NansenResult("none", None, error="expired")
        return NansenResult("cached", reading(signals))
    was_cached = is_cached(asset, tier)  # check before get_signals(), which fills the cache
    try:
        signals = get_signals(asset, horizons_for(tier)[0])  # any horizon of the tier buys the same data
    except NansenUnavailable as e:
        cost = d.price_usd if e.spent else 0.0
        return NansenResult("none", None, cost, _error_label(e), e.spent)
    if was_cached:
        return NansenResult("cached", reading(signals))
    cost = 0.0 if stub_mode() else signals.cost_usdc / 1_000_000
    return NansenResult("paid", reading(signals), cost)


def get_readings(
    snap: MarketSnapshot,
) -> dict[tuple[str, Tier], tuple[InfoDecision, NansenResult]]:
    """Step 2: decide() every group, then fetch Nansen for the ones worth it.

    Groups are fetched best first (value minus price), so if a budget guardrail refuses
    partway through, the money went to the groups worth the most. Refused groups fall
    back to the baseline.
    """
    decisions = {
        (asset, tier): decide(asset, tier, quotes, snap.spots[asset], snap.vols[asset])
        for (asset, tier), quotes in snap.groups.items()
    }
    order = sorted(decisions, key=lambda k: decisions[k].value_usd - decisions[k].price_usd, reverse=True)
    return {key: (decisions[key], fetch_reading(*key, decisions[key])) for key in order}


def forecast_quotes(
    quotes: list[Quote], spot: float, minute_vol: float, tier: Tier, reading: float | None
) -> list[QuoteRecord]:
    """Step 3: baseline, informed chance (if there's a reading), edges and a call per Contract.

    The baseline is always kept so scoring can compare it with the informed forecast.
    The call uses the informed chance when there is one, else the baseline.
    """
    records = []
    for q in quotes:
        mid = (q.bid + q.ask) / 2
        baseline = informed_prob(spot, q.strike, q.mins_left, minute_vol, mid, 0.0, tier)  # reading 0 = baseline
        informed = (
            informed_prob(spot, q.strike, q.mins_left, minute_vol, mid, reading, tier)
            if reading is not None else None
        )
        yes_edge, no_edge = edges(informed if informed is not None else baseline, q.bid, q.ask)
        try:
            records.append(QuoteRecord(
                q.event, q.strike, q.mins_left, q.bid, q.ask,
                baseline, informed, yes_edge, no_edge, call(yes_edge, no_edge),
            ))
        except RecordError as e:  # e.g. a crossed or out-of-range quote from Gemini: skip it
            print(f"  skipped quote {q.event} @ {q.strike}: {e}")
    return records


def last_rows() -> tuple[int, dict[tuple[str, str], DecisionRow]]:
    """(last cycle number, newest logged row per (asset, tier)) from the decision log."""
    rows = read_decisions(limit=500).rows  # newest 500 is plenty: 8 groups per cycle at most
    last = {(r.asset, r.tier): r for r in rows}  # later rows overwrite earlier ones
    return (rows[-1].cycle if rows else 0), last


def build_row(
    snap: MarketSnapshot, cycle: int, stub: bool, asset: str, tier: Tier,
    d: InfoDecision, n: NansenResult, quotes: list[QuoteRecord], trades: list[TradeRecord],
) -> DecisionRow:
    """Step 5: one decision-log row for one (asset, tier) group. Numbers and fixed labels only."""
    info = InfoRecord(
        value_usd=d.value_usd,
        price_usd=d.price_usd,
        buy=d.buy,
        reason=d.reason,
        source=n.source,
        cost_usd=n.cost_usd,
        reading=n.reading,
        error=n.error,
        spent=n.spent,
    )
    return DecisionRow(
        at=snap.at,
        cycle=cycle,
        stub=stub,
        asset=asset,
        tier=tier.value,
        spot=snap.spots[asset],
        minute_vol=snap.vols[asset],
        info=info,
        quotes=tuple(quotes),
        trades=tuple(trades),
    )


def run_cycle() -> None:
    snap = fetch_snapshot()
    results = get_readings(snap)
    stub = stub_mode()
    # Events traded in earlier cycles (from the decision log) are never traded again.
    # A live run ignores trades made in stub mode, since those used fake readings.
    traded = traded_events(include_stub=stub)
    last_cycle, previous = last_rows()
    cycle = last_cycle + 1
    print(f"cycle {cycle} at {snap.at:%Y-%m-%d %H:%M:%S} UTC  (stub={stub})")
    all_trades = []
    logged = 0
    for (asset, tier), (d, n) in results.items():
        quotes = forecast_quotes(snap.groups[(asset, tier)], snap.spots[asset], snap.vols[asset], tier, n.reading)
        trades = pick_trades(quotes, traded)
        try:
            row = build_row(snap, cycle, stub, asset, tier, d, n, quotes, trades)
        except RecordError as e:  # a row that doesn't fit the schema: report it, don't trade on it
            print(f"  could not log {asset} {tier.value}: {e}")
            trades = []
        else:
            # Always log a trade or a payment; otherwise only when something changed.
            if worth_logging(row, previous.get((asset, tier.value))):
                append_decision(row)
                logged += 1
        traded |= {t.event for t in trades}
        all_trades += trades
        r = f"{n.reading:+.2f}" if n.reading is not None else "  -  "
        err = f"  error={n.error}" if n.error else ""
        print(
            f"\n{asset:<4} {tier.value:<12} {'BUY' if d.buy else 'skip':<4} ({d.reason})"
            f"  source={n.source} reading={r} cost=${n.cost_usd:.2f}{err}"
        )
        for q in quotes:
            inf = f"{q.informed:.2f}" if q.informed is not None else "  - "
            print(
                f"    {q.event:<18} strike {q.strike:>12,.4f}  bid {q.bid:.2f} ask {q.ask:.2f}"
                f"  base {q.baseline:.2f} inf {inf}  yesE {q.yes_edge:+.2f} noE {q.no_edge:+.2f}  {q.call}"
            )

    print(f"\nLogged {logged} of {len(results)} groups to data/decisions.jsonl")
    print(f"Trades this cycle (shadow, nothing sent to Gemini): {len(all_trades)}")
    for t in all_trades:
        print(
            f"  {t.event:<18} {t.side:<3} strike {t.strike:>12,.4f}  {t.contracts} x ${t.price:.2f}"
            f" + fee ${t.fee_usd:.2f}  edge {t.edge:+.3f}/contract"
        )


if __name__ == "__main__":
    run_cycle()
