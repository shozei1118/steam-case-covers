"""Filtering keeps the verified Steam IDs paired with their original titles."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import gui
from gui import matching_shortcuts


class ShortcutSearch(unittest.TestCase):
    def setUp(self):
        self.long_name = "The Extremely Long Adventure of the Clockwork Kingdom: Definitive Edition " * 3
        self.options = [{"name": "Game %04d" % n, "id": 3_000_000_000 + n} for n in range(1000)]
        self.options.append({"name": self.long_name, "id": 4_000_000_001})

    def test_many_shortcuts_keep_their_order_and_ids(self):
        self.assertEqual(matching_shortcuts(self.options, ""), self.options)
        self.assertEqual(matching_shortcuts(self.options, "GAME 0999"), [self.options[999]])
        self.assertEqual(matching_shortcuts(self.options, "4000000001"), [self.options[-1]])

    def test_long_title_is_found_without_changing_its_id(self):
        found = matching_shortcuts(self.options, "clockWORK kingDOM")
        self.assertEqual(found, [self.options[-1]])
        self.assertEqual(found[0]["name"], self.long_name)
        self.assertEqual(matching_shortcuts(self.options, "not present"), [])

    def test_manual_selection_uses_verified_shortcut_id(self):
        selected = []
        statuses = []
        current = []
        app = SimpleNamespace(_acc=lambda: "account",
                              manual_steam_id=SimpleNamespace(set=selected.append),
                              _manual_status=lambda message: statuses.append(message),
                              _manual_update_actions=lambda: None,
                              current_cover_group=SimpleNamespace(pack=lambda **_kw: None),
                              manual_preview=SimpleNamespace(master=object()),
                              current_cover=SimpleNamespace(configure=lambda **_kw: None),
                              _load_current_steam_cover=lambda *args, **kw: current.append((args, kw)))
        with patch.object(gui.sc, "steam_dir", return_value="steam"), \
             patch.object(gui.cw, "list_shortcuts", return_value=self.options) as read, \
             patch.object(gui, "ShortcutPicker") as picker:
            picker.return_value.show.return_value = self.options[-1]["id"]
            gui.App._manual_choose_shortcut(app)
        read.assert_called_once_with("steam", "account")
        picker.assert_called_once_with(app, self.options)
        self.assertEqual(selected, ["4000000001"])
        self.assertEqual(statuses, ["Steam shortcut ID selected: 4000000001"])
        self.assertEqual(current, [((4_000_000_001,), {"allow_cdn": False})])

        with patch.object(gui.sc, "steam_dir", return_value="steam"), \
             patch.object(gui.cw, "list_shortcuts", return_value=self.options), \
             patch.object(gui, "ShortcutPicker") as picker:
            picker.return_value.show.return_value = None
            gui.App._manual_choose_shortcut(app)
        self.assertEqual(selected, ["4000000001"], "Cancel must retain the previous selection")


if __name__ == "__main__":
    unittest.main()
