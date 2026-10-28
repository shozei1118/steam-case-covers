"""The Steam library and manual search feed one editor and one backup path."""
import queue
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

import cover_workflow as cw
import gui
import steamcase as sc


class EditorWorkflow(unittest.TestCase):
    def make_app(self):
        try:
            with mock.patch.object(gui.App, "refresh_steam_games"):
                app = gui.App()
        except gui.tk.TclError as exc:
            self.skipTest("Tk display unavailable: %s" % exc)
        self.addCleanup(app.destroy)
        app.update()
        return app

    def wait_for(self, app, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            app.update()
            time.sleep(.02)
        self.assertTrue(condition())

    def test_library_filter_identity_and_exact_art_source(self):
        app = self.make_app()
        app.steam_games = [(220, "Half-Life 2"), (440, "Team Fortress 2")]
        app.steam_game_query.set("HALF")
        app.update()
        self.assertEqual(app.filtered_steam_games, [(220, "Half-Life 2")])
        with mock.patch.object(app, "_load_current_steam_cover") as current, \
             mock.patch.object(app, "_load_art_for_selected") as artwork:
            app.steam_game_list.selection_set(0)
            app._pick_library_game()
        self.assertEqual(app.manual_game, {"id": 220, "name": "Half-Life 2", "source": "steam"})
        self.assertEqual(app.manual_steam_id.get(), "220")
        self.assertEqual(app.manual_verified_steam_id, 220)
        self.assertEqual(app.manual_platform.get(), "Steam")
        current.assert_called_once_with(220)
        artwork.assert_called_once()

        calls = []
        client = SimpleNamespace(grids_steam=lambda appid: calls.append(appid) or
                                 [{"id": 7, "url": "https://example.com/art.png"}])
        app._manual_client = lambda key=None: client
        app.manual_source.set("SteamGridDB")
        app._manual_source_changed()
        self.wait_for(app, lambda: calls == [220] and len(app.manual_art) == 1)
        self.assertEqual(app.manual_steam_id.get(), "220")

    def test_library_worker_resolves_owned_games_without_blocking_gui(self):
        app = self.make_app()
        app.library_path = "userdata.json"
        with mock.patch.object(sc, "steam_dir", return_value="steam"), \
             mock.patch.object(sc, "load_games", return_value={220: "Half-Life 2", 440: None}) as load, \
             mock.patch.object(sc, "list_games", return_value=[(220, "Half-Life 2"), (440, "Team Fortress 2")]):
            app.refresh_steam_games()
            self.wait_for(app, lambda: len(app.steam_games) == 2)
        load.assert_called_once_with("steam", "userdata.json")
        self.assertEqual([item[0] for item in app.steam_games], [220, 440])

    def test_manual_search_uses_the_same_editor_without_fuzzy_choice(self):
        app = self.make_app()
        app._editor_mode("search")
        app.manual_source.set("SteamGridDB")
        app.manual_term.set("Example")
        app._manual_client = lambda key=None: SimpleNamespace(search=lambda term, source: [
            {"id": 7, "name": "Example", "source": "steamgriddb"},
            {"id": 8, "name": "Example II", "source": "steamgriddb"}])
        app._manual_search()
        self.wait_for(app, lambda: len(app.manual_results) == 2)
        self.assertIsNone(app.manual_game)
        with mock.patch.object(app, "_load_art_for_selected"):
            app.game_list.selection_set(1)
            app._manual_pick_game()
        self.assertEqual(app.manual_game["id"], 8)
        self.assertIsNone(app.manual_verified_steam_id)

    def test_queue_replaces_a_game_and_allows_edit_and_remove(self):
        app = self.make_app()
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "source.png"
            Image.new("RGB", (600, 900), "blue").save(image)
            app.manual_game = {"id": 220, "name": "Half-Life 2", "source": "steam"}
            app.manual_verified_steam_id = 220
            app.manual_steam_id.set("220")
            app.manual_image = str(image)
            app.manual_preview_path = str(image)
            app._manual_add()
            self.assertEqual(len(app.manual_queue), 1)
            self.assertEqual(app.manual_queue[0]["steam_id"], 220)
            app.manual_platform.set("PlayStation 4")
            app._manual_add()
            self.assertEqual(len(app.manual_queue), 1, "A game has only one queued cover")
            self.assertEqual(app.manual_queue[0]["platform"], "ps4")
            with mock.patch.object(app, "_select_game") as select, \
                 mock.patch.object(app, "_manual_prepare_preview"):
                app._queue_edit()
            select.assert_called_once()
            self.assertEqual(app.queue_edit_key, "steam:220")
            app._queue_remove()
            self.assertFalse(app.manual_queue)
            self.assertIsNone(app.queue_edit_key)

    def test_automatic_covers_join_the_same_queue(self):
        app = self.make_app()
        with tempfile.TemporaryDirectory() as temp:
            cover = Path(temp) / "Half-Life_2_220.png"
            Image.new("RGBA", (600, 900), "red").save(cover)
            app.steam_games = [(220, "Half-Life 2")]
            app.finish_make({"files": [str(cover)], "ok": 1, "missing": [], "failed": [],
                             "cancelled": False})
            self.assertEqual(len(app.manual_queue), 1)
            self.assertEqual(app.manual_queue[0]["file"], str(cover))
            self.assertEqual(app.manual_queue[0]["name"], "Half-Life 2")
            self.assertEqual(app.btn_apply.cget("state"), "normal")

    def test_two_queued_games_apply_once_and_restore_together(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            steam = root / "steam"
            grid = steam / "userdata" / "111" / "config" / "grid"
            grid.mkdir(parents=True)
            (steam / "config").mkdir()
            old_220, old_440 = grid / "220p.png", grid / "440p.png"
            old_220.write_bytes(b"previous 220")
            old_440.write_bytes(b"previous 440")
            source1, source2 = root / "one.png", root / "two.png"
            Image.new("RGB", (600, 900), "red").save(source1)
            Image.new("RGB", (600, 900), "blue").save(source2)
            cache = root / "cache"
            cache.mkdir()
            app = SimpleNamespace(events=queue.Queue(), _acc=lambda: "111",
                                  covers_dir=str(root / "covers"))
            items = [{"key": "steam:220", "name": "Half-Life 2", "platform": "ps4",
                      "image": str(source1), "steam_id": 220},
                     {"key": "steam:440", "name": "Team Fortress 2", "platform": "steam",
                      "image": str(source2), "steam_id": 440}]
            with mock.patch.object(sc, "steam_dir", return_value=str(steam)), \
                 mock.patch.object(cw, "cache_dir", return_value=cache), \
                 mock.patch.object(sc, "steam_running", side_effect=[True, False]), \
                 mock.patch.object(sc, "close_steam", return_value=True) as close, \
                 mock.patch.object(sc, "start_steam") as start:
                gui.App._step3_worker(app, "apply", True, items=items)
                events = list(app.events.queue)
                self.assertTrue(any(event[0] == "step3_done" and event[2] == "apply"
                                    for event in events), events)
                self.assertNotEqual(old_220.read_bytes(), b"previous 220")
                self.assertNotEqual(old_440.read_bytes(), b"previous 440")
                self.assertEqual(len(sc.list_backups(str(steam), "111")), 1)
                self.assertTrue(any(event[0] == "queue_status" and
                                    event[1].get("steam:220") == "Applied" and
                                    event[1].get("steam:440") == "Applied" for event in events))
                close.assert_called_once()
                start.assert_called_once()
                self.assertFalse(list(cache.iterdir()), "Temporary staging files are removed")
                gui.App._step3_worker(app, "restore", False)
            self.assertEqual(old_220.read_bytes(), b"previous 220")
            self.assertEqual(old_440.read_bytes(), b"previous 440")
            self.assertFalse(sc.list_backups(str(steam), "111"))

    def test_bad_queued_image_fails_before_steam_closes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            steam = root / "steam"
            grid = steam / "userdata" / "111" / "config" / "grid"
            grid.mkdir(parents=True)
            (steam / "config").mkdir()
            old = grid / "220p.png"
            old.write_bytes(b"previous")
            app = SimpleNamespace(events=queue.Queue(), _acc=lambda: "111",
                                  covers_dir=str(root / "covers"))
            items = [{"key": "steam:220", "name": "Broken", "platform": "steam",
                      "image": str(root / "missing.png"), "steam_id": 220}]
            with mock.patch.object(sc, "steam_dir", return_value=str(steam)), \
                 mock.patch.object(sc, "steam_running", return_value=True) as running, \
                 mock.patch.object(sc, "close_steam") as close:
                gui.App._step3_worker(app, "apply", True, items=items)
            self.assertFalse(running.called)
            close.assert_not_called()
            self.assertEqual(old.read_bytes(), b"previous")
            self.assertFalse(sc.list_backups(str(steam), "111"))
            self.assertTrue(any(event[0] == "step3_error" for event in app.events.queue))

    def test_removed_shortcut_fails_before_steam_closes(self):
        with tempfile.TemporaryDirectory() as temp:
            app = SimpleNamespace(events=queue.Queue(), _acc=lambda: "111", covers_dir=temp)
            item = {"key": "steam:4000000001", "name": "Non-Steam game", "platform": "steam",
                    "image": "unused.png", "steam_id": 4_000_000_001,
                    "game": {"id": 7, "name": "Non-Steam game", "source": "steamgriddb"}}
            with mock.patch.object(sc, "steam_dir", return_value=temp), \
                 mock.patch.object(cw, "list_shortcuts", return_value=[]) as shortcuts, \
                 mock.patch.object(sc, "steam_running") as running, \
                 mock.patch.object(sc, "close_steam") as close:
                gui.App._step3_worker(app, "apply", True, items=[item])
            shortcuts.assert_called_once_with(temp, "111")
            running.assert_not_called()
            close.assert_not_called()
            self.assertTrue(any(event[0] == "step3_error" and "no longer exists" in event[1]
                                for event in app.events.queue))

    def test_verified_shortcut_joins_the_same_apply_and_restore_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            steam = root / "steam"
            config = steam / "userdata" / "111" / "config"
            grid = config / "grid"
            grid.mkdir(parents=True)
            (steam / "config").mkdir()
            identifier = 0xC0000001
            entry = (b"\x02appid\0" + identifier.to_bytes(4, "little") +
                     b"\x01AppName\0Example Shortcut\0" + b"\x08")
            (config / "shortcuts.vdf").write_bytes(b"\x00shortcuts\0\x000\0" + entry + b"\x08\x08")
            source = root / "source.png"
            Image.new("RGB", (600, 900), "green").save(source)
            item = {"key": "steam:%d" % identifier, "name": "Example Shortcut", "platform": "ps4",
                    "image": str(source), "steam_id": identifier,
                    "game": {"id": None, "name": "Example Shortcut", "source": "local"}}
            app = SimpleNamespace(events=queue.Queue(), _acc=lambda: "111", covers_dir=str(root / "covers"))
            with mock.patch.object(sc, "steam_dir", return_value=str(steam)), \
                 mock.patch.object(sc, "steam_running", return_value=False):
                gui.App._step3_worker(app, "apply", False, items=[item])
                self.assertTrue((grid / ("%dp.png" % identifier)).is_file())
                self.assertTrue(any(event[0] == "step3_done" for event in app.events.queue))
                gui.App._step3_worker(app, "restore", False)
            self.assertFalse((grid / ("%dp.png" % identifier)).exists())

    def test_write_failure_rolls_back_both_and_restarts_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            steam = root / "steam"
            grid = steam / "userdata" / "111" / "config" / "grid"
            grid.mkdir(parents=True)
            (steam / "config").mkdir()
            for appid in (220, 440):
                (grid / ("%dp.png" % appid)).write_bytes(b"old %d" % appid)
            items = []
            for appid in (220, 440):
                image = root / ("%d.png" % appid)
                Image.new("RGB", (600, 900), "red").save(image)
                items.append({"key": "steam:%d" % appid, "name": "Game %d" % appid,
                              "platform": "steam", "image": str(image), "steam_id": appid})
            app = SimpleNamespace(events=queue.Queue(), _acc=lambda: "111",
                                  covers_dir=str(root / "covers"))
            original = sc._safe_copy
            calls = []

            def fail_second(source, dest):
                calls.append(dest)
                if len(calls) == 2:
                    raise OSError("disk full")
                return original(source, dest)

            with mock.patch.object(sc, "steam_dir", return_value=str(steam)), \
                 mock.patch.object(sc, "steam_running", return_value=True), \
                 mock.patch.object(sc, "close_steam", return_value=True) as close, \
                 mock.patch.object(sc, "start_steam") as start, \
                 mock.patch.object(sc, "_safe_copy", side_effect=fail_second):
                gui.App._step3_worker(app, "apply", True, items=items)
            close.assert_called_once()
            start.assert_called_once()
            for appid in (220, 440):
                self.assertEqual((grid / ("%dp.png" % appid)).read_bytes(), b"old %d" % appid)
            self.assertFalse(sc.list_backups(str(steam), "111"))
            self.assertTrue(any(event[0] == "step3_error" and "Nothing was changed" in event[1]
                                for event in app.events.queue))


if __name__ == "__main__":
    unittest.main()
