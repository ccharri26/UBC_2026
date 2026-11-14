"""Horizons (how long a Gemini Event runs) and the one paid Tier each maps to.

Values match the series suffixes in markets/gemini.py ("ETH05M", "SOL1H", ...).
"""

from enum import Enum

from .endpoints import Tier


class Horizon(str, Enum):
    M5 = "05M"
    M15 = "15M"
    H1 = "1H"


# Each Horizon buys exactly one Tier. Nansen has no 15m window, so 5M and 15M
# both use Basic (5m flow) and can share one purchase per asset.
HORIZON_TIER: dict[Horizon, Tier] = {
    Horizon.M5: Tier.BASIC,
    Horizon.M15: Tier.BASIC,
    Horizon.H1: Tier.SMART_MONEY,
}
