"""The Nansen endpoints PennyWise is allowed to call, one per tier.

Anything not in ENDPOINTS is off-limits; the guardrails use this as the allowlist.
"""

from dataclasses import dataclass
from enum import Enum

BASE_URL = "https://api.nansen.ai"


class Tier(str, Enum):
    BASIC = "basic"
    SMART_MONEY = "smart_money"


@dataclass(frozen=True)
class Endpoint:
    path: str
    tier: Tier
    price: int  # expected price in USDC base units (6 decimals): 10_000 = $0.01

    @property
    def url(self) -> str:
        return BASE_URL + self.path


# Basic ($0.01), for 5M/15M Events: net flow by wallet segment (smart trader,
# whale, exchange, ...) for one token over a 5m window. Supports native ETH/SOL.
FLOW_INTELLIGENCE = Endpoint("/api/v1/tgm/flow-intelligence", Tier.BASIC, 10_000)

# Smart Money ($0.05), for 1H Events: smart-money net flow over 1h/24h/7d/30d
# plus trader count. Rolling windows ending at request time, no response cache.
SMART_MONEY_NETFLOW = Endpoint("/api/v1/smart-money/netflow", Tier.SMART_MONEY, 50_000)

ENDPOINTS: dict[Tier, Endpoint] = {
    Tier.BASIC: FLOW_INTELLIGENCE,
    Tier.SMART_MONEY: SMART_MONEY_NETFLOW,
}
