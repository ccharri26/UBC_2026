"""Pull active Gemini crypto prediction Events: fetch_snapshot() for the agent, main() to print.

Run: uv run python -m pennywise.markets.gemini
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from pennywise.forecast.baseline import blend, minute_volatility, prob_above, typical_move
from pennywise.info.value import Quote, decide
from pennywise.nansen import Horizon, Tier, tier_of
from pennywise.trading.edge import call, edges

EVENTS_URL = "https://api.gemini.com/v1/prediction-markets/events"
# Contracts settle on Lukka reference rates, which Gemini doesn't publish via API.
# Gemini's own spot price is the closest free stand-in.
PRICEFEED_URL = "https://api.gemini.com/v1/pricefeed"
# 5-minute candles cover the last ~7 days. 1-minute candles overstate movement by
# ~45% (tick-by-tick noise bouncing between bid and ask), so we don't use them.
CANDLES_URL = "https://api.gemini.com/v2/candles/{symbol}/5m"
CANDLE_MINUTES = 5
ASSETS = ("BTC", "ETH", "SOL", "XRP")
SERIES = ("05M", "15M", "1H")  # 5-minute, 15-minute, hourly
WIDE_SPREAD = 0.10  # spreads wider than this are flagged as untradeable


def get_json(url: str, params: dict | None = None, attempts: int = 3):
    """GET with a 30s timeout, retrying timeouts: Gemini's public API sometimes stalls."""
    for attempt in range(attempts):
        try:
            resp = httpx.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            if attempt == attempts - 1:
                raise


def fetch_active_events() -> list[dict]:
    """Every active crypto Event, following pagination."""
    events, offset = [], 0
    while True:
        body = get_json(
            EVENTS_URL,
            {"status": "active", "category": "crypto", "limit": 500, "offset": offset},
        )
        events += body["data"]
        offset += len(body["data"])
        if not body["data"] or offset >= body["pagination"]["total"]:
            return events


def fetch_spot_prices() -> dict[str, float]:
    """Current Gemini spot price per asset, e.g. {"BTC": 68346.98, ...}."""
    pairs = {p["pair"]: float(p["price"]) for p in get_json(PRICEFEED_URL)}
    return {asset: pairs[asset + "USD"] for asset in ASSETS if asset + "USD" in pairs}


def fetch_minute_volatility(asset: str) -> float:
    """Typical move per minute over the last ~7 days, recent candles weighted more."""
    candles = get_json(CANDLES_URL.format(symbol=asset.lower() + "usd"))
    # Each candle is [time_ms, open, high, low, close, volume], newest first.
    closes = [float(c[4]) for c in sorted(candles)]
    return minute_volatility(closes, CANDLE_MINUTES)


def asset_of(event: dict) -> str:
    return next(a for a in ASSETS if event["series"].startswith(a))


def wanted(event: dict) -> bool:
    return any(event.get("series") == asset + s for asset in ASSETS for s in SERIES)


def has_strikes(event: dict) -> bool:
    """False for 5/15-minute windows that haven't opened: their start price isn't set yet."""
    return all((c.get("strike") or {}).get("value") is not None for c in event["contracts"])


def parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def to_float(s: str | None) -> float | None:
    return float(s) if s is not None else None


def fmt_price(x: float | None) -> str:
    return f"{x:.2f}" if x is not None else "  - "


def costs(bid: float | None, ask: float | None) -> tuple[float | None, float | None, float | None]:
    """(yes_cost, no_cost, spread) for buying instantly.

    Buying Yes pays the Yes ask. Buying No means taking the other side of the
    best Yes bid, so it costs 1 - bid. Spread is ask - bid: the pass zone.
    """
    yes_cost = ask
    no_cost = 1 - bid if bid is not None else None
    # Round to cents: float subtraction gives 0.0999.. or 0.1000..01 for a 10-cent spread.
    spread = round(ask - bid, 2) if bid is not None and ask is not None else None
    return yes_cost, no_cost, spread


def flag(spread: float | None) -> str:
    if spread is None:
        return "one-sided"  # nobody quoting one side: can only bet the other way
    if spread > WIDE_SPREAD:
        return "wide"
    return ""


