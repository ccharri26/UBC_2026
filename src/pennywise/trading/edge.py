"""Edge per side and the buy Yes / buy No / pass rule. shadow.py picks trades from these calls."""

# Only trade when expected profit per contract, after fees, beats this margin.
MIN_EDGE = 0.03
# Contracts per trade (each pays $1). Shadow mode: nothing is actually spent.
MAX_CONTRACTS = 10


def taker_fee(price: float) -> float:
    """Gemini's prediction-market taker fee per contract: 0.07 * P * (1 - P)."""
    return 0.07 * price * (1 - price)


def edges(prob: float, bid: float | None, ask: float | None) -> tuple[float | None, float | None]:
    """(yes_edge, no_edge): expected profit per $1 contract if we buy that side now.

    Buying Yes costs the ask and wins with chance `prob`. Buying No costs 1 - bid and
    wins with chance 1 - prob.
    """
    yes_edge = prob - ask - taker_fee(ask) if ask is not None else None
    no_cost = 1 - bid if bid is not None else None
    no_edge = (1 - prob) - no_cost - taker_fee(no_cost) if no_cost is not None else None
    return yes_edge, no_edge


def call(yes_edge: float | None, no_edge: float | None) -> str:
    if yes_edge is not None and yes_edge > MIN_EDGE:
        return "BUY YES"
    if no_edge is not None and no_edge > MIN_EDGE:
        return "BUY NO"
    return "pass"
