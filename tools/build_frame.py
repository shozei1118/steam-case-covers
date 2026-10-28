#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Diego Bergonsi. Part of steam-case-covers: https://github.com/diegobergonsi/steam-case-covers
"""Maintainers only: render 600x900 transparent frame PNGs from SVG.

The build uses resvg_py and Pillow. Runtime users need neither renderer because
the PNGs are committed.
"""
import io, os, re
from functools import lru_cache

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
OUT = os.path.join(HERE, "..", "assets", "frame.png")

W, H = 600, 900
L, R, T, B = 14, 586, 14, 872   # art+banner box
BAR = 78
AT = T + BAR + 4                # art window top  (window = L..R x AT..B)

svg_logo = open(os.path.join(SRC, "steam_logo.svg"), encoding="utf-8").read()
DISC, MARK = re.findall(r'<path d="([^"]+)"', svg_logo)[:2]
FONT = os.path.join(SRC, "fonts", "NunitoSans.ttf")
cy = T + BAR / 2
STEAM_MARKUP = (f'<g transform="translate(196,{cy-24}) scale({48/32})"><path d="{DISC}" fill="#fff"/>'
                f'<path d="{MARK}" fill="#0a2a66"/></g>\n'
                f' <text x="252" y="{cy+13}" font-family="Nunito Sans, sans-serif" font-weight="bold" '
                'font-size="40" letter-spacing="4" fill="#fff" stroke="#fff" stroke-width="1.8" '
                'stroke-linejoin="round">STEAM</text>')

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs>
 <linearGradient id="case" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2f5fe8"/><stop offset=".5" stop-color="#1636c8"/><stop offset="1" stop-color="#0a1e90"/></linearGradient>
 <linearGradient id="bar" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0d3a82"/><stop offset="1" stop-color="#051c4d"/></linearGradient>
 <linearGradient id="gloss" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".13"/><stop offset=".3" stop-color="#fff" stop-opacity="0"/></linearGradient>
 <linearGradient id="fade" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
 <mask id="dm"><rect x="{L}" y="{T}" width="190" height="{BAR}" fill="url(#fade)"/></mask>
 <mask id="hole"><rect width="{W}" height="{H}" fill="#fff"/><rect x="{L}" y="{AT}" width="{R-L}" height="{B-AT}" fill="#000"/></mask>
 <pattern id="dots" width="12" height="12" patternUnits="userSpaceOnUse"><circle cx="6" cy="6" r="2.4" fill="#5d8fd6" opacity=".55"/></pattern>
 <clipPath id="ban"><rect x="{L}" y="{T}" width="{R-L}" height="{BAR}" rx="4"/></clipPath>
</defs>
<g mask="url(#hole)">
 <rect x="0" y="0" width="{W}" height="{H}" rx="20" fill="url(#case)"/>
 <rect x="1.5" y="1.5" width="{W-3}" height="{H-3}" rx="19" fill="none" stroke="#8fb2ff" stroke-opacity=".55" stroke-width="2"/>
 <rect x="14" y="{B+2}" width="{R-L}" height="12" rx="3" fill="#0b2bb5"/>
 <rect x="14" y="{B+2}" width="{R-L}" height="2.5" fill="#4d7cf2" opacity=".8"/>
 <rect x="30" y="{B+10}" width="{R-L-32}" height="2" fill="#061a78" opacity=".8"/>
 <g clip-path="url(#ban)">
  <rect x="{L}" y="{T}" width="{R-L}" height="{BAR}" fill="url(#bar)"/>
  <rect x="{L}" y="{T}" width="190" height="{BAR}" fill="url(#dots)" mask="url(#dm)"/>
 </g>
 <rect x="{L}" y="{T+BAR}" width="{R-L}" height="4" fill="#2e86e6"/>
 <rect x="{L}" y="{T+BAR}" width="{R-L}" height="1.2" fill="#7fc0ff" opacity=".8"/>
 {STEAM_MARKUP}
</g>
<!-- gloss over everything, art window included -->
<rect x="0" y="0" width="{W}" height="{H}" rx="20" fill="url(#gloss)"/>
</svg>'''

ORIGINAL_COLORS = {
    "case_top": "#2f5fe8", "case_mid": "#1636c8", "case_bottom": "#0a1e90",
    "bar_top": "#0d3a82", "bar_bottom": "#051c4d", "dots": "#5d8fd6",
    "edge": "#8fb2ff", "separator": "#2e86e6", "separator_high": "#7fc0ff",
    "lip_base": "#0b2bb5", "lip_high": "#4d7cf2", "lip_shadow": "#061a78",
}


def platform_svg(palette):
    """Keep the original case geometry and gloss; exchange only its palette and header logo."""
    result = svg.replace(STEAM_MARKUP, "")
    for key, original in ORIGINAL_COLORS.items():
        result = result.replace(original, palette[key])
    return result


@lru_cache(maxsize=1)
def steam_logo_bounds():
    """Visible bounds of the original Steam icon and wordmark rendered together."""
    from PIL import Image
    import resvg_py

    markup = ('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="900">'
              + STEAM_MARKUP + '</svg>')
    image = Image.open(io.BytesIO(resvg_py.svg_to_bytes(
        svg_string=markup, width=W, height=H, font_files=[FONT]))).convert("RGBA")
    bounds = image.getbbox()
    if bounds is None:
        raise ValueError("Steam reference logo has no visible pixels")
    return bounds


def fitted_logo_size(visible_size, correction=1.0):
    """Fit visible SVG art within the Steam mark, without enlarging source pixels."""
    if not 0 < correction <= 1:
        raise ValueError("logo correction must be in (0, 1]")
    left, top, right, bottom = steam_logo_bounds()
    reference_w, reference_h = right - left, bottom - top
    width, height = visible_size
    if width < 1 or height < 1:
        raise ValueError("SVG logo has no visible pixels")
    scale = min(1.0, reference_w / width, reference_h / height) * correction
    return max(1, round(width * scale)), max(1, round(height * scale))


def render_platform_frame(palette, logo_path, output, logo_box=(38, 20, 562, 84), logo_scale=1.0):
    """Render a transparent PNG using visible SVG bounds and Steam-sized logo caps."""
    from PIL import Image
    import resvg_py

    frame = Image.open(io.BytesIO(resvg_py.svg_to_bytes(
        svg_string=platform_svg(palette), width=W, height=H, font_files=[FONT]))).convert("RGBA")
    if logo_path:
        with open(logo_path, encoding="utf-8-sig") as source:
            logo = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=source.read()))).convert("RGBA")
        bounds = logo.getbbox()
        if bounds is None:
            raise ValueError("SVG logo has no visible pixels: " + logo_path)
        logo = logo.crop(bounds)
        left, top, right, bottom = logo_box
        size = fitted_logo_size(logo.size, logo_scale)
        if size[0] > right - left or size[1] > bottom - top:
            raise ValueError("Steam reference logo does not fit into the platform header")
        logo = logo.resize(size, Image.Resampling.LANCZOS)
        x = (left + right - logo.width) // 2
        y = (top + bottom - logo.height) // 2
        frame.alpha_composite(logo, (x, y))
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    frame.save(output)


def render_original_frame():
    from PIL import Image
    import resvg_py

    frame = Image.open(io.BytesIO(resvg_py.svg_to_bytes(
        svg_string=svg, width=W, height=H, font_files=[FONT]))).convert("RGBA")
    frame.save(OUT)
    print("wrote", os.path.normpath(OUT), "| art window:", (L, AT, R, B))


if __name__ == "__main__":
    render_original_frame()
