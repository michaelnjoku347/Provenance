"""Run one check from image bytes to a receipt."""

from __future__ import annotations

import hashlib
import queue
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, TimeoutError as FuturesTimeout, wait
from datetime import datetime, timezone
from typing import Iterator

from app import config, credentials, detector, explain, httputil, links, questions, reverse_image, samples, see, sponsors, store, treg, verdict, youcom

# One wall-clock budget for the whole check. Provider timeouts must not add up past this.
CHECK_DEADLINE_S = 20.0


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
    finding: str = "",
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
    if finding:
        data["finding"] = finding
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


def _download_image(image_url: str, timeout: float = 8.0) -> tuple[bytes, str]:
    """Fetch a public image so EXIF, vision, and the hash see the real bytes."""
    try:
        status, data, media = httputil.get_bytes(image_url, timeout=max(0.2, min(8.0, timeout)))
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


def _x_target(url: str) -> tuple[str, str]:
    if not links.is_status_url(url):
        return "", ""
    parts = [part for part in urlparse_path(url).split("/") if part]
    if len(parts) >= 3 and parts[1] == "status" and parts[2].isdigit() and parts[0].lower() not in {"i", "intent", "share"}:
        return parts[0], parts[2]
    return "", ""


def urlparse_path(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).path


def _safe_future(future):
    if future is None:
        return {"status": "skipped", "detail": "", "hits": [], "latency_ms": 0, "results": 0, "replies": [], "profile": {}}
    try:
        return future.result()
    except Exception:
        return {"status": "error", "detail": "Treg call failed. The check continued.", "hits": [], "latency_ms": 0, "results": 0, "replies": [], "profile": {}}


def _stage_row(result: dict) -> dict:
    return {
        "status": result.get("status") or "skipped",
        "detail": result.get("detail") or "",
        "latency_ms": int(result.get("latency_ms") or 0),
        "results": int(result.get("results") if result.get("results") is not None else len(result.get("hits") or result.get("replies") or [])),
    }


def _remaining(clock: float) -> float:
    return CHECK_DEADLINE_S - (time.monotonic() - clock)


def _open_pool() -> ThreadPoolExecutor:
    """Public executor only. Private ThreadPoolExecutor fields differ across 3.11–3.15."""
    return ThreadPoolExecutor(max_workers=8, thread_name_prefix="provenance")


def _blank_call(detail: str, status: str = "error") -> dict:
    return {
        "status": status,
        "detail": detail,
        "hits": [],
        "matches": [],
        "latency_ms": 0,
        "results": 0,
        "replies": [],
        "profile": {},
        "text": "",
        "citations": [],
        "pages": [],
        "knowledge": "",
        "tool": "",
        "knowledge_title": "",
        "provider": "",
        "what": "",
        "timed_out": status == "error" and "timed out" in detail.lower(),
    }


def _future_value(future, label: str) -> dict:
    try:
        value = future.result()
        return value if isinstance(value, dict) else _blank_call(f"{label} failed.")
    except Exception:
        return _blank_call(f"{label} failed. The check continued.")


def _finding(row: dict | None) -> str:
    row = row or {}
    for item in (row.get("hits") or row.get("matches") or [])[:1]:
        title = str(item.get("title") or item.get("url") or "").strip()
        if title:
            return title[:160]
    for reply in (row.get("replies") or [])[:1]:
        text = str(reply.get("text") or "").strip()
        if text:
            who = str(reply.get("user") or "").strip()
            return (f"@{who}: {text}" if who else text)[:160]
    profile = row.get("profile") or {}
    if profile.get("name") or profile.get("username"):
        return str(profile.get("name") or profile.get("username"))[:160]
    text = str(row.get("text") or row.get("detail") or "").strip()
    if text and not text.lower().startswith("treg:") and "timed out" not in text.lower():
        return text[:160]
    return ""


def _safe_resolve(image_url: str) -> dict:
    try:
        return links.resolve(image_url)
    except Exception:
        return {
            "kind": "status" if links.is_status_url(image_url) else "article",
            "status": "error",
            "url": image_url,
            "detail": "The link could not be read. Paste the claim instead.",
        }


