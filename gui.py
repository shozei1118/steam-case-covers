#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Diego Bergonsi. Part of steam-case-covers: https://github.com/diegobergonsi/steam-case-covers
"""steamcase GUI: three steps, no terminal.  Run:  python gui.py"""
import base64, io, os, queue, re, shutil, stat, subprocess, sys, tempfile, threading, time, webbrowser
import tkinter as tk
from tkinter import filedialog
import tkinter.font as tkfont

import completion
import steamcase as sc
import cover_workflow as cw
from platform_catalog import load_catalog
from widgets import (AMBER, BG, CARD, LINE, FG, MUTED, FAINT, ACCENT, RED, Card, StepBadge, RoundedButton, Switch, Bar, InfoBadge, ScrollFrame, Messages, Flow, HueSlider, ToneSlider, Swatch, Choice, px, set_scale)


def downloads_dir():
    """The user's Downloads folder (honours the Linux XDG setting)."""
    home = os.path.expanduser("~")
    cfg = os.path.join(home, ".config", "user-dirs.dirs")
    if os.path.exists(cfg):
        m = re.search(r'XDG_DOWNLOAD_DIR="([^"]+)"', open(cfg, errors="replace").read())
        if m:
            p = m.group(1).replace("$HOME", home)
            if os.path.isdir(p):
                return p
    return os.path.join(home, "Downloads")


SAVE_KEY = "Cmd+S" if sys.platform == "darwin" else "Ctrl+S"
GAMES_PAGE_URL = "https://steamcommunity.com/my/games/?tab=all&sort=achievements"     # the user's own games page, most achievements first
STYLES = [("gold-case", "Gold case"), ("gold-border", "Gold border"), ("ribbon", "Normal case with ribbon"), ("none", "No special case")]
PAGE_HELP = ("How to save the page: open it with the button and log in if asked. Wait until your games have loaded, press %s and save it as "
             "“Webpage, Complete” (Chrome or Firefox), named games.html. Your browser also saves a folder next to it.\n\n"
             "The saved file contains a temporary login token for your Steam account. This app only reads which games are at 100%%: "
             "it does not use or keep the token. You can delete the file and its folder afterwards." % SAVE_KEY)
messagebox = Messages()                      # themed dialogs; App sets the parent window


def pick_file(title, initialdir, kind=("JSON files", "*.json")):
    """File chooser. On Linux the plain Tk dialog looks very dated, so use the desktop's own (KDE or GNOME) when present.
    `kind` is (description, patterns separated by spaces) of the files to show first."""
    start = (initialdir if initialdir and os.path.isdir(initialdir) else os.path.expanduser("~")).rstrip("/") + "/"
    what, patterns = kind
    if sys.platform.startswith("linux"):
        if shutil.which("kdialog"):
            cmds = [["kdialog", "--title", title, "--getopenfilename", start, "%s|%s (%s)\n*|All files" % (patterns, what, patterns)]]
        elif shutil.which("zenity"):
            cmds = [["zenity", "--file-selection", "--title=" + title, "--filename=" + start, "--file-filter=%s | %s" % (what, patterns), "--file-filter=All files | *"]]
        else:
            cmds = []
        for cmd in cmds:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True)
            except OSError:
                break
            if r.returncode == 0:
                return r.stdout.strip()
            if r.returncode == 1:                    # the user pressed Cancel
                return ""
    return filedialog.askopenfilename(title=title, initialdir=start, filetypes=[(what, patterns), ("All files", "*.*")])


def _short(name, n=28):
    """Long account names must not push the buttons off the window."""
    return name if len(name) <= n else name[:n - 1] + "…"


def matching_shortcuts(options, query):
    """Preserve Steam's shortcut records and order while filtering by title or ID."""
    needle = query.strip().casefold()
    return [item for item in options if not needle or needle in item["name"].casefold()
            or needle in str(item["id"])]


