"""JSON POST helper. Tests patch post_json so the suite never touches the network."""

from __future__ import annotations

import httpx

USER_AGENT = "Provenance/0.1"


def post_json(
    url: str,
    headers: dict,
    payload: dict,
    timeout: float = 30.0,
) -> tuple[int, dict | str]:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **headers}
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, headers=request_headers, json=payload)
    try:
        body: dict | str = response.json()
    except Exception:
        body = response.text[:500]
    return response.status_code, body


def get_json(url: str, headers: dict | None = None, timeout: float = 20.0) -> tuple[int, dict | str]:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, headers=request_headers)
    try:
        body: dict | str = response.json()
    except Exception:
        body = response.text[:500]
    return response.status_code, body


def get_text(url: str, timeout: float = 15.0) -> tuple[int, str]:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url, headers=request_headers)
    return response.status_code, response.text[:200_000]
