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

    # Narrow metallic bands stay outside the artwork window (x=14..585).
    bands = (
        (0, (65, 79, 98, 255)),
        (2, (194, 214, 226, 255)),
        (4, (239, 246, 250, 255)),
        (6, (136, 162, 181, 255)),
        (9, (76, 98, 118, 255)),
        (11, (214, 229, 237, 230)),
    )
    for inset, color in bands:
        draw.rectangle(box((inset, inset, 599 - inset, 899 - inset)),
                       outline=color, width=scale * (2 if inset in (0, 4) else 1))
    # Restrained icy reflection along the top and side edges.
    draw.line(box((18, 3, 581, 3)), fill=(248, 253, 255, 215), width=scale)
    draw.line(box((3, 22, 3, 840)), fill=(204, 230, 245, 135), width=scale)
    draw.line(box((596, 22, 596, 840)), fill=(225, 241, 251, 115), width=scale)

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
    return Image.alpha_composite(frame.convert("RGBA"), overlay())
