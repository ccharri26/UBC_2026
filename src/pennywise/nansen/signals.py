"""NansenSignals: the only form in which Nansen data leaves the nansen package.

Numbers only, never text from a Nansen response, so nothing Nansen returns can
reach the LLM as instructions (prompt-injection defence).

Net flow = USD flowing into a group of wallets minus USD flowing out, over the
Tier's window. Positive means the group is accumulating; negative, distributing.

Fields for the Tier you did not buy are None. None means "not measured" (including a
Basic segment where Nansen saw no wallets) and is different from 0.0, which means
"measured, nothing moved".
"""

import math
from dataclasses import dataclass, fields
from datetime import datetime

from .endpoints import Tier


@dataclass(frozen=True)
class NansenSignals:
    asset: str  # "ETH" or "SOL"
    tier: Tier
    fetched_at: datetime  # when we bought it, not when the data is from (Basic may be 10-30 min old)
    cost_usdc: int  # what this purchase cost, in USDC base units (10_000 = $0.01)

    # Basic tier (5M and 15M Horizons): last 5 minutes, by wallet segment.
    smart_trader_net_flow_usd: float | None = None  # historically profitable traders; positive leans up
    whale_net_flow_usd: float | None = None  # very large holders; positive leans up
    exchange_net_flow_usd: float | None = None  # into exchange wallets; positive usually leans down (deposits to sell)
    smart_trader_wallet_count: int | None = None  # breadth: many traders agreeing beats one big wallet

    # Smart Money tier (1H Horizon): rolling window ending at request time.
    sm_net_flow_1h_usd: float | None = None  # net buying by smart-money wallets over the last hour
    sm_trader_count: int | None = None  # breadth: how many smart-money traders are involved

    def __post_init__(self) -> None:
        # Reject NaN/inf so bad data can't silently poison the forecast.
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"{f.name} must be finite, got {value!r}")
        if self.cost_usdc < 0:
            raise ValueError(f"cost_usdc must be >= 0, got {self.cost_usdc}")
