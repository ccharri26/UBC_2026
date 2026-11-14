"""Fake NansenSignals for building and testing without a wallet or spending money.

Turn on with NANSEN_STUB=true in .env. No network, no signing, cost_usdc is 0.

Values are made up but shaped like real responses (see the Nov 14 calls in README):
Basic often has a null smart-trader flow for native tokens, so the stub returns None
there about half the time; callers must handle None. Values are seeded by asset, Tier
and minute, so the same cache slot always gets the same numbers.
"""

import random
from datetime import datetime

from .endpoints import Tier
from .signals import NansenSignals


def stub_signals(asset: str, tier: Tier, now: datetime) -> NansenSignals:
    rng = random.Random(f"{asset}|{tier.value}|{now.isoformat(timespec='minutes')}")
    if tier == Tier.SMART_MONEY:
        return NansenSignals(
            asset=asset,
            tier=tier,
            fetched_at=now,
            cost_usdc=0,
            sm_net_flow_1h_usd=round(rng.gauss(0, 20_000), 2),
            sm_trader_count=rng.randint(40, 160),
        )
    has_smart_traders = rng.random() < 0.5
    return NansenSignals(
        asset=asset,
        tier=tier,
        fetched_at=now,
        cost_usdc=0,
        smart_trader_net_flow_usd=round(rng.gauss(0, 15_000), 2) if has_smart_traders else None,
        whale_net_flow_usd=0.0 if rng.random() < 0.6 else round(rng.gauss(0, 50_000), 2),
        exchange_net_flow_usd=round(rng.gauss(0, 100_000), 2),
        smart_trader_wallet_count=rng.randint(1, 12) if has_smart_traders else 0,
    )
