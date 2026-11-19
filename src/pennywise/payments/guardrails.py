"""Spending limits, checked in plain code before anything is signed.

Every signed authorization is written to data/payments.jsonl BEFORE it is sent and
counts toward the budgets whatever happens next. Once signed, Nansen's facilitator
may settle it even if we never see a response, so we assume the money is gone.

- Run   = one start of the agent (agent/runner.py calls start_run()). Its spend is kept
  in memory; a process that never starts a Run counts as one Run. A Run may set its
  own budget, but never above BUDGET_PER_RUN_USD.
- Daily = UTC calendar day, summed from the ledger, so it survives restarts.
- Market = one (asset, tier), e.g. "ETH-smart_money": its spend on the UTC day,
  summed from the ledger. Every payment names its market.
- Pause = after MAX_CONSECUTIVE_FAILURES failed signed payments, refuse until restart.
"""

import json
from datetime import datetime, timezone

from . import control
from .config import DATA_DIR, Limits

LEDGER = DATA_DIR / "payments.jsonl"
MAX_CONSECUTIVE_FAILURES = 3

_run_spent = 0
_run_limit: int | None = None  # the current Run's own budget; None = BUDGET_PER_RUN_USD
_consecutive_failures = 0


class PaymentRefused(RuntimeError):
    """A guardrail blocked the payment. Nothing was signed; no money moved."""


_STATUSES = {"signed", "settled", "failed"}


def _row_problem(row) -> str | None:
    """Why a parsed ledger row can't be trusted, or None if it's fine."""
    if not isinstance(row, dict):
        return "not a JSON object"
    if row.get("status") not in _STATUSES:
        return "missing or unknown status"
    if not isinstance(row.get("at"), str):
        return "'at' is not a string"
    amount = row.get("amount")
    if row["status"] == "signed" and (type(amount) is not int or amount < 0):
        return "signed row without a non-negative integer 'amount'"
    return None


def _read_ledger() -> tuple[list[dict], list[str]]:
    """(good rows, problems). Bad lines are skipped and described, never raised."""
    if not LEDGER.exists():
        return [], []
    try:
        data = LEDGER.read_bytes()
    except OSError as e:
        return [], [f"cannot read {LEDGER.name}: {type(e).__name__}"]
    rows, problems = [], []
    for n, raw in enumerate(data.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw.decode("utf-8"))
        except ValueError:  # covers bad UTF-8 and bad JSON
            problems.append(f"line {n}: not valid JSON")
            continue
        if problem := _row_problem(row):
            problems.append(f"line {n}: {problem}")
        else:
            rows.append(row)
    return rows, problems


def _trusted_rows() -> list[dict]:
    """Every ledger row, or PaymentRefused. A skipped line might be a signed payment,
    so spending never runs on a partial ledger."""
    rows, problems = _read_ledger()
    if problems:
        raise PaymentRefused(f"payment ledger can't be trusted ({_summary(problems)}); "
                             f"inspect and fix data/{LEDGER.name} by hand")
    return rows


def _summary(problems: list[str]) -> str:
    more = f" (+{len(problems) - 3} more)" if len(problems) > 3 else ""
    return "; ".join(problems[:3]) + more


def _spent_on(rows: list[dict], now: datetime, market: str | None = None) -> int:
    """Signed spend on `now`'s UTC day, for one market if given, else for all."""
    today = now.astimezone(timezone.utc).date().isoformat()
    return sum(
        r["amount"] for r in rows
        if r["status"] == "signed" and r["at"][:10] == today and (market is None or r.get("market") == market)
    )


def _append(row: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def check(amount: int, limits: Limits, market: str, now: datetime) -> None:
    """Raise PaymentRefused if paying `amount` now would break any limit."""
    if limits.kill_switch:
        raise PaymentRefused("kill switch is on in .env (KILL_SWITCH is not 'false')")
    if control.dashboard_stopped():
        raise PaymentRefused("spending is switched off from the dashboard (data/control.json)")
    if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        raise PaymentRefused(f"paused after {_consecutive_failures} consecutive payment failures; restart to resume")

    if not market:
        raise PaymentRefused("payment names no market, so the per-market budget can't be checked")

    rows = _trusted_rows()
    budgets = [
        ("run", _run_spent, run_budget(limits)),
        ("daily", _spent_on(rows, now), limits.daily),
        (f"market {market} (today)", _spent_on(rows, now, market), limits.per_market),
    ]

    for name, spent, limit in budgets:
        if spent + amount > limit:
            raise PaymentRefused(f"{name} budget: spent {spent} + {amount} > limit {limit} (USDC base units)")


def start_run(limit: int | None = None) -> None:
    """A new Run: its spend starts at 0. `limit` (USDC base units) may lower the per-run
    budget for this Run; it can never raise it above BUDGET_PER_RUN_USD (see run_budget)."""
    global _run_spent, _run_limit
    if limit is not None and (type(limit) is not int or limit < 0):
        raise ValueError("a Run's budget must be a whole number of USDC base units, at least 0")
    _run_spent, _run_limit = 0, limit


def run_budget(limits: Limits) -> int:
    """The current Run's budget: its own limit, capped by BUDGET_PER_RUN_USD."""
    return limits.per_run if _run_limit is None else min(_run_limit, limits.per_run)


def run_spent() -> int:
    return _run_spent


def record_signed(amount: int, url: str, market: str, payer: str, now: datetime) -> None:
    """Count the payment as spent. Called after signing, before sending."""
    global _run_spent
    _run_spent += amount
    _append({"status": "signed", "at": now.isoformat(), "amount": amount, "url": url,
             "market": market, "payer": payer})


def record_outcome(ok: bool, url: str, tx_hash: str | None, detail: str, now: datetime) -> None:
    global _consecutive_failures
    _consecutive_failures = 0 if ok else _consecutive_failures + 1
    _append({"status": "settled" if ok else "failed", "at": now.isoformat(), "url": url,
             "tx_hash": tx_hash, "detail": detail})


# --- Read-only views for the dashboard/API. ---------------------------------------
# These never raise on a bad ledger: they skip bad lines, and ledger_error() says why
# check() is refusing.


def spent_today(now: datetime) -> int:
    """USDC base units signed so far on `now`'s UTC day, skipping bad ledger lines.

    Display only: check() uses the strict read and refuses on any bad line.
    """
    return _spent_on(_read_ledger()[0], now)


def ledger_error() -> str | None:
    """Why the ledger blocks spending (unreadable file or bad lines), or None if clean."""
    problems = _read_ledger()[1]
    if not problems:
        return None
    return f"{len(problems)} ledger problem(s), spending blocked until data/{LEDGER.name} is fixed: {_summary(problems)}"


def paused() -> bool:
    """True if this process stopped paying after repeated failures."""
    return _consecutive_failures >= MAX_CONSECUTIVE_FAILURES


def history() -> list[dict]:
    """One entry per signed payment, oldest first, joined with its outcome.

    status is "settled", "failed", or "pending" (signed, no outcome recorded: the
    process died mid-request, so treat it as spent).
    """
    entries: dict[tuple[str, str], dict] = {}
    for row in _read_ledger()[0]:
        key = (row["at"], str(row.get("url", "")))
        if row["status"] == "signed":
            entries[key] = {**row, "status": "pending", "tx_hash": None, "detail": None}
        elif key in entries:
            entries[key].update(status=row["status"], tx_hash=row.get("tx_hash"), detail=row.get("detail"))
    return list(entries.values())
