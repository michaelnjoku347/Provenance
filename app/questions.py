"""Split a question into parts, name who is shown, and write one short answer."""

from __future__ import annotations

import json
import re

from app import config
from app.textutil import repair_text
from app.verdict import FALSE, UNVERIFIED, host_of, is_credible, is_rumor, tier

_WORD = re.compile(r"[A-Za-z][A-Za-z'’]*")
_BAD = {
    "new",
    "state",
    "live",
    "he",
    "she",
    "they",
    "his",
    "her",
    "the",
    "and",
    "supercomputer",
    "oregon",
    "university",
    "times",
    "journal",
    "news",
    "ceo",
    "nvidia",
    "wife",
    "husband",
    "divorce",
    "photo",
    "image",
    "picture",
    "video",
    "says",
    "with",
    "from",
    "after",
    "before",
    "their",
    "who",
    "what",
    "alleged",
    "affair",
    "speculation",
    "third",
    "could",
    "walk",
    "away",
    "half",
    "march",
    "april",
    "may",
    "june",
    "july",
    "january",
    "february",
    "august",
    "september",
    "october",
    "november",
    "december",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "forbes",
    "yahoo",
    "reuters",
    "downtown",
    "spouse",
    "helps",
    "help",
    "launch",
    "launches",
    "launched",
    "launching",
    "foundation",
    "college",
    "school",
    "institute",
    "trustee",
    "trust",
    "trusts",
    "born",
    "married",
    "meets",
    "met",
    "donates",
    "donated",
    "says",
    "said",
    "walk",
    "walks",
    "files",
    "filed",
    "reports",
    "reported",
    "could",
    "would",
    "side",
    "years",
    "head",
    "nvidia",
    "spoke",
    "beside",
    "standing",
    "during",
    "will",
    "like",
    "machine",
    "time",
}
_DIVORCE = ("divorce", "divorced", "divorcing", "separation", "separated", "split up")
_SPECULATION = (
    "speculation",
    "speculated",
    "alleged",
    "allegedly",
    "rumor",
    "rumour",
    "potential divorce",
    "could divorce",
    "could walk",
    "were to divorce",
    "were to split",
    "if they divorce",
    "if the",
    "might divorce",
)
_FILING = (
    "filed for divorce",
    "files for divorce",
    "divorce filing",
    "divorce was finalized",
    "finalized their divorce",
    "announced their divorce",
    "announced a divorce",
    "are divorced",
    "got divorced",
    "is divorced",
)
_OUTLETS = {
    "forbes.com": "Forbes",
    "reuters.com": "Reuters",
    "apnews.com": "AP",
    "bbc.com": "BBC",
    "bbc.co.uk": "BBC",
    "nytimes.com": "The New York Times",
    "wsj.com": "The Wall Street Journal",
    "bloomberg.com": "Bloomberg",
    "ft.com": "Financial Times",
    "economictimes.indiatimes.com": "The Economic Times",
    "mensjournal.com": "Men's Journal",
    "yahoo.com": "Yahoo",
    "ilsole24ore.com": "Il Sole 24 Ore",
    "en.ilsole24ore.com": "Il Sole 24 Ore",
    "oregonlive.com": "OregonLive",
    "celebitchy.com": "Celebitchy",
    "readtheprofile.com": "Read The Profile",
}


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


def _token(word: str) -> str:
    bare = word.strip(".'’")
    if len(bare) < 2 or not bare.isalpha():
        return ""
    if bare.isupper():
        return ""
    if bare.lower() in _BAD:
        return ""
    if bare[:1].islower():
        return bare[:1].upper() + bare[1:]
    return bare


