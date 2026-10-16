# -*- coding: utf-8 -*-
"""Crop a pixel region from a reference PNG using the img2threejs stdlib image helpers.

Usage: python tools/crop_ref.py <src.png> <x> <y> <w> <h> <out.png>
"""
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\damn\.agents\skills\img2threejs\forge\stage1_intake")
from build_detail_inventory import composite_over_white, load_image, write_png_rgb  # noqa: E402

HERE = Path(__file__).resolve().parent.parent


def crop(src: str, x: int, y: int, w: int, h: int, out: str) -> None:
    path = HERE / src if not Path(src).is_absolute() else Path(src)
    out_path = HERE / out if not Path(out).is_absolute() else Path(out)
    width, height, pixels = load_image(path)
    x = max(0, min(width - 1, x))
    y = max(0, min(height - 1, y))
    w = max(1, min(w, width - x))
    h = max(1, min(h, height - y))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = []
    for yy in range(y, y + h):
        row = yy * width
        for xx in range(x, x + w):
            data.append(composite_over_white(pixels[row + xx]))
    write_png_rgb(out_path, w, h, data)
    print(f"{out_path} {w}x{h}")


if __name__ == "__main__":
    crop(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), sys.argv[6])
