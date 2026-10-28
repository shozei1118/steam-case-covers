"""Checks for the independently exported platform frame assets."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops

from platform_catalog import get_platform, load_catalog, local_asset
from tools.build_platform_frames import export_frame
from tools.build_frame import fitted_logo_size, render_platform_frame, steam_logo_bounds, svg


class PlatformFrames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.platforms = cls.catalog["platforms"]

    def test_catalog_and_local_logos(self):
        self.assertEqual(len(self.platforms), 29)
        self.assertEqual({p["family"] for p in self.platforms},
                         {"PlayStation", "Xbox", "Nintendo", "Sega", "PC"})
        self.assertEqual(get_platform("switch_2")["logo_default"], "light")
        removed = {"windows", "linux", "dos", "game_gear", "atari_2600", "atari_5200",
                   "atari_7800", "atari_lynx", "atari_jaguar"}
        self.assertFalse(removed.intersection({p["id"] for p in self.platforms}))
        for platform in self.platforms:
            with self.subTest(platform=platform["id"]):
                self.assertEqual(platform["template"]["id"], "steam_case_v1")
                self.assertEqual(len(platform["palette"]), 12)
                self.assertEqual(platform["template"]["logo_box"], [38, 20, 562, 84])
                self.assertGreater(platform["template"].get("logo_scale", 1.0), 0)
                self.assertLessEqual(platform["template"].get("logo_scale", 1.0), 1.0)
                if platform["logo_default"]:
                    self.assertIn(platform["logo_default"], platform["logos"])
                for path in list(platform["logos"].values()) + list(platform.get("regional_logos", {}).values()):
                    self.assertTrue(os.path.isfile(local_asset(path)), path)

    def test_manifest_integrity(self):
        with open(local_asset("assets/logos/MANIFEST.json"), encoding="utf-8") as source:
            manifest = json.load(source)
        catalog_paths = {path for platform in self.platforms
                         for path in list(platform["logos"].values()) +
                         list(platform.get("regional_logos", {}).values())}
        manifest_paths = {item["file"] for item in manifest["files"]}
        self.assertEqual(catalog_paths, manifest_paths)
        logo_root = Path(local_asset("assets/logos"))
        self.assertEqual({"assets/logos/" + path.relative_to(logo_root).as_posix()
                          for path in logo_root.rglob("*.svg")}, manifest_paths)
        self.assertEqual({p["id"] + ".png" for p in self.platforms},
                         set(os.listdir(local_asset("assets/frames"))))
        for item in manifest["files"]:
            with self.subTest(file=item["file"]):
                self.assertTrue(item["source"].startswith("https://"))
                self.assertTrue(item["license"])
                with open(local_asset(item["file"]), "rb") as asset:
                    self.assertEqual(hashlib.sha256(asset.read()).hexdigest(), item["sha256"])

    def test_generated_png_geometry_palette_and_steam_compatibility(self):
        for platform in self.platforms:
            with self.subTest(platform=platform["id"]):
                with Image.open(local_asset("assets/frames/%s.png" % platform["id"])) as frame:
                    self.assertEqual(frame.size, (600, 900))
                    self.assertEqual(frame.mode, "RGBA")
                    self.assertEqual(frame.getpixel((300, 400))[3], 0)
                    self.assertGreater(frame.getpixel((2, 150))[3], 0)
                    expected_lip = tuple(bytes.fromhex(platform["palette"]["lip_base"][1:]))
                    self.assertEqual(frame.getpixel((20, 879))[:3], expected_lip)
        with open(local_asset("assets/frame.png"), "rb") as original, \
             open(local_asset("assets/frames/steam.png"), "rb") as copied:
            self.assertEqual(original.read(), copied.read())

    def test_ps5_and_wii_outer_rims_are_visibly_colored(self):
        # These two light headers used to leave the case rim almost white.
        for platform_id in ("ps5", "wii"):
            with self.subTest(platform=platform_id):
                with Image.open(local_asset("assets/frames/%s.png" % platform_id)) as frame:
                    red, green, blue, alpha = frame.getpixel((7, 450))
                    self.assertEqual(alpha, 255)
                    self.assertGreater(max(red, green, blue) - min(red, green, blue), 70)
                    self.assertEqual(frame.getpixel((300, 450))[3], 0)

    def test_reviewed_logo_variants_match_exported_frames(self):
        expected = {"ps2": "light", "ps3": "light", "psp": "light",
                    "wii": "light", "ps5": "light", "game_boy": "light",
                    "game_boy_color": "colored", "n64": "colored",
                    "gamecube": "light", "dreamcast": "colored", "ps1": "colored"}
        self.assertEqual(get_platform("n64")["frame_color"], "#2388a3")
        self.assertEqual(get_platform("game_boy_color")["frame_color"], "#7654a3")
        with tempfile.TemporaryDirectory() as folder:
            for platform_id, variant in expected.items():
                with self.subTest(platform=platform_id):
                    platform = get_platform(platform_id)
                    self.assertEqual(platform["logo_default"], variant)
                    generated = os.path.join(folder, platform_id + ".png")
                    export_frame(platform, generated)
                    with Image.open(generated) as fresh, \
                         Image.open(local_asset("assets/frames/%s.png" % platform_id)) as saved:
                        self.assertEqual(fresh.tobytes(), saved.tobytes())
                        self.assertEqual(saved.getpixel((300, 450))[3], 0)

    def test_playstation_wordmarks_have_no_secondary_name_line(self):
        try:
            import resvg_py
        except ImportError:
            self.skipTest("resvg_py build dependency not installed")
        import io
        for platform_id in ("ps2", "ps3", "psp"):
            with self.subTest(platform=platform_id):
                logo = local_asset(get_platform(platform_id)["logos"]["light"])
                with open(logo, encoding="utf-8-sig") as source:
                    image = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=source.read())))
                bounds = image.convert("RGBA").getbbox()
                self.assertIsNotNone(bounds)
                self.assertGreater((bounds[2] - bounds[0]) / (bounds[3] - bounds[1]), 4.5)

    def test_all_headers_center_logos_without_os_badges(self):
        try:
            import resvg_py  # noqa: F401 - optional build dependency
        except ImportError:
            self.skipTest("resvg_py build dependency not installed")
        self.assertNotIn(">Linux</text>", svg)
        self.assertNotIn(">Windows</text>", svg)
        self.assertNotIn("data:image/svg+xml;base64,", svg)
        left_ref, top_ref, right_ref, bottom_ref = steam_logo_bounds()
        reference_size = (right_ref - left_ref, bottom_ref - top_ref)
        self.assertEqual(reference_size, (204, 42))
        self.assertLess(fitted_logo_size((400, 100), 0.75)[0],
                        fitted_logo_size((400, 100))[0])
        with self.assertRaises(ValueError):
            fitted_logo_size((400, 100), 1.1)
        logo_bounds = {}
        with tempfile.TemporaryDirectory() as folder:
            for platform in self.platforms:
                with self.subTest(platform=platform["id"]):
                    blank_path = os.path.join(folder, platform["id"] + "-blank.png")
                    render_platform_frame(platform["palette"], None, blank_path,
                                          platform["template"]["logo_box"])
                    with Image.open(local_asset("assets/frames/%s.png" % platform["id"])) as default, \
                         Image.open(blank_path) as blank:
                        difference = ImageChops.difference(
                            default.convert("RGB").crop((0, 14, 600, 92)),
                            blank.convert("RGB").crop((0, 14, 600, 92)))
                        box = difference.getbbox()
                        self.assertIsNotNone(box)
                        left, top, right, bottom = box
                        top += 14
                        bottom += 14
                        logo_bounds[platform["id"]] = (left, top, right, bottom)
                        self.assertGreaterEqual(left, 38)
                        self.assertLessEqual(right, 562)
                        self.assertGreaterEqual(top, 20)
                        self.assertLessEqual(bottom, 84)
                        self.assertLessEqual(right - left, reference_size[0])
                        self.assertLessEqual(bottom - top, reference_size[1])
                        self.assertLessEqual(abs((left + right) / 2 - 300), 2)
        color = logo_bounds["game_boy_color"]
        advance = logo_bounds["game_boy_advance"]
        self.assertLess(advance[3] - advance[1], color[3] - color[1])
        self.assertEqual(advance[2] - advance[0], reference_size[0])
        self.assertEqual(color[2] - color[0], reference_size[0])

    def test_explicit_variant_rejects_missing_logo(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "no colored SVG logo"):
                export_frame(get_platform("saturn"), os.path.join(folder, "saturn.png"), "colored")

    def test_platform_specific_logo_correction(self):
        platform = dict(get_platform("game_boy_color"))
        platform["template"] = dict(platform["template"], logo_scale=0.75)
        with tempfile.TemporaryDirectory() as folder:
            corrected = os.path.join(folder, "corrected.png")
            blank = os.path.join(folder, "blank.png")
            export_frame(platform, corrected)
            render_platform_frame(platform["palette"], None, blank, platform["template"]["logo_box"])
            with Image.open(corrected) as result, Image.open(blank) as base:
                box = ImageChops.difference(result.convert("RGB"), base.convert("RGB")).getbbox()
            self.assertIsNotNone(box)
            self.assertLess(box[2] - box[0], steam_logo_bounds()[2] - steam_logo_bounds()[0])
            self.assertLessEqual(abs((box[0] + box[2]) / 2 - 300), 2)

    def test_svg_viewbox_whitespace_is_ignored(self):
        platform = get_platform("ps4")
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "margin.svg")
            with open(source, "w", encoding="utf-8") as target:
                target.write('<svg xmlns="http://www.w3.org/2000/svg" width="500" height="500" '
                             'viewBox="0 0 500 500"><rect x="40" y="20" width="100" '
                             'height="20" fill="white"/></svg>')
            result = os.path.join(folder, "result.png")
            blank = os.path.join(folder, "blank.png")
            render_platform_frame(platform["palette"], source, result, platform["template"]["logo_box"])
            render_platform_frame(platform["palette"], None, blank, platform["template"]["logo_box"])
            with Image.open(result) as actual, Image.open(blank) as base:
                box = ImageChops.difference(actual.convert("RGB"), base.convert("RGB")).getbbox()
            self.assertIsNotNone(box)
            self.assertEqual((box[2] - box[0], box[3] - box[1]), (100, 20))
            self.assertLessEqual(abs((box[0] + box[2]) / 2 - 300), 1)


if __name__ == "__main__":
    unittest.main()
