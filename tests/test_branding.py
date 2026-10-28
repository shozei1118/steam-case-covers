"""App identity and icon resources used by the GUI and release build."""
from pathlib import Path
import unittest
from unittest import mock

from PIL import Image

import gui
import steamcase


ROOT = Path(__file__).resolve().parents[1]


class Branding(unittest.TestCase):
    def test_update_checker_available_without_affecting_version(self):
        self.assertTrue(hasattr(gui.App, "check_update"))
        self.assertTrue(hasattr(steamcase, "check_for_update"))
        self.assertTrue(isinstance(steamcase.APP_VERSION, str))

    def test_update_check_uses_official_repository(self):
        with mock.patch.object(steamcase, "http_get", return_value=b'[{"tag_name":"v1.5.2"}]') as get:
            release = steamcase.check_for_update("v1.5.1")
        self.assertIn("api.github.com/repos/shozei1118/steam-case-covers/releases", get.call_args.args[0])
        self.assertEqual(release["url"], "https://github.com/shozei1118/steam-case-covers/releases/tag/v1.5.2")

    def test_icon_formats_have_transparent_small_and_large_sizes(self):
        with Image.open(ROOT / "assets" / "icon.png") as icon:
            self.assertEqual(icon.size, (256, 256))
            self.assertEqual(icon.mode, "RGBA")
            self.assertEqual(icon.getpixel((0, 0))[3], 0)
        with Image.open(ROOT / "assets" / "icon.ico") as icon:
            self.assertTrue({(16, 16), (32, 32), (256, 256)}.issubset(icon.info["sizes"]))
        with Image.open(ROOT / "assets" / "icon.icns") as icon:
            self.assertGreaterEqual(icon.size[0], 512)


if __name__ == "__main__":
    unittest.main()
