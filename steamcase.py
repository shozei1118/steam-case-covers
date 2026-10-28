#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Diego Bergonsi. Part of steam-case-covers: https://github.com/diegobergonsi/steam-case-covers
"""steamcase: give every game in your Steam library a "physical case" portrait cover.

  python steamcase.py list                       show the games it found
  python steamcase.py make                       build covers into ./covers
  python steamcase.py apply                      copy covers into Steam's grid folder
  python steamcase.py run                        make + apply
  python steamcase.py restore                    undo the last apply

Needs Python 3.8+ and Pillow (pip install pillow). No Steam API key, no account login.
Covers are built on your machine from the artwork Steam itself serves for your games.

The functions below are the engine. The CLI at the bottom and gui.py both use them.
"""
import argparse, filecmp, hashlib, json, os, re, shutil, socket, ssl, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request, uuid

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import certifi                      # a bundled set of trusted certificates (the packaged app's own Python may not find the system's)
except ImportError:
    certifi = None

for _s in (sys.stdout, sys.stderr):          # game names may hold non-ASCII; never crash a legacy console
    if _s is not None and hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

HERE = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))   # _MEIPASS: inside a PyInstaller bundle
FRAME = os.path.join(HERE, "assets", "frame.png")
WINDOW = (14, 96, 586, 872)                 # art window inside frame.png (x0, y0, x1, y1)
SIZE = (600, 900)
STEAMID64_BASE = 76561197960265728
CDN = "https://shared.fastly.steamstatic.com/store_item_assets/"
OLD_CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps/%d/library_600x900_2x.jpg"
STORE_API = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1?"
LIBRARY_JSON_URL = "https://store.steampowered.com/dynamicstore/userdata/"
# The data page returns an EMPTY list (not an error) when you are logged out, and Steam lets the browser keep that
# answer for an hour (Cache-Control: max-age=3600). So the button opens Steam's login page with a redirect to the
# data page, using a NEW address every time (?cb=...): logged in already -> straight to the data; logged out -> log in,
# then fresh data, never the cached empty copy.
def library_login_url():
    return "https://store.steampowered.com/login/?redir=dynamicstore%2Fuserdata%2F%3Fcb%3D" + uuid.uuid4().hex[:10] + "&redir_ssl=1"
MAX_DOWNLOAD = 25 * 1024 * 1024          # a cover portrait is ~1 MB; anything bigger is not one
MAX_LIBRARY_FILE = 20 * 1024 * 1024      # a real library list is a few KB
MAX_APPS = 100_000                       # a real library has at most a few thousand apps
MAX_PIXELS = 30_000_000                  # portraits are ~1 MP; refuses decompression bombs
TOOL_NAMES = re.compile(r"^(Proton|Steam Linux Runtime|Steamworks Common|Steam Controller Configs)", re.I)
BACKUP_PREFIX = "grid_backup_"

# Shown next to the "skip blurry auto-art" option (GUI tooltip, CLI --help).
AUTO_ART_HELP = (
    "Some games, mostly older or small ones, have no real portrait on Steam. "
    "Steam builds a stand-in from the wide header image: the title banner sits in the "
    "middle of a blurred, stretched copy of itself, with lots of empty space. "
    "Tick this to skip those games and keep Steam's default art for them."
)


def default_covers_dir():
    """Per-user folder for the app (GUI) to keep covers in."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "steamcase", "covers")


class SteamcaseError(Exception):
    """A problem the user can understand (no Steam found, bad file...). The message is meant to be shown."""


# ---------- helpers ----------
_ssl_ctx = None


def _ssl_context():
    """TLS settings: the system's trusted certificates plus certifi's. Without certifi, the packaged Linux app
    looked in /usr/lib/ssl (a Debian path), found nothing on SteamOS and failed every HTTPS request."""
    global _ssl_ctx
    if _ssl_ctx is None:
        ctx = ssl.create_default_context()
        if certifi is not None:
            try:
                ctx.load_verify_locations(cafile=certifi.where())
            except Exception:
                pass
        _ssl_ctx = ctx
    return _ssl_ctx


def explain_error(exc):
    """A short human reason for a failed request."""
    text = str(exc)
    inner = getattr(exc, "reason", exc)
    if isinstance(inner, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in text:
        return "its security certificate could not be verified. Check that your computer's date and time are right and that your network isn't intercepting secure connections"
    if isinstance(exc, urllib.error.HTTPError):
        return "it answered with an error (HTTP %d)" % exc.code
    if isinstance(inner, socket.gaierror) or "Name or service not known" in text or "getaddrinfo" in text:
        return "no internet, or a DNS problem (the address could not be found)"
    if isinstance(inner, (socket.timeout, TimeoutError)) or "timed out" in text:
        return "the connection timed out"
    return (text or type(exc).__name__)[:120]


def check_network():
    """One tiny real request to Steam's store API. Returns (ok, message). Used by 'gui.py --check-network'."""
    try:
        q = json.dumps({"ids": [{"appid": 220}], "context": {"language": "english", "country_code": "US"}, "data_request": {}})
        json.loads(http_get(STORE_API + urllib.parse.urlencode({"input_json": q}), tries=1))
        return True, "Steam's servers answered."
    except Exception as e:
        return False, explain_error(e)


