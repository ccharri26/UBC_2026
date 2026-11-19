"""Human approval for purchases at or above the Approval Threshold.

require() runs before a purchase: inside pay() for live payments (before the lock and
again implicitly, since pay() re-checks every guardrail after approval), and in
nansen's stub path so the demo works without money. It blocks until a human answers
on the dashboard, for at most WAIT_SECONDS:
- approved -> return, the purchase goes ahead (guardrails still apply).
- denied   -> PaymentRefused; the agent carries on with the baseline.
- no answer -> PaymentRefused AND the dashboard kill switch turns on (all spending
               and trading stop until a human turns it back off).

Threshold:
- APPROVAL_CEILING_USD in .env (hand-edited): the highest threshold the dashboard may
  set. Missing or malformed -> 0, so every purchase needs approval (fail closed).
- data/approval.json {"threshold": units}, written by the dashboard. Missing -> the
  ceiling. Unreadable or out of range -> 0. Raising it needs confirm=True.

Requests live as files in data/approvals/ so the agent and the API can be separate
processes: <id>.json is the request (written by the agent), <id>.answer.json is the
answer, created exclusively ("x" mode), so whoever answers first (the human, or the
agent's timeout) wins and the other side sees that answer.
"""

import json
import os
import secrets
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from . import control
from .config import DATA_DIR, env, usd_to_units
from .guardrails import PaymentRefused

SETTINGS_FILE = DATA_DIR / "approval.json"
REQUESTS_DIR = DATA_DIR / "approvals"
WAIT_SECONDS = 90
POLL_SECONDS = 0.5

Answer = Literal["approved", "denied", "expired"]
_ANSWERS = ("approved", "denied", "expired")


class ApprovalError(ValueError):
    """A dashboard request that can't be applied (bad value, unknown or answered request)."""


# --- threshold ---------------------------------------------------------------------


def ceiling() -> int:
    """APPROVAL_CEILING_USD in USDC base units; 0 if missing or malformed (fail closed)."""
    raw = env("APPROVAL_CEILING_USD")
    if raw is None:
        return 0
    try:
        units = usd_to_units(raw)
    except ValueError:
        return 0
    return max(units, 0)


def ceiling_problem() -> str | None:
    """Why the ceiling is 0 by accident, for the dashboard; None if it's set and valid."""
    raw = env("APPROVAL_CEILING_USD")
    if raw is None:
        return "APPROVAL_CEILING_USD is not set in .env, so every purchase needs approval"
    try:
        usd_to_units(raw)
    except ValueError:
        return f"APPROVAL_CEILING_USD is not a number ({raw!r}), so every purchase needs approval"
    return None


def threshold() -> int:
    """Purchases at or above this many USDC base units need approval."""
    top = ceiling()
    try:
        raw = SETTINGS_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return top
    except OSError:
        return 0
    try:
        value = json.loads(raw).get("threshold")
    except (ValueError, AttributeError):
        return 0
    if type(value) is not int or not 0 <= value <= top:
        return 0
    return value


def set_threshold(units: int, confirm: bool = False) -> None:
    """Save the dashboard's threshold. Lowering it is free; raising it needs confirm."""
    if type(units) is not int or units < 0:
        raise ApprovalError("threshold must be a whole number of USDC base units, at least 0")
    top = ceiling()
    if units > top:
        raise ApprovalError(f"threshold {units} is above the ceiling {top}; raise APPROVAL_CEILING_USD in .env by hand")
    if units > threshold() and not confirm:
        raise ApprovalError("raising the threshold lets more purchases through without asking; send confirm=true")
    _write_json(SETTINGS_FILE, {"threshold": units})


def needs_approval(amount: int) -> bool:
    return amount >= threshold()


# --- requests ----------------------------------------------------------------------


