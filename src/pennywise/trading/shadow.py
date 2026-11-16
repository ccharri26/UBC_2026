"""Pick trades: at most one per Event, the Contract with the biggest edge. Shadow mode only.

All Contracts in one Event settle on the same final price, so buying several of them is
one bigger bet, not several independent ones. This matches info/value.py's
best_trade_profit(), so the Nansen purchase check values data the way we actually trade.
"""

from pennywise.decisions import QuoteRecord, TradeRecord

from .edge import MAX_CONTRACTS, taker_fee


def pick_trades(quotes: list[QuoteRecord], already_traded: set[str]) -> list[TradeRecord]:
    """Best BUY YES / BUY NO per Event, skipping Events traded in an earlier cycle.

    Nothing is sent to Gemini: these are simulated (shadow) trades for the decision log.
    """
    best: dict[str, tuple[float, QuoteRecord]] = {}
    for q in quotes:
        if q.event in already_traded or q.call == "pass":
            continue
        edge = q.yes_edge if q.call == "BUY YES" else q.no_edge
        if q.event not in best or edge > best[q.event][0]:
            best[q.event] = (edge, q)

    trades = []
    for edge, q in best.values():
        side = "YES" if q.call == "BUY YES" else "NO"
        price = q.ask if side == "YES" else round(1 - q.bid, 4)  # cost of one $1 contract
        trades.append(TradeRecord(
            event=q.event,
            strike=q.strike,
            side=side,
            price=price,
            contracts=MAX_CONTRACTS,
            fee_usd=taker_fee(price) * MAX_CONTRACTS,
            edge=edge,
            mode="shadow",
        ))
    return trades
