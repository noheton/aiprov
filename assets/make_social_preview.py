"""Build the 1280 x 640 social preview of the repository from the badge source picture: the badge cut to a transparent
circle as in make_icon.py (resized once, from the source), the name and the expanded acronym in Inter.
See assets/PROVENANCE.md.

usage: uv run --no-project --with pillow --with numpy python assets/make_social_preview.py \
           assets/aiprov-icon-source-gemini.png assets/aiprov-social-preview.png [light|dark]
"""

import hashlib
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONTS = Path("/usr/share/fonts/opentype/inter")
W, H, BADGE, LEFT = 1280, 640, 440, 96
THEMES = {
    "light": {"bg": ((246, 250, 253), (226, 238, 247)), "title": (11, 37, 69), "text": (40, 72, 102), "small": (86, 112, 138)},
    "dark": {"bg": ((7, 24, 43), (12, 44, 74)), "title": (255, 255, 255), "text": (196, 222, 240), "small": (140, 176, 202)},
}


def badge(src: Path, size: int) -> Image.Image:
    a = np.asarray(Image.open(src).convert("RGB")).astype(np.int16)
    ys, xs = np.nonzero((a.max(axis=2) - a.min(axis=2)) > 40)
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    r = max(xs.max() - xs.min(), ys.max() - ys.min()) / 2
    side = round(2 * r) + 2
    x0, y0 = round(cx - side / 2), round(cy - side / 2)
    crop = Image.open(src).convert("RGBA").crop((x0, y0, x0 + side, y0 + side))
    yy, xx = np.mgrid[:side, :side]
    dist = np.sqrt((xx - (side - 1) / 2) ** 2 + (yy - (side - 1) / 2) ** 2)
    rgba = np.asarray(crop).copy()
    rgba[..., 3] = (np.clip(side / 2 - 3.0 - dist + 0.5, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA").resize((size, size), Image.LANCZOS)


def fit(text: str, path: Path, size: int, width: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(path), size)
    while font.getlength(text) > width and size > 10:
        size -= 1
        font = ImageFont.truetype(str(path), size)
    return font


def main() -> None:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    t = THEMES[sys.argv[3] if len(sys.argv) > 3 else "light"]
    (r0, g0, b0), (r1, g1, b1) = t["bg"]
    ramp = np.linspace(0, 1, W)[None, :, None] * 0.6 + np.linspace(0, 1, H)[:, None, None] * 0.4
    bg = np.array([r0, g0, b0]) + (np.array([r1, g1, b1]) - np.array([r0, g0, b0])) * ramp
    card = Image.fromarray(bg.astype(np.uint8), "RGB").convert("RGBA")
    card.alpha_composite(badge(src, BADGE), (LEFT, (H - BADGE) // 2))

    x = LEFT + BADGE + 64
    room = W - x - 72
    d = ImageDraw.Draw(card)
    lines = [
        ("aiprov", FONTS / "InterDisplay-Bold.otf", 156, t["title"], 0),
        ("AI provenance", FONTS / "Inter-SemiBold.otf", 50, t["text"], 26),
        ("recorded, open, verifiable", FONTS / "Inter-Regular.otf", 42, t["text"], 10),
        ("W3C PROV-O  \u00b7  github.com/noheton/aiprov", FONTS / "Inter-Medium.otf", 26, t["small"], 40),
    ]
    fonts = [fit(text, path, size, room) for text, path, size, _, _ in lines]
    heights = [f.getbbox(text)[3] - f.getbbox(text)[1] for (text, *_), f in zip(lines, fonts, strict=True)]
    y = (H - (sum(heights) + sum(gap for *_, gap in lines))) // 2
    for (text, _, _, colour, gap), font, h in zip(lines, fonts, heights, strict=True):
        y += gap
        d.text((x, y - font.getbbox(text)[1]), text, font=font, fill=colour)
        y += h

    card.convert("RGB").save(out, optimize=True)
    print(f"{out.name}: {W}x{H} sha256 {hashlib.sha256(out.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
