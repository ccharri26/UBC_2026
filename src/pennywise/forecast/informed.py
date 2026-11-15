"""Informed forecast: the baseline, with the price nudged by a Nansen reading.

A reading (pennywise.nansen.reading(), in [-1, 1]) moves the expected price by
reading * NUDGE_STRONG typical moves over the data's window. A reading of 0 gives
exactly the baseline. info/value.py uses the same shift() to imagine readings before
buying, so the purchase check and the real update can't drift apart.
"""

import math

from pennywise.nansen import Tier

from .baseline import blend, prob_above

# A strong reading (+-1) shifts the expected price by this many typical moves *over the
# data's window* (not over the time to expiry). A guess until scoring calibrates it.
NUDGE_STRONG = 0.5
# How much time each tier's data covers.
WINDOW_MINUTES: dict[Tier, float] = {Tier.BASIC: 5, Tier.SMART_MONEY: 60}


def shift(reading: float, minute_vol: float, tier: Tier) -> float:
    """How far a reading moves the expected log-price."""
    return reading * NUDGE_STRONG * minute_vol * math.sqrt(WINDOW_MINUTES[tier])


def informed_prob(
    spot: float,
    strike: float,
    minutes_left: float,
    minute_vol: float,
    market_mid: float,
    reading: float,
    tier: Tier,
) -> float:
    """Chance of ending at or above `strike`, after nudging the price by the reading.

    Blended with the market price exactly like the baseline, so reading=0 is the baseline.
    """
    nudged_spot = spot * math.exp(shift(reading, minute_vol, tier))
    return blend(prob_above(nudged_spot, strike, minutes_left, minute_vol), market_mid)
