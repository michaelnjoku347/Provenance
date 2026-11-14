"""Treg calls. Each one times out at 15s and never raises."""

from __future__ import annotations

import json
import re
import time

from app import config, httputil, sponsors

_TIMEOUT = 15.0
_COMMENT_KEYS = ("tweet_id", "id", "status_id", "post_id", "conversation_id")


def _ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _output(body) -> dict:
    if isinstance(body, dict) and isinstance(body.get("output"), dict):
        return body["output"]
    return body if isinstance(body, dict) else {}


def call(tool: str, body: dict, sponsor: str) -> dict:
    """POST https://treg.to/call/<tool>. A 422 comes back as status 'invalid' so the caller can retry."""
    empty = {"status": "skipped", "detail": "", "latency_ms": 0, "output": {}, "error": ""}
    if not config.key("TREG_API_KEY"):
        empty["detail"] = "Treg: add key"
        return empty
    started = time.perf_counter()
    try:
        status, payload = httputil.post_json(
            f"https://treg.to/call/{tool}",
            {"X-Treg-Token": config.key("TREG_API_KEY")},
            body,
            timeout=_TIMEOUT,
        )
    except Exception:
        elapsed = _ms(started)
        return {**empty, "status": "error", "detail": f"{tool} failed.", "latency_ms": elapsed}
    elapsed = _ms(started)
    if status == 422:
        return {
            **empty,
            "status": "invalid",
            "detail": f"{tool} returned HTTP 422.",
            "latency_ms": elapsed,
            "error": payload if isinstance(payload, str) else json.dumps(payload)[:800],
            "output": payload if isinstance(payload, dict) else {},
        }
    if status != 200 or not isinstance(payload, dict):
        return {**empty, "status": "error", "detail": f"{tool} returned HTTP {status}.", "latency_ms": elapsed}
    output = _output(payload)
    return {
        "status": "ok",
        "detail": "",
        "latency_ms": elapsed,
        "output": output,
        "error": "",
    }


def _rows(output: dict) -> list:
    rows = output.get("results") or output.get("organic") or output.get("news") or []
    return rows if isinstance(rows, list) else []


def _hit(row: dict, found_by: str) -> dict | None:
    if not isinstance(row, dict):
        return None
    url = str(row.get("link") or row.get("url") or "").strip()
    title = str(row.get("title") or "").strip()
    if not url.startswith("http") or not title:
        return None
    when = str(row.get("published_at") or row.get("date") or row.get("page_age") or "")[:40]
    return {
        "url": url,
        "title": title[:180],
        "excerpt": str(row.get("snippet") or row.get("description") or row.get("source") or "")[:700],
        "page_age": when,
        "bucket": "treg",
        "found_by": found_by,
    }


def _finish(name: str, sponsor: str, label: str, result: dict, hits: list[dict]) -> dict:
    status = "ok" if result.get("status") == "ok" else result.get("status") or "error"
    if status == "invalid":
        status = "error"
    detail = result.get("detail") or f"{len(hits)} results."
    if result.get("status") == "ok":
        detail = f"{len(hits)} results via {label}."
    sponsors.record(sponsor, called=status != "skipped", latency_ms=int(result.get("latency_ms") or 0), results=len(hits), status=status)
    return {
        "status": status,
        "detail": detail,
        "hits": hits,
        "latency_ms": int(result.get("latency_ms") or 0),
        "results": len(hits),
        "tool": name,
    }


def news(query: str) -> dict:
    query = " ".join((query or "").split())[:300]
    if not query:
        return {"status": "skipped", "detail": "No query for Treg News.", "hits": [], "latency_ms": 0, "results": 0, "tool": "treg.google.serp.news"}
    result = call("treg.google.serp.news", {"q": query}, "treg_news")
    if result["status"] != "ok":
        return _finish("treg.google.serp.news", "treg_news", "Treg News", result, [])
    hits = []
    for row in _rows(result["output"]):
        hit = _hit(row, "Treg News")
        if hit:
            hits.append(hit)
    # call() already recorded a sponsor row before we knew the hit count. Record the real count.
    return _finish("treg.google.serp.news", "treg_news", "Treg News", result, hits[:8])


def web(query: str) -> dict:
    query = " ".join((query or "").split())[:300]
    if not query:
        return {"status": "skipped", "detail": "No query for Treg Web.", "hits": [], "latency_ms": 0, "results": 0, "tool": "treg.google.serp.organic"}
    result = call("treg.google.serp.organic", {"q": query}, "treg_web")
    if result["status"] != "ok":
        return _finish("treg.google.serp.organic", "treg_web", "Treg Web", result, [])
    hits = []
    for row in _rows(result["output"]):
        hit = _hit(row, "Treg Web")
        if hit:
            hits.append(hit)
    return _finish("treg.google.serp.organic", "treg_web", "Treg Web", result, hits[:8])


