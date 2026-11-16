"""Settings for payments, read from the environment and the repo's .env file.

.env is READ-ONLY to code: it holds the wallet key and is edited by hand only.
Runtime state (the dashboard's kill switch) lives in data/, see control.py.
The .env file is re-read on every call, so hand edits take effect on the next
payment without a restart. Real environment variables win over .env.
"""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = ROOT / ".env"
DATA_DIR = ROOT / "data"


def _read_env_file() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    values = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.split(" #")[0].strip().strip("'\"")
    return values


def env(name: str) -> str | None:
    """os.environ first, then .env; None if unset or blank."""
    value = os.environ.get(name)
    if value is None:
        value = _read_env_file().get(name)
    return value or None


def usd_to_units(usd: str) -> int:
    """'0.10' -> 100_000 USDC base units."""
    return round(float(usd) * 1_000_000)


@dataclass(frozen=True)
class Limits:
    per_market: int  # USDC base units, per (asset, tier) per UTC day
    per_run: int
    daily: int
    kill_switch: bool


class ConfigError(RuntimeError):
    """A required setting is missing or malformed. Payments refuse rather than guess."""


def load_limits() -> Limits:
    def budget(name: str) -> int:
        raw = env(name)
        if raw is None:
            raise ConfigError(f"{name} is not set")
        try:
            units = usd_to_units(raw)
        except ValueError:
            raise ConfigError(f"{name} is not a number: {raw!r}") from None
        if units < 0:
            raise ConfigError(f"{name} must be >= 0")
        return units

    return Limits(
        per_market=budget("BUDGET_PER_MARKET_USD"),
        per_run=budget("BUDGET_PER_RUN_USD"),
        daily=budget("BUDGET_DAILY_USD"),
        # The hand-set master lock. Anything other than an explicit "false" counts as ON: fail closed.
        kill_switch=(env("KILL_SWITCH") or "true").lower() != "false",
    )


def private_key() -> str:
    """The wallet key. Never print, log or put this in an exception message."""
    key = env("WALLET_PRIVATE_KEY")
    if key is None:
        raise ConfigError("WALLET_PRIVATE_KEY is not set")
    return key

