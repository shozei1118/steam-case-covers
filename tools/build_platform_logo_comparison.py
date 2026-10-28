#!/usr/bin/env python3
"""Render the eight reviewed platform frames with dark and light sample artwork."""
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cover_workflow as cw
from platform_catalog import ROOT, get_platform


PLATFORMS = ("wii", "ps5", "game_boy", "game_boy_color",
             "n64", "gamecube", "dreamcast", "ps1")
OUTPUT = Path(ROOT) / "docs" / "platform-logo-comparison.png"


def sample_art(path, dark):
    image = Image.new("RGB", (600, 900))
    pixels = image.load()
    for y in range(900):
        ratio = y / 899
        if dark:
            color = (int(9 + 23 * ratio), int(18 + 32 * ratio), int(35 + 40 * ratio))
        else:
            color = (int(249 - 27 * ratio), int(244 - 30 * ratio), int(225 - 24 * ratio))
        for x in range(600):
            pixels[x, y] = color
    draw = ImageDraw.Draw(image)
    accent = "#65bfff" if dark else "#7953a1"
    ink = "#e9f2fb" if dark else "#1d2d41"
    draw.ellipse((80, 115, 520, 555), outline=accent, width=22)
    draw.rectangle((125, 490, 475, 505), fill=accent)
    draw.text((125, 550), "NIGHT" if dark else "DAYLIGHT", fill=ink,
              font=ImageFont.truetype("arial.ttf", 55))
    draw.text((125, 620), "SAMPLE ARTWORK", fill=ink,
              font=ImageFont.truetype("arial.ttf", 26))
    image.save(path)


def main():
    stage = Path(ROOT) / "build" / "platform-logo-comparison"
    stage.mkdir(parents=True, exist_ok=True)
    for dark, name in ((True, "dark"), (False, "light")):
        sample_art(stage / (name + ".png"), dark)
    sheet = Image.new("RGB", (920, 1380), "#08111d")
    draw = ImageDraw.Draw(sheet)
    title_font = ImageFont.truetype("arial.ttf", 23)
    label_font = ImageFont.truetype("arial.ttf", 15)
    draw.text((25, 18), "Case Covers - platform logo comparison", fill="#e9f2fb", font=title_font)
    draw.text((25, 52), "Generated frames with dark and light sample artwork; real export compositing",
              fill="#a9bfd6", font=label_font)
    for index, platform_id in enumerate(PLATFORMS):
        platform = get_platform(platform_id)
        left = 20 + (index % 2) * 450
        top = 90 + (index // 2) * 320
        draw.rounded_rectangle((left, top, left + 430, top + 308), radius=12,
                               fill="#112338", outline="#2b4361", width=2)
        draw.text((left + 17, top + 10), platform["name"], fill="#e9f2fb", font=title_font)
        draw.text((left + 17, top + 40),
                  "%s logo  |  frame %s" % (platform["logo_default"], platform["frame_color"]),
                  fill="#a9bfd6", font=label_font)
        for column, name in enumerate(("dark", "light")):
            exported = cw.export_one(stage / (name + ".png"), platform_id,
                                     "Sample artwork", stage / "exports")
            with Image.open(exported) as cover:
                cover = cover.convert("RGBA")
                cover.thumbnail((146, 219), Image.Resampling.LANCZOS)
                x = left + 46 + column * 193
                y = top + 64
                sheet.paste(cover, (x, y), cover)
            draw.text((left + 88 + column * 193, top + 286), name,
                      fill="#a9bfd6", font=label_font)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()