def profile(username: str) -> dict:
    username = (username or "").strip().lstrip("@")
    if not username:
        return {"status": "skipped", "detail": "No X username.", "latency_ms": 0, "profile": {}}
    result = call("treg.x.user.profile", {"username": username}, "treg_profile")
    output = result.get("output") or {}
    card = {
        "username": str(output.get("username") or username),
        "name": str(output.get("name") or ""),
        "followers": output.get("followers") or output.get("followers_count") or 0,
        "verified": bool(output.get("is_verified") or output.get("verified")),
        "description": str(output.get("description") or output.get("bio") or "")[:280],
    }
    status = "ok" if result.get("status") == "ok" else ("skipped" if result.get("status") == "skipped" else "error")
    followers = card["followers"]
    try:
        followers_text = f"{int(followers):,}"
    except (TypeError, ValueError):
        followers_text = str(followers or "0")
    verified = "Verified" if card["verified"] else "Not verified"
    detail = result.get("detail") or f"{verified} · {followers_text} followers"
    if result.get("status") == "ok":
        detail = f"{verified} · {followers_text} followers. {card['description']}".strip()
    sponsors.record("treg_profile", called=result.get("status") != "skipped", latency_ms=int(result.get("latency_ms") or 0), results=1 if status == "ok" else 0, status=status)
    return {"status": status, "detail": detail[:300], "latency_ms": int(result.get("latency_ms") or 0), "profile": card, "results": 1 if status == "ok" else 0}


def _comment_keys(error: str) -> list[str]:
    found = re.findall(r"\b([A-Za-z][A-Za-z0-9_]{1,40})\b", error or "")
    keys = []
    for name in found:
        lowered = name.lower()
        if lowered in {"tweet_id", "tweetid", "id", "status_id", "post_id", "conversation_id", "url", "tweet_url"}:
            canonical = "tweet_id" if lowered == "tweetid" else name
            if canonical not in keys:
                keys.append(canonical)
    return keys


def comments(tweet_id: str, url: str = "") -> dict:
    tweet_id = str(tweet_id or "").strip()
    if not tweet_id:
        return {"status": "skipped", "detail": "No post id.", "latency_ms": 0, "replies": [], "results": 0}
    bodies = [{key: tweet_id} for key in _COMMENT_KEYS]
    if url:
        bodies.append({"url": url})
    tried = set()
    last = {"status": "skipped", "detail": "No post id.", "latency_ms": 0, "output": {}, "error": ""}
    for body in bodies:
        signature = tuple(sorted(body))
        if signature in tried:
            continue
        tried.add(signature)
        last = call("treg.x.post.comments", body, "treg_replies")
        if last.get("status") != "invalid":
            break
        for key in _comment_keys(last.get("error") or ""):
            value = url if "url" in key else tweet_id
            extra = (key, value)
            if extra not in {(k, v) for item in bodies for k, v in item.items()}:
                bodies.append({key: value})
    output = last.get("output") or {}
    rows = output.get("comments") or output.get("replies") or output.get("results") or []
    replies = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            text = str(row.get("text") or row.get("full_text") or row.get("body") or row.get("snippet") or "").strip()
            if not text:
                continue
            replies.append({"text": text[:240], "user": str(row.get("username") or row.get("user") or row.get("author") or "")[:40]})
            if len(replies) == 3:
                break
    status = "ok" if last.get("status") == "ok" else ("skipped" if last.get("status") == "skipped" else "error")
    detail = last.get("detail") or ""
    if last.get("status") == "ok":
        detail = f"{len(replies)} replies." if replies else "No reply text returned."
    sponsors.record("treg_replies", called=last.get("status") not in {"skipped", None}, latency_ms=int(last.get("latency_ms") or 0), results=len(replies), status=status)
    return {"status": status, "detail": detail, "latency_ms": int(last.get("latency_ms") or 0), "replies": replies, "results": len(replies)}


def merge_hits(hits: list[dict], extra: list[dict]) -> list[dict]:
    """Add Treg hits that You.com did not already return."""
    seen = {item.get("url") for item in hits if item.get("url")}
    merged = list(hits)
    for hit in extra:
        url = hit.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        merged.append(hit)
    return merged
