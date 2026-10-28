"""Manual artwork workflow without live APIs or a Steam installation."""
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from PIL import Image

import cover_workflow as cw
import steamcase as sc
from platform_catalog import load_catalog


class Response(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body))}


class Opener:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def open(self, request, timeout=20):
        self.calls.append((request.full_url, request.get_header("Authorization")))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return Response(answer)


def payload(data):
    return json.dumps({"success": True, "data": data}).encode()


class Workflow(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def image(self):
        path = self.root / "source.webp"
        Image.new("RGB", (600, 900), "#dc4534").save(path)
        return path

    def test_search_grid_selection_preview_cache_and_batch_without_steam(self):
        picture = self.image().read_bytes()
        opener = Opener([
            payload([{"id": 7, "name": "Example", "types": ["game"], "verified": True},
                     {"id": 8, "name": "Example II", "types": [], "verified": False}]),
            payload([{"id": 55, "url": "https://cdn2.steamgriddb.com/example.webp",
                      "thumb": "https://cdn2.steamgriddb.com/thumb.webp", "style": "alternate"}]),
            picture,
        ])
        client = cw.ArtworkClient("secret", self.root / "cache", opener)
        games = client.search("Example", "steamgriddb")
        self.assertEqual([game["id"] for game in games], [7, 8])
        self.assertTrue(all(game["source"] == "steamgriddb" for game in games))
        self.assertEqual(len(opener.calls), 1)  # No automatic artwork request or choice.
        grids = client.grids(games[0]["id"])
        self.assertEqual(grids[0]["id"], 55)
        self.assertEqual(client.grids(7), grids)
        selected = client.image(grids[0]["url"])
        self.assertEqual(client.image(grids[0]["url"]), selected)
        self.assertEqual(len(opener.calls), 3)
        self.assertTrue(all(auth == "Bearer secret" for _, auth in opener.calls[:2]))
        items = [{"name": "Example", "platform": "ps4", "image": str(selected)},
                 {"name": "Example II", "platform": "switch_2", "image": str(selected)}]
        exported, errors = cw.export_many(items, self.root / "out")
        self.assertFalse(errors)
        self.assertEqual(len(exported), 2)
        with Image.open(exported[0]) as cover:
            self.assertEqual(cover.size, (600, 900))
            self.assertTrue(all(abs(a - b) <= 3 for a, b in
                                zip(cover.getpixel((300, 400))[:3], (220, 69, 52))))
            self.assertEqual(cover.getpixel((300, 400))[3], 255)
        self.assertFalse(sc.find_covers(self.root / "out"))  # No invented Steam ID.

    def test_steam_search_and_default_cdn_candidates(self):
        opener = Opener([json.dumps({"items": [{"id": 220, "name": "Half-Life 2"}]}).encode()])
        client = cw.ArtworkClient(directory=self.root, opener=opener)
        self.assertEqual(client.search("Half-Life", "steam"),
                         [{"id": 220, "name": "Half-Life 2", "source": "steam"}])
        with mock.patch.object(sc, "store_items", return_value={220: {}}):
            art = client.steam_art(220)
        self.assertTrue(art[0]["url"].startswith("https://"))
        self.assertIn("220", art[0]["url"])

    def test_steamgrid_grids_use_exact_steam_id(self):
        opener = Opener([payload([{"id": 55, "url": "https://cdn2.steamgriddb.com/art.png"}])])
        client = cw.ArtworkClient("secret", self.root, opener)
        self.assertEqual(client.grids_steam(220)[0]["id"], 55)
        self.assertIn("/grids/steam/220?", opener.calls[0][0])

    def test_current_steam_cover_respects_override_priority(self):
        steam = self.root / "steam"
        grid = steam / "userdata" / "111" / "config" / "grid"
        grid.mkdir(parents=True)
        png = grid / "220p.png"
        jpg = grid / "220p.jpg"
        Image.new("RGB", (600, 900), "red").save(png)
        Image.new("RGB", (600, 900), "blue").save(jpg)
        self.assertEqual(cw.current_steam_cover(str(steam), "111", 220), jpg)
        jpg.unlink()
        self.assertEqual(cw.current_steam_cover(str(steam), "111", 220), png)

    def test_key_rate_limit_and_invalid_image(self):
        client = cw.ArtworkClient(directory=self.root)
        with self.assertRaisesRegex(sc.SteamcaseError, "API key"):
            client.search("Example", "steamgriddb")
        error = urllib.error.HTTPError(cw.SGDB_API, 429, "limit", {"Retry-After": "30"}, None)
        client = cw.ArtworkClient("secret", self.root, Opener([error]))
        with self.assertRaisesRegex(sc.SteamcaseError, "30"):
            client.search("Example", "steamgriddb")
        client = cw.ArtworkClient("secret", self.root, Opener([b"not an image"]))
        with self.assertRaisesRegex(sc.SteamcaseError, "supported image"):
            client.image("https://cdn2.steamgriddb.com/art.png")

    def test_key_storage_uses_credential_store(self):
        fake = mock.Mock()
        fake.get_password.return_value = "secret"
        with mock.patch.dict("sys.modules", {"keyring": fake}):
            cw.save_api_key(" secret ")
            self.assertEqual(cw.load_api_key(), "secret")
            cw.save_api_key("")
        fake.set_password.assert_called_once_with(cw.KEY_SERVICE, cw.KEY_USER, "secret")
        fake.delete_password.assert_called_once_with(cw.KEY_SERVICE, cw.KEY_USER)

    def test_all_platforms_export_and_steam_apply_restore(self):
        source = self.image()
        platforms = load_catalog()["platforms"]
        self.assertEqual(len(platforms), 29)
        for platform in platforms:
            with self.subTest(platform=platform["id"]):
                path = cw.export_one(source, platform["id"], "Example", self.root / "all")
                with Image.open(path) as image:
                    self.assertEqual(image.size, (600, 900))
        steam = self.root / "steam"
        grid = steam / "userdata" / "111" / "config" / "grid"
        grid.mkdir(parents=True)
        (steam / "config").mkdir()
        current = grid / "220p.png"
        current.write_bytes(b"old art")
        cover = cw.export_one(source, "ps4", "Example", self.root / "all", steam_id=220)
        result = sc.apply_covers(str(steam), str(self.root / "all"), files=[str(cover)])
        self.assertEqual(result["applied"], 1)
        self.assertEqual(result["changed_ids"], [220])
        self.assertEqual(current.read_bytes(), cover.read_bytes())
        sc.restore_backup(str(steam), result["backup"])
        self.assertEqual(current.read_bytes(), b"old art")

    def test_batch_export_copies_automatic_cover_without_second_frame(self):
        automatic = cw.export_one(self.image(), "steam", "Automatic", self.root / "auto", 220)
        original = automatic.read_bytes()
        items = [{"name": "Automatic", "platform": "steam", "steam_id": 220,
                  "file": str(automatic), "image": None},
                 {"name": "Manual", "platform": "ps4", "image": str(self.image())}]
        done, errors = cw.export_many(items, self.root / "out")
        self.assertFalse(errors)
        self.assertEqual(len(done), 2)
        self.assertEqual(done[0].read_bytes(), original)

    def test_existing_shortcut_id_is_read_from_steam_record(self):
        steam = self.root / "steam"
        config = steam / "userdata" / "111" / "config"
        config.mkdir(parents=True)
        (steam / "config").mkdir()
        identifier = 0xC0000001
        entry = (b"\x02appid\0" + identifier.to_bytes(4, "little") +
                 b"\x01AppName\0Example Shortcut\0" + b"\x08")
        data = b"\x00shortcuts\0\x000\0" + entry + b"\x08\x08"
        (config / "shortcuts.vdf").write_bytes(data)
        self.assertEqual(cw.list_shortcuts(str(steam)), [{"id": identifier, "name": "Example Shortcut"}])
        cover = cw.export_one(self.image(), "game_boy_color", "Example Shortcut", self.root / "out", identifier)
        self.assertEqual(sc.appid_of(str(cover)), str(identifier))


if __name__ == "__main__":
    unittest.main()
