# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**PennyWise**: a hackathon agent (University Blockchain Conference, Agentic Payments and AI track; deadline Fri Nov 20 2026, 12:00 PM CST) that scans Gemini crypto prediction markets (BTC, ETH, SOL, XRP), decides whether paid Nansen on-chain data is worth buying for a contract, pays for it with USDC on Base via x402, and then decides whether to trade. `README.md` is the source of truth for design.

### Commands

Run from the repo root (Python via uv). Set `NANSEN_STUB=true` in `.env` to get fake Nansen data with no spending.

- `uv run uvicorn pennywise.api.app:app --reload`: API + dashboard. Dashboard at http://127.0.0.1:8000/, API docs at http://127.0.0.1:8000/docs.
- `uv run python -m pennywise.nansen [--asset ETH|SOL] [--horizon 05M|15M|1H]`: signals via `get_signals` (refuses to spend unless stub mode is on or `--live` is passed).
- `uv run python -m pennywise.payments --dry-run [--tier basic|smart_money] [--asset ETH|SOL]`: check guardrails and signing without paying. `--live` makes a real payment.
- `uv run python -m pennywise.markets.gemini`: free scan of active Gemini Events with baseline odds and the buy/skip decision per (asset, tier).
- `uv run python -m pennywise.agent.cycle`: one deterministic agent cycle (snapshot → Nansen → forecast → shadow trades → `data/decisions.jsonl`). Keep `NANSEN_STUB=true` unless a live run is intended.

### LLM integration (planned, see README "INTEGRATE LLM")

The LLM becomes the agent: a tool-use loop where it calls tools (`scan_markets`, `estimate_data_value`, `buy_nansen_data`, `wallet_status`, `propose_trade`, `request_approval`) and decides what to buy and trade. Tools are thin wrappers over existing code, so every purchase still goes through `get_signals` → `pay()` and every guardrail; trade size and the one-trade-per-Event rule stay in code. Log whenever the LLM goes against the value-of-information check. Keep the deterministic `agent/cycle.py` as a fallback mode. Also planned: human approval for large spends (in `payments/`), an on-chain check that each x402 payment settled, a narrator over the decision log, and (stretch) selling our forecasts over x402 on Base Sepolia.

### Decision pipeline

free baseline probability → value-of-information check → skip / Basic (~$0.01) / Smart Money (~$0.05) → pay via x402 → update probability → trade or pass → score after settlement.

- Paid data is bought only for **ETH and SOL**. Nansen doesn't cover XRP and covers BTC at most through wrapped tokens, so BTC and XRP contracts use the baseline-only path unless a paid test of wrapped BTC proves useful. **For the MVP, buy for ETH only**: SOL is untested on both tiers.
- Target every crypto horizon Gemini lists: the **5- and 15-minute "up" contracts** and the **hourly-and-longer price-threshold ladders** (Gemini files ladders expiring hours to days out under the `1H` series). Each horizon has one paid tier: **Smart Money** (`smart-money/netflow`, 1h window) for 1H ladders, **Basic** (`tgm/flow-intelligence`, 5m window) for 5M and 15M contracts (Nansen has no 15m window). The value-of-information check still decides skip vs. buy.
- One Nansen call per asset serves every contract on that asset, so cache and share purchases across contracts.
- Trades run in **shadow mode** (simulated) by default; Gemini sandbox orders are opt-in.
- Scoring compares baseline vs. informed forecast vs. market price, and tier cost vs. forecast improvement. Count results **per event**, because contracts in one event share an outcome.

### Layout

Python + FastAPI, packaged as `src/pennywise/`, with one folder per step of the decision flow and each folder owned by one person: `markets/` (Gemini client), `forecast/` (baseline + informed update), `info/` (value-of-information: skip/Basic/Smart Money), `nansen/` (calls reduced to numbers), `payments/` (x402 wallet; **guardrails live here** so signing is impossible without passing every limit), `trading/`, `scoring/`, `narrator/` (LLM explanations of the decision log), `agent/` (the cycle that ties the steps together; the planned LLM tool loop lives here too), `decisions/` (shared decision log + outcomes records; agent writes decisions, scoring writes outcomes), `api/` (thin FastAPI layer; the agent must run without HTTP). `frontend/` is the dashboard: plain HTML + JS for now, meant to be swapped for React later, so all API calls stay in `frontend/api.js` and the UI talks only to `/api`, never to `data/`. `data/` is git-ignored local state: `payments.jsonl` (payment ledger; the daily budget is summed from it), `control.json` (dashboard kill switch), `nansen_cache.json` (paid Nansen results, numbers only; survives restarts and lets the API show live signals; stub results never written), `decisions.jsonl` (one row per (asset, tier) purchase decision per agent cycle, with its quotes and at most one trade per Event; `stub` marks fake readings), `outcomes.jsonl` (one row per settled Event, joined on the Event ticker). Log rows hold numbers and fixed labels only, so the narrator can read them. Code never writes `.env`: it is hand-edited config holding the wallet key, and `KILL_SWITCH=true` there is a lock the dashboard cannot override. There is no `tests/` folder.

### Safety invariants (must hold in any implementation)

- Every spending limit is plain code that runs **before** a payment is signed. The LLM may trigger purchases and propose trades only through tools that call that code; it must never be able to raise a limit, bypass a guardrail, pick a trade size, or skip human approval.
- Human approval for large spends (planned, not built yet) must be enforced in `payments/` before signing, not in the LLM tools.
- Payments only to the official Nansen host (`api.nansen.ai`) and its listed endpoints, to the expected pay-to address, in USDC on Base.
- Hard cap of $0.05 per call, plus per-market (one (asset, tier), e.g. `ETH-smart_money`, per UTC day), per-run and daily budgets; a price-drift check (every fresh 402 offer must match the price pinned in `payments/expected.py`; `/.well-known/x402` lists no prices); a kill switch; a pause after repeated payment failures.
- Reduce Nansen responses to numbers before the LLM sees them (prompt-injection defence).
- Trades default to shadow mode. All x402 payments go to the real Nansen API. The wallet holds about $5 USDC at most.

### Ownership

Andrew: Gemini market data, baseline math, trade/abstain logic, scoring. Chase: x402 wallet and Nansen calls, guardrails and voice approval, dashboard.

### Open questions (from README)

Nansen signal quality per asset (especially XRP); whether Gemini's sandbox lists crypto prediction markets with realistic prices; which price source Gemini uses to settle crypto contracts.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `ccharri26/UBC_2026`, managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` + `docs/adr/` at the repo root (created lazily, so don't flag them as missing). See `docs/agents/domain.md`.