ALLOW_LOCAL_HTTP = False         # only the tests switch this on (they talk to a throw-away local server)
_opener = None


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _require_https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _require_https(url):
    """Every address the app opens must be https (no file:// and no unencrypted http://)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https":
        return
    if ALLOW_LOCAL_HTTP and parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost"):
        return
    raise SteamcaseError("Refusing to open an address that is not https: %s" % url[:80])


def _get_opener():
    global _opener
    if _opener is None:
        _opener = urllib.request.build_opener(_HttpsOnlyRedirects, urllib.request.HTTPSHandler(context=_ssl_context()))
    return _opener


def _read_capped(resp):
    size = resp.headers.get("Content-Length")
    if size and size.isdigit() and int(size) > MAX_DOWNLOAD:
        raise SteamcaseError("A download was unexpectedly large (%s bytes); refusing it." % size)
    data = resp.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise SteamcaseError("A download was unexpectedly large; refusing it.")
    return data


def http_get(url, tries=3):
    for i in range(tries):
        try:
            _require_https(url)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 steamcase"})
            with _get_opener().open(req, timeout=30) as r:
                return _read_capped(r)
        except SteamcaseError:
            raise
        except urllib.error.HTTPError as e:
            if i == tries - 1 or (400 <= e.code < 500 and e.code != 429):      # a real "not found": retrying will not help
                raise
            time.sleep(1.5 * (i + 1))
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


_TAG = re.compile(r"^v([0-9]{1,4})\.([0-9]{1,4})\.([0-9]{1,4})$")


def _read_version():
    """The release tag stamped into this build (assets/version.txt, written by the release workflow); "dev" for source runs."""
    try:
        with open(os.path.join(HERE, "assets", "version.txt"), encoding="ascii") as fh:
            v = fh.read(40).strip()
        return v if _TAG.match(v) else "dev"
    except Exception:
        return "dev"


APP_VERSION = _read_version()


def _tmp(path, tag="tmp"):
    """A temp file name next to `path` that no other run can share."""
    return "%s.%d.%s.%s" % (path, os.getpid(), uuid.uuid4().hex[:8], tag)


def slug(name):
    return re.sub(r"[^\w]+", "_", name)[:60].strip("_") or "game"      # short enough for any filesystem (255 bytes)


def read_text(path):
    with open(path, encoding="utf-8-sig", errors="replace") as stream:
        return stream.read()


def vdf_values(text, key):
    return re.findall(r'"%s"\s+"((?:[^"\\]|\\.)*)"' % re.escape(key), text, re.I)


def _tool(name):
    """Full path of a system tool, so a look-alike file next to the app (or in the current folder) can never be run instead."""
    if sys.platform.startswith("win"):
        return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", name + ".exe")
    for d in ("/usr/bin", "/bin"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return name


def appid_of(filename):
    m = re.search(r"_([0-9]{1,10})\.png$", filename)
    return m.group(1) if m and 0 < int(m.group(1)) < 2 ** 32 else None


# ---------- finding Steam ----------
def steam_dir(override=None):
    if override:
        path = os.path.expanduser(override)
        if not os.path.isdir(path):
            raise SteamcaseError("Steam folder not found: %s" % path)
        return path
    home = os.path.expanduser("~")
    cands = []
    if sys.platform.startswith("win"):
        try:
            import winreg
            for hive, sub, val in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                   (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                                   (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        cands.append(winreg.QueryValueEx(k, val)[0])
                except OSError:
                    pass
        except ImportError:
            pass
        cands += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    elif sys.platform == "darwin":
        cands.append(os.path.join(home, "Library/Application Support/Steam"))
    else:
        cands += [os.path.join(home, ".local/share/Steam"), os.path.join(home, ".steam/steam"),
                  os.path.join(home, ".var/app/com.valvesoftware.Steam/.local/share/Steam"),
                  os.path.join(home, "snap/steam/common/.local/share/Steam")]
    for c in cands:
        if os.path.isdir(os.path.join(c, "steamapps")) or os.path.isdir(os.path.join(c, "userdata")):
            return os.path.realpath(c)
    raise SteamcaseError("Could not find Steam. Is it installed? (CLI: pass its folder with --steam-dir.)")


def library_paths(steam):
    paths = [steam]
    vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
    if os.path.exists(vdf):
        try:
            folders = vdf_values(read_text(vdf), "path")
        except OSError:
            folders = []
        for p in folders:
            p = p.replace("\\\\", "\\")
            if os.path.isdir(p) and os.path.realpath(p) not in [os.path.realpath(x) for x in paths]:
                paths.append(p)
    return paths


def installed_games(steam):
    games = {}
    for lib in library_paths(steam):
        apps = os.path.join(lib, "steamapps")
        if not os.path.isdir(apps):
            continue
        try:
            manifests = os.listdir(apps)
        except OSError:
            continue
        for fn in manifests:
            if not re.fullmatch(r"appmanifest_([0-9]{1,10})\.acf", fn):
                continue
            try:
                t = read_text(os.path.join(apps, fn))
            except OSError:
                continue
            i, n = vdf_values(t, "appid"), vdf_values(t, "name")
            if i and n and i[0] == fn[12:-4] and 0 < int(i[0]) < 2 ** 32 and not TOOL_NAMES.match(n[0]):
                games[int(i[0])] = n[0]
    return games


def owned_ids(json_path):
    path = os.path.expanduser(json_path)
    try:
        if os.path.getsize(path) > MAX_LIBRARY_FILE:
            raise SteamcaseError("That file is far too big to be your game list (over %d MB)." % (MAX_LIBRARY_FILE >> 20))
        with open(path, encoding="utf-8-sig") as stream:
            d = json.load(stream)
    except SteamcaseError:
        raise
    except (OSError, ValueError, RecursionError, MemoryError, UnicodeError) as e:
        raise SteamcaseError("Could not read %s as a game list (%s)." % (os.path.basename(path), type(e).__name__))
    ids = d.get("rgOwnedApps") if isinstance(d, dict) else None
    if isinstance(ids, list) and not ids and "rgOwnedPackages" in d:
        raise SteamcaseError("That file has no games in it. This usually means you were not logged in to Steam in your browser when you saved it. "
                             "Click “Download your userdata.json” again, log in when Steam asks, then save the page. "
                             "If the page you see shows no games even though you are logged in, refresh it (F5, or Cmd+R on a Mac) before saving.")
    if not ids or not isinstance(ids, list):
        raise SteamcaseError("That file has no game list ('rgOwnedApps'). Save %s while logged in to Steam." % LIBRARY_JSON_URL)
    if len(ids) > MAX_APPS:
        raise SteamcaseError("That game list has %d entries; a real library has far fewer. Refusing it." % len(ids))
    try:
        out = [int(i) for i in ids]
    except (TypeError, ValueError):
        raise SteamcaseError("The game list in that file is damaged. Save %s again." % LIBRARY_JSON_URL)
    out = [i for i in out if 0 < i < 2 ** 32]                    # real Steam app IDs only
    if not out:
        raise SteamcaseError("The game list in that file is empty. Save %s while logged in to Steam." % LIBRARY_JSON_URL)
    return out


def load_games(steam, library_json=None):
    """{appid: name or None}: installed games, plus every owned app when library_json is given."""
    games = installed_games(steam)
    if library_json:
        for i in owned_ids(library_json):
            games.setdefault(i, None)
    return games


def pick_account(steam, forced=None):
    base = os.path.join(steam, "userdata")
    accs = [d for d in os.listdir(base) if re.fullmatch(r"[0-9]+", d) and d != "0"] if os.path.isdir(base) else []
    if forced:
        if not re.fullmatch(r"[0-9]+", str(forced)):
            raise SteamcaseError("The account must be the numeric folder name inside userdata/, e.g. 12345678")
        return str(forced)
    if not accs:
        raise SteamcaseError("No account folders in %s. Log in to Steam once, then retry." % base)
    if len(accs) == 1:
        return accs[0]
    recent = None
    lu = os.path.join(steam, "config", "loginusers.vdf")
    if os.path.exists(lu):
        for m in re.finditer(r'"([0-9]{17})"\s*\{(.*?)\}', read_text(lu), re.S):
            if re.search(r'"MostRecent"\s+"1"', m.group(2)):
                recent = str(int(m.group(1)) - STEAMID64_BASE)
    if recent in accs:
        return recent
    return max(accs, key=lambda a: os.path.getmtime(os.path.join(base, a)))


def list_accounts(steam):
    """[(folder id, display name)] for every Steam account that has a userdata folder, the one pick_account() would choose first."""
    base = os.path.join(steam, "userdata")
    accs = [d for d in os.listdir(base) if re.fullmatch(r"[0-9]+", d) and d != "0"] if os.path.isdir(base) else []
    first = pick_account(steam) if accs else None
    accs.sort(key=lambda a: (a != first, a))
    return [(a, account_label(steam, a)) for a in accs]


def account_label(steam, acc):
    """Human name for a userdata folder id: Steam display name, else login name, else the number."""
    lu = os.path.join(steam, "config", "loginusers.vdf")
    if os.path.exists(lu):
        for m in re.finditer(r'"([0-9]{17})"\s*\{(.*?)\}', read_text(lu), re.S):
            if str(int(m.group(1)) - STEAMID64_BASE) == str(acc):
                names = vdf_values(m.group(2), "PersonaName") + vdf_values(m.group(2), "AccountName")
                for n in names:
                    if n.strip():
                        return n.strip()
    return str(acc)


def grid_dir(steam, user=None):
    return os.path.join(steam, "userdata", pick_account(steam, user), "config", "grid")


# ---------- Steam process ----------
def _background_creationflags():
    """Keep Windows console tools from opening a window when called by the GUI."""
    return subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0


def steam_running():
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run([_tool("tasklist")], capture_output=True, text=True,
                                 creationflags=_background_creationflags()).stdout.lower()
            return "steam.exe" in out
        out = subprocess.run([_tool("ps"), "-A", "-o", "comm="], capture_output=True, text=True).stdout.lower()
        # Linux prints just the name ("steam"); macOS prints the whole path (".../Steam.app/Contents/MacOS/steam_osx")
        return any(os.path.basename(l.strip()) in ("steam", "steam_osx", "steamwebhelper") for l in out.splitlines())
    except Exception:
        return False


def _mac_steam_binary():
    for base in ("/Applications", os.path.expanduser("~/Applications")):
        p = os.path.join(base, "Steam.app", "Contents", "MacOS", "steam_osx")
        if os.path.exists(p):
            return p
    return None


def _steam_launcher(steam):
    """Command list that runs Steam, or None if unknown."""
    if sys.platform.startswith("win"):
        exe = os.path.join(steam, "steam.exe")
        return [exe] if os.path.exists(exe) else None
    if sys.platform == "darwin":
        return [_tool("open"), "-a", "Steam", "--args"]
    if "com.valvesoftware.Steam" in steam and shutil.which("flatpak"):
        return ["flatpak", "run", "com.valvesoftware.Steam"]
    found = shutil.which("steam")
    if found:
        return [found]
    for rel in ("steam.sh", "ubuntu12_32/steam"):
        p = os.path.join(steam, rel)
        if os.path.exists(p):
            return [p]
    return None


def close_steam(steam, timeout=60):
    """Ask Steam to exit and wait for it. Returns True when it is gone. Never kills the process."""
    if not steam_running():
        return True
    cmd = _steam_launcher(steam)
    try:
        if sys.platform == "darwin":
            exe = _mac_steam_binary()
            if exe:                                                  # Steam's own "-shutdown" (works without any permission prompt)
                subprocess.Popen([exe, "-shutdown"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=_background_creationflags())
            else:
                subprocess.Popen([_tool("osascript"), "-e", 'quit app "Steam"'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=_background_creationflags())
        elif cmd:
            subprocess.Popen(cmd + ["-shutdown"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=_background_creationflags())
        else:
            raise SteamcaseError("Could not work out how to close Steam. Please close it yourself.")
    except OSError as e:
        raise SteamcaseError("Could not close Steam: %s" % e)
    end = time.time() + timeout
    while time.time() < end:
        if not steam_running():
            time.sleep(2)                       # let it finish writing its files
            return True
        time.sleep(1)
    return False


def start_steam(steam):
    cmd = _steam_launcher(steam)
    if not cmd:
        raise SteamcaseError("Could not work out how to start Steam. Please start it yourself.")
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                         start_new_session=not sys.platform.startswith("win"),
                         creationflags=_background_creationflags())
    except OSError as e:
        raise SteamcaseError("Could not start Steam: %s" % e)


# ---------- store data ----------
def store_items(appids, log=None, cancelled=None, errors=None):
    out = {}
    for n in range(0, len(appids), 100):
        if cancelled and cancelled():
            break
        chunk = appids[n:n + 100]
        q = json.dumps({"ids": [{"appid": i} for i in chunk], "context": {"language": "english", "country_code": "US"},
                        "data_request": {"include_assets": True}})
        try:
            items = json.loads(http_get(STORE_API + urllib.parse.urlencode({"input_json": q})))["response"].get("store_items", [])
        except Exception as e:
            if errors is not None:
                errors.append(e)
            if log:
                log("store lookup failed for a chunk: %s" % e)
            continue
        requested = set(chunk)
        if len(items) == len(chunk) and all(isinstance(it, dict) and "appid" not in it for it in items):
            out.update(zip(chunk, items))
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                appid = int(it.get("appid"))
            except (TypeError, ValueError):
                continue
            if appid in requested:
                out[appid] = it
    return out


def portrait_candidates(appid, item):
    a = (item or {}).get("assets") or {}
    fmt = a.get("asset_url_format")
    urls, auto = [], False
    for k in ("library_capsule_2x", "library_capsule"):
        if fmt and a.get(k):
            urls.append(CDN + fmt.replace("${FILENAME}", a[k]))
            auto = a[k].endswith("portrait.png")     # Steam-generated from the header: blurry
            break
    urls.append(OLD_CDN % appid)
    return urls, auto


def list_games(games, log=None, include_unknown=False):
    """[(appid, name)] of real games only (no DLC, tools or unnamed leftovers)."""
    info = store_items(sorted(games), log)
    out = []
    for appid in sorted(games):
        it = info.get(appid, {})
        name = games[appid] or it.get("name")
        if not name and include_unknown:
            name = "Steam app %s" % appid
        if it.get("type", 0) not in (0, None) or not name or TOOL_NAMES.match(name):
            continue
        out.append((appid, name))
    return out


# ---------- drawing ----------
def build_cover(portrait_path, out_path, frame):
    if Image is None:
        raise SteamcaseError("Pillow is missing. Install it with:  python -m pip install pillow")
    with Image.open(portrait_path, formats=["PNG", "JPEG", "WEBP"]) as im:        # never let Pillow guess (EPS, TIFF, ... have a worse track record)
        if im.width * im.height > MAX_PIXELS:                  # header check only; nothing is decoded yet
            raise SteamcaseError("Image is too large to be a game portrait (%dx%d)." % im.size)
        art = im.convert("RGBA")
    x0, y0, x1, y1 = WINDOW
    ww, wh = x1 - x0, y1 - y0
    s = max(ww / art.width, wh / art.height)                      # scale to cover, then center-crop
    art = art.resize((max(ww, round(art.width * s)), max(wh, round(art.height * s))), Image.LANCZOS)
    cx, cy = (art.width - ww) // 2, (art.height - wh) // 2
    art = art.crop((cx, cy, cx + ww, cy + wh))
    canvas = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    canvas.paste(art, (x0, y0))
    part = _tmp(out_path, "part")                  # write aside, then rename: a crash never leaves a half-written cover
    try:
        Image.alpha_composite(canvas, frame).save(part, format="PNG", optimize=True)
        for attempt in range(6):
            try:
                os.replace(part, out_path)
                break
            except PermissionError as exc:
                # On Windows another reader can briefly hold the destination open.
                # Keep the atomic replacement, but wait for that sharing lock to pass.
                if not sys.platform.startswith("win") or getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 5:
                    raise
                time.sleep(0.04 * (attempt + 1))
    finally:
        if os.path.exists(part):
            os.remove(part)


# ---------- make ----------
def make_covers(games, out, only=None, force=False, skip_auto_art=False, progress=None, cancelled=None, log=None):
    """Build a cover per game into `out`.

    progress(done, total, appid, name, status)  status: ok | exists | skipped | noart | failed
    cancelled() -> True stops early.
    progress counts only items that can become a cover (DLC, soundtracks and tools are not counted).
    Returns {"ok", "skipped", "not_games" (DLC, tools...), "unlisted" (apps Steam no longer lists), "missing": [(appid, name)] (Steam has no art),
    "failed": [(appid, name)] (download problem), "cancelled", "files": [cover paths of this run]}.
    """
    if Image is None:
        raise SteamcaseError("Pillow is missing. Install it with:  python -m pip install pillow")
    os.makedirs(out, exist_ok=True)
    frame = Image.open(FRAME).convert("RGBA")
    ids = sorted(games)
    if only:
        ids = [i for i in ids if i in set(only)]
    if log:
        log("Looking up %d apps on Steam's store..." % len(ids))
    errs = []
    info = store_items(ids, log, cancelled, errs)
    if ids and not info and not (cancelled and cancelled()):
        why = explain_error(errs[-1]) if errs else "no answer, check your internet connection"
        raise SteamcaseError("Could not reach Steam's servers: %s." % why.rstrip("."))
    res = {"ok": 0, "skipped": 0, "not_games": 0, "unlisted": 0, "missing": [], "failed": [], "cancelled": False, "files": []}
    todo = []                                   # only items that can become a cover count towards the progress
    for appid in ids:
        it = info.get(appid) or {}
        known = games[appid] or it.get("name")
        if it.get("type", 0) not in (0, None) or TOOL_NAMES.match(known or ""):
            res["skipped"] += 1
            res["not_games"] += 1               # DLC, soundtracks, tools, demos
        elif not known:
            res["skipped"] += 1
            res["unlisted"] += 1                # Steam no longer lists it (delisted or removed): no name, almost never any art
        else:
            todo.append(appid)
    ids = todo
    total = len(ids)

    def report(done, appid, name, status):
        if progress:
            progress(done, total, appid, name, status)

    for n, appid in enumerate(ids, 1):
        if cancelled and cancelled():
            res["cancelled"] = True
            break
        it = info.get(appid) or {}
        name = games[appid] or it.get("name") or str(appid)
        if it.get("type", 0) not in (0, None) or TOOL_NAMES.match(name):
            res["skipped"] += 1
            report(n, appid, name, "skipped")
            continue
        dest = os.path.join(out, "%s_%d.png" % (slug(name), appid))
        urls, auto = portrait_candidates(appid, it)
        if auto and skip_auto_art:                 # checked first: also drops covers built by an earlier run without this option
            res["skipped"] += 1
            report(n, appid, name, "skipped")
            continue
        if os.path.exists(dest) and not force:
            res["ok"] += 1
            res["files"].append(dest)
            report(n, appid, name, "exists")
            continue
        tmp = os.path.join(out, ".tmp_%d_%s" % (appid, uuid.uuid4().hex[:8]))
        got = neterr = False
        for u in urls:
            try:
                b = http_get(u)
            except urllib.error.HTTPError as e:
                neterr = neterr or not (400 <= e.code < 500 and e.code != 429)      # 404/403 = no such art; the rest = trouble
                continue
            except Exception:
                neterr = True
                continue
            if b[:2] == b"\xff\xd8" or b[:4] == b"\x89PNG" or b[8:12] == b"WEBP":
                with open(tmp, "wb") as f:
                    f.write(b)
                got = True
                break
            neterr = True                                    # answered, but not with an image: a login page or proxy in the way
        if not got:
            res["failed" if neterr else "missing"].append((appid, name))        # failed = connection problem, worth a retry
            report(n, appid, name, "failed" if neterr else "noart")
            continue
        try:
            build_cover(tmp, dest, frame)
            res["ok"] += 1
            res["files"].append(dest)
            report(n, appid, name, "ok")
        except Exception as e:
            res["failed"].append((appid, name))
            if log:
                log("FAIL %s %s: %s" % (appid, name, e))
            report(n, appid, name, "failed")
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    return res


# ---------- apply / backup / restore ----------
def _safe_copy(src, dst):
    """Copy src to dst atomically. If dst is a symlink, the link itself is replaced, never the file it points to."""
    tmp = _tmp(dst)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def find_covers(covers_dir):
    cdir = os.path.abspath(covers_dir)
    if not os.path.isdir(cdir):
        return []
    return [os.path.join(cdir, f) for f in sorted(os.listdir(cdir)) if appid_of(f)]


def apply_covers(steam, covers_dir, user=None, files=None):
    """Copy covers into Steam's grid folder as <appid>p.png. Always makes a backup first.

    `files`: apply only these cover files (default: every cover in covers_dir).
    Only files that differ are written (and backed up); if nothing differs there is no backup and "backup" is None.
    Steam shows <appid>p.jpg before <appid>p.png (tested), so a leftover .jpg (art set by hand in Steam) is moved into the backup too.
    Returns {"account", "account_name", "grid", "applied", "unchanged", "replaced", "jpg_moved", "backup"}.
    The caller closes Steam beforehand (see close_steam)."""
    grid = grid_dir(steam, user)
    covers = list(files) if files else find_covers(covers_dir)
    if not covers:
        raise SteamcaseError("No covers found in %s. Make them first." % covers_dir)
    gone = [f for f in covers if not os.path.exists(f)]
    if gone:
        raise SteamcaseError("%d cover files are missing (deleted since they were made). Click “Make covers” again. Nothing was changed." % len(gone))
    os.makedirs(grid, exist_ok=True)
    with _Lock(os.path.dirname(grid)):
        acc = os.path.basename(os.path.dirname(os.path.dirname(grid)))
        info = {"account": acc, "account_name": account_label(steam, acc), "grid": grid}
        work, added, replaced, moved = [], [], [], []
        for f in covers:
            n = "%sp.png" % appid_of(f)
            dest = os.path.join(grid, n)
            js = ["%sp.%s" % (appid_of(f), e) for e in OTHER_EXT if _is_plain_file(os.path.join(grid, "%sp.%s" % (appid_of(f), e)))]
            moved += js                                          # they would hide our cover: Steam prefers them over .png
            same = os.path.exists(dest) and filecmp.cmp(f, dest, shallow=False)
            if same:
                if js:
                    work.append((None, n))                       # our cover is there, only the .jpg has to go
                continue                                         # identical already: no need to touch or back it up
            if os.path.exists(dest):
                replaced.append(n)
            else:
                added.append(n)
            work.append((f, n))
        if not work:
            return dict(info, applied=0, unchanged=len(covers), replaced=0, jpg_moved=0, backup=None,
                        changed_ids=[], unchanged_ids=[int(appid_of(f)) for f in covers])
        base = os.path.join(os.path.dirname(grid), BACKUP_PREFIX + time.strftime("%Y%m%d_%H%M%S"))
        backup, k = base, 1
        while True:
            try:
                os.makedirs(backup)
                break
            except FileExistsError:                                  # two applies in the same second
                k += 1
                backup = "%s-%d" % (base, k)
        try:
            for n in replaced:
                shutil.copy2(os.path.join(grid, n), os.path.join(backup, n))
            with open(os.path.join(backup, "manifest.json"), "w") as fh:     # written before copying, so a rollback always works
                json.dump({"added": added, "replaced": replaced, "moved": moved}, fh)
            for j in moved:
                os.replace(os.path.join(grid, j), os.path.join(backup, j))   # a move: the user's own art is kept, not deleted
            for f, n in work:
                if f:
                    _safe_copy(f, os.path.join(grid, n))
        except OSError as e:
            try:
                _undo(grid, backup, {"added": added, "replaced": replaced, "moved": moved})     # leave Steam's art exactly as it was (we already hold the lock)
            except Exception:
                raise SteamcaseError("Could not write to Steam's artwork folder (%s), and the old artwork could not be put back. "
                                     "It is safe in the backup folder %s (use Restore, or copy the files back by hand)." % (e, backup))
            shutil.rmtree(backup, ignore_errors=True)                           # a failed run must not leave a backup behind
            raise SteamcaseError("Could not write to Steam's artwork folder (%s). Nothing was changed." % e)
        changed = {int(n.split("p.", 1)[0]) for _, n in work}
        return dict(info, applied=len(work), unchanged=len(covers) - len(work), replaced=len(replaced),
                    jpg_moved=len(moved), backup=backup, changed_ids=sorted(changed),
                    unchanged_ids=[int(appid_of(f)) for f in covers if int(appid_of(f)) not in changed])


class _Lock:
    """One Apply/Restore at a time per Steam account (two open windows, or a script and a window)."""

    def __init__(self, cfg):
        self.path = os.path.join(cfg, ".steamcase.lock")

    def __enter__(self):
        for _ in range(3):
            try:
                os.mkdir(self.path)                                  # atomic: only one run can create it
                return self
            except FileExistsError:
                try:
                    stale = time.time() - os.path.getmtime(self.path) > 600       # left behind by a crashed run
                except OSError:
                    continue
                if stale:
                    shutil.rmtree(self.path, ignore_errors=True)
                    continue
                raise SteamcaseError("Another steamcase window is changing Steam's artwork right now. Wait for it to finish, then try again.")
        raise SteamcaseError("Could not get exclusive access to Steam's artwork folder. Please try again.")

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)


_frame_ref = None
# Header and lower-lip hashes from the last shipped frame with Windows/Linux
# badges. This lets reset recognize earlier covers without rendering those badges
# in any current platform frame.
_LEGACY_FRAME_REGION_HASHES = (
    "77b13681ffdc772b7acfdc7a588c45b717192d77884c02628dfc1acc44fd8a0f",
    "eedccaa8b8713061b49087facd6e18f05d68785a504a9be0f33420b22366e569",
)


def _frame_regions():
    """The parts of a cover that are pure frame (banner on top, lip at the bottom), from frame.png."""
    global _frame_ref
    if _frame_ref is None:
        fr = Image.open(FRAME).convert("RGBA")
        top, bot = (0, 0, SIZE[0], WINDOW[1]), (0, WINDOW[3], SIZE[0], SIZE[1])
        _frame_ref = (top, bot, fr.crop(top).tobytes(), fr.crop(bot).tobytes())
    return _frame_ref


def _known_frame_hashes():
    """Exact header/lip signatures for every shipped normal and platinum frame."""
    global _known_frame_ref
    if _known_frame_ref is None:
        from platform_catalog import load_catalog
        from platinum_frame import apply
        top, bot, _ref_top, _ref_bot = _frame_regions()
        found = {_LEGACY_FRAME_REGION_HASHES}
        for platform in load_catalog()["platforms"]:
            path = os.path.join(HERE, "assets", "frames", platform["id"] + ".png")
            with Image.open(path) as source:
                frame = source.convert("RGBA")
            for version in (frame, apply(frame)):
                found.add((hashlib.sha256(version.crop(top).tobytes()).hexdigest(),
                           hashlib.sha256(version.crop(bot).tobytes()).hexdigest()))
        _known_frame_ref = found
    return _known_frame_ref


_known_frame_ref = None


def is_steamcase_cover(path):
    """Recognize current and legacy Steam covers by their exact frame regions."""
    try:
        if Image is None or os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > MAX_DOWNLOAD:
            return False
        top, bot, ref_top, ref_bot = _frame_regions()
        with Image.open(path, formats=["PNG"]) as im:
            if im.size != SIZE:
                return False
            im = im.convert("RGBA")
        candidate_top, candidate_bot = im.crop(top).tobytes(), im.crop(bot).tobytes()
        if candidate_top == ref_top and candidate_bot == ref_bot:
            return True
        return (hashlib.sha256(candidate_top).hexdigest(),
                hashlib.sha256(candidate_bot).hexdigest()) in _known_frame_hashes()
    except Exception:
        return False


def find_our_covers(steam, user=None, progress=None, cancelled=None):
    """File names in Steam's grid folder (<appid>p.png) that are covers made by this app. Takes a few seconds for a big library."""
    grid = grid_dir(steam, user)
    names = sorted(n for n in os.listdir(grid) if _COVER_NAME.match(n)) if os.path.isdir(grid) else []
    out = []
    for i, n in enumerate(names, 1):
        if cancelled and cancelled():
            break
        if is_steamcase_cover(os.path.join(grid, n)):
            out.append(n)
        if progress and (i % 20 == 0 or i == len(names)):
            progress(i, len(names))
    return out


