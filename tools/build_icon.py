#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the original Case Covers app mark to PNG, ICO and ICNS with Pillow.

The matching vector master is tools/src/icon.svg. No platform logos are used.
"""
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"


def render(size):
    # Fourfold drawing resolution keeps the 16px Windows taskbar icon clear.
    scale = size * 4 / 512
    image = Image.new("RGBA", (size * 4, size * 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def box(coords, fill, radius=0, outline=None, width=1):
        rect = tuple(round(v * scale) for v in coords)
        draw.rounded_rectangle(rect, radius=round(radius * scale), fill=fill,
                               outline=outline, width=max(1, round(width * scale)))

    def polygon(points, fill):
        draw.polygon([(round(x * scale), round(y * scale)) for x, y in points], fill=fill)

    def ellipse(coords, fill):
        draw.ellipse(tuple(round(v * scale) for v in coords), fill=fill)

    # A dark tile carries three overlapping portrait cases: several platforms,
    # one finished cover. The side colors are generic and contain no trademarks.
    box((16, 16, 496, 496), "#132336", 98, "#354d64", 7)
    box((68, 107, 278, 430), "#7a6ce2", 22)
    box((82, 125, 264, 414), "#302c61", 10)
    box((82, 125, 264, 164), "#a69bff", 7)
    box((237, 92, 445, 415), "#ffab66", 22)
    box((250, 109, 430, 399), "#543342", 10)
    box((250, 109, 430, 148), "#ffd09b", 7)
    box((131, 56, 388, 456), "#081622", 25)
    box((139, 64, 380, 448), "#56c1eb", 21)
    box((151, 76, 368, 436), "#17283c", 13)
    box((151, 76, 368, 134), "#75d7f3", 12)
    box((151, 122, 368, 134), "#75d7f3")
    box((166, 153, 353, 390), "#244666", 6)
    ellipse((269, 180, 331, 242), "#ffca75")
    polygon(((166, 349), (225, 267), (267, 320), (306, 270), (353, 339), (353, 390), (166, 390)), "#756ed3")
    polygon(((166, 379), (220, 322), (268, 370), (309, 325), (353, 370), (353, 390), (166, 390)), "#373e83")
    box((166, 405, 353, 421), "#75d7f3", 7)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main():
    OUT.mkdir(exist_ok=True)
    render(256).save(OUT / "icon.png", optimize=True)
    render(256).save(OUT / "icon.ico", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    render(1024).save(OUT / "icon.icns")
    print("wrote", OUT / "icon.png", OUT / "icon.ico", OUT / "icon.icns")


if __name__ == "__main__":
    main()
