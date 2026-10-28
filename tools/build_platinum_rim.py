"""Render platinum case material with the original frame SVG geometry."""
import io
import sys
from pathlib import Path

from PIL import Image
import resvg_py

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_frame import ORIGINAL_COLORS, platform_svg, FONT


def main():
    palette = dict(ORIGINAL_COLORS)
    palette.update(case_top="#e0edf5", case_mid="#a3bacb", case_bottom="#647f98",
                   edge="#f4faff", lip_base="#829db3", lip_high="#e4f4ff",
                   lip_shadow="#435c74")
    data = resvg_py.svg_to_bytes(svg_string=platform_svg(palette),
                                width=600, height=900, font_files=[FONT])
    output = Path(__file__).resolve().parents[1] / "assets" / "platinum-rim.png"
    Image.open(io.BytesIO(data)).save(output)
    print(output)


if __name__ == "__main__":
    main()
