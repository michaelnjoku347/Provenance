"""You.com search, contents, and cited synthesis (Answer, or Research when asked)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from app import config, httputil

SEARCH_URL = "https://ydc-index.io/v1/search"
CONTENTS_URL = "https://ydc-index.io/v1/contents"
ANSWER_URL = "https://api.you.com/v1/answer"
RESEARCH_URL = "https://api.you.com/v1/research"


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
    return " ".join(text.split())[:700]


def _hit(item: dict, bucket: str) -> dict | None:
    if not isinstance(item, dict):
        return None
    url = str(item.get("url") or item.get("source") or "").strip()
    if not url.startswith("http"):
        return None
    title = str(item.get("title") or urlparse(url).netloc or "Source").strip()
    return {
        "url": url,
        "title": title[:180],
        "excerpt": _excerpt(item),
        "page_age": str(item.get("page_age") or "")[:40],
        "bucket": bucket,
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


def _search(query: str) -> dict:
    payload = {
        "query": query,
        "count": 10,
        "extraction": {"extraction_mode": "highlights"},
        "knowledge": "core",
        "freshness": "week",
    }
    status, body = httputil.post_json(SEARCH_URL, _headers(), payload, timeout=25)
    if status >= 400:
        payload.pop("freshness", None)
        status, body = httputil.post_json(SEARCH_URL, _headers(), payload, timeout=25)
    if status != 200 or not isinstance(body, dict):
        return {"status": "error", "detail": f"You.com search returned HTTP {status}.", "hits": []}
    hits = _parse_search(body)
    knowledge = ""
    for item in (body.get("results") or {}).get("knowledge") or []:
        if isinstance(item, dict) and item.get("description"):
            knowledge = str(item["description"])[:400]
            break
    return {
        "status": "ok",
        "detail": f"{len(hits)} results.",
        "hits": hits,
        "knowledge": knowledge,
    }


def _parse_pages(body: dict) -> list[dict]:
    if not isinstance(body, dict):
        return []
    rows = body.get("results") or body.get("data") or body.get("contents") or []
    if isinstance(rows, dict):
        rows = list(rows.values())
    pages = []
    if not isinstance(rows, list):
        return pages
    for row in rows:
        if not isinstance(row, dict):
            continue
        markdown = row.get("markdown") or ""
        if isinstance(markdown, dict):
            markdown = markdown.get("content") or markdown.get("text") or ""
        meta = row.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        text = str(markdown or meta.get("description") or "")
        pages.append(
            {
                "url": str(row.get("url") or ""),
                "title": str(meta.get("title") or meta.get("ogTitle") or "")[:180],
                "excerpt": " ".join(text.split())[:700],
            }
        )
    return pages


def _contents(urls: list[str]) -> dict:
    if not urls:
        return {"status": "skipped", "detail": "No result URLs to read.", "pages": []}
    payload = {"urls": urls[:3], "formats": ["markdown", "metadata"]}
    status, body = httputil.post_json(CONTENTS_URL, _headers(), payload, timeout=25)
    if status != 200 or not isinstance(body, dict):
        return {"status": "error", "detail": f"You.com contents returned HTTP {status}.", "pages": []}
    pages = _parse_pages(body)
    return {"status": "ok", "detail": f"Read {len(pages)} pages.", "pages": pages}


def _answer(query: str) -> dict:
    question = (
        "Is this claim being reported right now by credible news outlets? "
        "Say whether the depicted event looks real, AI-generated, or like an old image "
        f"used out of context. Cite sources. Claim: {query}"
    )[:1500]
    if config.flag("YDC_USE_RESEARCH"):
        status, body = httputil.post_json(
            RESEARCH_URL,
            _headers(),
            {"input": question, "research_effort": "lite"},
            timeout=25,
        )
        if status != 200 or not isinstance(body, dict):
            return {
                "status": "error",
                "detail": f"You.com research returned HTTP {status}.",
                "text": "",
                "citations": [],
                "kind": "research",
            }
        output = body.get("output") or {}
        content = output.get("content") if isinstance(output, dict) else ""
        if not isinstance(content, str):
            content = ""
        citations = []
        for source in (output.get("sources") or []) if isinstance(output, dict) else []:
            if isinstance(source, dict) and source.get("url"):
                citations.append(
                    {
                        "url": source["url"],
                        "title": source.get("title") or "",
                        "excerpt": " ".join(source.get("snippets") or [])[:400]
                        if isinstance(source.get("snippets"), list)
                        else str(source.get("snippet") or "")[:400],
                    }
                )
        return {
            "status": "ok",
            "detail": "Research API lite.",
            "text": content[:1200],
            "citations": citations,
            "kind": "research",
        }

    status, body = httputil.post_json(
        ANSWER_URL,
        _headers(),
        {"query": question, "freshness": "week"},
        timeout=35,
    )
    if status != 200 or not isinstance(body, dict):
        return {
            "status": "error",
            "detail": f"You.com answer returned HTTP {status}.",
            "text": "",
            "citations": [],
            "kind": "answer",
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
    return {
        "status": "ok",
        "detail": "Answer API.",
        "text": str(body.get("answer") or "")[:1200],
        "citations": citations,
        "kind": "answer",
    }


def _merge_pages(hits: list[dict], pages: list[dict]) -> None:
    by_url = {page["url"]: page for page in pages if page.get("url")}
    for hit in hits:
        page = by_url.get(hit["url"])
        if not page:
            continue
        if page.get("excerpt") and len(page["excerpt"]) > len(hit.get("excerpt") or ""):
            hit["excerpt"] = page["excerpt"]
        if page.get("title") and hit["title"] == urlparse(hit["url"]).netloc:
            hit["title"] = page["title"]


def investigate(query: str) -> dict:
    empty_search = {"status": "skipped", "detail": "", "hits": [], "knowledge": ""}
    empty_contents = {"status": "skipped", "detail": "", "pages": []}
    empty_answer = {"status": "skipped", "detail": "", "text": "", "citations": [], "kind": "answer"}
    if not config.key("YDC_API_KEY"):
        detail = "YDC_API_KEY is not set."
        empty_search["detail"] = detail
        empty_contents["detail"] = detail
        empty_answer["detail"] = detail
        return {"search": empty_search, "contents": empty_contents, "answer": empty_answer}
    query = (query or "").strip()
    if not query:
        detail = "No claim to search."
        empty_search["detail"] = detail
        empty_contents["detail"] = detail
        empty_answer["detail"] = detail
        return {"search": empty_search, "contents": empty_contents, "answer": empty_answer}

    try:
        search = _search(query)
    except Exception:
        search = {"status": "error", "detail": "You.com search failed.", "hits": [], "knowledge": ""}

    urls = []
    for hit in search.get("hits") or []:
        if hit["url"] not in urls:
            urls.append(hit["url"])

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            contents_f = pool.submit(_contents, urls[:3])
            answer_f = pool.submit(_answer, query)
            contents = contents_f.result()
            answer = answer_f.result()
    except Exception:
        contents = {"status": "error", "detail": "You.com contents failed.", "pages": []}
        answer = {"status": "error", "detail": "You.com synthesis failed.", "text": "", "citations": [], "kind": "answer"}

    _merge_pages(search.get("hits") or [], contents.get("pages") or [])
    return {"search": search, "contents": contents, "answer": answer}
