"""Packaged GUI stress exercise for the Batch and artwork object lifecycles."""
from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from case_service import AppSettings, CaseService, Game


def working_set_bytes():
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    size_t = ctypes.c_size_t

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", size_t), ("WorkingSetSize", size_t),
                    ("QuotaPeakPagedPoolUsage", size_t), ("QuotaPagedPoolUsage", size_t),
                    ("QuotaPeakNonPagedPoolUsage", size_t), ("QuotaNonPagedPoolUsage", size_t),
                    ("PagefileUsage", size_t), ("PeakPagefileUsage", size_t)]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    process = kernel32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
        return None
    return counters.WorkingSetSize


def run(count=60, large=False, race=False, realistic=False, grid=False, grid_only=False):
    from qt_gui import MainWindow, STYLE

    log = logging.getLogger("casecovers")
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)

    def until(predicate, description):
        deadline = time.monotonic() + 15
        while not predicate():
            app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            if time.monotonic() >= deadline:
                raise AssertionError("Timed out waiting for " + description)
            time.sleep(.005)
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    with tempfile.TemporaryDirectory(prefix="casecovers-batch-stress-") as folder:
        root = Path(folder)
        images = []
        image_count = 8 if large else count
        for index in range(image_count):
            image = root / ("art-%03d.%s" % (index, "jpg" if large else "png"))
            Image.new("RGB", (3000, 4500) if large else (600, 900),
                      (index * 29 % 256, index * 47 % 256, index * 73 % 256)).save(image)
            images.append(image)

        class Service(CaseService):
            def artwork(self, game, _source):
                return [{"id": number, "style": "alternate", "url": str(images[(game.id + number) % image_count]),
                         "thumb": "thumb:" + str(images[(game.id + number) % image_count])}
                        for number in range(50 if grid else 1 if realistic else 8)]

            def image(self, url):
                if url.startswith("thumb:"):
                    if race:
                        time.sleep(.15)
                    url = url[6:]
                return Path(url)

            def current_cover(self, _game):
                return None

        service = Service(AppSettings(root / "settings.json"), root / "covers")
        window = MainWindow(service, auto_refresh=False)
        window.show()
        app.processEvents()
        if realistic:
            window.library_games = [Game("Stress game %03d" % index, "steam", 400000 + index,
                                         400000 + index, True) for index in range(count)]
            window.filter_library()
        start_memory = working_set_bytes()
        log.info("Batch stress started: count=%d large=%s race=%s realistic=%s grid=%s working_set=%s",
                 count, large, race, realistic, grid, start_memory)
        try:
            for index in range(count):
                steam_id = 400000 + index
                if realistic:
                    window.library_list.setCurrentRow(index)
                else:
                    window.select_game(Game("Stress game %03d" % index, "steam", steam_id,
                                            steam_id, True))
                until(lambda: len(window.gallery.tiles) == (50 if grid else 1 if realistic else 8),
                      "artwork grid")
                if grid_only:
                    continue
                if race:
                    # Move on while old thumbnails are still in the worker queue.
                    window.prepared_file = str(images[index % image_count])
                    window.preview_path = window.prepared_file
                    window.editor.new.set_path(window.preview_path)
                else:
                    window.gallery.tiles[0]._select_current()
                    until(lambda: window.preview_path is not None, "framed preview")
                window.add_to_batch()
                if not realistic:
                    window.navigate("Batch")
                assert window.batch_table.rowCount() == index + 1
                if index % 10 == 9:
                    log.info("Batch stress added=%d working_set=%s", index + 1, working_set_bytes())
            if grid_only:
                log.info("Main-window grid replacement completed: rounds=%d working_set=%s",
                         count, working_set_bytes())
                return 0
            if realistic:
                window.navigate("Batch")
            for index in range(min(50, count)):
                window.batch_table.selectRow(index)
                window.edit_batch()
                until(lambda: window.preview_path is not None, "edited framed preview")
                if race:
                    window.prepared_file = None
                    window.image_path = str(images[index % image_count])
                previous = window.preview_path
                window.editor.set_platform("ps5" if index % 2 else "wii")
                window.render_preview()
                until(lambda: window.preview_path != previous, "changed platform preview")
                window.add_to_batch()
                window.navigate("Batch")
                assert window.batch_table.rowCount() == count
                if index % 10 == 9:
                    log.info("Batch stress edited=%d working_set=%s", index + 1, working_set_bytes())
            for index in range(min(50, count)):
                window.batch_table.selectRow(0)
                window.remove_batch()
                assert window.batch_table.rowCount() == count - index - 1
                if index % 10 == 9:
                    log.info("Batch stress removed=%d working_set=%s", index + 1, working_set_bytes())
            import gc
            from PySide6.QtGui import QPixmap, QPixmapCache
            from qt_gui import ArtTile

            log.info("Batch stress before collect: tiles=%d pixmaps=%d working_set=%s",
                     sum(isinstance(obj, ArtTile) for obj in gc.get_objects()),
                     sum(isinstance(obj, QPixmap) for obj in gc.get_objects()), working_set_bytes())
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
            gc.collect()
            log.info("Batch stress after collect: tiles=%d pixmaps=%d working_set=%s",
                     sum(isinstance(obj, ArtTile) for obj in gc.get_objects()),
                     sum(isinstance(obj, QPixmap) for obj in gc.get_objects()), working_set_bytes())
            QPixmapCache.clear()
            app.processEvents()
            log.info("Batch stress after pixmap cache clear: working_set=%s", working_set_bytes())
            log.info("Batch stress completed: added=%d edited=%d removed=%d working_set=%s",
                     count, min(50, count), min(50, count), working_set_bytes())
        finally:
            window.close()
            window.jobs.waitForDone(5000)
            app.processEvents()
    return 0
