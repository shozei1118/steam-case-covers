"""Portable artwork backup and restore, using only a temporary fake Steam account."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import steamcase as sc
from case_service import AppSettings, CaseService


class ArtworkBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.steam = self.root / "steam"
        self.grid = self.steam / "userdata" / "111" / "config" / "grid"
        self.grid.mkdir(parents=True)

    def image(self, name, color="navy"):
        path = self.grid / name
        Image.new("RGB", (80, 120), color).save(path)
        return path

    def export(self, shortcut_ids=()):
        return sc.export_artwork_backup(str(self.steam), str(self.root / "portable"),
                                        "111", shortcut_ids=shortcut_ids)

    def test_export_includes_steam_and_shortcut_art_from_other_tools(self):
        self.image("220p.png")
        self.image("3221225473p.jpg", "blue")  # verified non-Steam shortcut ID format
        self.image("440p.webp", "green")
        self.image("0p.png", "white")
        (self.grid / "999p.png").write_bytes(b"not an image")
        (self.grid / "header.png").write_bytes(b"not a portrait")
        result = self.export({3221225473})
        self.assertEqual(result["exported"], 3)
        self.assertEqual([x["filename"] for x in result["skipped"]], ["0p.png", "999p.png"])
        manifest = json.loads((self.root / "portable" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["account"], "111")
        self.assertEqual({(item["id"], item["filename"]) for item in manifest["files"]},
                         {(220, "220p.png"), (3221225473, "3221225473p.jpg"), (440, "440p.webp")})
        self.assertEqual(next(item["kind"] for item in manifest["files"]
                              if item["id"] == 3221225473), "shortcut")
        self.assertFalse((self.root / "portable" / "999p.png").exists())
        self.assertFalse((self.root / "portable" / "header.png").exists())

    def test_missing_shortcut_record_blocks_import_without_dropping_export(self):
        self.image("3221225473p.png")
        self.export({3221225473})
        plan = sc.inspect_artwork_backup(str(self.steam), str(self.root / "portable"),
                                         "111", shortcut_ids=set())
        self.assertFalse(plan["can_import"])
        self.assertIn("shortcut ID", plan["issues"][0])

    def test_read_only_export_survives_damaged_shortcuts_file(self):
        self.image("3221225473p.png")
        settings = AppSettings(self.root / "settings.json")
        settings.account = "111"
        service = CaseService(settings)
        with mock.patch.object(service, "steam", return_value=str(self.steam)), \
             mock.patch("case_service.cw.list_shortcuts", side_effect=sc.SteamcaseError("bad VDF")):
            result = service.export_artwork_backup(str(self.root / "portable"), "111")
        self.assertEqual(result["exported"], 1)
        plan = sc.inspect_artwork_backup(str(self.steam), result["path"], "111", shortcut_ids=set())
        self.assertFalse(plan["can_import"], "High-bit artwork IDs still need a verified shortcut before import")

    def test_export_refuses_to_count_steam_defaults_without_local_files(self):
        with self.assertRaisesRegex(sc.SteamcaseError, "No valid locally stored"):
            self.export()
        self.assertFalse((self.root / "portable").exists())

    def test_preview_import_conflict_and_restore_safety_backup(self):
        self.image("220p.png", "red")
        self.image("3221225473p.jpg", "green")
        self.export()
        original = (self.grid / "220p.png").read_bytes()
        self.image("220p.jpg", "blue")
        old_jpg = (self.grid / "220p.jpg").read_bytes()
        self.image("220p.png", "purple")
        (self.grid / "3221225473p.jpg").unlink()
        plan = sc.inspect_artwork_backup(str(self.steam), str(self.root / "portable"), "111")
        self.assertTrue(plan["can_import"])
        self.assertEqual((plan["new"], plan["overwrite"], plan["removals"]),
                         (1, 1, ["220p.jpg"]))
        result = sc.import_artwork_backup(str(self.steam), str(self.root / "portable"),
                                          "111", expected=plan["token"])
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["removed"], 1)
        self.assertEqual((self.grid / "220p.png").read_bytes(), original)
        self.assertFalse((self.grid / "220p.jpg").exists())
        self.assertTrue((self.grid / "3221225473p.jpg").exists())
        self.assertIn(result["backup"], sc.list_backups(str(self.steam), "111"))
        sc.restore_backup(str(self.steam), result["backup"], "111")
        self.assertEqual((self.grid / "220p.jpg").read_bytes(), old_jpg)
        self.assertFalse((self.grid / "3221225473p.jpg").exists())

    def test_missing_or_changed_backup_file_blocks_import(self):
        self.image("220p.png")
        self.export()
        package_file = self.root / "portable" / "220p.png"
        package_file.unlink()
        plan = sc.inspect_artwork_backup(str(self.steam), str(self.root / "portable"), "111")
        self.assertFalse(plan["can_import"])
        self.assertIn("Invalid", plan["rows"][0]["status"])
        with self.assertRaises(sc.SteamcaseError):
            sc.import_artwork_backup(str(self.steam), str(self.root / "portable"), "111")
        self.assertEqual(sc.list_backups(str(self.steam), "111"), [])

    def test_stale_preview_and_write_failure_leave_current_art_unchanged(self):
        self.image("220p.png", "red")
        self.image("440p.png", "blue")
        self.export()
        self.image("220p.png", "green")
        self.image("440p.png", "purple")
        plan = sc.inspect_artwork_backup(str(self.steam), str(self.root / "portable"), "111")
        self.image("440p.png", "yellow")
        with self.assertRaisesRegex(sc.SteamcaseError, "changed since the preview"):
            sc.import_artwork_backup(str(self.steam), str(self.root / "portable"),
                                     "111", expected=plan["token"])
        plan = sc.inspect_artwork_backup(str(self.steam), str(self.root / "portable"), "111")
        before = {name: (self.grid / name).read_bytes() for name in ("220p.png", "440p.png")}
        original_copy = sc._safe_copy
        writes = {"count": 0}

        def fail_second(src, dst):
            if Path(dst).parent == self.grid:
                writes["count"] += 1
                if writes["count"] == 2:
                    raise OSError("simulated write failure")
            return original_copy(src, dst)

        with mock.patch.object(sc, "_safe_copy", side_effect=fail_second):
            with self.assertRaisesRegex(sc.SteamcaseError, "No changes were kept"):
                sc.import_artwork_backup(str(self.steam), str(self.root / "portable"),
                                         "111", expected=plan["token"])
        self.assertEqual({name: (self.grid / name).read_bytes() for name in before}, before)
        self.assertEqual(sc.list_backups(str(self.steam), "111"), [])

    def test_service_closes_and_restarts_steam_once_for_import(self):
        self.image("220p.png", "red")
        self.export()
        self.image("220p.png", "blue")
        settings = AppSettings(self.root / "settings.json")
        settings.account = "111"
        settings.restart_steam = True
        service = CaseService(settings)
        plan = sc.inspect_artwork_backup(str(self.steam), str(self.root / "portable"), "111")
        with mock.patch.object(service, "steam", return_value=str(self.steam)), \
             mock.patch.object(sc, "steam_running", return_value=True), \
             mock.patch.object(sc, "close_steam", return_value=True) as close, \
             mock.patch.object(sc, "start_steam") as start:
            result = service.import_artwork_backup(str(self.root / "portable"), plan["token"], "111")
        self.assertEqual(result["imported"], 1)
        close.assert_called_once()
        start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
