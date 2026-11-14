"""Read-only wallet info: the USDC balance on Base. Free (a plain RPC read, no signing)."""

import httpx

from . import expected
from .config import env

_BALANCE_OF = "0x70a08231"  # balanceOf(address)


def usdc_balance(address: str, timeout: float = 10) -> int:
    """USDC base units held by `address` on Base. Raises httpx.HTTPError / ValueError on failure."""
    rpc = env("BASE_RPC_URL") or "https://mainnet.base.org"
    data = _BALANCE_OF + address.lower().removeprefix("0x").rjust(64, "0")
    resp = httpx.post(rpc, timeout=timeout, json={
        "jsonrpc": "2.0", "id": 1, "method": "eth_call",
        "params": [{"to": expected.USDC_ON_BASE, "data": data}, "latest"],
    })
    resp.raise_for_status()
    body = resp.json()
    if "result" not in body:
        raise ValueError(f"RPC error: {body.get('error')}")
    return int(body["result"], 16)