def _pump_youcom(query: str, asked: list | None, sink: queue.Queue) -> None:
    try:
        for name, data in youcom.iter_investigate(query, asked):
            sink.put(("part", name, data))
        sink.put(("done", "", None))
    except Exception as exc:
        sink.put(("error", "", exc))


def _empty_web(search: dict | None = None, contents: dict | None = None, answer: dict | None = None) -> dict:
    return {
        "search": search or {"status": "skipped", "detail": "No claim to search.", "hits": [], "knowledge": ""},
        "contents": contents or {"status": "skipped", "detail": "No claim to search.", "pages": []},
        "answer": answer or {"status": "skipped", "detail": "No claim to search.", "text": "", "citations": [], "kind": "answer"},
    }


def _assemble(image, media_type, claim_text, image_url, demo_id, filename, cache_key, creds, prior, claim, vision_stage, web, reverse, link=None, subject=None, image_from_url=False, treg_extra=None, timed_out=None) -> dict:
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
            "reverse_image": {
                "status": reverse["status"],
                "detail": reverse.get("detail", ""),
                "latency_ms": int(reverse.get("latency_ms") or 0),
                "results": len(reverse.get("matches") or []),
            },
            "treg_news": _stage_row((treg_extra or {}).get("news") or {}),
            "treg_web": _stage_row((treg_extra or {}).get("web") or {}),
            "treg_profile": _stage_row((treg_extra or {}).get("profile") or {}),
            "treg_replies": _stage_row((treg_extra or {}).get("replies") or {}),
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
        "poster": ((treg_extra or {}).get("profile") or {}).get("profile") or {},
        "pushback": ((treg_extra or {}).get("replies") or {}).get("replies") or [],
    }
    if demo_id:
        result["preview_url"] = f"/api/demos/{demo_id}/image"
    elif not image and link.get("image_url"):
        result["preview_url"] = link["image_url"]
    if link.get("kind"):
        result["link"] = _link_card(link)
        result["stages"]["link"] = {"status": link.get("status") or "error", "detail": link.get("detail") or ""}
    if timed_out:
        names = [str(name) for name in timed_out if name]
        result["timed_out"] = names
        result["deadline_note"] = (
            "Stopped at the 20 second deadline with the best partial receipt. Timed out: " + ", ".join(names) + "."
        )
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


_STOP_HEADS = {"the", "a", "an", "this", "these", "that", "those", "two", "they", "it", "people", "couple", "man", "woman", "image", "photo", "no", "not", "unknown"}
_NAME_STOP = {"The", "This", "New", "Who", "What", "How", "Why", "CEO", "Nvidia", "NVIDIA", "Million", "Billion", "Settlement", "Divorce", "Gift", "State", "He", "She", "Used", "Service", "Repair", "Near", "Sale", "For", "Are", "Is"}


def _recurring_name(matches: list) -> str:
    """A person-style name (two capitalised words) that shows up in 2+ Lens match titles."""
    counts: dict = {}
    for m in matches:
        title = str(m.get("title") or "")
        seen = set()
        for a, b in re.findall(r"(?=\b([A-Z][a-z]{2,})\s+([A-Z][a-z]{2,})\b)", title):
            if a in _NAME_STOP or b in _NAME_STOP:
                continue
            seen.add(f"{a} {b}")
        for name in seen:
            counts[name] = counts.get(name, 0) + 1
    best = sorted(counts.items(), key=lambda kv: -kv[1])
    return best[0][0] if best and best[0][1] >= 2 else ""


