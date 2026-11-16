"""Try a payment from the command line.

    uv run python -m pennywise.payments --dry-run              # sign locally, send nothing (free)
    uv run python -m pennywise.payments --live --tier basic    # REAL payment: $0.01 (smart_money: $0.05)
"""

import argparse
import json

from pennywise.nansen.bodies import NATIVE_TOKENS, build_body
from pennywise.nansen.client import market_id
from pennywise.nansen.endpoints import ENDPOINTS

from .pay import pay

parser = argparse.ArgumentParser(prog="python -m pennywise.payments")
mode = parser.add_mutually_exclusive_group(required=True)
mode.add_argument("--dry-run", action="store_true", help="sign locally but send no payment")
mode.add_argument("--live", action="store_true", help="really pay Nansen and fetch the data")
parser.add_argument("--asset", default="ETH", choices=list(NATIVE_TOKENS))  # paid assets only
parser.add_argument("--tier", default="basic", choices=[t.value for t in ENDPOINTS])
args = parser.parse_args()

endpoint = next(e for t, e in ENDPOINTS.items() if t.value == args.tier)
receipt = pay(endpoint.url, build_body(endpoint, args.asset), market_id(args.asset, endpoint.tier), dry_run=args.dry_run)
if args.dry_run:
    print(f"DRY RUN OK: {args.tier} {args.asset} would pay {receipt.amount} units "
          f"(${receipt.amount / 1e6:.2f}) from {receipt.payer}; nothing sent.")
else:
    print(f"PAID {receipt.amount} units (${receipt.amount / 1e6:.2f}) from {receipt.payer}")
    print(f"tx: https://basescan.org/tx/{receipt.tx_hash}" if receipt.tx_hash else "tx: (no payment-response header)")
    print(json.dumps(receipt.json, indent=1))
    from datetime import datetime, timezone

    from pennywise.nansen.parsers import PARSERS

    tier = next(t for t, e in ENDPOINTS.items() if e is endpoint)
    print()
    print("Parsed:", PARSERS[tier](receipt.json, args.asset, datetime.now(timezone.utc), receipt.amount))