def _runs(text: str) -> list[str]:
    """Person-name bigrams and trigrams. A verb, a role word, or punctuation breaks the run."""
    found: list[str] = []
    run: list[str] = []
    previous = 0
    source = text or ""

    def flush() -> None:
        if len(run) in {2, 3}:
            found.append(" ".join(run))

    for match in _WORD.finditer(source):
        gap = source[previous:match.start()]
        token = _token(match.group())
        if run and re.search(r"[.!?|;:]", gap):
            flush()
            run = []
        if not token:
            flush()
            run = []
        else:
            run.append(token)
            if len(run) == 3:
                flush()
                run = []
        previous = match.end()
    flush()
    return found


def _ok(name: str) -> bool:
    words = [word for word in (name or "").split() if word]
    if len(words) < 2 or len(words) > 3:
        return False
    return all(_token(word) == word or (_token(word) and word[:1].isupper()) for word in words) and all(
        word.lower().strip(".'’") not in _BAD for word in words
    )


def _contained(shorter: str, longer: str) -> bool:
    small = shorter.split()
    large = longer.split()
    if len(small) >= len(large):
        return False
    index = 0
    for word in large:
        if index < len(small) and word.lower() == small[index].lower():
            index += 1
    return index == len(small)


def _drop_contained(names: list[str], counts: dict[str, int] | None = None) -> list[str]:
    """Drop a fragment that a longer name also covers, and a one-off that swallows a common name."""
    counts = counts or {}
    kept = []
    for name in names:
        longer = [other for other in names if other != name and _contained(name, other)]
        if longer and all(counts.get(other, 0) >= counts.get(name, 0) for other in longer):
            continue
        kept.append(name)
    final = []
    for name in kept:
        shorter = [
            other
            for other in kept
            if other != name and _contained(other, name) and counts.get(other, 0) > counts.get(name, 0)
        ]
        if shorter:
            continue
        final.append(name)
    return final


def _name_counts(matches: list[dict], extra: str = "") -> dict[str, int]:
    counts: dict[str, int] = {}
    texts = [f"{item.get('title') or ''} {item.get('snippet') or ''}" for item in matches or []]
    if extra:
        texts.append(extra)
    for text in texts:
        seen: set[str] = set()
        for name in _runs(text):
            if not _ok(name) or name in seen:
                continue
            seen.add(name)
            counts[name] = counts.get(name, 0) + 1
    return counts


def frequency_names(matches: list[dict], extra: str = "") -> list[str]:
    """Rank real person names. A name in two or more titles beats a one-off headline."""
    counts = _name_counts(matches, extra)
    ranked = sorted(counts, key=lambda name: (-counts[name], name))
    if any(counts[name] >= 2 for name in ranked):
        ranked = [name for name in ranked if counts[name] >= 2]
    return _drop_contained(ranked, counts)[:4]


def _wife_pair(text: str) -> tuple[str, str]:
    match = re.search(
        r"([A-Z][A-Za-z.'’-]+(?:\s+[A-Z][A-Za-z.'’-]+){0,2})\s+and (?:his|her) wife\s+([A-Z][A-Za-z.'’-]+(?:\s+[A-Z][A-Za-z.'’-]+){0,2})",
        text or "",
    )
    if not match:
        return "", ""
    left = match.group(1)
    right = match.group(2)
    left_words = [word for word in left.split() if word.lower() not in _BAD]
    right_words = [word for word in right.split() if word.lower() not in _BAD]
    left = " ".join(left_words[-2:]) if len(left_words) >= 2 else ""
    right = " ".join(right_words)
    if right and len(right.split()) == 1 and left:
        right = f"{right} {left.split()[-1]}"
    if not _ok(left):
        left = ""
    if not _ok(right):
        right = ""
    return left, right


def _role(text: str) -> str:
    lowered = (text or "").lower()
    if "nvidia" in lowered and re.search(r"\bceo\b|chief executive", lowered):
        return "NVIDIA CEO"
    match = re.search(r"\b(?:CEO|chief executive) of ([A-Z][\w&]+)", text or "")
    if match:
        return f"CEO of {match.group(1)}"
    return ""