def fmt_strike(contract: dict) -> str:
    strike = contract.get("strike") or {}
    value = strike.get("value")
    if value is None:
        return "(not set yet)"
    # "above" pays if price >= strike; "reference" (UP) pays if price ends above the start price
    label = "UP from" if strike.get("type") == "reference" else ">="
    return f"{label} {float(value):,.4f}".rstrip("0").rstrip(".")


def distance(contract: dict, spot: float | None) -> float | None:
    """How far the strike is from the current price: + means price must rise to reach it."""
    value = (contract.get("strike") or {}).get("value")
    if value is None or spot is None:
        return None
    return (float(value) - spot) / spot


def fmt_pct(x: float | None) -> str:
    return f"{x:+.2%}" if x is not None else "  -   "


def fmt_edge(x: float | None) -> str:
    return f"{x:+.2f}" if x is not None else "  -  "


def evaluate(
    contract: dict, spot: float | None, mins_left: float, minute_vol: float | None,
    bid: float | None, ask: float | None,
) -> tuple[float | None, float | None, float | None, float | None, float | None, str]:
    """(model, mid, blended, yes_edge, no_edge, call) for one Contract.

    Needs both bid and ask: without a two-sided market there's no mid to blend with.
    """
    value = (contract.get("strike") or {}).get("value")
    if value is None or spot is None or minute_vol is None:
        return None, None, None, None, None, "-"
    model = prob_above(spot, float(value), mins_left, minute_vol)
    if bid is None or ask is None:
        return model, None, None, None, None, "-"
    mid = (bid + ask) / 2
    blended = blend(model, mid)
    yes_edge, no_edge = edges(blended, bid, ask)
    return model, mid, blended, yes_edge, no_edge, call(yes_edge, no_edge)


def fmt_moves(dist: float | None, move: float | None) -> str:
    """Distance measured in typical moves: under ~1 is easily reachable, over ~2 is unlikely."""
    if dist is None or not move:
        return "  - "
    return f"{dist / move:+.1f}"


def print_event(event: dict, now: datetime, spot: float | None, minute_vol: float | None) -> None:
    expires = parse_time(event["expiryDate"])
    mins_left = (expires - now).total_seconds() / 60
    move = typical_move(minute_vol, mins_left) if minute_vol is not None else None
    spot_txt = f"{spot:,.4f}".rstrip("0").rstrip(".") if spot is not None else "?"
    move_txt = f"+/-{move:.2%}" if move is not None else "?"
    print(
        f"\n{event['ticker']:<18} {event['series']:<7} "
        f"expires {expires:%m-%d %H:%M} UTC ({mins_left:.0f}m left)   "
        f"{asset_of(event)} now: {spot_txt}   typical move by expiry: {move_txt}   "
        f"index: {event.get('source', '?')}"
    )
    print(
        f"  {'strike':<20} {'dist':>7} {'moves':>5} {'bid':>5} {'ask':>5}  "
        f"{'yes$':>5} {'no$':>5} {'sprd':>5}  {'model':>5} {'mid':>5} {'blend':>5}  "
        f"{'yesE':>5} {'noE':>5}  {'call':<8} {'state':<10} flag"
    )
    contracts = sorted(
        event["contracts"],
        key=lambda c: float((c.get("strike") or {}).get("value") or 0),
    )
    for c in contracts:
        p = c.get("prices") or {}
        bid, ask = to_float(p.get("bestBid")), to_float(p.get("bestAsk"))
        yes_cost, no_cost, spread = costs(bid, ask)
        model, mid, blended, yes_edge, no_edge, verdict = evaluate(
            c, spot, mins_left, minute_vol, bid, ask
        )
        print(
            f"  {fmt_strike(c):<20} {fmt_pct(distance(c, spot)):>7} "
            f"{fmt_moves(distance(c, spot), move):>5} "
            f"{fmt_price(bid):>5} {fmt_price(ask):>5}  "
            f"{fmt_price(yes_cost):>5} {fmt_price(no_cost):>5} {fmt_price(spread):>5}  "
            f"{fmt_price(model):>5} {fmt_price(mid):>5} {fmt_price(blended):>5}  "
            f"{fmt_edge(yes_edge):>5} {fmt_edge(no_edge):>5}  {verdict:<8} "
            f"{c.get('marketState', '?'):<10} {flag(spread)}"
        )


