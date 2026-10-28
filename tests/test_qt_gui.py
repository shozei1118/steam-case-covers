"""Exercise the four Qt views and their one shared cover editor without network."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest

from case_service import AppSettings, CaseService, CoverItem, Game
import cover_workflow as cw
import steamcase as sc
from qt_gui import ArtworkGrid, MainWindow, STYLE


class QtWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.art = self.root / "art.png"
        Image.new("RGB", (600, 900), "navy").save(self.art)
        self.service = CaseService(AppSettings(self.root / "settings.json"), self.root / "covers")
        self.game = Game("A very long game title with additional words", "steam", 220, 220, True)
        self.window = MainWindow(self.service, auto_refresh=False)
        self.addCleanup(self.window.close)
        self.window.show()
        self.app.processEvents()

    def wait(self, condition):
        end = time.monotonic() + 5
        while not condition() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.01)
        self.assertTrue(condition())

    def test_views_and_library_selection_use_one_editor(self):
        self.assertEqual(self.window.pages.count(), 5)
        self.assertEqual(self.window.editor.platform.count(), 29)
        self.window.library_games = [self.game]
        self.window.filter_library()
        self.window.library_filter.setText("LONG GAME")
        self.assertEqual(self.window.library_list.count(), 1)
        with mock.patch.object(self.service, "current_cover", return_value=self.art), \
             mock.patch.object(self.service, "artwork", return_value=[]):
            self.window.library_list.setCurrentRow(0)
            self.wait(lambda: self.window.game == self.game and self.window.editor.current.original is not None)
        editor = self.window.editor
        self.window.navigate("Search")
        self.assertIs(self.window.editor, editor)
        self.window.navigate("Batch")
        self.assertFalse(self.window.editor.isVisible())
        self.window.navigate("Backup")
        self.assertFalse(self.window.editor.isVisible())
        self.assertTrue(self.window.reset_everything.isVisible())
        self.window.navigate("Settings")
        self.app.processEvents()
        self.assertFalse(self.window.editor.isVisible())
        self.assertEqual(self.window.splitter.sizes()[2], 0)
        self.assertGreater(self.window.splitter.sizes()[1], 600)
        self.assertIs(self.window.editor, editor)

    def test_platinum_toggle_persists_and_batch_edit_restores_it(self):
        with mock.patch.object(self.service, "current_cover", return_value=None), \
             mock.patch.object(self.service, "artwork", return_value=[]):
            self.window.select_game(self.game)
        self.assertFalse(self.window.editor.platinum.isChecked())
        self.window.image_path = str(self.art)
        self.window.render_preview()
        self.wait(lambda: self.window.preview_path is not None)
        standard = self.window.preview_path
        self.window.editor.platinum.setChecked(True)
        self.wait(lambda: self.window.preview_path is not None and self.window.preview_path != standard)
        self.assertTrue(self.service.platinum_for(self.game))
        self.window.add_to_batch()
        self.assertTrue(self.service.queue["steam:220"].platinum)
        self.window.navigate("Batch")
        self.assertIn("Platinum", self.window.batch_table.item(0, 0).text())
        self.window.batch_table.selectRow(0)
        with mock.patch.object(self.service, "current_cover", return_value=None), \
             mock.patch.object(self.service, "artwork", return_value=[]):
            self.window.edit_batch()
        self.assertTrue(self.window.editor.platinum.isChecked())
        self.assertTrue(AppSettings(self.service.settings.path).platinum_choices["steam:220"])
        self.window.editor.platinum.setChecked(False)
        self.wait(lambda: self.window.preview_path is not None)
        self.assertFalse(self.service.platinum_for(self.game))

    def test_library_download_button_opens_steam_and_manual_file_still_loads(self):
        import json
        import qt_gui
        library = self.root / "userdata.json"
        library.write_text(json.dumps({"rgOwnedApps": [220]}), encoding="utf-8")
        with mock.patch.object(qt_gui.QDesktopServices, "openUrl", return_value=True) as browser, \
             mock.patch.object(sc, "library_login_url", return_value="https://store.steampowered.com/login/?redir=dynamicstore"), \
             mock.patch.object(QFileDialog, "getOpenFileName", return_value=(str(library), "")), \
             mock.patch.object(self.window, "refresh_library") as refresh:
            self.window.download_game_list_button.click()
            self.assertEqual(browser.call_count, 1)
            self.assertTrue(browser.call_args.args[0].isValid())
            self.window.load_userdata()
            refresh.assert_called_once()
        self.assertEqual(self.service.settings.userdata, str(library))

    def test_local_only_clears_saved_import_and_refreshes(self):
        self.service.settings.userdata = str(self.root / "userdata.json")
        self.service.settings.save()
        with mock.patch.object(self.window, "refresh_library") as refresh:
            self.window.clear_userdata()
        self.assertIsNone(self.service.settings.userdata)
        self.assertIsNone(AppSettings(self.service.settings.path).userdata)
        refresh.assert_called_once()

    def test_manual_search_thumbnail_preview_batch_and_direct_apply(self):
        game = Game("Manual result", "steamgriddb", 7)
        with mock.patch.object(self.service, "search", return_value=[game, Game("Other", "steamgriddb", 8)]):
            self.window.navigate("Search")
            self.window.search_source.setCurrentText("SteamGridDB")
            self.window.search_term.setText("Manual")
            self.window.search_games_now()
            self.wait(lambda: self.window.search_list.count() == 2)
            self.assertIsNone(self.window.game, "Ambiguous results must not be selected")
        art = [{"id": 13, "style": "alternate", "url": "https://example.com/art.png"}]
        with mock.patch.object(self.service, "artwork", return_value=art), \
             mock.patch.object(self.service, "image", return_value=self.art), \
             mock.patch.object(self.service, "preview", return_value=self.art):
            self.window.search_list.itemClicked.emit(self.window.search_list.item(0))
            self.wait(lambda: len(self.window.gallery.tiles) == 1)
            QTest.mouseClick(self.window.gallery.tiles[0], Qt.MouseButton.LeftButton)
            self.wait(lambda: self.window.preview_path == str(self.art))
            self.assertTrue(self.window.gallery.tiles[0].property("selected"))
        self.assertFalse(self.window.editor.apply.isEnabled())
        self.window.add_to_batch()
        self.assertEqual(len(self.service.queue), 1)
        self.window.navigate("Batch")
        self.assertEqual(self.window.batch_table.rowCount(), 1)
        self.window.batch_table.selectRow(0)
        self.window.remove_batch()
        self.assertEqual(self.window.batch_table.rowCount(), 0)

    def test_verified_library_game_can_apply_without_batch(self):
        self.window.game = self.game
        self.window.image_path = str(self.art)
        self.window.preview_path = str(self.art)
        self.window.editor.set_game(self.game)
        self.window.editor.set_ready(True, True)
        result = {"changed_ids": [220], "applied": 1, "unchanged": 0, "backup": "backup"}
        with mock.patch.object(self.window, "_confirm_apply", return_value=True), \
             mock.patch.object(self.service, "apply_items", return_value=result) as apply, \
             mock.patch.object(self.service, "current_cover", return_value=self.art):
            self.window.editor.apply.click()
            self.wait(lambda: apply.call_count == 1 and not self.window.busy)
        self.assertEqual(len(apply.call_args.args[0]), 1)
        self.assertEqual(len(self.service.queue), 0, "Direct Apply must not require Batch")

    def test_shortcut_keeps_verified_steam_artwork_id(self):
        shortcut = Game("Non-Steam title", "shortcut", 0xC0000001, 0xC0000001, True)
        result = Game("Matching title", "steamgriddb", 17)
        self.window.library_games = [shortcut]
        self.window.filter_library()
        with mock.patch.object(self.service, "search", return_value=[result]), \
             mock.patch.object(self.service, "current_cover", return_value=None), \
             mock.patch.object(self.service, "artwork", return_value=[]):
            self.window.library_list.setCurrentRow(0)
            self.wait(lambda: len(self.window.search_games) == 1 and self.window.shortcut_context == shortcut)
            self.assertEqual(self.window.game.steam_id, shortcut.steam_id)
            self.window.search_list.itemClicked.emit(self.window.search_list.item(0))
            self.wait(lambda: self.window.game.source == "steamgriddb")
        self.assertEqual(self.window.game.id, 17)
        self.assertEqual(self.window.game.steam_id, shortcut.steam_id)
        self.assertTrue(self.window.game.verified)
        self.window.navigate("Search")
        self.assertIsNone(self.window.shortcut_context, "A later manual search must not reuse a shortcut ID")

    def test_automatic_batch_item_is_editable_and_keeps_its_preview(self):
        generated = self.root / "Auto_220.png"
        Image.new("RGB", (600, 900), "green").save(generated)
        self.service.add(CoverItem(self.game, "steam", file=str(generated), preview=str(generated)))
        self.window.navigate("Batch")
        self.window.batch_table.selectRow(0)
        with mock.patch.object(self.service, "current_cover", return_value=None), \
             mock.patch.object(self.service, "artwork", return_value=[]):
            self.window.edit_batch()
            self.wait(lambda: self.window.prepared_file == str(generated))
        self.assertEqual(self.window.current_item().file, str(generated))
        self.assertTrue(self.window.editor.export.isEnabled())

    def test_settings_and_resizing(self):
        self.window.navigate("Settings")
        self.window.export_folder.setText(str(self.root / "export"))
        self.window.default_source.setCurrentText("SteamGridDB")
        self.assertEqual(self.service.settings.default_source, "SteamGridDB")
        self.assertTrue(self.service.settings.path.is_file())
        for width, height in ((900, 610), (1150, 730), (1490, 900)):
            self.window.resize(width, height)
            self.app.processEvents()
            self.assertGreaterEqual(self.window.splitter.sizes()[1], 330)
            self.assertEqual(self.window.splitter.sizes()[2], 0)
        self.window.navigate("Library")
        self.app.processEvents()
        self.assertGreaterEqual(self.window.splitter.sizes()[2], 325)

    def test_account_change_is_saved_and_refreshes_library(self):
        self.window.account_combo.addItem("Second account", "222")
        with mock.patch.object(self.window, "refresh_library") as refresh, \
             mock.patch.object(self.window, "refresh_backups") as backups:
            self.window.account_combo.setCurrentIndex(1)
        self.assertEqual(self.service.settings.account, "222")
        self.assertEqual(AppSettings(self.service.settings.path).account, "222")
        refresh.assert_called_once()
        backups.assert_called_once()

    def test_library_filters_and_editor_state_survive_navigation(self):
        installed = Game("Installed game", "steam", 220, 220, True, True)
        owned = Game("Owned game", "steam", 440, 440, True, False)
        shortcut = Game("Shortcut", "shortcut", 0xC0000001, 0xC0000001, True)
        self.window._library_loaded([installed, owned, shortcut])
        self.assertEqual(self.window.library_list.count(), 3)
        for scope, expected in (("Installed", "Installed game"),
                                ("Not installed", "Owned game"),
                                ("Non-Steam", "Shortcut")):
            self.window.library_scope.setCurrentIndex(self.window.library_scope.findData(scope))
            self.assertEqual(self.window.library_list.count(), 1)
            self.assertIn(expected, self.window.library_list.item(0).text())
        self.window.library_scope.setCurrentIndex(self.window.library_scope.findData("All"))
        self.window.library_filter.setText("440")
        self.assertEqual(self.window.library_list.count(), 1)
        self.window.library_filter.clear()
        self.window.game = installed
        self.window.image_path = str(self.art)
        self.window.preview_path = str(self.art)
        editor = self.window.editor
        editor.set_game(installed)
        editor.new.set_path(self.art)
        for page in ("Batch", "Backup", "Settings", "Search", "Library"):
            self.window.navigate(page)
            self.app.processEvents()
        self.assertIs(self.window.editor, editor)
        self.assertEqual(self.window.game.steam_id, 220)
        self.assertEqual(self.window.preview_path, str(self.art))
        self.assertTrue(editor.isVisible())

    def test_library_splitter_counts_compact_rows_and_persistence(self):
        installed = Game("A very long installed title " * 8, "steam", 220, 220, True, True)
        owned = Game("Owned", "steam", 440, 440, True, False)
        shortcut = Game("Shortcut", "shortcut", 0xC0000001, 0xC0000001, True)
        self.window._library_loaded([installed, owned, shortcut])
        self.assertEqual(self.window.library_scope.itemText(0), "All (3)")
        self.assertEqual(self.window.library_scope.itemText(1), "Installed (1)")
        self.assertEqual(self.window.library_scope.itemText(2), "Not installed (1)")
        self.assertEqual(self.window.library_scope.itemText(3), "Non-Steam (1)")
        self.assertNotIn("\n", self.window.library_list.item(0).text())
        self.assertEqual(self.window.library_list.item(0).text(), installed.name)
        self.assertEqual(self.window.library_list.item(0).data(Qt.ItemDataRole.UserRole + 1), "Installed")
        self.assertEqual(self.window.library_list.item(1).data(Qt.ItemDataRole.UserRole + 1), "Not installed")
        self.assertEqual(self.window.library_list.item(2).data(Qt.ItemDataRole.UserRole + 1), "Non-Steam")
        self.assertIn(installed.name, self.window.library_list.item(0).toolTip())
        with mock.patch.object(self.service, "current_cover", return_value=None), \
             mock.patch.object(self.service, "artwork", return_value=[]):
            row = self.window.library_list.visualItemRect(self.window.library_list.item(0))
            QTest.mouseClick(self.window.library_list.viewport(), Qt.MouseButton.LeftButton,
                             pos=row.center() + QPoint(row.width() // 2 - 12, 0))
            self.wait(lambda: self.window.game == installed)
            self.assertTrue(self.window.library_list.item(0).isSelected())
        self.window.library_filter.setText("Owned")
        self.assertEqual(self.window.library_scope.itemText(0), "All (1)")
        self.assertEqual(self.window.library_list.count(), 1)
        self.window.library_filter.clear()
        self.window.library_splitter.moveSplitter(365, 1)
        self.app.processEvents()
        QTest.qWait(300)
        saved = AppSettings(self.service.settings.path).library_splitter_sizes
        self.assertGreater(saved[0], 300)
        self.window.navigate("Search")
        self.window.navigate("Library")
        self.assertGreater(self.window.library_splitter.sizes()[0], 300)

    def test_artwork_keyboard_navigation_batch_and_fifty_tile_reuse(self):
        arts = [{"id": index, "style": "alternate", "url": "https://example.com/%d" % index}
                for index in range(50)]
        self.window.game = self.game
        self.window.editor.set_game(self.game)
        self.window.gallery.set_art(arts)
        self.app.processEvents()
        self.assertEqual(len(self.window.gallery.tiles), 50)
        self.window.resize(1490, 900)
        self.app.processEvents()
        self.assertEqual(self.window.gallery.columns, 5)
        self.assertEqual(self.window.gallery.horizontalScrollBarPolicy(),
                         Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.window.gallery.tiles[0].setFocus()
        with mock.patch.object(self.service, "image", return_value=self.art), \
             mock.patch.object(self.service, "preview", return_value=self.art):
            QTest.keyClick(self.window.gallery.tiles[0], Qt.Key.Key_Right)
            self.assertIs(self.window.gallery.selected_art, arts[1])
            self.wait(lambda: self.window.preview_path == str(self.art))
            self.window.navigate("Search")
            self.window.navigate("Library")
            self.assertIs(self.window.gallery.selected_art, arts[1])
            QTest.keyClick(self.window.gallery.tiles[1], Qt.Key.Key_Return)
        self.assertEqual(len(self.service.queue), 1)
        first_tile = self.window.gallery.tiles[0]
        for _ in range(3):
            self.window.gallery.set_art(arts)
            self.app.processEvents()
            self.assertEqual(len(self.window.gallery.tiles), 50)
        self.assertIn(first_tile, self.window.gallery.tiles)

    def test_stale_artwork_result_cannot_replace_new_game_and_empty_state_is_clear(self):
        newer = {"id": 2, "style": "alternate", "url": "https://example.com/new.png"}
        older = {"id": 1, "style": "alternate", "url": "https://example.com/old.png"}
        self.window.art_token = 2
        self.window.gallery.set_art([newer])
        self.window._art_loaded(1, [older])
        self.assertIs(self.window.gallery.tiles[0].art, newer)
        self.window._art_error(1, "Old network failure")
        self.assertIs(self.window.gallery.tiles[0].art, newer)
        self.window._art_loaded(2, [])
        self.assertEqual(len(self.window.gallery.tiles), 0)
        self.assertIn("No artwork found", self.window.editor.status.text())

    def test_platform_choice_saved_for_game_and_invalid_preview_disables_actions(self):
        self.window.game = self.game
        self.window.editor.set_game(self.game)
        self.window.editor.set_platform("ps4")
        self.window.platform_changed("ps4")
        saved = AppSettings(self.service.settings.path)
        self.assertEqual(saved.platform_choices["steam:220"], "ps4")
        self.window.editor.set_ready(False, True)
        self.assertFalse(self.window.editor.apply.isEnabled())
        self.assertFalse(self.window.editor.batch.isEnabled())
        self.assertFalse(self.window.editor.export.isEnabled())

    def test_settings_credential_actions_use_keyring_backend(self):
        self.window.navigate("Settings")
        self.window.save_preferences()
        self.window.api_key.setText("sample-secret")
        with mock.patch.object(cw.ArtworkClient, "verify_key", return_value=True), \
             mock.patch.object(cw, "save_api_key") as save, \
             mock.patch.object(cw, "load_api_key", return_value="sample-secret"):
            self.window.save_key()
            self.wait(lambda: save.call_count == 1 and not self.window.api_key.text())
            save.assert_called_once_with("sample-secret")
            self.window.verify_key()
            self.wait(lambda: "valid" in self.window.statusBar().currentMessage())
            self.window.delete_key()
            self.wait(lambda: save.call_count == 2)
            self.assertEqual(save.call_args.args[0], "")
        self.assertNotIn("sample-secret", self.service.settings.path.read_text(encoding="utf-8"))

    def test_local_import_works_without_local_file_source_option(self):
        self.assertEqual([self.window.editor.source.itemText(i) for i in range(self.window.editor.source.count())],
                         ["Steam CDN", "SteamGridDB"])
        self.window.game = self.game
        self.window.editor.set_game(self.game)
        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(str(self.art), "")), \
             mock.patch.object(self.service, "preview", return_value=self.art):
            self.window.import_image()
            self.wait(lambda: self.window.preview_path == str(self.art))
        self.assertTrue(self.window.local_image)
        self.assertEqual(self.window.current_item().source, "Local file")
        self.assertEqual(self.window.editor.source.currentIndex(), -1)
        with mock.patch.object(self.service, "artwork", return_value=[]):
            self.window.editor.source.setCurrentText("SteamGridDB")
            self.wait(lambda: not self.window.local_image)

    def test_backup_view_exports_previews_and_imports_current_artwork(self):
        steam = self.root / "steam"
        grid = steam / "userdata" / "111" / "config" / "grid"
        grid.mkdir(parents=True)
        original = grid / "220p.png"
        Image.new("RGB", (80, 120), "red").save(original)
        original_bytes = original.read_bytes()
        self.service.settings.account = "111"
        self.window.navigate("Backup")
        with mock.patch.object(self.service, "steam", return_value=str(steam)), \
             mock.patch.object(QFileDialog, "getExistingDirectory", return_value=str(self.root)):
            self.window.export_current_artwork()
            self.wait(lambda: "1 local covers exported" in self.window.backup_result.text())
        package = next(self.root.glob("CaseCovers-artwork-*"))
        Image.new("RGB", (80, 120), "blue").save(original)
        Image.new("RGB", (80, 120), "green").save(grid / "220p.jpg")
        with mock.patch.object(self.service, "steam", return_value=str(steam)), \
             mock.patch.object(QFileDialog, "getExistingDirectory", return_value=str(package)):
            self.window.choose_artwork_backup()
            self.wait(lambda: self.window.backup_table.rowCount() == 2 and
                      self.window.backup_import_button.isEnabled())
        self.assertIn("Overwrite", self.window.backup_table.item(0, 2).text())
        self.assertEqual(self.window.backup_table.item(1, 2).text(), "Remove conflict")
        self.assertIsNotNone(self.window.backup_image.original)
        with mock.patch.object(self.service, "steam", return_value=str(steam)), \
             mock.patch.object(sc, "steam_running", return_value=False), \
             mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Ok):
            self.window.import_selected_backup()
            self.wait(lambda: "1 files imported" in self.window.backup_result.text())
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertFalse((grid / "220p.jpg").exists())
        self.assertTrue(sc.list_backups(str(steam), "111"))

    def test_replacing_large_artwork_grids_does_not_crash_qt(self):
        # A child process keeps a native access violation from killing the suite.
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
                   CASE_COVERS_LOG_DIR=str(self.root / "logs"))
        result = subprocess.run(
            [sys.executable, "-c",
             "from batch_diagnostics import run; raise SystemExit(run(30, grid=True, grid_only=True))"],
            cwd=Path(__file__).resolve().parent.parent, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=45,
        )
        log_path = self.root / "logs" / "native-crash.log"
        details = result.stdout + (log_path.read_text(encoding="utf-8") if log_path.exists() else "")
        self.assertEqual(result.returncode, 0, details)

    def test_reused_tile_selects_new_artwork(self):
        selected = []
        grid = ArtworkGrid(selected.append)
        first = {"id": 1, "url": "https://example.com/first.png"}
        second = {"id": 2, "url": "https://example.com/second.png"}
        grid.set_art([first])
        tile = grid.tiles[0]
        grid.set_art([second])
        self.assertIs(grid.tiles[0], tile)
        QTest.mouseClick(tile, Qt.MouseButton.LeftButton)
        self.assertEqual(selected, [second])
        grid.close()


if __name__ == "__main__":
    unittest.main()
