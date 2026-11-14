"""Fetch signals the way the agent does, through get_signals (cache, guardrails, parsers).

    uv run python -m pennywise.nansen                         # ETH 1H; needs NANSEN_STUB=true
    uv run python -m pennywise.nansen --asset SOL --horizon 05M
    uv run python -m pennywise.nansen --live ...              # stub off: REAL payment
"""

import argparse
from dataclasses import fields

from . import Horizon, NansenUnavailable, get_signals, stub_mode

parser = argparse.ArgumentParser(prog="python -m pennywise.nansen")
parser.add_argument("--asset", default="ETH", help="ETH or SOL (BTC/XRP show the fallback)")
parser.add_argument("--horizon", default="1H", choices=[h.value for h in Horizon])
parser.add_argument("--live", action="store_true", help="allow a real payment when NANSEN_STUB is not true")
args = parser.parse_args()

stub = stub_mode()
if not stub and not args.live:
    parser.error("NANSEN_STUB is not true, so this would spend real USDC. Add --live to confirm.")

print(f"mode: {'STUB (fake data, no spending)' if stub else 'LIVE (real payment)'}")
try:
    s = get_signals(args.asset, Horizon(args.horizon))
except NansenUnavailable as e:
    print(f"NansenUnavailable ({type(e).__name__}, spent={e.spent}): {e}\n-> agent would use the baseline only")
else:
    for f in fields(s):
        print(f"  {f.name:28s} {getattr(s, f.name)}")
