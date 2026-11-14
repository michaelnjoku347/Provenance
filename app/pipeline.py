"""Run one check from image bytes to a receipt."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Iterator

from app import config, credentials, detector, explain, links, reverse_image, samples, store, verdict, vision, youcom


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
    digest.update(b"\0claim-v2")
    return digest.hexdigest()


def _stage(stage_id: str, status: str, label: str, detail: str = "", flags: list | None = None) -> dict:
    return {
        "event": "stage",
        "data": {
            "id": stage_id,
            "status": status,
            "label": label,
            "detail": detail,
            "flags": flags or [],
        },
    }


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


def _assemble(image, media_type, claim_text, image_url, demo_id, filename, cache_key, creds, prior, claim, vision_stage, web, reverse, link=None) -> dict:
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
        "mode": "demo" if demo_id else "upload",
        "checked_at": checked_at,
        "receipt_id": cache_key[:12],
        "cache": {"hit": False, "key": cache_key[:12]},
    }
    if demo_id:
        result["preview_url"] = f"/api/demos/{demo_id}/image"
    elif not image and link.get("image_url"):
        result["preview_url"] = link["image_url"]
    if link.get("kind"):
        result["link"] = _link_card(link)
        result["stages"]["link"] = {"status": link.get("status") or "error", "detail": link.get("detail") or ""}
    explain.attach(result, image_url)
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
    if image_url.startswith("http") and not links.is_direct_image(image_url):
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

    yield _stage("vision", "running", "Reading the claim", "Using the caption, or a vision model if one is configured.")
    claim, vision_stage = vision.extract(image, media_type, claim_text)
    if link.get("search_query") and vision_stage.get("status") != "ok":
        claim["search_query"] = str(link["search_query"])[:300]
    yield _stage("vision", vision_stage["status"], "Read the claim", vision_stage.get("detail") or claim.get("text") or "", [{"label": (claim.get("text") or "No claim")[:80], "tone": "neutral"}])

    query = (claim.get("search_query") or claim.get("text") or "").strip()
    if query.lower().startswith("no caption"):
        query = ""

    yield _stage("youcom_search", "running", "Searching You.com", "Looking for reporting, fact-checks, and similar claims.")
    yield _stage("reverse_image", "running", "Reverse image lookup", "Only runs when a public image URL is provided.")

    web = {"search": {}, "contents": {}, "answer": {}}
    reverse = {"status": "error", "detail": "Reverse image failed.", "matches": [], "tool": ""}
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            reverse_url = image_url
            if link.get("kind") == "status":
                reverse_url = link.get("image_url") or ""
            elif link.get("kind") == "article":
                reverse_url = ""
            rev_f = pool.submit(reverse_image.lookup, reverse_url)
            for name, data in youcom.iter_investigate(query):
                web[name] = data
                if name == "search":
                    yield _stage("youcom_search", data["status"], "Searched You.com", data.get("detail") or "", _search_flags(data))
                    yield _stage("youcom_contents", "running", "Reading sources", "Pulling page text from the top results.")
                    yield _stage("youcom_answer", "running", "Cited synthesis", "Asking You.com to weigh the reporting.")
                elif name == "contents":
                    yield _stage("youcom_contents", data["status"], "Read sources", data.get("detail") or "")
                elif name == "answer":
                    flags = []
                    if data.get("text"):
                        flags.append({"label": data["text"][:80], "tone": "neutral"})
                    yield _stage("youcom_answer", data["status"], "Cited synthesis", data.get("detail") or data.get("text") or "", flags)
            reverse = rev_f.result()
    except Exception:
        web = {
            "search": {"status": "error", "detail": "You.com failed.", "hits": []},
            "contents": _stage_error("Contents"),
            "answer": {"status": "error", "detail": "Synthesis failed.", "text": "", "citations": []},
        }
        reverse = {"status": "error", "detail": "Reverse image failed.", "matches": [], "tool": ""}
        yield _stage("youcom_search", "error", "Search failed", "You.com failed.")
        yield _stage("youcom_contents", "error", "Could not read sources", "Contents failed.")
        yield _stage("youcom_answer", "error", "Synthesis failed", "Answer failed.")

    matches = reverse.get("matches") or []
    rev_flags = [{"label": m.get("title") or m.get("url") or "Match", "tone": "neutral"} for m in matches[:3]]
    yield _stage("reverse_image", reverse["status"], "Reverse image", reverse.get("detail") or "", rev_flags)

    yield _stage("verdict", "running", "Judging the claim", "Comparing sources and dates with what the claim says.")
    result = _assemble(
        image, media_type, claim_text, image_url, demo_id, filename, cache_key, creds, prior, claim, vision_stage, web, reverse, link
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
