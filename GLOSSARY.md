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

**Decision**:
The agent's choice for one asset and one Tier in one Cycle: skip the data, reuse data already bought, or buy it, together with any trades that follow.
_Avoid_: Action, step

**Cycle**:
One pass of the agent: scan Gemini, decide per Feed whether to buy data, forecast, trade or pass, then settle finished Events.
_Avoid_: Pass, tick, iteration

**Run**:
Everything from one human start of the agent until it stops: a sequence of one or more Cycles. It ends when its Cycles are done, a human stops it, the Kill Switch trips, Cycles keep failing, or the server restarts. Each Run has its own spending budget.
_Avoid_: Session, job

**Profit**:
Settled shadow-trade winnings minus what was spent on Nansen data. LLM costs are not counted, and shadow trades are assumed to fill at the quoted price.
_Avoid_: Return, earnings

**Feed**:
One asset's Nansen data at one Tier, such as ETH Smart Money. Spending budgets are counted per Feed per day.
_Avoid_: Market, slot

**Approval Threshold**:
The price at or above which a purchase of Nansen data needs a human's approval before any money moves. The human sets it, up to a ceiling that only they can raise by hand.
_Avoid_: Approval limit, trigger

**Approval Request**:
One purchase at or above the Approval Threshold, waiting for a human to approve or deny it. It covers that one purchase only. A denial skips the purchase; no answer in time counts as a denial and also trips the Kill Switch.
_Avoid_: Prompt, confirmation

**Kill Switch**:
Stops all spending and all trading until a human turns it back off.
_Avoid_: Pause, stop button (stopping a Run ends the Run but leaves spending allowed)
