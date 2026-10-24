"""Qt's GUI-independent workflows keep the existing Steam backup transaction."""
import tempfile
import json
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import cover_workflow as cw
import steamcase as sc
from case_service import AppSettings, CaseService, CoverItem, Game


class CaseServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.steam = self.root / "steam"
        self.grid = self.steam / "userdata" / "111" / "config" / "grid"
        self.grid.mkdir(parents=True)
        (self.steam / "config").mkdir()
        self.cache = self.root / "cache"
        self.settings = AppSettings(self.root / "settings.json")
        self.settings.account = "111"
        self.service = CaseService(self.settings, self.root / "covers")

    def image(self, name):
        path = self.root / name
        Image.new("RGB", (600, 900), "blue").save(path)
        return str(path)

    def item(self, appid, name=None):
        name = name or "Game %s" % appid
        return CoverItem(Game(name, "steam", appid, appid, True), "steam", self.image("art-%s.png" % appid))

    def test_library_includes_exact_games_and_verified_shortcuts(self):
        with mock.patch.object(sc, "steam_dir", return_value=str(self.steam)), \
             mock.patch.object(sc, "load_games", return_value={220: "Half-Life 2"}), \
             mock.patch.object(sc, "list_games", return_value=[(220, "Half-Life 2")]), \
             mock.patch.object(cw, "list_shortcuts", return_value=[{"name": "Custom", "id": 0xC0000001}]):
            games = self.service.library()
        self.assertEqual({game.source for game in games}, {"steam", "shortcut"})
        self.assertTrue(all(game.verified for game in games))

    def test_missing_saved_game_list_falls_back_to_installed_steam_games(self):
        apps = self.steam / "steamapps"
        apps.mkdir()
        (apps / "appmanifest_220.acf").write_text('"AppState" { "appid" "220" "name" "Half-Life 2" }', encoding="utf-8")
        self.settings.userdata = str(self.root / "deleted-user.json")
        self.settings.save()
        restored = CaseService(AppSettings(self.settings.path), self.root / "covers")
        with mock.patch.object(sc, "steam_dir", return_value=str(self.steam)), \
             mock.patch.object(sc, "list_games", side_effect=lambda games: list(games.items())), \
             mock.patch.object(cw, "list_shortcuts", return_value=[]):
            games = restored.library()
        self.assertEqual([(game.steam_id, game.name) for game in games], [(220, "Half-Life 2")])
        self.assertIsNone(restored.library_json())

    def test_saved_userdata_json_adds_owned_games_and_automatic_uses_it(self):
        library = self.root / "userdata.json"
        library.write_text(json.dumps({"rgOwnedApps": [440]}), encoding="utf-8")
        self.settings.userdata = str(library)
        with mock.patch.object(sc, "steam_dir", return_value=str(self.steam)), \
             mock.patch.object(sc, "list_games", side_effect=lambda games, **_kwargs: [(appid, name or "Owned game") for appid, name in games.items()]), \
             mock.patch.object(cw, "list_shortcuts", return_value=[]), \
             mock.patch.object(sc, "make_covers", return_value={"files": [], "ok": 0, "missing": [], "failed": []}) as make:
            self.assertEqual([game.steam_id for game in self.service.library()], [440])
            self.service.automatic()
        self.assertIn(440, make.call_args.args[0])

    def test_multiple_libraries_accounts_owned_games_and_shortcut_ids(self):
        base_apps = self.steam / "steamapps"
        base_apps.mkdir()
        other = self.root / "Second Library"
        other_apps = other / "steamapps"
        other_apps.mkdir(parents=True)
        (base_apps / "libraryfolders.vdf").write_text(
            '"libraryfolders" { "1" { "path" "%s" } }' % str(other).replace("\\", "\\\\"),
            encoding="utf-8")
        (base_apps / "appmanifest_220.acf").write_text(
            '"AppState" { "appid" "220" "name" "Half-Life 2" }', encoding="utf-8")
        (other_apps / "appmanifest_570.acf").write_text(
            '"AppState" { "appid" "570" "name" "Dota 2" }', encoding="utf-8")
        # A damaged manifest must not hide the healthy games.
        (other_apps / "appmanifest_999.acf").write_text('"appid" "invalid"', encoding="utf-8")
        library = self.root / "userdata.json"
        library.write_text(json.dumps({"rgOwnedApps": [220, 440]}), encoding="utf-8")
        self.settings.userdata = str(library)
        second_config = self.steam / "userdata" / "222" / "config"
        second_config.mkdir(parents=True)
        shortcut_id = 0xC0000001
        entry = (b"\x02appid\0" + shortcut_id.to_bytes(4, "little") +
                 b"\x01AppName\0Second account shortcut\0" + b"\x08")
        (second_config / "shortcuts.vdf").write_bytes(b"\x00shortcuts\0\x000\0" + entry + b"\x08\x08")
        self.settings.account = "222"
        with mock.patch.object(sc, "steam_dir", return_value=str(self.steam)), \
             mock.patch.object(sc, "list_games", return_value=[(440, "Portal 2")]) as lookup:
            games = self.service.library()
        by_id = {game.steam_id: game for game in games}
        self.assertEqual(set(by_id), {220, 440, 570, shortcut_id})
        self.assertEqual({appid for appid, game in by_id.items() if game.installed}, {220, 570})
        self.assertEqual(by_id[shortcut_id].source, "shortcut")
        self.assertEqual(by_id[440].name, "Portal 2")
        lookup.assert_called_once_with({440: None})
        self.settings.account = "111"
        with mock.patch.object(sc, "steam_dir", return_value=str(self.steam)), \
             mock.patch.object(sc, "list_games", return_value=[(440, "Portal 2")]):
            self.assertNotIn(shortcut_id, {game.steam_id for game in self.service.library()})

    def test_imported_unknown_ids_do_not_count_as_games(self):
        library = self.root / "userdata.json"
        library.write_text(json.dumps({"rgOwnedApps": [440, 570]}), encoding="utf-8")
        self.settings.userdata = str(library)
        with mock.patch.object(sc, "steam_dir", return_value=str(self.steam)), \
             mock.patch.object(sc, "store_items", return_value={440: {"name": "Portal 2", "type": 0}}), \
             mock.patch.object(cw, "list_shortcuts", return_value=[]):
            games = self.service.library()
        self.assertEqual([(game.steam_id, game.name) for game in games], [(440, "Portal 2")])
        self.assertIn("2 additional app IDs, 1 titled game(s)", self.service.last_library_warning)

    def test_platform_choice_persists_separately_from_temporary_artwork(self):
        game = Game("Half-Life 2", "steam", 220, 220, True)
        self.settings.default_source = "SteamGridDB"
        self.service.remember_platform(game, "ps4")
        restored = CaseService(AppSettings(self.settings.path), self.root / "covers")
        self.assertEqual(restored.platform_for(game), "ps4")
        self.assertEqual(restored.default_source(game), "SteamGridDB")
        self.assertEqual(restored.default_source(Game("Other", "steamgriddb", 7)), "SteamGridDB")
        self.assertFalse(hasattr(restored.settings, "image_path"))
        self.assertNotIn("api_key", self.settings.path.read_text(encoding="utf-8"))

    def test_unreadable_saved_list_keeps_installed_games_and_no_account_is_required(self):
        apps = self.steam / "steamapps"
        apps.mkdir()
        (apps / "appmanifest_220.acf").write_text(
            '"AppState" { "appid" "220" "name" "Half-Life 2" }', encoding="utf-8")
        (self.steam / "userdata" / "111").rename(self.steam / "unused-account")
        damaged = self.root / "userdata.json"
        damaged.write_text("{not valid JSON", encoding="utf-8")
        self.settings.userdata = str(damaged)
        with mock.patch.object(sc, "steam_dir", return_value=str(self.steam)):
            games = self.service.library()
        self.assertEqual([game.steam_id for game in games], [220])
        self.assertTrue(games[0].installed)
        self.assertIn("could not be read", self.service.last_library_warning)

    def test_invalid_settings_use_safe_defaults(self):
        self.settings.path.write_text("[]", encoding="utf-8")
        self.assertEqual(AppSettings(self.settings.path).default_source, "Automatic")
        self.settings.path.write_text(json.dumps({"default_source": "Local file",
                                                  "restart_steam": "false",
                                                  "export_dir": [],
                                                  "account": "../../other",
                                                  "platform_choices": {"steam:220": "missing", "steam:440": []}}),
                                      encoding="utf-8")
        clean = AppSettings(self.settings.path)
        self.assertEqual(clean.default_source, "Automatic")
        self.assertTrue(clean.restart_steam)
        self.assertEqual(clean.account, None)
        self.assertEqual(clean.platform_choices, {})

    def test_direct_and_batch_apply_share_one_backup_and_restart(self):
        for appid in (220, 440):
            (self.grid / ("%sp.png" % appid)).write_bytes(b"old cover")
        one, two = self.item(220), self.item(440)
        with mock.patch.object(sc, "steam_dir", return_value=str(self.steam)), \
             mock.patch.object(cw, "cache_dir", return_value=self.cache), \
             mock.patch.object(sc, "steam_running", return_value=True), \
             mock.patch.object(sc, "close_steam", return_value=True) as close, \
             mock.patch.object(sc, "start_steam") as start:
            result = self.service.apply_items([one, two])
            self.assertEqual(result["changed_ids"], [220, 440])
            close.assert_called_once()
            start.assert_called_once()
            self.assertEqual(len(sc.list_backups(str(self.steam), "111")), 1)
            self.assertNotEqual((self.grid / "220p.png").read_bytes(), b"old cover")
            self.service.restore()
        self.assertEqual((self.grid / "220p.png").read_bytes(), b"old cover")
        self.assertEqual((self.grid / "440p.png").read_bytes(), b"old cover")

    def test_bad_batch_cover_fails_before_steam_closes(self):
        first = self.item(220)
        bad = CoverItem(Game("Broken", "steam", 440, 440, True), "steam", str(self.root / "missing.png"))
        with mock.patch.object(sc, "steam_dir", return_value=str(self.steam)), \
             mock.patch.object(cw, "cache_dir", return_value=self.cache), \
             mock.patch.object(sc, "steam_running") as running, \
             mock.patch.object(sc, "close_steam") as close:
            with self.assertRaises(sc.SteamcaseError):
                self.service.apply_items([first, bad])
        running.assert_not_called()
        close.assert_not_called()
        self.assertFalse(sc.list_backups(str(self.steam), "111"))

    def test_shortcut_id_is_revalidated(self):
        shortcut = CoverItem(Game("Shortcut", "shortcut", 0xC0000001, 0xC0000001, True),
                             "steam", self.image("shortcut.png"))
        with mock.patch.object(sc, "steam_dir", return_value=str(self.steam)), \
             mock.patch.object(cw, "list_shortcuts", return_value=[]), \
             mock.patch.object(sc, "steam_running") as running:
            with self.assertRaisesRegex(sc.SteamcaseError, "no longer exists"):
                self.service.apply_items([shortcut])
        running.assert_not_called()

    def test_queue_replace_export_and_settings_never_store_key(self):
        one = self.item(220)
        self.service.add(one)
        self.service.add(CoverItem(one.game, "ps4", one.image))
        self.assertEqual(len(self.service.queue), 1)
        self.assertEqual(next(iter(self.service.queue.values())).platform, "ps4")
        files, errors = self.service.export_all(self.root / "export")
        self.assertEqual(errors, [])
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].is_file())
        self.settings.export_dir = str(self.root / "export")
        self.settings.save()
        self.assertNotIn("api_key", self.settings.path.read_text(encoding="utf-8"))

    def test_automatic_generation_joins_existing_edit_queue(self):
        generated = self.root / "Auto_220.png"
        Image.new("RGB", (600, 900), "green").save(generated)
        manual = self.item(220)
        self.service.add(manual)
        result = {"files": [str(generated)], "ok": 1, "missing": [], "failed": []}
        with mock.patch.object(sc, "steam_dir", return_value=str(self.steam)), \
             mock.patch.object(sc, "load_games", return_value={220: "Game 220"}), \
             mock.patch.object(sc, "list_games", return_value=[(220, "Game 220")]), \
             mock.patch.object(sc, "make_covers", return_value=result) as make:
            completed = self.service.automatic(skip_auto_art=True)
        make.assert_called_once()
        self.assertTrue(make.call_args.kwargs["skip_auto_art"])
        self.service.add_automatic(completed)
        self.assertEqual(len(self.service.queue), 1)
        self.assertEqual(self.service.queue[manual.key].image, manual.image,
                         "A manually edited cover takes precedence")

    def test_manual_search_keeps_ambiguous_results_unselected(self):
        results = [{"name": "Example", "id": 7, "source": "steamgriddb"},
                   {"name": "Example II", "id": 8, "source": "steamgriddb"}]
        with mock.patch.object(cw, "load_api_key", return_value="secret"), \
             mock.patch.object(cw.ArtworkClient, "search", return_value=results):
            games = self.service.search("Example", "SteamGridDB")
        self.assertEqual([game.id for game in games], [7, 8])
        self.assertTrue(all(not game.verified for game in games))


if __name__ == "__main__":
    unittest.main()