def require(amount: int, market: str, *, stub: bool) -> None:
    """Block until a human approves this purchase, if it needs approval. Raises PaymentRefused otherwise."""
    if control.kill_switch_on():
        raise PaymentRefused("kill switch is on")
    if not needs_approval(amount):
        return
    now = datetime.now(timezone.utc)
    request_id = secrets.token_hex(16)
    _write_json(REQUESTS_DIR / f"{request_id}.json", {
        "id": request_id,
        "market": market,
        "amount": amount,
        "stub": stub,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=WAIT_SECONDS)).isoformat(),
    })
    print(f"  approval needed: {market} ${amount / 1_000_000:.2f}{' (stub)' if stub else ''}; "
          f"waiting up to {WAIT_SECONDS}s for the dashboard")

    deadline = time.monotonic() + WAIT_SECONDS
    answer = _read_answer(request_id)
    while answer is None and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        answer = _read_answer(request_id)
    if answer is None:
        _answer(request_id, "expired")  # if a human answered at the last moment, theirs wins
        answer = _read_answer(request_id) or "expired"

    if answer == "approved":
        print("  approved")
        return
    if answer == "denied":
        raise PaymentRefused(f"denied on the dashboard: {market} ${amount / 1_000_000:.2f}")
    control.set_spending(on=False)
    raise PaymentRefused(f"no answer within {WAIT_SECONDS}s for {market}; kill switch turned on")


def pending() -> list[dict]:
    """Unanswered, unexpired requests, oldest first. Never raises on a bad file."""
    now = datetime.now(timezone.utc)
    out = []
    try:
        files = sorted(REQUESTS_DIR.glob("*.json"))
    except OSError:
        return []
    for f in files:
        if f.name.endswith(".answer.json"):
            continue
        req = _read_request(f.stem)
        if req is None or _read_answer(req["id"]) is not None:
            continue
        if datetime.fromisoformat(req["expires_at"]) <= now:
            continue
        out.append(req)
    return sorted(out, key=lambda r: r["created_at"])


def answer(request_id: str, approve: bool) -> Answer:
    """Record a human's answer. Raises ApprovalError if unknown, expired or already answered."""
    req = _read_request(request_id)
    if req is None:
        raise ApprovalError("no such approval request")
    if datetime.fromisoformat(req["expires_at"]) <= datetime.now(timezone.utc):
        raise ApprovalError("this approval request has expired")
    value: Answer = "approved" if approve else "denied"
    if not _answer(request_id, value):
        raise ApprovalError(f"already answered: {_read_answer(request_id)}")
    return value


# --- files -------------------------------------------------------------------------


def _valid_id(request_id: str) -> bool:
    return len(request_id) == 32 and all(c in "0123456789abcdef" for c in request_id)


def _read_request(request_id: str) -> dict | None:
    if not _valid_id(request_id):
        return None
    try:
        req = json.loads((REQUESTS_DIR / f"{request_id}.json").read_text(encoding="utf-8"))
        datetime.fromisoformat(req["expires_at"])
        datetime.fromisoformat(req["created_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(req, dict) or req.get("id") != request_id:
        return None
    if type(req.get("amount")) is not int or not isinstance(req.get("market"), str):
        return None
    return req


def _read_answer(request_id: str) -> Answer | None:
    try:
        value = json.loads((REQUESTS_DIR / f"{request_id}.answer.json").read_text(encoding="utf-8")).get("answer")
    except FileNotFoundError:
        return None
    except (OSError, ValueError, AttributeError):
        return "expired"  # an unreadable answer is never an approval
    return value if value in _ANSWERS else "expired"


def _answer(request_id: str, value: Answer) -> bool:
    """Create the answer file exclusively. False if an answer already exists."""
    if not _valid_id(request_id):
        return False
    path = REQUESTS_DIR / f"{request_id}.answer.json"
    payload = json.dumps({"answer": value, "at": datetime.now(timezone.utc).isoformat()})
    try:
        # Write to a temp file, then hard-link it into place: atomic, and fails if the answer exists,
        # so a reader never sees a half-written answer.
        fd, tmp = tempfile.mkstemp(dir=REQUESTS_DIR, prefix="answer.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.link(tmp, path)
        finally:
            Path(tmp).unlink(missing_ok=True)
    except FileExistsError:
        return False
    return True


def _write_json(path: Path, data: dict) -> None:
    """Atomic write (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.stem + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
