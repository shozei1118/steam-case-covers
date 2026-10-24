"""GUI-independent application workflows shared by the Qt editor and CLI backends.

The service composes steamcase and cover_workflow; it does not implement another
Steam grid writer, image renderer, downloader, or credential store.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

import cover_workflow as cw
import steamcase as sc


@dataclass(frozen=True)
class Game:
    name: str
    source: str  # steam, shortcut, steamgriddb, local
    id: int | None = None
    steam_id: int | None = None
    verified: bool = False
    installed: bool = False


@dataclass(frozen=True)
class CoverItem:
    game: Game
    platform: str
    image: str | None = None  # selected portrait; never a composited cover
    file: str | None = None   # already composited automatic cover
    source: str = "Steam CDN"
    preview: str | None = None
    status: str = "Queued"

    @property
    def key(self):
        if self.game.steam_id and self.game.verified:
            return "steam:%d" % self.game.steam_id
        return "local:%s:%s" % (self.game.source, self.game.id or self.game.name)


class AppSettings:
    """Non-secret preferences. The SGDB key remains exclusively in keyring."""

    def __init__(self, path=None):
        self.path = Path(path) if path else cw.cache_dir().parent / "settings.json"
        self.export_dir = str(sc.default_covers_dir())
        self.default_source = "Automatic"
        self.restart_steam = True
        self.account = None
        self.userdata = None
        self.platform_choices = {}
        self.library_splitter_sizes = [310, 430]
        self.load()

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            if isinstance(data.get("export_dir"), str) and data["export_dir"].strip():
                self.export_dir = data["export_dir"]
            self.default_source = data.get("default_source") if data.get("default_source") in (
                "Automatic", "Steam CDN", "SteamGridDB") else "Automatic"
            if isinstance(data.get("restart_steam"), bool):
                self.restart_steam = data["restart_steam"]
            self.account = str(data["account"]) if isinstance(data.get("account"), str) and data["account"].isdigit() else None
            self.userdata = data["userdata"] if isinstance(data.get("userdata"), str) and data["userdata"] else None
            from platform_catalog import load_catalog
            platforms = {item["id"] for item in load_catalog()["platforms"]}
            choices = data.get("platform_choices")
            if isinstance(choices, dict):
                self.platform_choices = {key: value for key, value in choices.items()
                                         if isinstance(key, str) and len(key) <= 80 and
                                         isinstance(value, str) and value in platforms}
            sizes = data.get("library_splitter_sizes")
            if (isinstance(sizes, list) and len(sizes) == 2 and
                    all(type(value) is int and 100 <= value <= 10000 for value in sizes)):
                self.library_splitter_sizes = sizes
        except (OSError, ValueError, TypeError):
            pass

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"export_dir": self.export_dir, "default_source": self.default_source,
                "restart_steam": self.restart_steam, "account": self.account,
                "userdata": self.userdata, "platform_choices": self.platform_choices,
                "library_splitter_sizes": self.library_splitter_sizes}
        fd, temporary = tempfile.mkstemp(prefix=".settings-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


class CaseService:
    def __init__(self, settings=None, covers_dir=None):
        self.settings = settings or AppSettings()
        self.covers_dir = str(covers_dir or sc.default_covers_dir())
        self.queue: dict[str, CoverItem] = {}
        self.last_library_warning = None

    def steam(self):
        return sc.steam_dir()

    def account(self):
        return self.settings.account

    def platform_for(self, game):
        return self.settings.platform_choices.get("%s:%s" % (game.source, game.id or game.name), "steam")

    def remember_platform(self, game, platform):
        from platform_catalog import load_catalog
        if platform not in {item["id"] for item in load_catalog()["platforms"]}:
            return
        key = "%s:%s" % (game.source, game.id or game.name)
        if self.settings.platform_choices.get(key) != platform:
            self.settings.platform_choices[key] = platform
            self.settings.save()

    def library_json(self):
        """Use an optional saved game list only while its file still exists."""
        path = self.settings.userdata
        if path and not Path(path).is_file():
            logging.warning("Saved Steam game list is unavailable: %s", path)
            self.last_library_warning = "Saved game list not found. Installed Steam games are still available."
            return None
        return path

    def _steam_games(self, steam):
        self.last_library_warning = None
        library_json = self.library_json()
        try:
            return sc.load_games(steam, library_json)
        except sc.SteamcaseError as error:
            if library_json:
                logging.warning("Saved Steam game list could not be used (%s): %s", library_json, error)
                self.last_library_warning = "Saved game list could not be read. Installed Steam games are still available."
                return sc.load_games(steam)
            raise

    def library(self):
        steam = self.steam()
        games = self._steam_games(steam)
        installed = sc.installed_games(steam)
        named = {appid: name for appid, name in games.items() if name}
        unresolved = {appid: None for appid, name in games.items() if not name}
        if unresolved:
            # Imported rgOwnedApps contains app IDs, not verified game titles.
            # Missing Store metadata must not become a fictitious "Steam app" game.
            named.update(sc.list_games(unresolved))
        if self.last_library_warning is None and self.settings.userdata:
            self.last_library_warning = (
                "Imported userdata.json: %d additional app IDs, %d titled game(s) not installed locally. "
                "The file does not identify the selected Steam account; other IDs may be "
                "non-games or unavailable in Steam's catalog."
                % (len(games) - len(installed), len(named) - len(installed)))
        result = [Game(named[appid], "steam", int(appid),
                       int(appid), True, appid in installed)
                  for appid in games if appid in named]
        accounts = sc.list_accounts(steam)
        if accounts:
            selected = self.account()
            if selected not in {account for account, _label in accounts}:
                selected = accounts[0][0]
            known_ids = {game.steam_id for game in result}
            for item in cw.list_shortcuts(steam, selected):
                shortcut_id = int(item["id"])
                if shortcut_id not in known_ids:
                    result.append(Game(item["name"], "shortcut", shortcut_id, shortcut_id, True))
                    known_ids.add(shortcut_id)
        return sorted(result, key=lambda game: game.name.casefold())

    def search(self, term, source):
        client = cw.ArtworkClient(cw.load_api_key() if source == "SteamGridDB" else "")
        return [Game(item["name"], item["source"], int(item["id"]),
                     int(item["id"]) if item["source"] == "steam" else None,
                     item["source"] == "steam")
                for item in client.search(term, "steam" if source == "Steam CDN" else "steamgriddb")]

    def default_source(self, game):
        if game.source != "steam":
            return "SteamGridDB"
        if self.settings.default_source == "Automatic":
            return "Steam CDN"
        return self.settings.default_source

    def artwork(self, game, source):
        client = cw.ArtworkClient(cw.load_api_key() if source == "SteamGridDB" else "")
        if source == "Steam CDN":
            if game.source != "steam":
                raise sc.SteamcaseError("Steam CDN needs a selected Steam game.")
            return client.steam_art(game.id)
        if source != "SteamGridDB":
            return []
        if game.source == "steam":
            return client.grids_steam(game.id)
        if game.source == "steamgriddb":
            return client.grids(game.id)
        raise sc.SteamcaseError("Choose a SteamGridDB search result for this shortcut first.")

    def image(self, url):
        return cw.ArtworkClient().image(url)

    def current_cover(self, game):
        if not game.steam_id:
            return None
        path = cw.current_steam_cover(self.steam(), self.account(), game.steam_id)
        if path or game.source != "steam":
            return path
        art = cw.ArtworkClient().steam_art(game.id)
        return cw.ArtworkClient().image(art[0]["url"]) if art else None

    def preview(self, item):
        if item.file:
            cw.validate_local_image(item.file)
            return Path(item.file)
        if not item.image:
            raise sc.SteamcaseError("Choose artwork first.")
        # Separate folders prevent an older worker from replacing a newer preview.
        import hashlib
        digest = hashlib.sha256((item.platform + item.image).encode()).hexdigest()[:16]
        return cw.export_one(item.image, item.platform, item.game.name,
                             cw.cache_dir() / "qt-previews" / digest, item.game.steam_id)

    def export_one(self, item, folder=None):
        if item.file:
            files, errors = cw.export_many([{"file": item.file, "name": item.game.name}],
                                           folder or self.settings.export_dir)
            if errors:
                raise sc.SteamcaseError(errors[0][1])
            return files[0]
        return cw.export_one(item.image, item.platform, item.game.name,
                             folder or self.settings.export_dir, item.game.steam_id)

    def add(self, item):
        if not item.file and not item.image:
            raise sc.SteamcaseError("Choose artwork before adding it to the batch.")
        self.queue[item.key] = replace(item, status="Queued" if item.game.verified else "Export only")
        return item.key

    def remove(self, key):
        self.queue.pop(key, None)

    def export_all(self, folder=None):
        items = [{"name": item.game.name, "platform": item.platform, "image": item.image,
                  "file": item.file, "steam_id": item.game.steam_id}
                 for item in self.queue.values()]
        return cw.export_many(items, folder or self.settings.export_dir)

    def automatic(self, progress=None, cancelled=None, skip_auto_art=False):
        games = self._steam_games(self.steam())
        if not games:
            raise sc.SteamcaseError("No Steam games found. Install a game or load userdata.json.")
        result = sc.make_covers(games, self.covers_dir, skip_auto_art=skip_auto_art,
                                progress=progress, cancelled=cancelled)
        result["titles"] = dict(sc.list_games(games))
        return result

    def add_automatic(self, result):
        titles = result.get("titles", {})
        for path in result["files"]:
            appid = int(sc.appid_of(path))
            game = Game(titles.get(appid, str(appid)), "steam", appid, appid, True)
            item = CoverItem(game, "steam", file=str(path), preview=str(path))
            self.queue.setdefault(item.key, item)

    def _verified_items(self, items):
        chosen = list(items)
        if not chosen:
            raise sc.SteamcaseError("Choose a cover to apply.")
        ids = [item.game.steam_id for item in chosen]
        if any(not item.game.verified or not ident or not 0 < ident < 2 ** 32 for item, ident in zip(chosen, ids)):
            raise sc.SteamcaseError("Only a selected Steam game or verified shortcut can be applied.")
        if len(set(ids)) != len(ids):
            raise sc.SteamcaseError("Only one cover per Steam ID can be applied at a time.")
        return chosen

    def apply_items(self, items, progress: Callable[[str, str], None] | None = None):
        """One preflight, one backup/apply transaction, at most one client restart."""
        chosen = self._verified_items(items)
        report = progress or (lambda _key, _status: None)
        steam, account = self.steam(), self.account()
        shortcut_ids = None
        for item in chosen:
            if item.game.source != "steam":
                if shortcut_ids is None:
                    shortcut_ids = {int(entry["id"]) for entry in cw.list_shortcuts(steam, account)}
                if item.game.steam_id not in shortcut_ids:
                    report(item.key, "Failed: shortcut no longer exists")
                    raise sc.SteamcaseError("The shortcut for %s no longer exists. Nothing was changed." % item.game.name)
        closed = False
        cw.cache_dir().mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="casecovers-apply-", dir=cw.cache_dir()) as stage:
            files = []
            for item in chosen:
                report(item.key, "Preparing")
                try:
                    path = (Path(item.file) if item.file else
                            cw.export_one(item.image, item.platform, item.game.name, stage, item.game.steam_id))
                    cw.validate_local_image(path)
                    if int(sc.appid_of(str(path)) or 0) != item.game.steam_id:
                        raise sc.SteamcaseError("Prepared cover has the wrong Steam ID.")
                    files.append(str(path))
                    report(item.key, "Ready")
                except (OSError, ValueError, sc.SteamcaseError) as exc:
                    report(item.key, "Failed: %s" % exc)
                    raise sc.SteamcaseError("Could not prepare %s: %s. Nothing was changed." %
                                            (item.game.name, exc)) from exc
            try:
                if sc.steam_running():
                    if not sc.close_steam(steam):
                        raise sc.SteamcaseError("Steam did not close. Save any running game and exit Steam, then retry.")
                    closed = True
                for item in chosen:
                    report(item.key, "Applying")
                result = sc.apply_covers(steam, self.covers_dir, account, files=files)
                changed = set(result["changed_ids"])
                for item in chosen:
                    report(item.key, "Applied" if item.game.steam_id in changed else "Already current")
                return result
            except Exception as exc:
                for item in chosen:
                    report(item.key, "Failed · restore backup" if "could not be put back" in str(exc)
                           else "Failed · no changes applied")
                raise
            finally:
                if closed and self.settings.restart_steam:
                    try:
                        sc.start_steam(steam)
                    except sc.SteamcaseError as exc:
                        report("", "Steam could not restart: %s" % exc)

    def apply_all(self, progress=None):
        return self.apply_items([item for item in self.queue.values() if item.game.verified], progress)

    def restore(self):
        steam, account = self.steam(), self.account()
        backups = sc.list_backups(steam, account)
        if not backups:
            raise sc.SteamcaseError("No backup found for this Steam account.")
        return self._with_closed_steam(lambda: sc.restore_backup(steam, backups[0], account))

    def export_artwork_backup(self, destination, account=None, progress=None):
        steam = self.steam()
        chosen = self.account() if account is None else account
        try:
            shortcut_ids = {int(item["id"]) for item in cw.list_shortcuts(steam, chosen)}
        except (OSError, sc.SteamcaseError):
            # A damaged shortcuts.vdf must not prevent a read-only backup of grid files.
            shortcut_ids = set()
        return sc.export_artwork_backup(steam, destination, chosen, progress, shortcut_ids)

    def preview_artwork_backup(self, folder, account=None):
        steam = self.steam()
        chosen = self.account() if account is None else account
        shortcut_ids = {int(item["id"]) for item in cw.list_shortcuts(steam, chosen)}
        return sc.inspect_artwork_backup(steam, folder, chosen, shortcut_ids)

    def import_artwork_backup(self, folder, expected, account=None, progress=None):
        steam = self.steam()
        chosen = self.account() if account is None else account
        shortcut_ids = {int(item["id"]) for item in cw.list_shortcuts(steam, chosen)}
        preview = sc.inspect_artwork_backup(steam, folder, chosen, shortcut_ids)
        if not preview["can_import"] or preview["token"] != expected:
            raise sc.SteamcaseError("The artwork backup or current artwork changed. Preview it again before importing.")
        action = lambda: sc.import_artwork_backup(
            steam, folder, chosen, expected, progress,
            {int(item["id"]) for item in cw.list_shortcuts(steam, chosen)})
        if not preview["new"] and not preview["overwrite"] and not preview["removals"]:
            return action()
        return self._with_closed_steam(action)

    def reset_default(self, everything=False):
        steam, account = self.steam(), self.account()
        return self._with_closed_steam(lambda: sc.reset_to_default(steam, account, everything=everything))

    def _with_closed_steam(self, action):
        closed = False
        steam = self.steam()
        try:
            if sc.steam_running():
                if not sc.close_steam(steam):
                    raise sc.SteamcaseError("Steam did not close. Save any running game and exit Steam, then retry.")
                closed = True
            return action()
        finally:
            if closed and self.settings.restart_steam:
                sc.start_steam(steam)
