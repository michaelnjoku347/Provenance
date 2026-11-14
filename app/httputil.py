"""JSON helpers. Tests patch these so the suite never touches the network."""

from __future__ import annotations

import json

import httpx

USER_AGENT = "Provenance/0.1"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _body(response: httpx.Response) -> dict | list | str:
    """Decode the payload as UTF-8. A declared Latin-1 charset must not win."""
    raw = response.content or b""
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except Exception:
        return text[:500]


def post_json(
    url: str,
    headers: dict,
    payload: dict,
    timeout: float = 30.0,
) -> tuple[int, dict | list | str]:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **headers}
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, headers=request_headers, json=payload)
    return response.status_code, _body(response)


def get_json(url: str, headers: dict | None = None, timeout: float = 20.0) -> tuple[int, dict | list | str]:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, headers=request_headers)
    return response.status_code, _body(response)


def get_text(url: str, timeout: float = 15.0) -> tuple[int, str]:
    request_headers = {"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml"}
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, headers=request_headers)
    raw = response.content or b""
    return response.status_code, raw.decode("utf-8", errors="replace")[:200_000]


def get_bytes(url: str, timeout: float = 20.0) -> tuple[int, bytes, str]:
    """Download a public image. Browser User-Agent, hard timeout, no raise on HTTP errors."""
    request_headers = {"User-Agent": BROWSER_UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, headers=request_headers)
    media = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    return response.status_code, response.content or b"", media
