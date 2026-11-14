# PennyWise

An agent that forecasts Gemini crypto prediction contracts, decides whether paid Nansen data is worth its price, and then decides whether to trade.

## Language

**Event**:
One question on Gemini with a single settlement time, such as "BTC price on November 20". It groups one or more Contracts that settle together.
_Avoid_: Market

**Contract**:
One strike within an Event that pays $1 if its outcome happens and $0 if not. Its price is the market's implied probability.
_Avoid_: Market, option

**Horizon**:
How long an Event runs before it settles: 5M, 15M or 1H. Each Horizon is paired with one Tier.
_Avoid_: Series, duration, timeframe

**Tier**:
A level of paid Nansen data with a fixed price per call: Basic (5M and 15M Horizons) or Smart Money (1H Horizon).
_Avoid_: Plan, package
