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

**Contracts:** Gemini lists short 5- and 15-minute "up" contracts and daily-and-longer price-threshold contracts. We trade both: the hourly threshold ladders use the Smart Money tier (1-hour flows), and the 5- and 15-minute contracts use the Basic tier (5-minute flows).

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
- Wallet capped at about $5 USDC. Trades default to shadow mode; data purchases always go to the real Nansen API.
- Nansen responses are reduced to numbers before the AI sees them, so text inside a response cannot give it instructions.

## Scoring

Every decision, payment, and trade is logged. After a market settles, we compare the baseline forecast, the informed forecast, and the market price, and calculate what each paid tier cost versus how much it improved the forecast. Results are counted per event, since contracts in one event share an outcome.

## Hackathon

Entered in the **Agentic Payments and AI** track of the University Blockchain Conference hackathon. Submission deadline: Fri Nov 20, 12:00 PM CST.

## Verified so far

- x402 payments to Nansen work end to end: USDC on Base, gasless for us (tested Nov 14: $0.01 Basic and $0.05 Smart Money, both for ETH).
- Smart Money (`smart-money/netflow`) returns a row for native ETH with a 1h net flow and trader count.
- Basic (`tgm/flow-intelligence`, 5m) for native ETH is coarse: smart-trader flow came back null and whale flow 0; only exchange net flow had a value.

## Still unverified

- Whether Nansen's paid data improves forecasts enough to cover its cost (Basic looks weak for native ETH).
- SOL on either tier (Solana handles the native-token placeholder differently).
- Whether `trader_count` from Smart Money covers the last hour or a longer window.
- Nansen covers BTC only through wrapped tokens and XRP not at all, so both stay baseline-only.
- Whether Gemini's sandbox lists crypto prediction markets with realistic prices.
- Which price source Gemini uses to settle its crypto contracts.

## Team
Andrew: Gemini market data, baseline math, trade/abstain logic, scoring

Chase: x402 wallet and Nansen calls, guardrails and voice approval, dashboard

## INTEGRATE LLM

The payment side fits the track well, but the agent's decisions are currently plain math: no LLM decides anything, and the narrator isn't built yet. This section is the plan for putting an LLM in the loop without weakening any safety limit.

### Where we stand against the track

| Track item | Status |
|---|---|
| Agent pays per request (x402) | **Done.** Real USDC on Base, settled on-chain |
| Budgets and allowlists | **Done.** Per-call cap, run and daily budgets, host and endpoint allowlist, price pinning, kill switch, pause after failures |
| Human approval for large transactions | **Missing.** Voice approval is planned but not built |
| LLMs that read from and act on the blockchain safely | **Missing.** No LLM is in the loop |
| Marketplace or service that agents pay for | Not attempted (optional, since the track only says to "aim" for these) |
| Document the decision loop and safety limits | Partly done here; needs a proper write-up |

### 1. The LLM is the agent; code is the guardrail

The agent cycle becomes a tool-use loop. The LLM gets tools like these:

- `scan_markets`: the Gemini snapshot plus baseline odds
- `estimate_data_value(asset, tier)`: the existing value-of-information math, given as advice
- `buy_nansen_data(asset, tier)`: calls `get_signals`, so it goes through `pay()` and every guardrail
- `wallet_status`: balance, spent today, budget left
- `propose_trade(event, side)`: code checks the edge, picks the size, and enforces one trade per Event
- `request_approval(...)`: see section 2

The LLM decides what to buy and why. Code still decides whether a payment can be signed. Every time the LLM goes against the value-of-information check is logged, so scoring can compare whether the LLM or the math rule spent money better.

This changes the LLM's role. It used to only explain decisions and veto or shrink trades. Now it may trigger purchases, but only through tools that enforce every limit, and it can never raise or bypass a limit. The current deterministic cycle stays as a fallback mode (for example, if the LLM API is down during the demo).

### 2. Human approval for big spends

An approval step in `payments/guardrails.py`, before signing. Any payment above a set amount (for example a $0.05 Smart Money call, or anything once daily spend passes 50%) waits until a human approves it from the dashboard or by voice. If no one approves it, it is refused. It lives in `payments/`, not in the LLM tools, so the LLM cannot skip it.

### 3. The LLM reads the chain safely

- A tool that confirms each x402 payment on Base over RPC: the USDC transfer to Nansen's pay-to address actually happened, for the right amount.
- The wallet's USDC balance as a tool.
- The existing prompt-injection defence: Nansen data reaches the LLM only as numbers, so text inside a response cannot give it instructions.

### 4. Narrator

The LLM explains each cycle in a few sentences ("bought ETH Smart Money because…, skipped SOL Basic because…"), shown on the dashboard. It reads only the decision log, which holds numbers and fixed labels.

### 5. Stretch: sell our forecasts over x402

Put PennyWise's informed probabilities behind our own x402 paywall, on Base Sepolia testnet. The agent then both buys data and sells insight, which covers the track's marketplace objective. Only if sections 1–4 are done first.
