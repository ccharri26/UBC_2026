"""Value of information: is a Nansen purchase likely to pay for itself?

Before paying, imagine the readings Nansen might return (bearish ... bullish). For each,
nudge the forecast, redo the trade decision on every Event the purchase covers, and add
up the profit. The average over readings, minus the profit we'd make without the data,
is what the data is worth. Buy only if that beats its price.

This only recommends. Payments go through payments/, whose guardrails have the final say.
"""

import math
from dataclasses import dataclass

from pennywise.forecast.baseline import blend, prob_above
from pennywise.nansen import Tier, is_cached, is_supported, tier_price
from pennywise.trading.edge import MAX_CONTRACTS, call, edges

# Possible Nansen readings and how likely we think each is, before buying.
# -1 = strongly bearish, +1 = strongly bullish. A guess until scoring calibrates it.
SCENARIOS: tuple[tuple[float, float], ...] = (
    (-1.0, 0.1),
    (-0.5, 0.2),
    (0.0, 0.4),
    (0.5, 0.2),
    (1.0, 0.1),
)
# A strong reading shifts the expected price by this many typical moves *over the
# data's window* (not over the time to expiry). Also a guess until scoring calibrates it.
NUDGE_STRONG = 0.5
# How much time each tier's data covers.
WINDOW_MINUTES: dict[Tier, float] = {Tier.BASIC: 5, Tier.SMART_MONEY: 60}


@dataclass(frozen=True)
class Quote:
    """One two-sided Contract, as the value check sees it."""

    event: str  # Event ticker: Contracts in one Event share an outcome
    strike: float
    mins_left: float
    bid: float
    ask: float


@dataclass(frozen=True)
class InfoDecision:
    asset: str
    tier: Tier
    value_usd: float  # expected extra profit from having the data
    price_usd: float
    buy: bool
    reason: str


def best_trade_profit(
    quotes: list[Quote], spot: float, minute_vol: float, shift: float
) -> float:
    """Expected profit from the single best trade in one Event, with the price nudged by `shift`.

    One trade per Event: its Contracts all hinge on the same final price, so buying
    several is one bigger bet, not several independent ones.
    """
    nudged_spot = spot * math.exp(shift)
    best = 0.0
    for q in quotes:
        belief = blend(prob_above(nudged_spot, q.strike, q.mins_left, minute_vol), (q.bid + q.ask) / 2)
        yes_edge, no_edge = edges(belief, q.bid, q.ask)
        verdict = call(yes_edge, no_edge)
        edge = yes_edge if verdict == "BUY YES" else no_edge if verdict == "BUY NO" else 0.0
        best = max(best, edge * MAX_CONTRACTS)
    return best


def value_of_information(
    quotes: list[Quote], spot: float, minute_vol: float, tier: Tier
) -> float:
    """Expected extra profit, in dollars, from knowing the Nansen reading before trading."""
    by_event: dict[str, list[Quote]] = {}
    for q in quotes:
        by_event.setdefault(q.event, []).append(q)

    strong_shift = NUDGE_STRONG * minute_vol * math.sqrt(WINDOW_MINUTES[tier])

    def total_profit(shift: float) -> float:
        return sum(best_trade_profit(qs, spot, minute_vol, shift) for qs in by_event.values())

    without_data = total_profit(0.0)
    with_data = sum(weight * total_profit(reading * strong_shift) for reading, weight in SCENARIOS)
    return max(0.0, with_data - without_data)


def decide(
    asset: str, tier: Tier, quotes: list[Quote], spot: float, minute_vol: float
) -> InfoDecision:
    if not is_supported(asset):
        return InfoDecision(asset, tier, 0.0, tier_price(tier) / 1_000_000, False, "no Nansen coverage")
    # Fresh data already in the cache costs nothing more, so always use it.
    cached = is_cached(asset, tier)
    price = 0.0 if cached else tier_price(tier) / 1_000_000  # USDC base units -> dollars
    if not quotes:
        return InfoDecision(asset, tier, 0.0, price, False, "no two-sided contracts")
    value = value_of_information(quotes, spot, minute_vol, tier)
    if cached:
        return InfoDecision(asset, tier, value, price, True, "already cached, free")
    if value > price:
        return InfoDecision(asset, tier, value, price, True, "worth more than it costs")
    return InfoDecision(asset, tier, value, price, False, "not worth its price")
