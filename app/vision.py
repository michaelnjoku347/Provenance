"""Pull a checkable claim out of the image with OpenAI or Gemini."""

from __future__ import annotations

import base64
import json

from app import config, httputil

PROMPT = (
    "Extract the central checkable claim in this image and caption. "
    "Return one JSON object with keys claim, who, what, where, when, search_query. "
    "claim is one sentence a newsroom could verify against reporting. "
    "search_query is a short web search for that event. "
    "Use empty strings when unknown. If the caption and the picture disagree, say so in claim. "
    "No markdown."
)


def _blank(caption: str, source: str) -> dict:
    text = caption.strip()
    return {
        "text": text,
        "who": "",
        "what": "",
        "where": "",
        "when": "",
        "search_query": text[:300],
        "source": source,
    }


def _parse(raw: str) -> dict:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no json")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return data


def _claim_from_model(data: dict, fallback: str) -> dict:
    text = str(data.get("claim") or fallback or "").strip()
    query = str(data.get("search_query") or text).strip()[:300]
    return {
        "text": text[:600],
        "who": str(data.get("who") or "")[:160],
        "what": str(data.get("what") or "")[:160],
        "where": str(data.get("where") or "")[:160],
        "when": str(data.get("when") or "")[:160],
        "search_query": query,
        "source": "vision",
    }


def _openai(data: bytes, media_type: str, caption: str) -> dict:
    encoded = base64.b64encode(data).decode("ascii")
    payload = {
        "model": config.openai_model(),
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Caption supplied with the upload:\n{caption or '(none)'}"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                    },
                ],
            },
        ],
    }
    status, body = httputil.post_json(
        "https://api.openai.com/v1/chat/completions",
        {"Authorization": f"Bearer {config.key('OPENAI_API_KEY')}"},
        payload,
        timeout=40,
    )
    if status != 200 or not isinstance(body, dict):
        raise RuntimeError(f"OpenAI returned HTTP {status}")
    content = body["choices"][0]["message"]["content"]
    return _claim_from_model(_parse(content), caption)


def _gemini(data: bytes, media_type: str, caption: str) -> dict:
    model = config.gemini_model()
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={config.key('GEMINI_API_KEY')}"
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": PROMPT + f"\n\nCaption supplied with the upload:\n{caption or '(none)'}"},
                    {
                        "inline_data": {
                            "mime_type": media_type,
                            "data": base64.b64encode(data).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    status, body = httputil.post_json(url, {}, payload, timeout=40)
    if status != 200 or not isinstance(body, dict):
        raise RuntimeError(f"Gemini returned HTTP {status}")
    parts = body["candidates"][0]["content"]["parts"]
    text = "".join(part.get("text", "") for part in parts)
    return _claim_from_model(_parse(text), caption)


def extract(data: bytes, media_type: str, caption: str) -> tuple[dict, dict]:
    """Return (claim, stage). Never raises."""
    caption = (caption or "").strip()
    provider = ""
    try:
        if config.key("OPENAI_API_KEY"):
            provider = "OpenAI"
            claim = _openai(data, media_type, caption)
        elif config.key("GEMINI_API_KEY"):
            provider = "Gemini"
            claim = _gemini(data, media_type, caption)
        else:
            source = "caption" if caption else "none"
            claim = _blank(caption, source)
            if not caption:
                claim["text"] = ""
            return claim, {
                "status": "skipped",
                "detail": "Set OPENAI_API_KEY or GEMINI_API_KEY to read the image. The caption is the claim for now.",
            }
    except Exception:
        claim = _blank(caption, "caption" if caption else "none")
        return claim, {
            "status": "error",
            "detail": f"{provider or 'Vision'} could not be read. The caption is the claim for now.",
        }
    return claim, {"status": "ok", "detail": f"Claim read with {provider}."}
