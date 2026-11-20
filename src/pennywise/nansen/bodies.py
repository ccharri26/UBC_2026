"""Build the JSON request body for each Nansen endpoint, per asset.

Only assets in NATIVE_TOKENS get paid data: ETH and SOL (both Tiers tested live). Nansen
has no XRP coverage and no useful native BTC. Each one needs flow scales in interpret.py.
Native-token placeholders come from https://docs.nansen.ai/reference/native-tokens
(copy exactly: a miscased Solana value is silently treated as a normal token).
"""

from dataclasses import dataclass

from .endpoints import Endpoint, FLOW_INTELLIGENCE, SMART_MONEY_NETFLOW


@dataclass(frozen=True)
class NativeToken:
    chain: str
    address: str


NATIVE_TOKENS: dict[str, NativeToken] = {
    "ETH": NativeToken("ethereum", "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"),
    "SOL": NativeToken("solana", "So11111111111111111111111111111111111111112"),  # base58: case matters
}


def flow_intelligence_body(asset: str, timeframe: str = "5m") -> dict:
    """Basic tier, used for 5M and 15M Events. timeframe: 5m, 1h, 6h, 12h, 1d or 7d.

    Nansen has no 15m window, so 15M Events also use 5m (the most recent flow).
    """
    token = NATIVE_TOKENS[asset]
    return {"chain": token.chain, "token_address": token.address, "timeframe": timeframe}


def smart_money_netflow_body(asset: str) -> dict:
    """Smart Money tier, used for 1H Events (rolling net_flow_1h_usd, uncached).

    Native tokens are excluded unless include_native_tokens is set.
    """
    token = NATIVE_TOKENS[asset]
    return {
        "chains": [token.chain],
        "filters": {"token_address": token.address, "include_native_tokens": True},
        "pagination": {"page": 1, "per_page": 10},
    }


def build_body(endpoint: Endpoint, asset: str) -> dict:
    if endpoint == FLOW_INTELLIGENCE:
        return flow_intelligence_body(asset)
    if endpoint == SMART_MONEY_NETFLOW:
        return smart_money_netflow_body(asset)
    raise ValueError(f"No body builder for {endpoint.path}")
