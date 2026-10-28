"""Platinum art is optional and follows preview, batch, export and reset paths."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageChops

import cover_workflow as cw
import steamcase as sc
from case_service import AppSettings, CaseService, CoverItem, Game
from platform_catalog import load_catalog


class PlatinumWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dark = self.root / "dark.png"
        self.light = self.root / "light.png"
        Image.new("RGB", (600, 900), "#18223a").save(self.dark)
        Image.new("RGB", (600, 900), "#f6ead8").save(self.light)

    def test_all_platforms_normal_pixels_and_platinum_geometry(self):
        for platform in load_catalog()["platforms"]:
            with self.subTest(platform=platform["id"]):
                standard = cw.export_one(self.dark, platform["id"], "Example",
                                         self.root / "normal" / platform["id"])
                platinum = cw.export_one(self.dark, platform["id"], "Example",
                                         self.root / "platinum" / platform["id"], platinum=True)
                with Image.open(standard) as a, Image.open(platinum) as b:
                    a, b = a.convert("RGBA"), b.convert("RGBA")
                    self.assertEqual(a.size, (600, 900))
                    self.assertEqual(b.size, (600, 900))
                    self.assertEqual(a.getchannel("A").tobytes(), b.getchannel("A").tobytes())
                    self.assertEqual(a.crop((14, 14, 586, 96)).tobytes(), b.crop((14, 14, 586, 96)).tobytes())
                    self.assertIsNone(ImageChops.difference(a.crop((14, 96, 586, 872)),
                                                             b.crop((14, 96, 586, 872))).getbbox())
                    self.assertIsNone(ImageChops.difference(a.crop((38, 20, 562, 84)),
                                                             b.crop((38, 20, 562, 84))).getbbox())
                    for point in ((0, 450), (599, 450), (300, 0), (300, 899)):
                        self.assertNotEqual(a.getpixel(point), b.getpixel(point))
                    self.assertNotEqual(a.getpixel((300, 884)), b.getpixel((300, 884)))
                    self.assertEqual(b.getpixel((300, 500)), a.getpixel((300, 500)))
                    self.assertTrue(sc.is_steamcase_cover(platinum))

    def test_settings_preview_batch_export_and_prepared_cover(self):
        settings = AppSettings(self.root / "settings.json")
        service = CaseService(settings)
        game = Game("Example", "steam", 220, 220, True)
        self.assertFalse(service.platinum_for(game))
        service.remember_platinum(game, True)
        restored = CaseService(AppSettings(settings.path))
        self.assertTrue(restored.platinum_for(game))
        item = CoverItem(game, "ps5", str(self.light), platinum=True)
        standard = restored.preview(CoverItem(game, "ps5", str(self.light)))
        premium = restored.preview(item)
        self.assertNotEqual(standard, premium)
        self.assertNotEqual(standard.read_bytes(), premium.read_bytes())
        restored.add(item)
        self.assertTrue(restored.queue[item.key].platinum)
        exported, errors = restored.export_all(self.root / "batch")
        self.assertFalse(errors)
        self.assertEqual(exported[0].read_bytes(), premium.read_bytes())
        direct = restored.export_one(item, self.root / "direct")
        self.assertEqual(direct.read_bytes(), exported[0].read_bytes())
        prepared = CoverItem(game, "steam", file=str(standard), platinum=True)
        decorated = restored.preview(prepared)
        self.assertNotEqual(decorated, standard)
        self.assertEqual(standard.read_bytes(), restored.preview(CoverItem(game, "steam", file=str(standard))).read_bytes())
        self.assertTrue(sc.is_steamcase_cover(decorated))
        restored.remember_platinum(game, False)
        self.assertFalse(CaseService(AppSettings(settings.path)).platinum_for(game))

    def test_apply_uses_platinum_png_and_restore_keeps_previous_art(self):
        steam = self.root / "steam"
        grid = steam / "userdata" / "111" / "config" / "grid"
        grid.mkdir(parents=True)
        (steam / "config").mkdir()
        previous = grid / "220p.png"
        previous.write_bytes(b"old artwork")
        settings = AppSettings(self.root / "settings.json")
        settings.account = "111"
        service = CaseService(settings, self.root / "covers")
        item = CoverItem(Game("Example", "steam", 220, 220, True), "wii",
                         str(self.dark), platinum=True)
        expected = cw.export_one(self.dark, "wii", "Example", self.root / "expected",
                                 220, True).read_bytes()
        with mock.patch.object(sc, "steam_dir", return_value=str(steam)), \
             mock.patch.object(sc, "steam_running", return_value=False), \
             mock.patch.object(cw, "cache_dir", return_value=self.root / "cache"):
            service.apply_items([item])
            self.assertEqual(previous.read_bytes(), expected)
            service.restore()
        self.assertEqual(previous.read_bytes(), b"old artwork")


if __name__ == "__main__":
    unittest.main()
