# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**PennyWise**: a hackathon agent (University Blockchain Conference, Agentic Payments and AI track; deadline Fri Nov 20 2026, 12:00 PM CST) that scans Gemini crypto prediction markets (BTC, ETH, SOL, XRP), decides whether paid Nansen on-chain data is worth buying for a contract, pays for it with USDC on Base via x402, and then decides whether to trade. `README.md` is the source of truth for design; no code has been written yet, so there are no build/test commands to record. Add them here once a stack is chosen.

### Decision pipeline

free baseline probability → value-of-information check → skip / Basic (~$0.01) / Smart Money (~$0.05) → pay via x402 → update probability → trade or pass → score after settlement.

- Paid data is bought only for **ETH and SOL**. Nansen doesn't cover XRP and covers BTC at most through wrapped tokens, so BTC and XRP contracts use the baseline-only path unless a paid test of wrapped BTC proves useful.
- Target every crypto horizon Gemini lists: the **5- and 15-minute "up" contracts** and the **hourly-and-longer price-threshold ladders** (Gemini files ladders expiring hours to days out under the `1H` series). The value-of-information check decides per horizon whether Nansen data is fast enough to be worth buying; short horizons will often be baseline-only.
- One Nansen call per asset serves every contract on that asset, so cache and share purchases across contracts.
- Trades run in **shadow mode** (simulated) by default; Gemini sandbox orders are opt-in.
- Scoring compares baseline vs. informed forecast vs. market price, and tier cost vs. forecast improvement. Count results **per event**, because contracts in one event share an outcome.

### Layout

Python + FastAPI, packaged as `src/pennywise/`, with one folder per step of the decision flow and each folder owned by one person: `markets/` (Gemini client), `forecast/` (baseline + informed update), `info/` (value-of-information: skip/Basic/Smart Money), `nansen/` (calls reduced to numbers), `payments/` (x402 wallet; **guardrails live here** so signing is impossible without passing every limit), `trading/`, `scoring/`, `narrator/` (LLM explain/veto), `api/` (thin FastAPI layer; the agent must run without HTTP). `frontend/` is the separate dashboard app. `data/` is git-ignored local state (decision log, Nansen response cache). There is no `tests/` folder.

### Safety invariants (must hold in any implementation)

- Every spending limit is plain code that runs **before** a payment is signed. The LLM only explains decisions and can veto or shrink a trade; it must never be able to raise spend or bypass a limit.
- Payments only to the official Nansen host (`api.nansen.ai`) and its listed endpoints, to the expected pay-to address, in USDC on Base.
- Hard cap of $0.05 per call, plus per-market, per-run and daily budgets; a price-drift check against `/.well-known/x402`; a kill switch; a pause after repeated payment failures.
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
