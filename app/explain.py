"""Honest caveats, grouped evidence, and checks a person can run next."""

from __future__ import annotations

from urllib.parse import quote, urlparse

from app.links import is_direct_image, is_status_url
from app.verdict import FALSE, MISLEADING, TRUE, host_of


def _stage(stages: dict, name: str) -> dict:
    return (stages or {}).get(name) or {}


def caveats(result: dict) -> list[dict]:
    notes: list[dict] = []
    stages = result.get("stages") or {}
    credentials = result.get("credentials") or {}
    exif = credentials.get("exif") or {}
    verdict = result.get("verdict") or ""

    vision = _stage(stages, "vision")
    if vision.get("status") in {"skipped", "error"} or (result.get("claim") or {}).get("source") in {"caption", "none", ""}:
        notes.append(
            {
                "id": "no_vision",
                "text": "No vision model was used, so the image itself wasn't read. This check is about the claim: the words, the dates, and what credible sources say.",
            }
        )

    reverse = _stage(stages, "reverse_image")
    if reverse.get("status") == "skipped":
        notes.append(
            {
                "id": "no_reverse",
                "text": "Reverse image search was skipped because no public image link was provided. An earlier original could still be online.",
            }
        )
    elif reverse.get("status") == "error":
        notes.append(
            {
                "id": "reverse_failed",
                "text": "Reverse image search did not finish, so this verdict does not include earlier appearances of the same picture.",
            }
        )

    search = _stage(stages, "youcom_search")
    if search.get("status") == "skipped":
        notes.append(
            {
                "id": "no_web",
                "text": "Web search was not run, so this reading is based only on the file itself and the caption.",
            }
        )
    elif search.get("status") == "error":
        notes.append(
            {
                "id": "web_failed",
                "text": "Web search did not finish, so reporting that could confirm or contradict the claim may be missing.",
            }
        )

    if exif.get("datetime") or exif.get("make"):
        notes.append(
            {
                "id": "exif_can_lie",
                "text": "Camera tags and file dates can be edited or stripped, so metadata is a clue, not proof.",
            }
        )
    else:
        notes.append(
            {
                "id": "no_exif",
                "text": "The file has no useful camera date, so we could not compare when it was taken with what the claim says.",
            }
        )

    if verdict == "Unverified":
        notes.append(
            {
                "id": "thin_evidence",
                "text": "The clues are thin or they pull in more than one direction, so this could easily be wrong.",
            }
        )
    elif verdict == TRUE:
        notes.append(
            {
                "id": "news_is_not_the_photo",
                "text": "Matching coverage supports the claim. It still does not prove a particular file is the original photograph of that event.",
            }
        )
    elif verdict == FALSE:
        notes.append(
            {
                "id": "sources_can_miss",
                "text": "A source can be wrong, or about a different event than the one in the claim.",
            }
        )
    elif verdict == MISLEADING:
        notes.append(
            {
                "id": "context_is_not_pixels",
                "text": "A date or context mismatch means the claim's timing or story is off. It does not mean the picture was generated.",
            }
        )

    detector = result.get("detector") or {}
    if detector.get("method"):
        notes.append(
            {
                "id": "detector_is_a_prior",
                "text": "Any AI-image score is a weak local prior, not a verdict. This desk checks whether the claim is true.",
            }
        )

    # Deduplicate while keeping order; the first note is the one shown under the meter.
    seen = set()
    unique = []
    for note in notes:
        if note["id"] in seen:
            continue
        seen.add(note["id"])
        unique.append(note)
    return unique[:4]


def confidence_note(result: dict, notes: list[dict]) -> str:
    if notes:
        return notes[0]["text"]
    return "This number reflects how the clues lined up, not a guarantee that the verdict is right."


