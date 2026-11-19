"""pay(): the only function in PennyWise that signs a payment.

Order: kill switch/pause → URL allowlist → budgets → human approval at or above the
Approval Threshold (outside the lock; may wait 90 s) → all of these again → free unpaid request → offer check
(scheme, network, asset, pay-to, pinned price, hard cap) → budgets → wallet key
matches WALLET_ADDRESS → on-chain USDC balance covers the price → sign → ledger →
send. A refusal at any step before signing raises PaymentRefused.

Dry run (signs locally, sends NO payment; makes only the free unpaid request):
    uv run python -m pennywise.payments --dry-run
"""

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from . import approval, expected, guardrails, wallet, x402
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


def _check_balance(address: str, amount: int) -> None:
    """Refuse unless the wallet holds at least `amount` USDC on Base (a free RPC read).

    Fail closed: if the balance can't be read, refuse rather than sign blind.
    """
    try:
        balance = wallet.usdc_balance(address)
    except Exception as e:  # RPC down, rate-limited, or a malformed reply
        raise PaymentRefused(f"could not read the wallet's USDC balance on Base: {type(e).__name__}") from None
    if balance < amount:
        raise PaymentRefused(f"wallet holds {balance} USDC base units on Base, less than the {amount} asked")


def _send_signed(http: httpx.Client, url: str, body: dict, header: str):
    """Send the signed request. Returns (ok, tx_hash, ledger detail, data, error message)."""
    try:
        paid = http.post(url, json=body, headers={x402.PAYMENT_HEADER: header})
    except httpx.HTTPError as e:
        return False, None, f"network: {type(e).__name__}", None, f"network error after signing: {type(e).__name__}"

    settlement = x402.decode_payment_response(paid)  # None if the header is unreadable
    tx_hash = x402.settlement_tx_hash(settlement)
    if paid.status_code != 200:
        detail = f"HTTP {paid.status_code}"
        return False, tx_hash, detail, None, f"{detail}: {paid.text[:300]}"
    try:
        data = paid.json()
    except ValueError:
        return False, tx_hash, "HTTP 200 but body is not JSON", None, "paid, but the response body is not JSON"
    # Data arrived, so the payment is presumed settled even if we can't read the receipt.
    detail = "ok" if settlement is not None else "ok, payment-response header unreadable"
    return True, tx_hash, detail, data, ""


def _approve(url: str, market: str) -> None:
    """Human approval for prices at or above the Approval Threshold (approval.py).

    Runs outside _lock, because it can wait up to 90 s for a human. Every guardrail runs
    first so nobody is asked about a purchase that would be refused anyway; pay() then
    re-runs them all under the lock, since budgets may have moved while we waited.
    """
    try:
        limits = load_limits()
    except ConfigError as e:
        raise PaymentRefused(str(e)) from None
    price = _allowed_price(url)
    guardrails.check(price, limits, market, datetime.now(timezone.utc))
    approval.require(price, market, stub=False)


def pay(url: str, body: dict, market: str, *, dry_run: bool = False,
        client: httpx.Client | None = None) -> Receipt:
    """POST `body` to a Nansen endpoint, paying via x402 if every guardrail passes.

    `market` names what the data is for, e.g. "ETH-smart_money"; the per-market
    daily budget is counted per market.
    """
    if not dry_run:
        _approve(url, market)
    with _lock:
        now = datetime.now(timezone.utc)
        try:
            limits = load_limits()
        except ConfigError as e:
            raise PaymentRefused(str(e)) from None
        price = _allowed_price(url)
        guardrails.check(price, limits, market, now)  # fail fast before any network call

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
            guardrails.check(amount, limits, market, now)

            try:
                key = private_key()
            except ConfigError as e:
                raise PaymentRefused(str(e)) from None
            payer = x402.address_of(key)
            wallet_address = env("WALLET_ADDRESS")
            if wallet_address and wallet_address.lower() != payer.lower():
                raise PaymentRefused("WALLET_PRIVATE_KEY does not match WALLET_ADDRESS")
            _check_balance(payer, amount)

            header, signed_by = x402.sign_payment(payment_required, offer, key)
            if signed_by != payer:
                raise PaymentRefused("signing address changed between checks")
            if dry_run:
                return Receipt(json={}, amount=amount, tx_hash=None, payer=payer)

            guardrails.record_signed(amount, url, market, payer, now)
            # The money may be gone from here on: record exactly one outcome, and let
            # nothing but PaymentFailed leave pay().
            try:
                ok, tx_hash, detail, data, error = _send_signed(http, url, body, header)
            except Exception as e:
                ok, tx_hash, data = False, None, None
                detail = error = f"unexpected error after signing: {type(e).__name__}"
            try:
                guardrails.record_outcome(ok, url, tx_hash, detail, now)
            except Exception as e:
                raise PaymentFailed(f"could not record the payment outcome: {type(e).__name__}") from None
            if not ok:
                raise PaymentFailed(error)
            return Receipt(json=data, amount=amount, tx_hash=tx_hash, payer=payer)
        finally:
            if client is None:
                http.close()

