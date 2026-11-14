"""Build docs/pitch/devpost-cover.png (2400x1600) from real images in docs/pitch/img/."""

from PIL import Image, ImageDraw

import build_deck as d

W, H = 2400, 1600
INK, BG, RULE = d.rgb(d.INK), d.rgb("#0B0E12"), d.rgb("#2A323D")
PAPER, MIST, LIME = d.rgb(d.PAPER), d.rgb(d.MIST), d.rgb(d.LIME)


def main():
    im = Image.new("RGB", (W, H), BG)
    g = ImageDraw.Draw(im)
    f = d.font

    logo = Image.open(d.make_logo(256)).resize((96, 96), Image.LANCZOS)
    im.paste(logo, (140, 120), logo)
    g.text((262, 134), "Provenance", font=f("semibold", 56), fill=PAPER)
    g.rectangle((140, 260, 2260, 262), fill=RULE)

    y = 380
    for line in ["Check the claim", "behind any image."]:
        g.text((140, y), line, font=f("bold", 112), fill=PAPER)
        y += 140
    g.text((140, y + 40), "Drop in an image, an X post or a link.", font=f("regular", 40), fill=MIST)
    g.text((140, y + 100), "Get one answer, with the sources.", font=f("regular", 40), fill=MIST)

    g.rectangle((140, 1380, 1100, 1381), fill=RULE)
    g.text((140, 1410), "BUILT WITH", font=f("bold", 22), fill=MIST)
    g.text((140, 1450), "You.com  \u00b7  Treg  \u00b7  XDC x402", font=f("semibold", 34), fill=PAPER)

    x0, iw, ih = 1240, 1020, 536
    art = Image.open(d.OUT / "img" / "gta6.jpg").convert("RGB").resize((iw, ih), Image.LANCZOS)
    im.paste(art, (x0, 330))
    g.rectangle((x0, 330, x0 + iw - 1, 330 + ih - 1), outline=RULE, width=2)
    g.text((x0, 890), "GTA VI key art: Rockstar Games", font=f("regular", 22), fill=MIST)

    ry = 960
    g.rectangle((x0, ry, x0 + iw, ry + 1), fill=RULE)
    g.text((x0, ry + 36), "CLAIM", font=f("bold", 22), fill=MIST)
    g.text((x0, ry + 72), "\u201cWhen does GTA 6 come out?\u201d", font=f("semibold", 46), fill=PAPER)
    bw = 210
    g.rounded_rectangle((x0 + iw - bw, ry + 30, x0 + iw, ry + 110), radius=10, fill=LIME)
    tw = f("bold", 44).getlength("TRUE")
    g.text((x0 + iw - bw + (bw - tw) / 2, ry + 44), "TRUE", font=f("bold", 44), fill=INK)

    g.text((x0, ry + 180), "SOURCES", font=f("bold", 22), fill=MIST)
    cx = x0
    for chip in ["Rockstar Games", "rockstargames.com"]:
        cw = int(f("semibold", 30).getlength(chip)) + 56
        g.rounded_rectangle((cx, ry + 220, cx + cw, ry + 290), radius=35, outline=PAPER, width=2)
        g.text((cx + 28, ry + 237), chip, font=f("semibold", 30), fill=PAPER)
        cx += cw + 20
    g.rectangle((x0, 1380, x0 + iw, 1381), fill=RULE)
    g.text((x0, 1410), "github.com/michaelnjoku347/Provenance", font=f("semibold", 30), fill=LIME)

    im.save(d.OUT / "devpost-cover.png", optimize=True)


if __name__ == "__main__":
    main()