def evidence_groups(result: dict) -> dict:
    toward_real = []
    toward_other = []
    for item in result.get("contributions") or []:
        row = {
            "title": item.get("title") or "",
            "why": item.get("detail") or "",
            "points": int(item.get("points") or 0),
            "bucket": item.get("bucket") or "",
            "url": item.get("url") or "",
        }
        if row["bucket"] == "real":
            toward_real.append(row)
        elif row["bucket"] == "weak":
            continue
        else:
            toward_other.append(row)

    couldnt = []
    stages = result.get("stages") or {}
    labels = {
        "vision": (
            "The picture itself",
            "No vision model was configured, so only the caption was used.",
        ),
        "youcom_search": (
            "Web search",
            "You.com search was not run, so reporting was not checked.",
        ),
        "youcom_contents": (
            "Source pages",
            "The top search results were not read in full.",
        ),
        "youcom_answer": (
            "Cited synthesis",
            "You.com did not produce a cited answer for this claim.",
        ),
        "reverse_image": (
            "Reverse image search",
            "No public image link was provided, so earlier appearances were not checked.",
        ),
    }
    # If search was skipped, don't also list contents/answer as separate misses.
    search_status = (stages.get("youcom_search") or {}).get("status")
    for name, (title, default_why) in labels.items():
        info = stages.get(name) or {}
        status = info.get("status")
        if status not in {"skipped", "error"}:
            continue
        if name in {"youcom_contents", "youcom_answer"} and search_status in {"skipped", "error"}:
            continue
        why = info.get("detail") or default_why
        if status == "error" and name == "reverse_image":
            why = info.get("detail") or "Reverse image search did not finish."
        couldnt.append({"title": title, "why": why, "status": status, "points": 0, "bucket": "skipped"})

    credentials = result.get("credentials") or {}
    exif = credentials.get("exif") or {}
    if not exif.get("datetime"):
        couldnt.append(
            {
                "title": "Capture date",
                "why": "The file has no capture date to compare with the claim.",
                "status": "missing",
                "points": 0,
                "bucket": "skipped",
            }
        )
    weak = []
    for item in result.get("contributions") or []:
        if (item.get("bucket") or "") != "weak":
            continue
        weak.append(
            {
                "title": item.get("title") or "",
                "why": item.get("detail") or "",
                "points": int(item.get("points") or 0),
                "bucket": "weak",
                "url": item.get("url") or "",
            }
        )
    return {
        "toward_real": toward_real,
        "toward_fake_or_ooc": toward_other,
        "weak_clues": weak,
        "couldnt_check": couldnt,
    }


def next_steps(result: dict, image_url: str = "") -> list[dict]:
    steps: list[dict] = []
    image_url = (image_url or "").strip()
    if is_status_url(image_url):
        steps.append(
            {
                "id": "open_post",
                "title": "Open the post",
                "why": "Read the X post itself and check the author, the date, and whether the text matches what is circulating now.",
                "links": [{"label": "Open on X", "url": image_url}],
            }
        )
    if image_url.startswith("http") and is_direct_image(image_url):
        encoded = quote(image_url, safe="")
        steps.append(
            {
                "id": "reverse_search",
                "title": "Run a reverse image search",
                "why": "See where this picture appeared before, and whether an earlier original exists.",
                "links": [
                    {"label": "Google Images", "url": f"https://www.google.com/searchbyimage?image_url={encoded}"},
                    {"label": "TinEye", "url": f"https://tineye.com/search?url={encoded}"},
                    {"label": "Yandex", "url": f"https://yandex.com/images/search?rpt=imageview&url={encoded}"},
                ],
            }
        )
    else:
        steps.append(
            {
                "id": "reverse_search",
                "title": "Run a reverse image search",
                "why": "This check didn't have a public image link. Upload the same file at Google Images or TinEye and look for earlier dates.",
                "links": [
                    {"label": "Google Images", "url": "https://images.google.com/"},
                    {"label": "TinEye", "url": "https://tineye.com/"},
                ],
            }
        )

    sources = [src for src in (result.get("sources") or []) if (src.get("url") or "").startswith("http")]
    if sources:
        steps.append(
            {
                "id": "open_sources",
                "title": "Open the original sources",
                "why": "Read the pages this check relied on, and see whether they are actually about this image.",
                "links": [
                    {
                        "label": src.get("outlet") or host_of(src["url"]) or urlparse(src["url"]).netloc,
                        "url": src["url"],
                    }
                    for src in sources[:5]
                ],
            }
        )
    else:
        steps.append(
            {
                "id": "search_the_claim",
                "title": "Search the claim yourself",
                "why": "No sources were attached to this receipt. Search the caption and see if credible outlets describe this specific picture.",
                "links": [],
            }
        )

    claim = (result.get("claim") or {}).get("text") or ""
    captured = ((result.get("credentials") or {}).get("exif") or {}).get("datetime") or ""
    if captured or claim:
        detail = "Compare the file date with what the caption claims. If they disagree, the picture may be older than the post suggests."
        if captured and claim:
            detail = f"The file is dated {captured}. The claim is: “{claim[:180]}”"
        elif captured:
            detail = f"The file is dated {captured}. Check whether that matches the story being told."
        steps.append(
            {
                "id": "compare_dates",
                "title": "Compare the dates",
                "why": detail,
                "links": [],
            }
        )
    return steps


def attach(result: dict, image_url: str = "") -> dict:
    notes = caveats(result)
    result["caveats"] = notes
    result["confidence_note"] = confidence_note(result, notes)
    result["evidence_groups"] = evidence_groups(result)
    result["next_steps"] = next_steps(result, image_url)
    return result
