"""You.com search, contents, and cited synthesis (Answer, or Research when asked)."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from app import config, httputil, sponsors
from app.textutil import repair_text

SEARCH_URL = "https://ydc-index.io/v1/search"
CONTENTS_URL = "https://ydc-index.io/v1/contents"
ANSWER_URL = "https://api.you.com/v1/answer"
RESEARCH_URL = "https://api.you.com/v1/research"
ANSWER_MAX = 380


def _headers() -> dict:
    return {"X-API-Key": config.key("YDC_API_KEY"), "Content-Type": "application/json"}


def _excerpt(item: dict) -> str:
    contents = item.get("contents") or {}
    highlights = contents.get("highlights") if isinstance(contents, dict) else None
    snippets = item.get("snippets") or []
    parts = highlights or snippets or []
    if isinstance(parts, str):
        parts = [parts]
    text = " ".join(str(part) for part in parts[:3] if part)
    if not text:
        text = str(item.get("description") or "")
    return repair_text(" ".join(text.split())[:700])


def _hit(item: dict, bucket: str) -> dict | None:
    if not isinstance(item, dict):
        return None
    url = str(item.get("url") or item.get("source") or "").strip()
    if not url.startswith("http"):
        return None
    title = repair_text(str(item.get("title") or urlparse(url).netloc or "Source").strip())
    return {
        "url": url,
        "title": title[:180],
        "excerpt": _excerpt(item),
        "page_age": str(item.get("page_age") or "")[:40],
        "bucket": bucket,
        "found_by": "You.com Search",
    }


def _parse_search(body: dict) -> list[dict]:
    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, dict):
        return []
    hits = []
    for bucket in ("news", "web"):
        for item in results.get(bucket) or []:
            hit = _hit(item, bucket)
            if hit:
                hits.append(hit)
    return hits


def _ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _search(query: str) -> dict:
    from app.verdict import _recent_claim

    started = time.perf_counter()
    payload = {
        "query": query,
        "count": 10,
        "extraction": {"extraction_mode": "highlights"},
        "knowledge": "core",
    }
    if _recent_claim(query):
        payload["freshness"] = "week"
    status, body = httputil.post_json(SEARCH_URL, _headers(), payload, timeout=25)
    hits = _parse_search(body) if status == 200 and isinstance(body, dict) else []
    if status >= 400 or (payload.get("freshness") and not hits):
        payload.pop("freshness", None)
        status, body = httputil.post_json(SEARCH_URL, _headers(), payload, timeout=25)
    if status != 200 or not isinstance(body, dict):
        elapsed = _ms(started)
        sponsors.record("youcom_search", called=True, latency_ms=elapsed, results=0, status="error")
        return {"status": "error", "detail": f"You.com search returned HTTP {status}.", "hits": [], "latency_ms": elapsed}
    hits = _parse_search(body)
    knowledge = ""
    for item in (body.get("results") or {}).get("knowledge") or []:
        if isinstance(item, dict) and item.get("description"):
            knowledge = str(item["description"])[:400]
            break
    elapsed = _ms(started)
    sponsors.record("youcom_search", called=True, latency_ms=elapsed, results=len(hits), status="ok")
    return {
        "status": "ok",
        "detail": f"{len(hits)} results.",
        "hits": hits,
        "knowledge": knowledge,
        "latency_ms": elapsed,
    }


def _page_rows(body) -> list:
    """Contents returns a top-level list. Older payloads used a results object."""
    if isinstance(body, list):
        return body
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            return []
        return _page_rows(body)
    if not isinstance(body, dict):
        return []
    rows = body.get("results")
    if rows is None:
        rows = body.get("data") or body.get("contents") or []
    if isinstance(rows, dict):
        rows = list(rows.values())
    return rows if isinstance(rows, list) else []


def _parse_pages(body) -> list[dict]:
    pages = []
    for row in _page_rows(body):
        if not isinstance(row, dict):
            continue
        markdown = row.get("markdown") or row.get("html") or ""
        if isinstance(markdown, dict):
            markdown = markdown.get("content") or markdown.get("text") or ""
        meta = row.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        text = str(markdown or meta.get("description") or "")
        title = row.get("title") or meta.get("title") or meta.get("ogTitle") or ""
        pages.append(
            {
                "url": str(row.get("url") or ""),
                "title": repair_text(str(title))[:180],
                "excerpt": repair_text(" ".join(text.split())[:700]),
            }
        )
    return pages


def read_page(url: str) -> dict:
    """Read one URL the user pasted. Skips cleanly when You.com is not configured."""
    if not config.key("YDC_API_KEY"):
        return {"status": "skipped", "detail": "YDC_API_KEY is not set.", "pages": []}
    return _contents([url])


def _contents(urls: list[str]) -> dict:
    if not urls:
        return {"status": "skipped", "detail": "No result URLs to read.", "pages": [], "latency_ms": 0}
    started = time.perf_counter()
    payload = {"urls": urls[:3], "formats": ["markdown", "metadata"]}
    status, body = httputil.post_json(CONTENTS_URL, _headers(), payload, timeout=25)
    elapsed = _ms(started)
    pages = _parse_pages(body) if status == 200 else []
    if status != 200 or (not pages and not isinstance(body, (dict, list))):
        sponsors.record("youcom_contents", called=True, latency_ms=elapsed, pages=0, status="error")
        return {"status": "error", "detail": f"You.com contents returned HTTP {status}.", "pages": [], "latency_ms": elapsed}
    sponsors.record("youcom_contents", called=True, latency_ms=elapsed, pages=len(pages), status="ok")
    return {"status": "ok", "detail": f"Read {len(pages)} pages.", "pages": pages, "latency_ms": elapsed}


def _clip_query(text: str, limit: int = ANSWER_MAX) -> str:
    """Answer rejects any query over 400 characters."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    clipped = text[:limit]
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped or text[:limit]


