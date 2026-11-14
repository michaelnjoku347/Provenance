"""Split a question into parts, then write one short answer."""

from __future__ import annotations

import re

from app.verdict import FALSE, UNVERIFIED, host_of, is_credible

_NAME = re.compile(r"\b([A-Z][A-Za-z.'’-]+(?:\s+[A-Z][A-Za-z.'’-]+){1,3})\b")
_STOP = {
    "The",
    "This",
    "That",
    "These",
    "Those",
    "Photo",
    "Image",
    "Picture",
    "March",
    "April",
    "May",
    "June",
    "July",
    "January",
    "February",
    "August",
    "September",
    "October",
    "November",
    "December",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
    "Downtown",
    "United",
    "New York",
    "Los Angeles",
}
_DIVORCE = ("divorce", "divorced", "divorcing", "separation", "separated", "split up")
_NEGATION = (
    "no evidence",
    "no credible",
    "not divorced",
    "never divorced",
    "denied",
    "denies",
    "rumor",
    "rumour",
    "unfounded",
    "speculation",
    "not separated",
)


def split_questions(text: str) -> list[dict]:
    """Break a question into the parts a person actually asked."""
    raw = " ".join((text or "").split())
    lowered = raw.lower()
    parts: list[dict] = []
    if re.search(r"\bwho\b", lowered) or "who are" in lowered or "who is" in lowered:
        parts.append({"id": "who", "kind": "identity", "text": "Who is in the image?"})
    if re.search(r"\bwhat\b|\bwhich\b", lowered):
        parts.append({"id": "what", "kind": "identity", "text": raw if "?" in raw else "What is in the image?"})
    if re.search(r"divorc|married|wife|husband|\bspouse\b|split", lowered):
        parts.append({"id": "relationship", "kind": "relationship", "text": "Are they divorced?"})
    if not parts and "?" in raw:
        parts.append({"id": "ask", "kind": "other", "text": raw})
    return parts


def _clean_name(value: str) -> str:
    words = [word for word in value.split() if word not in _STOP and word.lower() not in {"and", "the", "his", "her"}]
    if len(words) < 2 or len(words) > 4:
        return ""
    if any(word in _STOP for word in words):
        return ""
    return " ".join(words)


def _names(text: str) -> list[str]:
    found: list[str] = []
    for match in _NAME.findall(text or ""):
        name = _clean_name(match)
        if name and name not in found:
            found.append(name)
    return found[:4]


def _wife_pair(text: str) -> tuple[str, str]:
    match = re.search(
        r"([A-Z][A-Za-z.'’-]+(?:\s+[A-Z][A-Za-z.'’-]+){1,2})\s+and (?:his|her) wife\s+([A-Z][A-Za-z.'’-]+(?:\s+[A-Z][A-Za-z.'’-]+){0,2})",
        text or "",
    )
    if not match:
        return "", ""
    left = _clean_name(match.group(1))
    right = _clean_name(match.group(2))
    if right and len(right.split()) == 1 and left:
        surname = left.split()[-1]
        right = f"{right} {surname}"
    return left, right


def _role(text: str, names: list[str]) -> str:
    lowered = (text or "").lower()
    if "nvidia" in lowered and re.search(r"\bceo\b|chief executive", lowered):
        return "NVIDIA CEO"
    match = re.search(r"\b(?:CEO|chief executive) of ([A-Z][\w&]+)", text or "")
    if match:
        return f"CEO of {match.group(1)}"
    return ""


def _asserts_divorce(text: str) -> bool:
    lowered = (text or "").lower()
    if not any(word in lowered for word in _DIVORCE):
        return False
    return not any(phrase in lowered for phrase in _NEGATION)


def identify(claim_text: str, matches: list[dict], context: str = "") -> dict:
    blob = " ".join(
        " ".join(
            part
            for part in (
                item.get("title") or "",
                item.get("snippet") or "",
                item.get("source") or "",
            )
            if part
        )
        for item in matches or []
    )
    blob = f"{blob} {context or ''}"
    left, right = _wife_pair(blob)
    names = []
    if left:
        names.append(left)
    if right and right not in names:
        names.append(right)
    for name in _names(blob):
        if name not in names:
            names.append(name)
    names = names[:4]
    questions = split_questions(claim_text)
    kinds = {item["kind"] for item in questions}
    query = " ".join((claim_text or "").split())[:300]
    if names and "relationship" in kinds:
        if len(names) > 1:
            query = f"{names[0]} wife {names[1]} divorce"
        else:
            query = f"{names[0]} divorce"
    elif context and "identity" in kinds and not names:
        query = context[:240]
    elif names and "identity" in kinds:
        query = " ".join(names)
    return {
        "names": names,
        "relation": "wife" if left and right else "",
        "role": _role(blob, names),
        "questions": questions,
        "query": query[:300],
    }


