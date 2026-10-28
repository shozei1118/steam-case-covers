"""Original platinum rim and trophy, composited over an existing platform frame."""
from functools import lru_cache

from PIL import Image, ImageDraw


@lru_cache(maxsize=1)
def overlay():
    scale = 3
    size = (600, 900)
    layer = Image.new("RGBA", (size[0] * scale, size[1] * scale))
    draw = ImageDraw.Draw(layer)

    def box(coords):
        return tuple(value * scale for value in coords)

    # One original cup silhouette, centered entirely in the lower lip.
    outline = (40, 57, 75, 255)
    metal = (226, 239, 247, 255)
    light = (250, 253, 255, 255)
    shadow = (126, 162, 186, 255)
    draw.ellipse(box((276, 874, 324, 897)), fill=outline)
    draw.ellipse(box((278, 876, 322, 895)), fill=(77, 105, 129, 255))
    draw.arc(box((281, 876, 297, 890)), 70, 275, fill=metal, width=2 * scale)
    draw.arc(box((303, 876, 319, 890)), 265, 110, fill=metal, width=2 * scale)
    draw.polygon([(x * scale, y * scale) for x, y in
                  ((287, 876), (313, 876), (310, 886), (305, 890),
                   (295, 890), (290, 886))], fill=metal)
    draw.line(box((291, 878, 295, 886, 299, 888)), fill=light, width=scale)
    draw.line(box((309, 878, 305, 886, 302, 888)), fill=shadow, width=scale)
    draw.rectangle(box((298, 890, 302, 893)), fill=metal)
    draw.rounded_rectangle(box((292, 893, 308, 896)), radius=scale,
                           fill=metal, outline=outline, width=scale)
    return layer.resize(size, Image.Resampling.LANCZOS)


def apply(frame):
    if frame.size != (600, 900):
        raise ValueError("Platinum frames must be 600 x 900 pixels.")
    from platform_catalog import local_asset
    original = frame.convert("RGBA")
    with Image.open(local_asset("assets/platinum-rim.png")) as source:
        rim = source.convert("RGBA")
    result = original.copy()
    # Replace only the existing case material, retaining the exact source alpha,
    # rounded corners, header, separator and artwork. No extra contour is drawn.
    for region in ((0, 0, 600, 14), (0, 14, 14, 872),
                   (586, 14, 600, 872), (0, 872, 600, 900)):
        result.paste(rim.crop(region), region[:2])
    result.putalpha(original.getchannel("A"))
    return Image.alpha_composite(result, overlay())
