"""A local AI-image prior. It is one weak clue and cannot carry a verdict alone."""

from __future__ import annotations

from io import BytesIO

from PIL import Image


def _texture(data: bytes) -> float:
    try:
        image = Image.open(BytesIO(data)).convert("L").resize((64, 64))
    except Exception:
        return 0.4
    pixels = list(image.getdata())
    total = 0
    count = 0
    for y in range(64):
        row = y * 64
        for x in range(63):
            total += abs(pixels[row + x] - pixels[row + x + 1])
            count += 1
    mean = total / max(count, 1)
    # Smooth graphics score a bit higher. The range stays inside 0.28–0.55.
    return round(0.55 - min(0.27, mean / 140), 2)


def score(data: bytes, credentials: dict) -> dict:
    note = "Local prior only. Count it as one weak clue, not a lab detector."
    if credentials.get("c2pa", {}).get("generative") or credentials.get("software_generative"):
        value = 0.84
        note = "Raised because the file names a generative tool. Still one weak clue."
    elif credentials.get("exif", {}).get("make"):
        value = 0.2
    else:
        value = _texture(data)
    label = "high" if value >= 0.75 else "low" if value <= 0.3 else "mixed"
    return {
        "status": "ok",
        "score": value,
        "label": label,
        "method": "local_prior",
        "note": note,
    }
