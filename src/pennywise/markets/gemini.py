"""Pull active Gemini crypto prediction Events and print their Contracts.

Run: uv run python -m pennywise.markets.gemini
"""

from datetime import datetime, timezone

import httpx

EVENTS_URL = "https://api.gemini.com/v1/prediction-markets/events"
ASSETS = ("BTC", "ETH", "SOL", "XRP")
SERIES = ("05M", "15M", "1H")  # 5-minute, 15-minute, hourly


def fetch_active_events() -> list[dict]:
    """Every active crypto Event, following pagination."""
    events, offset = [], 0
    while True:
        resp = httpx.get(
            EVENTS_URL,
            params={"status": "active", "category": "crypto", "limit": 500, "offset": offset},
            timeout=10,
        )
        resp.raise_for_status()
        body = resp.json()
        events += body["data"]
        offset += len(body["data"])
        if not body["data"] or offset >= body["pagination"]["total"]:
            return events


def wanted(event: dict) -> bool:
    return any(event.get("series") == asset + s for asset in ASSETS for s in SERIES)


def parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fmt_price(s: str | None) -> str:
    return f"{float(s):.2f}" if s is not None else "  - "


def fmt_strike(contract: dict) -> str:
    strike = contract.get("strike") or {}
    value = strike.get("value")
    if value is None:
        return "(not set yet)"
    # "above" pays if price >= strike; "reference" (UP) pays if price ends above the start price
    label = "UP from" if strike.get("type") == "reference" else ">="
    return f"{label} {float(value):,.4f}".rstrip("0").rstrip(".")


def print_event(event: dict, now: datetime) -> None:
    expires = parse_time(event["expiryDate"])
    mins_left = (expires - now).total_seconds() / 60
    print(
        f"\n{event['ticker']:<18} {event['series']:<7} "
        f"expires {expires:%H:%M} UTC ({mins_left:.0f}m left)   "
        f"index: {event.get('source', '?')}"
    )
    print(f"  {'strike':<24} {'bid':>5} {'ask':>5} {'last':>5}  state")
    contracts = sorted(
        event["contracts"],
        key=lambda c: float((c.get("strike") or {}).get("value") or 0),
    )
    for c in contracts:
        p = c.get("prices") or {}
        print(
            f"  {fmt_strike(c):<24} {fmt_price(p.get('bestBid')):>5} "
            f"{fmt_price(p.get('bestAsk')):>5} {fmt_price(p.get('lastTradePrice')):>5}  "
            f"{c.get('marketState', '?')}"
        )


def main() -> None:
    now = datetime.now(timezone.utc)
    events = sorted(
        (e for e in fetch_active_events() if wanted(e)),
        key=lambda e: (e["series"][:3], e["expiryDate"]),
    )
    print(f"{len(events)} active events at {now:%Y-%m-%d %H:%M} UTC")
    for event in events:
        print_event(event, now)


if __name__ == "__main__":
    main()