def find_other_art(steam, user=None, ours=()):
    """Custom portraits in the grid folder that this app did not make: art from SteamGridDB, from Steam's own menu, other formats.
    Returns (png names, jpg/jpeg/webp names)."""
    grid = grid_dir(steam, user)
    if not os.path.isdir(grid):
        return [], []
    files = [n for n in os.listdir(grid) if _is_plain_file(os.path.join(grid, n))]
    return sorted(n for n in files if _COVER_NAME.match(n) and n not in ours), sorted(n for n in files if _JPG_NAME.match(n))


def reset_to_default(steam, user=None, names=None, everything=False):
    """Remove our covers from Steam's grid folder so Steam shows its own default art again.
    Only files recognised as ours go; the files are moved into a normal backup, so restore_backup() undoes this.
    `names`: result of an earlier find_our_covers() (default: scan now).
    `everything`: also remove every other custom portrait (SteamGridDB, set by hand in Steam, any format), so no custom art is left.
    Returns {"removed", "backup", "account", "account_name"}."""
    grid = grid_dir(steam, user)
    acc = os.path.basename(os.path.dirname(os.path.dirname(grid)))
    info = {"account": acc, "account_name": account_label(steam, acc), "grid": grid}
    if names is None:
        names = find_our_covers(steam, user)
    names = [n for n in names if _COVER_NAME.match(n) and _is_plain_file(os.path.join(grid, n))]
    other = []
    if everything:
        extra_png, other = find_other_art(steam, user, names)
        names += extra_png
    if not names and not other:
        return dict(info, removed=0, backup=None)
    with _Lock(os.path.dirname(grid)):
        base = os.path.join(os.path.dirname(grid), BACKUP_PREFIX + time.strftime("%Y%m%d_%H%M%S"))
        backup, k = base, 1
        while True:
            try:
                os.makedirs(backup)
                break
            except FileExistsError:
                k += 1
                backup = "%s-%d" % (base, k)
        moved = []
        try:
            with open(os.path.join(backup, "manifest.json"), "w") as fh:
                json.dump({"added": [], "replaced": names, "moved": other}, fh)
            for n in names + other:
                os.replace(os.path.join(grid, n), os.path.join(backup, n))      # a move, not a copy: instant and no extra disk space
                moved.append(n)
        except OSError as e:
            for n in moved:
                try:
                    os.replace(os.path.join(backup, n), os.path.join(grid, n))
                except OSError:
                    pass
            shutil.rmtree(backup, ignore_errors=True)
            raise SteamcaseError("Could not remove the covers (%s). Nothing was changed." % e)
        return dict(info, removed=len(moved), backup=backup)


