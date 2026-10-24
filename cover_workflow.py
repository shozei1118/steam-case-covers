# SPDX-License-Identifier: GPL-3.0-or-later
"""Manual cover search, source selection and Steam-independent export."""
import hashlib
import io
import json
import os
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

import platform_catalog
import steamcase as sc

SGDB_API = "https://www.steamgriddb.com/api/v2"
STEAM_SEARCH = "https://store.steampowered.com/api/storesearch/"
KEY_SERVICE = "Case Covers SteamGridDB"
KEY_USER = "api-key"


def save_api_key(key):
    """Use the OS credential store. Never write a plaintext key into app files."""
    try:
        import keyring
        if key.strip():
            keyring.set_password(KEY_SERVICE, KEY_USER, key.strip())
        else:
            try:
                keyring.delete_password(KEY_SERVICE, KEY_USER)
            except keyring.errors.PasswordDeleteError:
                pass
    except Exception as exc:
        raise sc.SteamcaseError("The system credential store is unavailable: %s" % exc) from exc


def load_api_key():
    try:
        import keyring
        return keyring.get_password(KEY_SERVICE, KEY_USER) or ""
    except Exception as exc:
        raise sc.SteamcaseError("The system credential store is unavailable: %s" % exc) from exc


def cache_dir():
    return Path(sc.default_covers_dir()).parent / "cache"


