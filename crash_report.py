"""Early, persistent diagnostics for Python exceptions and native Qt crashes."""
from __future__ import annotations

import faulthandler
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

_crash_file = None  # faulthandler needs the file descriptor alive for the process lifetime.
_qt_handler = None


def log_dir():
    override = os.environ.get("CASE_COVERS_LOG_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Case Covers" / "logs"
    return Path.home() / ".local" / "state" / "case-covers"


def install():
    global _crash_file
    if _crash_file is not None:
        return log_dir()
    folder = log_dir()
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / "case-covers.log", maxBytes=2_000_000,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s"))
    root = logging.getLogger("casecovers")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    _crash_file = open(folder / "native-crash.log", "a", encoding="utf-8", buffering=1)
    faulthandler.enable(file=_crash_file, all_threads=True)

    def exception_hook(exc_type, exc, tb):
        root.critical("Unhandled Python exception", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    def thread_hook(args):
        root.critical("Unhandled thread exception", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = exception_hook
    threading.excepthook = thread_hook
    root.info("Case Covers started: pid=%d executable=%s", os.getpid(), sys.executable)
    return folder


def install_qt_handler():
    global _qt_handler
    from PySide6.QtCore import qInstallMessageHandler

    def handle(message_type, context, message):
        logging.getLogger("casecovers").warning("Qt %s: %s (%s:%s)",
                                                  message_type, message, context.file, context.line)

    _qt_handler = handle  # Keep the Python callable alive while Qt holds it.
    qInstallMessageHandler(_qt_handler)
