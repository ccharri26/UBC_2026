"""Typed rows for the decision log (data/decisions.jsonl) and outcomes (data/outcomes.jsonl).

One DecisionRow = one purchase decision for one (asset, tier) in one agent cycle, with
every Contract it covered (quotes) and the trades it led to. Outcomes are written later,
by scoring, once an Event settles; they join to decisions on the Event ticker.

Every field is a number, a bool, a timestamp, or a short label from a fixed set or a
ticker-shaped string. No free text (and never anything from Nansen), so the narrator
LLM can read these rows safely. Each record checks itself on creation and on load.
"""

import math
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Literal, get_args, get_origin

SCHEMA = 1

Asset = Literal["BTC", "ETH", "SOL", "XRP"]
TierName = Literal["basic", "smart_money"]
Call = Literal["BUY YES", "BUY NO", "pass"]
Side = Literal["YES", "NO"]
# Where the forecast's Nansen data came from: bought this cycle, already cached, or none.
Source = Literal["paid", "cached", "none"]
# Why there was no data when we wanted it: NansenUnavailable, or "expired" when cached
# data the decision relied on expired before it was read (nothing is bought then).
NansenError = Literal["unsupported", "refused", "failed", "bad_response", "expired"]
Mode = Literal["shadow", "sandbox"]
# Who made the cycle's decisions: the deterministic cycle (rule) or the Grok tool loop (llm).
DecidedBy = Literal["rule", "llm"]

_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,63}$")
_REASON = re.compile(r"^[a-z0-9 ,'-]{1,60}$")


class RecordError(ValueError):
    """A record doesn't match the schema."""


def _labels(tp: object) -> tuple | None:
    """Allowed values if `tp` is a Literal (or Literal | None), else None."""
    if get_origin(tp) is Literal:
        return get_args(tp)
    literals = [a for a in get_args(tp) if get_origin(a) is Literal]
    if literals:  # e.g. NansenError | None
        return tuple(v for a in literals for v in get_args(a)) + ((None,) if type(None) in get_args(tp) else ())
    return None


def _check(record: object) -> None:
    """Shared checks: numbers are finite, numeric fields hold numbers, labels come from their Literal."""
    name = type(record).__name__
    for f in fields(record):  # type: ignore[arg-type]
        value = getattr(record, f.name)
        if isinstance(value, float) and not math.isfinite(value):
            raise RecordError(f"{name}.{f.name} must be finite, got {value!r}")
        if f.type in (float, float | None) and value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float))
        ):
            raise RecordError(f"{name}.{f.name} must be a number, got {value!r}")
        if f.type in (int, bool) and type(value) is not f.type:
            raise RecordError(f"{name}.{f.name} must be {f.type.__name__}, got {value!r}")
        allowed = _labels(f.type)
        if allowed is not None and value not in allowed:
            raise RecordError(f"{name}.{f.name} must be one of {allowed}, got {value!r}")


def _ticker(name: str, value: str) -> None:
    if not isinstance(value, str) or not _TICKER.match(value):
        raise RecordError(f"{name} must look like a Gemini ticker, got {value!r}")


def _prob(name: str, value: float | None) -> None:
    if value is not None and not 0.0 <= value <= 1.0:
        raise RecordError(f"{name} must be in [0, 1], got {value!r}")


@dataclass(frozen=True)
class InfoRecord:
    """The value-of-information decision and what actually happened with Nansen."""

    value_usd: float  # expected extra profit from the data (info/value.py)
    price_usd: float  # what decide() compared it with (0 if cached)
    buy: bool  # decide() said use the data
    reason: str  # decide()'s short reason, e.g. "worth more than it costs"
    source: Source  # where the data used for `informed` came from
    cost_usd: float  # actually paid this cycle (0 for cached/none/stub). Spend totals come from payments.jsonl
    reading: float | None = None  # nansen.reading(), [-1, 1]; None if no data
    error: NansenError | None = None  # set if we wanted data but got none (see NansenError)
    spent: bool = False  # with `error`: money left the wallet anyway

    def __post_init__(self) -> None:
        _check(self)
        if not _REASON.match(self.reason):
            raise RecordError(f"reason must be a short lowercase label, got {self.reason!r}")
        if self.reading is not None and not -1.0 <= self.reading <= 1.0:
            raise RecordError(f"reading must be in [-1, 1], got {self.reading!r}")
        if self.cost_usd < 0 or self.price_usd < 0 or self.value_usd < 0:
            raise RecordError("value_usd, price_usd and cost_usd must be >= 0")
        if (self.source == "none") != (self.reading is None):
            raise RecordError("reading must be set exactly when source is 'paid' or 'cached'")


