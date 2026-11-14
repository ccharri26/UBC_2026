"""What a legitimate Nansen x402 payment request must look like.

The guardrails compare every 402 offer against these values before anything is
signed. Values verified against live 402 responses and Nansen's docs on 2026-11-13.

This list is deliberately separate from nansen/endpoints.py: payments trusts only
its own allowlist, so a bug in the caller can't widen what we're willing to pay for.
"""

NANSEN_HOST = "api.nansen.ai"

# x402 V2 "exact" scheme, USDC on Base mainnet.
SCHEME = "exact"
NETWORK = "eip155:8453"
CHAIN_ID = 8453
USDC_ON_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
NANSEN_PAY_TO = "0x93053f1e7A5eFEDa532Fe69CbbE43cBEc3A0F13f"

# EIP-712 domain of the USDC contract on Base (the offer's `extra`); we sign against this.
USDC_EIP712_NAME = "USD Coin"
USDC_EIP712_VERSION = "2"

# Hard cap for a single call, in USDC base units (6 decimals): 50_000 = $0.05.
MAX_PRICE_PER_CALL = 50_000

# The only paths we will ever pay for, with their pinned price in USDC base units.
# A 402 asking for any other amount is treated as price drift and refused.
ALLOWED_ENDPOINTS: dict[str, int] = {
    "/api/v1/tgm/flow-intelligence": 10_000,  # Basic, $0.01
    "/api/v1/smart-money/netflow": 50_000,  # Smart Money, $0.05
}

# The longest validity window we will sign, whatever the offer's maxTimeoutSeconds says.
MAX_AUTH_SECONDS = 300
