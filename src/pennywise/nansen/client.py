"""Public entry point for Nansen data: callers pass an asset and a Horizon, never a Tier.

Purchases are cached so one paid call serves every Contract that needs it:
- Smart Money: one per (asset, UTC clock hour), shared by the whole 1H ladder.
- Basic: one per asset, reused for 10 minutes, shared by 5M and 15M Events.
  Nansen caches flow-intelligence for 10-30 min, so rebuying sooner pays for the same data.
Paid results are also saved to data/nansen_cache.json (store.py): a restart reuses
them, and other processes (the dashboard API) can see them. Stub results stay in memory.

A slot that was paid for but gave nothing usable (bad response, or a payment that failed
after money left) is remembered until it would have expired, and not bought again.

Callers handle one error: NansenUnavailable means "use the baseline only".
Set NANSEN_STUB=true to get fake signals with no network and no spending.
"""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from pennywise.payments import PaymentFailed, PaymentRefused, pay
from pennywise.payments.config import env

from .bodies import NATIVE_TOKENS, build_body
from .endpoints import ENDPOINTS, Tier
from .horizons import HORIZON_TIER, Horizon
from .parsers import PARSERS, NansenResponseError
from .signals import NansenSignals
from . import store
from .stub import stub_signals

BASIC_TTL = timedelta(minutes=10)


class NansenUnavailable(RuntimeError):
    """No Nansen signals this time; fall back to the baseline forecast.

    `spent` says whether money left the wallet anyway (the payment went through but
    the data was missing or unusable), so scoring can still count the cost. The
    underlying error is chained as __cause__ for logs.
    """

    def __init__(self, message: str, *, spent: bool = False) -> None:
        super().__init__(message)
        self.spent = spent


class UnsupportedAsset(NansenUnavailable, ValueError):
    """Asset has no paid Nansen data (only NATIVE_TOKENS do; MVP: ETH). Nothing spent."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stub_mode() -> bool:
    """NANSEN_STUB=true in the environment or .env. Re-read on every call."""
    return (env("NANSEN_STUB") or "false").lower() == "true"


# cache key -> (expires_at, signals). Keys: (stub, asset, tier) or (stub, asset, tier, hour_start).
_cache: dict[tuple, tuple[datetime, NansenSignals]] = {}
# Same keys -> (expires_at, original error) for slots paid for with nothing usable back.
# In memory only: a restart may rebuy once, within the payment budgets.
_failed: dict[tuple, tuple[datetime, BaseException | None]] = {}


def is_supported(asset: str) -> bool:
    """True if Nansen sells paid data for this asset (NATIVE_TOKENS; MVP: ETH). Others use the baseline only."""
    return asset in NATIVE_TOKENS


def supported_assets() -> tuple[str, ...]:
    """Assets with paid Nansen data, in a stable order."""
    return tuple(NATIVE_TOKENS)


def horizons_for(tier: Tier) -> list[Horizon]:
    """Every Horizon that buys this Tier (Basic serves both 5M and 15M)."""
    return [h for h, t in HORIZON_TIER.items() if t == tier]


def tier_for_url(url: str | None) -> Tier | None:
    """Which Tier a paid URL belongs to (e.g. for labelling ledger rows); None if it isn't ours."""
    return next((t for t, e in ENDPOINTS.items() if e.url == url), None)


def tier_of(horizon: Horizon) -> Tier:
    """The one paid Tier a Horizon buys (5M/15M -> Basic, 1H -> Smart Money)."""
    return HORIZON_TIER[horizon]


def market_id(asset: str, tier: Tier) -> str:
    """The market a purchase is budgeted under, e.g. "ETH-smart_money" (per-market daily budget)."""
    return f"{asset}-{tier.value}"


def tier_price(tier: Tier) -> int:
    """Price of one call for this Tier, in USDC base units (10_000 = $0.01)."""
    return ENDPOINTS[tier].price


def price_of(horizon: Horizon) -> int:
    """Price of one call for this Horizon, in USDC base units (10_000 = $0.01)."""
    return tier_price(tier_of(horizon))


def cached_result(asset: str, tier: Tier, now: Callable[[], datetime] = _utc_now) -> NansenSignals | None:
    """The unexpired cached signals for this asset+tier, or None. Never buys.

    Live mode also checks data/nansen_cache.json, so purchases by other processes count.
    """
    if not is_supported(asset):
        return None
    t, stub = now(), stub_mode()
    slot, _ = _cache_slot(asset, tier, t)
    key = (stub, *slot)
    hit = _cache.get(key)
    if (hit is None or t >= hit[0]) and not stub:
        _load_from_disk(t)
        hit = _cache.get(key)
    return hit[1] if hit is not None and t < hit[0] else None


