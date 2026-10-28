"""Screenshot check of the shared Steam/manual cover editor with local mock artwork.

Run: python tests/editor_visual_check.py 1.0 docs/gui-check/shared-editor-100
"""
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image, ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gui
from widgets import px


def capture(app, path):
    app.update()
    path.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(window=app.winfo_id()).save(path)


def wait_for(app, condition):
    deadline = time.monotonic() + 8
    while not condition() and time.monotonic() < deadline:
        app.update()
        time.sleep(.03)
    assert condition()


def main():
    factor = float(sys.argv[1])
    target = Path(sys.argv[2])
    original_scale = gui.set_scale

    def scaled(root):
        root.tk.call("tk", "scaling", 96 * factor / 72)
        original_scale(root)

    gui.set_scale = scaled
    with tempfile.TemporaryDirectory() as temp, mock.patch.object(gui.App, "refresh_steam_games"):
        image = Path(temp) / "art.png"
        Image.new("RGB", (600, 900), (110, 70, 145)).save(image)
        app = gui.App()
        try:
            app.update()
            app.steam_games = [(n, "Game %03d" % n) for n in range(300, 350)]
            app.steam_games.append((220, "The Long Clockwork Kingdom: Definitive Edition"))
            app.steam_game_query.set("clockwork")
            app.update()
            with mock.patch.object(app, "_load_current_steam_cover"), \
                 mock.patch.object(app, "_load_art_for_selected"):
                app.steam_game_list.selection_set(0)
                app._pick_library_game()
            assert app.manual_steam_id.get() == "220"
            assert app.manual_platform.get() == "Steam"
            app._display_current_cover(image)
            art = {"id": 9, "url": "https://example.com/portrait.png", "thumb": "https://example.com/portrait.png",
                   "style": "alternate"}
            app.manual_art = [art]
            app._show_art_grid([art])
            with mock.patch.object(gui.cw, "ArtworkClient", return_value=SimpleNamespace(image=lambda url: image)):
                app._manual_pick_art(0)
                wait_for(app, lambda: app.manual_image == image)
            assert app.btn_manual_apply.cget("state") == "normal"
            assert app.btn_manual_export.cget("state") == "normal"
            app.manual_scroller.canvas.yview_moveto(1.0)
            capture(app, target.with_name(target.name + "-steam.png"))

            output = Path(temp) / "exports"
            app.manual_folder.set(str(output))
            app._manual_export_selected()
            wait_for(app, lambda: bool(list(output.glob("*.png"))))
            assert len(list(output.glob("*.png"))) == 1

            app._manual_add()
            app.manual_game = {"id": 440, "name": "Another Library Game", "source": "steam"}
            app.manual_steam_id.set("440")
            app.manual_verified_steam_id = 440
            app.manual_image = str(image)
            app._manual_add()
            assert len(app.manual_queue) == 2
            assert app.btn_manual_apply.text == "Apply 2 to Steam"
            app.update()
            app.manual_scroller._update()
            app.manual_scroller.canvas.yview_moveto(1.0)
            capture(app, target.with_name(target.name + "-queue.png"))

            app._editor_mode("search")
            app.manual_source.set("SteamGridDB")
            app.manual_term.set("Example")
            app._manual_client = lambda key=None: SimpleNamespace(search=lambda term, source: [
                {"id": 7, "name": "Example", "source": "steamgriddb"},
                {"id": 8, "name": "Example II", "source": "steamgriddb"}])
            app._manual_search()
            wait_for(app, lambda: len(app.manual_results) == 2)
            capture(app, target.with_name(target.name + "-search.png"))
            print("DPI %d%%: Steam selection, current/new preview, direct export, manual search OK" % round(factor * 100))
        finally:
            app.destroy()


if __name__ == "__main__":
    main()
