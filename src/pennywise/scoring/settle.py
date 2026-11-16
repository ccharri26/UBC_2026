"""Settler: write one OutcomeRow per settled Event in the decision log to data/outcomes.jsonl.

Only Events we logged are checked, and only once they should have expired
(row time + mins_left, plus a short grace period). Each is looked up by ticker
(GET /v1/prediction-markets/events/{ticker}); Events Gemini hasn't settled yet are
left for the next run. Events already in outcomes.jsonl are skipped, so running
this repeatedly is safe. Stub rows count too: their readings are fake, but the
Events and outcomes are real.

Run: uv run python -m pennywise.scoring.settle
"""

import time
from datetime import datetime, timedelta, timezone

import httpx

from pennywise.decisions import (
    ContractResult,
    OutcomeRow,
    RecordError,
    append_outcome,
    read_decisions,
    settled_events,
)
from pennywise.markets.gemini import EVENTS_URL, get_json

# Gemini usually settles a few seconds after expiry; wait a bit before asking.
GRACE = timedelta(minutes=1)
# Pause between lookups so a big backlog doesn't get rate-limited.
PAUSE_SECONDS = 0.2


def expired_events(now: datetime) -> dict[str, tuple[str, datetime]]:
    """Logged Events whose expiry has passed: {event ticker: (asset, expiry)}.

    Expiry = row time + mins_left. Different cycles agree to within seconds; keep the latest.
    """
    expiries: dict[str, tuple[str, datetime]] = {}
    for row in read_decisions().rows:
        for q in row.quotes:
            expiry = row.at + timedelta(minutes=q.mins_left)
            if q.event not in expiries or expiry > expiries[q.event][1]:
                expiries[q.event] = (row.asset, expiry)
    return {e: v for e, v in expiries.items() if v[1] + GRACE <= now}


def parse_outcome(event: dict, asset: str) -> OutcomeRow | None:
    """An OutcomeRow from Gemini's Event JSON, or None if it isn't fully settled yet."""
    if event.get("status") != "settled":
        return None
    results = []
    for c in event.get("contracts", []):
        side = c.get("resolutionSide")
        if side not in ("yes", "no"):
            return None  # a Contract without a result yet: try again next run
        results.append(ContractResult(strike=float(c["strike"]["value"]), yes=side == "yes"))
    if not results:
        return None
    settled_at = event.get("resolvedAt") or event["expiryDate"]
    price = (event.get("settlement") or {}).get("value")
    return OutcomeRow(
        event=event["ticker"],
        asset=asset,
        settled_at=datetime.fromisoformat(settled_at.replace("Z", "+00:00")),
        settle_price=float(price) if price is not None else None,
        results=tuple(sorted(results, key=lambda r: r.strike)),
    )


def settle(now: datetime | None = None) -> dict[str, int]:
    """Look up every expired, unsettled logged Event and record the settled ones."""
    now = now or datetime.now(timezone.utc)
    done = settled_events()
    pending = {e: v for e, v in expired_events(now).items() if e not in done}
    counts = {"checked": 0, "settled": 0, "not_yet": 0, "errors": 0}
    for i, (event, (asset, _)) in enumerate(sorted(pending.items(), key=lambda kv: kv[1][1])):
        if i:
            time.sleep(PAUSE_SECONDS)
        counts["checked"] += 1
        try:
            outcome = parse_outcome(get_json(f"{EVENTS_URL}/{event}"), asset)
        except (httpx.HTTPError, KeyError, ValueError, TypeError, RecordError) as e:
            print(f"  {event}: lookup failed ({type(e).__name__}), will retry next run")
            counts["errors"] += 1
            continue
        if outcome is None:
            counts["not_yet"] += 1
            continue
        append_outcome(outcome)
        counts["settled"] += 1
    return counts


if __name__ == "__main__":
    c = settle()
    print(
        f"checked {c['checked']} expired Events: {c['settled']} settled and recorded, "
        f"{c['not_yet']} not settled yet, {c['errors']} lookup errors"
    )
