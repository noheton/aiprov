"""Cut the aiprov badge out of the generator image: find the circle by colour saturation, crop square, mask to a
transparent circle, write 1024 px and 512 px files, print sha256 of every file. See assets/PROVENANCE.md.

usage: uv run --no-project --with pillow --with numpy python assets/make_icon.py \
           assets/aiprov-icon-source-gemini.png assets aiprov-icon
"""
import hashlib
import sys
from pathlib import Path

import numpy as np
from PIL import Image

src, out_dir, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
im = Image.open(src).convert("RGB")
a = np.asarray(im).astype(np.int16)
sat = a.max(axis=2) - a.min(axis=2)
mask = sat > 40  # the checkerboard and smudges are grey; the badge is teal/blue
ys, xs = np.nonzero(mask)
cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
r = max(xs.max() - xs.min(), ys.max() - ys.min()) / 2
print(f"circle centre=({cx:.1f},{cy:.1f}) bbox {xs.max()-xs.min()+1}x{ys.max()-ys.min()+1}px of {im.width}x{im.height}")

side = round(2 * r) + 2
box = (round(cx - side / 2), round(cy - side / 2))
crop = Image.open(src).convert("RGBA").crop((box[0], box[1], box[0] + side, box[1] + side))

yy, xx = np.mgrid[:side, :side]
dist = np.sqrt((xx - (side - 1) / 2) ** 2 + (yy - (side - 1) / 2) ** 2)
INSET = 3.0  # px: drop the generator's anti-aliased rim, which is blended with the painted checkerboard
alpha = np.clip((side / 2 - INSET - dist) + 0.5, 0, 1)  # 1 px anti-aliased edge
rgba = np.asarray(crop).copy()
rgba[..., 3] = (alpha * 255).astype(np.uint8)
badge = Image.fromarray(rgba, "RGBA")

out_dir.mkdir(parents=True, exist_ok=True)
for px, suffix in ((1024, "-1024"), (512, "")):
    resample = Image.LANCZOS
    o = badge.resize((px, px), resample)
    p = out_dir / f"{name}{suffix}.png"
    o.save(p, optimize=True)
    print(f"{p.name}: {px}px {'upscaled' if side < px else 'downscaled'} from {side}px "
          f"sha256 {hashlib.sha256(p.read_bytes()).hexdigest()}")
print(f"{src.name}: sha256 {hashlib.sha256(src.read_bytes()).hexdigest()}")
