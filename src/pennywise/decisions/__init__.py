"""Decision log (data/decisions.jsonl) and Event outcomes (data/outcomes.jsonl).

The agent writes one DecisionRow per (asset, tier) per cycle when something happened
(see worth_logging); scoring writes one OutcomeRow per settled Event. Scoring, the API
and the narrator read them. Rows hold numbers and fixed labels only.
"""

from .log import (
    DECISIONS,
    OUTCOMES,
    Loaded,
    append_decision,
    append_outcome,
    read_decisions,
    read_outcomes,
    settled_events,
    traded_events,
    worth_logging,
)
from .records import (
    SCHEMA,
    ContractResult,
    DecisionRow,
    InfoRecord,
    OutcomeRow,
    QuoteRecord,
    RecordError,
    TradeRecord,
)

__all__ = [
    "DECISIONS", "OUTCOMES", "SCHEMA", "ContractResult", "DecisionRow", "InfoRecord", "Loaded",
    "OutcomeRow", "QuoteRecord", "RecordError", "TradeRecord", "append_decision", "append_outcome",
    "read_decisions", "read_outcomes", "settled_events", "traded_events", "worth_logging",
]
