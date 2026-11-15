"""Baseline probability from free data: current price, strike, time left, recent movement."""

import math
from statistics import NormalDist

# How fast old data fades: a move this many hours ago counts half as much as one now.
HALF_LIFE_HOURS = 12
# Weight on our model when blending with the market price (0.5 = 50/50).
MODEL_WEIGHT = 0.5


def minute_volatility(closes: list[float], candle_minutes: int) -> float:
    """Typical move per minute, weighting recent candles more (exponentially weighted).

    `closes` are candle close prices, oldest first. Each step back in time multiplies a
    move's weight by `decay`, so a move HALF_LIFE_HOURS ago counts half as much as now.
    """
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    decay = 0.5 ** (candle_minutes / (HALF_LIFE_HOURS * 60))
    weights = [decay**age for age in range(len(returns) - 1, -1, -1)]  # newest has age 0
    variance = sum(w * r * r for w, r in zip(weights, returns)) / sum(weights)
    return math.sqrt(variance / candle_minutes)


def typical_move(minute_vol: float, minutes_left: float) -> float:
    """Typical move by expiry. Moves grow with the square root of time, not linearly."""
    return minute_vol * math.sqrt(max(minutes_left, 0))


def prob_above(spot: float, strike: float, minutes_left: float, minute_vol: float) -> float:
    """Chance the price ends at or above `strike`, assuming no drift and bell-curve moves."""
    move = typical_move(minute_vol, minutes_left)
    if move == 0:
        return 1.0 if spot >= strike else 0.0
    # Log-price at expiry ~ Normal(log(spot) - move^2/2, move); the -move^2/2 keeps the
    # expected *price* (not log-price) equal to today's.
    z = (math.log(spot / strike) - move * move / 2) / move
    return NormalDist().cdf(z)


def blend(model: float, market_mid: float, model_weight: float = MODEL_WEIGHT) -> float:
    """Weighted average of our model and the market's price."""
    return model_weight * model + (1 - model_weight) * market_mid