class ArtworkClient:
    def __init__(self, api_key="", directory=None, opener=None):
        self.api_key = api_key.strip()
        self.directory = Path(directory) if directory is not None else cache_dir()
        self.opener = opener or sc._get_opener()

    def _request(self, url, authenticated=False):
        sc._require_https(url)
        if authenticated and not self.api_key:
            raise sc.SteamcaseError("Enter a SteamGridDB API key in the settings first.")
        headers = {"User-Agent": "Case Covers/1"}
        if authenticated:
            headers["Authorization"] = "Bearer " + self.api_key
        request = urllib.request.Request(url, headers=headers)
        try:
            with self.opener.open(request, timeout=20) as response:
                return sc._read_capped(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise sc.SteamcaseError("SteamGridDB rejected the API key or access was denied.") from exc
            if exc.code == 429:
                delay = exc.headers.get("Retry-After", "a while")
                raise sc.SteamcaseError("SteamGridDB rate limit reached. Retry after %s." % delay) from exc
            if exc.code == 404:
                return b'{"success":true,"data":[]}'
            raise sc.SteamcaseError("Artwork service returned HTTP %d." % exc.code) from exc
        except (OSError, TimeoutError) as exc:
            raise sc.SteamcaseError("Artwork network request failed: %s" % sc.explain_error(exc)) from exc

    def _cached(self, url, authenticated=False, ttl=86400):
        if authenticated and not self.api_key:
            raise sc.SteamcaseError("Enter a SteamGridDB API key in the settings first.")
        # The cache key contains no credential; artwork and search results are public.
        name = hashlib.sha256(url.encode("utf-8")).hexdigest() + ".json"
        path = self.directory / "requests" / name
        if path.is_file() and time.time() - path.stat().st_mtime < ttl:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass
        body = self._request(url, authenticated)
        try:
            data = json.loads(body)
            if data.get("success") is False:
                raise sc.SteamcaseError("Artwork service did not accept the request.")
        except (ValueError, AttributeError) as exc:
            raise sc.SteamcaseError("Artwork service sent an invalid response.") from exc
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".response-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                json.dump(data, target)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return data

    def verify_key(self):
        # An authenticated request distinguishes a valid key from an empty field.
        self._request(SGDB_API + "/games/id/1", authenticated=True)
        return True

    def search(self, term, source):
        term = term.strip()
        if len(term) < 2:
            raise sc.SteamcaseError("Enter at least two characters to search.")
        if source == "steam":
            url = STEAM_SEARCH + "?" + urllib.parse.urlencode({"term": term, "l": "english", "cc": "US"})
            data = self._cached(url, ttl=3600)
            return [{"id": int(item["id"]), "name": item["name"], "source": "steam"}
                    for item in data.get("items", []) if item.get("id") and item.get("name")]
        if source != "steamgriddb":
            raise ValueError("Unsupported search source")
        url = SGDB_API + "/search/autocomplete/" + urllib.parse.quote(term, safe="")
        data = self._cached(url, authenticated=True)
        return [{"id": int(item["id"]), "name": item["name"], "source": "steamgriddb",
                 "types": item.get("types", []), "verified": bool(item.get("verified"))}
                for item in data.get("data", []) if isinstance(item, dict) and item.get("id") and item.get("name")]

    def grids(self, game_id):
        return self._grids("game", game_id)

    def grids_steam(self, appid):
        """SteamGridDB's exact Steam App ID mapping; no title guess is involved."""
        return self._grids("steam", appid)

    def _grids(self, identifier_type, identifier):
        url = SGDB_API + "/grids/%s/%d?" % (identifier_type, int(identifier)) + urllib.parse.urlencode(
            {"dimensions": "600x900,342x482,660x930", "types": "static", "nsfw": "false", "humor": "false", "epilepsy": "false", "limit": 50})
        data = self._cached(url, authenticated=True, ttl=6 * 3600)
        return [{"id": int(item["id"]), "url": item["url"], "thumb": item.get("thumb") or item["url"],
                 "score": item.get("score", 0), "style": item.get("style", "")}
                for item in data.get("data", []) if isinstance(item, dict) and item.get("id") and item.get("url")]

    def steam_art(self, appid):
        info = sc.store_items([int(appid)])
        urls, _auto = sc.portrait_candidates(int(appid), info.get(int(appid)))
        return [{"id": i, "url": url, "thumb": url, "style": "Steam CDN"}
                for i, url in enumerate(urls, 1)]

    def image(self, url):
        sc._require_https(url)
        suffix = Path(urllib.parse.urlsplit(url).path).suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
            suffix = ".png"
        path = self.directory / "images" / (hashlib.sha256(url.encode("utf-8")).hexdigest() + suffix)
        if path.is_file():
            try:
                with Image.open(path, formats=["PNG", "JPEG", "WEBP"]) as im:
                    im.verify()
                return path
            except (OSError, ValueError):
                path.unlink(missing_ok=True)
        body = self._request(url)
        try:
            with Image.open(io.BytesIO(body), formats=["PNG", "JPEG", "WEBP"]) as im:
                if im.width * im.height > sc.MAX_PIXELS:
                    raise sc.SteamcaseError("Artwork image is too large.")
                im.verify()
        except (OSError, ValueError) as exc:
            raise sc.SteamcaseError("Downloaded artwork is not a supported image.") from exc
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".art-")
        try:
            with os.fdopen(fd, "wb") as target:
                target.write(body)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return path


def validate_local_image(path):
    if Path(path).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise sc.SteamcaseError("Choose a PNG, JPG or WebP image.")
    try:
        with Image.open(path, formats=["PNG", "JPEG", "WEBP"]) as im:
            if im.width * im.height > sc.MAX_PIXELS:
                raise sc.SteamcaseError("Artwork image is too large.")
            im.verify()
    except OSError as exc:
        raise sc.SteamcaseError("The selected image cannot be read.") from exc
    return Path(path)


def current_steam_cover(steam, user, appid):
    """Return the portrait Steam currently overrides, respecting its image priority."""
    folder = Path(sc.grid_dir(steam, user))
    for suffix in ("jpg", "jpeg", "webp", "png"):
        path = folder / ("%dp.%s" % (int(appid), suffix))
        if path.is_file() and not path.is_symlink():
            try:
                with Image.open(path, formats=["PNG", "JPEG", "WEBP"]) as image:
                    if image.width * image.height <= sc.MAX_PIXELS:
                        image.verify()
                        return path
            except (OSError, ValueError):
                continue
    return None


