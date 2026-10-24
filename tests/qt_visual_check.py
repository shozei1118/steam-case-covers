"""Capture a deterministic Qt layout at logical 100/125/150% scale."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_SCALE_FACTOR"] = sys.argv[1] if len(sys.argv) > 1 else "1"

from PIL import Image
from PySide6.QtWidgets import QApplication

from case_service import AppSettings, CaseService, CoverItem, Game
import steamcase as sc
from qt_gui import MainWindow, STYLE


def main():
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("qt-layout.png")
    output.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyleSheet(STYLE)
    service = CaseService(AppSettings(output.parent / "visual-settings.json"))
    window = MainWindow(service, auto_refresh=False)
    window.resize(int(sys.argv[3]) if len(sys.argv) > 3 else 1150,
                  int(sys.argv[4]) if len(sys.argv) > 4 else 730)
    window.show()
    if len(sys.argv) > 6 and sys.argv[6] == "maximized":
        window.showMaximized()
    games = [Game("Half-Life 2", "steam", 220, 220, True),
             Game("A much longer example game title", "steam", 440, 440, True)]
    window._library_loaded(games)
    if "selected" in sys.argv[6:]:
        window.library_list.blockSignals(True)
        window.library_list.setCurrentRow(0)
        window.library_list.blockSignals(False)
    window.search_term.setText("Example")
    window._search_loaded([Game("Example game", "steamgriddb", 7),
                           Game("Example game II", "steamgriddb", 8)])
    window.game = Game("Example game", "steamgriddb", 7)
    window.editor.set_game(window.game)
    art = output.parent / "visual-art.png"
    Image.new("RGB", (600, 900), "#304b68").save(art)
    window.editor.current.set_path(art)
    window.editor.new.set_path(art)
    window.gallery.set_art([{"id": index, "style": "alternate", "url": "https://example.com/%s" % index}
                            for index in range(1, 9)])
    for tile in window.gallery.tiles:
        tile.set_image(art)
    window.gallery.mark_selected(window.gallery.tiles[0].art)
    service.add(CoverItem(games[0], "steam", image=str(art), preview=str(art)))
    service.add(CoverItem(games[1], "ps4", image=str(art), preview=str(art)))
    view = sys.argv[5] if len(sys.argv) > 5 else "Search"
    if view == "Backup":
        fake_steam = output.parent / "visual-steam"
        grid = fake_steam / "userdata" / "111" / "config" / "grid"
        grid.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (600, 900), "#5a4568").save(grid / "220p.png")
        (grid / "220p.jpg").unlink(missing_ok=True)
        package = output.parent / ("visual-backup-" + output.stem)
        if not package.exists():
            sc.export_artwork_backup(str(fake_steam), str(package), "111")
        Image.new("RGB", (600, 900), "#23445c").save(grid / "220p.png")
        Image.new("RGB", (600, 900), "#3a6548").save(grid / "220p.jpg")
        service.settings.account = "111"
        service.steam = lambda: str(fake_steam)
    window.navigate(view)
    if view == "Backup":
        window.backup_path_label.setText(str(package))
        window._backup_preview_loaded(sc.inspect_artwork_backup(str(fake_steam), str(package), "111"), "111")
    app.processEvents()
    window.grab().save(str(output))
    sizes = window.splitter.sizes()
    assert len(sizes) == 3 and min(sizes[:2]) > 130, sizes
    if view in ("Library", "Search"):
        assert sizes[2] > 130
        assert window.editor.apply.geometry().right() <= window.editor.width()
        assert window.editor.export.geometry().right() <= window.editor.width()
    else:
        assert sizes[2] == 0 and sizes[1] > 500, sizes
    if view in ("Search", "Library"):
        assert window.gallery.viewport().width() >= 200
    if view == "Library":
        assert window.download_game_list_button.height() >= 30
    print("scale=%s effectiveDPR=%.2f width=%d splitter=%s grid=%d/%d image=%s" %
          (os.environ["QT_SCALE_FACTOR"], window.devicePixelRatioF(), window.width(), sizes,
           window.gallery.columns, window.gallery.viewport().width(), output))
    window.close()


if __name__ == "__main__":
    main()
