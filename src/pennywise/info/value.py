"""Value of information: is a Nansen purchase likely to pay for itself?

Before paying, imagine the readings Nansen might return (bearish ... bullish). For each,
nudge the forecast with the same forecast/informed.py update used after buying, redo the trade decision on every Event the purchase covers, and add
up the profit. The average over readings, minus the profit we'd make without the data,
is what the data is worth. Buy only if that beats its price.

This only recommends. Payments go through payments/, whose guardrails have the final say.
"""

from dataclasses import dataclass

from pennywise.forecast.informed import informed_prob
from pennywise.nansen import Tier, is_cached, is_supported, tier_price
from pennywise.trading.edge import MAX_CONTRACTS, call, edges

# Possible Nansen readings and how likely we think each is, before buying.
# -1 = strongly bearish, +1 = strongly bullish. Keep roughly in step with what
# pennywise.nansen.reading() produces (`python -m pennywise.nansen --spread` prints its spread).
SCENARIOS: tuple[tuple[float, float], ...] = (
    (-1.0, 0.1),
    (-0.5, 0.2),
    (0.0, 0.4),
    (0.5, 0.2),
    (1.0, 0.1),
)


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
    quotes: list[Quote], spot: float, minute_vol: float, reading: float, tier: Tier
) -> float:
    """Expected profit from the single best trade in one Event, if Nansen returned `reading`.

    One trade per Event: its Contracts all hinge on the same final price, so buying
    several is one bigger bet, not several independent ones.
    """
    best = 0.0
    for q in quotes:
        belief = informed_prob(spot, q.strike, q.mins_left, minute_vol, (q.bid + q.ask) / 2, reading, tier)
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

    def total_profit(reading: float) -> float:
        return sum(best_trade_profit(qs, spot, minute_vol, reading, tier) for qs in by_event.values())

    without_data = total_profit(0.0)  # reading 0 = baseline
    with_data = sum(weight * total_profit(reading) for reading, weight in SCENARIOS)
    return max(0.0, with_data - without_data)


def decide(
    asset: str, tier: Tier, quotes: list[Quote], spot: float, minute_vol: float
) -> InfoDecision:
    if not is_supported(asset):
        return InfoDecision(asset, tier, 0.0, tier_price(tier) / 1_000_000, False, "no nansen coverage")
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