@dataclass(frozen=True)
class QuoteRecord:
    """One two-sided Contract as the agent saw it this cycle."""

    event: str  # Event ticker: Contracts in one Event share an outcome
    strike: float
    mins_left: float
    bid: float
    ask: float
    baseline: float  # blended baseline probability (reading 0)
    informed: float | None  # with the Nansen reading; None if no data (baseline was used)
    yes_edge: float | None
    no_edge: float | None
    call: Call  # on `informed` if set, else on `baseline`

    def __post_init__(self) -> None:
        _check(self)
        _ticker("event", self.event)
        for name in ("bid", "ask", "baseline", "informed"):
            _prob(name, getattr(self, name))
        if self.bid > self.ask:
            raise RecordError(f"bid {self.bid} > ask {self.ask}")


@dataclass(frozen=True)
class TradeRecord:
    """A trade taken (simulated in shadow mode). At most one per Event, ever."""

    event: str
    strike: float
    side: Side
    price: float  # cost per $1 contract: ask for YES, 1 - bid for NO
    contracts: int
    fee_usd: float  # total taker fee for all contracts
    edge: float  # expected profit per contract after fees, at decision time
    mode: Mode = "shadow"

    def __post_init__(self) -> None:
        _check(self)
        _ticker("event", self.event)
        _prob("price", self.price)
        if self.contracts <= 0 or self.fee_usd < 0:
            raise RecordError("contracts must be > 0 and fee_usd >= 0")


@dataclass(frozen=True)
class DecisionRow:
    at: datetime
    cycle: int
    stub: bool  # NANSEN_STUB was on: readings are fake, scoring must skip them
    asset: Asset
    tier: TierName
    spot: float
    minute_vol: float
    info: InfoRecord
    quotes: tuple[QuoteRecord, ...] = ()
    trades: tuple[TradeRecord, ...] = ()
    decided_by: DecidedBy = "rule"  # rows written before this field existed were all rule-based
    schema: int = SCHEMA

    def __post_init__(self) -> None:
        _check(self)
        if self.at.tzinfo is None:
            raise RecordError("at must be timezone-aware (UTC)")
        events = [t.event for t in self.trades]
        if len(events) != len(set(events)):
            raise RecordError(f"more than one trade for an Event in one row: {events}")
        quoted = {(q.event, q.strike) for q in self.quotes}
        for t in self.trades:
            if (t.event, t.strike) not in quoted:
                raise RecordError(f"trade {t.event} @ {t.strike} has no matching quote")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["at"] = self.at.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "DecisionRow":
        return cls(
            at=datetime.fromisoformat(d["at"]),
            cycle=d["cycle"],
            stub=d["stub"],
            asset=d["asset"],
            tier=d["tier"],
            spot=d["spot"],
            minute_vol=d["minute_vol"],
            info=InfoRecord(**d["info"]),
            quotes=tuple(QuoteRecord(**q) for q in d.get("quotes", ())),
            trades=tuple(TradeRecord(**t) for t in d.get("trades", ())),
            decided_by=d.get("decided_by", "rule"),
            schema=d.get("schema", SCHEMA),
        )


@dataclass(frozen=True)
class ContractResult:
    strike: float
    yes: bool  # the Contract resolved Yes (paid $1 to Yes holders)


@dataclass(frozen=True)
class OutcomeRow:
    """How an Event settled. Written once per Event by scoring."""

    event: str
    asset: Asset
    settled_at: datetime
    settle_price: float | None  # the price Gemini settled on, if it reports one
    results: tuple[ContractResult, ...] = field(default_factory=tuple)
    schema: int = SCHEMA

    def __post_init__(self) -> None:
        _check(self)
        _ticker("event", self.event)
        if self.settled_at.tzinfo is None:
            raise RecordError("settled_at must be timezone-aware (UTC)")
        for r in self.results:
            if not isinstance(r.yes, bool) or not math.isfinite(r.strike):
                raise RecordError(f"bad result {r!r}")

    def result_for(self, strike: float) -> bool | None:
        return next((r.yes for r in self.results if r.strike == strike), None)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["settled_at"] = self.settled_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "OutcomeRow":
        return cls(
            event=d["event"],
            asset=d["asset"],
            settled_at=datetime.fromisoformat(d["settled_at"]),
            settle_price=d.get("settle_price"),
            results=tuple(ContractResult(**r) for r in d.get("results", ())),
            schema=d.get("schema", SCHEMA),
        )
