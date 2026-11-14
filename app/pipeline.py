"""Run one check from image bytes to a receipt."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app import config, credentials, detector, reverse_image, samples, store, verdict, vision, youcom


def _stage_error(name: str) -> dict:
    return {"status": "error", "detail": f"{name} failed."}


def run(
    image: bytes,
    media_type: str,
    claim_text: str,
    image_url: str = "",
    demo_id: str | None = None,
    filename: str = "",
) -> dict:
    claim_text = (claim_text or "").strip()[:2000]
    image_url = (image_url or "").strip()
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
    cache_key = digest.hexdigest()
    cached = store.get(cache_key)
    if cached:
        cached = dict(cached)
        cached["cache"] = {"hit": True, "key": cache_key[:12]}
        return cached

    creds = credentials.inspect(image)
    prior = detector.score(image, creds)
    claim, vision_stage = vision.extract(image, media_type, claim_text)
    query = (claim.get("search_query") or claim.get("text") or "").strip()
    if query.lower().startswith("no caption"):
        query = ""

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            web_f = pool.submit(youcom.investigate, query)
            rev_f = pool.submit(reverse_image.lookup, image_url)
            web = web_f.result()
            reverse = rev_f.result()
    except Exception:
        web = {
            "search": {"status": "error", "detail": "You.com failed.", "hits": []},
            "contents": _stage_error("Contents"),
            "answer": {"status": "error", "detail": "Synthesis failed.", "text": "", "citations": []},
        }
        reverse = {"status": "error", "detail": "Reverse image failed.", "matches": [], "tool": ""}

    decision = verdict.decide(claim, creds, web, reverse, prior)
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = {
        "verdict": decision["verdict"],
        "confidence": decision["confidence"],
        "summary": decision["summary"],
        "claim": claim,
        "clues": decision["clues"],
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
    statuses = [stage["status"] for stage in result["stages"].values()]
    if "error" not in statuses:
        store.put(cache_key, result)
    return result


def run_request(payload: dict) -> dict:
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
    if not image:
        raise ValueError("Send an image as base64, a multipart file, or a demo_id.")
    return run(
        image=image,
        media_type=media_type,
        claim_text=claim,
        image_url=payload.get("image_url") or "",
        demo_id=demo_id,
        filename=filename,
    )
