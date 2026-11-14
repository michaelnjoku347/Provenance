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
BG = None


def chrome(n: int, kicker: str | None = None):
    items = [image(0, 0, W, H, BG)]
    if n > 1:
        items += [
            image(96, 64, 44, 44, LOGO),
            text(152, 64, 400, 44, "Provenance", size=15, weight="semibold", anchor="middle"),
            text(1424, 64, 400, 44, f"{n:02d} / 08", size=12, color=MIST, weight="medium", align="right", anchor="middle", tracking=0.1),
        ]
        if kicker:
            items.append(text(96, 160, 1200, 32, kicker.upper(), size=13, color=LIME, weight="bold", tracking=0.18))
    items.append(text(96, 1000, 1400, 32, "Ground Truth hackathon  ·  You.com  ·  NYC  ·  Nov 14, 2026", size=11, color=MIST, tracking=0.05, anchor="middle"))
    return items


# ---------- slides ----------

def slide_title():
    s = chrome(1)
    s += [
        image(96, 300, 150, 150, LOGO),
        text(96, 480, 1500, 170, "Provenance", size=88, weight="bold", spacing=1.0),
        text(100, 660, 1500, 80, "Every answer comes with proof.", size=40, color=LIME, weight="semibold"),
        text(100, 760, 1200, 60, "A claim checker for viral images, X posts, and article links.", size=20, color=MIST),
    ]
    stamp_y = 300
    for i, (label, color) in enumerate([("TRUE", LIME), ("MISLEADING", AMBER), ("FALSE", ROSE), ("UNVERIFIED", MIST)]):
        p, w = pill(1824 - 300, stamp_y + i * 64, label, color, size=14, h=48)
        for item in p:
            item["x"] += 300 - w
        s += p
    notes = ("Hi, I'm Michael. This is Provenance: drop in a viral image, an X post, or an article link, "
             "and you get one clear answer about the claim, with the sources that prove it.")
    return s, notes


def slide_problem():
    s = chrome(2, "The problem")
    s += [
        text(96, 220, 960, 300, "Viral images spread claims faster than fact-checks.", size=42, weight="bold", spacing=1.08),
        text(96, 540, 900, 120, "People can't tell what's true behind an image. The caption is usually the lie, not the pixels.", size=20, color=MIST, spacing=1.35),
    ]
    rows = [("Shared in seconds", "A post goes viral long before anyone checks it."),
            ("Real photo, false story", "Old or unrelated photos get new captions."),
            ("No receipts", "Readers can't see who said what, or where.")]
    for i, (a, b) in enumerate(rows):
        y = 716 + i * 88
        s += [rect(96, y + 8, 8, 64, fill=LIME, radius=4),
              text(128, y, 860, 40, a, size=20, weight="semibold"),
              text(128, y + 40, 860, 40, b, size=16, color=MIST)]
    img = cover(SAMPLES / "copacabana.jpg", 720, 480, "s2-copa")
    s += [
        rect(1104, 220, 720, 680, fill=PANEL, line=LINE, radius=24),
        image(1104, 220, 720, 480, img),
        text(1136, 736, 660, 90, "\u201cThis photo shows Trump's May 11 rally in Wildwood, NJ.\u201d", size=17, color=PAPER, weight="medium", spacing=1.3),
        text(1136, 840, 660, 36, "Viral caption on a crowd photo", size=12, color=MIST),
    ]
    p, _ = pill(1128, 644, "SHARED AS FACT", AMBER, size=12, h=38, filled=True)
    s += p
    notes = ("Viral posts move faster than fact-checks. Most of the time the photo is real but the story attached "
             "to it is wrong, and readers have no way to see what's actually behind it.")
    return s, notes


