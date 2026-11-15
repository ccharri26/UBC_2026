"""Paid Nansen results saved to data/nansen_cache.json, so they survive restarts
and other processes (the API/dashboard) can see what the agent bought.

Live (paid) results only: stub results never touch disk, so fake numbers can't be
mistaken for paid ones. The file holds numbers only (NansenSignals), never raw
Nansen text.

Fail open: an unreadable file or entry is ignored, which at worst means paying
again; the payment guardrails still cap that.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from pennywise.payments.config import DATA_DIR

from .bodies import NATIVE_TOKENS
from .endpoints import Tier
from .signals import NansenSignals

CACHE_FILE = DATA_DIR / "nansen_cache.json"

# Same shape as client._cache, minus the stub flag: slot -> (expires_at, signals).
# slot is (asset, tier) or (asset, tier, hour_start).
Slot = tuple
Entries = dict[Slot, tuple[datetime, NansenSignals]]


def _to_json(slot: Slot, expires_at: datetime, s: NansenSignals) -> dict:
    signals = {**s.__dict__, "tier": s.tier.value, "fetched_at": s.fetched_at.isoformat()}
    return {
        "asset": slot[0],
        "tier": slot[1].value,
        "hour": slot[2].isoformat() if len(slot) == 3 else None,
        "expires_at": expires_at.isoformat(),
        "signals": signals,
    }


def _from_json(row: dict) -> tuple[Slot, datetime, NansenSignals]:
    tier = Tier(row["tier"])
    slot = (row["asset"], tier) if row["hour"] is None else (row["asset"], tier, datetime.fromisoformat(row["hour"]))
    raw = dict(row["signals"])
    # Numbers only: the file is outside our control, so a string or bool sneaking in
    # here would reach the forecast (and the LLM) as if Nansen had sent it.
    for name, value in raw.items():
        if name in ("asset", "tier", "fetched_at"):
            continue
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError(f"{name} is not a number")
        if name.endswith("_count") and value is not None and (not float(value).is_integer() or value < 0):
            raise ValueError(f"{name} is not a whole number")
    if raw.get("asset") not in NATIVE_TOKENS:
        raise ValueError("unknown asset")
    raw["tier"] = Tier(raw["tier"])
    raw["fetched_at"] = datetime.fromisoformat(raw["fetched_at"])
    signals = NansenSignals(**raw)  # __post_init__ re-validates the numbers
    if signals.asset != slot[0] or signals.tier != tier:
        raise ValueError("entry key does not match its signals")
    return slot, datetime.fromisoformat(row["expires_at"]), signals


def load(now: datetime) -> Entries:
    """Unexpired entries from disk. Missing or broken file -> {}; broken entries skipped."""
    try:
        rows = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(rows, list):
        return {}
    entries: Entries = {}
    for row in rows:
        try:
            slot, expires_at, signals = _from_json(row)
        except (KeyError, TypeError, ValueError):
            continue
        if now < expires_at:
            entries[slot] = (expires_at, signals)
    return entries


def save(slot: Slot, expires_at: datetime, signals: NansenSignals, now: datetime) -> None:
    """Add one entry, dropping expired ones. Atomic: readers never see a half-written file.

    Last writer wins if two agent processes save at the same instant; the loser's
    entry is just re-bought later, within the payment budgets.
    """
    entries = load(now)
    entries[slot] = (expires_at, signals)
    rows = [_to_json(k, exp, s) for k, (exp, s) in entries.items()]
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CACHE_FILE.parent, prefix="nansen_cache.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=1)
        os.replace(tmp, CACHE_FILE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
