"""The dashboard's kill switch, stored in data/control.json (never in .env).

The Kill Switch stops all spending AND all trading (the agent skips trades and the
runner stops looping). It is on if EITHER switch says so:
- KILL_SWITCH in .env: the master lock, set by hand. true = locked, and the
  dashboard cannot override it.
- data/control.json: {"spending": "on" | "off"}, written by the dashboard.

Fail closed: a missing file means "on" (defer to .env), but an unreadable or
unexpected file means "off".
"""

import json
import os
import tempfile
from pathlib import Path

from .config import DATA_DIR, env

CONTROL_FILE = DATA_DIR / "control.json"


def dashboard_stopped() -> bool:
    """True if the dashboard switched spending off, or the file can't be trusted."""
    try:
        raw = CONTROL_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    except OSError:
        return True
    try:
        state = json.loads(raw)
    except ValueError:
        return True
    return not (isinstance(state, dict) and state.get("spending") == "on")


def kill_switch_on() -> bool:
    """True if all spending and trading must stop: the .env lock or the dashboard switch."""
    return (env("KILL_SWITCH") or "true").lower() != "false" or dashboard_stopped()


def set_spending(on: bool) -> None:
    """Write the dashboard switch atomically (temp file + rename)."""
    CONTROL_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CONTROL_FILE.parent, prefix="control.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"spending": "on" if on else "off"}, f)
        os.replace(tmp, CONTROL_FILE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
