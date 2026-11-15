"""Fetch signals the way the agent does, through get_signals (cache, guardrails, parsers).

    uv run python -m pennywise.nansen                         # ETH 1H; needs NANSEN_STUB=true
    uv run python -m pennywise.nansen --asset SOL --horizon 05M
    uv run python -m pennywise.nansen --live ...              # stub off: REAL payment
    uv run python -m pennywise.nansen --spread                # how stub readings spread over [-1, 1]
"""

import argparse
from dataclasses import fields

from . import Horizon, NansenUnavailable, get_signals, reading, stub_mode

parser = argparse.ArgumentParser(prog="python -m pennywise.nansen")
parser.add_argument("--asset", default="ETH", help="ETH or SOL (BTC/XRP show the fallback)")
parser.add_argument("--horizon", default="1H", choices=[h.value for h in Horizon])
parser.add_argument("--live", action="store_true", help="allow a real payment when NANSEN_STUB is not true")
parser.add_argument("--spread", action="store_true", help="print how stub readings spread (free, no network)")
args = parser.parse_args()

if args.spread:
    from .interpret import spread

    for tier, shares in spread().items():
        print(f"{tier.value:<12} " + "  ".join(f"{p:+.1f}: {share:4.0%}" for p, share in shares.items()))
    raise SystemExit

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
    print(f"  {'reading':28s} {reading(s):+.3f}")
