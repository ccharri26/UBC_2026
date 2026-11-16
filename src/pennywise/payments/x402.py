"""x402 V2 wire format: read the 402 offer, sign an EIP-3009 USDC authorization, read the receipt.

No policy lives here; guardrails.py decides whether we are allowed to sign.
"""

import base64
import json
import os
import time

import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data

from . import expected

PAYMENT_HEADER = "PAYMENT-SIGNATURE"

_TRANSFER_WITH_AUTHORIZATION = {
    "TransferWithAuthorization": [
        {"name": "from", "type": "address"},
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "validAfter", "type": "uint256"},
        {"name": "validBefore", "type": "uint256"},
        {"name": "nonce", "type": "bytes32"},
    ]
}


def _b64_json(raw: str) -> dict:
    return json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4)))


def decode_payment_required(resp: httpx.Response) -> dict:
    """x402 V2 puts the offer, base64-encoded JSON, in the payment-required header."""
    raw = resp.headers.get("payment-required")
    if raw is None:  # V1 servers send it as the body instead
        return resp.json()
    return _b64_json(raw)


def decode_payment_response(resp: httpx.Response) -> dict | None:
    """Settlement result ({success, transaction, network, payer}).

    {} if the header is absent; None if it is there but unreadable (bad base64 or
    JSON, or not an object). Never raises: by now the payment is already signed.
    """
    raw = resp.headers.get("payment-response")
    if not raw:
        return {}
    try:
        settlement = _b64_json(raw)
    except ValueError:  # binascii.Error, JSONDecodeError and UnicodeDecodeError are ValueErrors
        return None
    return settlement if isinstance(settlement, dict) else None


def settlement_tx_hash(settlement: dict | None) -> str | None:
    """The settlement's transaction hash, if it is a string."""
    tx_hash = (settlement or {}).get("transaction")
    return tx_hash if isinstance(tx_hash, str) else None


def base_offer(payment_required: dict) -> dict | None:
    """The USDC-on-Base entry of the offer's `accepts` list, if any."""
    for offer in payment_required.get("accepts", []):
        if offer.get("network") == expected.NETWORK:
            return offer
    return None


def check_offer(offer: dict, expected_price: int) -> list[str]:
    """Problems with one entry of the offer's `accepts` list; empty means it looks legit."""
    try:
        price = int(offer.get("amount", offer.get("maxAmountRequired", -1)))
    except (TypeError, ValueError):
        price = -1
    extra = offer.get("extra") or {}
    checks = {
        "scheme": (offer.get("scheme"), expected.SCHEME),
        "network": (offer.get("network"), expected.NETWORK),
        "asset": (str(offer.get("asset", "")).lower(), expected.USDC_ON_BASE.lower()),
        "payTo": (str(offer.get("payTo", "")).lower(), expected.NANSEN_PAY_TO.lower()),
        "price": (price, expected_price),
        "extra.name": (extra.get("name"), expected.USDC_EIP712_NAME),
        "extra.version": (extra.get("version"), expected.USDC_EIP712_VERSION),
    }
    problems = [f"{k}: got {got!r}, expected {want!r}" for k, (got, want) in checks.items() if got != want]
    if price > expected.MAX_PRICE_PER_CALL:
        problems.append(f"price {price} exceeds hard cap {expected.MAX_PRICE_PER_CALL}")
    return problems


def address_of(private_key: str) -> str:
    """The wallet address for a private key (no signing, no network)."""
    return Account.from_key(private_key).address


def sign_payment(payment_required: dict, offer: dict, private_key: str) -> tuple[str, str]:
    """Sign a USDC transferWithAuthorization for exactly this offer.

    Returns (header value for PAYMENT-SIGNATURE, payer address). Gasless for us: the
    facilitator submits the authorization on-chain and pays the gas.
    """
    account = Account.from_key(private_key)
    now = int(time.time())
    timeout = min(int(offer.get("maxTimeoutSeconds") or expected.MAX_AUTH_SECONDS), expected.MAX_AUTH_SECONDS)
    authorization = {
        "from": account.address,
        "to": expected.NANSEN_PAY_TO,  # our pinned value, not the offer's
        "value": int(offer["amount"]),
        "validAfter": now - 60,  # small allowance for clock skew
        "validBefore": now + timeout,
        "nonce": os.urandom(32),
    }
    domain = {
        "name": expected.USDC_EIP712_NAME,
        "version": expected.USDC_EIP712_VERSION,
        "chainId": expected.CHAIN_ID,
        "verifyingContract": expected.USDC_ON_BASE,
    }
    message = encode_typed_data(domain, _TRANSFER_WITH_AUTHORIZATION, authorization)
    signed = account.sign_message(message)

    # Self-check: the signature must recover to our own address.
    if Account.recover_message(message, signature=signed.signature) != account.address:
        raise RuntimeError("signature self-check failed")

    payload = {
        "x402Version": 2,
        "resource": payment_required.get("resource"),
        "accepted": offer,
        "payload": {
            "signature": "0x" + signed.signature.hex().removeprefix("0x"),
            "authorization": {
                **{k: str(v) for k, v in authorization.items() if k != "nonce"},
                "nonce": "0x" + authorization["nonce"].hex(),
            },
        },
    }
    header = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return header, account.address
