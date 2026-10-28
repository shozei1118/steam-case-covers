"""Screenshot and interaction check for many Steam shortcuts and long titles.

Run: python tests/shortcut_dialog_check.py 1.0 docs/gui-check/shortcuts-100
The factor changes Tk scaling for this process, not Windows display settings.
"""
import sys
from pathlib import Path

from PIL import ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gui
from widgets import px, set_scale


def check_bounds(dialog):
    left, right = dialog.winfo_rootx(), dialog.winfo_rootx() + dialog.winfo_width()
    top, bottom = dialog.winfo_rooty(), dialog.winfo_rooty() + dialog.winfo_height()
    for child in dialog.winfo_children():
        pending = [child]
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if widget.winfo_ismapped() and widget.winfo_width() > 1:
                assert widget.winfo_rootx() >= left - 2, str(widget)
                assert widget.winfo_rootx() + widget.winfo_width() <= right + 2, str(widget)
                assert widget.winfo_rooty() >= top - 2, str(widget)
                assert widget.winfo_rooty() + widget.winfo_height() <= bottom + 2, str(widget)
                parent = widget.master
                assert widget.winfo_rootx() + widget.winfo_width() <= parent.winfo_rootx() + parent.winfo_width() + 2, str(widget)
                assert widget.winfo_rooty() + widget.winfo_height() <= parent.winfo_rooty() + parent.winfo_height() + 2, str(widget)


def capture(dialog, path):
    dialog.update()
    path.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(window=dialog.winfo_id()).save(path)


def main():
    factor = float(sys.argv[1])
    target = Path(sys.argv[2])
    root = gui.tk.Tk()
    root.tk.call("tk", "scaling", 96 * factor / 72)
    set_scale(root)
    root.geometry("%dx%d+35+35" % (px(800), px(620)))
    root.update()
    long_name = "The Extremely Long Adventure of the Clockwork Kingdom: Definitive Edition " * 3
    options = [{"name": "Game %04d" % n, "id": 3_000_000_000 + n} for n in range(1000)]
    options.append({"name": long_name, "id": 4_000_000_001})
    dialog = gui.ShortcutPicker(root, options)
    dialog.update()
    assert dialog.listbox.size() == 1001
    assert dialog.select_button.cget("state") == "disabled", "no silent default selection"
    dialog.listbox.yview_moveto(1.0)
    check_bounds(dialog)
    capture(dialog, target.with_name(target.name + "-many.png"))

    dialog.query.set("clockwork kingdom")
    dialog.update()
    assert dialog.listbox.size() == 1
    dialog.listbox.selection_set(0)
    dialog._on_select()
    dialog.update()
    assert dialog.name.cget("text") == long_name
    assert dialog.identifier.cget("text") == "Steam shortcut ID: 4000000001"
    assert dialog.select_button.cget("state") == "normal"
    capture(dialog, target.with_name(target.name + "-long-title.png"))
    dialog.geometry("%dx%d" % dialog.minsize())
    dialog.update()
    check_bounds(dialog)
    capture(dialog, target.with_name(target.name + "-minimum.png"))
    dialog._accept()
    assert dialog.result == 4_000_000_001

    cancel = gui.ShortcutPicker(root, options)
    cancel._cancel()
    assert cancel.result is None
    root.destroy()
    print("DPI %d%%: 1001 shortcuts, search, long title, resize, Select/Cancel OK" % round(factor * 100))


if __name__ == "__main__":
    main()
