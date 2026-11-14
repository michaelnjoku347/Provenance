"""Run one check from image bytes to a receipt."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Iterator

from app import config, credentials, detector, explain, httputil, links, questions, reverse_image, samples, see, sponsors, store, verdict, youcom


def _stage_error(name: str) -> dict:
    return {"status": "error", "detail": f"{name} failed."}


def _cache_key(image: bytes, claim_text: str, image_url: str) -> str:
    flags = "".join(
        [
            "o" if config.key("OPENAI_API_KEY") else "-",
            "g" if config.key("GEMINI_API_KEY") else "-",
            "y" if config.key("YDC_API_KEY") else "-",
            "t" if config.key("TREG_API_KEY") else "-",
            "r" if config.flag("YDC_USE_RESEARCH") else "-",
        ]
    )
    digest = hashlib.sha256()
    digest.update(image)
    digest.update(b"\0")
    digest.update(claim_text.encode())
    digest.update(b"\0")
    digest.update(image_url.encode())
    digest.update(b"\0")
    digest.update(flags.encode())
    digest.update(b"\0claim-v4")
    return digest.hexdigest()


def _stage(
    stage_id: str,
    status: str,
    label: str,
    detail: str = "",
    flags: list | None = None,
    sponsor: str = "",
    stats: dict | None = None,
) -> dict:
    data = {
        "id": stage_id,
        "status": status,
        "label": label,
        "detail": detail,
        "flags": flags or [],
    }
    if sponsor:
        data["sponsor"] = sponsor
    if stats:
        data["stats"] = stats
    return {"event": "stage", "data": data}


def _credential_flags(creds: dict) -> list[dict]:
    flags = []
    exif = creds.get("exif") or {}
    c2pa = creds.get("c2pa") or {}
    if exif.get("make") or exif.get("model"):
        flags.append({"label": " ".join(part for part in (exif.get("make"), exif.get("model")) if part), "tone": "real"})
    if exif.get("datetime"):
        flags.append({"label": f"Captured {exif['datetime']}", "tone": "neutral"})
    if creds.get("software_generative") or c2pa.get("generative"):
        flags.append({"label": f"Weak: {exif.get('software') or 'Generative marker'}", "tone": "neutral"})
    elif c2pa.get("present"):
        flags.append({"label": "C2PA present", "tone": "real"})
    else:
        flags.append({"label": "No C2PA", "tone": "neutral"})
    return flags


def _search_flags(search: dict) -> list[dict]:
    flags = []
    for hit in (search.get("hits") or [])[:4]:
        flags.append({"label": hit.get("title") or hit.get("url") or "Source", "tone": "neutral", "url": hit.get("url") or ""})
    return flags


def _link_card(link: dict) -> dict:
    return {
        "kind": link.get("kind") or "",
        "status": link.get("status") or "",
        "url": link.get("url") or "",
        "author": link.get("author") or "",
        "author_url": link.get("author_url") or "",
        "posted_at": link.get("posted_at") or "",
        "text": (link.get("text") or "")[:1000],
        "title": link.get("title") or "",
        "image_url": link.get("image_url") or "",
        "detail": link.get("detail") or "",
    }


def _download_image(image_url: str) -> tuple[bytes, str]:
    """Fetch a public image so EXIF, vision, and the hash see the real bytes."""
    try:
        status, data, media = httputil.get_bytes(image_url, timeout=20)
    except Exception:
        return b"", ""
    if status != 200 or not data or len(data) > 8_000_000:
        return b"", ""
    if data[:3] == b"\xff\xd8\xff":
        media = "image/jpeg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        media = "image/png"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        media = "image/webp"
    elif not media.startswith("image/"):
        return b"", ""
    return data, media or "image/jpeg"


def _assemble(image, media_type, claim_text, image_url, demo_id, filename, cache_key, creds, prior, claim, vision_stage, web, reverse, link=None, subject=None, image_from_url=False) -> dict:
    link = link or {}
    decision = verdict.decide(claim, creds, web, reverse, prior, posted_at=link.get("posted_at") or "")
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = {
        "verdict": decision["verdict"],
        "confidence": decision["confidence"],
        "summary": decision["summary"],
        "claim": claim,
        "clues": decision["clues"],
        "contributions": decision.get("contributions") or [],
        "timeline": decision["timeline"],
        "sources": decision["sources"],
        "scores": decision["scores"],
        "stages": {
            "vision": vision_stage,
            "credentials": {"status": creds["status"], "detail": creds["detail"]},
            "youcom_search": {"status": web["search"]["status"], "detail": web["search"].get("detail", "")},
            "youcom_contents": {
                "status": web["contents"]["status"],
                "detail": web["contents"].get("detail", ""),
            },
            "youcom_answer": {"status": web["answer"]["status"], "detail": web["answer"].get("detail", "")},
            "reverse_image": {"status": reverse["status"], "detail": reverse.get("detail", "")},
            "detector": {"status": prior["status"], "detail": prior["note"]},
        },
        "credentials": {
            "exif": creds["exif"],
            "c2pa": {
                "present": creds["c2pa"]["present"],
                "generative": creds["c2pa"]["generative"],
                "camera": creds["c2pa"]["camera"],
            },
        },
        "detector": {
            "score": prior["score"],
            "label": prior["label"],
            "method": prior["method"],
            "note": prior["note"],
        },
        "synthesis": {
            "kind": web["answer"].get("kind") or "answer",
            "text": (web["answer"].get("text") or "")[:800],
        },
        "image_sha256": hashlib.sha256(image).hexdigest(),
        "filename": filename,
        "demo_id": demo_id,
        "mode": "demo" if demo_id else ("url" if image_from_url else "upload"),
        "checked_at": checked_at,
        "receipt_id": cache_key[:12],
        "cache": {"hit": False, "key": cache_key[:12]},
        "sponsors": sponsors.receipt(web, reverse),
    }
    if demo_id:
        result["preview_url"] = f"/api/demos/{demo_id}/image"
    elif not image and link.get("image_url"):
        result["preview_url"] = link["image_url"]
    if link.get("kind"):
        result["link"] = _link_card(link)
        result["stages"]["link"] = {"status": link.get("status") or "error", "detail": link.get("detail") or ""}
    explain.attach(result, image_url)
    try:
        answer = questions.compose(claim.get("text") or claim_text, result, web, reverse, subject or {})
    except Exception:
        answer = {}
    if answer:
        result["answer"] = answer
        if (subject or {}).get("questions"):
            result["verdict"] = answer["verdict"]
            result["summary"] = answer["text"]
            result["confidence"] = answer["confidence"]
    statuses = [stage["status"] for stage in result["stages"].values()]
    if "error" not in statuses:
        store.put(cache_key, result)
    return result


def iter_run(
    image: bytes,
    media_type: str,
    claim_text: str,
    image_url: str = "",
    demo_id: str | None = None,
    filename: str = "",
) -> Iterator[dict]:
    claim_text = (claim_text or "").strip()[:2000]
    image_url = (image_url or "").strip()
    image_from_url = False
    if not image and image_url.startswith("http") and not links.is_status_url(image_url):
        fetched, fetched_type = _download_image(image_url)
        if fetched:
            image = fetched
            media_type = fetched_type or media_type
            image_from_url = True
    cache_key = _cache_key(image, claim_text, image_url)
    cached = store.get(cache_key)
    if cached:
        cached = dict(cached)
        cached["cache"] = {"hit": True, "key": cache_key[:12]}
        explain.attach(cached, image_url)
        yield {"event": "cache", "data": {"hit": True, "key": cache_key[:12]}}
        yield {"event": "result", "data": cached}
        return

    link: dict = {}
    if image_url.startswith("http") and not links.is_direct_image(image_url) and not image_from_url:
        yield _stage("link", "running", "Reading the link", "X posts and article pages can supply the claim.")
        try:
            link = links.resolve(image_url)
        except Exception:
            link = {
                "kind": "status" if links.is_status_url(image_url) else "article",
                "status": "error",
                "url": image_url,
                "detail": "The link could not be read. Paste the claim instead.",
            }
        if not claim_text and link.get("claim"):
            claim_text = link["claim"]
        flags = []
        if link.get("author"):
            flags.append({"label": link["author"], "tone": "neutral"})
        if link.get("posted_at"):
            flags.append({"label": f"Posted {link['posted_at'][:10]}", "tone": "neutral"})
        elif link.get("title"):
            flags.append({"label": link["title"][:80], "tone": "neutral"})
        yield _stage(
            "link",
            "ok" if link.get("status") == "ok" else "error",
            "Read the link",
            link.get("detail") or "",
            flags,
        )

    yield _stage("credentials", "running", "Reading the file", "Checking EXIF, software tags, and C2PA." if image else "No file attached.")
    creds = credentials.inspect(image)
    yield _stage("credentials", creds["status"], "Read EXIF and C2PA", creds["detail"], _credential_flags(creds))

    yield _stage("detector", "running", "Weighing AI-image prior", "A local prior, not a lab detector.")
    prior = detector.score(image, creds)
    yield _stage(
        "detector",
        prior["status"],
        "Weighed AI-image prior",
        prior["note"],
        [{"label": f"Weak prior {prior['score']:.2f}", "tone": "neutral"}],
    )

    yield _stage("vision", "running", "SEE", "Describing the image, its subject, and any text.", sponsor="see")
    try:
        seen = see.describe(image_url, image, media_type, claim_text)
    except Exception:
        seen = {
            "status": "error",
            "text": "",
            "provider": "",
            "detail": "Vision step unavailable. The check continued.",
            "latency_ms": 0,
        }
    reverse = None
    reverse_url = image_url
    if link.get("kind") == "status":
        reverse_url = link.get("image_url") or ""
    elif link.get("kind") == "article":
        reverse_url = ""
    if not seen.get("text") and reverse_url.startswith("http"):
        try:
            reverse = reverse_image.lookup(reverse_url)
        except Exception:
            reverse = {"status": "error", "detail": "Treg reverse-image request failed.", "matches": [], "tool": "", "latency_ms": 0}
        try:
            fallback = see.from_matches(reverse.get("matches") or [], claim_text)
        except Exception:
            fallback = {"text": ""}
        if fallback.get("text"):
            seen = fallback
        elif "continued" not in (seen.get("detail") or "").lower():
            seen["detail"] = ((seen.get("detail") or "Vision step unavailable.") + " The check continued.").strip()
    claim = {
        "text": claim_text,
        "who": "",
        "what": seen.get("what") or "",
        "where": "",
        "when": "",
        "search_query": (seen.get("text") or claim_text or "")[:300],
        "source": "vision" if seen.get("text") else ("caption" if claim_text else "none"),
        "seen": seen.get("text") or "",
    }
    if link.get("search_query") and not seen.get("text"):
        claim["search_query"] = str(link["search_query"])[:300]
    vision_stage = {"status": seen.get("status") or "skipped", "detail": seen.get("detail") or ""}
    yield _stage(
        "vision",
        vision_stage["status"],
        "SEE",
        vision_stage["detail"],
        [{"label": (seen.get("text") or "Vision unavailable")[:80], "tone": "neutral"}],
        sponsor="see",
        stats={"latency_ms": int(seen.get("latency_ms") or 0), "provider": seen.get("provider") or ""},
    )

    query = (claim.get("search_query") or claim.get("text") or "").strip()
    if query.lower().startswith("no caption"):
        query = ""

    yield _stage("reverse_image", "running", "FIND", "Treg reverse image and earlier appearances.", sponsor="find")

    if reverse is None and reverse_url.startswith("http"):
        try:
            reverse = reverse_image.lookup(reverse_url)
        except Exception:
            reverse = {"status": "error", "detail": "Treg reverse-image request failed.", "matches": [], "tool": "", "latency_ms": 0}
    elif reverse is None:
        reverse = {
            "status": "skipped",
            "detail": "Reverse image needs a public image URL.",
            "matches": [],
            "tool": "",
            "latency_ms": 0,
        }
    matches = reverse.get("matches") or []
    rev_flags = [{"label": m.get("title") or m.get("url") or "Match", "tone": "neutral"} for m in matches[:3]]
    if not matches and "add key" in (reverse.get("detail") or ""):
        rev_flags = [{"label": "Treg: add key", "tone": "neutral"}]
    yield _stage(
        "reverse_image",
        reverse.get("status") or "error",
        "FIND",
        reverse.get("detail") or "",
        rev_flags,
        sponsor="treg",
        stats={"latency_ms": int(reverse.get("latency_ms") or 0), "matches": len(matches)},
    )

    subject = {}
    try:
        context = ""
        if image_url.startswith("http") and not links.is_direct_image(image_url):
            context = ""
        subject = questions.identify(claim.get("text") or claim_text, matches, f"{context} {claim.get('seen') or ''}", claim.get("what") or "")
        if claim.get("seen"):
            subject["seen"] = claim["seen"]
    except Exception:
        subject = {}
    if subject.get("query") and subject.get("questions"):
        query = subject["query"]
        claim["search_query"] = query

    yield _stage("youcom_search", "running", "PROVE", query or "Searching credible sources for the claim.", sponsor="prove")

    web = {"search": {}, "contents": {}, "answer": {}}
    try:
        for name, data in youcom.iter_investigate(query, subject.get("questions") or None):
            web[name] = data
            if name == "search":
                yield _stage(
                    "youcom_search",
                    data["status"],
                    "PROVE",
                    data.get("detail") or "",
                    _search_flags(data),
                    sponsor="youcom_search",
                    stats={"latency_ms": int(data.get("latency_ms") or 0), "results": len(data.get("hits") or [])},
                )
                yield _stage(
                    "youcom_contents",
                    "running",
                    "You.com Contents",
                    "Pulling page text from the top results.",
                    sponsor="youcom_contents",
                )
                synthesis = "You.com Research" if subject.get("questions") else "You.com Answer"
                yield _stage(
                    "youcom_answer",
                    "running",
                    synthesis,
                    "Asking You.com for a cited synthesis.",
                    sponsor="youcom_answer",
                )
            elif name == "contents":
                yield _stage(
                    "youcom_contents",
                    data["status"],
                    "You.com Contents",
                    data.get("detail") or "",
                    sponsor="youcom_contents",
                    stats={"latency_ms": int(data.get("latency_ms") or 0), "pages": len(data.get("pages") or [])},
                )
            elif name == "answer":
                flags = []
                if data.get("text"):
                    flags.append({"label": data["text"][:80], "tone": "neutral"})
                yield _stage(
                    "youcom_answer",
                    data["status"],
                    "You.com Research" if data.get("kind") == "research" else "You.com Answer",
                    data.get("detail") or data.get("text") or "",
                    flags,
                    sponsor="youcom_answer",
                    stats={"latency_ms": int(data.get("latency_ms") or 0), "citations": len(data.get("citations") or [])},
                )
    except Exception:
        web = {
            "search": {"status": "error", "detail": "You.com failed.", "hits": []},
            "contents": _stage_error("Contents"),
            "answer": {"status": "error", "detail": "Synthesis failed.", "text": "", "citations": []},
        }
        yield _stage("youcom_search", "error", "Search failed", "You.com failed.")
        yield _stage("youcom_contents", "error", "Could not read sources", "Contents failed.")
        yield _stage("youcom_answer", "error", "Synthesis failed", "Answer failed.")

    paywall = config.paywall_on()
    yield _stage(
        "x402",
        "ok" if paywall else "skipped",
        "XDC x402",
        "Pay-per-verify is armed." if paywall else "Test mode. This desk check is not charged.",
        [{"label": "Live" if paywall else "Test mode", "tone": "neutral"}],
        sponsor="x402",
        stats={"mode": "live" if paywall else "test", "price_usdc": sponsors.receipt({}, {}).get("x402", {}).get("price_usdc", "0.02")},
    )

    yield _stage("verdict", "running", "Judging the claim", "Comparing sources and dates with what the claim says.")
    result = _assemble(
        image, media_type, claim_text, image_url, demo_id, filename, cache_key, creds, prior, claim, vision_stage, web, reverse, link, subject, image_from_url
    )
    tone = "real" if result["verdict"] == "True" else "fake" if result["verdict"] == "False" else "verdict"
    yield _stage(
        "verdict",
        "ok",
        "Judged the claim",
        result["summary"],
        [{"label": result["verdict"], "tone": tone}],
    )
    yield {"event": "result", "data": result}


def run(
    image: bytes,
    media_type: str,
    claim_text: str,
    image_url: str = "",
    demo_id: str | None = None,
    filename: str = "",
) -> dict:
    final = None
    for ev in iter_run(
        image=image,
        media_type=media_type,
        claim_text=claim_text,
        image_url=image_url,
        demo_id=demo_id,
        filename=filename,
    ):
        if ev["event"] == "result":
            final = ev["data"]
    if final is None:
        raise RuntimeError("check produced no result")
    return final


def _prepare_request(payload: dict) -> dict:
    demo_id = (payload.get("demo_id") or "").strip() or None
    image = payload.get("image_bytes") or b""
    media_type = payload.get("media_type") or "image/jpeg"
    filename = payload.get("filename") or ""
    claim = payload.get("claim") or ""
    if demo_id and not image:
        sample = samples.get(demo_id)
        if sample is None:
            raise ValueError("Unknown demo_id.")
        image = sample["bytes"]
        filename = filename or f"{demo_id}.jpg"
        if not str(claim).strip():
            claim = sample["claim"]
    image_url = str(payload.get("image_url") or "").strip()
    if not image and not str(claim).strip() and not image_url:
        raise ValueError("Send a claim, a link, an image, a file, or a demo_id.")
    return {
        "image": image,
        "media_type": media_type,
        "claim_text": claim,
        "image_url": image_url,
        "demo_id": demo_id,
        "filename": filename,
    }


def run_request(payload: dict) -> dict:
    return run(**_prepare_request(payload))


def iter_request(payload: dict) -> Iterator[dict]:
    yield from iter_run(**_prepare_request(payload))
