# Case Covers: detailed notes

[← Back to the README](../README.md)

- [Installation help](#installation-help)
- [Command line](#command-line)
- [Safety](#safety)
- [Steam compatibility](#steam-compatibility)
- [FAQ](#faq)

## Installation help

### Windows

Run `CaseCovers-Setup-windows.exe` for an installed app, or double-click `CaseCovers-windows.exe` for the portable one.

If "Windows protected your PC" appears, click **More info**, then **Run anyway**. The app isn't code-signed (that costs money), which is why Windows warns you. Some antivirus tools also flag apps of this kind.

The installer puts the app in a per-user folder you can change, and needs no administrator rights. Updates and uninstalls keep your settings and the SteamGridDB key stored in Windows Credential Manager.

### macOS

Download `CaseCovers-macos.zip` and double-click it to unzip. **Before you open the app**, run this in **Terminal** (change the path if the app isn't in Downloads), then double-click the app:

```bash
xattr -dr com.apple.quarantine ~/Downloads/CaseCovers.app
```

Why: macOS blocks any app that doesn't come from a paid Apple developer (about 99 USD a year, which a free project can't justify). That command removes the "downloaded from the internet" mark, so macOS opens the app normally. The app isn't harmful or damaged, and its source code is here for anyone to read.

If you open the app first instead, macOS shows **"CaseCovers" Not Opened: Apple could not verify it is free of malware**. Click **Done** (not Move to Trash), then open **System Settings**, **Privacy & Security**, scroll to **Security**, and click **Open Anyway** next to the CaseCovers message (it stays for about an hour; double-click the app again to bring it back). If the app then bounces in the Dock forever with no window, **restart your Mac** and use the Terminal command above instead. On macOS 14 or older you can also right-click the app and choose **Open**.

The first time you press **Apply to Steam**, macOS may say the app isn't allowed to control Steam. Allow it in the prompt (or in **System Settings**, **Privacy & Security**), then press the button again.

macOS support is **best effort**: it has only been tested on an Apple Silicon MacBook Air. The build is for Apple Silicon (M1 or newer). On an Intel Mac, run it [from source](../README.md#from-source).

### Linux and Steam Deck

On a Steam Deck, switch to **Desktop Mode** first. The app needs a desktop window, so it doesn't run in Gaming Mode.

Download `CaseCovers-linux` and open it. On a Steam Deck a small pop-up appears: click **Launch** and the app opens. If your file manager doesn't run it, make it executable and start it from a terminal:

```bash
chmod +x CaseCovers-linux
./CaseCovers-linux
```

## Command line

The command-line workflows remain available in a terminal:

```bash
python steamcase.py make --library userdata.json   # build covers
python steamcase.py apply --close-steam            # install them
python steamcase.py restore                        # undo the last apply
python steamcase.py reset                          # back to Steam's default art
python steamcase.py reset --everything             # ...also removing art from other sources
```

| Command | What it does |
|---|---|
| `list` | Show the games it found |
| `make` | Build covers into `./covers` |
| `apply` | Copy covers into Steam, with a backup |
| `run` | `make` then `apply` |
| `restore` | Undo the last apply (run again to go further back) |
| `reset` | Remove the covers this app made from Steam (`--everything` also removes custom art from other sources) |

Run `python steamcase.py -h` for all options, such as `--only`, `--skip-auto-art`, `--steam-dir` and `--user` (the account's folder number in Steam's `userdata`, to pick one of several accounts).

## Safety

- It only ever touches the portrait files (`<appid>p.png`, and `.jpg`, `.jpeg` or `.webp` ones that would hide a cover) in your Steam account's `config/grid` folder. Anything it moves is kept in the backup. It never touches your games or saves.
- Before every change it makes a backup of exactly what it changes, writes files atomically, and rolls back if anything fails.
- Non-Steam shortcuts are matched only by their existing ID in `shortcuts.vdf`; the file is read, never edited.
- Two open windows can't change Steam's folder at the same time.
- It never asks for a Steam password or elevated rights. SteamGridDB access uses a personal API key saved in the operating system credential store; only API requests send it to SteamGridDB.
- Files it reads from the internet must use HTTPS, are size-limited and checked as images before use.
- Steam's own CDN artwork is not stored on your computer, so Backup can't export it; it exports only locally stored custom portraits.

If you find a security problem, please [report it privately](../SECURITY.md).

## Steam compatibility

✅ Windows: tested on a real PC, and the automated tests pass <br>
✅ Linux and SteamOS (Steam in `~/.local/share/Steam`) <br>
🟡 macOS: tested on one Apple Silicon Mac (best effort)

If something doesn't work on your system, please [open an issue](../../../issues) with your system and what you saw.

## FAQ

<details>
<summary><b>It says my game list has no games in it</b></summary>

You weren't logged in to Steam in your browser when you saved the page. Steam doesn't show an error in that case; it gives an empty list. Click **Download your game list** again: it opens Steam's login page first, so log in there, then save the page you land on. If that page shows no games even though you just logged in, refresh it (F5, or Cmd+R on a Mac) before saving.

The file contains app IDs without an account identifier; only IDs with a game title in Steam's catalog appear in Library. **Local only** removes the saved import.

</details>

<details>
<summary><b>Why do some covers look blurry?</b></summary>

Many older or smaller games have no real portrait on Steam. Steam builds a stand-in from the wide header image. Tick **Skip blurry Steam artwork** in Batch before automatic generation to leave those games alone.

</details>

<details>
<summary><b>I set custom art by hand in Steam. Will these replace it?</b></summary>

Steam shows art you set by hand (or got from SteamGridDB) before these covers. **Apply to Steam** moves such art for the covered games into the backup, so the case is shown, and **Restore** brings it back. To clear all of it, enable **Reset all custom portraits** in Backup before **Reset to Steam default**.

</details>

<details>
<summary><b>Does it work for non-Steam games and shortcuts?</b></summary>

Yes. Search by name or import a local image for PNG export. To apply artwork to a non-Steam game already in Steam, select its existing ID with **Choose shortcut**; the app reads that ID from Steam's `shortcuts.vdf` without editing the shortcut.

</details>

<details>
<summary><b>How do I move my covers to another computer?</b></summary>

Use **Backup** to export the portrait artwork of a Steam account, then import that folder on the other computer. You can also copy Steam's `userdata/<id>/config/grid` folder directly.

</details>

<details>
<summary><b>Can I get the covers without running it?</b></summary>

Covers already made are on SteamGridDB: <https://www.steamgriddb.com/profile/76561198040695197/grids/1>.

</details>

<details>
<summary><b>Are screen readers supported?</b></summary>

No. The window works fully with the keyboard (Tab, Space, Enter), but the toolkit it uses can't talk to screen readers. The command line is the accessible alternative.

</details>

## Tkinter completion highlights

### Saved games page

Step 2 has an optional block, **Highlight my 100% games**. Games where you unlocked every achievement get a rosette at the top right, on top of the platform badges, and a "100% Complete" ribbon at the bottom. It works like step 1: the app cannot see your achievements by itself, so you save one more page from your own browser.

1. Click **Open my games page** (or **Copy link**). Your browser opens your Steam games page, sorted by achievements. Log in if it asks and wait until your games have loaded.
2. Save it (Ctrl+S, or Cmd+S on a Mac) as **"Webpage, Complete"** in Chrome or Firefox, named `games.html`. Your browser also saves a folder next to it. The app notices the file in your Downloads folder by itself, or you can click **Browse…** and pick it.
3. Choose how those games look: **Gold case** (the whole case turns gold), **Gold border** (a gold border around the outside of the case, which becomes about 5% smaller), **Normal case with ribbon** (your case stays as it is; this is the default once a page is loaded) or **No special case**. The choice can be picked once a page is loaded. Then click **Make covers**.

> [!NOTE]
> The saved page contains a temporary login token for your Steam account. The app only reads which games are at 100%: it never uses, stores or logs the token. You can delete `games.html` and its folder once the covers are made. The app never deletes your files itself.

Good to know:

* Only games that are already in your step 1 list can be highlighted.
* Steam's page shows progress only for games where you have unlocked at least one achievement. That is why only games at 100% are marked: there are no marks for games you have only started.
* Switching the choice, or saving the page again after you finish another game and clicking **Make covers**, rebuilds only the covers that change. If you make covers without loading a page, covers that are already highlighted keep their highlight.
* The page lists most of a library but not all of it. On the author's library it listed about 99% of the covers (509 of 515): a few old, free or hidden games are not on it and cannot be highlighted.
* This was only tried with Chrome, on Linux, with Steam set to Portuguese and to English; the saved pages gave exactly the same result. Firefox is expected to save the page the same way, and the app reads the progress without depending on the language of Steam's label, but other languages and browsers were not tested. Windows and macOS were not tested either, and neither was a real touchscreen.
