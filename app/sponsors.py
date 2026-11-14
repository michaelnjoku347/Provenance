"""Which sponsor tools ran, and what they returned. Counts live in this process."""

from __future__ import annotations

import threading

from app import config
from app.x402 import PRICE_HUMAN, USDC_XDC

_LOCK = threading.Lock()
_CALLS = {
    "youcom_search": 0,
    "youcom_contents": 0,
    "youcom_answer": 0,
    "treg": 0,
    "treg_news": 0,
    "treg_web": 0,
    "treg_profile": 0,
    "treg_replies": 0,
    "x402": 0,
}
_LAST: dict[str, dict] = {}


def reset() -> None:
    with _LOCK:
        for name in _CALLS:
            _CALLS[name] = 0
        _LAST.clear()


def record(name: str, called: bool = False, **stats) -> dict:
    payload = {"called": called, **stats}
    with _LOCK:
        if called and name in _CALLS:
            _CALLS[name] += 1
        _LAST[name] = payload
        payload["calls"] = _CALLS.get(name, 0)
    return payload


def _calls() -> dict:
    with _LOCK:
        return dict(_CALLS)


def receipt(web: dict, reverse: dict) -> dict:
    """Per-check stats copied onto the receipt. Counts are this call, not the session."""
    search = (web or {}).get("search") or {}
    contents = (web or {}).get("contents") or {}
    answer = (web or {}).get("answer") or {}
    reverse = reverse or {}
    paywall = config.paywall_on()
    amount = config.xdc_price_base()
    price = PRICE_HUMAN if amount == "20000" else amount
    treg_detail = reverse.get("detail") or ""
    if not config.key("TREG_API_KEY"):
        treg_detail = "Treg: add key"
    return {
        "youcom_search": {
            "label": "You.com Search",
            "status": search.get("status") or "skipped",
            "latency_ms": int(search.get("latency_ms") or 0),
            "results": len(search.get("hits") or []),
            "detail": search.get("detail") or "",
        },
        "youcom_contents": {
            "label": "You.com Contents",
            "status": contents.get("status") or "skipped",
            "latency_ms": int(contents.get("latency_ms") or 0),
            "pages": len(contents.get("pages") or []),
            "detail": contents.get("detail") or "",
        },
        "youcom_answer": {
            "label": "You.com Research" if answer.get("kind") == "research" else "You.com Answer",
            "status": answer.get("status") or "skipped",
            "latency_ms": int(answer.get("latency_ms") or 0),
            "citations": len(answer.get("citations") or []),
            "detail": answer.get("detail") or "",
        },
        "treg": {
            "label": "Treg reverse image",
            "status": reverse.get("status") or "skipped",
            "latency_ms": int(reverse.get("latency_ms") or 0),
            "matches": len(reverse.get("matches") or []),
            "detail": treg_detail,
        },
        "x402": {
            "label": "XDC x402",
            "status": "live" if paywall else "test",
            "mode": "live" if paywall else "test",
            "price_usdc": price,
            "amount": amount,
            "asset": USDC_XDC,
            "network": "xdc",
            "detail": (
                "Paywall is on. POST /api/x402/check returns a 402 challenge until a payment header is sent."
                if paywall
                else "Test mode. Set XDC_AI_KEY and XDC_PAYTO to require USDC. This desk check is not charged."
            ),
        },
        "opencrawl": {
            "label": "OpenCrawl",
            "runtime": False,
            "role": "build",
            "detail": (
                "OpenCrawl (getopencrawl.com) keeps full agent-session transcripts searchable. "
                "It was used while building this desk. The checker does not call it."
            ),
        },
    }


def snapshot() -> dict:
    calls = _calls()
    card = receipt(
        {
            "search": {"status": "skipped", "hits": [], "detail": ""},
            "contents": {"status": "skipped", "pages": [], "detail": ""},
            "answer": {"status": "skipped", "citations": [], "detail": ""},
        },
        {"status": "skipped", "matches": [], "detail": ""},
    )
    youcom_calls = calls["youcom_search"] + calls["youcom_contents"] + calls["youcom_answer"]
    card["youcom"] = {
        "label": "You.com",
        "connected": bool(config.key("YDC_API_KEY")),
        "calls": youcom_calls,
    }
    for name in ("youcom_search", "youcom_contents", "youcom_answer", "treg", "x402"):
        card[name]["calls"] = calls[name]
        card[name]["connected"] = {
            "youcom_search": bool(config.key("YDC_API_KEY")),
            "youcom_contents": bool(config.key("YDC_API_KEY")),
            "youcom_answer": bool(config.key("YDC_API_KEY")),
            "treg": bool(config.key("TREG_API_KEY")),
            "x402": config.paywall_on(),
        }[name]
    if not card["treg"]["connected"]:
        card["treg"]["hint"] = "Treg: add key"
    return card