def is_cached(asset: str, tier: Tier, now: Callable[[], datetime] = _utc_now) -> bool:
    """True if get_signals would return this asset+tier from cache right now (costs nothing). Never buys."""
    return cached_result(asset, tier, now) is not None


def paid_but_unusable(asset: str, tier: Tier, now: Callable[[], datetime] = _utc_now) -> bool:
    """True if this slot was already paid for with nothing usable back, so get_signals won't rebuy it."""
    if not is_supported(asset):
        return False
    t = now()
    slot, _ = _cache_slot(asset, tier, t)
    bad = _failed.get((stub_mode(), *slot))
    return bad is not None and t < bad[0]


def _cache_slot(asset: str, tier: Tier, now: datetime) -> tuple[tuple, datetime]:
    """Cache key for a purchase made at `now`, and when that purchase expires."""
    if tier == Tier.SMART_MONEY:
        hour = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        return (asset, tier, hour), hour + timedelta(hours=1)
    return (asset, tier), now + BASIC_TTL


def get_signals(asset: str, horizon: Horizon, now: Callable[[], datetime] = _utc_now) -> NansenSignals:
    """Signals for `asset` at `horizon`, paying Nansen only on a cache miss.

    Raises NansenUnavailable (including its subclass UnsupportedAsset for BTC/XRP)
    whenever there is no data; the caller should then use the baseline only.
    `now` is injectable for tests.
    """
    if not is_supported(asset):
        raise UnsupportedAsset(f"No paid Nansen data for {asset!r}; supported: {sorted(NATIVE_TOKENS)}")
    tier = HORIZON_TIER[horizon]
    t = now()
    stub = stub_mode()
    slot, expires_at = _cache_slot(asset, tier, t)
    key = (stub, *slot)  # stub and real data never share a cache entry
    hit = _cache.get(key)
    if (hit is None or t >= hit[0]) and not stub:
        _load_from_disk(t)  # a restart, or another process, may already have bought it
        hit = _cache.get(key)
    if hit is not None and t < hit[0]:
        return hit[1]
    bad = _failed.get(key)
    if bad is not None and t < bad[0]:
        # Chain the original cause so callers can still tell a bad response from a failed payment.
        raise NansenUnavailable(f"{asset} {tier.value} already paid this slot with nothing usable; not rebuying",
                                spent=False) from bad[1]
    if stub:
        signals = stub_signals(asset, tier, t)
    else:
        try:
            signals = _purchase(asset, tier)
        except NansenUnavailable as e:
            if e.spent:  # money left but nothing to cache: don't pay again for this slot
                _failed[key] = (expires_at, e.__cause__)
            raise
        store.save(slot, expires_at, signals, t)
    _cache[key] = (expires_at, signals)
    return signals


def _load_from_disk(t: datetime) -> None:
    """Merge saved live entries into memory, keeping whichever of each expires later."""
    for slot, entry in store.load(t).items():
        key = (False, *slot)
        if key not in _cache or _cache[key][0] < entry[0]:
            _cache[key] = entry


def cached_signals(now: Callable[[], datetime] = _utc_now) -> list[NansenSignals]:
    """Unexpired cached results for the current mode (stub or live), for display. Never buys.

    Live mode re-reads data/nansen_cache.json, so it includes purchases made by other
    processes (e.g. the agent, when called from the dashboard API).
    """
    t, stub = now(), stub_mode()
    if not stub:
        _load_from_disk(t)
    return [signals for key, (expires_at, signals) in _cache.items() if key[0] == stub and t < expires_at]


def _purchase(asset: str, tier: Tier) -> NansenSignals:
    """Buy fresh data from Nansen and reduce it to numbers. The only place money is spent.

    Every failure becomes NansenUnavailable; nothing is cached on error (get_signals
    remembers spent failures in _failed instead).
    """
    endpoint = ENDPOINTS[tier]
    try:
        receipt = pay(endpoint.url, build_body(endpoint, asset), market_id(asset, tier))
    except PaymentRefused as e:
        raise NansenUnavailable(f"payment refused: {e}", spent=False) from e
    except PaymentFailed as e:
        raise NansenUnavailable(f"payment failed: {e}", spent=True) from e
    try:
        return PARSERS[tier](receipt.json, asset, _utc_now(), receipt.amount)
    except NansenResponseError as e:
        raise NansenUnavailable(f"unusable response: {e}", spent=True) from e
