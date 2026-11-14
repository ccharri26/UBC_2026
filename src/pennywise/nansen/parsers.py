"""Turn a raw Nansen response into NansenSignals: numbers only.

All text in the response (`warnings`, symbols, labels) is dropped here so nothing
Nansen returns can reach the LLM as instructions.

A null in the response stays None ("not measured"), never 0.0. Example from a real
5m ETH flow-intelligence call: smart_trader_net_flow_usd was null while
whale_net_flow_usd was 0.0.
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


def _rows(raw: object) -> list[dict]:
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), list):
        raise NansenResponseError("expected an object with a 'data' list")
    return [r for r in raw["data"] if isinstance(r, dict)]


def parse_flow_intelligence(raw: object, asset: str, fetched_at: datetime, cost_usdc: int) -> NansenSignals:
    """Basic tier. The response has one row for the requested token."""
    rows = _rows(raw)
    if len(rows) != 1:
        raise NansenResponseError(f"flow-intelligence: expected 1 row, got {len(rows)}")
    row = rows[0]
    return NansenSignals(
        asset=asset,
        tier=Tier.BASIC,
        fetched_at=fetched_at,
        cost_usdc=cost_usdc,
        smart_trader_net_flow_usd=_number(row, "smart_trader_net_flow_usd"),
        whale_net_flow_usd=_number(row, "whale_net_flow_usd"),
        exchange_net_flow_usd=_number(row, "exchange_net_flow_usd"),
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
