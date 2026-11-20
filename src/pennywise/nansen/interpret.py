"""Interpret NansenSignals as one reading in [-1, 1]: -1 strongly bearish, +1 strongly bullish.

This is the only interpretation of Nansen data; forecast/informed.py turns the reading
into a price move. info/value.py's SCENARIOS guess how readings are spread before
buying, so keep the two roughly in step (check with `python -m pennywise.nansen --spread`).

Each flow is squashed with tanh(flow / scale), so one huge transfer can't push the
reading past +-1. A field that is None was not measured and is left out; 0.0 was
measured and counts as "nothing moved".
"""

import math

from .endpoints import Tier
from .signals import NansenSignals

# USD flow that counts as "one unit" (tanh(1) ~ 0.76), per asset. Rough guesses, to be
# refined from real readings (the raw flows are kept in data/nansen_cache.json).
SCALE_USD: dict[str, dict[str, float]] = {
    # Matched to the stub's spread.
    "ETH": {
        "smart_trader": 15_000,
        "whale": 50_000,
        "exchange": 100_000,
        "sm_1h": 20_000,
    },
    # From one live call per Tier (2026-11-20): smart money moved $326 in 1h (178 traders),
    # exchanges -$449k in 5m, whales -$1.3k, no smart traders. So smart money and whales
    # get smaller scales than ETH, and exchanges a larger one so one burst doesn't max out.
    "SOL": {
        "smart_trader": 5_000,
        "whale": 15_000,
        "exchange": 300_000,
        "sm_1h": 3_000,
    },
}
# Basic tier: how much each wallet segment counts, and which way it points.
BASIC_WEIGHTS: dict[str, float] = {
    "smart_trader": +0.5,  # profitable traders accumulating -> up
    "whale": +0.3,
    "exchange": -0.2,  # flow into exchanges = deposits to sell -> down
}
# Fewer smart traders than this agreeing: trust their flow half as much.
MIN_TRADERS = 3


def _squash(usd: float, scale: float) -> float:
    return math.tanh(usd / scale)


def reading(s: NansenSignals) -> float:
    """One number in [-1, 1] summarising which way the data leans. 0.0 if nothing was measured."""
    if s.tier == Tier.SMART_MONEY:
        if s.sm_net_flow_1h_usd is None:
            return 0.0
        return _squash(s.sm_net_flow_1h_usd, SCALE_USD[s.asset]["sm_1h"])

    flows = {
        "smart_trader": s.smart_trader_net_flow_usd,
        "whale": s.whale_net_flow_usd,
        "exchange": s.exchange_net_flow_usd,
    }
    total = weight_used = 0.0
    for name, usd in flows.items():
        if usd is None:
            continue
        w = BASIC_WEIGHTS[name]
        trust = 0.5 if name == "smart_trader" and (s.smart_trader_wallet_count or 0) < MIN_TRADERS else 1.0
        total += trust * w * _squash(usd, SCALE_USD[s.asset][name])
        weight_used += abs(w)  # untrusted flow still counts here, so low trust shrinks the reading
    # Divide by the weight actually used, so missing segments don't drag the reading to 0.
    return total / weight_used if weight_used else 0.0



def spread(n_per_asset: int = 500) -> dict[Tier, dict[float, float]]:
    """Share of stub readings nearest each SCENARIOS point, per Tier (for comparing with info/value.py)."""
    from datetime import datetime, timedelta, timezone

    from .bodies import NATIVE_TOKENS
    from .stub import stub_signals

    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    points = (-1.0, -0.5, 0.0, 0.5, 1.0)
    out: dict[Tier, dict[float, float]] = {}
    for tier in Tier:
        counts = dict.fromkeys(points, 0)
        for asset in NATIVE_TOKENS:  # paid assets only
            for m in range(n_per_asset):
                r = reading(stub_signals(asset, tier, start + timedelta(minutes=m)))
                counts[min(points, key=lambda p: abs(p - r))] += 1
        out[tier] = {p: c / (len(NATIVE_TOKENS) * n_per_asset) for p, c in counts.items()}
    return out
