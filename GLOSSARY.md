# PennyWise

An agent that forecasts Gemini crypto prediction contracts, decides whether paid Nansen data is worth its price, and then decides whether to trade.

## Language

**Event**:
One question on Gemini with a single settlement time, such as "BTC price on November 20". It groups one or more Contracts that settle together.
_Avoid_: Market

**Contract**:
One strike within an Event that pays $1 if its outcome happens and $0 if not. Its price is the market's implied probability.
_Avoid_: Market, option