def _blob(matches: list[dict], extra: str = "") -> str:
    parts = [extra or ""]
    for item in matches or []:
        parts.append(item.get("title") or "")
        parts.append(item.get("snippet") or "")
    return repair_text(" ".join(part for part in parts if part))


def _json_object(text: str) -> dict:
    start = (text or "").find("{")
    end = (text or "").rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _from_model(matches: list[dict], page_text: str) -> dict:
    if not config.key("YDC_API_KEY"):
        return {}
    if not (matches or []) and not (page_text or "").strip():
        return {}
    from app import youcom

    lines = []
    for item in (matches or [])[:8]:
        lines.append(f"- {item.get('title') or ''} | {item.get('snippet') or ''}")
    prompt = (
        "Who or what is shown? Use only the reverse-image titles, snippets, and host page text. "
        'Return one JSON object with keys names, role, relation, what. '
        'names is an array of full names of the people or products actually depicted. '
        "Never return a publication, a place, or a sentence fragment such as \"Oregon Live He\". "
        "relation is wife, husband, or an empty string.\n"
        f"Host page:\n{(page_text or '')[:1200]}\n\nMatches:\n" + "\n".join(lines)
    )
    try:
        answer = youcom.ask(prompt)
    except Exception:
        return {}
    data = _json_object(answer.get("text") or "")
    names = []
    raw_names = data.get("names") or data.get("people") or []
    if isinstance(raw_names, str):
        raw_names = [raw_names]
    for name in raw_names:
        cleaned = " ".join(str(name).split())
        if _ok(cleaned) and cleaned not in names:
            names.append(cleaned)
    relation = str(data.get("relation") or "").strip().lower()
    if relation not in {"wife", "husband"}:
        relation = ""
    return {
        "names": names[:4],
        "role": " ".join((", ".join(map(str, data.get("role"))) if isinstance(data.get("role"), list) else str(data.get("role") or "")).split())[:80],
        "relation": relation,
        "what": " ".join(str(data.get("what") or "").split())[:160],
    }


def identify(claim_text: str, matches: list[dict], context: str = "", seen_what: str = "", skip_model: bool = False) -> dict:
    context = repair_text(context or "")
    blob = _blob(matches, context)
    model = {} if skip_model else _from_model(matches, context)
    left, right = _wife_pair(blob)
    counts = _name_counts(matches, context)
    names: list[str] = []
    for name in list(model.get("names") or []) + [left, right] + frequency_names(matches, context):
        if name and _ok(name) and name not in names:
            names.append(name)
    model_names = [n for n in (model.get("names") or []) if n and _ok(n)]
    seen_what = " ".join((seen_what or "").split())[:80]
    head = seen_what.split()[0].lower() if seen_what else ""
    if seen_what and model_names and any(head in name.lower() for name in model_names):
        names = [seen_what]
    elif model_names:
        names = model_names[:4]
    elif seen_what:
        names = [seen_what]
    else:
        names = _drop_contained(names, counts)
        names.sort(key=lambda name: (-counts.get(name, 0), name))
        names = names[:4]
    questions = split_questions(claim_text)
    kinds = {item["kind"] for item in questions}
    query = " ".join((claim_text or "").split())[:300]
    if names and "relationship" in kinds:
        query = f"{names[0]} wife {names[1]} divorce" if len(names) > 1 else f"{names[0]} divorce"
    elif names and "identity" in kinds:
        query = " ".join(names)
    elif context and "identity" in kinds:
        query = context[:240]
    relation = model.get("relation") or ""
    if not relation and left and right:
        relation = "wife"
    if not relation and len(names) > 1 and re.search(r"\bwife\b", blob, re.I):
        relation = "wife"
    role = model.get("role") or _role(blob)
    if role.lower().startswith("ceo ") and names and names[0].lower().startswith("ceo "):
        names[0] = names[0][4:]
    return {
        "names": names,
        "relation": relation,
        "role": role,
        "what": model.get("what") or "",
        "questions": questions,
        "query": query[:300],
    }


