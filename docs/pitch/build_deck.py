"""Build docs/pitch/Provenance-pitch.pptx and a PNG of each slide.

Every slide is described once as a list of shapes in 1920x1080 pixel space.
The same list is written to the .pptx (python-pptx) and drawn to PNG (Pillow),
so the PNGs show the layout that Google Slides will import.

    pip install python-pptx pillow
    python3 docs/pitch/build_deck.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Pt

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "pitch"
PNG_DIR = OUT / "png"
SAMPLES = ROOT / "samples"
W, H = 1920, 1080
EMU = 12192000 // W
TMP = Path(tempfile.mkdtemp(prefix="pitch-"))

INK = "#070A0D"
PANEL = "#10151B"
PANEL2 = "#161D26"
LINE = "#1C2430"
LIME = "#C8F54A"
CYAN = "#2EE6D6"
AMBER = "#FFB020"
ROSE = "#FF5C7A"
MIST = "#8B97A6"
PAPER = "#E8EDF2"

FONT_DIR = Path("/usr/share/fonts/truetype/macos")
WEIGHTS = {"regular": "Inter-Regular.ttf", "medium": "Inter-Medium.ttf", "semibold": "Inter-SemiBold.ttf", "bold": "Inter-Bold.ttf"}
_font_cache: dict = {}


def font(weight: str, px: int):
    key = (weight, px)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(str(FONT_DIR / WEIGHTS[weight]), px)
    return _font_cache[key]


def rgb(hex_: str):
    hex_ = hex_.lstrip("#")
    return tuple(int(hex_[i : i + 2], 16) for i in (0, 2, 4))


def mix(a: str, b: str, t: float) -> str:
    ra, rb = rgb(a), rgb(b)
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ra, rb))


# ---------- shape constructors ----------

def rect(x, y, w, h, fill=None, line=None, radius=0, lw=2):
    return {"k": "rect", "x": x, "y": y, "w": w, "h": h, "fill": fill, "line": line, "r": radius, "lw": lw}


def text(x, y, w, h, s, size=20, color=PAPER, weight="regular", align="left", anchor="top", spacing=1.2, tracking=0):
    return {"k": "text", "x": x, "y": y, "w": w, "h": h, "s": s, "size": size, "color": color, "weight": weight,
            "align": align, "anchor": anchor, "spacing": spacing, "tracking": tracking}


def image(x, y, w, h, path, radius=0):
    return {"k": "img", "x": x, "y": y, "w": w, "h": h, "path": str(path), "r": radius}


def pill(x, y, label, color, size=13, h=40, filled=False, weight="bold", pad=20):
    f = font(weight, size * 2)
    tw = f.getlength(label) + size * 2 * 0.06 * len(label)
    w = int(tw + pad * 2)
    fill = color if filled else mix(INK, color, 0.14)
    return [
        rect(x, y, w, h, fill=fill, line=color, radius=h // 2, lw=2),
        text(x, y, w, h, label, size=size, color=INK if filled else color, weight=weight, align="center", anchor="middle", tracking=0.06),
    ], w


# ---------- assets ----------

def cubic(p0, p1, p2, p3, n=40):
    pts = []
    for i in range(n + 1):
        t = i / n
        a = (1 - t) ** 3
        b = 3 * (1 - t) ** 2 * t
        c = 3 * (1 - t) * t ** 2
        d = t ** 3
        pts.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return pts


def make_logo(size=512) -> Path:
    s = size / 32
    big = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    pts = []
    pts += cubic((5.2, 16), (9.7, 9.4), (13.5, 7), (16, 7))
    pts += cubic((16, 7), (18.5, 7), (22.3, 9.4), (26.8, 16))
    pts += cubic((26.8, 16), (22.3, 22.6), (18.5, 25), (16, 25))
    pts += cubic((16, 25), (13.5, 25), (9.7, 22.6), (5.2, 16))
    d.polygon([(x * s, y * s) for x, y in pts], fill=rgb(LIME))
    r = 5.15 * s
    d.ellipse((16 * s - r, 16 * s - r, 16 * s + r, 16 * s + r), fill=rgb(INK))
    check = [(13.7 * s, 16.15 * s), (15.6 * s, 18 * s), (19.35 * s, 14 * s)]
    lw = int(1.85 * s)
    d.line(check, fill=rgb(LIME), width=lw, joint="curve")
    for px, py in (check[0], check[-1]):
        d.ellipse((px - lw / 2, py - lw / 2, px + lw / 2, py + lw / 2), fill=rgb(LIME))
    path = TMP / "logo.png"
    big.save(path)
    return path


def make_background() -> Path:
    bg = Image.new("RGB", (W, H), rgb(INK))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((-500, -520, 1100, 380), fill=(30, 40, 12))
    g.ellipse((1250, -420, 2350, 320), fill=(8, 34, 34))
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    bg = Image.fromarray(__import__("numpy").clip(__import__("numpy").asarray(bg, dtype="int16") + __import__("numpy").asarray(glow, dtype="int16"), 0, 255).astype("uint8")) if _has_numpy() else Image.blend(bg, glow, 0.5)
    d = ImageDraw.Draw(bg)
    for x in range(0, W, 96):
        d.line((x, 0, x, H), fill=(11, 15, 19))
    for y in range(0, H, 96):
        d.line((0, y, W, y), fill=(11, 15, 19))
    path = TMP / "bg.png"
    bg.save(path)
    return path


def _has_numpy():
    try:
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


def cover(src: Path, w: int, h: int, name: str, focus=(0.5, 0.5), caption: str | None = None) -> Path:
    im = Image.open(src).convert("RGB")
    scale = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    left = int((im.width - w) * focus[0])
    top = int((im.height - h) * focus[1])
    im = im.crop((left, top, left + w, top + h))
    path = TMP / f"{name}.png"
    im.save(path)
    return path


# ---------- chrome ----------

LOGO = None
SHOT = None
RULE = "#2A323D"
BG_FILL = "#0B0E12"


def shot(box, name):
    """Crop the app screenshot; box is in 1600x1000 CSS pixels."""
    im = Image.open(SHOT)
    k = im.width / 1600
    x0, y0, x1, y1 = (round(v * k) for v in box)
    path = TMP / f"{name}.png"
    im.crop((x0, y0, x1, y1)).save(path)
    return path


def hrule(x, y, w, color=RULE, t=2):
    return rect(x, y, w, t, fill=color)


def chrome(n: int, section: str):
    return [
        rect(0, 0, W, H, fill=BG_FILL),
        hrule(96, 72, 1728),
        text(96, 32, 600, 32, "PROVENANCE", size=11, color=PAPER, weight="bold", tracking=0.2, anchor="middle"),
        text(520, 32, 900, 32, section.upper(), size=11, color=MIST, weight="medium", tracking=0.2, anchor="middle"),
        text(1424, 32, 400, 32, f"{n} / 8", size=11, color=MIST, weight="medium", align="right", anchor="middle", tracking=0.1),
    ]


def badge(x, y, label, color, size=16, h=52):
    f = font("bold", size * 2)
    w = int(f.getlength(label) + size * 2 * 0.08 * len(label) + 48)
    return [rect(x, y, w, h, fill=color, radius=6),
            text(x, y, w, h, label, size=size, color=INK, weight="bold", align="center", anchor="middle", tracking=0.08)], w


# ---------- slides ----------

def slide_title():
    s = [rect(0, 0, W, H, fill=BG_FILL)]
    hero = shot((0, 0, 1180, 640), "hero")
    s += [
        image(1010, 150, 1180, 640, hero),
        rect(1010, 150, 1180, 640, line=RULE, lw=2),
        image(96, 96, 64, 64, LOGO),
        text(180, 96, 600, 64, "Provenance", size=20, weight="semibold", anchor="middle"),
        text(96, 300, 860, 460, "Every answer comes with proof.", size=58, weight="bold", spacing=1.02),
        hrule(96, 880, 860),
        text(96, 900, 860, 40, "Ground Truth hackathon, You.com  ·  New York, Nov 14, 2026", size=13, color=MIST),
        text(1010, 806, 900, 36, "The desk, live. A claim checker for images, X posts and article links.", size=13, color=MIST),
    ]
    notes = ("I'm Michael. This is Provenance. You give it a viral image, an X post or an article link, "
             "and it tells you whether the claim is true, with the sources to prove it.")
    return s, notes


def slide_problem():
    s = chrome(2, "The problem")
    img = cover(SAMPLES / "copacabana.jpg", 1000, 667, "s2-copa", focus=(0, 0))
    s += [
        text(96, 150, 700, 520, "The photo is real. The caption isn't.", size=64, weight="bold", spacing=1.04),
        text(96, 700, 640, 120, "Posts like this spread faster than any fact-check can catch them.", size=20, color=MIST, spacing=1.4),
        image(824, 150, 1000, 667, img),
        hrule(824, 845, 1000),
        text(824, 864, 1000, 40, "SHARED AS  \u201cTrump's May 11 rally in Wildwood, New Jersey.\u201d", size=14, color=PAPER, weight="semibold"),
        text(824, 908, 1000, 40, "Actually Copacabana beach, Rio. Reuters fact check, May 14, 2024.", size=14, color=MIST),
    ]
    notes = ("Here's the problem. This crowd photo is real. It went around as a Trump rally in New Jersey. "
             "It's Copacabana beach. The picture isn't fake, the story attached to it is, and people can't tell.")
    return s, notes


def slide_what():
    s = chrome(3, "What it does")
    form = shot((0, 40, 390, 520), "form")
    s += [
        image(96, 140, 546, 672, form),
        rect(96, 140, 546, 672, line=RULE, lw=2),
        text(96, 830, 560, 40, "The input: a claim, a link, an optional image.", size=13, color=MIST),
        text(760, 140, 1064, 260, "Ask about anything you saw online. Get one answer.", size=40, weight="bold", spacing=1.05),
    ]
    rows = [("True", LIME, "Credible sources back it."), ("False", ROSE, "Sources contradict it."),
            ("Misleading", AMBER, "Real thing, wrong context."), ("Unverified", MIST, "Nobody credible has reported it."),
            ("Answered", PAPER, "Your question, answered with sources.")]
    for i, (v, c, d) in enumerate(rows):
        y = 470 + i * 76
        s += [hrule(760, y, 1064),
              rect(760, y + 26, 22, 22, fill=c, radius=3),
              text(806, y, 340, 74, v, size=22, weight="bold", color=c, anchor="middle"),
              text(1150, y, 674, 74, d, size=17, color=MIST, anchor="middle")]
    s += [hrule(760, 470 + 5 * 76, 1064),
          text(760, 880, 1064, 40, "Up to 3 reasons, 2\u20133 sources. Checks the claim, not whether it's AI.", size=14, color=PAPER)]
    notes = ("Paste a claim, an X link or an article link, add an image if you have one, and ask a question if you want. "
             "You get one verdict, up to three reasons and two or three credible sources, with the receipts folded underneath. "
             "It checks the claim, not whether the picture was made by AI.")
    return s, notes


def slide_pipeline():
    s = chrome(4, "How it works")
    s += [text(96, 150, 1728, 120, "Four steps, each one on the record.", size=48, weight="bold")]
    steps = [
        ("Identify", ["Treg Google Lens"], "Gemini, vision assist only"),
        ("Gather", ["Treg News", "Treg Web", "X profile and replies"], None),
        ("Read", ["You.com Search", "You.com Contents", "You.com Answer", "You.com Research"], None),
        ("Decide", ["Verdict and confidence"], None),
    ]
    y = 420
    s.append(rect(96, y - 3, 1728, 6, fill=PAPER))
    for i, (head, tools, foot) in enumerate(steps):
        x = 96 + i * 432
        s += [rect(x, y - 18, 36, 36, fill=LIME if i < 3 else PAPER, radius=18),
              text(x, y + 44, 400, 40, f"0{i + 1}", size=13, color=MIST, weight="bold", tracking=0.1),
              text(x, y + 84, 400, 70, head, size=36, weight="bold")]
        for j, t in enumerate(tools):
            s.append(text(x, y + 176 + j * 46, 400, 44, t, size=18, color=PAPER))
        if foot:
            s.append(text(x, y + 176 + len(tools) * 46 + 10, 400, 40, foot, size=13, color=MIST))
    s += [hrule(96, 880, 1728),
          text(96, 896, 1100, 60, "Behind an XDC x402 paywall, ready at $0.02 a check.", size=17, weight="semibold", color=LIME, anchor="middle"),
          text(1124, 896, 700, 60, "OpenCrawl was our agents' memory at build time.", size=13, color=MIST, align="right", anchor="middle")]
    notes = ("Four steps. Treg's Google Lens figures out what the image is; Gemini only assists. "
             "Treg News, Treg Web and the poster's X profile and replies gather evidence. "
             "You.com Search, Contents, Answer and Research read the credible sources and write the verdict with a confidence. "
             "The endpoint sits behind an XDC x402 paywall at two cents a check. OpenCrawl was our agents' memory while we built it.")
    return s, notes


def slide_examples():
    s = chrome(5, "From the desk")
    s += [text(96, 140, 520, 400, "Three checks we ran today.", size=40, weight="bold", spacing=1.05),
          text(96, 560, 460, 300, "Real posts from the demo, with the verdict the desk gave.\n\nCopacabana photo: CHr0m4tiko0, CC BY-SA 4.0, Wikimedia Commons. GTA VI art: Rockstar Games.", size=17, color=MIST, spacing=1.4)]
    rows = [
        (OUT / "img/gta6.jpg", "\u201cWhen does GTA 6 come out?\u201d", "Text question", "TRUE", LIME, "Release date confirmed by Rockstar's own sources."),
        (OUT / "img/reuters-x-post.png", "Reuters post on X", "x.com/Reuters", "TRUE", LIME, "Matches Reuters reporting. The poster's profile checks out."),
        (OUT / "img/copacabana-crowd.jpg", "\u201cTrump rally in Wildwood, NJ\u201d", "Viral photo", "MISLEADING", AMBER, "It's Copacabana beach in Rio, miscaptioned."),
    ]
    x0, rw, rh = 600, 1224, 270
    for i, (img, claim, kind, v, c, why) in enumerate(rows):
        y = 140 + i * rh
        s.append(hrule(x0, y, rw))
        if img:
            s.append(image(x0, y + 17, 400, 236, cover(img, 400, 236, f"s5-{i}", focus=(0.5, 0.0 if i == 1 else 0.45))))
        else:
            s += [rect(x0, y + 24, 330, 220, fill="#151A21"),
                  text(x0 + 24, y + 24, 282, 220, "GTA 6?", size=40, weight="bold", color=PAPER, anchor="middle")]
        s += [text(x0 + 436, y + 30, 760, 30, kind.upper(), size=11, color=MIST, weight="bold", tracking=0.16),
              text(x0 + 436, y + 66, 560, 90, claim, size=20, weight="semibold", spacing=1.2),
              text(x0 + 436, y + 176, 760, 60, why, size=15, color=MIST, spacing=1.35)]
        b, bw = badge(0, y + 30, v, c, size=15, h=48)
        for it in b:
            it["x"] = x0 + rw - bw
        s += b
    s.append(hrule(x0, 140 + 3 * rh, rw))
    notes = ("Three real checks from the demo. A plain question, when does GTA 6 come out: True, from Rockstar's own sources. "
             "A Reuters post on X: True, and it checks the poster's profile too. "
             "And the crowd photo shared as a Trump rally in New Jersey: Misleading, it's Copacabana beach.")
    return s, notes


def slide_sponsors():
    s = chrome(6, "Sponsor tools")
    s += [text(96, 150, 1728, 120, "You watch every tool do its job.", size=50, weight="bold", spacing=1.04),
          text(96, 290, 1728, 80, "The live check panel: every step names its tool as it runs, with time and results.", size=20, color=MIST)]
    panel = OUT / "img/app-live-check.png"
    s += [image(96, 390, 1728, 600, cover(panel, 1728, 600, "s6-panel", focus=(0, 0))),
          rect(96, 390, 1728, 600, line=RULE, lw=2)]
    notes = ("While a check runs, each step lights up with the sponsor tool's name, its latency, and how many results it found. "
             "Nothing's hidden: you see You.com, Treg and XDC doing the work.")
    return s, notes


def slide_why():
    s = chrome(7, "Who it's for")
    s += [text(96, 150, 860, 260, "$0.02", size=120, weight="bold", color=LIME, spacing=1.0),
          text(96, 440, 800, 120, "per check. Agents and apps pay over XDC x402, no account needed.", size=22, weight="semibold", spacing=1.3),
          text(96, 640, 900, 60, "POST /api/x402/check  \u2192  402  \u2192  pay USDC on XDC  \u2192  receipt", size=14, color=MIST)]
    who = [("People about to repost", "Check it before you share it."),
           ("Journalists on deadline", "Sources and a timeline in one place."),
           ("Moderators making a call", "A verdict with receipts behind it.")]
    for i, (a, b) in enumerate(who):
        y = 150 + i * 220
        s += [hrule(1060, y, 764),
              text(1060, y + 30, 764, 60, a, size=30, weight="bold"),
              text(1060, y + 124, 764, 50, b, size=18, color=MIST)]
    s.append(hrule(1060, 150 + 3 * 220, 764))
    notes = ("It's for people about to hit repost, journalists on deadline, and moderators who need to make a call they can defend. "
             "And for agents and apps it's a pay-per-call API: x402 on XDC, two cents a check. "
             "In this build the paywall speaks the 402 challenge; real settlement is the next step.")
    return s, notes


def slide_close():
    s = [rect(0, 0, W, H, fill=BG_FILL)]
    s += [image(96, 96, 64, 64, LOGO),
          text(180, 96, 600, 64, "Provenance", size=20, weight="semibold", anchor="middle"),
          text(96, 300, 1500, 300, "Check it before\nyou share it.", size=88, weight="bold", spacing=1.0),
          hrule(96, 820, 1728),
          text(96, 846, 900, 50, "github.com/michaelnjoku347/Provenance", size=22, color=LIME, weight="semibold"),
          text(96, 904, 900, 40, "Built by Michael Njoku", size=16, color=PAPER),
          text(1024, 846, 800, 50, "Every answer comes with proof.", size=22, weight="semibold", align="right"),
          text(1024, 904, 800, 40, "You.com  ·  Treg  ·  XDC x402  ·  OpenCrawl", size=14, color=MIST, align="right")]
    notes = "That's Provenance. Every answer comes with proof. The code is on GitHub at michaelnjoku347/Provenance. I'm Michael Njoku, thanks."
    return s, notes


# ---------- writers ----------

def wrap(s: str, f, width: float, tracking_px: float):
    out = []
    for para in s.split("\n"):
        words, cur = para.split(" "), ""
        for wd in words:
            trial = f"{cur} {wd}".strip()
            if f.getlength(trial) + tracking_px * len(trial) <= width or not cur:
                cur = trial
            else:
                out.append(cur)
                cur = wd
        out.append(cur)
    return out


def draw_png(items, path: Path):
    im = Image.new("RGB", (W, H), rgb(INK))
    d = ImageDraw.Draw(im)
    for it in items:
        if it["k"] == "img":
            src = Image.open(it["path"]).convert("RGBA").resize((it["w"], it["h"]), Image.LANCZOS)
            im.paste(src, (it["x"], it["y"]), src)
        elif it["k"] == "rect":
            box = (it["x"], it["y"], it["x"] + it["w"] - 1, it["y"] + it["h"] - 1)
            d.rounded_rectangle(box, radius=it["r"], fill=rgb(it["fill"]) if it["fill"] else None,
                                outline=rgb(it["line"]) if it["line"] else None, width=it["lw"] if it["line"] else 0)
        else:
            px = it["size"] * 2
            f = font(it["weight"], px)
            tr = it["tracking"] * px
            lines = wrap(it["s"], f, it["w"], tr)
            lh = px * it["spacing"]
            total = lh * len(lines)
            y = it["y"] if it["anchor"] == "top" else it["y"] + (it["h"] - total) / 2
            for ln in lines:
                lw = f.getlength(ln) + tr * max(len(ln) - 1, 0)
                x = it["x"] + {"left": 0, "center": (it["w"] - lw) / 2, "right": it["w"] - lw}[it["align"]]
                ty = y + (lh - px) / 2 - px * 0.06
                if tr:
                    for ch in ln:
                        d.text((x, ty), ch, font=f, fill=rgb(it["color"]))
                        x += f.getlength(ch) + tr
                else:
                    d.text((x, ty), ln, font=f, fill=rgb(it["color"]))
                y += lh
    im.save(path)


def add_pptx(prs, items, notes):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    sh = slide.shapes
    for it in items:
        x, y, w, h = (Emu(int(v * EMU)) for v in (it["x"], it["y"], it["w"], it["h"]))
        if it["k"] == "img":
            sh.add_picture(it["path"], x, y, w, h)
        elif it["k"] == "rect":
            shape = sh.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if it["r"] else MSO_SHAPE.RECTANGLE, x, y, w, h)
            if it["r"]:
                shape.adjustments[0] = min(0.5, it["r"] / min(it["w"], it["h"]))
            if it["fill"]:
                shape.fill.solid()
                shape.fill.fore_color.rgb = RGBColor(*rgb(it["fill"]))
            else:
                shape.fill.background()
            if it["line"]:
                shape.line.color.rgb = RGBColor(*rgb(it["line"]))
                shape.line.width = Emu(int(it["lw"] * EMU * 0.75))
            else:
                shape.line.fill.background()
            shape.shadow.inherit = False
        else:
            tb = sh.add_textbox(x, y, w, h)
            tf = tb.text_frame
            tf.word_wrap = True
            tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
            tf.vertical_anchor = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE}[it["anchor"]]
            for i, para in enumerate(it["s"].split("\n")):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}[it["align"]]
                p.line_spacing = it["spacing"]
                r = p.add_run()
                r.text = para
                r.font.name = "Inter"
                r.font.size = Pt(it["size"])
                r.font.bold = it["weight"] in ("bold", "semibold")
                r.font.color.rgb = RGBColor(*rgb(it["color"]))
                if it["tracking"]:
                    r.font._element.set("spc", str(int(it["tracking"] * it["size"] * 100)))
    slide.notes_slide.notes_text_frame.text = notes


def main():
    global LOGO, SHOT
    LOGO = make_logo()
    SHOT = OUT / "app-desk.png"
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    builders = [slide_title, slide_problem, slide_what, slide_pipeline, slide_examples, slide_sponsors, slide_why, slide_close]
    names = ["01-title", "02-problem", "03-what-it-does", "04-how-it-works", "05-live-examples", "06-sponsor-tools", "07-why-it-matters", "08-close"]
    for build, name in zip(builders, names):
        items, notes = build()
        add_pptx(prs, items, notes)
        draw_png(items, PNG_DIR / f"{name}.png")
    prs.save(OUT / "Provenance-pitch.pptx")
    print(OUT / "Provenance-pitch.pptx")


if __name__ == "__main__":
    main()
