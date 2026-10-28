"""Windows screenshots and bounds checks for the two-column GUI and artwork grid.

Run: python tests/gui_layout_check.py 1.0 docs/gui-check/columns-100
The factor sets Tk scaling before widgets are built; system DPI is unchanged.
"""
import io
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image, ImageDraw, ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gui
from widgets import px


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def capture(window, path):
    window.update()
    path.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(window=window.winfo_id()).save(path)


def check_bounds(widget, left, right):
    for child in descendants(widget):
        if child.winfo_ismapped() and child.winfo_width() > 1:
            edge = child.winfo_rootx() + child.winfo_width()
            if child.winfo_rootx() < left - 2 or edge > right + 2:
                raise AssertionError("Clipped widget %s: %d..%d, allowed %d..%d" %
                                     (child, child.winfo_rootx(), edge, left, right))


def colored_png(color, size=(94, 132)):
    image = Image.new("RGBA", size, color)
    ImageDraw.Draw(image).rectangle((8, 8, size[0] - 9, size[1] - 9), outline="white", width=3)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def main():
    factor = float(sys.argv[1])
    target = Path(sys.argv[2])
    original = gui.set_scale

    def scaled(root):
        root.tk.call("tk", "scaling", 96 * factor / 72)
        original(root)

    gui.set_scale = scaled
    app = gui.App()
    app.update()
    assert app.title() == "Case Covers"
    assert app.winfo_height() <= min(px(860), app.winfo_screenheight() - px(110))
    if app._column_mode == "wide":
        assert not app.scroller.scrollable(), "default window should keep the header visible"
    capture(app, target.with_name(target.name + "-default.png"))
    assert app.btn_settings.winfo_ismapped()
    assert app.manual_body.winfo_ismapped(), "right panel starts open"
    assert app.resizable() == (1, 1)
    app.toggle_manual()
    app.update()
    assert not app.manual_body.winfo_ismapped(), "right panel can collapse"
    app.toggle_manual()
    app.update()
    assert app.manual_body.winfo_ismapped(), "right panel can reopen"

    wide = min(app.winfo_screenwidth() - px(40), px(1400))
    height = min(app.winfo_screenheight() - px(80), px(860))
    app.geometry("%dx%d+20+20" % (wide, height))
    app.update()
    if wide >= px(1260):
        assert app._column_mode == "wide"
        assert app.right_column.winfo_rootx() > app.left_column.winfo_rootx()
        assert app.manual_card.winfo_height() >= app.left_column.winfo_height() - px(20)
    check_bounds(app.holder, app.winfo_rootx(), app.winfo_rootx() + app.winfo_width())
    capture(app, target.with_name(target.name + "-wide.png"))

    app.geometry("%dx%d+20+20" % (app.minsize()[0], height))
    app.update()
    assert app._column_mode == "stacked"
    assert app.right_column.winfo_rooty() > app.left_column.winfo_rooty()
    check_bounds(app.holder, app.winfo_rootx(), app.winfo_rootx() + app.winfo_width())
    capture(app, target.with_name(target.name + "-narrow.png"))
    app.scroller.canvas.yview_moveto(1.0)
    capture(app, target.with_name(target.name + "-narrow-right.png"))
    app.manual_scroller.canvas.yview_moveto(0.0)
    outer_before = app.scroller.canvas.yview()
    wheel = SimpleNamespace(widget=app.manual_preview, delta=-120)
    app.scroller._wheel(wheel)
    assert app.scroller.canvas.yview() == outer_before, "wheel over right card must not scroll the whole window"
    app.manual_scroller._wheel(wheel)
    assert app.manual_scroller.canvas.yview()[0] > 0, "wheel must scroll the right card"

    app.geometry("%dx%d+20+20" % (wide, height))
    app.update()
    app.scroller.canvas.yview_moveto(0.0)
    games = ["Distinctive Game One  ·  SteamGridDB ID 7", "Distinctive Game Two  ·  SteamGridDB ID 8"]
    for game in games:
        app.game_list.insert("end", game)
    app._manual_list_visibility(app.game_list, len(games))
    arts = []
    for number in range(12):
        url = "https://example.com/art-%d.png" % number
        arts.append({"id": number, "url": url, "thumb": url, "style": "Alternate"})
        app._thumb_cache[url] = colored_png((92 + number * 11, 70 + number * 7, 150))
    app.manual_game = {"name": "Distinctive Game One", "id": 7, "source": "steamgriddb"}
    app.manual_art = arts
    app._show_art_grid(arts)
    app.update()
    assert len(app._art_tiles) == 12
    assert app.art_grid.bbox("all")[3] > app.art_grid.winfo_height(), "artwork grid must scroll"
    assert app.manual_scroller.scrollable(), "long right panel must scroll inside its card"
    assert not app.scroller.scrollable(), "gallery must not push the whole window off screen"
    check_bounds(app.holder, app.winfo_rootx(), app.winfo_rootx() + app.winfo_width())
    capture(app, target.with_name(target.name + "-gallery.png"))

    with tempfile.TemporaryDirectory() as tmp:
        art_path = Path(tmp) / "art.png"
        Image.new("RGB", (600, 900), (58, 92, 140)).save(art_path)
        with mock.patch.object(gui.cw, "ArtworkClient", return_value=SimpleNamespace(image=lambda url: art_path)):
            app._manual_pick_art(1)
            deadline = time.monotonic() + 8
            while app.manual_image is None and time.monotonic() < deadline:
                app.update()
                time.sleep(.05)
        assert app.manual_image == art_path, "selected image must render with the platform frame"
        assert app.manual_art_selected == 1
        assert app.manual_preview.cget("image"), "final frame preview is visible"
        app._manual_add()
        assert len(app.manual_queue) == 1
        app.update()
        app.manual_scroller.canvas.yview_moveto(1.0)
        app.update()
        assert app.manual_preview.winfo_rooty() + app.manual_preview.winfo_height() <= app.winfo_rooty() + app.winfo_height()
        assert app.manual_queue_label.winfo_rooty() + app.manual_queue_label.winfo_height() <= app.winfo_rooty() + app.winfo_height()
        capture(app, target.with_name(target.name + "-selected.png"))

    app.open_settings()
    app.settings_window.update()
    check_bounds(app.settings_window, app.settings_window.winfo_rootx(),
                 app.settings_window.winfo_rootx() + app.settings_window.winfo_width())
    capture(app.settings_window, target.with_name(target.name + "-settings.png"))
    print("DPI %d%%: columns, gallery, preview and bounds OK" % round(factor * 100))
    app.destroy()


if __name__ == "__main__":
    main()
