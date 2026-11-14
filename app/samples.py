"""Three synthetic sample images so the desk demo runs without API keys."""

from __future__ import annotations

import json

from PIL import Image, ImageDraw

from app import config

MAKE = 271
MODEL = 272
SOFTWARE = 305
DATETIME = 306

MANIFEST = [
    {
        "id": "wire",
        "file": "wire.jpg",
        "title": "City hall, this morning",
        "blurb": "Camera-style file and a same-day claim. Without a You.com key this stays unverified.",
        "claim": "A crowd gathered outside city hall this morning after a surprise transit announcement.",
        "exif": {
            MAKE: "Canon",
            MODEL: "EOS R6",
            SOFTWARE: "Adobe Photoshop Lightroom Classic",
            DATETIME: "2026:11:14 08:05:00",
        },
    },
    {
        "id": "synthetic",
        "file": "synthetic.jpg",
        "title": "Relief-bill photograph",
        "blurb": "The software tag names a generative model. The claim says the photo is breaking news.",
        "claim": "Breaking: this photograph shows the president signing the relief bill an hour ago.",
        "exif": {
            SOFTWARE: "Stable Diffusion XL",
        },
    },
    {
        "id": "archive",
        "file": "archive.jpg",
        "title": "Flooding, claimed as this morning",
        "blurb": "The file date is 2011. The caption says the picture was taken this morning.",
        "claim": "This photo was taken this morning of flooding downtown.",
        "exif": {
            MAKE: "Nikon",
            MODEL: "D700",
            SOFTWARE: "Nikon Transfer",
            DATETIME: "2011:03:11 14:46:23",
        },
    },
]


def _gradient(size, top, bottom) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        blend = y / (height - 1)
        color = tuple(int(top[channel] * (1 - blend) + bottom[channel] * blend) for channel in range(3))
        draw.line([(0, y), (width, y)], fill=color)
    return image


def _stamp(draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int]) -> None:
    draw.rectangle([xy[0], xy[1], xy[0] + 118, xy[1] + 28], fill=(196, 85, 42))
    draw.text((xy[0] + 12, xy[1] + 7), text, fill=(255, 248, 240))


def _draw(sample_id: str) -> Image.Image:
    if sample_id == "wire":
        image = _gradient((960, 600), (186, 214, 228), (92, 122, 138))
        draw = ImageDraw.Draw(image)
        draw.ellipse([720, 48, 860, 188], fill=(244, 214, 150))
        for index, (x, h) in enumerate(((70, 280), (210, 340), (360, 250), (520, 390))):
            shade = 54 + index * 12
            draw.rectangle([x, 600 - h, x + 120, 560], fill=(shade, shade + 4, shade + 8))
            for row in range(4):
                for col in range(3):
                    draw.rectangle(
                        [x + 16 + col * 32, 600 - h + 24 + row * 48, x + 36 + col * 32, 600 - h + 48 + row * 48],
                        fill=(214, 206, 176),
                    )
        draw.rectangle([0, 520, 960, 600], fill=(28, 36, 34))
        draw.text((28, 548), "SAMPLE  ·  city hall desk photo", fill=(232, 224, 206))
        _stamp(draw, "SAMPLE", (800, 36))
        return image
    if sample_id == "synthetic":
        image = _gradient((960, 600), (246, 92, 72), (64, 28, 92))
        draw = ImageDraw.Draw(image)
        draw.ellipse([80, 70, 520, 520], fill=(255, 196, 92))
        draw.ellipse([300, 160, 860, 560], fill=(72, 196, 186))
        draw.rectangle([180, 220, 780, 380], fill=(250, 246, 238))
        draw.text((210, 268), "GENERATED SAMPLE", fill=(28, 24, 48))
        _stamp(draw, "SAMPLE", (800, 36))
        return image
    image = _gradient((960, 600), (176, 146, 110), (78, 62, 48))
    draw = ImageDraw.Draw(image)
    draw.polygon([(0, 430), (220, 300), (420, 450), (640, 260), (960, 420), (960, 600), (0, 600)], fill=(92, 78, 64))
    draw.rectangle([0, 470, 960, 600], fill=(64, 86, 96))
    draw.text((28, 500), "SAMPLE  ·  file date 2011", fill=(232, 220, 196))
    _stamp(draw, "SAMPLE", (800, 36))
    return image


def _write(sample: dict, path) -> None:
    image = _draw(sample["id"])
    exif = Image.Exif()
    for tag, value in sample["exif"].items():
        exif[tag] = value
    image.save(path, format="JPEG", quality=86, exif=exif.tobytes())


def ensure() -> None:
    config.SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    for sample in MANIFEST:
        path = config.SAMPLES_DIR / sample["file"]
        if not path.exists():
            _write(sample, path)
    manifest_path = config.SAMPLES_DIR / "manifest.json"
    public = [
        {
            "id": sample["id"],
            "title": sample["title"],
            "blurb": sample["blurb"],
            "claim": sample["claim"],
            "image": f"/api/demos/{sample['id']}/image",
        }
        for sample in MANIFEST
    ]
    manifest_path.write_text(json.dumps(public, indent=2), encoding="utf-8")


def get(sample_id: str) -> dict | None:
    ensure()
    for sample in MANIFEST:
        if sample["id"] == sample_id:
            path = config.SAMPLES_DIR / sample["file"]
            return {
                "id": sample["id"],
                "title": sample["title"],
                "blurb": sample["blurb"],
                "claim": sample["claim"],
                "path": path,
                "bytes": path.read_bytes(),
            }
    return None


def public_list() -> list[dict]:
    ensure()
    return [
        {
            "id": sample["id"],
            "title": sample["title"],
            "blurb": sample["blurb"],
            "claim": sample["claim"],
            "image": f"/api/demos/{sample['id']}/image",
        }
        for sample in MANIFEST
    ]