def list_backups(steam, user=None):
    """Backup folders for this account, newest first."""
    cfg = os.path.dirname(grid_dir(steam, user))
    if not os.path.isdir(cfg):
        return []
    return [os.path.join(cfg, d) for d in sorted(os.listdir(cfg), reverse=True) if d.startswith(BACKUP_PREFIX)]


def _portrait_name(name):
    return bool(_COVER_NAME.fullmatch(name) or _JPG_NAME.fullmatch(name))


def _portrait_files(grid):
    return sorted(n for n in os.listdir(grid) if _portrait_name(n)) if os.path.isdir(grid) else []


def _artwork_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def _check_artwork_file(path):
    if not _is_plain_file(path):
        raise SteamcaseError("Artwork file is missing or is a link: %s" % os.path.basename(path))
    size = os.path.getsize(path)
    if not 0 < size <= MAX_DOWNLOAD:
        raise SteamcaseError("Artwork file has an unsupported size: %s" % os.path.basename(path))
    if Image is None:
        raise SteamcaseError("Pillow is required to validate artwork images.")
    try:
        with Image.open(path, formats=["PNG", "JPEG", "WEBP"]) as image:
            if image.width * image.height > MAX_PIXELS:
                raise SteamcaseError("Artwork image is too large: %s" % os.path.basename(path))
            image.verify()
    except (OSError, ValueError) as exc:
        raise SteamcaseError("Artwork image cannot be read: %s" % os.path.basename(path)) from exc
    return size, _artwork_digest(path)


