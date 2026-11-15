"""Append-only JSONL files in data/: decisions.jsonl (agent) and outcomes.jsonl (scoring).

Rows are never rewritten. A line that fails to parse or validate is skipped on read and
counted, so one bad line can't break the dashboard or scoring.
"""

import json
import threading
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from pennywise.payments.config import DATA_DIR

from .records import DecisionRow, OutcomeRow, RecordError

DECISIONS = DATA_DIR / "decisions.jsonl"
OUTCOMES = DATA_DIR / "outcomes.jsonl"

_lock = threading.Lock()
T = TypeVar("T")


@dataclass(frozen=True)
class Loaded(Generic[T]):
    rows: list[T]
    skipped: int  # lines that failed to parse or validate


def _append(path: Path, row: dict) -> None:
    line = json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n"
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line)


def _read(path: Path, parse, limit: int | None) -> Loaded[T]:
    if not path.exists():
        return Loaded([], 0)
    rows: Iterable[T] = deque(maxlen=limit) if limit is not None else []
    skipped = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rows.append(parse(json.loads(line)))  # type: ignore[union-attr]
            except (ValueError, KeyError, TypeError, RecordError):
                skipped += 1
    return Loaded(list(rows), skipped)


def append_decision(row: DecisionRow, path: Path = DECISIONS) -> None:
    _append(path, row.to_dict())


def read_decisions(limit: int | None = None, path: Path = DECISIONS) -> Loaded[DecisionRow]:
    """Valid rows, oldest first; `limit` keeps only the newest N."""
    return _read(path, DecisionRow.from_dict, limit)


def append_outcome(row: OutcomeRow, path: Path = OUTCOMES) -> None:
    _append(path, row.to_dict())


def read_outcomes(path: Path = OUTCOMES) -> Loaded[OutcomeRow]:
    return _read(path, OutcomeRow.from_dict, None)


def settled_events(path: Path = OUTCOMES) -> set[str]:
    """Events that already have an outcome, so scoring doesn't write a second one."""
    return {o.event for o in read_outcomes(path).rows}


def traded_events(path: Path = DECISIONS, include_stub: bool = True) -> set[str]:
    """Events already traded in any earlier cycle: the agent must not trade them again."""
    return {
        t.event
        for row in read_decisions(path=path).rows
        if include_stub or not row.stub
        for t in row.trades
    }


def worth_logging(row: DecisionRow, previous: DecisionRow | None) -> bool:
    """Log a cycle only if something happened, to keep the file small.

    True on the first row for this (asset, tier), any trade, any payment or Nansen
    error, or a change from `previous` (same asset and tier) in whether to use data
    or in any Contract's call.
    """
    if previous is None or row.trades or row.info.source == "paid" or row.info.error:
        return True
    if (row.info.buy, row.info.source) != (previous.info.buy, previous.info.source):
        return True
    calls = lambda r: {(q.event, q.strike): q.call for q in r.quotes}  # noqa: E731
    return calls(row) != calls(previous)
