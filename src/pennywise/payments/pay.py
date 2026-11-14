"""pay(): the only function in PennyWise that signs a payment.

Order: kill switch/pause → URL allowlist → free unpaid request → offer check
(scheme, network, asset, pay-to, pinned price, hard cap) → budgets → sign →
ledger → send. A refusal at any step before signing raises PaymentRefused.

Dry run (signs locally, sends NO payment; makes only the free unpaid request):
    uv run python -m pennywise.payments --dry-run
"""

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from . import expected, guardrails, x402
from .config import ConfigError, load_limits, private_key, env
from .guardrails import PaymentRefused

_lock = threading.Lock()  # check-then-record must be atomic


class PaymentFailed(RuntimeError):
    """We signed and sent a payment but did not get data back. Counted as spent."""


@dataclass(frozen=True)
class Receipt:
    json: dict  # Nansen's response body; the caller reduces it to numbers
    amount: int  # USDC base units paid (10_000 = $0.01)
    tx_hash: str | None  # Base transaction hash from the payment-response header
    payer: str


def _allowed_price(url: str) -> int:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != expected.NANSEN_HOST or parts.port not in (None, 443):
        raise PaymentRefused(f"not the Nansen host: {url!r}")
    if parts.query or parts.fragment or parts.path not in expected.ALLOWED_ENDPOINTS:
        raise PaymentRefused(f"endpoint not on the allowlist: {parts.path!r}")
    return expected.ALLOWED_ENDPOINTS[parts.path]


def pay(url: str, body: dict, event_id: str | None = None, *, dry_run: bool = False,
        client: httpx.Client | None = None) -> Receipt:
    """POST `body` to a Nansen endpoint, paying via x402 if every guardrail passes."""
    with _lock:
        now = datetime.now(timezone.utc)
        try:
            limits = load_limits()
        except ConfigError as e:
            raise PaymentRefused(str(e)) from None
        price = _allowed_price(url)
        guardrails.check(price, limits, event_id, now)  # fail fast before any network call

        http = client or httpx.Client(timeout=30)
        try:
            try:
                first = http.post(url, json=body)
            except httpx.HTTPError as e:
                raise PaymentRefused(f"network error before signing: {type(e).__name__}") from None
            if first.status_code != 402:
                raise PaymentRefused(f"expected a 402 offer, got HTTP {first.status_code}")
            try:
                payment_required = x402.decode_payment_required(first)
            except ValueError:  # bad base64 or JSON (binascii.Error and JSONDecodeError are ValueErrors)
                raise PaymentRefused("402 offer is not readable") from None
            if not isinstance(payment_required, dict):
                raise PaymentRefused("402 offer is not an object")
            offer = x402.base_offer(payment_required)
            if offer is None:
                raise PaymentRefused("402 has no USDC-on-Base offer")
            problems = x402.check_offer(offer, price)
            if problems:
                raise PaymentRefused("offer mismatch: " + "; ".join(problems))
            amount = int(offer["amount"])
            guardrails.check(amount, limits, event_id, now)

            try:
                header, payer = x402.sign_payment(payment_required, offer, private_key())
            except ConfigError as e:
                raise PaymentRefused(str(e)) from None
            wallet = env("WALLET_ADDRESS")
            if wallet and wallet.lower() != payer.lower():
                raise PaymentRefused("WALLET_PRIVATE_KEY does not match WALLET_ADDRESS")
            if dry_run:
                return Receipt(json={}, amount=amount, tx_hash=None, payer=payer)

            guardrails.record_signed(amount, url, event_id, payer, now)
            try:
                paid = http.post(url, json=body, headers={x402.PAYMENT_HEADER: header})
            except httpx.HTTPError as e:
                guardrails.record_outcome(False, url, None, f"network: {type(e).__name__}", now)
                raise PaymentFailed(f"network error after signing: {type(e).__name__}") from None

            settlement = x402.decode_payment_response(paid)
            tx_hash = settlement.get("transaction")
            if paid.status_code != 200:
                detail = f"HTTP {paid.status_code}"
                guardrails.record_outcome(False, url, tx_hash, detail, now)
                raise PaymentFailed(f"{detail}: {paid.text[:300]}")
            try:
                data = paid.json()
            except ValueError:
                guardrails.record_outcome(False, url, tx_hash, "HTTP 200 but body is not JSON", now)
                raise PaymentFailed("paid, but the response body is not JSON") from None
            guardrails.record_outcome(True, url, tx_hash, "ok", now)
            return Receipt(json=data, amount=amount, tx_hash=tx_hash, payer=payer)
        finally:
            if client is None:
                http.close()

