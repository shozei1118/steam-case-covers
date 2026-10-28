"""Build a six-platform comparison using original synthetic artwork."""
from pathlib import Path
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cover_workflow as covers


PLATFORMS = ("steam", "ps5", "wii", "switch", "xbox_360", "game_boy")
CELL = (150, 225)


def artwork(path, light):
    image = Image.new("RGB", (600, 900))
    pixels = image.load()
    for y in range(900):
        for x in range(600):
            if light:
                pixels[x, y] = (min(255, 222 + y // 35),
                                min(255, 221 + x // 45), 205 + y // 45)
            else:
                pixels[x, y] = (17 + x // 26, 27 + y // 29, 57 + x // 19)
    draw = ImageDraw.Draw(image)
    color = "#667f9b" if light else "#dcecff"
    draw.ellipse((140, 205, 460, 525), outline=color, width=9)
    draw.line((120, 665, 480, 665), fill=color, width=8)
    draw.line((160, 700, 440, 700), fill=color, width=4)
    image.save(path)


def main():
    root = Path(__file__).resolve().parents[1]
    target = root / "docs" / "platinum-comparison.png"
    canvas = Image.new("RGB", (690, 1560), "#0e1826")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    headings = ("Normal · dark", "Platinum · dark", "Normal · light", "Platinum · light")
    for col, heading in enumerate(headings):
        draw.text((20 + col * 170, 18), heading, fill="#edf3fb", font=font)
    with tempfile.TemporaryDirectory() as temp:
        stage = Path(temp)
        dark, light = stage / "dark.png", stage / "light.png"
        artwork(dark, False)
        artwork(light, True)
        for row, platform in enumerate(PLATFORMS):
            y = 52 + row * 250
            draw.text((20, y), platform.replace("_", " ").upper(), fill="#aebfd0", font=font)
            for col, (source, premium) in enumerate(((dark, False), (dark, True),
                                                       (light, False), (light, True))):
                result = covers.export_one(source, platform, "Sample", stage / str(row) / str(col),
                                           platinum=premium)
                with Image.open(result) as cover:
                    cover = cover.convert("RGB").resize(CELL, Image.Resampling.LANCZOS)
                    canvas.paste(cover, (20 + col * 170, y + 16))
    canvas.save(target, optimize=True)
    import platinum_frame
    details = Image.new("RGB", (840, 660), "#172536")
    pen = ImageDraw.Draw(details)
    with Image.open(root / "assets" / "frames" / "steam.png") as source:
        normal = source.convert("RGBA")
    for col, frame in enumerate((normal, platinum_frame.apply(normal))):
        pen.text((20 + col * 420, 12), "Normal" if col == 0 else "Platinum V2", fill="white")
        for row, region in enumerate(((0, 0, 100, 100), (0, 350, 35, 450), (230, 830, 370, 900))):
            crop = frame.crop(region)
            factor = min(3, 380 // crop.width, 200 // crop.height)
            crop = crop.resize((crop.width * factor, crop.height * factor), Image.Resampling.LANCZOS)
            details.paste(crop, (20 + col * 420, 40 + row * 200), crop)
    details.save(root / "docs" / "platinum-details.png")
    print(target)


if __name__ == "__main__":
    main()
