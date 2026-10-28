"""Render platinum case material with the original frame SVG geometry."""
import io
import re
import sys
from pathlib import Path

from PIL import Image
import resvg_py

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_frame import ORIGINAL_COLORS, platform_svg, FONT


def main():
    palette = dict(ORIGINAL_COLORS)
    palette.update(case_top="#abb9c8", case_mid="#8198b0", case_bottom="#607d9b",
                   edge="#f4faff", lip_base="#829db3", lip_high="#e4f4ff",
                   lip_shadow="#435c74")
    markup = platform_svg(palette)
    metal = '<linearGradient id="case" x1="0" y1="0" x2="0" y2="1">' + ''.join(
        '<stop offset="%s" stop-color="%s"/>' % pair for pair in (
            ('0','#607d9b'),('.006','#e3f0ff'),('.015','#abb9c8'),
            ('.18','#8ba2b9'),('.42','#bac9d7'),('.66','#718ca6'),
            ('.87','#abb9c8'),('.972','#607d9b'),('.98','#d6e7f6'),('1','#526d87'))) + '</linearGradient>'
    markup = re.sub(r'<linearGradient id="case".*?</linearGradient>', metal, markup)
    cross = '<linearGradient id="cross" x1="0" y1="0" x2="1" y2="0">' + ''.join(
        '<stop offset="%s" stop-color="%s" stop-opacity="%s"/>' % stop for stop in (
            ('0','#344e69','.6'),('.004','#e3f0ff','.5'),('.012','#abb9c8','.25'),
            ('.023','#344e69','.45'),('.024','#abb9c8','0'),
            ('.976','#abb9c8','0'),('.977','#344e69','.45'),
            ('.988','#abb9c8','.25'),('.996','#e3f0ff','.5'),('1','#344e69','.6'))) + '</linearGradient>'
    markup = markup.replace('</defs>', cross + '</defs>')
    # A material reflection on the existing body, before the original bevel,
    # lip and header layers. This introduces no new outline or geometry.
    markup = markup.replace('<rect x="1.5"',
        '<rect width="600" height="900" rx="20" fill="url(#cross)"/><rect x="1.5"', 1)
    data = resvg_py.svg_to_bytes(svg_string=markup,
                                width=600, height=900, font_files=[FONT])
    output = Path(__file__).resolve().parents[1] / "assets" / "platinum-rim.png"
    Image.open(io.BytesIO(data)).save(output)
    print(output)
    trophy = output.with_name("platinum-trophy.png")
    source = output.parents[1] / "tools" / "src" / "platinum-trophy.svg"
    Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=source.read_text(),
               width=600, height=900))).save(trophy)
    print(trophy)


if __name__ == "__main__":
    main()
