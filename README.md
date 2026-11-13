# PennyWise

An AI agent that looks at crypto prediction markets on Gemini, decides whether it is worth paying for extra on-chain data from Nansen, picks which price tier to buy, and then decides whether to trade.

## What it does

1. **Scan** Gemini's crypto prediction markets (BTC, ETH, SOL, XRP).
2. **Estimate** a probability for each contract using free data: current price, strike, time left, recent volatility.
3. **Decide whether to buy information.** Is the extra Nansen data likely to change the trade enough to be worth the cost? If not, skip.
4. **Pick a tier** if buying: Basic (about $0.01 per call) or Smart Money (about $0.05 per call).
5. **Pay** automatically with USDC on Base using the x402 payment protocol.
6. **Update** the probability with the new data and **decide whether to trade**. Trades are simulated ("shadow mode") by default, with optional orders in Gemini's sandbox.
7. **Score itself** after each market settles: did the paid data improve the forecast by more than it cost?

## The pieces

| Piece | What it is |
|---|---|
| **Gemini prediction markets** | The markets we trade. Each contract pays $1 if its outcome happens, $0 if not, and its price is the market's implied probability. Public market data needs no API key. A separate sandbox account has fake money. |
| **Nansen** | The paid data source (smart-money flows, token flows, wallet activity). Official x402 pay-per-call API at `api.nansen.ai`; the price list is at `/.well-known/x402`. |
| **x402** | An HTTP standard where a server replies "402 Payment Required" with a price and the agent pays and retries, with no account or API key. |
| **Agent wallet** | A throwaway Base wallet holding a few dollars of USDC. The balance is the most the agent can ever lose. |

**Contracts:** Gemini lists short 5- and 15-minute "up" contracts and daily-and-longer price-threshold contracts. We focus on the **daily threshold contracts**, because Nansen's flow data covers windows of an hour or more and is too slow to matter for 5-minute markets.

## How it decides

```
free baseline probability  -->  is extra info worth its price?  -->  skip / Basic / Smart Money
                                                                              |
                                              pay via x402  -->  update probability  -->  trade or pass
```

- **Baseline:** probability that the price finishes above the strike, from current price, strike, time left, and recent volatility.
- **Is info worth buying?** Compare the expected gain from better information (bigger when the edge is close to the trade threshold and the position is large) against the price of each tier. Pick the best tier, or skip if none pays for itself. One Nansen call about an asset covers all contracts on that asset, so purchases are shared and cached.
- **Trade:** buy only if the estimated edge, after fees and spread, clears a threshold. Position size is a small fraction of the Kelly bet, with a hard cap.
- **The LLM's role:** it explains each decision in plain language and can veto or shrink a trade. It cannot spend more than the code allows.

## Safety limits

All limits are plain code that runs before any payment is signed. The AI cannot override them.

- Only the official Nansen host and its listed endpoints, paid to the expected address, in USDC on Base.
- Hard cap per call ($0.05), plus per-market, per-run, and daily budgets.
- A price-drift check against Nansen's published price list, a kill switch, and a pause after repeated payment failures.
- Wallet capped at about $5 USDC. Shadow mode and a local mock seller are the defaults for development.
- Nansen responses are reduced to numbers before the AI sees them, so text inside a response cannot give it instructions.

## Scoring

Every decision, payment, and trade is logged. After a market settles, we compare the baseline forecast, the informed forecast, and the market price, and calculate what each paid tier cost versus how much it improved the forecast. Results are counted per event, since contracts in one event share an outcome.

## Hackathon

Entered in the **Agentic Payments and AI** track of the University Blockchain Conference hackathon. Submission deadline: Fri Nov 20, 12:00 PM CST.

## Still unverified

- Whether Nansen's endpoints give useful signals for all four assets (XRP in particular).
- Whether Gemini's sandbox lists crypto prediction markets with realistic prices.
- Which price source Gemini uses to settle its crypto contracts.

## Team
Andrew: Gemini market data, baseline math, trade/abstain logic, scoring
Chase: x402 wallet and Nansen calls, guardrails and voice approval, dashboard