def iter_run(
    image: bytes,
    media_type: str,
    claim_text: str,
    image_url: str = "",
    demo_id: str | None = None,
    filename: str = "",
    photo_url: bool = False,
) -> Iterator[dict]:
    clock = time.monotonic()
    claim_text = (claim_text or "").strip()[:2000]
    image_url = (image_url or "").strip()
    image_from_url = False
    if not image and image_url.startswith("http") and not links.is_status_url(image_url):
        fetched, fetched_type = _download_image(image_url, timeout=max(0.2, _remaining(clock)))
        if fetched:
            image = fetched
            media_type = fetched_type or media_type
            image_from_url = True
    if photo_url and image:
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

    pool = _open_pool()
    timed_out: list[str] = []
    held: dict = {}
    try:
        def submit(name: str, fn, *args):
            held[name] = pool.submit(fn, *args)

        def take_ready() -> list[tuple[str, object]]:
            ready = []
            for name, future in list(held.items()):
                if future.done():
                    ready.append((name, future))
                    del held[name]
            return ready

        def wait_some() -> None:
            left = _remaining(clock)
            if left <= 0 or not held:
                return
            wait(list(held.values()), timeout=min(0.15, left), return_when=FIRST_COMPLETED)

        def x_stage(kind: str, row: dict) -> dict:
            if kind == "profile":
                return _stage(
                    "treg_profile",
                    row.get("status") or "skipped",
                    "Treg X profile",
                    row.get("detail") or "",
                    sponsor="treg_profile",
                    stats={"latency_ms": int(row.get("latency_ms") or 0), "results": int(row.get("results") or 0)},
                    finding=_finding(row),
                )
            return _stage(
                "treg_replies",
                row.get("status") or "skipped",
                "Treg X replies",
                row.get("detail") or "",
                sponsor="treg_replies",
                stats={"latency_ms": int(row.get("latency_ms") or 0), "results": int(row.get("results") or len(row.get("replies") or []))},
                finding=_finding(row),
            )

        link: dict = {}
        profile_row = None
        replies_row = None
        emitted = set()
        need_link = image_url.startswith("http") and not links.is_direct_image(image_url) and not image_from_url
        early_url = image_url if links.is_status_url(image_url) else ""
        x_user, x_id = _x_target(early_url)
        if x_user:
            yield _stage("treg_profile", "running", "Treg X profile", f"@{x_user}", sponsor="treg_profile")
            submit("profile", treg.profile, x_user)
        if x_id:
            yield _stage("treg_replies", "running", "Treg X replies", "Reading replies for pushback.", sponsor="treg_replies")
            submit("replies", treg.comments, x_id, early_url)

        if need_link:
            yield _stage("link", "running", "Reading the link", "X posts and article pages can supply the claim.")
            submit("link", _safe_resolve, image_url)
            while "link" in held and _remaining(clock) > 0:
                for name, future in take_ready():
                    if name == "link":
                        link = _future_value(future, "Reading the link")
                    elif name == "profile":
                        profile_row = _future_value(future, "Treg X profile")
                        emitted.add("profile")
                        yield x_stage("profile", profile_row)
                    elif name == "replies":
                        replies_row = _future_value(future, "Treg X replies")
                        emitted.add("replies")
                        yield x_stage("replies", replies_row)
                if "link" not in held:
                    break
                wait_some()
            if "link" in held:
                del held["link"]
                timed_out.append("Reading the link")
                link = _blank_call("Reading the link timed out.")
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
                finding=(link.get("title") or link.get("author") or "")[:160],
            )

        if not x_user and not x_id:
            status_url = link.get("url") if links.is_status_url(link.get("url") or "") else ""
            x_user, x_id = _x_target(status_url)
            if x_user:
                yield _stage("treg_profile", "running", "Treg X profile", f"@{x_user}", sponsor="treg_profile")
                submit("profile", treg.profile, x_user)
            else:
                profile_row = _blank_call("", "skipped")
                emitted.add("profile")
                yield x_stage("profile", profile_row)
            if x_id:
                yield _stage("treg_replies", "running", "Treg X replies", "Reading replies for pushback.", sponsor="treg_replies")
                submit("replies", treg.comments, x_id, status_url)
            else:
                replies_row = _blank_call("", "skipped")
                emitted.add("replies")
                yield x_stage("replies", replies_row)

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

        reverse_url = image_url
        if link.get("kind") == "status":
            reverse_url = link.get("image_url") or ""
        elif link.get("kind") == "article":
            reverse_url = ""
        yield _stage("reverse_image", "running", "Treg Lens", "Identifying the photo from visual matches.", sponsor="treg_lens")
        yield _stage("vision", "running", "Gemini", "vision assist", sponsor="gemini")

        def _lens():
            if not reverse_url.startswith("http"):
                return {
                    "status": "skipped",
                    "detail": "Reverse image needs a public image URL.",
                    "matches": [],
                    "tool": "",
                    "latency_ms": 0,
                    "knowledge_title": "",
                }
            try:
                return reverse_image.lookup(reverse_url)
            except Exception:
                return {"status": "error", "detail": "Treg reverse-image request failed.", "matches": [], "tool": "", "latency_ms": 0, "knowledge_title": ""}

        def _assist(caption: str):
            try:
                return see.describe(image_url, image, media_type, caption)
            except Exception:
                return {
                    "status": "error",
                    "text": "",
                    "what": "",
                    "provider": "",
                    "detail": "Vision assist unavailable. The check continued.",
                    "latency_ms": 0,
                }

        submit("lens", _lens)
        submit("vision", _assist, claim_text)
        signals: dict = {}
        while ("lens" in held or "vision" in held) and _remaining(clock) > 0:
            for name, future in take_ready():
                if name == "lens":
                    signals["lens"] = _future_value(future, "Treg Lens")
                    title = ((signals["lens"].get("matches") or [{}])[0] or {}).get("title") or ""
                    if title:
                        yield _stage(
                            "reverse_image",
                            "running",
                            "Treg Lens",
                            signals["lens"].get("detail") or "Identifying the photo from visual matches.",
                            [{"label": str(title)[:80], "tone": "neutral"}],
                            sponsor="treg_lens",
                            finding=str(title)[:160],
                        )
                elif name == "vision":
                    signals["vision"] = _future_value(future, "Vision assist")
                    text = signals["vision"].get("text") or ""
                    if text:
                        yield _stage(
                            "vision",
                            "running",
                            "Gemini" if signals["vision"].get("provider") in {"Gemini", "OpenAI"} else "Vision assist",
                            "vision assist",
                            [{"label": str(text)[:80], "tone": "neutral"}],
                            sponsor="gemini" if signals["vision"].get("provider") else "see",
                            finding=str(text)[:160],
                        )
                elif name == "profile" and "profile" not in emitted:
                    profile_row = _future_value(future, "Treg X profile")
                    emitted.add("profile")
                    yield x_stage("profile", profile_row)
                elif name == "replies" and "replies" not in emitted:
                    replies_row = _future_value(future, "Treg X replies")
                    emitted.add("replies")
                    yield x_stage("replies", replies_row)
            if "lens" in held or "vision" in held:
                wait_some()
        if "lens" in held:
            del held["lens"]
            timed_out.append("Treg Lens")
            signals["lens"] = _blank_call("Treg Lens timed out.")
        if "vision" in held:
            del held["vision"]
            timed_out.append("Vision assist")
            signals["vision"] = _blank_call("Vision assist timed out.")
        reverse = signals.get("lens") or _blank_call("Treg Lens timed out.")
        assist = signals.get("vision") or _blank_call("Vision assist timed out.")
        matches = reverse.get("matches") or []
        lens_name = (reverse.get("knowledge_title") or "").strip()
        rev_flags = [{"label": m.get("title") or m.get("url") or "Match", "tone": "neutral"} for m in matches[:3]]
        if lens_name:
            rev_flags = [{"label": lens_name[:80], "tone": "neutral"}] + rev_flags[:2]
        if not matches and "add key" in (reverse.get("detail") or ""):
            rev_flags = [{"label": "Treg: add key", "tone": "neutral"}]
        yield _stage(
            "reverse_image",
            reverse.get("status") or "error",
            "Treg Lens",
            reverse.get("detail") or "Identified by Treg Google Lens.",
            rev_flags,
            sponsor="treg_lens",
            stats={"latency_ms": int(reverse.get("latency_ms") or 0), "matches": len(matches)},
        )

        assist_what = " ".join(str(assist.get("what") or "").split())[:80]
        if not lens_name and matches:
            recurring = _recurring_name(matches[:8])
            if recurring and assist_what and recurring.lower() in assist_what.lower():
                lens_name = assist_what
            elif recurring:
                lens_name = recurring
        if assist_what and not lens_name and matches:
            head = assist_what.split()[0].lower()
            if head not in _STOP_HEADS and len(head) > 2 and any(re.search(rf"\b{re.escape(head)}\b", str(m.get("title") or "").lower()) for m in matches[:6]):
                lens_name = assist_what
        if lens_name:
            seen_text = f"Identified by Treg Google Lens: {lens_name}"
        elif assist.get("text"):
            seen_text = assist["text"]
        else:
            seen_text = ""
            if matches:
                try:
                    fallback = see.from_matches(matches, claim_text)
                except Exception:
                    fallback = {}
                if fallback.get("text"):
                    seen_text = fallback["text"]
                    assist = fallback
        if assist.get("text") and lens_name and assist["text"] not in seen_text:
            assist_note = "vision assist"
        else:
            assist_note = assist.get("detail") or ""
        if "continued" not in (assist_note or "").lower() and not lens_name:
            assist_note = ((assist_note or "Vision assist unavailable.") + " The check continued.").strip()
        claim = {
            "text": claim_text,
            "who": "",
            "what": assist.get("what") or "",
            "where": "",
            "when": "",
            "search_query": (lens_name or seen_text or claim_text or "")[:300],
            "source": "lens" if lens_name else ("vision" if seen_text else ("caption" if claim_text else "none")),
            "seen": seen_text,
        }
        if link.get("search_query") and not seen_text:
            claim["search_query"] = str(link["search_query"])[:300]
        vision_status = "ok" if assist.get("text") or lens_name else (assist.get("status") or "skipped")
        vision_stage = {"status": vision_status, "detail": "vision assist" if assist.get("text") else (assist_note or "vision assist skipped")}
        yield _stage(
            "vision",
            vision_stage["status"],
            "Gemini" if assist.get("provider") in {"Gemini", "OpenAI"} else "Vision assist",
            vision_stage["detail"],
            [{"label": (assist.get("text") or seen_text or "Vision assist skipped")[:80], "tone": "neutral"}],
            sponsor="gemini" if assist.get("provider") else "see",
            stats={"latency_ms": int(assist.get("latency_ms") or 0), "provider": "vision assist" if assist.get("text") else (assist.get("provider") or "")},
        )

        query = (claim.get("search_query") or claim.get("text") or "").strip()
        if query.lower().startswith("no caption"):
            query = ""

        def _identify():
            try:
                context = ""
                if image_url.startswith("http") and not links.is_direct_image(image_url):
                    context = ""
                return questions.identify(
                    claim.get("text") or claim_text,
                    matches,
                    f"{context} {claim.get('seen') or ''}",
                    claim.get("what") or "",
                    skip_model=bool(lens_name),
                )
            except Exception:
                return {}

        subject = {}
        submit("identify", _identify)
        left = _remaining(clock)
        if "identify" in held and left > 0:
            try:
                subject = held["identify"].result(timeout=left) or {}
                del held["identify"]
            except FuturesTimeout:
                del held["identify"]
                timed_out.append("Subject naming")
                subject = {}
            except Exception:
                held.pop("identify", None)
                subject = {}
        elif "identify" in held:
            if held["identify"].done():
                subject = _future_value(held["identify"], "Subject naming")
            else:
                timed_out.append("Subject naming")
            del held["identify"]
        if not isinstance(subject, dict):
            subject = {}
        if claim.get("seen"):
            subject["seen"] = claim["seen"]
        if subject.get("query") and subject.get("questions"):
            query = subject["query"]
            claim["search_query"] = query

        news_row = None
        web_row = None
        web_parts: dict = {}
        you_failed = False
        if not query:
            news_row = _blank_call("", "skipped")
            web_row = _blank_call("", "skipped")
            yield _stage("treg_news", "skipped", "Treg News", "No query for Treg News.", sponsor="treg_news")
            yield _stage("treg_web", "skipped", "Treg Web", "No query for Treg Web.", sponsor="treg_web")
            for name, data in youcom.iter_investigate(query, subject.get("questions") or None):
                web_parts[name] = data
                if name == "search":
                    yield _stage("youcom_search", data["status"], "You.com Search", data.get("detail") or "", _search_flags(data), sponsor="youcom_search", stats={"latency_ms": int(data.get("latency_ms") or 0), "results": len(data.get("hits") or [])}, finding=_finding(data))
                elif name == "contents":
                    yield _stage("youcom_contents", data["status"], "You.com Contents", data.get("detail") or "", sponsor="youcom_contents", stats={"latency_ms": int(data.get("latency_ms") or 0), "pages": len(data.get("pages") or [])})
                elif name == "answer":
                    yield _stage("youcom_answer", data["status"], "You.com Answer", data.get("detail") or "", sponsor="youcom_answer", stats={"latency_ms": int(data.get("latency_ms") or 0), "citations": len(data.get("citations") or [])})
        elif _remaining(clock) <= 0:
            for label in ("You.com Search", "You.com Contents", "You.com Answer", "Treg News", "Treg Web"):
                timed_out.append(label)
            news_row = _blank_call("Treg News timed out.")
            web_row = _blank_call("Treg Web timed out.")
            web_parts = {
                "search": _blank_call("You.com Search timed out."),
                "contents": _blank_call("You.com Contents timed out."),
                "answer": _blank_call("You.com Answer timed out."),
            }
            yield _stage("youcom_search", "error", "You.com Search", "You.com Search timed out.", sponsor="youcom_search")
            yield _stage("youcom_contents", "error", "You.com Contents", "You.com Contents timed out.", sponsor="youcom_contents")
            yield _stage("youcom_answer", "error", "You.com Answer", "You.com Answer timed out.", sponsor="youcom_answer")
            yield _stage("treg_news", "error", "Treg News", "Treg News timed out.", sponsor="treg_news")
            yield _stage("treg_web", "error", "Treg Web", "Treg Web timed out.", sponsor="treg_web")
        else:
            yield _stage("youcom_search", "running", "You.com Search", query or "Searching credible sources for the claim.", sponsor="prove")
            yield _stage("treg_news", "running", "Treg News", "Fresh headlines for the same query.", sponsor="treg_news")
            yield _stage("treg_web", "running", "Treg Web", "Cross-checking the open web.", sponsor="treg_web")
            you_q: queue.Queue = queue.Queue()
            submit("youcom", _pump_youcom, query, subject.get("questions") or None, you_q)
            submit("news", treg.news, query)
            submit("websearch", treg.web, query)
            followups = False
            you_done = False


            while _remaining(clock) > 0 and (not you_done or any(name in held for name in ("news", "websearch", "profile", "replies", "youcom"))):
                while True:
                    try:
                        kind, name, data = you_q.get_nowait()
                    except queue.Empty:
                        break
                    if kind == "error":
                        you_failed = True
                        you_done = True
                        continue
                    if kind == "done":
                        you_done = True
                        continue
                    if not isinstance(data, dict):
                        continue
                    web_parts[name] = data
                    if name == "search":
                        yield _stage(
                            "youcom_search",
                            data.get("status") or "error",
                            "You.com Search",
                            data.get("detail") or "",
                            _search_flags(data),
                            sponsor="youcom_search",
                            stats={"latency_ms": int(data.get("latency_ms") or 0), "results": len(data.get("hits") or [])},
                            finding=_finding(data),
                        )
                        if not followups:
                            followups = True
                            yield _stage("youcom_contents", "running", "You.com Contents", "Pulling page text from the top results.", sponsor="youcom_contents")
                            synthesis = "You.com Research" if subject.get("questions") else "You.com Answer"
                            yield _stage("youcom_answer", "running", synthesis, "Asking You.com for a cited synthesis.", sponsor="youcom_answer")
                    elif name == "contents":
                        page = (data.get("pages") or [{}])[0] if data.get("pages") else {}
                        yield _stage(
                            "youcom_contents",
                            data.get("status") or "error",
                            "You.com Contents",
                            data.get("detail") or "",
                            sponsor="youcom_contents",
                            stats={"latency_ms": int(data.get("latency_ms") or 0), "pages": len(data.get("pages") or [])},
                            finding=str((page or {}).get("title") or "")[:160],
                        )
                    elif name == "answer":
                        flags = [{"label": data["text"][:80], "tone": "neutral"}] if data.get("text") else []
                        yield _stage(
                            "youcom_answer",
                            data.get("status") or "error",
                            "You.com Research" if data.get("kind") == "research" else "You.com Answer",
                            data.get("detail") or data.get("text") or "",
                            flags,
                            sponsor="youcom_answer",
                            stats={"latency_ms": int(data.get("latency_ms") or 0), "citations": len(data.get("citations") or [])},
                            finding=_finding(data),
                        )
                for name, future in take_ready():
                    if name == "news":
                        news_row = _future_value(future, "Treg News")
                        yield _stage(
                            "treg_news",
                            news_row.get("status") or "error",
                            "Treg News",
                            news_row.get("detail") or "",
                            sponsor="treg_news",
                            stats={"latency_ms": int(news_row.get("latency_ms") or 0), "results": int(news_row.get("results") or len(news_row.get("hits") or []))},
                            finding=_finding(news_row),
                        )
                    elif name == "websearch":
                        web_row = _future_value(future, "Treg Web")
                        yield _stage(
                            "treg_web",
                            web_row.get("status") or "error",
                            "Treg Web",
                            web_row.get("detail") or "",
                            sponsor="treg_web",
                            stats={"latency_ms": int(web_row.get("latency_ms") or 0), "results": int(web_row.get("results") or len(web_row.get("hits") or []))},
                            finding=_finding(web_row),
                        )
                    elif name == "profile" and "profile" not in emitted:
                        profile_row = _future_value(future, "Treg X profile")
                        emitted.add("profile")
                        yield x_stage("profile", profile_row)
                    elif name == "replies" and "replies" not in emitted:
                        replies_row = _future_value(future, "Treg X replies")
                        emitted.add("replies")
                        yield x_stage("replies", replies_row)
                    elif name == "youcom":
                        you_done = True
                if you_done and not any(name in held for name in ("news", "websearch", "profile", "replies")):
                    break
                if not you_done or any(name in held for name in ("news", "websearch", "profile", "replies", "youcom")):
                    wait_some()
            for name, label, key in (
                ("news", "Treg News", "news"),
                ("websearch", "Treg Web", "web"),
                ("profile", "Treg X profile", "profile"),
                ("replies", "Treg X replies", "replies"),
            ):
                if name not in held:
                    continue
                del held[name]
                timed_out.append(label)
                row = _blank_call(f"{label} timed out.")
                if key == "news":
                    news_row = row
                elif key == "web":
                    web_row = row
                elif key == "profile":
                    profile_row = row
                    emitted.add("profile")
                else:
                    replies_row = row
                    emitted.add("replies")
                yield _stage(
                    "treg_news" if key == "news" else "treg_web" if key == "web" else "treg_profile" if key == "profile" else "treg_replies",
                    "error",
                    label,
                    row["detail"],
                    sponsor="treg_news" if key == "news" else "treg_web" if key == "web" else "treg_profile" if key == "profile" else "treg_replies",
                )
            if "youcom" in held:
                del held["youcom"]
            if you_failed and "search" not in web_parts:
                web_parts = {
                    "search": {"status": "error", "detail": "You.com failed.", "hits": []},
                    "contents": _stage_error("Contents"),
                    "answer": {"status": "error", "detail": "Synthesis failed.", "text": "", "citations": []},
                }
                yield _stage("youcom_search", "error", "Search failed", "You.com failed.")
                yield _stage("youcom_contents", "error", "Could not read sources", "Contents failed.")
                yield _stage("youcom_answer", "error", "Synthesis failed", "Answer failed.")
            else:
                for part, label in (("search", "You.com Search"), ("contents", "You.com Contents"), ("answer", "You.com Answer")):
                    if part in web_parts:
                        continue
                    timed_out.append(label)
                    web_parts[part] = _blank_call(f"{label} timed out.")
                    yield _stage(f"youcom_{part}", "error", label, f"{label} timed out.", sponsor=f"youcom_{part}")

        if "profile" in held:
            if _remaining(clock) > 0:
                try:
                    profile_row = held["profile"].result(timeout=_remaining(clock))
                except FuturesTimeout:
                    timed_out.append("Treg X profile")
                    profile_row = _blank_call("Treg X profile timed out.")
                except Exception:
                    profile_row = _blank_call("Treg X profile failed. The check continued.")
            elif held["profile"].done():
                profile_row = _future_value(held["profile"], "Treg X profile")
            else:
                timed_out.append("Treg X profile")
                profile_row = _blank_call("Treg X profile timed out.")
            del held["profile"]
            if "profile" not in emitted and profile_row:
                yield x_stage("profile", profile_row)
        if "replies" in held:
            if _remaining(clock) > 0:
                try:
                    replies_row = held["replies"].result(timeout=_remaining(clock))
                except FuturesTimeout:
                    timed_out.append("Treg X replies")
                    replies_row = _blank_call("Treg X replies timed out.")
                except Exception:
                    replies_row = _blank_call("Treg X replies failed. The check continued.")
            elif held["replies"].done():
                replies_row = _future_value(held["replies"], "Treg X replies")
            else:
                timed_out.append("Treg X replies")
                replies_row = _blank_call("Treg X replies timed out.")
            del held["replies"]
            if "replies" not in emitted and replies_row:
                yield x_stage("replies", replies_row)

        web = _empty_web(web_parts.get("search"), web_parts.get("contents"), web_parts.get("answer"))
        extra_hits = list((news_row or {}).get("hits") or []) + list((web_row or {}).get("hits") or [])
        if extra_hits:
            web["search"]["hits"] = treg.merge_hits(list(web["search"].get("hits") or []), extra_hits)
        treg_extra = {"news": news_row or {}, "web": web_row or {}, "profile": profile_row or {}, "replies": replies_row or {}}

        paywall = config.paywall_on()
        yield _stage(
            "x402",
            "skipped",
            "Paywall ready ($0.02 on XDC)",
            "Paywall ready ($0.02 on XDC). This desk check is not a verified payment.",
            [{"label": "Paywall ready" if paywall else "Test mode", "tone": "neutral"}],
            sponsor="x402",
            stats={"mode": "live" if paywall else "test", "price_usdc": sponsors.receipt({}, {}).get("x402", {}).get("price_usdc", "0.02")},
        )

        yield _stage("verdict", "running", "Judging the claim", "Comparing sources and dates with what the claim says.")
        result = _assemble(
            image, media_type, claim_text, image_url, demo_id, filename, cache_key, creds, prior, claim, vision_stage, web, reverse, link, subject, image_from_url, treg_extra, timed_out
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
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def run(
    image: bytes,
    media_type: str,
    claim_text: str,
    image_url: str = "",
    demo_id: str | None = None,
    filename: str = "",
    photo_url: bool = False,
) -> dict:
    final = None
    for ev in iter_run(
        image=image,
        media_type=media_type,
        claim_text=claim_text,
        image_url=image_url,
        demo_id=demo_id,
        filename=filename,
        photo_url=photo_url,
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
    image_url = str(payload.get("image_url") or "").strip()
    payload_photo = False
    if demo_id:
        sample = samples.get(demo_id)
        if sample is None:
            raise ValueError("Unknown demo_id.")
        if not image and sample.get("attach", True) and sample.get("bytes"):
            image = sample["bytes"]
            filename = filename or f"{demo_id}.jpg"
        if not str(claim).strip():
            claim = sample["claim"]
        if not image_url and sample.get("url"):
            image_url = sample["url"]
        payload_photo = bool(sample.get("attach") and sample.get("url") and image)
    if not image and not str(claim).strip() and not image_url:
        raise ValueError("Send a claim, a link, an image, a file, or a demo_id.")
    return {
        "image": image,
        "media_type": media_type,
        "claim_text": claim,
        "image_url": image_url,
        "demo_id": demo_id,
        "filename": filename,
        "photo_url": payload_photo,
    }


def run_request(payload: dict) -> dict:
    return run(**_prepare_request(payload))


def iter_request(payload: dict) -> Iterator[dict]:
    yield from iter_run(**_prepare_request(payload))
