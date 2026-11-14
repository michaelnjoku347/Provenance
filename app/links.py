"""Turn a pasted link into a claim: an X post, or an article page."""

from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import quote, urlparse

from app import config, httputil, youcom

OEMBED_URL = "https://publish.twitter.com/oembed"
_STATUS_HOSTS = {"x.com", "twitter.com", "mobile.twitter.com"}
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_TWIMG = re.compile(r"https://pbs\.twimg\.com/[^\s\"'<>]+", re.I)


def _host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def is_status_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    if _host(url) not in _STATUS_HOSTS:
        return False
    return bool(re.search(r"/status/\d+", parsed.path))


def is_direct_image(url: str) -> bool:
    path = urlparse((url or "").strip()).path.lower()
    return path.endswith(_IMAGE_EXT)


def _parse_date(value: str) -> str:
    text = " ".join((value or "").split())
    if not text:
        return ""
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    return ""


class _TweetHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_p = False
        self._p: list[str] = []
        self.paragraphs: list[str] = []
        self._date_href = False
        self.date_text = ""
        self.images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "p":
            self._in_p = True
            self._p = []
        if tag == "img" and values.get("src", "").startswith("http"):
            self.images.append(values["src"])
        href = values.get("href", "")
        self._date_href = tag == "a" and "/status/" in href

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._in_p:
            text = " ".join("".join(self._p).split())
            if text:
                self.paragraphs.append(text)
            self._in_p = False
        if tag == "a":
            self._date_href = False

    def handle_data(self, data: str) -> None:
        if self._in_p:
            self._p.append(data)
        if self._date_href and not self.date_text:
            cleaned = " ".join(data.split())
            if cleaned:
                self.date_text = cleaned


def _tweet_from_html(html: str) -> tuple[str, str, str]:
    parser = _TweetHTML()
    try:
        parser.feed(html or "")
    except Exception:
        return "", "", ""
    text = " ".join(parser.paragraphs).strip()
    image = ""
    for candidate in parser.images + _TWIMG.findall(html or ""):
        if candidate.startswith("https://"):
            image = candidate.rstrip("\\")
            break
    return text, parser.date_text, image


def fetch_status(url: str) -> dict:
    record = {
        "kind": "status",
        "status": "error",
        "url": url,
        "author": "",
        "author_url": "",
        "posted_at": "",
        "text": "",
        "title": "",
        "image_url": "",
        "claim": "",
        "search_query": "",
        "detail": "",
    }
    endpoint = f"{OEMBED_URL}?url={quote(url, safe='')}&omit_script=true"
    try:
        status, body = httputil.get_json(endpoint, timeout=15)
    except Exception:
        record["detail"] = "X oEmbed could not be reached. Paste the post text as the claim."
        return record
    if status != 200 or not isinstance(body, dict):
        record["detail"] = f"X oEmbed returned HTTP {status}. Paste the post text as the claim."
        return record
    text, date_text, image = _tweet_from_html(str(body.get("html") or ""))
    author = str(body.get("author_name") or "").strip()
    record.update(
        {
            "status": "ok" if text else "error",
            "author": author[:120],
            "author_url": str(body.get("author_url") or "")[:300],
            "posted_at": _parse_date(date_text),
            "text": text[:1000],
            "title": author or "X post",
            "image_url": image[:500],
            "claim": text[:1000],
            "search_query": text[:300],
            "detail": "Read the post from X oEmbed." if text else "X oEmbed did not include the post text.",
        }
    )
    return record


class _PageHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self.title = ""
        self.description = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key in {"description", "og:description"} and not self.description:
                self.description = " ".join(values.get("content", "").split())[:700]

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and not self.title:
            self.title = " ".join(data.split())[:180]


def _page_from_html(html: str) -> tuple[str, str]:
    parser = _PageHTML()
    try:
        parser.feed(html or "")
    except Exception:
        return "", ""
    return parser.title, parser.description


def fetch_article(url: str) -> dict:
    record = {
        "kind": "article",
        "status": "error",
        "url": url,
        "author": "",
        "author_url": "",
        "posted_at": "",
        "text": "",
        "title": "",
        "image_url": "",
        "claim": "",
        "search_query": "",
        "detail": "",
    }
    title = ""
    text = ""
    if config.key("YDC_API_KEY"):
        try:
            page = youcom.read_page(url)
        except Exception:
            page = {"status": "error", "pages": [], "detail": "You.com contents failed."}
        pages = page.get("pages") or []
        if page.get("status") == "ok" and pages:
            title = str(pages[0].get("title") or "")
            text = str(pages[0].get("excerpt") or "")
            record["detail"] = "Read the page with You.com contents."
    if not title and not text:
        try:
            status, html = httputil.get_text(url, timeout=12)
        except Exception:
            record["detail"] = record["detail"] or "The page could not be fetched. Paste the claim instead."
            return record
        if status != 200:
            record["detail"] = f"The page returned HTTP {status}. Paste the claim instead."
            return record
        title, text = _page_from_html(html)
        record["detail"] = "Read the page title from the link."
    title = title.strip()
    text = " ".join(text.split())
    if title and text:
        claim = f"{title} — {text[:500]}"
    else:
        claim = title or text[:500]
    record.update(
        {
            "status": "ok" if claim else "error",
            "title": title[:180],
            "text": text[:1000],
            "claim": claim[:1000],
            "search_query": (title or claim)[:300],
        }
    )
    if not claim:
        record["detail"] = "The page had no title or text to use as a claim."
    return record


def resolve(url: str) -> dict:
    url = (url or "").strip()
    if is_status_url(url):
        return fetch_status(url)
    if url.startswith("http") and not is_direct_image(url):
        return fetch_article(url)
    return {
        "kind": "",
        "status": "skipped",
        "url": url,
        "author": "",
        "author_url": "",
        "posted_at": "",
        "text": "",
        "title": "",
        "image_url": "",
        "claim": "",
        "search_query": "",
        "detail": "",
    }