def export_artwork_backup(steam, destination, user=None, progress=None, shortcut_ids=()):
    """Export every locally stored portrait override, regardless of who created it.

    Steam's CDN defaults are absent from config/grid and therefore never counted.
    The destination is a new directory containing original filenames and manifest.json.
    """
    grid = grid_dir(steam, user)
    account = os.path.basename(os.path.dirname(os.path.dirname(grid)))
    destination = os.path.abspath(destination)
    if os.path.lexists(destination):
        raise SteamcaseError("The backup folder already exists. Choose a new name.")
    parent = os.path.dirname(destination)
    if not os.path.isdir(parent):
        raise SteamcaseError("The backup destination's parent folder does not exist.")
    temporary = tempfile.mkdtemp(prefix=".casecovers-export-", dir=parent)
    entries, skipped = [], []
    try:
        names = _portrait_files(grid)
        for index, name in enumerate(names, 1):
            source = os.path.join(grid, name)
            try:
                ident = int(name.split("p.", 1)[0])
                if not 0 < ident < 2 ** 32:
                    raise SteamcaseError("Artwork ID is outside Steam's supported range")
                _check_artwork_file(source)
                copied = os.path.join(temporary, name)
                shutil.copy2(source, copied)
                size, digest = _check_artwork_file(copied)
                entries.append({"id": ident, "filename": name,
                                "kind": "shortcut" if ident in shortcut_ids else "steam_or_unknown",
                                "size": size, "sha256": digest})
            except (OSError, SteamcaseError) as exc:
                copied = os.path.join(temporary, name)
                if os.path.lexists(copied):
                    os.remove(copied)
                skipped.append({"filename": name, "reason": str(exc)})
            if progress:
                progress(index, len(names), "Exporting local artwork")
        if not entries:
            detail = (" Skipped: " + "; ".join("%s: %s" % (item["filename"], item["reason"])
                                               for item in skipped[:3])) if skipped else ""
            raise SteamcaseError("No valid locally stored portrait artwork was found for this account. Steam CDN defaults cannot be exported." + detail)
        manifest = {"format": "case-covers-artwork", "version": 1, "account": account,
                    "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "files": entries,
                    "skipped": skipped}
        with open(os.path.join(temporary, "manifest.json"), "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, ensure_ascii=False)
        os.replace(temporary, destination)
        return {"path": destination, "account": account, "exported": len(entries),
                "skipped": skipped, "bytes": sum(item["size"] for item in entries)}
    finally:
        if os.path.isdir(temporary):
            shutil.rmtree(temporary, ignore_errors=True)


def inspect_artwork_backup(steam, backup_dir, user=None, shortcut_ids=None):
    """Validate a portable backup and preview every overwrite before import."""
    backup_dir = os.path.abspath(backup_dir)
    manifest_path = os.path.join(backup_dir, "manifest.json")
    if not _is_plain_file(manifest_path) or os.path.getsize(manifest_path) > 2 * 1024 * 1024:
        raise SteamcaseError("Choose a Case Covers artwork backup folder containing manifest.json.")
    try:
        with open(manifest_path, encoding="utf-8") as stream:
            manifest = json.load(stream)
        entries = manifest["files"]
        if (manifest.get("format") != "case-covers-artwork" or manifest.get("version") != 1 or
                not isinstance(entries, list) or not 0 < len(entries) <= MAX_APPS or
                not re.fullmatch(r"[0-9]+", str(manifest.get("account", "")))):
            raise ValueError("unsupported manifest")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
        raise SteamcaseError("The artwork backup manifest is damaged or unsupported.") from exc
    grid = grid_dir(steam, user)
    target_account = os.path.basename(os.path.dirname(os.path.dirname(grid)))
    current = _portrait_files(grid)
    current_by_id = {}
    for name in current:
        current_by_id.setdefault(int(name.split("p.", 1)[0]), []).append(name)
    rows, seen, issues = [], set(), []
    for entry in entries:
        try:
            name, ident, size, expected_hash = (entry["filename"], entry["id"],
                                                entry["size"], entry["sha256"])
            kind = entry.get("kind", "steam_or_unknown")
            if (not isinstance(name, str) or not _portrait_name(name) or name in seen or
                    type(ident) is not int or not 0 < ident < 2 ** 32 or
                    int(name.split("p.", 1)[0]) != ident or type(size) is not int or
                    not 0 < size <= MAX_DOWNLOAD or not isinstance(expected_hash, str) or
                    not re.fullmatch(r"[0-9a-f]{64}", expected_hash) or
                    kind not in ("shortcut", "steam_or_unknown")):
                raise ValueError("bad entry")
        except (TypeError, KeyError, ValueError, AttributeError) as exc:
            raise SteamcaseError("The artwork backup manifest contains an invalid file entry.") from exc
        seen.add(name)
        if (kind == "shortcut" or ident >= 2 ** 31) and shortcut_ids is not None and ident not in shortcut_ids:
            issues.append("%s: non-Steam shortcut ID is not present in this account" % name)
        source = os.path.join(backup_dir, name)
        try:
            actual_size, actual_hash = _check_artwork_file(source)
            if actual_size != size or actual_hash != expected_hash:
                raise SteamcaseError("Size or checksum does not match the manifest")
            if os.path.lexists(os.path.join(grid, name)):
                if not _is_plain_file(os.path.join(grid, name)):
                    raise SteamcaseError("Target artwork is a link or special file")
                status = "Identical" if _artwork_digest(os.path.join(grid, name)) == expected_hash else "Overwrite"
            else:
                status = "New"
        except (OSError, SteamcaseError) as exc:
            status = "Invalid: %s" % exc
            issues.append("%s: %s" % (name, exc))
        rows.append({"id": ident, "filename": name, "kind": kind, "size": size,
                     "sha256": expected_hash, "status": status,
                     "path": source if status in ("New", "Overwrite", "Identical") else None})
    imported_ids = {row["id"] for row in rows}
    removals = sorted(name for ident in imported_ids for name in current_by_id.get(ident, []) if name not in seen)
    removal_rows = [{"id": int(name.split("p.", 1)[0]), "filename": name,
                     "path": os.path.join(grid, name)} for name in removals]
    for name in removals:
        if not _is_plain_file(os.path.join(grid, name)):
            issues.append("%s: target artwork is a link or special file" % name)
    current_state = []
    for name in sorted(name for ident in imported_ids for name in current_by_id.get(ident, [])):
        path = os.path.join(grid, name)
        current_state.append((name, _artwork_digest(path) if _is_plain_file(path) else "not-regular"))
    token_data = {"entries": [(row["filename"], row["kind"], row["size"], row["sha256"], row["status"])
                              for row in rows],
                  "current": current_state, "removals": removals, "account": target_account}
    token = hashlib.sha256(json.dumps(token_data, sort_keys=True).encode("utf-8")).hexdigest()
    return {"path": backup_dir, "source_account": manifest["account"], "target_account": target_account,
            "rows": rows, "removals": removals, "removal_rows": removal_rows,
            "issues": issues, "token": token,
            "new": sum(row["status"] == "New" for row in rows),
            "overwrite": sum(row["status"] == "Overwrite" for row in rows),
            "identical": sum(row["status"] == "Identical" for row in rows),
            "can_import": not issues}


def import_artwork_backup(steam, backup_dir, user=None, expected=None, progress=None, shortcut_ids=None):
    """Restore a portable backup with a pre-change undo backup and rollback on failure."""
    grid = grid_dir(steam, user)
    cfg = os.path.dirname(grid)
    os.makedirs(grid, exist_ok=True)
    with _Lock(cfg):
        plan = inspect_artwork_backup(steam, backup_dir, user, shortcut_ids)
        if not plan["can_import"]:
            raise SteamcaseError("The backup has missing or invalid files. Nothing was changed: %s" % plan["issues"][0])
        if expected is not None and plan["token"] != expected:
            raise SteamcaseError("The backup or current artwork changed since the preview. Review it again before importing.")
        changed_ids = {row["id"] for row in plan["rows"] if row["status"] != "Identical"}
        changed_ids.update(int(name.split("p.", 1)[0]) for name in plan["removals"])
        if not changed_ids:
            return {"imported": 0, "removed": 0, "unchanged": len(plan["rows"]),
                    "backup": None, "account": plan["target_account"]}
        rows = [row for row in plan["rows"] if row["id"] in changed_ids]
        incoming = {row["filename"] for row in rows}
        current = [name for name in _portrait_files(grid)
                   if int(name.split("p.", 1)[0]) in changed_ids]
        staged = tempfile.mkdtemp(prefix=".casecovers-import-", dir=cfg)
        backup = None
        mutation_started = False
        try:
            for index, row in enumerate(rows, 1):
                source = os.path.join(backup_dir, row["filename"])
                copied = os.path.join(staged, row["filename"])
                if not _is_plain_file(source):
                    raise SteamcaseError("Artwork file is missing or is a link: %s" % row["filename"])
                shutil.copy2(source, copied)
                size, digest = _check_artwork_file(copied)
                if size != row["size"] or digest != row["sha256"]:
                    raise SteamcaseError("Artwork changed during import staging: %s" % row["filename"])
                if progress:
                    progress(index, len(rows) * 2 + len(current), "Validating import files")
            base = os.path.join(cfg, BACKUP_PREFIX + time.strftime("%Y%m%d_%H%M%S"))
            backup, suffix = base, 1
            while True:
                try:
                    os.makedirs(backup)
                    break
                except FileExistsError:
                    suffix += 1
                    backup = "%s-%d" % (base, suffix)
            for index, name in enumerate(current, 1):
                shutil.copy2(os.path.join(grid, name), os.path.join(backup, name))
                if progress:
                    progress(len(rows) + index, len(rows) * 2 + len(current), "Saving current artwork")
            manifest = {"added": sorted(incoming - set(current)), "replaced": current,
                        "moved": [], "operation": "artwork_import"}
            with open(os.path.join(backup, "manifest.json"), "w", encoding="utf-8") as stream:
                json.dump(manifest, stream, indent=2)
            mutation_started = True
            for name in current:
                if name not in incoming:
                    os.remove(os.path.join(grid, name))
            for index, row in enumerate(rows, 1):
                if row["status"] != "Identical":
                    _safe_copy(os.path.join(staged, row["filename"]), os.path.join(grid, row["filename"]))
                if progress:
                    progress(len(rows) + len(current) + index, len(rows) * 2 + len(current), "Restoring artwork")
            return {"imported": sum(row["status"] != "Identical" for row in rows),
                    "removed": len(plan["removals"]), "unchanged": plan["identical"],
                    "backup": backup, "account": plan["target_account"]}
        except Exception as exc:
            if mutation_started:
                try:
                    _undo(grid, backup, manifest)
                except Exception as rollback_error:
                    raise SteamcaseError("Import failed (%s); automatic rollback failed (%s). Original artwork is in %s." %
                                         (exc, rollback_error, backup)) from exc
            if backup:
                shutil.rmtree(backup, ignore_errors=True)
            raise SteamcaseError("Artwork import failed (%s). No changes were kept." % exc) from exc
        finally:
            shutil.rmtree(staged, ignore_errors=True)


def _undo(grid, backup_dir, m):
    """Put the replaced files back from backup_dir and remove the added ones. Caller holds the lock. Returns files touched."""
    n = 0
    for name in m.get("replaced", []):
        src = os.path.join(backup_dir, name)
        if os.path.exists(src) and not os.path.islink(src):          # a symlink here could smuggle another file into Steam's folder
            _safe_copy(src, os.path.join(grid, name))
            n += 1
    for name in m.get("added", []):
        p = os.path.join(grid, name)
        if os.path.lexists(p):
            os.remove(p)                                             # removes a symlink itself, never what it points to
            n += 1
    for name in m.get("moved", []):
        src = os.path.join(backup_dir, name)
        if _JPG_NAME.match(name) and _is_plain_file(src):
            os.replace(src, os.path.join(grid, name))                # hand-made art goes back where it was
            n += 1
    return n


_COVER_NAME = re.compile(r"^[0-9]{1,10}p\.png$")
_JPG_NAME = re.compile(r"^[0-9]{1,10}p\.(jpg|jpeg|webp)$")      # art set from Steam's menu or by SteamGridDB; Steam shows these before our .png
OTHER_EXT = ("jpg", "jpeg", "webp")


def _is_plain_file(path):
    return os.path.isfile(path) and not os.path.islink(path)


def restore_backup(steam, backup_dir, user=None, keep=False):
    """Undo one apply: put replaced files back and remove the ones that were added. Returns files touched.
    The backup is deleted afterwards (so the next restore goes one step further back) unless keep=True.
    Only real steamcase backups inside this account's config folder are accepted, and only files named <appid>p.png (or <appid>p.jpg, put back from the backup) are touched."""
    grid = grid_dir(steam, user)
    cfg = os.path.realpath(os.path.dirname(grid))
    real = os.path.realpath(backup_dir)
    if os.path.dirname(real) != cfg or not os.path.basename(real).startswith(BACKUP_PREFIX):
        raise SteamcaseError("That is not a steamcase backup of this Steam account.")
    mf = os.path.join(real, "manifest.json")
    if not os.path.exists(mf):
        raise SteamcaseError("That folder is not a steamcase backup: %s" % backup_dir)
    try:
        with open(mf) as fh:
            m = json.load(fh)
        names = [str(x) for x in m.get("replaced", []) + m.get("added", [])]
        jpgs = [str(x) for x in m.get("moved", [])]
    except (OSError, ValueError, AttributeError, TypeError, RecursionError, MemoryError, UnicodeError):
        raise SteamcaseError("The backup's manifest is damaged.")
    if not all(_portrait_name(n) for n in names) or not all(_JPG_NAME.match(n) for n in jpgs):
        raise SteamcaseError("The backup's manifest lists unexpected files; refusing to use it.")
    if m.get("operation") == "artwork_import" and any(
            not _is_plain_file(os.path.join(real, n)) for n in m.get("replaced", [])):
        raise SteamcaseError("The import's safety backup has missing files; refusing an incomplete restore.")
    with _Lock(cfg):
        n = _undo(grid, real, m)
        if not keep:
            shutil.rmtree(real, ignore_errors=True)
    return n


# ---------- command line ----------
def _collect(args):
    steam = steam_dir(args.steam_dir)
    return steam, load_games(steam, args.library)


def cmd_list(args):
    steam, games = _collect(args)
    print("Steam folder:", steam)
    rows = list_games(games, print)
    for appid, name in rows:
        print(appid, name)
    print("\n%d games%s" % (len(rows), "" if args.library else "  (installed only; add --library userdata.json for your whole library)"))


def cmd_make(args):
    steam, games = _collect(args)

    def progress(done, total, appid, name, status):
        if status == "ok":
            print("ok  ", appid, name)

    res = make_covers(games, os.path.abspath(args.out), args.only, args.force, args.skip_auto_art, progress, log=print)
    print("\n%d covers in %s | %d skipped (DLC/tools/non-games) | %d without portrait art" % (res["ok"], os.path.abspath(args.out), res["skipped"], len(res["missing"])))
    for appid, name in res["missing"]:
        print("  no art:", appid, name)
    for appid, name in res["failed"]:
        print("  failed (connection problem? run again to retry):", appid, name)


def cmd_apply(args):
    steam = steam_dir(args.steam_dir)
    if steam_running() and not args.yes:
        if args.close_steam:
            print("Closing Steam...")
            if not close_steam(steam):
                raise SteamcaseError("Steam did not close. Close it yourself and retry.")
        else:
            print("Steam seems to be running. Close it first (Steam > Exit), or pass --close-steam.")
            if input("Copy anyway? [y/N] ").strip().lower() != "y":
                raise SteamcaseError("Cancelled.")
    r = apply_covers(steam, args.covers, args.user)
    print("Steam account:", r["account_name"], "(folder %s)" % r["account"], "\nGrid folder:", r["grid"])
    if r["applied"]:
        print("Applied %d covers (%d replaced older files, %d already up to date). Backup: %s" % (r["applied"], r["replaced"], r["unchanged"], r["backup"]))
    else:
        print("Nothing to change: all %d covers were already in Steam." % r["unchanged"])
    if r["jpg_moved"]:
        print("Art you had set by hand in Steam (%d games) was moved into the backup; restore brings it back." % r["jpg_moved"])
    print("Start Steam to see them.")
    print("To undo: python steamcase.py restore")


def cmd_run(args):
    args.covers = args.out
    cmd_make(args)
    cmd_apply(args)


def cmd_reset(args):
    steam = steam_dir(args.steam_dir)
    print("Looking for covers made by this app (this can take a few seconds)...")
    names = find_our_covers(steam, args.user)
    if args.everything:
        extra, other = find_other_art(steam, args.user, names)
        print("%d covers made by this app and %d custom portraits from other sources (SteamGridDB, set by hand) will be removed; Steam goes back to its own default art." % (len(names), len(extra) + len(other)))
        names = names + extra
        if not names and not other:
            print("Nothing to reset.")
            return
    elif not names:
        print("None found. Nothing to reset.")
        return
    else:
        print("%d covers made by this app will be removed; Steam goes back to its own default art for them. Your own custom art is not touched. (--everything also removes art from other sources.)" % len(names))
    if steam_running() and not args.yes:
        if args.close_steam:
            print("Closing Steam...")
            if not close_steam(steam):
                raise SteamcaseError("Steam did not close. Close it yourself and retry.")
        else:
            print("Steam seems to be running. Close it first, or pass --close-steam.")
            if input("Continue anyway? [y/N] ").strip().lower() != "y":
                raise SteamcaseError("Cancelled.")
    elif not args.yes and input("Remove them? [y/N] ").strip().lower() != "y":
        raise SteamcaseError("Cancelled.")
    r = reset_to_default(steam, args.user, names, args.everything)
    print("Removed %d covers. Backup: %s\nTo bring them back: python steamcase.py restore" % (r["removed"], r["backup"]))


def cmd_restore(args):
    steam = steam_dir(args.steam_dir)
    backups = list_backups(steam, args.user)
    if not backups:
        raise SteamcaseError("No backups found.")
    if args.backup and os.path.basename(args.backup) != args.backup:
        raise SteamcaseError("--backup takes just the folder name (like grid_backup_20260101_120000), not a path.")
    target = os.path.join(os.path.dirname(backups[0]), args.backup) if args.backup else backups[0]
    if steam_running() and not args.yes:
        print("Steam seems to be running. Close it first so it picks the files up on next start.")
        if input("Restore anyway? [y/N] ").strip().lower() != "y":
            raise SteamcaseError("Cancelled.")
    n = restore_backup(steam, target, args.user)
    left = len(list_backups(steam, args.user))
    print("Restored from %s (%d files). %d older backup%s left; run restore again to go one step further back." % (target, n, left, "" if left == 1 else "s"))


def main():
    ap = argparse.ArgumentParser(description="Steam 'physical case' covers for your library.")
    ap.add_argument("--version", action="version", version="Case Covers %s" % APP_VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, make=False, apply_=False):
        p.add_argument("--steam-dir", help="Steam folder (auto-detected by default)")
        if make:
            p.add_argument("--library", metavar="JSON", help="whole-library list saved from " + LIBRARY_JSON_URL)
            p.add_argument("--out", default="covers", help="where covers are written (default: ./covers)")
        if apply_:
            p.add_argument("--covers", default="covers", help="folder with covers (default: ./covers)")
            p.add_argument("--user", help="Steam account folder id inside userdata/ (auto: most recent login)")
            p.add_argument("--yes", action="store_true", help="don't ask even if Steam is running")
            p.add_argument("--close-steam", action="store_true", help="close Steam automatically before copying")

    p = sub.add_parser("list", help="show detected games"); common(p, make=True); p.set_defaults(fn=cmd_list)
    for name, fn in (("make", cmd_make), ("run", cmd_run)):
        p = sub.add_parser(name, help=name + " covers" if name == "make" else "make + apply")
        common(p, make=True, apply_=(name == "run"))
        p.add_argument("--only", type=int, nargs="+", metavar="APPID", help="only these app IDs")
        p.add_argument("--force", action="store_true", help="rebuild covers that already exist")
        p.add_argument("--skip-auto-art", action="store_true", help=AUTO_ART_HELP)
        p.set_defaults(fn=fn)
    p = sub.add_parser("apply", help="copy covers into Steam"); common(p, apply_=True); p.set_defaults(fn=cmd_apply)
    p = sub.add_parser("reset", help="remove our covers from Steam so it shows its default art again"); common(p, apply_=True)
    p.add_argument("--everything", action="store_true", help="also remove custom portraits from other sources (SteamGridDB, set by hand)"); p.set_defaults(fn=cmd_reset)
    p = sub.add_parser("restore", help="undo an apply (newest backup by default)")
    p.add_argument("--steam-dir"); p.add_argument("--user"); p.add_argument("--yes", action="store_true")
    p.add_argument("--backup", help="backup folder name (see userdata/<id>/config/)")
    p.set_defaults(fn=cmd_restore)
    args = ap.parse_args()
    try:
        args.fn(args)
    except SteamcaseError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
