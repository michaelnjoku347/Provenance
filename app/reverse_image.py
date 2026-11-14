"""Optional reverse-image / first-seen lookup through Treg. Skips cleanly."""

from __future__ import annotations

from app import config, httputil


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
                    }
                )
            for key, value in node.items():
                walk(value, preferred or key in {"organic", "visual_matches", "exact_matches", "matches"})
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


def lookup(image_url: str) -> dict:
    tool = config.treg_tool()
    if not config.key("TREG_API_KEY"):
        return {
            "status": "skipped",
            "detail": "TREG_API_KEY is not set.",
            "tool": tool,
            "matches": [],
        }
    image_url = (image_url or "").strip()
    if not image_url.startswith("http"):
        return {
            "status": "skipped",
            "detail": "Reverse image needs a public image_url. An upload alone skips this step.",
            "tool": tool,
            "matches": [],
        }
    try:
        status, body = httputil.post_json(
            f"https://treg.to/call/{tool}",
            {"X-Treg-Token": config.key("TREG_API_KEY")},
            {"url": image_url, "gl": "us", "hl": "en"},
            timeout=25,
        )
    except Exception:
        return {
            "status": "error",
            "detail": "Treg reverse-image request failed.",
            "tool": tool,
            "matches": [],
        }
    if status != 200 or not isinstance(body, dict):
        return {
            "status": "error",
            "detail": f"Treg returned HTTP {status}.",
            "tool": tool,
            "matches": [],
        }
    matches = _matches(body)
    return {
        "status": "ok",
        "detail": f"{len(matches)} visual matches via {tool}.",
        "tool": tool,
        "matches": matches,
    }
