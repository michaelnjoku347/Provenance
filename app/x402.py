"""Optional x402 pay-per-verify gate for XDC AI.

Settlement is not performed here. When the flag is on, a missing payment
header gets HTTP 402 with the USDC challenge. A present header is accepted
as a stub so the hackathon demo can show the contract without moving funds.
"""

from __future__ import annotations

import base64

from fastapi import Request
from fastapi.responses import JSONResponse

from app import config

# Circle USDC on XDC mainnet. See https://docs.xdcai.tech/reference/constants
USDC_XDC = "0xfA2958CB79b0491CC627c1557F441eF849Ca8eb1"
PRICE_HUMAN = "0.02"


def _amount() -> str:
    return config.xdc_price_base()


def _resource(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/api/x402/check"


def challenge(request: Request) -> dict:
    resource = _resource(request)
    amount = _amount()
    payto = config.xdc_payto()
    return {
        "x402Version": 1,
        "error": "Payment required",
        "accepts": [
            {
                "scheme": "exact",
                "network": "xdc",
                "maxAmountRequired": amount,
                "resource": resource,
                "description": "Provenance image check",
                "mimeType": "application/json",
                "asset": USDC_XDC,
                "payTo": payto,
                "extra": {"name": "USDC", "version": "2"},
            },
            {
                "x402Version": 2,
                "scheme": "exact",
                "network": "eip155:50",
                "amount": amount,
                "asset": USDC_XDC,
                "payTo": payto,
                "resource": resource,
                "description": "Provenance image check",
                "mimeType": "application/json",
                "extra": {"name": "USDC", "version": "2", "assetTransferMethod": "eip3009"},
            },
        ],
    }


def listing(request: Request) -> dict:
    return {
        "name": "Provenance image check",
        "url": _resource(request),
        "method": "POST",
        "priceUSDC": PRICE_HUMAN if _amount() == "20000" else _amount(),
        "capability": (
            "Check whether a viral image is likely real, AI-generated, or out of context, "
            "and return source receipts."
        ),
        "tags": ["provenance", "fact-check", "image", "newsroom", "verification"],
        "network": "xdc",
        "asset": USDC_XDC,
        "payTo": config.xdc_payto() or None,
        "paywallReady": config.paywall_on(),
        "docs": "https://docs.xdcai.tech/providers/x402-endpoint",
        "note": (
            "List this on the XDC AI marketplace once payTo is your USDC address and the "
            "service is on HTTPS. This build returns the 402 challenge and accepts a "
            "payment header without settling on-chain."
        ),
    }


def _header_ok(request: Request) -> bool:
    raw = request.headers.get("x-payment") or request.headers.get("payment-signature")
    if not raw or len(raw) < 16:
        return False
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception:
        return False
    return len(decoded) >= 16


def gate(request: Request) -> JSONResponse | dict:
    """Return a 402 response, a receipt dict, or a paywall-off receipt."""
    if not config.paywall_on():
        return {
            "status": "paywall_off",
            "detail": "Set XDC_AI_KEY and XDC_PAYTO to require 0.02 USDC per check on /api/x402/check.",
        }
    if not _header_ok(request):
        return JSONResponse(challenge(request), status_code=402)
    return {
        "status": "accepted_unsettled",
        "detail": (
            "Payment header decoded. This stub does not settle USDC on XDC. "
            "A facilitator would verify the EIP-3009 authorization and a relayer would submit it."
        ),
        "scheme": "exact",
        "amount": _amount(),
        "asset": USDC_XDC,
        "payTo": config.xdc_payto(),
    }