def slide_what():
    s = chrome(3, "What it does")
    s += [text(96, 220, 1700, 90, "Drop it in. Get one clear answer.", size=48, weight="bold")]
    ins = [("Image", "upload or paste"), ("X post link", "x.com / twitter.com"), ("Article link", "any news URL")]
    for i, (a, b) in enumerate(ins):
        y = 360 + i * 120
        s += [rect(96, y, 520, 100, fill=PANEL, line=LINE, radius=18),
              rect(124, y + 30, 40, 40, fill=mix(INK, LIME, 0.18), line=LIME, radius=10),
              text(188, y + 18, 400, 36, a, size=20, weight="semibold"),
              text(188, y + 54, 400, 30, b, size=14, color=MIST)]
    s += [rect(96, 724, 520, 80, fill=None, line=LINE, radius=18),
          text(124, 724, 480, 80, "+ optional question", size=17, color=MIST, anchor="middle")]
    s += [text(636, 520, 120, 80, "\u2192", size=48, color=LIME, align="center", anchor="middle")]

    x0, y0, cw = 776, 360, 1048
    s += [rect(x0, y0, cw, 444, fill=PANEL, line=LINE, radius=24)]
    px = x0 + 40
    for label, color in [("True", LIME), ("False", ROSE), ("Misleading", AMBER), ("Unverified", MIST), ("Answered", LIME)]:
        p, w = pill(px, y0 + 36, label.upper(), color, size=12, h=40, filled=(label == "True"))
        s += p
        px += w + 12
    feats = [("1 verdict", "about the claim itself"),
             ("Up to 3 reasons", "short and plain"),
             ("2\u20133 sources", "credible, linked outlets"),
             ("Receipts below", "folded, open on demand")]
    for i, (a, b) in enumerate(feats):
        cx = x0 + 40 + (i % 2) * 490
        cy = y0 + 124 + (i // 2) * 150
        s += [rect(cx, cy, 460, 126, fill=PANEL2, line=LINE, radius=16),
              text(cx + 24, cy + 24, 420, 40, a, size=21, weight="semibold", color=LIME if i == 0 else PAPER),
              text(cx + 24, cy + 70, 420, 40, b, size=15, color=MIST)]
    s += [rect(96, 852, 1728, 84, fill=mix(INK, CYAN, 0.08), line=mix(INK, CYAN, 0.45), radius=18),
          text(128, 852, 1680, 84, "It checks the claim \u2014 not whether the image is AI-generated.", size=20, color=CYAN, weight="semibold", anchor="middle")]
    notes = ("Three ways in: an image, an X post link, or an article link, plus an optional question. "
             "Out comes one verdict, up to three reasons, two or three credible sources, and the receipts folded below. "
             "Important: we check the claim, not whether the picture is AI-generated.")
    return s, notes


def slide_pipeline():
    s = chrome(4, "How it works")
    s += [text(96, 220, 1700, 80, "Identify. Gather. Read. Decide.", size=48, weight="bold")]
    cols = [
        ("IDENTIFY", LIME, ["Treg Google Lens", "names the image"], "Gemini \u00b7 vision assist"),
        ("GATHER", LIME, ["Treg News", "Treg Web", "X profile + replies"], None),
        ("READ", CYAN, ["You.com Search", "You.com Contents", "You.com Answer", "You.com Research"], None),
        ("DECIDE", AMBER, ["Verdict", "+ confidence", "+ sources"], None),
    ]
    x, y, cw, gap, ch = 96, 340, 384, 64, 470
    for i, (head, color, lines, extra) in enumerate(cols):
        cx = x + i * (cw + gap)
        s += [rect(cx, y, cw, ch, fill=PANEL, line=LINE, radius=22),
              rect(cx, y, cw, 6, fill=color, radius=0),
              text(cx + 28, y + 30, cw - 56, 30, f"{i + 1:02d}  {head}", size=13, color=color, weight="bold", tracking=0.14)]
        for j, ln in enumerate(lines):
            small = head == "IDENTIFY" and j == 1
            s.append(text(cx + 28, y + 96 + j * 58, cw - 56, 50, ln, size=15 if small else 18,
                          color=MIST if small else PAPER, weight="regular" if small else "semibold"))
        if extra:
            s += [rect(cx + 28, y + ch - 76, cw - 56, 48, fill=None, line=LINE, radius=24),
                  text(cx + 28, y + ch - 76, cw - 56, 48, extra, size=13, color=MIST, align="center", anchor="middle")]
        if i < len(cols) - 1:
            s.append(text(cx + cw, y + ch // 2 - 40, gap, 80, "\u2192", size=34, color=MIST, align="center", anchor="middle"))
    s += [rect(96, 846, 1728, 92, fill=mix(INK, LIME, 0.08), line=mix(INK, LIME, 0.5), radius=18),
          text(128, 846, 900, 92, "XDC x402 paywall ready", size=22, weight="bold", color=LIME, anchor="middle"),
          text(780, 846, 1016, 92, "Agents pay $0.02 per check  \u00b7  OpenCrawl used at build time", size=17, color=PAPER, anchor="middle", align="right")]
    notes = ("Treg's Google Lens identifies what's in the image; Gemini is only a small vision assist. "
             "Treg News, Treg Web and the X poster's profile and replies gather evidence. "
             "You.com Search, Contents, Answer and Research read the credible sources and synthesize a verdict with confidence. "
             "The whole check sits behind an XDC x402 paywall at two cents per call. OpenCrawl was our agents' memory while building.")
    return s, notes


def slide_examples():
    s = chrome(5, "Live examples")
    s += [text(96, 220, 1700, 80, "Real posts. Real answers.", size=48, weight="bold")]
    cards = [
        (None, "GTA 6 release", "True", LIME, "Confirmed by Rockstar's own sources."),
        ("huang.jpg", "Huang couple photo", "Unverified", MIST, "Names the couple. No divorce reported \u2014 only speculation."),
        ("reuters-post.jpg", "Reuters on X", "True", LIME, "Matches Reuters reporting, with the poster's profile."),
        ("copacabana.jpg", "\u201cNJ rally\u201d crowd", "Misleading", AMBER, "It's Copacabana beach in Brazil, miscaptioned."),
    ]
    cw, gap, y, ih = 408, 32, 340, 300
    for i, (img, title, verdict, color, line) in enumerate(cards):
        cx = 96 + i * (cw + gap)
        s.append(rect(cx, y, cw, 600, fill=PANEL, line=LINE, radius=22))
        if img:
            s.append(image(cx, y, cw, ih, cover(SAMPLES / img, cw, ih, f"s5-{i}", focus=(0.5, 0.3))))
        else:
            s += [rect(cx, y, cw, ih, fill=PANEL2, radius=0),
                  text(cx + 32, y + 40, cw - 64, 30, "TEXT CLAIM", size=12, color=MIST, weight="bold", tracking=0.16),
                  text(cx + 32, y + 90, cw - 64, 180, "\u201cWhen does GTA 6 come out?\u201d", size=28, weight="semibold", spacing=1.15)]
        p, _ = pill(cx + 28, y + ih + 28, verdict.upper(), color, size=13, h=42, filled=True)
        s += p
        s += [text(cx + 28, y + ih + 96, cw - 56, 40, title, size=17, weight="semibold"),
              text(cx + 28, y + ih + 144, cw - 56, 120, line, size=15, color=MIST, spacing=1.35)]
    notes = ("Four real checks from the demo. GTA 6 comes back True with Rockstar's sources. "
             "The Jensen Huang photo: it names the couple, finds no reported divorce, only speculation, so Unverified. "
             "A Reuters post on X is True and shows the poster's profile. "
             "And the famous crowd photo captioned as a New Jersey Trump rally is Copacabana beach: Misleading.")
    return s, notes


def slide_sponsors():
    s = chrome(6, "Sponsor tools, on screen")
    s += [text(96, 220, 820, 200, "Every step lights up as it runs.", size=48, weight="bold", spacing=1.08),
          text(96, 460, 760, 200, "Each step names the tool, its latency, and how many results it found \u2014 so judges watch You.com, Treg, and XDC work live.", size=21, color=MIST, spacing=1.4)]
    rows = [("Treg Lens", "matches", LIME), ("Treg News", "results", LIME), ("Treg Web", "results", LIME),
            ("Treg X replies", "replies", LIME), ("You.com Search", "results", CYAN), ("You.com Contents", "pages", CYAN),
            ("You.com Answer", "cited synthesis", CYAN), ("XDC x402", "test mode \u00b7 $0.02", AMBER)]
    x0, y0, pw = 980, 220, 844
    s.append(rect(x0, y0, pw, 760, fill=PANEL, line=LINE, radius=24))
    s.append(text(x0 + 36, y0 + 28, 600, 30, "CHECKING THE CLAIM", size=12, color=MIST, weight="bold", tracking=0.16))
    for i, (name, stat, color) in enumerate(rows):
        ry = y0 + 80 + i * 82
        s += [rect(x0 + 24, ry, pw - 48, 68, fill=PANEL2, line=LINE, radius=14),
              rect(x0 + 48, ry + 26, 16, 16, fill=color, radius=8),
              text(x0 + 84, ry, 360, 68, name, size=18, weight="semibold", anchor="middle")]
        p, w = pill(0, ry + 15, (stat if name == "XDC x402" else "latency \u00b7 " + stat).upper(), color, size=11, h=38)
        for it in p:
            it["x"] = x0 + pw - 48 - w
        s += p
    notes = ("While a check runs, every step lights up with the sponsor tool's name, how long it took, and how many results it returned. "
             "Nothing is hidden: you see Treg, You.com and XDC doing the work, live.")
    return s, notes


def slide_why():
    s = chrome(7, "Why it matters")
    s += [text(96, 220, 1700, 80, "Proof for anyone about to hit share.", size=48, weight="bold")]
    who = [("Everyday social users", "Check a viral image before reposting it."),
           ("Journalists", "Get credible sources and a timeline in one place."),
           ("Moderators", "A clear verdict with receipts to back a decision.")]
    for i, (a, b) in enumerate(who):
        cx = 96 + i * 592
        s += [rect(cx, 360, 544, 280, fill=PANEL, line=LINE, radius=22),
              text(cx + 36, 396, 200, 40, f"0{i + 1}", size=16, color=LIME, weight="bold"),
              text(cx + 36, 450, 480, 60, a, size=22, weight="semibold"),
              text(cx + 36, 520, 470, 100, b, size=17, color=MIST, spacing=1.35)]
    s += [rect(96, 688, 1728, 252, fill=mix(INK, LIME, 0.07), line=mix(INK, LIME, 0.5), radius=24),
          text(140, 724, 900, 30, "FOR AGENTS AND APPS", size=13, color=LIME, weight="bold", tracking=0.16),
          text(140, 770, 1100, 70, "Pay per check over XDC x402", size=34, weight="bold"),
          text(140, 846, 1100, 50, "POST /api/x402/check  \u2192  402 challenge  \u2192  pay 0.02 USDC on XDC  \u2192  receipt", size=15, color=PAPER),
          text(1380, 724, 400, 180, "$0.02", size=80, weight="bold", color=LIME, align="right", anchor="middle")]
    notes = ("It's for everyday users before they repost, journalists who need sources fast, and moderators who need a defensible call. "
             "And for agents and apps, the same check is a pay-per-call API: x402 on XDC at two cents. "
             "In this build the paywall speaks the 402 challenge; settlement is the production step.")
    return s, notes


def slide_close():
    s = chrome(8)
    s += [
        image(885, 220, 150, 150, LOGO),
        text(160, 410, 1600, 120, "Every answer comes with proof.", size=46, weight="bold", align="center"),
        rect(400, 590, 1120, 88, fill=PANEL, line=LIME, radius=44),
        text(400, 590, 1120, 88, "github.com/michaelnjoku347/Provenance", size=22, color=LIME, weight="semibold", align="center", anchor="middle"),
        text(160, 730, 1600, 50, "Built by Michael Njoku", size=24, align="center"),
        text(160, 790, 1600, 40, "You.com  \u00b7  Treg  \u00b7  XDC x402  \u00b7  OpenCrawl", size=16, color=MIST, align="center"),
    ]
    notes = "Provenance: every answer comes with proof. The code is on GitHub at michaelnjoku347/Provenance. I'm Michael Njoku. Thank you."
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
    global LOGO, BG
    LOGO = make_logo()
    BG = make_background()
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