@dataclass(frozen=True)
class MarketSnapshot:
    """Everything one agent cycle needs from Gemini, fetched at `at`. All free to fetch."""

    at: datetime
    spots: dict[str, float]  # current Gemini price per asset, USD
    vols: dict[str, float]  # typical move per minute per asset (0.0012 = 0.12%/min)
    # Open, two-sided Contracts per (asset, tier): one Nansen purchase covers each group.
    # Only groups whose asset has both a spot price and a volatility.
    groups: dict[tuple[str, Tier], list[Quote]]
    # Raw Gemini Events, for printing only. Free text from Gemini: never log these.
    events: list[dict] = field(repr=False, default_factory=list)


def fetch_snapshot() -> MarketSnapshot:
    """Fetch Events, spot prices and volatility, and group the quotes by Nansen purchase.

    `mins_left` on each Quote is measured from `at`, so use the snapshot right away.
    """
    events = sorted(
        (e for e in fetch_active_events() if wanted(e) and has_strikes(e)),
        key=lambda e: (e["series"][:3], e["expiryDate"]),
    )
    spots = fetch_spot_prices()
    vols = {asset: fetch_minute_volatility(asset) for asset in ASSETS}
    at = datetime.now(timezone.utc)
    groups = {
        (asset, tier): quotes
        for (asset, tier), quotes in quotes_by_purchase(events, at).items()
        if asset in spots and asset in vols
    }
    return MarketSnapshot(at, spots, vols, groups, events)


def main() -> None:
    snap = fetch_snapshot()
    print(f"{len(snap.events)} active events at {snap.at:%Y-%m-%d %H:%M} UTC")
    print(
        "typical daily move (last 7d, recent weighted): "
        + "  ".join(f"{a} {typical_move(v, 1440):.2%}" for a, v in snap.vols.items())
    )
    for event in snap.events:
        asset = asset_of(event)
        print_event(event, snap.at, snap.spots.get(asset), snap.vols.get(asset))
    print_info_decisions(snap)


def quotes_by_purchase(events: list[dict], now: datetime) -> dict[tuple[str, Tier], list[Quote]]:
    """Open, two-sided Contracts grouped by (asset, tier): one Nansen purchase covers each group.

    Every (asset, tier) seen gets a group, even an empty one, so decide() can say why it skipped.
    """
    groups: dict[tuple[str, Tier], list[Quote]] = {}
    for event in events:
        asset = asset_of(event)
        tier = tier_of(Horizon(event["series"][len(asset):]))
        mins_left = (parse_time(event["expiryDate"]) - now).total_seconds() / 60
        group = groups.setdefault((asset, tier), [])
        if mins_left <= 0:
            continue  # expired but not yet marked closed
        for c in event["contracts"]:
            if c.get("marketState") != "open":
                continue
            p = c.get("prices") or {}
            bid, ask = to_float(p.get("bestBid")), to_float(p.get("bestAsk"))
            value = (c.get("strike") or {}).get("value")
            if bid is not None and ask is not None and value is not None:
                group.append(Quote(event["ticker"], float(value), mins_left, bid, ask))
    return groups


def print_info_decisions(snap: MarketSnapshot) -> None:
    print("\nBuy Nansen data?  (value = expected extra profit from knowing the reading)")
    for (asset, tier), quotes in sorted(snap.groups.items()):
        d = decide(asset, tier, quotes, snap.spots[asset], snap.vols[asset])
        verdict = "BUY" if d.buy else "skip"
        print(
            f"  {asset:<4} {tier.value:<12} value ${d.value_usd:.3f} vs price ${d.price_usd:.2f}"
            f"  -> {verdict:<4} ({d.reason})"
        )


if __name__ == "__main__":
    main()