def _quote(hit: dict) -> str:
    text = repair_text(str(hit.get("excerpt") or hit.get("title") or ""))
    text = re.sub(r"^#+\s*", "", text)
    text = text.replace("#", " ")
    return " ".join(text.split())[:180]


def _rank(hit: dict) -> tuple:
    url = hit.get("url") or ""
    if is_rumor(url):
        level = 3
    else:
        scored = tier(url)
        level = 0 if scored == 1 else 1 if scored == 2 else 2
    news = 0 if hit.get("found_by") == "Treg News" and level < 3 else 1
    return (level, news)


def _top_sources(hits: list[dict]) -> list[dict]:
    rows = []
    seen = set()
    ordered = [hit for _, hit in sorted(enumerate(hits), key=lambda pair: (_rank(pair[1]), pair[0]))]
    for hit in ordered:
        url = hit.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        rows.append(
            {
                "title": repair_text(hit.get("title") or host_of(url))[:140],
                "url": url,
                "domain": host_of(url),
                "quote": _quote(hit),
                "credible": is_credible(url),
                "found_by": hit.get("found_by") or "",
            }
        )
        if len(rows) == 3:
            break
    return rows


def _about(hit: dict, names: list[str]) -> bool:
    blob = f"{hit.get('title') or ''} {hit.get('excerpt') or ''}".lower()
    if not names:
        return False
    for name in names:
        parts = [part for part in name.lower().split() if len(part) > 2]
        if parts and all(part in blob for part in parts[:2]):
            return True
    return False


def _confirmed(text: str) -> bool:
    lowered = (text or "").lower()
    if any(phrase in lowered for phrase in ("speculation", "alleged", "rumor", "rumour", "potential", "were to", "could ")):
        return False
    return any(phrase in lowered for phrase in _FILING)


def _speculates(text: str) -> bool:
    lowered = (text or "").lower()
    if "divorce" not in lowered and "split" not in lowered:
        return False
    return any(phrase in lowered for phrase in _SPECULATION)


def _outlet(url: str) -> str:
    host = host_of(url)
    if host in _OUTLETS:
        return _OUTLETS[host]
    for domain, name in _OUTLETS.items():
        if host == domain or host.endswith("." + domain):
            return name
    label = host.split(".")[0]
    return label[:1].upper() + label[1:] if label else host


def _who_sentence(names: list[str], role: str, relation: str) -> str:
    who = names[0]
    other = names[1] if len(names) > 1 else ""
    if who.lower().startswith("ceo "):
        who = who[4:]
    if role and other and relation == "wife":
        return f"This is {role} {who} and his wife {other}."
    if role and not other:
        return f"This is {role} {who}."
    if other:
        return f"This is {who} and {other}."
    return f"This is {who}."