def _research_body(body) -> tuple[str, list]:
    output = body.get("output") if isinstance(body, dict) else None
    if not isinstance(output, dict):
        return "", []
    content = output.get("content") if isinstance(output.get("content"), str) else ""
    citations = []
    for source in output.get("sources") or []:
        if not isinstance(source, dict) or not source.get("url"):
            continue
        snippets = source.get("snippets")
        excerpt = " ".join(snippets)[:400] if isinstance(snippets, list) else str(source.get("snippet") or "")[:400]
        citations.append({"url": source["url"], "title": source.get("title") or "", "excerpt": excerpt})
    return repair_text(content), citations


def _research(prompt: str) -> dict:
    """Research lite accepts a long input. Answer does not."""
    try:
        status, body = httputil.post_json(
            RESEARCH_URL,
            _headers(),
            {"input": (prompt or "")[:6000], "research_effort": "lite"},
            timeout=40,
        )
    except Exception:
        return {"status": "error", "text": "", "citations": [], "kind": "research", "detail": "You.com research failed."}
    if status != 200 or not isinstance(body, dict):
        return {
            "status": "error",
            "text": "",
            "citations": [],
            "kind": "research",
            "detail": f"You.com research returned HTTP {status}.",
        }
    text, citations = _research_body(body)
    return {
        "status": "ok",
        "text": text[:2000],
        "citations": citations,
        "kind": "research",
        "detail": "Research API lite.",
    }


def judge_stance(claim: str, hits: list | None) -> dict:
    """Strict JSON stance from the sources already retrieved. Empty dict means use the keyword fallback.

    The Answer query stays under 400 characters. A long source list uses Research lite instead.
    This does not record a sponsor call, and it never raises.
    """
    claim = " ".join((claim or "").split())
    if not config.key("YDC_API_KEY") or not claim:
        return {}
    urls = " ".join(str(hit.get("url") or "") for hit in (hits or [])[:4] if str(hit.get("url") or "").startswith("http"))
    packed = _clip_query(
        "Judge the claim from these sources only. "
        'Return JSON {"stance":"supports|contradicts|mixed|insufficient","answer":"one sentence",'
        '"evidence":[{"url":"","quote":"","stance":"supports|contradicts|mixed|insufficient"}]}. '
        f"Claim: {claim[:140]}. Sources: {urls}",
        380,
    )
    try:
        status, body = httputil.post_json(ANSWER_URL, _headers(), {"query": packed}, timeout=25)
    except Exception:
        return {}
    if status != 200 or not isinstance(body, dict):
        return {}
    text = str(body.get("answer") or "")
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    stance = str(data.get("stance") or "").strip().lower()
    if stance not in {"supports", "contradicts", "mixed", "insufficient"}:
        return {}
    evidence = []
    for item in data.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        item_stance = str(item.get("stance") or stance).strip().lower()
        if item_stance not in {"supports", "contradicts", "mixed", "insufficient"}:
            item_stance = stance
        if url.startswith("http"):
            evidence.append({"url": url, "quote": str(item.get("quote") or "")[:240], "stance": item_stance})
    return {"stance": stance, "answer": " ".join(str(data.get("answer") or "").split())[:400], "evidence": evidence}


def ask(prompt: str) -> dict:
    """Name who is shown. Research lite, because the titles do not fit in Answer."""
    if not config.key("YDC_API_KEY") or not (prompt or "").strip():
        return {"status": "skipped", "text": ""}
    result = _research(prompt)
    return {"status": result["status"], "text": result.get("text") or ""}


