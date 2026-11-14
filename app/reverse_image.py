"""Optional reverse-image / first-seen lookup through Treg. Skips cleanly."""

from __future__ import annotations

import time

from urllib.parse import quote

from app import config, httputil, sponsors


def _matches(body: dict) -> list[dict]:
    found: list[dict] = []

    def walk(node, preferred: bool) -> None:
        if len(found) >= 8:
            return
        if isinstance(node, dict):
            url = node.get("link") or node.get("url") or node.get("source_url")
            title = node.get("title") or node.get("name")
            if preferred and isinstance(url, str) and url.startswith("http") and title:
                found.append(
                    {
                        "url": url,
                        "title": str(title)[:180],
                        "date": str(node.get("date") or node.get("page_age") or "")[:40],
                        "source": str(node.get("source") or "")[:80],
                        "snippet": str(node.get("snippet") or node.get("excerpt") or node.get("description") or "")[:300],
                    }
                )
            for key, value in node.items():
                walk(value, preferred or key in {"organic", "visual_matches", "exact_matches", "matches", "results", "output"})
        elif isinstance(node, list):
            for item in node:
                walk(item, preferred)

    walk(body, False)
    unique = []
    seen = set()
    for item in found:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique.append(item)
    return unique[:6]


def knowledge_title(body) -> str:
    if not isinstance(body, dict):
        return ""
    output = body.get("output") if isinstance(body.get("output"), dict) else body
    graph = output.get("knowledge_graph") or output.get("knowledgeGraph") or {}
    if isinstance(graph, dict):
        title = graph.get("title") or graph.get("name") or ""
        if title:
            return str(title)[:180]
    return ""


def lookup(image_url: str) -> dict:
    tool = config.treg_tool()
    if not config.key("TREG_API_KEY"):
        return {
            "status": "skipped",
            "detail": "Treg: add key",
            "tool": tool,
            "matches": [],
            "latency_ms": 0,
        }
    image_url = (image_url or "").strip()
    if not image_url.startswith("http"):
        return {
            "status": "skipped",
            "detail": "Reverse image needs a public image_url. An upload alone skips this step.",
            "tool": tool,
            "matches": [],
        }
    started = time.perf_counter()
    endpoint = f"https://treg.to/call/{tool}?url={quote(image_url, safe='')}&gl=us&hl=en"
    status, body = 0, None
    try:
        status, body = httputil.get_json(
            endpoint,
            {"X-Treg-Token": config.key("TREG_API_KEY")},
            timeout=15,
        )
    except Exception:
        status, body = 0, None
    if status != 200 or not isinstance(body, dict):
        try:
            status, body = httputil.post_json(
                f"https://treg.to/call/{tool}",
                {"X-Treg-Token": config.key("TREG_API_KEY")},
                {"url": image_url, "gl": "us", "hl": "en"},
                timeout=15,
            )
        except Exception:
            return {
                "status": "error",
                "detail": "Treg reverse-image request failed.",
                "tool": tool,
                "matches": [],
                "latency_ms": 0,
            }
    elapsed = max(0, int((time.perf_counter() - started) * 1000))
    if status != 200 or not isinstance(body, dict):
        sponsors.record("treg", called=True, latency_ms=elapsed, matches=0, status="error")
        return {
            "status": "error",
            "detail": f"Treg returned HTTP {status}.",
            "tool": tool,
            "matches": [],
            "latency_ms": elapsed,
        }
    matches = _matches(body)
    named = knowledge_title(body)
    sponsors.record("treg", called=True, latency_ms=elapsed, matches=len(matches), status="ok")
    detail = f"Identified by Treg Google Lens. {len(matches)} visual matches via {tool}."
    if named:
        detail = f"Identified by Treg Google Lens: {named}. {len(matches)} visual matches."
    return {
        "status": "ok",
        "detail": detail,
        "tool": tool,
        "matches": matches,
        "knowledge_title": named,
        "latency_ms": elapsed,
    }