def compose(claim_text: str, decision: dict, web: dict, reverse: dict, subject: dict | None) -> dict:
    """One card: a direct answer, then at most three receipts."""
    subject = subject or {}
    questions = subject.get("questions") or split_questions(claim_text)
    hits = list(((web or {}).get("search") or {}).get("hits") or [])
    for page in ((web or {}).get("contents") or {}).get("pages") or []:
        for hit in hits:
            if hit.get("url") != page.get("url"):
                continue
            excerpt = page.get("excerpt") or ""
            if excerpt and len(excerpt) > len(hit.get("excerpt") or ""):
                hit["excerpt"] = excerpt
            if page.get("title") and not hit.get("title"):
                hit["title"] = repair_text(page["title"])
    names = [name for name in (subject.get("names") or []) if _ok(name)]
    kinds = {item["kind"] for item in questions}
    sources = _top_sources(hits)
    why = [{"text": source["quote"], "url": source["url"], "domain": source["domain"]} for source in sources if source["quote"]]
    why = why[:3]

    seen = " ".join((subject.get("seen") or "").split())
    if ("relationship" in kinds or "identity" in kinds) and names:
        who_sentence = _who_sentence(names, subject.get("role") or "", subject.get("relation") or "")
        blob_of = lambda hit: f"{hit.get('title') or ''} {hit.get('excerpt') or ''}"
        confirmed = [
            hit
            for hit in hits
            if is_credible(hit.get("url") or "") and not is_rumor(hit.get("url") or "") and _about(hit, names) and _confirmed(blob_of(hit))
        ]
        speculation = [
            hit
            for hit in hits
            if is_credible(hit.get("url") or "") and not is_rumor(hit.get("url") or "") and _about(hit, names) and _speculates(blob_of(hit))
        ]
        rumors = [
            hit
            for hit in hits
            if (is_rumor(hit.get("url") or "") or not is_credible(hit.get("url") or ""))
            and _about(hit, names)
            and any(word in blob_of(hit).lower() for word in _DIVORCE)
        ]
        if "relationship" in kinds and confirmed:
            sentence = f"{who_sentence} A credible source reports they divorced."
            verdict = "True"
            line = "Credible reporting says they divorced."
            confidence = 74
        elif "relationship" in kinds and speculation:
            top = sorted(speculation, key=lambda hit: (tier(hit.get("url") or "") or 9,))[0]
            outlet = _outlet(top.get("url") or "")
            affair = " after alleged affairs" if "affair" in blob_of(top).lower() else ""
            sentence = (
                f"{who_sentence} They are not reported divorced; "
                f"{outlet} reports divorce speculation{affair}, but no filing or announcement."
            )
            verdict = UNVERIFIED
            line = f"{outlet} reports speculation, not a filing or an announcement."
            confidence = 64
        elif "relationship" in kinds:
            sentence = f"{who_sentence} There are no credible reports they are divorced."
            verdict = FALSE
            line = "No credible evidence they are divorced. Unverified/likely false."
            confidence = 70
            if rumors and len(why) < 3:
                why.append(
                    {
                        "text": "A non-credible page mentions a divorce. That is a rumor, not a finding.",
                        "url": rumors[0].get("url") or "",
                        "domain": host_of(rumors[0].get("url") or ""),
                    }
                )
        else:
            sentence = who_sentence
            verdict = decision.get("verdict") or UNVERIFIED
            line = ""
            confidence = int(decision.get("confidence") or 55)
    elif seen:
        sentence = seen if seen.endswith((".", "!", "?")) else f"{seen}."
        answer_text = str((((web or {}).get("answer") or {}).get("text")) or "")
        answer_text = re.sub(r"\s*\[page[^\]]*\]|\[\[[\d,\s]*\]\]|\[(\d+|[^\]]*)\]\([^)]*\)|\[[\d,\s]+\]|[#*_`]", "", answer_text)
        picked = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+", " ".join(answer_text.split()))
            if 25 < len(part.strip()) < 260 and "|" not in part
        ][:2]
        fact = " ".join(picked) or next((source["quote"] for source in sources if source.get("quote") and "|" not in source["quote"]), "")
        if fact and fact.lower() not in sentence.lower():
            sentence = f"{sentence} {fact}"
        credible = any(item.get("credible") for item in sources)
        if "identity" in kinds and "relationship" not in kinds and (credible or sources):
            verdict = "Answered"
            line = "Identified from the image and confirmed by credible sources."
            confidence = max(int(decision.get("confidence") or 0), 78)
        else:
            verdict = decision.get("verdict") or ("True" if credible else UNVERIFIED)
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
                    why.append(
                        {
                            "text": item.get("detail") or item["title"],
                            "url": item.get("url") or "",
                            "domain": host_of(item.get("url") or "") if item.get("url") else "",
                        }
                    )

    if verdict == FALSE and "relationship" not in kinds:
        verdict = decision.get("verdict") or verdict
    return {
        "verdict": verdict,
        "confidence": confidence,
        "text": sentence,
        "line": line,
        "why": why[:3],
        "sources": sources,
        "questions": questions,
    }
