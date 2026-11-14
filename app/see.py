"""SEE: describe an image with Treg first, then Gemini or OpenAI."""

from __future__ import annotations

import base64
import time
from urllib.parse import quote

from app import config, httputil, sponsors, vision

_QUERIES = (
    "image captioning",
    "vision llm",
    "describe image",
    "gpt-4o",
    "gemini",
    "openrouter",
)
_HINTS = ("caption", "vision", "multimodal", "image-to-text", "ocr", "describe", "gpt-4o", "gemini")


def _ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _tools(body) -> list:
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    if not isinstance(body, dict):
        return []
    for key in ("tools", "results", "items", "data"):
        rows = body.get(key)
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    return []


def _tool_id(tool: dict) -> str:
    return str(tool.get("id") or tool.get("tool") or tool.get("name") or "").strip()


def _pick(tools: list) -> str:
    for tool in tools:
        blob = " ".join(str(tool.get(key) or "") for key in ("id", "name", "description", "title")).lower()
        if any(hint in blob for hint in _HINTS):
            chosen = _tool_id(tool)
            if chosen:
                return chosen
    return ""


def _text_from(body) -> str:
    if isinstance(body, str):
        return body.strip()
    if not isinstance(body, dict):
        return ""
    for key in ("caption", "text", "description", "output", "content", "answer"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = _text_from(value)
            if nested:
                return nested
    return ""


def _search_catalog(token: str) -> tuple[str, str, int]:
    """Try several catalog queries. Returns tool id, error detail, and elapsed ms."""
    started = time.perf_counter()
    last_status = 0
    for query in _QUERIES:
        try:
            status, body = httputil.get_json(
                f"https://treg.to/catalog/search?q={quote(query)}",
                {"X-Treg-Token": token},
                timeout=20,
            )
        except Exception:
            return "", "Treg vision catalog could not be reached.", _ms(started)
        last_status = status
        if status != 200:
            continue
        tool = _pick(_tools(body))
        if tool:
            return tool, "", _ms(started)
    env_tool = config.key("TREG_VISION_TOOL")
    if env_tool:
        return env_tool, "", _ms(started)
    if last_status and last_status != 200:
        return "", f"Treg vision catalog returned HTTP {last_status}.", _ms(started)
    return "", "Treg catalog has no vision tool.", _ms(started)


def _treg(image_url: str, image: bytes, media_type: str) -> dict:
    empty = {"status": "skipped", "text": "", "provider": "", "tool": "", "latency_ms": 0, "detail": ""}
    if not config.key("TREG_API_KEY"):
        empty["detail"] = "Treg vision: add key"
        return empty
    tool, detail, elapsed = _search_catalog(config.key("TREG_API_KEY"))
    if not tool and detail.startswith("Treg vision catalog could not"):
        return {**empty, "status": "error", "detail": detail, "latency_ms": elapsed}
    if not tool and "HTTP" in detail:
        return {**empty, "status": "error", "detail": detail, "latency_ms": elapsed}
    if not tool:
        return {**empty, "detail": "Treg catalog has no vision tool. The check continued.", "latency_ms": elapsed}
    started = time.perf_counter()
    prompt = "Describe this image. Name the main objects, people, or products, and transcribe any visible text."
    payload = {"prompt": prompt}
    if image_url:
        payload["image_url"] = image_url
        payload["url"] = image_url
    elif image:
        encoded = base64.b64encode(image).decode("ascii")
        payload["image_url"] = f"data:{media_type or 'image/jpeg'};base64,{encoded}"
    else:
        return {**empty, "detail": "No image to send to Treg vision.", "latency_ms": _ms(started)}
    try:
        called, result = httputil.post_json(
            f"https://treg.to/call/{quote(tool, safe='.')}",
            {"X-Treg-Token": config.key("TREG_API_KEY")},
            payload,
            timeout=40,
        )
    except Exception:
        sponsors.record("see", called=True, latency_ms=_ms(started), status="error")
        return {**empty, "status": "error", "tool": tool, "detail": "Treg vision call failed.", "latency_ms": _ms(started)}
    elapsed = _ms(started)
    text = _text_from(result)
    if called != 200 or not text:
        sponsors.record("see", called=True, latency_ms=elapsed, status="error")
        return {
            **empty,
            "status": "error",
            "tool": tool,
            "provider": "Treg",
            "detail": f"Treg vision returned HTTP {called}.",
            "latency_ms": elapsed,
        }
    sponsors.record("see", called=True, latency_ms=elapsed, status="ok")
    return {
        "status": "ok",
        "text": text[:800],
        "provider": "Treg",
        "tool": tool,
        "latency_ms": elapsed,
        "detail": f"Described with Treg {tool}.",
    }


def describe(image_url: str, image: bytes, media_type: str, caption: str) -> dict:
    """Never raises. Vision is optional; the check continues either way."""
    try:
        seen = _treg(image_url, image, media_type)
    except Exception:
        seen = {"status": "error", "text": "", "provider": "", "tool": "", "latency_ms": 0, "detail": "Treg vision failed."}
    if seen.get("text"):
        return seen
    if image and (config.key("OPENAI_API_KEY") or config.key("GEMINI_API_KEY")):
        started = time.perf_counter()
        try:
            claim, stage = vision.extract(image, media_type or "image/jpeg", caption)
        except Exception:
            claim, stage = {}, {"status": "error", "detail": "Gemini or OpenAI vision failed."}
        text = (claim or {}).get("text") or ""
        if stage.get("status") == "ok" and text:
            return {
                "status": "ok",
                "text": text[:800],
                "provider": "Gemini" if config.key("GEMINI_API_KEY") and not config.key("OPENAI_API_KEY") else "OpenAI",
                "tool": "",
                "latency_ms": _ms(started),
                "detail": stage.get("detail") or "Described with a vision model.",
            }
        return {
            "status": stage.get("status") or "error",
            "text": "",
            "provider": "",
            "tool": "",
            "latency_ms": _ms(started),
            "detail": stage.get("detail") or "Vision model did not return a description.",
        }
    if seen.get("status") == "error":
        seen["detail"] = (seen.get("detail") or "Vision step unavailable.") + " The check continued."
        return seen
    return {
        "status": "skipped",
        "text": "",
        "provider": "",
        "tool": "",
        "latency_ms": 0,
        "detail": "Vision step unavailable. No Treg vision tool or Gemini/OpenAI key. The check continued.",
    }


def from_matches(matches: list, claim: str) -> dict:
    """SEE fallback: name the photo from reverse-image titles when no vision tool exists."""
    empty = {
        "status": "skipped",
        "text": "",
        "provider": "",
        "tool": "",
        "latency_ms": 0,
        "detail": "Vision step unavailable. No Treg vision tool or Gemini/OpenAI key. The check continued.",
    }
    if not matches:
        return empty
    lines = [f"- {item.get('title') or ''} {item.get('snippet') or ''}".strip() for item in matches[:8]]
    text = ""
    provider = "Treg lens"
    if config.key("YDC_API_KEY"):
        from app import youcom

        prompt = (
            "These reverse-image page titles describe one photo. "
            "In one or two sentences, say who or what is shown. Do not decide whether anyone is divorced.\n"
            + "\n".join(lines)
        )
        try:
            answer = youcom.ask(prompt)
        except Exception:
            answer = {"text": ""}
        text = " ".join((answer.get("text") or "").split())
        if text:
            provider = "You.com Answer"
    if not text:
        from app.questions import frequency_names

        names = frequency_names(matches, claim)
        if names:
            shown = " and ".join(names[:2])
            text = f"Reverse-image pages describe {shown}."
    if not text:
        return empty
    detail = (
        "No Treg vision tool was found. SEE used Treg reverse-image titles"
        + (" and You.com Answer." if provider == "You.com Answer" else ".")
        + " The check continued."
    )
    return {
        "status": "ok",
        "text": text[:800],
        "provider": provider,
        "tool": "",
        "latency_ms": 0,
        "detail": detail,
    }
