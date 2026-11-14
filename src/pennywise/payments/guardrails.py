"""Spending limits, checked in plain code before anything is signed.

Every signed authorization is written to data/payments.jsonl BEFORE it is sent and
counts toward the budgets whatever happens next. Once signed, Nansen's facilitator
may settle it even if we never see a response, so we assume the money is gone.

- Run   = this Python process. Its spend is kept in memory.
- Daily = UTC calendar day, summed from the ledger, so it survives restarts.
- Event = optional event_id; summed from the ledger.
- Pause = after MAX_CONSECUTIVE_FAILURES failed signed payments, refuse until restart.
"""

import json
from datetime import datetime, timezone

from . import control
from .config import DATA_DIR, Limits

LEDGER = DATA_DIR / "payments.jsonl"
MAX_CONSECUTIVE_FAILURES = 3

_run_spent = 0
_consecutive_failures = 0


class PaymentRefused(RuntimeError):
    """A guardrail blocked the payment. Nothing was signed; no money moved."""


def _ledger_rows() -> list[dict]:
    if not LEDGER.exists():
        return []
    rows = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _append(row: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def check(amount: int, limits: Limits, event_id: str | None, now: datetime) -> None:
    """Raise PaymentRefused if paying `amount` now would break any limit."""
    if limits.kill_switch:
        raise PaymentRefused("kill switch is on in .env (KILL_SWITCH is not 'false')")
    if control.dashboard_stopped():
        raise PaymentRefused("spending is switched off from the dashboard (data/control.json)")
    if _consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        raise PaymentRefused(f"paused after {_consecutive_failures} consecutive payment failures; restart to resume")

    signed = [r for r in _ledger_rows() if r.get("status") == "signed"]
    budgets = [("run", _run_spent, limits.per_run), ("daily", spent_today(now), limits.daily)]
    if event_id is not None:
        per_event = sum(r["amount"] for r in signed if r.get("event_id") == event_id)
        budgets.append((f"event {event_id}", per_event, limits.per_event))

    for name, spent, limit in budgets:
        if spent + amount > limit:
            raise PaymentRefused(f"{name} budget: spent {spent} + {amount} > limit {limit} (USDC base units)")


def record_signed(amount: int, url: str, event_id: str | None, payer: str, now: datetime) -> None:
    """Count the payment as spent. Called after signing, before sending."""
    global _run_spent
    _run_spent += amount
    _append({"status": "signed", "at": now.isoformat(), "amount": amount, "url": url,
             "event_id": event_id, "payer": payer})


def record_outcome(ok: bool, url: str, tx_hash: str | None, detail: str, now: datetime) -> None:
    global _consecutive_failures
    _consecutive_failures = 0 if ok else _consecutive_failures + 1
    _append({"status": "settled" if ok else "failed", "at": now.isoformat(), "url": url,
             "tx_hash": tx_hash, "detail": detail})



# --- Read-only views for the dashboard/API. ---------------------------------------


def spent_today(now: datetime) -> int:
    """USDC base units signed so far on `now`'s UTC day (what the daily budget counts)."""
    today = now.astimezone(timezone.utc).date().isoformat()
    return sum(r["amount"] for r in _ledger_rows() if r.get("status") == "signed" and r["at"][:10] == today)


def paused() -> bool:
    """True if this process stopped paying after repeated failures."""
    return _consecutive_failures >= MAX_CONSECUTIVE_FAILURES


def history() -> list[dict]:
    """One entry per signed payment, oldest first, joined with its outcome.

    status is "settled", "failed", or "pending" (signed, no outcome recorded: the
    process died mid-request, so treat it as spent).
    """
    entries: dict[tuple[str, str], dict] = {}
    for row in _ledger_rows():
        key = (row.get("at", ""), row.get("url", ""))
        if row.get("status") == "signed":
            entries[key] = {**row, "status": "pending", "tx_hash": None, "detail": None}
        elif key in entries:
            entries[key].update(status=row["status"], tx_hash=row.get("tx_hash"), detail=row.get("detail"))
    return list(entries.values())