class ShortcutPicker(tk.Toplevel):
    """Compact, keyboard-friendly selector for existing Steam shortcut records."""

    def __init__(self, parent, options):
        super().__init__(parent)
        self.options = tuple(options)
        self.filtered = []
        self.selected = None
        self.result = None
        self.title("Choose Steam shortcut · Case Covers")
        self.configure(bg=BG)
        self.transient(parent)
        self.resizable(True, True)
        if getattr(parent, "_icon", None):
            self.iconphoto(False, parent._icon)
        outer = tk.Frame(self, bg=LINE, padx=1, pady=1)
        outer.pack(fill="both", expand=True, padx=px(12), pady=px(12))
        body = tk.Frame(outer, bg=CARD, padx=px(22), pady=px(18))
        body.pack(fill="both", expand=True)
        tk.Label(body, text="Choose a Steam shortcut", bg=CARD, fg=FG,
                 font=("TkDefaultFont", 16, "bold")).pack(anchor="w")
        tk.Label(body, text="Search by game name or shortcut ID.", bg=CARD, fg=MUTED).pack(
            anchor="w", pady=(px(6), px(14)))
        self.query = tk.StringVar()
        self.search = tk.Entry(body, textvariable=self.query, bg=BG, fg=FG,
                               insertbackground=FG, relief="flat", highlightthickness=1,
                               highlightbackground=LINE, highlightcolor=ACCENT)
        self.search.pack(fill="x", ipady=px(7))
        self.count = tk.Label(body, text="", bg=CARD, fg=MUTED, anchor="w")
        self.count.pack(fill="x", pady=(px(8), px(5)))
        list_area = tk.Frame(body, bg=CARD)
        list_area.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(list_area, height=1, bg=BG, fg=FG, selectbackground=ACCENT,
                                  selectforeground="#0b141d", exportselection=False,
                                  activestyle="none", borderwidth=0, highlightthickness=1,
                                  highlightbackground=LINE)
        vertical = tk.Scrollbar(list_area, orient="vertical", command=self.listbox.yview,
                                width=px(14), troughcolor=BG, bg=LINE, activebackground=ACCENT)
        horizontal = tk.Scrollbar(list_area, orient="horizontal", command=self.listbox.xview,
                                  width=px(14), troughcolor=BG, bg=LINE, activebackground=ACCENT)
        self.listbox.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        vertical.pack(side="right", fill="y")
        horizontal.pack(side="bottom", fill="x")
        self.listbox.pack(side="left", fill="both", expand=True)
        self.name = tk.Label(body, text="Select a game to continue.", bg=CARD, fg=FG,
                             justify="left", anchor="w", wraplength=px(500))
        self.name.pack(fill="x", pady=(px(10), 0))
        self.identifier = tk.Label(body, text="", bg=CARD, fg=MUTED, anchor="w")
        self.identifier.pack(fill="x", pady=(px(3), px(10)))
        body.bind("<Configure>", lambda event: self.name.configure(
            wraplength=max(px(180), event.width - px(44))), add="+")
        footer = tk.Frame(body, bg=CARD)
        footer.pack(fill="x")
        self.select_button = RoundedButton(footer, "Select", self._accept, primary=True, state="disabled")
        self.select_button.pack(side="right")
        RoundedButton(footer, "Cancel", self._cancel).pack(side="right", padx=(0, px(8)))
        self.query.trace_add("write", lambda *_: self._refresh())
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self.listbox.bind("<Double-Button-1>", lambda _event: self._accept())
        self.listbox.bind("<Return>", lambda _event: self._accept())
        self.bind("<Escape>", lambda _event: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._refresh()
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        width = min(px(600), screen_w - px(40))
        height = min(px(550), screen_h - px(80))
        self.geometry("%dx%d+%d+%d" % (width, height,
                      max(0, parent.winfo_rootx() + (parent.winfo_width() - width) // 2),
                      max(0, parent.winfo_rooty() + (parent.winfo_height() - height) // 2)))
        self.minsize(min(px(420), width), min(px(430), height))

    def _refresh(self):
        self.filtered = matching_shortcuts(self.options, self.query.get())
        self.listbox.delete(0, "end")
        if self.filtered:
            self.listbox.insert("end", *(item["name"] for item in self.filtered))
        self.count.configure(text="%d of %d shortcuts" % (len(self.filtered), len(self.options)))
        self.selected = None
        self.select_button.configure(state="disabled")
        self.name.configure(text="Select a game to continue." if self.filtered else "No matching shortcuts.")
        self.identifier.configure(text="")

    def _on_select(self, _event=None):
        indexes = self.listbox.curselection()
        if not indexes or indexes[0] >= len(self.filtered):
            return
        self.selected = self.filtered[indexes[0]]
        self.name.configure(text=self.selected["name"])
        self.identifier.configure(text="Steam shortcut ID: %s" % self.selected["id"])
        self.select_button.configure(state="normal")

    def _accept(self):
        if self.selected is not None:
            self.result = self.selected["id"]
            self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()

    def show(self):
        self.wait_visibility()
        self.grab_set()
        self.search.focus_set()
        self.wait_window()
        return self.result


class App(tk.Tk):
    def __init__(self, downloads=None, covers_dir=None, screen_h=None):
        super().__init__()
        self.covers_dir = covers_dir or sc.default_covers_dir()
        self.cover_files = []             # covers built by the last automatic run
        self.running = False
        self.busy = False                 # step 3 (apply/restore) in progress
        self.applied = False              # covers were added to Steam in this session
        self.last_apply_backup = None
        self.last_apply_keys = ()
        self.events = queue.Queue()
        self.cancel_flag = threading.Event()
        self.downloads = downloads or downloads_dir()
        self.started = time.time()
        self._reported = {}               # path -> signature of the files we already complained about
        self._last_error = ""
        self._seen = {}                   # path -> (size, mtime) from the last poll, to wait for a finished download
        self.title("Case Covers")
        messagebox.parent = self
        try:                                           # window / taskbar icon
            self._icon = tk.PhotoImage(master=self, file=os.path.join(sc.HERE, "assets", "icon.png"))
            self.iconphoto(True, self._icon)
        except tk.TclError:
            pass
        self.configure(bg=BG)
        self._style()
        set_scale(self)

        self.steam_on = False             # kept fresh by a background thread: asking the OS for processes can take long on Windows
        self._quit = threading.Event()
        threading.Thread(target=self._watch_steam, daemon=True).start()
        self._thumb_tasks = queue.Queue()
        for _ in range(4):
            threading.Thread(target=self._thumbnail_loop, daemon=True).start()
        self._collapse = False            # folding locked steps starts after the window has been sized for all of them
        self.account = None               # Steam account folder chosen by the user (None: the one Steam used last)
        self.library_path = None          # chosen userdata.json
        self.installed_only = tk.BooleanVar(value=False)
        self.skip_auto = tk.BooleanVar(value=False)
        self.hue = tk.IntVar(value=0)     # case colour: degrees turned from the original blue
        self.sat = tk.IntVar(value=100)   # its colourfulness and brightness, 0..100 (100: as the original blue)
        self.val = tk.IntVar(value=100)
        self._preview_job = None
        self._setting_tone = False
        self.restart_steam = tk.BooleanVar(value=True)
        self.games_page = None            # the saved Steam games page in use (path), or None: covers keep the 100% look they have
        self.completed = None             # app ids at 100% on that page; only these numbers are kept from it, never its text
        self.completion_style = tk.StringVar(value="ribbon")       # one of sc.TREATMENTS, or "none"
        self.page_pending = 0             # games pages being read on a worker thread
        self._page_req = 0                # the newest of those; older answers are dropped
        self._page_tried = {}             # path -> (size, mtime) of pages in Downloads already read once

        self._wrapped, self._wrap_width, self._head_narrow = [], 0, False
        self.scroller = ScrollFrame(self)
        self.scroller.pack(fill="both", expand=True)
        self.holder = self.scroller.inner
        self._thumb_cache = {}
        head = tk.Frame(self.holder, bg=BG)
        self.header = head
        head.pack(fill="x", padx=px(28), pady=(px(24), px(14)))
        brand = tk.Frame(head, bg=BG)
        brand.pack(side="left")
        if getattr(self, "_icon", None):
            self._icon_small = self._icon.subsample(4 if px(1) == 1 else 3)
            tk.Label(brand, image=self._icon_small, bg=BG).pack(side="left", padx=(0, px(16)))
        titles = tk.Frame(brand, bg=BG)
        titles.pack(side="left")
        tk.Label(titles, text="Case Covers", bg=BG, fg=FG, font=("TkDefaultFont", 22, "bold")).pack(anchor="w")
        tk.Label(titles, text="Put every game in your library in a physical case.", bg=BG, fg=MUTED).pack(anchor="w")
        actions = tk.Frame(head, bg=BG)
        actions.pack(side="right")
        self.btn_settings = RoundedButton(actions, "⚙", self.open_settings, bg=BG, quiet=True)
        self.btn_settings.pack(side="right")
        self.btn_update = RoundedButton(actions, "Check for updates", self.check_update, bg=BG, quiet=True)
        self.btn_update.pack(side="right", padx=(0, px(8)))
        self._header_stacked = False
        head.bind("<Configure>", lambda event: self._layout_header(event.width, brand, actions), add="+")
        self.settings_window = None

        self.columns = tk.Frame(self.holder, bg=BG)
        self.columns.pack(fill="x")
        self.left_column = tk.Frame(self.columns, bg=BG)
        self.right_column = tk.Frame(self.columns, bg=BG)
        self._column_mode = None
        self.columns.bind("<Configure>", lambda event: self._layout_columns(event.width), add="+")
        self.step1 = self._card("1", "Get your game list", self.left_column)
        self.step2 = self._card("2", "Make the covers", self.left_column)
        self.step3 = self._card("3", "Add them to Steam", self.left_column)
        self._build_step1(self.step1)
        self._build_step2(self.step2)
        self._build_step3(self.step3)
        self.manual_body = self._card("4", "Choose and edit covers", self.right_column)
        self.manual_card = self.manual_body.master.master
        self.manual_toggle = RoundedButton(self.manual_body.head, "Collapse", self.toggle_manual, quiet=True)
        self.manual_toggle.pack(side="right")
        self.manual_body.pack_configure(fill="both", expand=True)
        self.manual_scroller = ScrollFrame(self.manual_body, bg=CARD)
        self.manual_scroller.pack(fill="both", expand=True)
        self.manual_content = self.manual_scroller.inner
        self._build_manual(self.manual_content)
        self.manual_actions = tk.Frame(self.manual_body, bg=CARD)
        self.manual_actions.pack(side="bottom", fill="x", pady=(px(8), 0))
        self.btn_manual_apply = RoundedButton(self.manual_actions, "Apply to Steam", self._manual_apply, primary=True)
        self.btn_manual_apply.pack(side="left")
        self.btn_manual_export = RoundedButton(self.manual_actions, "Export PNG", self._manual_export_selected)
        self.btn_manual_export.pack(side="left", padx=px(8))
        self._manual_update_actions()
        self.manual_expanded = True
        self.scroller.canvas.bind("<Configure>", lambda _event: self.after_idle(self._sync_manual_height), add="+")
        self.left_column.bind("<Configure>", lambda _event: self.after_idle(self._sync_manual_height), add="+")
        self.manual_content.bind("<Configure>", lambda _event: self.after_idle(self._sync_manual_height), add="+")
        self.refresh_step1()
        self.refresh_step3()
        self._timers = [self.after(1500, self.watch_downloads), self.after(100, self.poll_events), None]
        self._tick_steam_note()
        self.refresh_steam_games()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.update_idletasks()
        want_w = self.holder.winfo_reqwidth()
        room = (screen_h or self.winfo_screenheight()) - px(110)               # title bar + taskbar
        minimum_w = min(px(640), self.winfo_screenwidth() - px(40))
        width = min(max(want_w + px(14), px(1360)), self.winfo_screenwidth() - px(40))
        height = min(px(860), max(room, px(420)))
        self.geometry("%dx%d+%d+%d" % (width, height,
                      max(0, (self.winfo_screenwidth() - width) // 2),
                      max(0, (self.winfo_screenheight() - height - px(40)) // 2)))
        self.minsize(minimum_w, min(px(420), self.winfo_screenheight() - px(80)))
        self.resizable(True, True)
        self._collapse = True
        self.update_steps()

    def _watch_steam(self):
        while not self._quit.is_set():
            try:
                self.steam_on = bool(sc.steam_running())
            except Exception:
                pass
            self._quit.wait(3)

    def on_close(self):
        if self.busy:
            messagebox.showinfo("Please wait", "Steam's artwork is being changed. Closing now could leave it half-done. "
                                               "Wait a few seconds, then close the window.")
            return
        self.destroy()

    def destroy(self):
        self.cancel_flag.set()
        self._quit.set()
        for t in list(getattr(self, "_timers", [])) + [getattr(self, "_preview_job", None)]:
            if not t:
                continue
            try:
                self.after_cancel(t)
            except (tk.TclError, ValueError):
                pass
        super().destroy()

    # ----- look -----
    def _layout_header(self, width, brand, actions):
        stacked = width < brand.winfo_reqwidth() + actions.winfo_reqwidth() + px(8)
        if stacked == self._header_stacked:
            return
        self._header_stacked = stacked
        brand.pack_forget()
        actions.pack_forget()
        if stacked:
            brand.pack(fill="x")
            actions.pack(anchor="e")
        else:
            brand.pack(side="left")
            actions.pack(side="right")

    def _layout_columns(self, width):
        # Side by side when both cards have room; one below the other on small displays.
        mode = "wide" if width >= px(1260) else "stacked"
        if mode == self._column_mode:
            return
        self._column_mode = mode
        self.left_column.pack_forget()
        self.right_column.pack_forget()
        if mode == "wide":
            self.left_column.pack(side="left", fill="both", expand=True)
            self.right_column.pack(side="left", fill="both", expand=True)
        else:
            self.left_column.pack(fill="x")
            self.right_column.pack(fill="x")
        self.after_idle(self._sync_manual_height)

    def _sync_manual_height(self):
        if not hasattr(self, "manual_scroller"):
            return
        if self._column_mode == "wide" and getattr(self, "manual_expanded", False):
            viewport = self.scroller.canvas.winfo_height() - self.header.winfo_height() - px(60)
            card_height = max(self.left_column.winfo_reqheight() - px(14), viewport)
            height = max(px(320), card_height - self.manual_body.head.winfo_reqheight()
                         - self.manual_actions.winfo_reqheight() - px(48))
        else:
            height = min(max(px(320), self.manual_content.winfo_reqheight()), px(520))
        if int(self.manual_scroller.canvas.cget("height")) != height:
            self.manual_scroller.canvas.configure(height=height)

    def _style(self):
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            tkfont.nametofont(name).configure(size=11)          # a little larger than the 10 pt default

    def _card(self, num, title, parent=None):
        card = Card(parent or self.holder)
        card.pack(fill="x", padx=px(12) if parent else px(28), pady=px(7))
        head = tk.Frame(card.body, bg=CARD)
        head.pack(fill="x")
        badge = StepBadge(head, num)
        badge.pack(side="left")
        title_lbl = tk.Label(head, text=title, bg=CARD, fg=FG, font=("TkDefaultFont", 14, "bold"))
        title_lbl.pack(side="left", padx=px(12))
        hint = tk.Label(head, text="", bg=CARD, fg=FAINT)
        hint.pack(side="left")
        body = tk.Frame(card.body, bg=CARD)
        body.pack(fill="x", pady=(px(12), 0))
        body.badge, body.title_lbl, body.hint, body.head, body.folded = badge, title_lbl, hint, head, False
        return body

    def _row(self, parent, pady=None):
        r = tk.Frame(parent, bg=CARD)
        r.pack(fill="x", pady=px(4) if pady is None else pady)       # px() here, not as a default: defaults run before the scale is known
        return r

    def _flow(self, parent, pady=None):
        r = Flow(parent, bg=CARD)
        r.pack(fill="x", pady=px(4) if pady is None else pady)
        return r

    def _wrap(self, label, cap=None):
        """Register a label whose wrap width follows the window (and never exceeds cap)."""
        label.configure(wraplength=cap or px(620))      # first size; _rewrap takes over once the window is on screen
        self._wrapped.append((label, cap))
        return label

    def _rewrap(self, _e=None):
        width = self.holder.winfo_width()
        if width < 2 or width == self._wrap_width:
            return
        self._wrap_width = width
        room = max(px(200), width - px(2 * 28) - px(44) - px(4))
        for label, cap in self._wrapped:
            label.configure(wraplength=min(room, cap) if cap else room)
        narrow = width < px(640)                    # the header's button drops under the title instead of squeezing it
        if narrow != self._head_narrow:
            self._head_narrow = narrow
            if narrow:
                self.btn_update.grid_configure(row=1, column=1, sticky="w", pady=(px(8), 0))
            else:
                self.btn_update.grid_configure(row=0, column=2, sticky="e", pady=0)
        self._tagline.configure(wraplength=max(px(160), width - px(2 * 28) - px(80)))

    def _note(self, parent, text):
        label = tk.Label(parent, text=text, bg=CARD, fg=MUTED, justify="left", wraplength=px(620), anchor="w")
        label.pack(fill="x", pady=(0, px(6)))
        self._wrap_to_parent(parent, label)

    def _wrap_to_parent(self, parent, label):
        parent.bind("<Configure>", lambda event: label.configure(
            wraplength=max(px(180), event.width - px(8))), add="+")

    def open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_set()
            return
        window = tk.Toplevel(self)
        self.settings_window = window
        window.title("Settings · Case Covers")
        window.configure(bg=BG)
        window.transient(self)
        window.resizable(True, True)
        if getattr(self, "_icon", None):
            window.iconphoto(False, self._icon)
        outer = Card(window)
        outer.pack(fill="both", expand=True, padx=px(14), pady=px(14))
        body = outer.body
        tk.Label(body, text="Settings", bg=CARD, fg=FG,
                 font=("TkDefaultFont", 16, "bold")).pack(anchor="w")
        tk.Label(body, text="SteamGridDB API key", bg=CARD, fg=FG,
                 font=("TkDefaultFont", 12, "bold")).pack(anchor="w", pady=(px(18), px(5)))
        self.settings_key = tk.Entry(body, show="•", bg=BG, fg=FG, insertbackground=FG,
                                     relief="flat", highlightthickness=1, highlightbackground=LINE)
        self.settings_key.pack(fill="x", ipady=px(7))
        note = tk.Label(body, text="Saved keys stay in the system credential store. The existing key is never displayed here.",
                        bg=CARD, fg=MUTED, justify="left", anchor="w")
        note.pack(fill="x", pady=(px(8), px(10)))
        body.bind("<Configure>", lambda event: note.configure(wraplength=max(px(220), event.width - px(8))), add="+")
        r = self._row(body)
        RoundedButton(r, "Check and save key", self._settings_save, primary=True).pack(side="left")
        r = self._row(body)
        RoundedButton(r, "Verify stored key", self._settings_verify_stored).pack(side="left")
        RoundedButton(r, "Delete key", self._settings_delete).pack(side="left", padx=px(8))
        self.settings_status = tk.Label(body, text="", bg=CARD, fg=MUTED,
                                        justify="left", anchor="w")
        self.settings_status.pack(fill="x", pady=(px(10), px(8)))
        body.bind("<Configure>", lambda event: self.settings_status.configure(
            wraplength=max(px(220), event.width - px(8))), add="+")
        RoundedButton(body, "Close", window.destroy, quiet=True).pack(anchor="e")
        self._settings_refresh_state()
        window.update_idletasks()
        height = max(px(440), body.winfo_reqheight() + px(80))
        window.geometry("%dx%d+%d+%d" % (px(500), min(height, self.winfo_screenheight() - px(80)),
                                          self.winfo_rootx() + px(45), self.winfo_rooty() + px(45)))
        window.minsize(px(390), min(height, self.winfo_screenheight() - px(80)))
        window.bind("<Escape>", lambda _event: window.destroy())
        self.settings_key.focus_set()

    def _settings_refresh_state(self):
        try:
            stored = bool(cw.load_api_key())
            self.settings_status.configure(text="Key stored securely." if stored else "No key stored.", fg=MUTED)
        except sc.SteamcaseError as exc:
            self.settings_status.configure(text=str(exc), fg=RED)

    def _settings_result(self, text, color=MUTED, clear=False):
        window = self.settings_window
        if not window or not window.winfo_exists():
            return
        if clear:
            self.settings_key.delete(0, "end")
        self.settings_status.configure(text=text, fg=color)

    def _settings_save(self):
        key = self.settings_key.get().strip()
        if not key:
            self._settings_result("Enter a new key first.", RED)
            return
        self._settings_result("Checking key…")
        def work():
            try:
                self._manual_client(key).verify_key()
                cw.save_api_key(key)
                self.events.put(("settings_key_saved",))
            except sc.SteamcaseError as exc:
                self.events.put(("settings_error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def _settings_verify_stored(self):
        self._settings_result("Checking stored key…")
        def work():
            try:
                self._manual_client().verify_key()
                self.events.put(("settings_key_checked",))
            except sc.SteamcaseError as exc:
                self.events.put(("settings_error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def _settings_delete(self):
        self._settings_result("Deleting key…")
        def work():
            try:
                cw.save_api_key("")
                self.events.put(("settings_key_deleted",))
            except sc.SteamcaseError as exc:
                self.events.put(("settings_error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def _set_state(self, body, enabled):
        st = "normal" if enabled else "disabled"

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, (RoundedButton, Switch, HueSlider, ToneSlider, Swatch)):
                    c.configure(state=st)
                walk(c)
        walk(body)

    def update_steps(self):
        """Badges and titles show where you are: locked, active or done."""
        ready = self.installed_only.get() or bool(self.library_path)
        s1 = "done" if ready else "active"
        s2 = "locked" if not ready else "done" if self.cover_files else "active"
        queued = any(item.get("verified_steam_id") for item in self.manual_queue)
        s3 = "done" if queued and self.applied else "active" if (queued or self.has_backup() or self.has_grid_art()) else "locked"   # Restore or Reset alone also unlock it
        for body, status, why in ((self.step1, s1, ""), (self.step2, s2, "Finish step 1 first"), (self.step3, s3, "Make the covers first")):
            body.badge.set(status)
            body.title_lbl.configure(fg=FAINT if status == "locked" else FG)
            fold = self._collapse and status == "locked"          # a step you cannot use yet is one line, not a wall of greyed-out controls
            if fold != body.folded:
                body.folded = fold
                if fold:
                    body.pack_forget()
                else:
                    body.pack(fill="x", pady=(px(12), 0))
            body.hint.configure(text="· " + why if fold else "")

    # ----- step 1 -----
    def _build_step1(self, body):
        self._note(body, "Steam keeps your game list on a web page. Click the button and log in if it asks. "
                         "A page of text appears: press %s and save it, keeping the name userdata.json. "
                         "This app notices the file by itself." % SAVE_KEY)
        r = self._flow(body)
        r.add(RoundedButton(r, "Download your game list", self.open_download_page, primary=True))
        r.add(RoundedButton(r, "Browse…", self.browse, quiet=True), px(10))
        r.add(RoundedButton(r, "Copy link", self.copy_link, quiet=True), px(10))
        r = self._row(body)
        self.sw_installed = Switch(r, "Only my installed games (no file needed)", self.installed_only, self.on_installed_only)
        self.sw_installed.pack(side="left")
        InfoBadge(r, sc.FAMILY_HELP).pack(side="left", padx=px(6))
        self.step1_status = self._wrap(tk.Label(body, text="Waiting for the saved game list (userdata.json)…", bg=CARD, fg=MUTED, anchor="w", justify="left"))
        self.step1_status.pack(fill="x", pady=(px(8), 0))
        self._wrap_to_parent(body, self.step1_status)

    def open_download_page(self):
        try:
            webbrowser.open(sc.library_login_url())
        except Exception:
            pass
        # webbrowser cannot tell us whether a browser really opened, so always show the way out
        self.step1_status.configure(text="Opening your browser… Log in to Steam if it asks. You'll then see a page of plain text: save it as userdata.json (%s) and I'll pick it up. "
                                         "Nothing opened? Click “Copy link” and paste it into your browser." % SAVE_KEY, fg=MUTED)

    def copy_link(self):
        self.clipboard_clear()
        self.clipboard_append(sc.library_login_url())
        self.update()                               # keeps the text on the clipboard on some systems
        self.step1_status.configure(text="Link copied. Paste it into your browser, log in if asked, then save the page as userdata.json (%s)." % SAVE_KEY, fg=ACCENT)

    def browse(self):
        path = pick_file("Choose your userdata.json", self.downloads)
        if path:
            self.load_library(path, ask=True)

    def load_library(self, path, ask=False):
        """Check the file and use it. Returns True on success. With ask=True, errors pop up."""
        try:
            n = len(sc.owned_ids(path))
        except sc.SteamcaseError as e:
            self._last_error = str(e)
            if ask:
                messagebox.showerror("That file doesn't look right", str(e))
            return False
        self.library_path = path
        self.installed_only.set(False)
        self.step1_status.configure(text="Got it: %s (%d items in your library)." % (os.path.basename(path), n), fg=ACCENT)
        self.refresh_step1()
        self.refresh_steam_games()
        return True

    def on_installed_only(self):
        self.refresh_step1()
        self.refresh_steam_games()

    def refresh_step1(self):
        """Step 2 unlocks once we have a library file or the user chose installed games only."""
        ready = self.installed_only.get() or bool(self.library_path)
        if self.installed_only.get():
            self.step1_status.configure(text="Using installed games only.", fg=ACCENT)
        elif not self.library_path:
            self.step1_status.configure(text="Waiting for userdata.json…", fg=MUTED)
        self._set_state(self.step2, ready and not self.running)
        if self.page_pending:
            self.btn_make.configure(state="disabled")        # wait for the page: Make covers must not use the one read before
        self._refresh_choice()
        self.btn_cancel.configure(state="normal" if self.running else "disabled")
        self.update_steps()

    def watch_downloads(self):
        """Every 1.5 s: look for a new, finished, valid userdata*.json in Downloads."""
        try:
            if not self.library_path and os.path.isdir(self.downloads):
                for fn in os.listdir(self.downloads):
                    if not (fn.lower().startswith("userdata") and fn.lower().endswith(".json")):
                        continue
                    p = os.path.join(self.downloads, fn)
                    st = os.stat(p)
                    if st.st_mtime < self.started:
                        continue
                    sig = (st.st_size, st.st_mtime)
                    if self._seen.get(p) == sig:                                # unchanged since last poll = finished
                        if self.load_library(p):
                            break
                        if self._reported.get(p) != sig and self._last_error:      # say why, once (e.g. saved while logged out)
                            self._reported[p] = sig
                            self.step1_status.configure(text="%s: %s" % (fn, self._last_error), fg=RED)
                    self._seen[p] = sig
        except OSError:
            pass
        if not self.games_page and not self.page_pending:
            self._watch_page()
        self._timers[0] = self.after(1500, self.watch_downloads)

    def _watch_page(self):
        """A new, finished games*.html (or .htm) in Downloads is read once, on a worker thread. Its error, if any, shows once per version of the file.
        The folder the browser saves next to the page is not a file, so it is skipped."""
        try:
            names = os.listdir(self.downloads)
        except OSError:
            return
        for fn in names:
            low = fn.lower()
            if not (low.startswith("games") and low.endswith((".html", ".htm"))):
                continue
            p = os.path.join(self.downloads, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_mtime < self.started or st.st_size > completion.MAX_GAMES_PAGE:
                continue
            sig = (st.st_size, st.st_mtime)
            if self._seen.get(p) == sig and self._page_tried.get(p) != sig:      # unchanged since last poll = finished; not read in this version yet
                self._page_tried[p] = sig
                self.load_games_page(p)
                break
            self._seen[p] = sig

    # ----- step 2 -----
    def _build_step2(self, body):
        self._note(body, "Downloads each game's artwork from Steam and builds the covers on your computer.")
        self._build_colour(body)
        self._build_completion(body)
        r = self._row(body)
        self.sw_skip = Switch(r, "Skip blurry covers", self.skip_auto)
        self.sw_skip.pack(side="left")
        InfoBadge(r, sc.AUTO_ART_HELP).pack(side="left", padx=px(6))
        self.row_make = r = self._flow(body, pady=px(6))
        self.btn_make = RoundedButton(r, "Make covers", self.start_make, primary=True)
        r.add(self.btn_make)
        self.btn_cancel = RoundedButton(r, "Cancel", self.cancel_make, state="disabled")
        r.add(self.btn_cancel, px(10))
        self.btn_folder = RoundedButton(r, "Open covers folder", self.open_covers_folder)
        self.progress = Bar(body)
        self.progress.pack(fill="x", pady=(px(10), px(6)))
        self.step2_status = self._wrap(tk.Label(body, text="Not started.", bg=CARD, fg=MUTED, anchor="w", justify="left"))
        self.step2_status.pack(fill="x")
        self._wrap_to_parent(body, self.step2_status)
        self.preview = Flow(body, bg=CARD)            # a few finished covers: the payoff of this step
        self._thumbs = []

    def _build_colour(self, body):
        """Cover colour: three sliders (colour, colourfulness, brightness) on the left, a live preview of a cover on the right (it wraps under
        on a narrow window), and a row of ready-made swatches below them (six colours, then three greys) that wraps as well."""
        box = self._flow(body, pady=px(6))
        left = tk.Frame(box, bg=CARD)
        head = tk.Frame(left, bg=CARD)
        head.pack(fill="x")
        tk.Label(head, text="Cover colour", bg=CARD, fg=FG, font=("TkDefaultFont", 11, "bold")).pack(side="left")
        self.colour_name = tk.Label(head, text="Original", bg=CARD, fg=MUTED)
        self.colour_name.pack(side="right", padx=(px(12), 0))
        grid = tk.Frame(left, bg=CARD)
        grid.pack(fill="x", pady=(px(4), 0))
        self.slider = HueSlider(grid, self.hue, sc.case_color)
        # the tracks show what each slider does to the case in its current colour: grey to vivid, black to bright
        self.sat_slider = ToneSlider(grid, self.sat, lambda v: sc.case_color(self.hue.get() % 360, v, self.val.get()), depends=(self.hue, self.val))
        self.val_slider = ToneSlider(grid, self.val, lambda v: sc.case_color(self.hue.get() % 360, self.sat.get(), v), depends=(self.hue, self.sat))
        self.colour_hint = tk.Label(grid, text="", bg=CARD, fg=MUTED, anchor="w")             # always gridded, so its row never changes height
        for row, (text, slider) in enumerate((("Colour", self.slider), ("Colourfulness", self.sat_slider), ("Brightness", self.val_slider))):
            tk.Label(grid, text=text, bg=CARD, fg=MUTED, anchor="w").grid(row=2 * row, column=0, sticky="w", padx=(0, px(10)))
            slider.grid(row=2 * row, column=1, sticky="ew")
        self.colour_hint.grid(row=1, column=1, sticky="w")
        grid.columnconfigure(1, weight=1)
        shown = tk.Frame(box, bg=CARD)
        self.colour_preview = tk.Label(shown, bg=CARD)
        self.colour_preview.pack()
        self.preview_caption = tk.Label(shown, text="", bg=CARD, fg=MUTED)       # packed once a page is loaded; then only its text comes and goes
        box.add(left)
        box.add(shown, px(20))
        self.swatch_row = row = self._flow(body, pady=(0, px(2)))
        self.swatches = []
        tones = [(sc.case_color(h), (h, 100, 100)) for h in sc.HUE_SWATCHES] + [(sc.case_color(0, s, v), (0, s, v)) for _, s, v in sc.NEUTRAL_SWATCHES]
        for color, tone in tones:
            s = Swatch(row, color, lambda t=tone: sc.tone_key(*self._tone()) == sc.tone_key(*t), lambda t=tone: self._set_tone(*t))
            row.add(s, px(4))
            self.swatches.append(s)
        self.colour_note = self._wrap(tk.Label(body, text="Only the original colour is checked for readable text.", bg=CARD, fg=FAINT, justify="left", anchor="w"))
        found = sc.existing_cover_colour(self.covers_dir)          # reopening the app shows the colour of the covers you already made
        if found:
            self._set_tone(*found)
        for var in (self.hue, self.sat, self.val):
            var.trace_add("write", self._colour_changed)
        self._colour_changed()

    def _build_completion(self, body):
        """The optional block for games at 100% achievements: a way to get the saved games page, and the style of their covers.
        The style can only be picked once a page is loaded; until then covers keep the look they have."""
        head = self._row(body, pady=(px(10), 0))
        tk.Label(head, text="Highlight my 100% games (optional)", bg=CARD, fg=FG, font=("TkDefaultFont", 11, "bold")).pack(side="left")
        InfoBadge(head, PAGE_HELP).pack(side="left", padx=px(6))
        self._note(body, "Games where you unlocked every achievement can get a ribbon, and a gold case or border if you like. "
                         "Steam shows them on your games page: open it, then save it as games.html, choosing “Webpage, Complete”. "
                         "This app notices the file by itself.")
        r = self._flow(body)
        self.btn_page_open = RoundedButton(r, "Open my games page", self.open_games_page)
        r.add(self.btn_page_open)
        self.btn_page_browse = RoundedButton(r, "Browse…", self.browse_games_page, quiet=True)
        r.add(self.btn_page_browse, px(10))
        self.btn_page_copy = RoundedButton(r, "Copy link", self.copy_page_link, quiet=True)
        r.add(self.btn_page_copy, px(10))
        self.page_status = self._wrap(tk.Label(body, text="No games page loaded. Your covers keep the look they have.", bg=CARD, fg=MUTED, anchor="w", justify="left"))
        self.page_status.pack(fill="x", pady=(px(4), px(4)))
        self.style_choice = Choice(body, self.completion_style, STYLES, state="disabled")
        self.style_choice.pack(fill="x", pady=px(4))
        self.page_note = self._wrap(tk.Label(body, text="", bg=CARD, fg=FAINT, anchor="w", justify="left"))         # packed once a page is loaded
        self.completion_style.trace_add("write", self._schedule_preview)

    def _completion(self):
        """(completed, treatment) for make_covers. No page loaded: (None, None), every cover keeps its look.
        "No special case": (empty set, None), the 100% covers become normal covers. Otherwise the 100% ids and the chosen style."""
        if self.completed is None:
            return None, None
        style = self.completion_style.get()
        if style not in sc.TREATMENTS:
            return set(), None
        return set(self.completed), style

    def open_games_page(self):
        try:
            webbrowser.open(GAMES_PAGE_URL)
        except Exception:
            pass
        # webbrowser cannot tell us whether a browser really opened, so always show the way out
        self.page_status.configure(text="Opening your browser… Log in to Steam if it asks and wait until your games have loaded. Then press %s and save the page "
                                        "as “Webpage, Complete”, named games.html. Nothing opened? Click “Copy link” and paste it into your browser." % SAVE_KEY, fg=MUTED)

    def copy_page_link(self):
        self.clipboard_clear()
        self.clipboard_append(GAMES_PAGE_URL)
        self.update()                               # keeps the text on the clipboard on some systems
        self.page_status.configure(text="Link copied. Paste it into your browser, log in if asked, then save the page as “Webpage, Complete”, named games.html (%s)." % SAVE_KEY, fg=ACCENT)

    def browse_games_page(self):
        path = pick_file("Choose your saved games page", self.downloads, ("Web pages", "*.html *.htm"))
        if path:
            self.load_games_page(path)

    def load_games_page(self, path):
        """Read the saved games page on a worker thread. The answer comes back as a "page" event (see on_page); a failure shows in red in the block."""
        self._page_req += 1
        self.page_pending += 1
        self.refresh_step1()
        self.page_status.configure(text="Reading %s…" % os.path.basename(path), fg=MUTED)
        threading.Thread(target=self._page_worker, args=(self._page_req, path), daemon=True).start()

    def _page_worker(self, req, path):
        """Off the UI thread. Only the app ids at 100% come back, never any text from the page (it holds a login token)."""
        try:
            done = completion.completed_apps(completion.read_games_page(path))
            self.events.put(("page", req, path, done, None))
        except completion.PageError as e:
            self.events.put(("page", req, path, None, str(e)))
        except Exception:                            # never echo what went wrong in detail: it could quote the page
            self.events.put(("page", req, path, None, "That file could not be read."))

    def on_page(self, req, path, done, error):
        self.page_pending -= 1
        if req != self._page_req:                    # the user picked another page in the meantime
            self.refresh_step1()
            return
        name = os.path.basename(path)              # only the file's name is shown, never anything from inside it
        if error:
            kept = " The page you loaded before is still used." if self.games_page else ""
            self.page_status.configure(text="%s: %s%s" % (name, error, kept), fg=RED)
            self.refresh_step1()
            return
        self.games_page, self.completed = path, set(done)
        n = len(done)
        found = "Found %d %s at 100%% in %s." % (n, "game" if n == 1 else "games", name) if n else "No game in %s is at 100%% yet." % name
        self.page_status.configure(text=found + " The game list from step 1 decides which games get covers.", fg=ACCENT)
        self.page_note.configure(text="Done with the page? You can delete %s and its folder: they hold a temporary login token for your Steam account, "
                                      "which this app does not use or keep." % name)
        if not self.page_note.winfo_manager():
            self.page_note.pack(fill="x", pady=(0, px(6)), after=self.style_choice)
        self.refresh_step1()
        self._schedule_preview()

    def _refresh_choice(self):
        """The style can be picked once a page is loaded, while the other step 2 controls can be used."""
        ready = self.installed_only.get() or bool(self.library_path)
        self.style_choice.configure(state="normal" if ready and not self.running and self.games_page else "disabled")

    def _tone(self):
        """The chosen case colour: (hue, colourfulness, brightness)."""
        return self.hue.get() % 360, self.sat.get(), self.val.get()

    def _set_tone(self, hue, sat, val):
        self._setting_tone = True                                # three variables change: update once, afterwards
        try:
            self.hue.set(hue)
            self.sat.set(sat)
            self.val.set(val)
        finally:
            self._setting_tone = False
        self._colour_changed()

    def _colour_changed(self, *_):
        if self._setting_tone:
            return
        hue, sat, val = self._tone()
        key = sc.tone_key(hue, sat, val)
        name = "Original" if key == sc.tone_key(0) else "Custom · %d° %d%% %d%%" % (hue, sat, val)
        for n, s, v in sc.NEUTRAL_SWATCHES:
            if key == sc.tone_key(0, s, v):
                name = n
        self.colour_name.configure(text=name)
        for s in self.swatches:
            s.draw()
        # without colour or light the Colour slider does nothing: say so (the text, not the row, comes and goes: nothing moves under a finger)
        self.colour_hint.configure(text="Colour has no effect on grey or black." if sat == 0 or val == 0 else "")
        if key == sc.tone_key(0):
            self.colour_note.pack_forget()
        elif not self.colour_note.winfo_manager():
            self.colour_note.pack(fill="x", pady=(0, px(6)), after=self.swatch_row)
        self._schedule_preview()

    def _schedule_preview(self, *_):
        if self._preview_job is None:                            # one redraw per burst of changes while a slider is dragged
            self._preview_job = self.after_idle(self._draw_preview)

    def _draw_preview(self):
        """The sample cover in the chosen colour; with a games page loaded and a style chosen, the cover of a 100% game in that style."""
        self._preview_job = None
        treatment = self._completion()[1]
        # the text, not the row, comes and goes: the style pills below never move under a finger
        if self.completed is not None and not self.preview_caption.winfo_manager():
            self.preview_caption.pack(pady=(px(4), 0))
        self.preview_caption.configure(text="Preview of a 100% game" if treatment else "")
        if sc.Image is None:
            return
        try:
            import base64, io
            hue, sat, val = self._tone()
            im = sc.preview_cover(hue, sat=sat, val=val, treatment=treatment).resize((px(130), px(195)), sc.Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "PNG")
            self._colour_img = tk.PhotoImage(master=self, data=base64.b64encode(buf.getvalue()))
            self.colour_preview.configure(image=self._colour_img)
        except Exception:
            pass                                                 # a preview is a nicety: never let it break the step

    def _show_preview(self):
        self.preview.clear()
        for w in self.preview.winfo_children():
            w.destroy()
        self._thumbs = []
        files = [f for f in self.cover_files if os.path.exists(f)]
        if not files or sc.Image is None:
            return
        step = max(1, len(files) // 5)
        for f in files[::step][:5]:
            try:
                import base64, io
                with sc.Image.open(f) as im:
                    im = im.convert("RGBA").resize((px(76), px(114)), sc.Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, "PNG")
                img = tk.PhotoImage(master=self, data=base64.b64encode(buf.getvalue()))
            except Exception:
                continue                                  # a preview is a nicety: never let it break the step
            self._thumbs.append(img)
            self.preview.add(tk.Label(self.preview, image=img, bg=CARD), px(10))
        if self._thumbs:
            self.preview.pack(fill="x", pady=(px(12), 0))

    def _replace_reason(self, tone, completed, treatment):
        """Why Make covers would rebuild covers already in the folder, as (title, sentence) for the prompt; None when nothing is rebuilt."""
        if not sc.covers_in_other_look(self.covers_dir, *tone, completed=completed, treatment=treatment):
            return None
        colour = sc.covers_in_other_colour(self.covers_dir, *tone)
        styles, changed = set(), False                       # the treatments in the folder, and whether any cover gets another one
        if completed is not None:
            try:
                for n in os.listdir(self.covers_dir):
                    appid = sc.appid_of(n)
                    if n.lower().endswith(".png") and appid is not None:
                        have = sc.cover_treatment(os.path.join(self.covers_dir, n)) or None
                        styles.add(have)
                        changed = changed or have != (treatment if int(appid) in completed else None)
            except OSError:
                pass
        if colour and not changed:
            return "Change the colour of your covers?", "This replaces the covers you already made in another colour."
        styles &= set(sc.TREATMENTS)
        label = dict(STYLES).get(treatment)
        if treatment is None:
            what = "the covers of your 100% games are made again as normal covers"
            title, one = "Remove the 100% highlight?", "You chose “No special case”: " + what + "."
        elif not completed:
            what = "the covers with a highlight lose it, as no game on your page is at 100%"
            title, one = "Remove the 100% highlight?", "No game on your page is at 100%, so the covers you made with a highlight lose it and are made again as normal covers."
        elif styles - {treatment}:
            what = "the covers of your 100%% games made in another style are made again as “%s”" % label
            title, one = "Change the look of your 100% games?", "This replaces the covers of your 100%% games made in another style with “%s”." % label
        elif not styles:
            what = "your 100%% games get highlighted covers (“%s”)" % label
            title, one = "Highlight your 100% games?", "This replaces the covers of your 100%% games with highlighted ones (“%s”)." % label
        else:
            what = "your 100% covers are updated to match your games page"
            title, one = "Update your 100% covers?", ("Some covers you already made are made again to match your games page: "
                                                      "games you finished get the highlight, games no longer at 100% lose it.")
        if colour:
            return "Change your covers?", "This replaces the covers you already made in another colour, and %s." % what
        return title, one

    def start_make(self):
        if self.running or self.busy:
            return
        tone = self._tone()
        completed, treatment = self._completion()           # read here, on the UI thread: the worker never touches Tk variables
        why = self._replace_reason(tone, completed, treatment)
        if why:
            if not messagebox.askokcancel(why[0],
                                          [(why[1], "main"),
                                           ("Steam keeps showing your current art until you add the new covers in step 3.", "muted")],
                                          ok="Replace them", cancel="Cancel"):
                return
        lib = None if self.installed_only.get() else self.library_path
        self.running = True
        self.cancel_flag.clear()
        self.cover_files = []
        self.manual_queue[:] = [item for item in self.manual_queue if not item.get("file")]
        self._queue_refresh()
        self.applied = False
        self.progress.configure(value=0, maximum=1)
        self.step2_status.configure(text="Looking up your games on Steam…", fg=MUTED)
        self.btn_folder.pack_forget()
        self.preview.pack_forget()
        self._set_state(self.step1, False)
        self.refresh_step1()
        self.refresh_step3()
        skip = self.skip_auto.get()
        threading.Thread(target=self._worker, args=(lib, skip, tone, (completed, treatment)), daemon=True).start()

    def _worker(self, lib, skip, tone=(0, 100, 100), look=(None, None)):
        """Runs off the UI thread; talks to the UI only through self.events. `tone` is the case colour (hue, sat, val);
        `look` is (completed, treatment) for the 100% games, taken by start_make (see _completion)."""
        hue, sat, val = tone
        completed, treatment = look
        try:
            steam = sc.steam_dir()
            games, family = sc.load_library(steam, lib)
            if not games:
                raise sc.SteamcaseError("No games found. Install a game first, or load your userdata.json.")
            res = sc.make_covers(games, self.covers_dir, skip_auto_art=skip, family=family, hue=hue, sat=sat, val=val,
                                 progress=lambda *a: self.events.put(("progress",) + a),
                                 cancelled=self.cancel_flag.is_set, completed=completed, treatment=treatment)
            self.events.put(("done", res))
        except sc.SteamcaseError as e:
            self.events.put(("error", str(e)))
        except Exception as e:                      # never leave the UI stuck in "running"
            self.events.put(("error", "Unexpected problem: %s" % e))

    def check_update(self):
        """Asks GitHub whether a newer release exists. Only on click; nothing is downloaded or installed."""
        self.btn_update.configure(state="disabled")
        threading.Thread(target=self._update_worker, daemon=True).start()

    def _update_worker(self):
        try:
            self.events.put(("update", sc.check_for_update()))
        except sc.SteamcaseError as e:
            self.events.put(("update_error", str(e)))
        except Exception as e:
            self.events.put(("update_error", "Unexpected problem: %s" % e))

    def show_update(self, r):
        self.btn_update.configure(state="normal")
        if r["newer"] is False:
            messagebox.showinfo("No update needed", "You have the latest version (%s)." % r["current"])
            return
        if r["newer"]:
            head = "A newer version is available: %s (you have %s)." % (r["latest"], r["current"])
        else:
            head = "The latest version is %s. This copy has no version number (it was not installed from a release), so I cannot compare." % r["latest"]
        text = [(head, "main"),
                ("“Open GitHub page” opens this project's release page on GitHub in your web browser:\n%s" % r["url"], "muted"),
                ("Nothing is downloaded or installed unless you choose to do it yourself on that page.", "note")]
        if messagebox.askokcancel("Update available", text, ok="Open GitHub page", cancel="Not now"):
            try:
                webbrowser.open(r["url"])
            except Exception:
                pass

    def poll_events(self):
        try:
            while True:
                ev = self.events.get_nowait()
                if ev[0] == "progress":
                    _, done, total, appid, name, status = ev
                    self.progress.configure(maximum=max(total, 1), value=done)
                    self.step2_status.configure(text="%d of %d · %s" % (done, total, name if len(name) <= 60 else name[:57] + "…"), fg=MUTED)
                elif ev[0] == "done":
                    self.finish_make(ev[1])
                elif ev[0] == "page":
                    self.on_page(*ev[1:])
                elif ev[0] == "update":
                    self.show_update(ev[1])
                elif ev[0] == "update_error":
                    self.btn_update.configure(state="normal")
                    messagebox.showerror("Could not check for updates", ev[1])
                elif ev[0] == "reset_scan":
                    self.on_reset_scan(ev[1], ev[2], ev[3])
                elif ev[0] == "step3_status":
                    self.say3(ev[1], MUTED)
                elif ev[0] == "step3_done":
                    self.busy = False
                    self.applied = ev[2] == "apply" if len(ev) > 2 else self.applied
                    detail = ev[3] if len(ev) > 3 else {}
                    if ev[2] == "apply" and detail.get("backup"):
                        self.last_apply_backup = detail["backup"]
                        self.last_apply_keys = tuple(detail.get("keys", ()))
                    elif ev[2] == "restore" and detail.get("restored") == self.last_apply_backup:
                        for item in self.manual_queue:
                            if item["key"] in self.last_apply_keys and item.get("status") == "Applied":
                                item["status"] = "Restored"
                        self.last_apply_backup = None
                        self.last_apply_keys = ()
                        self._queue_refresh()
                    self.say3(ev[1], ACCENT)
                    if len(ev) > 2 and ev[2] == "apply":
                        self._manual_status("Queue applied. Restore is available in step 3.", ACCENT)
                    if len(ev) > 2 and ev[2] in ("apply", "restore") and self.manual_verified_steam_id:
                        self._load_current_steam_cover(self.manual_verified_steam_id,
                                                       self.manual_game and self.manual_game["source"] == "steam")
                    self.refresh_step3()
                elif ev[0] == "step3_error":
                    self.busy = False
                    self.say3(ev[1], RED)
                    self.refresh_step3()
                    messagebox.showerror("Could not finish", ev[1])
                elif ev[0] == "queue_status":
                    statuses = ev[1]
                    selected = self.queue_list.curselection()
                    key = self.manual_queue[selected[0]]["key"] if selected and selected[0] < len(self.manual_queue) else None
                    for item in self.manual_queue:
                        if item["key"] in statuses:
                            item["status"] = statuses[item["key"]]
                    self._queue_refresh(key)
                elif ev[0] == "error":
                    self.running = False
                    self.step2_status.configure(text=ev[1], fg=RED)
                    self._set_state(self.step1, True)
                    self.refresh_step1()
                    messagebox.showerror("Could not make covers", ev[1])
                elif ev[0] == "steam_games" and ev[1] == self.steam_games_token:
                    self.steam_games = sorted(ev[2], key=lambda item: item[1].casefold())
                    self._filter_steam_games()
                    if not self.steam_games and not ev[4]:
                        self.steam_game_status.configure(text="No installed games found. Load userdata.json or search by name.")
                    elif ev[3] > len(self.steam_games) and not ev[4]:
                        self.steam_game_status.configure(text="%d games loaded; resolving library titles…" % len(self.steam_games))
                elif ev[0] == "steam_games_error" and ev[1] == self.steam_games_token:
                    self.steam_game_status.configure(text=ev[2], fg=RED)
                elif ev[0] == "manual_results" and ev[1] == self.manual_search_token:
                    self.manual_results = ev[2]
                    self.game_list.delete(0, "end")
                    for game in ev[2]:
                        details = "%s ID %s" % (game["source"], game["id"])
                        if game.get("types"):
                            details += " · " + ", ".join(game["types"])
                        if game.get("verified"):
                            details += " · verified"
                        self.game_list.insert("end", "%s  ·  %s" % (game["name"], details))
                    self._manual_list_visibility(self.game_list, len(ev[2]))
                    self._manual_status("%d games found. Choose one explicitly." % len(ev[2]))
                elif ev[0] == "manual_art" and ev[1] == self.manual_art_token:
                    self.manual_art = ev[2]
                    self._show_art_grid(ev[2])
                    self._manual_status("%d images found. Choose a thumbnail to preview." % len(ev[2]))
                elif ev[0] == "manual_current" and ev[1] == getattr(self, "manual_current_token", None):
                    self._display_current_cover(ev[2])
                elif ev[0] == "manual_thumb" and ev[1] == self.manual_art_token:
                    _, _, index, url, data, error = ev
                    if data is not None:
                        if len(self._thumb_cache) >= 100:
                            self._thumb_cache.pop(next(iter(self._thumb_cache)))
                        self._thumb_cache[url] = data
                    self._set_art_thumbnail(index, data, error)
                elif ev[0] == "manual_preview":
                    if ev[1] == self.manual_preview_token:
                        self.manual_image = ev[2]
                        self.manual_preview_path = str(ev[3])
                        self._display_manual_preview(ev[3])
                        self._manual_update_actions()
                        self._manual_status("Final frame ready. Apply to Steam or export a PNG.")
                elif ev[0] == "manual_export_selected":
                    self._manual_status("PNG exported: %s" % ev[1], ACCENT)
                elif ev[0] == "manual_export":
                    files, errors = ev[1]
                    self.manual_exported = [str(f) for f in files]
                    self._manual_status("Exported %d covers%s" % (len(files),
                                        ("; %d failed: %s" % (len(errors), errors[0][1])) if errors else "."))
                elif ev[0] == "manual_error":
                    self._manual_status(ev[1], RED)
                elif ev[0] == "settings_key_saved":
                    self._settings_result("SteamGridDB key checked and stored securely.", ACCENT, clear=True)
                elif ev[0] == "settings_key_deleted":
                    self._settings_result("SteamGridDB key deleted from the credential store.", ACCENT, clear=True)
                elif ev[0] == "settings_key_checked":
                    self._settings_result("Stored SteamGridDB key is valid.", ACCENT)
                elif ev[0] == "settings_error":
                    self._settings_result(ev[1], RED)
        except queue.Empty:
            pass
        self._timers[1] = self.after(100, self.poll_events)

    def finish_make(self, res):
        self.running = False
        self.cover_files = res["files"]
        titles = dict(self.steam_games)
        for path in self.cover_files:
            appid = int(sc.appid_of(path)) if sc.appid_of(path) else None
            if not appid or any(item.get("verified_steam_id") and item["steam_id"] == appid
                                for item in self.manual_queue):
                continue
            name = titles.get(appid) or os.path.basename(path).rsplit("_", 1)[0].replace("_", " ")
            self.manual_queue.append({"key": "steam:%d" % appid, "name": name,
                                      "platform": "steam", "source": "Steam CDN", "image": None,
                                      "file": str(path), "preview_path": str(path), "steam_id": appid,
                                      "verified_steam_id": True,
                                      "game": {"id": appid, "name": name, "source": "steam"},
                                      "status": "Queued"})
        self._queue_refresh()
        n, miss, bad = res["ok"], len(res["missing"]), len(res["failed"])
        text = "%s%d covers ready." % ("Stopped. " if res["cancelled"] else "Done. ", n)
        if miss:
            text += " %d %s no portrait on Steam." % (miss, "game has" if miss == 1 else "games have")
        fam = res.get("family", 0)
        if fam:
            text += " %d of them %s and %s a green corner." % (fam, "is a family game" if fam == 1 else "are family games", "has" if fam == 1 else "have")
        done = res.get("completed", 0)
        if done:
            text += " %d of them %s 100%% and %s highlighted." % (done, "is" if done == 1 else "are", "is" if done == 1 else "are")
        skipped = res.get("not_games", 0) + res.get("unlisted", 0)
        if skipped:
            text += " Skipped %d items that aren't games you can play (DLC, soundtracks, tools, and apps Steam no longer lists)." % skipped
        if bad:
            text += " %d could not be downloaded (connection problem?): click “Make covers” again to retry only those." % bad
        self.step2_status.configure(text=text, fg=ACCENT if n and not bad else MUTED if not n else FG)
        self._set_state(self.step1, True)
        self.refresh_step1()
        if n:
            self.row_make.add(self.btn_folder, px(10))
            self._show_preview()
        self.refresh_step3()

    def cancel_make(self):
        self.cancel_flag.set()
        self.step2_status.configure(text="Stopping…", fg=MUTED)

    def open_covers_folder(self):
        folder = os.path.abspath(self.covers_dir)
        os.makedirs(folder, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)
            else:
                subprocess.Popen([sc._tool("open" if sys.platform == "darwin" else "xdg-open"), folder])
        except (OSError, sc.SteamcaseError):
            messagebox.showinfo("Covers folder", "Could not open the folder. It is here:\n\n%s" % folder)

    # ----- independent search and export -----
    def toggle_manual(self):
        self.manual_expanded = not self.manual_expanded
        if self.manual_expanded:
            self.manual_body.pack(fill="x", pady=(px(12), 0))
        else:
            self.manual_body.pack_forget()
        self.manual_toggle.text = "Collapse" if self.manual_expanded else "Expand"
        self.manual_toggle.draw()
        self._sync_manual_height()
        self.after_idle(self.scroller._update)

    def _build_manual(self, body):
        self.manual_results, self.manual_art, self.manual_queue = [], [], []
        self.queue_edit_key = None
        self.queue_serial = 0
        self.queue_preview_photo = None
        self.manual_preview_path = None
        self.manual_game = self.manual_image = None
        self.steam_games, self.filtered_steam_games = [], []
        self.steam_games_token = 0
        self.manual_verified_steam_id = None
        self.manual_preview_token = self.manual_search_token = self.manual_art_token = self.manual_current_token = 0
        self.manual_exported = []
        self.manual_source = tk.StringVar(value="Steam CDN")
        self.manual_platform = tk.StringVar(value="steam")
        self.manual_term = tk.StringVar()
        self.manual_steam_id = tk.StringVar()
        self.manual_steam_id.trace_add("write", lambda *_: self._manual_update_actions())
        self.manual_folder = tk.StringVar(value=self.covers_dir)
        self.steam_game_query = tk.StringVar()
        self._manual_photo = None
        self._current_photo = None
        self._note(body, "Choose a Steam game or search by name. Pick artwork, inspect the frame, then apply or export.")
        mode_row = self._row(body)
        self.btn_library_mode = RoundedButton(mode_row, "Steam library", lambda: self._editor_mode("library"), primary=True)
        self.btn_library_mode.pack(side="left")
        self.btn_search_mode = RoundedButton(mode_row, "Search by name", lambda: self._editor_mode("search"))
        self.btn_search_mode.pack(side="left", padx=px(8))
        self.library_panel = tk.Frame(body, bg=CARD)
        self.library_panel.pack(fill="x")
        library_search = self._row(self.library_panel)
        tk.Entry(library_search, textvariable=self.steam_game_query).pack(side="left", fill="x", expand=True)
        RoundedButton(library_search, "Refresh", self.refresh_steam_games, quiet=True).pack(side="left", padx=(px(8), 0))
        self.steam_game_status = tk.Label(self.library_panel, text="Looking for Steam games…", bg=CARD, fg=MUTED, anchor="w")
        self.steam_game_status.pack(fill="x")
        library_list_frame = tk.Frame(self.library_panel, bg=CARD)
        library_list_frame.pack(fill="x", pady=px(4))
        self.steam_game_list = tk.Listbox(library_list_frame, height=5, bg=BG, fg=FG,
                                         selectbackground=ACCENT, exportselection=False)
        steam_scroll = tk.Scrollbar(library_list_frame, orient="vertical", command=self.steam_game_list.yview,
                                    width=px(14), troughcolor=BG, bg=LINE, activebackground=ACCENT)
        self.steam_game_list.configure(yscrollcommand=steam_scroll.set)
        steam_scroll.pack(side="right", fill="y")
        self.steam_game_list.pack(side="left", fill="both", expand=True)
        self.steam_game_list.bind("<<ListboxSelect>>", self._pick_library_game)
        self.steam_game_query.trace_add("write", lambda *_: self._filter_steam_games())
        self.manual_search_panel = tk.Frame(body, bg=CARD)
        r = self._row(body)
        self.platform_row = r
        tk.Label(r, text="Platform", bg=CARD, fg=FG).pack(side="left")
        platforms = load_catalog()["platforms"]
        self.manual_platform_names = {p["name"]: p["id"] for p in platforms}
        names = [p["name"] for p in platforms]
        self.manual_platform.set("Steam")
        menu = tk.OptionMenu(r, self.manual_platform, *names, command=lambda _: self._manual_platform_changed())
        menu.configure(bg=CARD, fg=FG, highlightthickness=0)
        menu.pack(side="left", padx=px(8))
        r = self._row(body)
        tk.Label(r, text="Image source", bg=CARD, fg=FG).pack(side="left")
        source = tk.OptionMenu(r, self.manual_source, "Steam CDN", "SteamGridDB", "Local file",
                               command=lambda _: self._manual_source_changed())
        source.configure(bg=CARD, fg=FG, highlightthickness=0)
        source.pack(side="left", padx=px(8))
        RoundedButton(r, "Import image", self._manual_local, quiet=True).pack(side="left", padx=px(8))
        r = self._row(self.manual_search_panel)
        tk.Entry(r, textvariable=self.manual_term).pack(fill="x", expand=True)
        r = self._row(self.manual_search_panel)
        RoundedButton(r, "Search games", self._manual_search).pack(side="left")
        self.game_holder = tk.Frame(self.manual_search_panel, bg=CARD)
        self.game_list = tk.Listbox(self.game_holder, height=1, bg=BG, fg=FG, selectbackground=ACCENT,
                                    exportselection=False)
        game_vertical = tk.Scrollbar(self.game_holder, orient="vertical", command=self.game_list.yview,
                                     width=px(14), troughcolor=BG, bg=LINE, activebackground=ACCENT)
        game_horizontal = tk.Scrollbar(self.game_holder, orient="horizontal", command=self.game_list.xview,
                                       width=px(14), troughcolor=BG, bg=LINE, activebackground=ACCENT)
        self.game_list.configure(yscrollcommand=game_vertical.set, xscrollcommand=game_horizontal.set)
        game_vertical.pack(side="right", fill="y")
        game_horizontal.pack(side="bottom", fill="x")
        self.game_list.pack(side="left", fill="both", expand=True)
        self.game_list.bind("<<ListboxSelect>>", self._manual_pick_game)
        self.art_holder = tk.Frame(body, bg=CARD)
        tk.Label(self.art_holder, text="Artwork · select an image", bg=CARD, fg=FG,
                 anchor="w").pack(fill="x", pady=(px(5), px(4)))
        gallery = tk.Frame(self.art_holder, bg=CARD)
        gallery.pack(fill="x")
        self.art_grid = tk.Canvas(gallery, bg=CARD, highlightthickness=0, height=px(280))
        self.art_scrollbar = tk.Scrollbar(gallery, orient="vertical", command=self.art_grid.yview,
                                         width=px(14), troughcolor=BG, bg=LINE, activebackground=ACCENT)
        self.art_scrollbar.pack(side="right", fill="y")
        self.art_grid.pack(side="left", fill="x", expand=True)
        self.art_grid.configure(yscrollcommand=self.art_scrollbar.set)
        self.art_inner = tk.Frame(self.art_grid, bg=CARD)
        self._art_window = self.art_grid.create_window(0, 0, window=self.art_inner, anchor="nw")
        self.art_inner.bind("<Configure>", lambda _event: self.art_grid.configure(
            scrollregion=self.art_grid.bbox("all")), add="+")
        self.art_grid.bind("<Configure>", self._art_grid_resized, add="+")
        for widget in (self.art_grid, self.art_inner):
            widget.bind("<MouseWheel>", self._art_wheel)
            widget.bind("<Button-4>", lambda _event: self._art_scroll(-1))
            widget.bind("<Button-5>", lambda _event: self._art_scroll(1))
        self._art_tiles, self._art_thumb_labels, self._art_photos = [], [], {}
        self._art_columns = 0
        self.manual_art_selected = None
        self.manual_id_row = r = self._row(body)
        tk.Label(r, text="Steam artwork ID (optional)", bg=CARD, fg=FG).pack(side="left")
        tk.Entry(r, textvariable=self.manual_steam_id, width=15).pack(side="left", padx=px(8))
        r = self._row(body)
        RoundedButton(r, "Choose shortcut", self._manual_choose_shortcut).pack(side="left", padx=px(8))
        self._note(body, "Steam IDs fill automatically. Choose a verified shortcut for non-Steam games. Covers without an ID can still be exported.")
        preview_row = self._row(body)
        current = tk.Frame(preview_row, bg=CARD)
        current.pack(side="left", anchor="n")
        tk.Label(current, text="Current Steam cover", bg=CARD, fg=MUTED).pack(anchor="w")
        self.current_cover = tk.Label(current, bg=CARD, fg=MUTED, text="Choose a Steam game.",
                                      width=20, height=3)
        self.current_cover.pack(anchor="w")
        final = tk.Frame(preview_row, bg=CARD)
        final.pack(side="left", anchor="n", padx=(px(15), 0))
        tk.Label(final, text="New framed cover", bg=CARD, fg=FG).pack(anchor="w")
        self.manual_preview = tk.Label(final, bg=CARD, fg=MUTED, text="Choose artwork to preview.")
        self.manual_preview.pack(anchor="w")
        self.current_cover_group = current
        self.queue_panel = tk.Frame(body, bg=CARD)
        tk.Label(self.queue_panel, text="Cover queue · select a game to preview or edit", bg=CARD,
                 fg=FG, anchor="w").pack(fill="x", pady=(px(7), px(4)))
        queue_row = tk.Frame(self.queue_panel, bg=CARD)
        queue_row.pack(fill="x")
        self.queue_list = tk.Listbox(queue_row, height=3, bg=BG, fg=FG, selectbackground=ACCENT,
                                     exportselection=False)
        queue_scroll = tk.Scrollbar(queue_row, orient="vertical", command=self.queue_list.yview,
                                    width=px(14), troughcolor=BG, bg=LINE, activebackground=ACCENT)
        self.queue_list.configure(yscrollcommand=queue_scroll.set)
        queue_scroll.pack(side="right", fill="y")
        self.queue_list.pack(side="left", fill="both", expand=True)
        self.queue_list.bind("<<ListboxSelect>>", self._queue_selected)
        queue_selection = tk.Frame(self.queue_panel, bg=CARD)
        queue_selection.pack(fill="x", pady=px(5))
        self.queue_preview = tk.Label(queue_selection, bg=CARD, fg=MUTED, text="Select a cover.")
        self.queue_preview.pack(side="left", anchor="n")
        self.queue_detail = tk.Label(queue_selection, bg=CARD, fg=MUTED, text="", anchor="nw",
                                     justify="left", wraplength=px(310))
        self.queue_detail.pack(side="left", fill="x", expand=True, anchor="n", padx=(px(10), 0))
        queue_buttons = self._row(self.queue_panel)
        RoundedButton(queue_buttons, "Edit selected", self._queue_edit).pack(side="left")
        RoundedButton(queue_buttons, "Remove selected", self._queue_remove).pack(side="left", padx=px(8))
        r = self._row(body)
        self.batch_row = r
        RoundedButton(r, "Add to batch", self._manual_add).pack(side="left")
        RoundedButton(r, "Choose export folder", self._manual_choose_folder).pack(side="left", padx=px(8))
        RoundedButton(r, "Export batch", self._manual_export).pack(side="left")
        self.manual_queue_label = tk.Label(body, text="Queue: empty", bg=CARD, fg=MUTED, anchor="w")
        self.manual_queue_label.pack(fill="x")
        self.manual_folder_label = tk.Label(body, text=self.manual_folder.get(), bg=CARD, fg=MUTED,
                                            anchor="w", justify="left")
        self.manual_folder_label.pack(fill="x")
        self.manual_status = tk.Label(body, text="", bg=CARD, fg=MUTED, anchor="w", justify="left")
        self.manual_status.pack(fill="x", pady=px(4))
        body.bind("<Configure>", lambda event: self._manual_wrap_labels(event.width), add="+")

    def _manual_wrap_labels(self, width):
        wrap = max(px(220), width - px(8))
        for label in (self.manual_queue_label, self.manual_folder_label, self.manual_status):
            label.configure(wraplength=wrap)
        self.queue_detail.configure(wraplength=max(px(120), width - px(120)))

    def _queue_refresh(self, selected_key=None):
        self.queue_list.delete(0, "end")
        for item in self.manual_queue:
            target = "Steam ID %s" % item["steam_id"] if item.get("verified_steam_id") else "PNG only"
            self.queue_list.insert("end", "%s  ·  %s  ·  %s" %
                                   (item["name"], target, item.get("status", "Queued")))
        if self.manual_queue:
            self.queue_panel.pack(fill="x", before=self.batch_row)
            self.queue_list.configure(height=min(5, len(self.manual_queue)))
            keys = [item["key"] for item in self.manual_queue]
            index = keys.index(selected_key) if selected_key in keys else 0
            self.queue_list.selection_set(index)
            self.queue_list.see(index)
            self._queue_selected()
        else:
            self.queue_panel.pack_forget()
            self.queue_preview.configure(image="", text="Select a queued cover.")
            self.queue_detail.configure(text="")
            self.queue_preview_photo = None
        n = sum(bool(item.get("verified_steam_id")) for item in self.manual_queue)
        self.manual_queue_label.configure(text="Queue: %d covers · %d ready for Steam" %
                                          (len(self.manual_queue), n) if self.manual_queue else "Queue: empty")
        self.refresh_step3()

    def _queue_selected(self, _event=None):
        selection = self.queue_list.curselection()
        if not selection or selection[0] >= len(self.manual_queue):
            return
        item = self.manual_queue[selection[0]]
        self.queue_detail.configure(text="%s\n%s\n%s" %
                                    (item["name"], "Steam ID %s" % item["steam_id"]
                                     if item.get("verified_steam_id") else "PNG export only",
                                     item.get("status", "Queued")))
        path = item.get("preview_path") or item.get("file") or item.get("image")
        try:
            with sc.Image.open(path, formats=["PNG", "JPEG", "WEBP"]) as source:
                thumb = source.convert("RGBA")
                thumb.thumbnail((px(70), px(105)), sc.Image.LANCZOS)
            buffer = io.BytesIO()
            thumb.save(buffer, "PNG")
            self.queue_preview_photo = tk.PhotoImage(master=self, data=base64.b64encode(buffer.getvalue()))
            self.queue_preview.configure(image=self.queue_preview_photo, text="")
        except (OSError, ValueError, TypeError):
            self.queue_preview.configure(image="", text="Preview unavailable.")

    def _queue_edit(self):
        selection = self.queue_list.curselection()
        if not selection or self.busy:
            return
        item = self.manual_queue[selection[0]]
        self.queue_edit_key = item["key"]
        game = item.get("game") or {"id": item.get("steam_id"), "name": item["name"], "source": "steam"}
        self._editor_mode("library" if game["source"] == "steam" else "search")
        self.manual_platform.set(next((name for name, ident in self.manual_platform_names.items()
                                       if ident == item["platform"]), "Steam"))
        self.manual_source.set(item.get("source", "Steam CDN"))
        self._select_game(game)
        if item.get("verified_steam_id") and game["source"] != "steam":
            self.manual_verified_steam_id = item["steam_id"]
            self.manual_steam_id.set(str(item["steam_id"]))
            self.current_cover_group.pack(side="left", anchor="n", before=self.manual_preview.master)
            self._load_current_steam_cover(item["steam_id"], allow_cdn=False)
        if item.get("image"):
            self._manual_prepare_preview(item["image"])
        self._manual_status("Editing %s. Add to batch to update this queued cover." % item["name"])

    def _queue_remove(self):
        selection = self.queue_list.curselection()
        if not selection or self.busy:
            return
        item = self.manual_queue.pop(selection[0])
        if self.queue_edit_key == item["key"]:
            self.queue_edit_key = None
        self._queue_refresh()
        self._manual_status("Removed %s from the queue." % item["name"])

    def _queue_upsert(self, item):
        edited = self.queue_edit_key
        key = "steam:%d" % item["steam_id"] if item.get("verified_steam_id") else edited
        if key is None:
            self.queue_serial += 1
            key = "local:%d" % self.queue_serial
        item["key"] = key
        item["status"] = "Queued" if item.get("verified_steam_id") else "Export only"
        if edited and edited != key:
            self.manual_queue[:] = [old for old in self.manual_queue if old["key"] != edited]
        index = next((i for i, old in enumerate(self.manual_queue) if old["key"] == key), None)
        if index is None and item.get("verified_steam_id"):
            index = next((i for i, old in enumerate(self.manual_queue)
                          if old.get("verified_steam_id") and old["steam_id"] == item["steam_id"]), None)
        if index is None:
            self.manual_queue.append(item)
        else:
            self.manual_queue[index] = item
        self.queue_edit_key = None
        self._queue_refresh(item["key"])

    def _manual_list_visibility(self, widget, count):
        if count:
            widget.configure(height=min(6, count))
            if not self.game_holder.winfo_manager():
                self.game_holder.pack(fill="x", pady=px(5))
        else:
            self.game_holder.pack_forget()

    def _editor_mode(self, mode):
        self.library_panel.pack_forget()
        self.manual_search_panel.pack_forget()
        if mode == "library":
            self.library_panel.pack(fill="x", before=self.platform_row)
        else:
            anchor = self.art_holder if self.art_holder.winfo_manager() else self.manual_id_row
            self.manual_search_panel.pack(fill="x", before=anchor)
        self.btn_library_mode.primary = mode == "library"
        self.btn_search_mode.primary = mode == "search"
        self.btn_library_mode.draw()
        self.btn_search_mode.draw()

    def refresh_steam_games(self):
        self.steam_games_token += 1
        token = self.steam_games_token
        library = None if self.installed_only.get() else self.library_path
        self.steam_game_status.configure(text="Looking for Steam games…", fg=MUTED)

        def work():
            try:
                games = sc.load_games(sc.steam_dir(), library)
                known = [(appid, name) for appid, name in games.items() if name]
                self.events.put(("steam_games", token, known, len(games), False))
                if any(name is None for name in games.values()):
                    resolved = sc.list_games(games)
                    self.events.put(("steam_games", token, resolved, len(games), True))
            except (sc.SteamcaseError, OSError, ValueError) as exc:
                self.events.put(("steam_games_error", token, str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _filter_steam_games(self):
        needle = self.steam_game_query.get().strip().casefold()
        self.filtered_steam_games = [game for game in self.steam_games
                                     if not needle or needle in game[1].casefold() or needle in str(game[0])]
        self.steam_game_list.delete(0, "end")
        if self.filtered_steam_games:
            self.steam_game_list.insert("end", *("%s  ·  Steam ID %d" % (name, appid)
                                                  for appid, name in self.filtered_steam_games))
        self.steam_game_status.configure(text="%d of %d Steam games" %
                                         (len(self.filtered_steam_games), len(self.steam_games)))

    def _pick_library_game(self, _event=None):
        selection = self.steam_game_list.curselection()
        if not selection or selection[0] >= len(self.filtered_steam_games):
            return
        appid, name = self.filtered_steam_games[selection[0]]
        self.steam_game_list.configure(height=2)
        self.manual_platform.set("Steam")
        self.manual_source.set("Steam CDN")
        self._select_game({"id": appid, "name": name, "source": "steam"})

    def _art_grid_resized(self, event):
        self.art_grid.itemconfigure(self._art_window, width=event.width)
        columns = max(1, event.width // px(128))
        if columns != self._art_columns:
            self._art_columns = columns
            for index, tile in enumerate(self._art_tiles):
                tile.grid(row=index // columns, column=index % columns,
                          padx=px(4), pady=px(5), sticky="n")

    def _clear_art_grid(self):
        for tile in self._art_tiles:
            tile.destroy()
        self._art_tiles, self._art_thumb_labels, self._art_photos = [], [], {}
        self.manual_art_selected = None
        self.art_holder.pack_forget()

    def _show_art_grid(self, arts):
        self._clear_art_grid()
        if not arts:
            return
        self.art_holder.pack(fill="x", before=self.manual_id_row, pady=px(5))
        columns = max(1, self.art_grid.winfo_width() // px(128))
        self._art_columns = columns
        token = self.manual_art_token
        for index, art in enumerate(arts):
            tile = tk.Frame(self.art_inner, bg=BG, highlightthickness=2,
                            highlightbackground=LINE, highlightcolor=ACCENT,
                            width=px(116), height=px(186), takefocus=True)
            tile.pack_propagate(False)
            tile.grid(row=index // columns, column=index % columns,
                      padx=px(4), pady=px(5), sticky="n")
            image = tk.Label(tile, text="Loading…", bg=BG, fg=MUTED,
                             wraplength=px(102), justify="center")
            image.pack(fill="both", expand=True, padx=px(3), pady=(px(3), 0))
            caption = "%s · %s" % (art.get("style") or "Image", art["id"])
            foot = tk.Label(tile, text=caption, bg=BG, fg=FG,
                            wraplength=px(105), justify="center")
            foot.pack(fill="x", padx=px(2), pady=(0, px(3)))
            for widget in (tile, image, foot):
                widget.bind("<Button-1>", lambda _event, i=index: self._manual_pick_art(i))
                widget.bind("<MouseWheel>", self._art_wheel)
                widget.bind("<Button-4>", lambda _event: self._art_scroll(-1))
                widget.bind("<Button-5>", lambda _event: self._art_scroll(1))
            tile.bind("<Return>", lambda _event, i=index: self._manual_pick_art(i))
            tile.bind("<space>", lambda _event, i=index: self._manual_pick_art(i))
            self._art_tiles.append(tile)
            self._art_thumb_labels.append(image)
            url = art.get("thumb") or art["url"]
            if url in self._thumb_cache:
                self._set_art_thumbnail(index, self._thumb_cache[url])
            else:
                self._thumb_tasks.put((token, index, url))
        self.art_grid.yview_moveto(0)

    def _art_scroll(self, units):
        self.art_grid.yview_scroll(units, "units")
        return "break"

    def _art_wheel(self, event):
        return self._art_scroll(-1 if event.delta > 0 else 1)

    def _thumbnail_loop(self):
        while not self._quit.is_set():
            try:
                token, index, url = self._thumb_tasks.get(timeout=0.3)
            except queue.Empty:
                continue
            if token == self.manual_art_token:
                self._manual_thumb_worker(token, index, url)

    def _manual_thumb_worker(self, token, index, url):
        try:
            path = cw.ArtworkClient().image(url)
            with sc.Image.open(path) as source:
                thumb = source.convert("RGBA")
                thumb.thumbnail((px(94), px(132)), sc.Image.LANCZOS)
            canvas = sc.Image.new("RGBA", (px(94), px(132)), BG)
            canvas.alpha_composite(thumb, ((canvas.width - thumb.width) // 2,
                                           (canvas.height - thumb.height) // 2))
            buffer = io.BytesIO()
            canvas.save(buffer, "PNG")
            self.events.put(("manual_thumb", token, index, url, buffer.getvalue(), None))
        except Exception as exc:
            self.events.put(("manual_thumb", token, index, url, None, str(exc)))

    def _set_art_thumbnail(self, index, data=None, error=None):
        if index >= len(self._art_thumb_labels):
            return
        label = self._art_thumb_labels[index]
        if error:
            label.configure(image="", text="Image unavailable", fg=RED)
            return
        photo = tk.PhotoImage(master=self, data=base64.b64encode(data))
        self._art_photos[index] = photo
        label.configure(image=photo, text="")

    def _manual_status(self, text, color=MUTED):
        self.manual_status.configure(text=text, fg=color)

    def _manual_update_actions(self):
        if not hasattr(self, "btn_manual_apply"):
            return
        ready = bool(self.manual_game and self.manual_image) and not self.busy
        steam_id = self.manual_steam_id.get().strip()
        verified = bool(steam_id.isdecimal() and self.manual_verified_steam_id == int(steam_id))
        self.btn_manual_export.configure(state="normal" if ready else "disabled")
        queued = any(item.get("verified_steam_id") for item in self.manual_queue)
        self.btn_manual_apply.configure(state="normal" if not self.busy and not self.running and
                                        ((ready and verified) or queued) else "disabled")

    def _manual_source_changed(self):
        self.manual_search_token += 1
        self.manual_art_token += 1
        self.manual_preview_token += 1
        self.manual_results = self.manual_art = []
        self.manual_image = None
        self.manual_preview_path = None
        self.game_list.delete(0, "end")
        self.game_holder.pack_forget()
        self._clear_art_grid()
        self.manual_preview.configure(image="", text="Choose artwork to preview.")
        self._manual_update_actions()
        if self.manual_game and self.manual_game["source"] == "steam":
            self._load_art_for_selected()
        else:
            self.manual_game = None
            self.manual_verified_steam_id = None
            self.manual_steam_id.set("")
            self.current_cover_group.pack_forget()

    def _manual_platform_changed(self):
        if not self.manual_game:
            wanted = "Steam CDN" if self.manual_platform_names[self.manual_platform.get()] == "steam" else "SteamGridDB"
            if self.manual_source.get() != "Local file" and self.manual_source.get() != wanted:
                self.manual_source.set(wanted)
                self._manual_source_changed()
        if self.manual_image and self.manual_game:
            self._manual_prepare_preview(self.manual_image)

    def _manual_client(self, key=None):
        return cw.ArtworkClient(cw.load_api_key() if key is None else key)

    def _manual_search(self):
        source = self.manual_source.get()
        if source == "Local file":
            self._manual_status("Import a local image, then enter its game title.")
            return
        term = self.manual_term.get().strip()
        self.manual_game = self.manual_image = None
        self.manual_preview_path = None
        self.manual_verified_steam_id = None
        self.manual_steam_id.set("")
        self.manual_current_token += 1
        self.current_cover_group.pack_forget()
        self.manual_art_token += 1
        self.manual_preview_token += 1
        self._clear_art_grid()
        self.manual_preview.configure(image="", text="Choose artwork to preview.")
        self.manual_results = []
        self.game_list.delete(0, "end")
        self.game_holder.pack_forget()
        self._manual_update_actions()
        self.manual_search_token += 1
        token = self.manual_search_token
        self._manual_status("Searching…")
        def work():
            try:
                result = self._manual_client().search(term, "steam" if source == "Steam CDN" else "steamgriddb")
                self.events.put(("manual_results", token, result))
            except sc.SteamcaseError as exc:
                self.events.put(("manual_error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def _manual_pick_game(self, _event=None):
        selection = self.game_list.curselection()
        if not selection or selection[0] >= len(self.manual_results):
            return
        game = self.manual_results[selection[0]]
        self._select_game(game)

    def _select_game(self, game):
        self.manual_game = dict(game)
        self.manual_image = None
        self.manual_preview_path = None
        self.manual_art = []
        if game["source"] == "steam":
            self.manual_verified_steam_id = int(game["id"])
            self.manual_steam_id.set(str(game["id"]))
            self.current_cover_group.pack(side="left", anchor="n", before=self.manual_preview.master)
            self.current_cover.configure(image="", text="Loading current cover…")
            self._load_current_steam_cover(int(game["id"]))
        else:
            self.manual_verified_steam_id = None
            self.manual_steam_id.set("")
            self.current_cover_group.pack_forget()
        self._load_art_for_selected()

    def _load_current_steam_cover(self, appid, allow_cdn=True):
        self.manual_current_token = getattr(self, "manual_current_token", 0) + 1
        token = self.manual_current_token

        def work():
            try:
                path = cw.current_steam_cover(sc.steam_dir(), self._acc(), appid)
                if path is None and allow_cdn:
                    client = cw.ArtworkClient()
                    candidates = client.steam_art(appid)
                    if candidates:
                        path = client.image(candidates[0]["url"])
                self.events.put(("manual_current", token, path))
            except (sc.SteamcaseError, OSError) as exc:
                self.events.put(("manual_current", token, None))

        threading.Thread(target=work, daemon=True).start()

    def _load_art_for_selected(self):
        if not self.manual_game:
            return
        self.manual_art_token += 1
        token = self.manual_art_token
        self._clear_art_grid()
        self.manual_preview_token += 1
        self.manual_preview.configure(image="", text="Choose artwork to preview.")
        self.manual_image = None
        self.manual_preview_path = None
        self._manual_update_actions()
        game = dict(self.manual_game)
        source = self.manual_source.get()
        if source == "Local file":
            self._manual_status("Import a PNG, JPG or WebP image for this game.")
            return
        self._manual_status("Loading available artwork…")

        def work():
            try:
                client = cw.ArtworkClient() if source == "Steam CDN" else self._manual_client()
                if source == "Steam CDN":
                    if game["source"] != "steam":
                        raise sc.SteamcaseError("Choose a Steam game to browse Steam CDN artwork.")
                    art = client.steam_art(game["id"])
                elif game["source"] == "steam":
                    art = client.grids_steam(game["id"])
                else:
                    art = client.grids(game["id"])
                self.events.put(("manual_art", token, art))
            except sc.SteamcaseError as exc:
                self.events.put(("manual_error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def _manual_pick_art(self, index):
        if index >= len(self.manual_art):
            return
        if self.manual_art_selected is not None and self.manual_art_selected < len(self._art_tiles):
            self._art_tiles[self.manual_art_selected].configure(highlightbackground=LINE)
        self.manual_art_selected = index
        self._art_tiles[index].configure(highlightbackground=ACCENT)
        art = self.manual_art[index]
        self.manual_image = None
        self.manual_preview_path = None
        self._manual_update_actions()
        self.manual_preview.configure(image="", text="Rendering the selected frame…")
        self.manual_preview_token += 1
        token = self.manual_preview_token
        platform_id = self.manual_platform_names[self.manual_platform.get()]
        name = self.manual_game["name"]
        self._manual_status("Downloading and rendering selected artwork…")
        def work():
            try:
                image = cw.ArtworkClient().image(art["url"])
                self._manual_render(image, token, platform_id, name)
            except sc.SteamcaseError as exc:
                self.events.put(("manual_error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def _manual_render(self, image, token, platform_id, name):
        try:
            preview = cw.export_one(image, platform_id, name, cw.cache_dir() / "previews")
            self.events.put(("manual_preview", token, image, preview))
        except (sc.SteamcaseError, OSError) as exc:
            self.events.put(("manual_error", str(exc)))

    def _manual_prepare_preview(self, image):
        self.manual_preview_token += 1
        self.manual_image = None
        self.manual_preview_path = None
        self._manual_update_actions()
        self.manual_preview.configure(image="", text="Rendering the selected frame…")
        platform_id = self.manual_platform_names[self.manual_platform.get()]
        name = self.manual_game["name"]
        threading.Thread(target=self._manual_render,
                         args=(image, self.manual_preview_token, platform_id, name), daemon=True).start()

    def _display_manual_preview(self, path):
        with sc.Image.open(path) as im:
            thumb = im.convert("RGBA").resize((px(160), px(240)), sc.Image.LANCZOS)
        buffer = io.BytesIO()
        thumb.save(buffer, "PNG")
        self._manual_photo = tk.PhotoImage(master=self, data=base64.b64encode(buffer.getvalue()))
        self.manual_preview.configure(image=self._manual_photo, text="")

    def _display_current_cover(self, path):
        if not path:
            self.current_cover.configure(image="", text="No current portrait found.")
            return
        try:
            with sc.Image.open(path, formats=["PNG", "JPEG", "WEBP"]) as image:
                thumb = image.convert("RGBA")
                thumb.thumbnail((px(120), px(180)), sc.Image.LANCZOS)
            buffer = io.BytesIO()
            thumb.save(buffer, "PNG")
            self._current_photo = tk.PhotoImage(master=self, data=base64.b64encode(buffer.getvalue()))
            self.current_cover.configure(image=self._current_photo, text="", width=0, height=0)
        except (OSError, ValueError):
            self.current_cover.configure(image="", text="Current cover unavailable.")

    def _manual_local(self):
        path = filedialog.askopenfilename(title="Import cover image", filetypes=[
            ("Cover images", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")])
        if not path:
            return
        try:
            cw.validate_local_image(path)
        except sc.SteamcaseError as exc:
            self._manual_status(str(exc), RED)
            return
        self.manual_source.set("Local file")
        self.manual_art_token += 1
        self._clear_art_grid()
        if not self.manual_game:
            title = self.manual_term.get().strip() or os.path.splitext(os.path.basename(path))[0]
            self.manual_game = {"name": title, "id": None, "source": "local"}
            self.manual_verified_steam_id = None
            self.manual_steam_id.set("")
        self._manual_prepare_preview(path)

    def _manual_choose_shortcut(self):
        try:
            steam = sc.steam_dir()
            options = cw.list_shortcuts(steam, self._acc())
        except sc.SteamcaseError as exc:
            self._manual_status(str(exc), RED)
            return
        if not options:
            self._manual_status("No Steam shortcuts found for this account.", RED)
            return
        picked = ShortcutPicker(self, options).show()
        if picked:
            self.manual_verified_steam_id = int(picked)
            self.manual_steam_id.set(str(picked))
            self.current_cover_group.pack(side="left", anchor="n", before=self.manual_preview.master)
            self.current_cover.configure(image="", text="Loading current cover…")
            self._load_current_steam_cover(int(picked), allow_cdn=False)
            self._manual_update_actions()
            self._manual_status("Steam shortcut ID selected: %s" % picked)

    def _selected_cover_item(self, require_verified_id=False):
        if not self.manual_game or not self.manual_image:
            raise sc.SteamcaseError("Choose a game and artwork, then wait for the final frame preview.")
        raw = self.manual_steam_id.get().strip()
        if raw and (not raw.isdecimal() or not 0 < int(raw) < 2 ** 32):
            raise sc.SteamcaseError("Steam artwork ID must be a positive 32-bit number.")
        steam_id = int(raw) if raw else None
        if require_verified_id and (steam_id is None or steam_id != self.manual_verified_steam_id):
            raise sc.SteamcaseError("Choose a Steam game or a verified shortcut before applying artwork.")
        return {"name": self.manual_game["name"],
                "platform": self.manual_platform_names[self.manual_platform.get()],
                "image": str(self.manual_image), "steam_id": steam_id}

    def _manual_export_selected(self):
        try:
            item = self._selected_cover_item()
        except sc.SteamcaseError as exc:
            self._manual_status(str(exc), RED)
            return
        folder = self.manual_folder.get()
        self._manual_status("Exporting the selected PNG…")

        def work():
            try:
                path = cw.export_one(item["image"], item["platform"], item["name"], folder, item["steam_id"])
                self.events.put(("manual_export_selected", str(path)))
            except (sc.SteamcaseError, OSError) as exc:
                self.events.put(("manual_error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _manual_apply(self):
        if self.busy or self.running:
            return
        queued = any(item.get("verified_steam_id") for item in self.manual_queue)
        if (not queued or self.queue_edit_key) and self.manual_game and self.manual_image and self.manual_verified_steam_id:
            try:
                item = self._selected_cover_item(require_verified_id=True)
            except sc.SteamcaseError as exc:
                self._manual_status(str(exc), RED)
                return
            item.update({"verified_steam_id": True, "game": dict(self.manual_game),
                         "source": self.manual_source.get(), "preview_path": self.manual_preview_path})
            self._queue_upsert(item)
        self.confirm_and_run("apply")

    def _manual_add(self):
        if self.busy or self.running:
            self._manual_status("Wait for the current Steam operation to finish before changing the queue.")
            return
        try:
            item = self._selected_cover_item()
        except sc.SteamcaseError as exc:
            self._manual_status(str(exc), RED)
            return
        item["verified_steam_id"] = item["steam_id"] is not None and item["steam_id"] == self.manual_verified_steam_id
        item.update({"game": dict(self.manual_game), "source": self.manual_source.get(),
                     "preview_path": self.manual_preview_path})
        self._queue_upsert(item)
        self._manual_status("Added to the queue. Apply verified Steam covers together or export selected covers.")

    def _manual_choose_folder(self):
        path = filedialog.askdirectory(title="Choose cover export folder", initialdir=self.manual_folder.get())
        if path:
            self.manual_folder.set(path)
            self.manual_folder_label.configure(text=path)

    def _manual_export(self):
        items = list(self.manual_queue)
        if not items:
            self._manual_status("Add at least one selected cover first.", RED)
            return
        folder = self.manual_folder.get()
        self._manual_status("Exporting %d covers…" % len(items))
        def work():
            self.events.put(("manual_export", cw.export_many(items, folder)))
        threading.Thread(target=work, daemon=True).start()

    # ----- step 3 -----
    def _build_step3(self, body):
        self.steam_note = self._wrap(tk.Label(body, text="", bg=CARD, anchor="w", justify="left"))
        self.steam_note.pack(fill="x", pady=(0, px(6)))
        self._wrap_to_parent(body, self.steam_note)
        self._steam_note_state = None
        self.acc_row = self._flow(body)
        self.acc_label = self._wrap(tk.Label(self.acc_row, text="", bg=CARD, fg=FG, anchor="w", justify="left"), cap=px(380))
        self.acc_row.add(self.acc_label)
        self.btn_account = RoundedButton(self.acc_row, "Change account", self.choose_account)
        self.refresh_account()
        r = self._row(body)
        self.chk_restart = Switch(r, "Start Steam again when finished", self.restart_steam)
        self.chk_restart.pack(side="left")
        r = self._flow(body, pady=px(6))
        self.btn_apply = RoundedButton(r, "Apply to Steam", lambda: self.confirm_and_run("apply"), primary=True)
        r.add(self.btn_apply)
        self.btn_restore = RoundedButton(r, "Restore previous artwork", lambda: self.confirm_and_run("restore"))
        r.add(self.btn_restore, px(10))
        r2 = self._row(body, pady=px(2))
        self.btn_reset = RoundedButton(r2, "Reset to Steam's default art", self.start_reset, quiet=True)
        self.btn_reset.pack(side="left")
        self.step3_status = tk.Label(body, text="", bg=CARD, fg=MUTED, anchor="w", justify="left", wraplength=px(620))
        self._wrap_to_parent(body, self.step3_status)

    def _tick_steam_note(self):
        """The warning follows reality: amber while Steam is open (Apply will close it), calm when it is already closed."""
        if self.steam_on != self._steam_note_state:
            self._steam_note_state = self.steam_on
            if self.steam_on:
                self.steam_note.configure(fg=AMBER, font=("TkDefaultFont", 11, "bold"),
                                          text="Steam is open. These buttons close it: any running game stops and downloads pause. Save your game first.")
            else:
                self.steam_note.configure(fg=MUTED, font=("TkDefaultFont", 11),
                                          text="Steam is closed, so nothing will be interrupted. Your current artwork is backed up first, so you can undo it.")
        self._timers[2] = self.after(1000, self._tick_steam_note)

    def _acc(self):
        """Account folder to use: the user's choice if it still exists, else None (the engine picks the last one Steam used)."""
        try:
            if self.account and self.account not in [a for a, _ in sc.list_accounts(sc.steam_dir())]:
                self.account = None
        except sc.SteamcaseError:
            self.account = None
        return self.account

    def refresh_account(self):
        """Show which Steam account will be changed; with two or more accounts also offer a button to choose."""
        try:
            steam = sc.steam_dir()
            accounts = sc.list_accounts(steam)
            acc = self._acc() or sc.pick_account(steam)
            who = sc.account_label(steam, acc)
        except (sc.SteamcaseError, OSError):
            accounts, who = [], ""
        self.acc_label.configure(text="Steam account: %s" % _short(who) if who else "")
        if len(accounts) > 1:
            self.acc_row.add(self.btn_account, px(12))
        else:
            self.acc_row.remove(self.btn_account)
        if not who:
            self.acc_row.pack_forget()

    def choose_account(self):
        if self.busy or self.running:
            return
        try:
            steam = sc.steam_dir()
            accounts = sc.list_accounts(steam)
        except sc.SteamcaseError as e:
            messagebox.showerror("Steam account", str(e))
            return
        picked = messagebox.choose("Which Steam account gets the covers?",
                                   [("Apply, Restore and Reset will change only this account's artwork.", "main")],
                                   [("Cancel", None, False)] + [(_short(label if not label.isdigit() else "Account %s" % label), a, a == (self._acc() or accounts[0][0])) for a, label in accounts])
        if picked:
            self.account = picked
            self.refresh_account()
            self.say3("")
            self.refresh_step3()

    def say3(self, text, fg=MUTED):
        """Step 3 message; the line only takes space while it has something to say."""
        self.step3_status.configure(text=text, fg=fg)
        if text and not self.step3_status.winfo_ismapped():
            self.step3_status.pack(fill="x", pady=(px(8), 0))
        elif not text:
            self.step3_status.pack_forget()

    def has_grid_art(self):
        """Cheap check (no image decoding): is there any <appid>p.png in Steam's grid folder?"""
        try:
            grid = sc.grid_dir(sc.steam_dir(), self._acc())
            return os.path.isdir(grid) and any(sc._COVER_NAME.match(n) or sc._JPG_NAME.match(n) for n in os.listdir(grid))
        except sc.SteamcaseError:
            return False

    def start_reset(self):
        """Step 1 of 2: look for our covers (a few seconds, in the background). Step 2 asks, then removes them."""
        if self.busy or self.running:
            return
        self.busy = True
        self.refresh_step3()
        self.say3("Looking for covers made by this app… (a few seconds)")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        try:
            steam = sc.steam_dir()
            acc = self._acc()
            names = sc.find_our_covers(steam, acc, progress=lambda i, n: self.events.put(("step3_status", "Checking Steam's artwork… %d of %d" % (i, n))),
                                       cancelled=self.cancel_flag.is_set)
            who = sc.account_label(steam, sc.pick_account(steam, acc))
            extra, other = sc.find_other_art(steam, acc, names)
            self.events.put(("reset_scan", names, who, len(extra) + len(other)))
        except sc.SteamcaseError as e:
            self.events.put(("step3_error", str(e)))
        except Exception as e:
            self.events.put(("step3_error", "Unexpected problem: %s" % e))

    def on_reset_scan(self, names, who, other=0):
        """`other`: custom portraits this app did not make (SteamGridDB, set by hand). They only go if the user says so."""
        if not names and not other:
            self.busy = False
            self.say3("No custom covers were found in “%s”. Nothing to reset." % who)
            self.refresh_step3()
            return
        steam_on = self.steam_on
        paras = [("%d covers made by this app will be removed from the Steam account “%s”. Steam goes back to its own default art for them." % (len(names), who), "main")] if names else []
        if other:
            paras.append(("Found %d more custom covers that this app did not make (from SteamGridDB or set by hand in Steam)." % other, "main"))
        paras.append(("A backup is kept, so “Restore previous artwork” brings everything back.", "muted"))
        if steam_on:
            paras.append(("Steam will be closed automatically. Any running game stops and downloads pause. Save your game first.", "warn"))
        icon = "warning" if steam_on else "question"
        close = "Close Steam and " if steam_on else ""
        if other:
            buttons = [("Cancel", None, False)]
            if names:
                buttons.append((close + "remove only ours" if steam_on else "Remove only ours", "ours", True))
            buttons.append((close + "remove all" if steam_on else "Remove all", "all", not names))      # Enter picks the safer one when there is a choice
            choice = messagebox.choose("Reset to Steam's default art", paras, buttons, icon)
        else:
            ok = messagebox.askokcancel("Reset to Steam's default art", paras, icon=icon, ok="Close Steam and reset" if steam_on else "Reset")
            choice = "ours" if ok else None
        if not choice:
            self.busy = False
            self.say3("")
            self.refresh_step3()
            return
        self.say3("Closing Steam…" if steam_on else "Working…")
        threading.Thread(target=self._step3_worker, args=("reset", self.restart_steam.get(), names, choice == "all"), daemon=True).start()

    def has_backup(self):
        try:
            return bool(sc.list_backups(sc.steam_dir(), self._acc()))
        except sc.SteamcaseError:
            return False

    def refresh_step3(self):
        idle = not self.running and not self.busy
        count = sum(bool(item.get("verified_steam_id")) for item in self.manual_queue)
        can_apply = idle and count > 0
        for button in (self.btn_apply, self.btn_manual_apply):
            caption = "Apply %d to Steam" % count if count else "Apply to Steam"
            if button.text != caption:
                button.text = caption
                button.configure(width=button._font.measure(caption) + px(46))
                button.draw()
        self.btn_make.primary = not self.cover_files
        self.btn_make.draw()
        self.btn_apply.configure(state="normal" if can_apply else "disabled")
        self.btn_restore.configure(state="normal" if idle and self.has_backup() else "disabled")
        backup = self.has_backup()
        self.btn_reset.configure(state="normal" if idle and self.has_grid_art() else "disabled")
        self.chk_restart.configure(state="normal" if idle and (can_apply or backup) else "disabled")
        # say why Restore is greyed out, and clear that note once it no longer applies
        hint = "Nothing to undo yet: “Restore previous artwork” works once you have used “Apply to Steam” in this app."
        if idle and not can_apply and not backup and not self.step3_status.cget("text"):
            self.say3(hint, FAINT)
        elif self.step3_status.cget("text") == hint and (can_apply or backup):
            self.say3("")
        self.update_steps()
        self._manual_update_actions()

    def confirm_and_run(self, mode):
        if self.busy or self.running:
            return
        items = [dict(item) for item in self.manual_queue if item.get("verified_steam_id")] if mode == "apply" else None
        if mode == "apply" and not items:
            self.say3("Add a verified Steam game or shortcut to the queue first.", RED)
            return
        steam_on = self.steam_on
        try:
            who = sc.account_label(sc.steam_dir(), sc.pick_account(sc.steam_dir(), self._acc()))
        except sc.SteamcaseError:
            who = "your Steam account"
        if mode == "apply":
            title = "Apply queued covers to Steam"
            count = len(items)
            paras = [("%d cover%s will be added to the Steam account “%s”." % (count, "" if count == 1 else "s", who), "main"),
                     ("The whole queue is backed up and applied in one operation. Restore undoes it together.", "muted")]
            go = "Close Steam and apply" if steam_on else "Apply covers"
        else:
            title = "Restore previous artwork"
            paras = [("Your artwork from before the last Apply will be put back on the Steam account “%s”." % who, "main"),
                     ("The covers added by that Apply are removed.", "muted")]
            go = "Close Steam and restore" if steam_on else "Restore"
        if steam_on:
            paras.append(("Steam will be closed automatically. Any running game stops and downloads pause. Save your game first.", "warn"))
        if not messagebox.askokcancel(title, paras, icon="warning" if steam_on else "question", ok=go):
            return
        self.busy = True
        self.refresh_step3()
        self.say3("Preparing covers…" if items else "Working…", MUTED)
        threading.Thread(target=self._step3_worker, args=(mode, self.restart_steam.get(), None, False, items), daemon=True).start()

    def _step3_worker(self, mode, restart, names=None, everything=False, items=None):
        say = lambda message: self.events.put(("step3_status", message))
        closed = False
        error = None
        text = ""
        detail = {}
        stage = None
        try:
            steam = sc.steam_dir()
            acc = self._acc()
            files = []
            if mode == "apply":
                if not items:
                    raise sc.SteamcaseError("The Steam apply queue is empty.")
                shortcuts = None
                for item in items:
                    if item.get("game", {}).get("source", "steam") != "steam":
                        if shortcuts is None:
                            shortcuts = {int(shortcut["id"]) for shortcut in cw.list_shortcuts(steam, acc)}
                        if item["steam_id"] not in shortcuts:
                            self.events.put(("queue_status", {item["key"]: "Failed: shortcut no longer exists"}))
                            raise sc.SteamcaseError("The Steam shortcut for %s no longer exists. Choose it again. "
                                                    "No Steam artwork was changed." % item["name"])
                say("Preparing %d queued covers…" % len(items))
                cw.cache_dir().mkdir(parents=True, exist_ok=True)  # absent on a fresh install
                stage = tempfile.mkdtemp(prefix="casecovers-apply-", dir=cw.cache_dir())
                for item in items:
                    self.events.put(("queue_status", {item["key"]: "Preparing"}))
                    try:
                        if item.get("file"):
                            path = cw.validate_local_image(item["file"])
                        else:
                            path = cw.export_one(item["image"], item["platform"], item["name"],
                                                 stage, item["steam_id"])
                        if int(sc.appid_of(str(path)) or 0) != item["steam_id"]:
                            raise sc.SteamcaseError("The prepared cover ID does not match the selected Steam game.")
                        files.append(str(path))
                    except (sc.SteamcaseError, OSError, ValueError) as exc:
                        self.events.put(("queue_status", {item["key"]: "Failed: %s" % exc}))
                        raise sc.SteamcaseError("Could not prepare %s: %s. No Steam artwork was changed." %
                                                (item["name"], exc)) from exc
                self.events.put(("queue_status", {item["key"]: "Ready" for item in items}))
            if sc.steam_running():
                say("Closing Steam once…")
                if not sc.close_steam(steam):
                    raise sc.SteamcaseError("Steam did not close in time. Close it yourself (Steam menu, then Exit) and try again."
                                            + (" If macOS asked for permission, allow it first." if sys.platform == "darwin" else ""))
                closed = True
            if mode == "apply":
                say("Backing up and applying %d covers together…" % len(files))
                self.events.put(("queue_status", {item["key"]: "Applying" for item in items}))
                r = sc.apply_covers(steam, self.covers_dir, acc, files=files)
                detail = {"backup": r["backup"], "keys": [item["key"] for item in items]}
                changed = set(r["changed_ids"])
                self.events.put(("queue_status", {item["key"]: "Applied" if item["steam_id"] in changed
                                                   else "Already current" for item in items}))
                if r["applied"]:
                    text = "Done. %d covers applied to the Steam account “%s” (%d replaced, %d already current). Backup: %s" % (
                        r["applied"], r["account_name"], r["replaced"], r["unchanged"], r["backup"])
                    if r["jpg_moved"]:
                        text += " %d older JPG/WebP portraits were preserved in the backup." % r["jpg_moved"]
                else:
                    text = "All %d queued covers were already current in the Steam account “%s”." % (
                        r["unchanged"], r["account_name"])
            elif mode == "reset":
                say("Removing our covers…")
                r = sc.reset_to_default(steam, acc, names, everything)
                text = "Done. %d covers removed from the Steam account “%s”. Restore brings them back." % (
                    r["removed"], r["account_name"])
            else:
                backups = sc.list_backups(steam, acc)
                if not backups:
                    raise sc.SteamcaseError("No backup found.")
                n = sc.restore_backup(steam, backups[0], acc)
                detail = {"restored": backups[0]}
                left = len(sc.list_backups(steam, acc))
                text = "Restored your previous artwork (%d files)." % n
                if left:
                    text += " %d older backup%s remain." % (left, "" if left == 1 else "s")
            if closed and not restart:
                text += " Start Steam to see the change."
        except (sc.SteamcaseError, OSError, ValueError) as exc:
            error = str(exc)
            if mode == "apply" and items and "No Steam artwork was changed" not in error:
                status = "Failed · restore backup" if "could not be put back" in error else "Failed · no changes applied"
                self.events.put(("queue_status", {item["key"]: status for item in items}))
        except Exception as exc:
            error = "Unexpected problem: %s" % exc
            if mode == "apply" and items:
                self.events.put(("queue_status", {item["key"]: "Failed · check backup" for item in items}))
        finally:
            if closed and restart:
                say("Starting Steam once…")
                try:
                    sc.start_steam(steam)
                    if not error:
                        text += " Steam is starting."
                except sc.SteamcaseError as exc:
                    note = "Steam could not restart (%s). Open it manually." % exc
                    error = "%s %s" % (error, note) if error else None
                    if error is None:
                        text += " " + note
            if stage:
                shutil.rmtree(stage, ignore_errors=True)
            self.events.put(("step3_error", error) if error else ("step3_done", text, mode, detail))


def restore_child_env():
    """Packaged Linux app: PyInstaller points LD_LIBRARY_PATH at its bundled libraries (OpenSSL...).
    Programs we launch (xdg-open, kde-open, flatpak, Steam) would load those and crash, so undo it."""
    if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
        orig = os.environ.get("LD_LIBRARY_PATH_ORIG")
        if orig is None:
            os.environ.pop("LD_LIBRARY_PATH", None)
        else:
            os.environ["LD_LIBRARY_PATH"] = orig


def enable_dpi_awareness():
    """Windows: without this, tkinter windows look blurry on high-DPI screens."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def selftest():
    """Headless check used by the build: Pillow, Tk and bundled platform frames work."""
    import tempfile
    from PIL import Image
    try:
        assert os.path.exists(sc.FRAME), "frame image missing: %s" % sc.FRAME
        assert os.path.exists(os.path.join(sc.HERE, "assets", "icon.png")), "icon missing"
        platforms = load_catalog()["platforms"]
        assert len(platforms) == 29, "expected 29 platform configurations"
        for platform in platforms:
            assert os.path.isfile(os.path.join(sc.HERE, "assets", "frames", platform["id"] + ".png")), \
                "platform frame missing: %s" % platform["id"]
        if sys.platform.startswith("win"):
            cw.load_api_key()  # also checks that the packaged Windows credential backend loads
        assert os.path.exists(sc.FAMILY_CORNER), "family corner image missing: %s" % sc.FAMILY_CORNER
        assert os.path.exists(sc.DEFAULT_ART), "default art missing: %s" % sc.DEFAULT_ART
        restore_child_env()
        assert sc._ssl_context().cert_store_stats()["x509_ca"] > 0, "no trusted certificates loaded: secure connections to Steam would fail"
        if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
            assert getattr(sys, "_MEIPASS", "\0") not in os.environ.get("LD_LIBRARY_PATH", ""), "child programs would inherit the bundled libraries"
        with tempfile.TemporaryDirectory() as d:
            src, out = os.path.join(d, "p.png"), os.path.join(d, "c.png")
            Image.new("RGB", (600, 900), (200, 60, 60)).save(src)
            sc.build_cover(src, out, Image.open(sc.FRAME).convert("RGBA"))
            im = Image.open(out)
            assert im.size == (600, 900), "bad size %s" % (im.size,)
            assert im.getpixel((300, 500))[:3] == (200, 60, 60), "art window not filled"
            assert sc.cover_colour(out) == (0, 100, 100), "the cover does not record its colour"
            blue = sc.preview_cover(0).getpixel((7, 450))
            turned = sc.preview_cover(134)
            assert turned.size == (600, 900) and turned.getpixel((7, 450)) != blue, "the case colour cannot be changed"
            assert sc.preview_cover(0, sat=0, val=14).getpixel((7, 450)) != blue, "the case cannot be made black"
            black = os.path.join(d, "b.png")
            sc.build_cover(src, black, sc.load_frame(0, sat=0, val=14), sat=0, val=14)
            assert sc.is_steamcase_cover(black), "a black cover is not recognised as ours"
            done = os.path.join(d, "d.png")                       # the cover of a game at 100% achievements
            sc.build_cover(src, done, sc.load_frame(0), treatment="ribbon")
            assert sc.cover_treatment(done) == "ribbon", "a 100% cover does not record its style"
            assert sc.is_steamcase_cover(done), "a 100% cover is not recognised as ours"
        print("selftest ok")
        return 0
    except Exception as e:
        print("selftest FAILED:", e)
        return 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "--version" in sys.argv:
        print("Case Covers %s" % sc.APP_VERSION)
        sys.exit(0)
    if "--check-network" in sys.argv:                     # for bug reports: does this computer reach Steam?
        ok, msg = sc.check_network()
        print(("network ok: " if ok else "network FAILED: ") + msg)
        sys.exit(0 if ok else 1)
    restore_child_env()
    enable_dpi_awareness()
    App().mainloop()