def export_one(image_path, platform_id, title, output_dir, steam_id=None):
    validate_local_image(image_path)
    platform_catalog.get_platform(platform_id)
    frame_path = platform_catalog.local_asset("assets/frames/%s.png" % platform_id)
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    if steam_id is not None:
        steam_id = int(steam_id)
        if not 0 < steam_id < 2 ** 32:
            raise sc.SteamcaseError("Steam artwork ID must be a 32-bit positive number.")
        name = "%s_%d.png" % (sc.slug(title), steam_id)
    else:
        digest = hashlib.sha256((title + platform_id + str(image_path)).encode("utf-8")).hexdigest()[:8]
        name = "%s_%s_x%s.png" % (sc.slug(title), platform_id, digest)
    output = folder / name
    with Image.open(frame_path) as frame:
        sc.build_cover(str(image_path), str(output), frame.convert("RGBA"))
    return output


def export_many(items, output_dir, progress=None):
    """Each item explicitly names its selected art and platform; no fuzzy match is applied."""
    done, errors = [], []
    for number, item in enumerate(items, 1):
        try:
            if item.get("file"):
                source = validate_local_image(item["file"])
                if source.suffix.lower() != ".png" or not sc.appid_of(str(source)):
                    raise sc.SteamcaseError("The prepared Steam cover must be a named PNG file.")
                target = Path(output_dir) / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.resolve() != target.resolve():
                    shutil.copy2(source, target)
                done.append(target)
            else:
                done.append(export_one(item["image"], item["platform"], item["name"], output_dir,
                                       item.get("steam_id")))
        except Exception as exc:
            errors.append((item.get("name", ""), str(exc)))
        if progress:
            progress(number, len(items))
    return done, errors


def _read_shortcut_object(data, offset=0, depth=0):
    """Read only the small binary KeyValues subset used by Steam shortcuts."""
    if depth > 8:
        raise sc.SteamcaseError("Steam shortcuts file is too deeply nested.")
    result = {}
    while offset < len(data):
        kind = data[offset]
        offset += 1
        if kind == 8:
            return result, offset
        end = data.find(b"\0", offset)
        if end < 0:
            break
        key = data[offset:end].decode("utf-8", "replace")
        offset = end + 1
        if kind == 0:
            value, offset = _read_shortcut_object(data, offset, depth + 1)
        elif kind == 1:
            end = data.find(b"\0", offset)
            if end < 0:
                break
            value = data[offset:end].decode("utf-8", "replace")
            offset = end + 1
        elif kind in (2, 7):
            width = 4 if kind == 2 else 8
            if offset + width > len(data):
                break
            value = int.from_bytes(data[offset:offset + width], "little", signed=True)
            offset += width
        else:
            raise sc.SteamcaseError("Unsupported Steam shortcuts format (field type %d)." % kind)
        result[key.lower()] = value
    raise sc.SteamcaseError("Steam shortcuts file is incomplete.")


def list_shortcuts(steam, user=None):
    """Return IDs actually recorded by Steam; never guess a shortcut ID from a title."""
    path = Path(sc.grid_dir(steam, user)).parent / "shortcuts.vdf"
    if not path.is_file():
        return []
    if path.stat().st_size > 4 * 1024 * 1024:
        raise sc.SteamcaseError("Steam shortcuts file is unexpectedly large.")
    tree, offset = _read_shortcut_object(path.read_bytes())
    if offset != path.stat().st_size:
        raise sc.SteamcaseError("Steam shortcuts file contains extra unread data.")
    entries = tree.get("shortcuts", {})
    if not isinstance(entries, dict):
        raise sc.SteamcaseError("Steam shortcuts file has no shortcuts list.")
    found = []
    for entry in entries.values():
        if not isinstance(entry, dict) or not isinstance(entry.get("appid"), int):
            continue
        identifier = entry["appid"] & 0xFFFFFFFF
        if identifier and entry.get("appname"):
            found.append({"id": identifier, "name": entry["appname"]})
    return found
