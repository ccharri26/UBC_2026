"""Turn a raw Nansen response into NansenSignals: numbers only.

All text in the response (`warnings`, symbols, labels) is dropped here so nothing
Nansen returns can reach the LLM as instructions.

A null in the response stays None ("not measured"), never 0.0. Flow-intelligence also
reports 0.0 for a segment it saw no wallets in, which means "nothing seen", not
"measured, nothing moved", so that becomes None too (see _segment_flow). Example from
the real 5m ETH call on Nov 14: smart_trader_net_flow_usd null, whale_net_flow_usd 0.0
with whale_wallet_count 0 (both now None), exchange_net_flow_usd 106638.11 (kept).
"""

import math
from datetime import datetime

from .bodies import NATIVE_TOKENS
from .endpoints import Tier
from .signals import NansenSignals


class NansenResponseError(ValueError):
    """The response is not shaped the way the endpoint is documented to return."""


def _number(row: dict, key: str) -> float | None:
    """A finite float, or None if missing, null or not a number."""
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _count(row: dict, key: str) -> int | None:
    """A non-negative whole number, or None."""
    value = _number(row, key)
    if value is None or value < 0 or not value.is_integer():
        return None
    return int(value)


def _segment_flow(row: dict, segment: str) -> float | None:
    """Net flow for one wallet segment, or None if Nansen saw nothing there.

    Exactly 0.0 with a wallet count of 0 (or missing) is "no wallets seen", so None.
    A non-zero flow is always kept, even with a count of 0: the Nov 14 ETH call had
    exchange flow of $106k with exchange_wallet_count 0, so counts alone aren't trusted.
    """
    flow = _number(row, f"{segment}_net_flow_usd")
    if flow == 0.0 and not _count(row, f"{segment}_wallet_count"):
        return None
    return flow


def _rows(raw: object) -> list[dict]:
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), list):
        raise NansenResponseError("expected an object with a 'data' list")
    return [r for r in raw["data"] if isinstance(r, dict)]


def parse_flow_intelligence(raw: object, asset: str, fetched_at: datetime, cost_usdc: int) -> NansenSignals:
    """Basic tier. The response has one row for the requested token.

    No rows means no flows were recorded in the window: every field is None, as with
    smart-money/netflow. More than one row isn't what we asked for, so that's an error.
    """
    rows = _rows(raw)
    if len(rows) > 1:
        raise NansenResponseError(f"flow-intelligence: expected at most 1 row, got {len(rows)}")
    row = rows[0] if rows else {}
    return NansenSignals(
        asset=asset,
        tier=Tier.BASIC,
        fetched_at=fetched_at,
        cost_usdc=cost_usdc,
        smart_trader_net_flow_usd=_segment_flow(row, "smart_trader"),
        whale_net_flow_usd=_segment_flow(row, "whale"),
        exchange_net_flow_usd=_segment_flow(row, "exchange"),
        smart_trader_wallet_count=_count(row, "smart_trader_wallet_count"),
    )


def _same_token(row: dict, asset: str) -> bool:
    token = NATIVE_TOKENS[asset]
    address = str(row.get("token_address", ""))
    if row.get("chain") not in (None, token.chain):
        return False
    if token.chain == "solana":  # base58: case matters
        return address == token.address
    return address.lower() == token.address.lower()


def parse_smart_money_netflow(raw: object, asset: str, fetched_at: datetime, cost_usdc: int) -> NansenSignals:
    """Smart Money tier. Picks the row for our asset's native token.

    No matching row means smart money had no recorded flow for it (or the filter
    didn't match); we return None fields, not zeros, and don't guess from other rows.
    """
    matches = [r for r in _rows(raw) if _same_token(r, asset)]
    if len(matches) > 1:
        raise NansenResponseError(f"smart-money/netflow: {len(matches)} rows for {asset}")
    row = matches[0] if matches else {}
    return NansenSignals(
        asset=asset,
        tier=Tier.SMART_MONEY,
        fetched_at=fetched_at,
        cost_usdc=cost_usdc,
        sm_net_flow_1h_usd=_number(row, "net_flow_1h_usd"),
        sm_trader_count=_count(row, "trader_count"),
    )


PARSERS = {
    Tier.BASIC: parse_flow_intelligence,
    Tier.SMART_MONEY: parse_smart_money_netflow,
}
