"""EXIF and a lightweight C2PA / content-credentials scan.

The full c2pa library is optional. If the manifest bytes are present we record
that, including a generative-tool hint, and keep going when they are not.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image

MAKE = 271
MODEL = 272
SOFTWARE = 305
DATETIME = 306

GENERATIVE_HINTS = (
    "stable diffusion",
    "midjourney",
    "dall-e",
    "dalle",
    "openai",
    "firefly",
    "generative",
    "novelai",
    "comfyui",
    "imagen",
    "flux",
)


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return str(value).replace("\x00", "").strip()


def _exif(data: bytes) -> dict:
    empty = {"make": "", "model": "", "software": "", "datetime": ""}
    try:
        with Image.open(BytesIO(data)) as image:
            raw = image.getexif()
    except Exception:
        return empty
    if not raw:
        return empty
    return {
        "make": _text(raw.get(MAKE)),
        "model": _text(raw.get(MODEL)),
        "software": _text(raw.get(SOFTWARE)),
        "datetime": _text(raw.get(DATETIME)),
    }


def _window(data: bytes, needle: bytes, span: int = 80) -> str:
    index = data.lower().find(needle)
    if index < 0:
        return ""
    chunk = data[index : index + span]
    return chunk.decode("latin-1", "replace").replace("\x00", " ").strip()


def _c2pa(data: bytes) -> dict:
    lowered = data.lower()
    present = b"c2pa" in lowered or b"jumbf" in lowered or b"claim_generator" in lowered
    snippet = ""
    if present:
        snippet = _window(lowered, b"claim_generator") or _window(lowered, b"c2pa")
    generative = present and any(hint.encode() in lowered for hint in GENERATIVE_HINTS)
    camera = present and not generative and (b"camera" in lowered or b"capture" in lowered)
    return {
        "present": present,
        "generative": generative,
        "camera": camera,
        "snippet": snippet[:160],
    }


def inspect(data: bytes) -> dict:
    exif = _exif(data)
    c2pa = _c2pa(data)
    software = exif["software"].lower()
    software_generative = any(hint in software for hint in GENERATIVE_HINTS)
    notes = []
    if c2pa["present"]:
        notes.append("C2PA marker bytes are present.")
    elif exif["make"] or exif["datetime"] or exif["software"]:
        notes.append("EXIF metadata is present.")
    else:
        notes.append("No EXIF camera tags and no C2PA marker were found.")
    return {
        "status": "ok",
        "detail": " ".join(notes),
        "exif": exif,
        "c2pa": c2pa,
        "software_generative": software_generative,
    }