def _answer(query: str, hits: list | None = None, questions: list | None = None) -> dict:
    started = time.perf_counter()
    if questions:
        lines = []
        for hit in (hits or [])[:8]:
            lines.append(
                f"- {hit.get('title') or ''} ({hit.get('url') or ''}): {(hit.get('excerpt') or '')[:360]}"
            )
        asked = "; ".join(str(item.get("text") or "") for item in questions if item.get("text"))
        question = (
            "Answer these questions from the retrieved sources only. "
            "Say who or what is shown, then the key facts. "
            "If a credible outlet only speculates about a divorce, say they are not reported divorced "
            "and that there is no filing or announcement. Do not treat a rumor site as proof. "
            f"Questions: {asked}\nSources:\n" + "\n".join(lines)
        )[:6000]
    else:
        question = _clip_query(
            "Is this claim true, false, or misleading based on credible reporting? "
            "Note if the timing or the context does not match. Cite sources. "
            f"Claim: {query}"
        )
    if questions or config.flag("YDC_USE_RESEARCH"):
        result = _research(question)
        elapsed = _ms(started)
        result["latency_ms"] = elapsed
        sponsors.record(
            "youcom_answer",
            called=True,
            latency_ms=elapsed,
            citations=len(result.get("citations") or []),
            status=result["status"],
        )
        return result

    question = _clip_query(question)
    status, body = httputil.post_json(
        ANSWER_URL,
        _headers(),
        {"query": question, "freshness": "week"},
        timeout=35,
    )
    elapsed = _ms(started)
    if status != 200 or not isinstance(body, dict):
        sponsors.record("youcom_answer", called=True, latency_ms=elapsed, citations=0, status="error")
        return {
            "status": "error",
            "detail": f"You.com answer returned HTTP {status}.",
            "text": "",
            "citations": [],
            "kind": "answer",
            "latency_ms": elapsed,
        }
    citations = []
    for item in body.get("citations") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("source") or item.get("url") or "")
        excerpts = item.get("excerpts") or []
        excerpt = excerpts[0] if excerpts else ""
        if url.startswith("http"):
            citations.append({"url": url, "title": "", "excerpt": str(excerpt)[:400]})
    sponsors.record("youcom_answer", called=True, latency_ms=elapsed, citations=len(citations), status="ok")
    return {
        "status": "ok",
        "detail": "Answer API.",
        "text": repair_text(str(body.get("answer") or "")[:1200]),
        "citations": citations,
        "kind": "answer",
        "latency_ms": elapsed,
    }


def _merge_pages(hits: list[dict], pages: list[dict]) -> None:
    by_url = {page["url"]: page for page in pages if page.get("url")}
    for hit in hits:
        page = by_url.get(hit["url"])
        if not page:
            continue
        if page.get("excerpt") and len(page["excerpt"]) > len(hit.get("excerpt") or ""):
            hit["excerpt"] = page["excerpt"]
            hit["found_by"] = "You.com Contents"
        if page.get("title") and hit["title"] == urlparse(hit["url"]).netloc:
            hit["title"] = page["title"]


def iter_investigate(query: str, questions: list | None = None):
    empty_search = {"status": "skipped", "detail": "", "hits": [], "knowledge": ""}
    empty_contents = {"status": "skipped", "detail": "", "pages": []}
    empty_answer = {"status": "skipped", "detail": "", "text": "", "citations": [], "kind": "answer"}
    if not config.key("YDC_API_KEY"):
        detail = "YDC_API_KEY is not set."
        empty_search["detail"] = detail
        empty_contents["detail"] = detail
        empty_answer["detail"] = detail
        yield "search", empty_search
        yield "contents", empty_contents
        yield "answer", empty_answer
        return
    query = (query or "").strip()
    if not query:
        detail = "No claim to search."
        empty_search["detail"] = detail
        empty_contents["detail"] = detail
        empty_answer["detail"] = detail
        yield "search", empty_search
        yield "contents", empty_contents
        yield "answer", empty_answer
        return

    try:
        search = _search(query)
    except Exception:
        search = {"status": "error", "detail": "You.com search failed.", "hits": [], "knowledge": ""}
    yield "search", search

    urls = []
    for hit in search.get("hits") or []:
        if hit["url"] not in urls:
            urls.append(hit["url"])

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            contents_f = pool.submit(_contents, urls[:3])
            answer_f = pool.submit(_answer, query, search.get("hits") or [], questions)
            contents = contents_f.result()
            answer = answer_f.result()
    except Exception:
        contents = {"status": "error", "detail": "You.com contents failed.", "pages": []}
        answer = {"status": "error", "detail": "You.com synthesis failed.", "text": "", "citations": [], "kind": "answer"}

    _merge_pages(search.get("hits") or [], contents.get("pages") or [])
    yield "contents", contents
    yield "answer", answer


def investigate(query: str) -> dict:
    web = {}
    for name, data in iter_investigate(query):
        web[name] = data
    return web