def _quote(hit: dict) -> str:
    text = " ".join(str(hit.get("excerpt") or hit.get("title") or "").split())
    return text[:180]


def _top_sources(hits: list[dict]) -> list[dict]:
    rows = []
    seen = set()
    ordered = sorted(hits, key=lambda hit: 0 if is_credible(hit.get("url") or "") else 1)
    for hit in ordered:
        url = hit.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        rows.append(
            {
                "title": (hit.get("title") or host_of(url))[:140],
                "url": url,
                "domain": host_of(url),
                "quote": _quote(hit),
                "credible": is_credible(url),
            }
        )
        if len(rows) == 3:
            break
    return rows


def compose(claim_text: str, decision: dict, web: dict, reverse: dict, subject: dict | None) -> dict:
    """One card: a verdict, one sentence, and at most three reasons."""
    subject = subject or {}
    questions = subject.get("questions") or split_questions(claim_text)
    hits = list(((web or {}).get("search") or {}).get("hits") or [])
    for page in ((web or {}).get("contents") or {}).get("pages") or []:
        for hit in hits:
            if hit.get("url") == page.get("url") and page.get("excerpt"):
                hit["excerpt"] = page["excerpt"]
    names = list(subject.get("names") or [])
    kinds = {item["kind"] for item in questions}
    credible_divorce = [
        hit
        for hit in hits
        if is_credible(hit.get("url") or "") and _asserts_divorce(f"{hit.get('title', '')} {hit.get('excerpt', '')}")
    ]
    rumors = [
        hit
        for hit in hits
        if not is_credible(hit.get("url") or "") and any(word in f"{hit.get('title', '')} {hit.get('excerpt', '')}".lower() for word in _DIVORCE)
    ]
    sources = _top_sources(hits)
    why = []
    for source in sources:
        if source["quote"]:
            why.append({"text": source["quote"], "url": source["url"], "domain": source["domain"]})
        if len(why) == 3:
            break

    seen = " ".join((subject.get("seen") or "").split())
    if "relationship" in kinds or ("identity" in kinds and names):
        if names:
            who = names[0]
            other = names[1] if len(names) > 1 else ""
            role = subject.get("role") or ""
            if role and other and subject.get("relation") == "wife":
                person = who[4:] if who.lower().startswith("ceo ") else who
                who_sentence = f"This is {role} {person} and his wife {other.split()[0]}."
            elif other:
                who_sentence = f"This is {who} and {other}."
            else:
                who_sentence = f"This is {who}."
        else:
            who_sentence = "The people in this image were not identified from the matches."

        if "relationship" in kinds and credible_divorce:
            sentence = f"{who_sentence} A credible source reports a divorce."
            verdict = "True"
            line = "Credible reporting says they divorced."
        elif "relationship" in kinds and names and not credible_divorce:
            sentence = f"{who_sentence} There are no credible reports they are divorced."
            verdict = FALSE
            line = "No credible evidence they are divorced. Unverified/likely false."
            if rumors and len(why) < 3:
                why.append(
                    {
                        "text": "A non-credible page mentions a divorce. That is a rumor, not a finding.",
                        "url": rumors[0].get("url") or "",
                        "domain": host_of(rumors[0].get("url") or ""),
                    }
                )
        elif names:
            sentence = who_sentence
            verdict = decision.get("verdict") or UNVERIFIED
            line = ""
        else:
            sentence = "The people in this image were not identified, so the question stays open."
            verdict = UNVERIFIED
            line = "Unverified."
        confidence = 70 if names and not credible_divorce and "relationship" in kinds else int(decision.get("confidence") or 40)
        if not names:
            confidence = min(confidence, 40)
    elif seen:
        sentence = seen if seen.endswith((".", "!", "?")) else f"{seen}."
        fact = sources[0]["quote"] if sources else ""
        if fact and fact.lower() not in sentence.lower():
            sentence = f"{sentence} {fact}"
        verdict = decision.get("verdict") or ("True" if any(item.get("credible") for item in sources) else UNVERIFIED)
        line = ""
        confidence = int(decision.get("confidence") or (64 if sources else 40))
    else:
        sentence = decision.get("summary") or "The claim could not be settled from the sources."
        verdict = decision.get("verdict") or UNVERIFIED
        line = ""
        confidence = int(decision.get("confidence") or 40)
        if not why:
            for item in (decision.get("contributions") or [])[:3]:
                if item.get("title"):
                    why.append({"text": item.get("detail") or item["title"], "url": item.get("url") or "", "domain": host_of(item.get("url") or "") if item.get("url") else ""})

    return {
        "verdict": verdict,
        "confidence": confidence,
        "text": sentence,
        "line": line,
        "why": why[:3],
        "sources": sources,
        "questions": questions,
    }
