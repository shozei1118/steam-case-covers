"""Original platinum rim and trophy, composited over an existing platform frame."""
from functools import lru_cache

from PIL import Image


@lru_cache(maxsize=1)
def overlay():
    from platform_catalog import local_asset
    with Image.open(local_asset("assets/platinum-trophy.png")) as source:
        return source.convert("RGBA")


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
