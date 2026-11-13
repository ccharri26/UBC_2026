# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**PennyWise**: a hackathon agent (University Blockchain Conference, Agentic Payments and AI track; deadline Fri Nov 20 2026, 12:00 PM CST) that scans Gemini crypto prediction markets (BTC, ETH, SOL, XRP), decides whether paid Nansen on-chain data is worth buying for a contract, pays for it with USDC on Base via x402, and then decides whether to trade. `README.md` is the source of truth for design; no code has been written yet, so there are no build/test commands to record. Add them here once a stack is chosen.

### Decision pipeline

free baseline probability → value-of-information check → skip / Basic (~$0.01) / Smart Money (~$0.05) → pay via x402 → update probability → trade or pass → score after settlement.

- Target **daily-and-longer price-threshold contracts**, not the 5/15-minute "up" contracts (Nansen flow data is too slow for those).
- One Nansen call per asset serves every contract on that asset, so cache and share purchases across contracts.
- Trades run in **shadow mode** (simulated) by default; Gemini sandbox orders are opt-in.
- Scoring compares baseline vs. informed forecast vs. market price, and tier cost vs. forecast improvement. Count results **per event**, because contracts in one event share an outcome.

### Safety invariants (must hold in any implementation)

- Every spending limit is plain code that runs **before** a payment is signed. The LLM only explains decisions and can veto or shrink a trade; it must never be able to raise spend or bypass a limit.
- Payments only to the official Nansen host (`api.nansen.ai`) and its listed endpoints, to the expected pay-to address, in USDC on Base.
- Hard cap of $0.05 per call, plus per-market, per-run and daily budgets; a price-drift check against `/.well-known/x402`; a kill switch; a pause after repeated payment failures.
- Reduce Nansen responses to numbers before the LLM sees them (prompt-injection defence).
- Development defaults: shadow mode and a local mock x402 seller. The real wallet holds about $5 USDC at most.

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
