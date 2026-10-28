#!/usr/bin/env python3
"""Case Covers PySide6 desktop UI. The Tkinter gui.py remains a fallback."""
from __future__ import annotations

import os
import sys
import logging
import time
from dataclasses import replace
from pathlib import Path

import crash_report
crash_report.install()

from PySide6.QtCore import Qt, QEvent, QObject, QRunnable, QThreadPool, Signal, Slot, QSize, QUrl, QTimer
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap, QColor, QImageReader, QPainter
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QComboBox, QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFileDialog, QMessageBox, QVBoxLayout,
    QHBoxLayout, QBoxLayout, QFormLayout, QGridLayout, QStackedWidget, QSplitter, QScrollArea,
    QProgressBar, QSizePolicy, QSplitterHandle, QStyledItemDelegate, QStyleOptionViewItem, QStyle,
)
crash_report.install_qt_handler()

import cover_workflow as cw
import steamcase as sc
from case_service import AppSettings, CaseService, CoverItem, Game
from platform_catalog import load_catalog, local_asset

BG, CARD, CARD2, LINE = "#08111D", "#112338", "#0F1C2B", "#2B4361"
FG, MUTED, ACCENT, RED = "#E9F2FB", "#A9BFD6", "#67BFFF", "#ff7b72"

STYLE = """
QWidget { color: #E9F2FB; font-family: 'Segoe UI'; font-size: 10pt; }
QMainWindow { background: #08111D; }
QFrame#card, QFrame#editor { background: #112338; border: none; border-radius: 0; }
QFrame#navigation { background: #0D1B2D; border: none; border-radius: 0; }
QFrame#backupSection { background: #0F1C2B; border: 1px solid #2B4361; border-radius: 12px; }
QFrame#artTile { background: #14283D; border: 1px solid #2B4361; border-radius: 10px; }
QFrame#artTile:hover { background: #1B3550; border-color: #67BFFF; }
QFrame#artTile[selected="true"] { background: #1B3550; border: 2px solid #67BFFF; }
QLabel#muted, QLabel#tileMeta { color: #A9BFD6; }
QLabel#title { font-size: 17pt; font-weight: 700; }
QLabel#section { font-size: 12pt; font-weight: 700; }
QLabel#eyebrow { color: #A9BFD6; font-size: 9pt; font-weight: 700; }
QPushButton { background: #203953; border: 1px solid #466584; border-radius: 8px; padding: 8px 12px; font-weight: 600; }
QPushButton:hover { background: #2B4B6A; border-color: #67BFFF; }
QPushButton:disabled { background: #1B3046; color: #7894AE; border-color: #29435D; }
QPushButton#primary { background: #67BFFF; color: #08111D; border-color: #67BFFF; }
QPushButton#primary:hover { background: #91D1FF; }
QPushButton#primary:disabled { background: #1B3046; color: #7894AE; border-color: #29435D; }
QPushButton#nav { text-align: left; border: none; background: transparent; padding: 12px 14px; color: #A9BFD6; }
QPushButton#nav:hover { background: #182D44; color: #E9F2FB; }
QPushButton#nav:checked { background: #1B3550; color: #E9F2FB; border-left: 3px solid #67BFFF; }
QLineEdit, QComboBox, QListWidget, QTableWidget { background: #0F1C2B; color: #E9F2FB; border: 1px solid #2B4361; border-radius: 8px; padding: 6px; selection-background-color: #345D7D; selection-color: #E9F2FB; }
QComboBox QAbstractItemView { background: #112338; color: #E9F2FB; selection-background-color: #345D7D; }
QListWidget::item { padding: 6px 8px; border-bottom: 1px solid #233A53; }
QListWidget::item:selected { background: #244563; border-left: 3px solid #67BFFF; }
QTableWidget { gridline-color: #2B4361; }
QHeaderView::section { background: #203953; color: #E9F2FB; border: none; padding: 8px; }
QScrollArea { border: none; background: #112338; }
QScrollArea > QWidget > QWidget { background: #112338; }
QScrollBar:vertical { background: #112338; width: 9px; }
QScrollBar::handle:vertical { background: #466584; border-radius: 4px; min-height: 26px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QSplitter::handle:horizontal { background: #2B4361; }
QProgressBar { border: 1px solid #2B4361; border-radius: 5px; text-align: center; background: #0F1C2B; }
QProgressBar::chunk { background: #67BFFF; }
QStatusBar { background: #0D1B2D; border-top: 1px solid #2B4361; color: #A9BFD6; }
QStatusBar QLabel { background: transparent; color: #A9BFD6; padding: 0 8px; }
"""


class Bridge(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)
    progress = Signal(str, str)
    backup_progress = Signal(int, int, str)


class PreviewLabel(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(100, 150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background:#0F1C2B; border:1px solid #2B4361; border-radius:8px; color:#A9BFD6;")
        self.original = None

    def set_path(self, path, empty="No cover available"):
        self.original = QPixmap(str(path)) if path else None
        if not self.original or self.original.isNull():
            self.original = None
            self.setPixmap(QPixmap())
            self.setText(empty)
        else:
            self.setText("")
            self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        if self.original:
            self.setPixmap(self.original.scaled(self.size() - QSize(6, 6),
                                                Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation))


class LibrarySplitterHandle(QSplitterHandle):
    """A full-width drag target with a restrained three-dot grip."""

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.hovered = False
        self.setCursor(Qt.CursorShape.SplitVCursor)

    def enterEvent(self, event):
        self.hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1B3550" if self.hovered else "#112338"))
        painter.setPen(QColor("#67BFFF" if self.hovered else "#466584"))
        middle = self.rect().center()
        for offset in (-8, 0, 8):
            painter.setBrush(QColor("#67BFFF" if self.hovered else "#466584"))
            painter.drawEllipse(middle.x() + offset - 1, middle.y() - 1, 3, 3)


class LibrarySplitter(QSplitter):
    def createHandle(self):
        return LibrarySplitterHandle(self.orientation(), self)


class LibraryGameDelegate(QStyledItemDelegate):
    """Paint compact rows without creating hundreds of child widgets."""

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        title = index.data(Qt.ItemDataRole.DisplayRole) or ""
        badge = index.data(Qt.ItemDataRole.UserRole + 1) or ""
        painter.save()
        area = option.rect.adjusted(12, 0, -12, 0)
        badge_width = painter.fontMetrics().horizontalAdvance(badge) + 18
        badge_rect = area.adjusted(max(0, area.width() - badge_width), 5, 0, -5)
        painter.setPen(QColor("#2B4361"))
        painter.setBrush(QColor("#203953"))
        painter.drawRoundedRect(badge_rect, 5, 5)
        painter.setPen(QColor("#A9BFD6"))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge)
        title_rect = area.adjusted(0, 0, -badge_width - 12, 0)
        title_text = painter.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight,
                                                      max(0, title_rect.width()))
        painter.setPen(QColor("#E9F2FB"))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         title_text)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(34)
        return size


class ArtTile(QFrame):
    def __init__(self, art, select, grid=None):
        super().__init__()
        self.art = art
        self.select = select
        self.grid = grid
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("artTile")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(112, 190)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(3)
        self.image = QLabel("Loading…")
        self.image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setFixedSize(98, 151)
        self.image.setStyleSheet("background:#0F1C2B; color:#A9BFD6; border-radius:6px;")
        layout.addWidget(self.image)
        self.caption = QLabel()
        self.caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setFixedHeight(22)
        layout.addWidget(self.caption)
        self.meta = QLabel()
        self.meta.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.meta.setObjectName("tileMeta")
        self.meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.meta.hide()
        self.set_art(art)

    def set_art(self, art):
        self.art = art
        self.caption.setText(str(art.get("style") or "Artwork"))
        self.meta.setText("ID %s" % art["id"] if art.get("id") else "Local artwork")
        self.setToolTip("%s · %s" % (self.caption.text(), self.meta.text()))
        self.setAccessibleName("Select %s, %s" % (self.caption.text(), self.meta.text()))
        self.set_selected(False)
        self.image.clear()
        self.image.setText("Loading…")

    def set_selected(self, selected):
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _select_current(self):
        self.select(self.art)

    def set_image(self, path):
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.image.setText("Image unavailable")
        else:
            self.image.setText("")
            self.image.setPixmap(pixmap.scaled(self.image.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._select_current()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if self.grid and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right,
                                         Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.grid.move_focus(self, event.key())
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.grid:
                self.grid.activate(self)
            else:
                self._select_current()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Space:
            self._select_current()
            event.accept()
            return
        super().keyPressEvent(event)


class ArtworkGrid(QScrollArea):
    def __init__(self, select, add_to_batch=None):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.container = QWidget()
        self.layout = QGridLayout(self.container)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.layout.setSpacing(8)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setWidget(self.container)
        self.viewport().installEventFilter(self)
        self.select = select
        self.add_to_batch = add_to_batch
        self.tiles = []
        self.spare_tiles = []
        self.columns = 0
        self.selected_art = None
        self.message = QLabel("Select a game to see available artwork.")
        self.message.setObjectName("muted")
        self.layout.addWidget(self.message, 0, 0)

    def clear_tiles(self, message="Loading artwork…"):
        for tile in self.tiles:
            self.layout.removeWidget(tile)
            tile.hide()
            self.spare_tiles.append(tile)
        self.tiles.clear()
        self.columns = 0
        self.selected_art = None
        self.container.setMinimumHeight(0)
        self.message.setText(message)
        self.message.show()

    def set_art(self, arts):
        self.clear_tiles("No artwork found. Try another source or import a local image.")
        if arts:
            self.message.hide()
            self.tiles = []
            for art in arts:
                if self.spare_tiles:
                    tile = self.spare_tiles.pop()
                    tile.set_art(art)
                else:
                    tile = ArtTile(art, self.select, self)
                self.tiles.append(tile)
                tile.show()
            self._reflow()

    def mark_selected(self, art):
        self.selected_art = art
        for tile in self.tiles:
            tile.set_selected(tile.art is art)

    def move_focus(self, tile, key):
        if tile not in self.tiles:
            return
        index = self.tiles.index(tile)
        delta = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1,
                 Qt.Key.Key_Up: -max(1, self.columns),
                 Qt.Key.Key_Down: max(1, self.columns)}[key]
        target = self.tiles[max(0, min(len(self.tiles) - 1, index + delta))]
        target.setFocus()
        self.ensureWidgetVisible(target)
        target._select_current()

    def activate(self, tile):
        if self.selected_art is tile.art and self.add_to_batch:
            self.add_to_batch()
        else:
            tile._select_current()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def eventFilter(self, watched, event):
        if watched is self.viewport() and event.type() == QEvent.Type.Resize:
            self._reflow()
        return super().eventFilter(watched, event)

    def _reflow(self):
        count = min(5, max(1, (self.viewport().width() + self.layout.spacing()) //
                            (112 + self.layout.spacing())))
        if count == self.columns:
            return
        self.columns = count
        for index, tile in enumerate(self.tiles):
            self.layout.addWidget(tile, index // count, index % count)
        if self.tiles:
            rows = (len(self.tiles) + count - 1) // count
            self.container.setMinimumHeight(rows * 190 + max(0, rows - 1) * self.layout.spacing())


class CoverEditor(QFrame):
    platform_changed = Signal(str)
    platinum_changed = Signal(bool)
    source_changed = Signal(str)
    apply_clicked = Signal()
    batch_clicked = Signal()
    export_clicked = Signal()
    import_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("editor")
        self.setMinimumWidth(325)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        title = QLabel("Cover Editor")
        title.setObjectName("title")
        layout.addWidget(title)
        self.game_title = QLabel("Select a game in Library or Search")
        self.game_title.setWordWrap(True)
        self.game_title.setObjectName("section")
        game_row = QHBoxLayout()
        game_row.addWidget(self.game_title, 1)
        self.game_state = QLabel("")
        self.game_state.setObjectName("muted")
        game_row.addWidget(self.game_state)
        layout.addLayout(game_row)
        self.identifier = QLabel("")
        self.identifier.setObjectName("muted")
        layout.addWidget(self.identifier)
        controls = QFormLayout()
        controls.setSpacing(10)
        self.platform = QComboBox()
        for platform in load_catalog()["platforms"]:
            self.platform.addItem(platform["name"], platform["id"])
        self.platform.currentIndexChanged.connect(lambda: self.platform_changed.emit(self.platform.currentData()))
        controls.addRow("Platform", self.platform)
        self.platinum = QCheckBox("Platinum Edition")
        self.platinum.setToolTip("Add a platinum rim and one trophy to this game's cover")
        self.platinum.toggled.connect(self.platinum_changed)
        controls.addRow("", self.platinum)
        self.source = QComboBox()
        self.source.setPlaceholderText("Imported local image")
        self.source.addItems(["Steam CDN", "SteamGridDB"])
        self.source.currentTextChanged.connect(self.source_changed)
        controls.addRow("Image source", self.source)
        layout.addLayout(controls)
        self.import_button = QPushButton("Import PNG / JPG / WebP")
        self.import_button.clicked.connect(self.import_clicked)
        layout.addWidget(self.import_button)
        previews = QHBoxLayout()
        current_col, new_col = QVBoxLayout(), QVBoxLayout()
        current_heading = QLabel("CURRENT")
        current_heading.setObjectName("eyebrow")
        new_heading = QLabel("NEW FRAME")
        new_heading.setObjectName("eyebrow")
        current_col.addWidget(current_heading)
        new_col.addWidget(new_heading)
        self.current = PreviewLabel("Select a Steam game")
        self.new = PreviewLabel("Select artwork")
        current_col.addWidget(self.current, 1)
        new_col.addWidget(self.new, 1)
        previews.addLayout(current_col, 1)
        previews.addLayout(new_col, 1)
        layout.addLayout(previews, 1)
        self.status = QLabel("Choose a game and artwork to begin.")
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        layout.addWidget(self.status)
        actions = QGridLayout()
        self.action_mode = None
        self.apply = QPushButton("Apply to Steam")
        self.apply.setObjectName("primary")
        self.apply.clicked.connect(self.apply_clicked)
        self.batch = QPushButton("Add to batch")
        self.batch.clicked.connect(self.batch_clicked)
        self.export = QPushButton("Export PNG")
        self.export.clicked.connect(self.export_clicked)
        for button in (self.apply, self.batch, self.export):
            button.setEnabled(False)
        self.actions = actions
        layout.addLayout(actions)
        self._layout_actions(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_actions(self.width() < 410)

    def _layout_actions(self, compact):
        if self.action_mode == compact:
            return
        self.action_mode = compact
        for button in (self.apply, self.batch, self.export):
            self.actions.removeWidget(button)
        if compact:
            self.actions.addWidget(self.apply, 0, 0, 1, 2)
            self.actions.addWidget(self.batch, 1, 0)
            self.actions.addWidget(self.export, 1, 1)
        else:
            for column, button in enumerate((self.apply, self.batch, self.export)):
                self.actions.addWidget(button, 0, column)

    def set_game(self, game):
        self.game_title.setText(game.name if game else "Select a game in Library or Search")
        self.game_state.setText(("Non-Steam" if game.source == "shortcut" else
                                 "Steam · Installed" if game.source == "steam" and game.installed else
                                 "Steam · Not installed" if game.source == "steam" else
                                 "Search result") if game else "")
        self.identifier.setText("Steam ID %s" % game.steam_id if game and game.steam_id else
                                "Local export only" if game else "")
        self.current.set_path(None, "Loading current cover…" if game and game.steam_id else "No Steam cover")
        self.new.set_path(None, "Select artwork")

    def set_platform(self, platform_id):
        index = self.platform.findData(platform_id)
        if index >= 0:
            self.platform.blockSignals(True)
            self.platform.setCurrentIndex(index)
            self.platform.blockSignals(False)

    def set_platinum(self, enabled):
        self.platinum.blockSignals(True)
        self.platinum.setChecked(bool(enabled))
        self.platinum.blockSignals(False)

    def set_source(self, source):
        self.source.blockSignals(True)
        if source == "Local file":
            self.source.setCurrentIndex(-1)
        else:
            self.source.setCurrentText(source)
        self.source.blockSignals(False)

    def set_ready(self, ready, verified):
        self.apply.setEnabled(bool(ready and verified))
        self.batch.setEnabled(bool(ready))
        self.export.setEnabled(bool(ready))


class MainWindow(QMainWindow):
    def __init__(self, service=None, auto_refresh=True):
        super().__init__()
        self.service = service or CaseService()
        self.setWindowTitle("Case Covers")
        self.setWindowIcon(QIcon(local_asset("assets/icon.png")))
        self.setMinimumSize(900, 610)
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(max(900, min(1250, int(available.width() * .9))),
                    max(610, min(780, int(available.height() * .9))))
        self.jobs = QThreadPool.globalInstance()
        self.jobs.setMaxThreadCount(5)
        self.bridge = Bridge(self)
        self.bridge.finished.connect(self._job_finished)
        self.bridge.failed.connect(self._job_failed)
        self.bridge.progress.connect(self._progress)
        self.bridge.backup_progress.connect(self._backup_progress)
        self.callbacks = {}
        self.next_job = 0
        self.selection_token = 0
        self.search_token = 0
        self.art_token = 0
        self.preview_token = 0
        self.thumbnail_cache = {}
        self.game = None
        self.image_path = None
        self.prepared_file = None
        self.preview_path = None
        self.artworks = []
        self.local_image = False
        self.backup_preview = None
        self.busy = False
        self.shortcut_context = None
        self.library_games = []
        self.library_token = 0
        self.search_games = []
        self._build()
        self.navigate("Library")
        if auto_refresh:
            self.refresh_library()
            self.refresh_accounts()

    def _build(self):
        root = QSplitter(Qt.Orientation.Horizontal)
        root.setHandleWidth(1)
        self.setCentralWidget(root)
        nav = QFrame()
        nav.setObjectName("navigation")
        nav.setMinimumWidth(145)
        nav.setMaximumWidth(220)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(16, 20, 16, 16)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(9)
        icon = QLabel()
        pixmap = QPixmap(local_asset("assets/icon.png"))
        icon.setPixmap(pixmap.scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
        brand_row.addWidget(icon)
        brand = QLabel("Case\nCovers")
        brand.setObjectName("section")
        brand_row.addWidget(brand, 1)
        nav_layout.addLayout(brand_row)
        nav_layout.addSpacing(24)
        self.nav = {}
        for name in ("Library", "Search", "Batch", "Backup", "Settings"):
            button = QPushButton(name)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, page=name: self.navigate(page))
            nav_layout.addWidget(button)
            self.nav[name] = button
        nav_layout.addStretch(1)
        root.addWidget(nav)
        center = QFrame()
        center.setObjectName("card")
        center.setMinimumWidth(330)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(18, 18, 18, 18)
        center_layout.setSpacing(12)
        self.pages = QStackedWidget()
        self.pages.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        self.pages.setMinimumHeight(305)
        self.library_page = self._library_page()
        self.search_page = self._search_page()
        self.batch_page = self._batch_page()
        self.backup_page = self._backup_page()
        self.settings_page = self._settings_page()
        for page in (self.library_page, self.search_page, self.batch_page,
                     self.backup_page, self.settings_page):
            self.pages.addWidget(page)
        self.gallery_wrap = QWidget()
        self.gallery_wrap.setMinimumHeight(100)
        self.gallery_wrap.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        gallery_layout = QVBoxLayout(self.gallery_wrap)
        gallery_layout.setContentsMargins(0, 8, 0, 0)
        gallery_title = QLabel("COVER ARTWORK")
        gallery_title.setObjectName("section")
        gallery_layout.addWidget(gallery_title)
        self.gallery = ArtworkGrid(self.select_art, self.add_to_batch)
        gallery_layout.addWidget(self.gallery, 1)
        self.library_splitter = LibrarySplitter(Qt.Orientation.Vertical)
        self.library_splitter.setHandleWidth(9)
        self.library_splitter.addWidget(self.pages)
        self.library_splitter.addWidget(self.gallery_wrap)
        self.library_splitter.setStretchFactor(0, 2)
        self.library_splitter.setStretchFactor(1, 3)
        self.library_splitter.setSizes(self.service.settings.library_splitter_sizes)
        self._splitter_save_timer = QTimer(self)
        self._splitter_save_timer.setSingleShot(True)
        self._splitter_save_timer.timeout.connect(self.service.settings.save)
        self.library_splitter.splitterMoved.connect(self._save_library_splitter)
        center_layout.addWidget(self.library_splitter, 1)
        root.addWidget(center)
        self.editor = CoverEditor()
        self.editor.platform_changed.connect(self.platform_changed)
        self.editor.platinum_changed.connect(self.platinum_changed)
        self.editor.source_changed.connect(self.source_changed)
        self.editor.apply_clicked.connect(self.apply_selected)
        self.editor.batch_clicked.connect(self.add_to_batch)
        self.editor.export_clicked.connect(self.export_selected)
        self.editor.import_clicked.connect(self.import_image)
        root.addWidget(self.editor)
        root.setStretchFactor(0, 0)
        root.setStretchFactor(1, 2)
        root.setStretchFactor(2, 2)
        root.setSizes([175, 750, 565])
        self.splitter = root
        self.library_status = QLabel("Library · not loaded")
        self.steam_status = QLabel("Steam · checking")
        self.sgdb_status = QLabel("SteamGridDB · checking")
        for label in (self.library_status, self.steam_status, self.sgdb_status):
            self.statusBar().addPermanentWidget(label)
        self.statusBar().showMessage("Ready")
        self.run_job(lambda: bool(cw.load_api_key()),
                     lambda configured: self.sgdb_status.setText(
                         "SteamGridDB · ready" if configured else "SteamGridDB · key needed"),
                     lambda _error: self.sgdb_status.setText("SteamGridDB · unavailable"))

    def _library_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        title = QLabel("Library")
        title.setObjectName("title")
        layout.addWidget(title)
        row = QHBoxLayout()
        self.library_filter = QLineEdit()
        self.library_filter.setPlaceholderText("Search games or Steam IDs")
        self.library_filter.textChanged.connect(self.filter_library)
        row.addWidget(self.library_filter, 1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_library)
        row.addWidget(refresh)
        layout.addLayout(row)
        self.library_scope = QComboBox()
        for scope in ("All", "Installed", "Not installed", "Non-Steam"):
            self.library_scope.addItem(scope, scope)
        self.library_scope.currentIndexChanged.connect(self.filter_library)
        layout.addWidget(self.library_scope)
        games_heading = QLabel("YOUR GAMES")
        games_heading.setObjectName("eyebrow")
        layout.addWidget(games_heading)
        self.library_list = QListWidget()
        self.library_list.setMinimumHeight(90)
        self.library_list.setWordWrap(False)
        self.library_list.setUniformItemSizes(True)
        self.library_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.library_list.setItemDelegate(LibraryGameDelegate(self.library_list))
        self.library_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.library_list.currentRowChanged.connect(self.library_selected)
        self.library_list.itemClicked.connect(lambda item: self.library_selected(self.library_list.row(item)))
        layout.addWidget(self.library_list, 1)
        actions = QVBoxLayout()
        actions.setSpacing(7)
        library_files = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.library_file_actions = library_files
        library_files.setSpacing(7)
        download = QPushButton("Download your game list")
        download.setMinimumHeight(31)
        self.download_game_list_button = download
        download.setToolTip("Open Steam's game list in your browser; save it as userdata.json")
        download.clicked.connect(self.download_game_list)
        library_files.addWidget(download, 1)
        load = QPushButton("Load userdata.json")
        load.setMinimumHeight(31)
        load.clicked.connect(self.load_userdata)
        library_files.addWidget(load, 1)
        local_only = QPushButton("Local only")
        local_only.setMinimumHeight(31)
        local_only.setToolTip("Stop using the imported userdata.json; show installed games and shortcuts")
        local_only.clicked.connect(self.clear_userdata)
        library_files.addWidget(local_only)
        actions.addLayout(library_files)
        self.library_file_hint = QLabel()
        self.library_file_hint.setObjectName("muted")
        self.library_file_hint.setWordWrap(True)
        self.library_file_hint.hide()
        actions.addWidget(self.library_file_hint)
        layout.addLayout(actions)
        page.installEventFilter(self)
        return page

    def eventFilter(self, watched, event):
        if watched is getattr(self, "library_page", None) and event.type() == QEvent.Type.Resize:
            direction = (QBoxLayout.Direction.TopToBottom if event.size().width() < 335
                         else QBoxLayout.Direction.LeftToRight)
            self.library_file_actions.setDirection(direction)
        return super().eventFilter(watched, event)

    def _search_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        title = QLabel("Search")
        title.setObjectName("title")
        layout.addWidget(title)
        self.search_source = QComboBox()
        self.search_source.addItems(["Steam CDN", "SteamGridDB"])
        if self.service.settings.default_source == "SteamGridDB":
            self.search_source.setCurrentText("SteamGridDB")
        layout.addWidget(self.search_source)
        row = QHBoxLayout()
        self.search_term = QLineEdit()
        self.search_term.setPlaceholderText("Game title")
        self.search_term.returnPressed.connect(self.search_games_now)
        row.addWidget(self.search_term, 1)
        search = QPushButton("Search games")
        search.clicked.connect(self.search_games_now)
        row.addWidget(search)
        layout.addLayout(row)
        matches_heading = QLabel("MATCHING GAMES")
        matches_heading.setObjectName("eyebrow")
        layout.addWidget(matches_heading)
        self.search_list = QListWidget()
        self.search_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.search_list.setWordWrap(True)
        self.search_list.currentRowChanged.connect(self.search_selected)
        self.search_list.itemClicked.connect(lambda item: self.search_selected(self.search_list.row(item)))
        layout.addWidget(self.search_list, 1)
        return page

    def _batch_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        title = QLabel("Batch")
        title.setObjectName("title")
        layout.addWidget(title)
        self.batch_note = QLabel("Queue covers in the editor, then apply or export them together.")
        self.batch_note.setObjectName("muted")
        self.batch_note.setWordWrap(True)
        layout.addWidget(self.batch_note)
        self.batch_table = QTableWidget(0, 3)
        self.batch_table.setIconSize(QSize(40, 60))
        self.batch_table.setHorizontalHeaderLabels(["Game and cover", "Platform", "Status"])
        self.batch_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.batch_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.batch_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.batch_table.verticalHeader().hide()
        self.batch_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.batch_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.batch_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.batch_table.itemDoubleClicked.connect(lambda _item: self.edit_batch())
        layout.addWidget(self.batch_table, 1)
        row = QGridLayout()
        edit = QPushButton("Edit selected")
        edit.clicked.connect(self.edit_batch)
        remove = QPushButton("Remove")
        remove.clicked.connect(self.remove_batch)
        export = QPushButton("Export all PNGs")
        export.clicked.connect(self.export_all)
        row.addWidget(edit, 0, 0)
        row.addWidget(remove, 0, 1)
        row.addWidget(export, 1, 0, 1, 2)
        layout.addLayout(row)
        self.apply_all_button = QPushButton("Apply all to Steam")
        self.apply_all_button.setObjectName("primary")
        self.apply_all_button.clicked.connect(self.apply_all)
        layout.addWidget(self.apply_all_button)
        auto_section = QFrame()
        auto_section.setObjectName("backupSection")
        auto_layout = QVBoxLayout(auto_section)
        auto_layout.setContentsMargins(16, 12, 16, 12)
        auto_heading = QLabel("Automatic generation")
        auto_heading.setObjectName("section")
        auto_layout.addWidget(auto_heading)
        self.generate_all_button = QPushButton("Generate all covers")
        self.generate_all_button.clicked.connect(self.generate_all)
        auto_layout.addWidget(self.generate_all_button)
        self.skip_blurry = QCheckBox("Skip blurry Steam artwork")
        auto_layout.addWidget(self.skip_blurry)
        self.cancel_generation = QPushButton("Cancel generation")
        self.cancel_generation.clicked.connect(lambda: setattr(self, "cancel_auto", True))
        self.cancel_generation.hide()
        auto_layout.addWidget(self.cancel_generation)
        self.library_progress = QProgressBar()
        self.library_progress.hide()
        auto_layout.addWidget(self.library_progress)
        layout.addWidget(auto_section)
        return page

    def _backup_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        title = QLabel("Backup")
        title.setObjectName("title")
        layout.addWidget(title)
        self.backup_account = QLabel()
        self.backup_account.setObjectName("muted")
        layout.addWidget(self.backup_account)

        export_section = QFrame()
        export_section.setObjectName("backupSection")
        export_layout = QVBoxLayout(export_section)
        export_layout.setContentsMargins(16, 16, 16, 16)
        export_layout.setSpacing(8)
        heading = QLabel("Export current artwork")
        heading.setObjectName("section")
        export_layout.addWidget(heading)
        note = QLabel("Save every locally stored custom portrait in this Steam account, including non-Steam shortcuts and artwork added outside Case Covers. Steam CDN defaults are not local files.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        export_layout.addWidget(note)
        self.backup_export_button = QPushButton("Export current artwork…")
        self.backup_export_button.clicked.connect(self.export_current_artwork)
        export_layout.addWidget(self.backup_export_button)
        layout.addWidget(export_section)

        import_heading = QLabel("Import artwork backup")
        import_heading.setObjectName("section")
        layout.addWidget(import_heading)
        chooser = QHBoxLayout()
        choose = QPushButton("Choose backup folder…")
        choose.clicked.connect(self.choose_artwork_backup)
        chooser.addWidget(choose)
        self.backup_import_button = QPushButton("Import selected backup")
        self.backup_import_button.setObjectName("primary")
        self.backup_import_button.setEnabled(False)
        self.backup_import_button.clicked.connect(self.import_selected_backup)
        chooser.addWidget(self.backup_import_button)
        layout.addLayout(chooser)
        self.backup_path_label = QLabel("Choose a folder containing a Case Covers artwork manifest.")
        self.backup_path_label.setObjectName("muted")
        self.backup_path_label.setWordWrap(True)
        layout.addWidget(self.backup_path_label)
        self.backup_summary = QLabel("No backup selected.")
        self.backup_summary.setWordWrap(True)
        layout.addWidget(self.backup_summary)
        preview_row = QHBoxLayout()
        self.backup_table = QTableWidget(0, 3)
        self.backup_table.setHorizontalHeaderLabels(["Original file / game ID", "Size", "Import action"])
        self.backup_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.backup_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.backup_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.backup_table.verticalHeader().hide()
        self.backup_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.backup_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.backup_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.backup_table.currentCellChanged.connect(self._backup_row_selected)
        preview_row.addWidget(self.backup_table, 3)
        self.backup_image = PreviewLabel("Select a file to preview")
        self.backup_image.setMinimumSize(140, 180)
        self.backup_image.setMaximumWidth(220)
        preview_row.addWidget(self.backup_image, 1)
        layout.addLayout(preview_row, 1)
        self.backup_progress_label = QLabel("")
        self.backup_progress_label.setObjectName("muted")
        layout.addWidget(self.backup_progress_label)
        self.backup_progress = QProgressBar()
        self.backup_progress.hide()
        layout.addWidget(self.backup_progress)
        self.backup_result = QLabel("")
        self.backup_result.setWordWrap(True)
        self.backup_result.setObjectName("muted")
        layout.addWidget(self.backup_result)
        recovery = QFrame()
        recovery.setObjectName("backupSection")
        recovery_layout = QVBoxLayout(recovery)
        recovery_layout.setContentsMargins(16, 16, 16, 16)
        self.backup_label = QLabel("Restore uses the newest backup for the selected account.")
        self.backup_label.setObjectName("muted")
        recovery_layout.addWidget(self.backup_label)
        recovery_row = QHBoxLayout()
        restore = QPushButton("Restore previous artwork")
        restore.clicked.connect(self.restore)
        reset = QPushButton("Reset to Steam default")
        reset.clicked.connect(self.reset_default)
        recovery_row.addWidget(restore)
        recovery_row.addWidget(reset)
        recovery_layout.addLayout(recovery_row)
        self.reset_everything = QCheckBox("Reset all custom portraits")
        self.reset_everything.setToolTip("Includes artwork added outside Case Covers")
        recovery_layout.addWidget(self.reset_everything)
        layout.addWidget(recovery)
        return page

    def _settings_page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(10)
        title = QLabel("Settings")
        title.setObjectName("title")
        layout.addWidget(title)
        key_label = QLabel("SteamGridDB API key · stored in the OS credential store")
        key_label.setWordWrap(True)
        layout.addWidget(key_label)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Enter a new key; saved keys are never displayed")
        layout.addWidget(self.api_key)
        key_row = QGridLayout()
        save_key = QPushButton("Check and save")
        save_key.clicked.connect(self.save_key)
        check_key = QPushButton("Verify stored")
        check_key.clicked.connect(self.verify_key)
        delete_key = QPushButton("Delete")
        delete_key.clicked.connect(self.delete_key)
        key_row.addWidget(save_key, 0, 0, 1, 2)
        key_row.addWidget(check_key, 1, 0)
        key_row.addWidget(delete_key, 1, 1)
        layout.addLayout(key_row)
        layout.addSpacing(14)
        layout.addWidget(QLabel("Default export folder"))
        folder_row = QHBoxLayout()
        self.export_folder = QLineEdit(self.service.settings.export_dir)
        self.export_folder.setMinimumWidth(0)
        self.export_folder.editingFinished.connect(self.save_preferences)
        folder_row.addWidget(self.export_folder, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse_export_folder)
        folder_row.addWidget(browse)
        layout.addLayout(folder_row)
        layout.addWidget(QLabel("Default artwork source"))
        self.default_source = QComboBox()
        self.default_source.addItems(["Automatic", "Steam CDN", "SteamGridDB"])
        self.default_source.setCurrentText(self.service.settings.default_source)
        self.default_source.currentTextChanged.connect(self.save_preferences)
        layout.addWidget(self.default_source)
        self.restart_checkbox = QCheckBox("Start Steam again after Apply / Restore / Reset")
        self.restart_checkbox.setChecked(self.service.settings.restart_steam)
        self.restart_checkbox.toggled.connect(self.save_preferences)
        layout.addWidget(self.restart_checkbox)
        layout.addWidget(QLabel("Steam account"))
        self.account_combo = QComboBox()
        self.account_combo.addItem("Most recent account", None)
        self.account_combo.currentIndexChanged.connect(self.account_changed)
        layout.addWidget(self.account_combo)
        layout.addStretch(1)
        scroll.setWidget(page)
        return scroll

    def navigate(self, name, preserve_shortcut=False):
        if name == "Search" and not preserve_shortcut:
            self.shortcut_context = None
        pages = {"Library": 0, "Search": 1, "Batch": 2, "Backup": 3, "Settings": 4}
        self.pages.setCurrentIndex(pages[name])
        for key, button in self.nav.items():
            button.setChecked(key == name)
        self.gallery_wrap.setVisible(name in ("Library", "Search"))
        self.editor.setVisible(name in ("Library", "Search"))
        if name == "Library":
            self.library_splitter.setSizes(self.service.settings.library_splitter_sizes)
        self.statusBar().showMessage(name)
        if name == "Batch":
            self.refresh_batch()
        elif name == "Backup":
            self._update_backup_account()
        elif name == "Settings":
            self.refresh_backups()

    def _save_library_splitter(self, *_args):
        if self.pages.currentWidget() is not self.library_page or not self.gallery_wrap.isVisible():
            return
        sizes = self.library_splitter.sizes()
        if len(sizes) == 2 and all(size >= 100 for size in sizes):
            self.service.settings.library_splitter_sizes = sizes
            self._splitter_save_timer.start(250)

    def closeEvent(self, event):
        if self._splitter_save_timer.isActive():
            self._splitter_save_timer.stop()
            self.service.settings.save()
        super().closeEvent(event)

    def run_job(self, fn, on_success, on_error=None):
        self.next_job += 1
        number = self.next_job
        self.callbacks[number] = (on_success, on_error)

        def execute():
            try:
                self.bridge.finished.emit(number, fn())
            except Exception as exc:
                logging.getLogger("casecovers").exception("Background job %d failed", number)
                self.bridge.failed.emit(number, str(exc))

        self.jobs.start(QRunnable.create(execute))
        return number

    @Slot(int, object)
    def _job_finished(self, number, result):
        callback = self.callbacks.pop(number, None)
        if callback:
            callback[0](result)

    @Slot(int, str)
    def _job_failed(self, number, error):
        callback = self.callbacks.pop(number, None)
        if callback:
            if callback[1]:
                callback[1](error)
            else:
                self.show_error(error)

    @Slot(str, str)
    def _progress(self, key, status):
        if key in self.service.queue:
            self.service.queue[key] = replace(self.service.queue[key], status=status)
            self.refresh_batch()
        elif status:
            self.statusBar().showMessage(status)

    @Slot(int, int, str)
    def _backup_progress(self, done, total, phase):
        self.backup_progress.setRange(0, max(1, total))
        self.backup_progress.setValue(min(done, max(1, total)))
        self.backup_progress_label.setText("%s · %d/%d" % (phase, done, total))

    def show_error(self, message):
        self.editor.status.setText(message)
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, "Case Covers", message)

    def refresh_library(self):
        self.library_token += 1
        token = self.library_token
        self.library_list.clear()
        self.library_list.addItem("Loading Steam library and shortcuts…")
        self.run_job(self.service.library,
                     lambda games: self._library_loaded(games) if token == self.library_token else None,
                     lambda error: self._library_failed(error) if token == self.library_token else None)

    def _library_failed(self, error):
        self.library_games = []
        self.library_list.clear()
        self.library_list.addItem("Steam library unavailable. Search and local export still work.")
        self.library_status.setText("Library · unavailable")
        self.steam_status.setText("Steam · unavailable")
        self.statusBar().showMessage(error)

    def _library_loaded(self, games):
        self.library_games = games
        self.filter_library()
        self.steam_status.setText("Steam · library found")
        if self.service.last_library_warning:
            self.library_file_hint.setText(self.service.last_library_warning)
            self.library_file_hint.show()
        else:
            self.library_file_hint.hide()
        self.statusBar().showMessage("%d unique games and shortcuts found" % len(games))

    def filter_library(self):
        needle = self.library_filter.text().strip().casefold()
        scope = self.library_scope.currentData() or "All"
        matching = [game for game in self.library_games
                    if not needle or needle in game.name.casefold() or
                    needle in str(game.steam_id or "")]
        counts = {"All": len(matching),
                  "Installed": sum(game.source == "steam" and game.installed for game in matching),
                  "Not installed": sum(game.source == "steam" and not game.installed for game in matching),
                  "Non-Steam": sum(game.source == "shortcut" for game in matching)}
        self.library_scope.blockSignals(True)
        for index in range(self.library_scope.count()):
            key = self.library_scope.itemData(index)
            self.library_scope.setItemText(index, "%s (%d)" % (key, counts[key]))
        self.library_scope.blockSignals(False)
        self.library_list.blockSignals(True)
        self.library_list.clear()
        for game in matching:
            if ((scope == "Installed" and (game.source != "steam" or not game.installed)) or
                (scope == "Not installed" and (game.source != "steam" or game.installed)) or
                (scope == "Non-Steam" and game.source != "shortcut")):
                continue
            label = ("Installed" if game.installed else "Not installed") if game.source == "steam" else "Non-Steam"
            item = QListWidgetItem(game.name)
            item.setToolTip("%s\n%s · ID %s" % (game.name, label, game.steam_id))
            item.setData(Qt.ItemDataRole.UserRole, game)
            item.setData(Qt.ItemDataRole.UserRole + 1, label)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, "%s · %s" % (game.name, label))
            self.library_list.addItem(item)
            if self.game and game.source == self.game.source and game.steam_id == self.game.steam_id:
                self.library_list.setCurrentItem(item)
        self.library_list.blockSignals(False)
        total = len(self.library_games)
        self.library_status.setText("Library · %d/%d · %d installed · %d imported (not installed) · %d non-Steam" %
                                    (self.library_list.count(), total,
                                     sum(game.source == "steam" and game.installed for game in self.library_games),
                                     sum(game.source == "steam" and not game.installed for game in self.library_games),
                                     sum(game.source == "shortcut" for game in self.library_games)))

    def library_selected(self, row):
        item = self.library_list.item(row)
        if not item:
            return
        game = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(game, Game):
            return
        if self.game and game.source == self.game.source and game.steam_id == self.game.steam_id:
            return
        if game.source == "shortcut":
            self.shortcut_context = game
            self.selection_token += 1
            token = self.selection_token
            self.art_token += 1
            self.preview_token += 1
            self.game = game
            self.image_path = self.preview_path = None
            self.prepared_file = None
            self.navigate("Search", preserve_shortcut=True)
            self.search_source.setCurrentText("SteamGridDB")
            self.search_term.setText(game.name)
            self.search_games_now()
            self.editor.set_game(game)
            self.editor.set_platform("steam")
            self.editor.set_platinum(self.service.platinum_for(game))
            self.editor.set_source("SteamGridDB")
            self.editor.set_ready(False, True)
            self.gallery.clear_tiles("Choose the matching search result, or import an image.")
            self.run_job(lambda: self.service.current_cover(game),
                         lambda path: self.editor.current.set_path(path) if token == self.selection_token else None,
                         lambda _error: None)
            self.editor.status.setText("Choose the matching search result explicitly, or import an image.")
        else:
            self.shortcut_context = None
            self.select_game(game)

    def load_userdata(self):
        path, _filter = QFileDialog.getOpenFileName(self, "Load Steam userdata.json", "", "JSON files (*.json)")
        if path:
            try:
                sc.owned_ids(path)
            except sc.SteamcaseError as exc:
                self.show_error(str(exc))
                return
            self.service.settings.userdata = path
            self.service.settings.save()
            self.library_file_hint.hide()
            self.refresh_library()

    def clear_userdata(self):
        if self.service.settings.userdata:
            self.service.settings.userdata = None
            self.service.settings.save()
            self.refresh_library()

    def download_game_list(self):
        url = sc.library_login_url()
        if QDesktopServices.openUrl(QUrl(url)):
            self.library_file_hint.setText("Log in to Steam in your browser, save the page as userdata.json, then click Load userdata.json.")
        else:
            QApplication.clipboard().setText(url)
            self.library_file_hint.setText("The browser could not open. The Steam link was copied to the clipboard; open it, save userdata.json, then load it here.")
        self.library_file_hint.show()

    def search_games_now(self):
        term, source = self.search_term.text().strip(), self.search_source.currentText()
        self.search_token += 1
        token = self.search_token
        self.search_games = []
        self.search_list.clear()
        self.search_list.addItem("Searching…")
        self.run_job(lambda: self.service.search(term, source),
                     lambda games: self._search_loaded(games) if token == self.search_token else None,
                     lambda error: (self.search_list.clear(), self.show_error(error))
                     if token == self.search_token else None)

    def _search_loaded(self, games):
        self.search_games = games
        self.search_list.blockSignals(True)
        self.search_list.clear()
        for game in games:
            item = QListWidgetItem("%s · %s ID %s" % (game.name, game.source, game.id))
            item.setData(Qt.ItemDataRole.UserRole, game)
            self.search_list.addItem(item)
        if not games:
            self.search_list.addItem("No games found. Try another title or source.")
        self.search_list.blockSignals(False)
        self.statusBar().showMessage("%d games found. Choose one explicitly." % len(games) if games else
                                     "No games found. Try another title or source.")

    def search_selected(self, row):
        item = self.search_list.item(row)
        if not item:
            return
        game = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(game, Game):
            return
        if self.shortcut_context and game.source == "steamgriddb":
            game = replace(game, steam_id=self.shortcut_context.steam_id, verified=True)
        else:
            self.shortcut_context = None
        if game == self.game:
            return
        self.select_game(game)

    def select_game(self, game):
        self.selection_token += 1
        self.preview_token += 1
        token = self.selection_token
        self.game = game
        self.local_image = False
        self.image_path = self.preview_path = None
        self.prepared_file = None
        self.editor.set_game(game)
        self.editor.set_platform(self.service.platform_for(game))
        self.editor.set_platinum(self.service.platinum_for(game))
        self.editor.set_source(self.service.default_source(game))
        self.editor.set_ready(False, game.verified)
        self.editor.status.setText("Loading current cover and artwork…")
        self.gallery.clear_tiles()
        if game.steam_id:
            self.run_job(lambda: self.service.current_cover(game),
                         lambda path: self.editor.current.set_path(path) if token == self.selection_token else None,
                         lambda error: self.editor.current.set_path(None, "Current cover unavailable")
                         if token == self.selection_token else None)
        self.load_art()

    def load_art(self):
        if not self.game:
            return
        self.art_token += 1
        token = self.art_token
        game, source = self.game, self.editor.source.currentText()
        self.gallery.clear_tiles("Loading %s artwork…" % source if not self.local_image else "Local image selected.")
        if self.local_image:
            return
        self.editor.status.setText("Loading %s artwork…" % source)
        self.run_job(lambda: self.service.artwork(game, source),
                     lambda arts: self._art_loaded(token, arts),
                     lambda error: self._art_error(token, error))

    def _art_loaded(self, token, arts):
        if token != self.art_token:
            return
        self.artworks = arts
        self.gallery.set_art(arts)
        for tile in self.gallery.tiles:
            url = tile.art.get("thumb") or tile.art["url"]
            if url in self.thumbnail_cache:
                tile.set_image(self.thumbnail_cache[url])
            else:
                self.run_job(lambda url=url: self.service.image(url),
                             lambda path, tile=tile, url=url, token=token: self._thumb_loaded(token, tile, url, path),
                             lambda _error, tile=tile, token=token: self._thumb_error(token, tile))
        self.editor.status.setText("%d images found. Choose a thumbnail." % len(arts) if arts else
                                   "No artwork found. Try another source or import a local image.")

    def _art_error(self, token, error):
        if token == self.art_token:
            self.gallery.clear_tiles(error)
            self.editor.status.setText(error)
            self.statusBar().showMessage(error)

    def _thumb_loaded(self, token, tile, url, path):
        self.thumbnail_cache[url] = str(path)
        if token == self.art_token and tile in self.gallery.tiles:
            tile.set_image(path)

    def _thumb_error(self, token, tile):
        if token == self.art_token and tile in self.gallery.tiles:
            tile.image.setText("Image unavailable")

    def select_art(self, art):
        self.local_image = False
        self.gallery.mark_selected(art)
        self.preview_token += 1
        self.image_path = self.preview_path = None
        self.prepared_file = None
        token = self.preview_token
        self.editor.new.set_path(None, "Rendering selected cover…")
        self.editor.set_ready(False, bool(self.game and self.game.verified))
        self.run_job(lambda: self.service.image(art["url"]),
                     lambda path: self._selected_image(token, path),
                     lambda error: self.show_error(error) if token == self.preview_token else None)

    def _selected_image(self, token, path):
        if token != self.preview_token:
            return
        self.image_path = str(path)
        self.render_preview()

    def render_preview(self):
        if not self.game or not self.image_path:
            return
        self.preview_token += 1
        self.preview_path = None
        token = self.preview_token
        item = self.current_item()
        self.editor.new.set_path(None, "Rendering selected cover…")
        self.editor.set_ready(False, item.game.verified)
        self.run_job(lambda: self.service.preview(item),
                     lambda path: self._preview_loaded(token, path),
                     lambda error: self.show_error(error) if token == self.preview_token else None)

    def _preview_loaded(self, token, path):
        if token != self.preview_token:
            return
        self.preview_path = str(path)
        self.editor.new.set_path(path)
        self.editor.status.setText("Final frame ready. Apply, add to batch, or export PNG.")
        self.editor.set_ready(True, self.game.verified)

    def platform_changed(self, _platform):
        if self.game:
            self.service.remember_platform(self.game, _platform)
        if self.prepared_file and not self.image_path:
            self.prepared_file = self.preview_path = None
            self.editor.new.set_path(None, "Choose artwork for the new frame")
            self.editor.set_ready(False, bool(self.game and self.game.verified))
            return
        self.render_preview()

    def platinum_changed(self, enabled):
        if self.game:
            self.service.remember_platinum(self.game, enabled)
        self.render_preview()

    def source_changed(self, _source):
        self.local_image = False
        self.preview_token += 1
        self.prepared_file = None
        self.image_path = self.preview_path = None
        self.editor.new.set_path(None, "Select artwork")
        self.editor.set_ready(False, bool(self.game and self.game.verified))
        self.load_art()

    def import_image(self):
        path, _filter = QFileDialog.getOpenFileName(self, "Import cover image", "",
                                                    "Images (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        try:
            cw.validate_local_image(path)
        except sc.SteamcaseError as exc:
            self.show_error(str(exc))
            return
        if not self.game:
            self.game = Game(Path(path).stem, "local")
            self.editor.set_game(self.game)
        elif self.shortcut_context and not self.game.verified:
            self.game = self.shortcut_context
            self.editor.set_game(self.game)
        self.local_image = True
        self.art_token += 1
        self.editor.set_source("Local file")
        self.gallery.clear_tiles("Local image selected.")
        self.prepared_file = None
        self.image_path = path
        self.render_preview()

    def current_item(self):
        return CoverItem(self.game, self.editor.platform.currentData(), image=self.image_path,
                         file=self.prepared_file, source="Local file" if self.local_image else self.editor.source.currentText(),
                         preview=self.preview_path, platinum=self.editor.platinum.isChecked())

    def add_to_batch(self):
        if not self.preview_path or not self.game:
            return
        try:
            self.service.add(self.current_item())
        except sc.SteamcaseError as exc:
            self.show_error(str(exc))
            return
        self.refresh_batch()
        self.editor.status.setText("Added to batch. Edit another game or open Batch to review.")
        self.statusBar().showMessage("%d covers queued" % len(self.service.queue))

    def _confirm_apply(self, count):
        text = "%d cover%s will be applied with one backup.\n\n" % (count, "" if count == 1 else "s")
        text += "If Steam is open, it will close once. Running games stop and downloads pause. "
        text += "It can be started once after Apply, as chosen in Settings. Save your game first."
        return QMessageBox.question(self, "Apply to Steam", text,
                                    QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Ok

    def apply_selected(self):
        if self.busy or not self.preview_path or not self.game or not self.game.verified:
            return
        if self._confirm_apply(1):
            self._run_apply([self.current_item()])

    def apply_all(self):
        if self.busy:
            return
        items = [item for item in self.service.queue.values() if item.game.verified]
        if not items:
            self.show_error("The batch has no verified Steam games or shortcuts.")
            return
        if self._confirm_apply(len(items)):
            self._run_apply(items)

    def _run_apply(self, items):
        self.busy = True
        self.editor.status.setText("Preparing covers before Steam changes…")
        self.editor.apply.setEnabled(False)
        self.apply_all_button.setEnabled(False)
        self.run_job(lambda: self.service.apply_items(items, lambda key, status: self.bridge.progress.emit(key, status)),
                     lambda result: self._apply_done(items, result), self._apply_failed)

    def _apply_done(self, items, result):
        self.busy = False
        self.editor.set_ready(bool(self.preview_path), bool(self.game and self.game.verified))
        self.apply_all_button.setEnabled(True)
        for item in items:
            if item.key in self.service.queue:
                self.service.queue[item.key] = replace(self.service.queue[item.key],
                                                       status="Applied" if item.game.steam_id in result["changed_ids"]
                                                       else "Already current")
        self.refresh_batch()
        message = "%d applied, %d already current. %s" % (
            result["applied"], result["unchanged"],
            "Backup saved." if result["backup"] else "No changes were needed.")
        self.editor.status.setText(message)
        self.statusBar().showMessage(message)
        if self.game and self.game.steam_id:
            game, token = self.game, self.selection_token
            self.run_job(lambda: self.service.current_cover(game),
                         lambda path: self.editor.current.set_path(path) if token == self.selection_token else None,
                         lambda _error: None)

    def _apply_failed(self, error):
        self.busy = False
        self.editor.set_ready(bool(self.preview_path), bool(self.game and self.game.verified))
        self.apply_all_button.setEnabled(True)
        self.show_error(error)

    def export_selected(self):
        if not self.preview_path:
            return
        item = self.current_item()
        self.run_job(lambda: self.service.export_one(item),
                     lambda path: self.editor.status.setText("PNG exported: %s" % path))

    def refresh_batch(self):
        selected = self.batch_table.currentRow()
        items = list(self.service.queue.values())
        self.batch_table.blockSignals(True)
        self.batch_table.setRowCount(len(items))
        for row, item in enumerate(items):
            title = QTableWidgetItem(item.game.name + (" · Platinum" if item.platinum else "") +
                                     ("\nSteam ID %s" % item.game.steam_id
                                                      if item.game.steam_id else "\nPNG only"))
            path = item.preview or item.file or item.image
            if path:
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    title.setIcon(QIcon(pixmap.scaled(40, 60, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation)))
            title.setData(Qt.ItemDataRole.UserRole, item.key)
            self.batch_table.setItem(row, 0, title)
            self.batch_table.setItem(row, 1, QTableWidgetItem(item.platform))
            self.batch_table.setItem(row, 2, QTableWidgetItem(item.status))
            self.batch_table.setRowHeight(row, 68)
        self.batch_table.blockSignals(False)
        if 0 <= selected < len(items):
            self.batch_table.selectRow(selected)
        total = sum(item.game.verified for item in items)
        self.batch_note.setText("%d queued covers · %d ready for Steam · all can be exported as PNG" %
                                (len(items), total))
        self.apply_all_button.setEnabled(bool(total) and not self.busy)

    def _batch_key(self):
        row = self.batch_table.currentRow()
        cell = self.batch_table.item(row, 0) if row >= 0 else None
        return cell.data(Qt.ItemDataRole.UserRole) if cell else None

    def edit_batch(self):
        key = self._batch_key()
        if not key or self.busy:
            return
        item = self.service.queue[key]
        if item.game.source in ("steam", "shortcut"):
            self.navigate("Library")
        else:
            self.navigate("Search")
        self.shortcut_context = item.game if item.game.verified and item.game.source != "steam" else None
        self.select_game(item.game)
        self.editor.set_platform(item.platform)
        self.editor.set_platinum(item.platinum)
        self.editor.set_source(item.source)
        self.local_image = item.source == "Local file"
        if self.local_image:
            self.art_token += 1
            self.gallery.clear_tiles("Local image selected.")
        else:
            self.load_art()
        if item.image:
            self.image_path = item.image
            self.render_preview()
        elif item.file:
            self.prepared_file = item.file
            if item.platinum:
                self.render_preview()
            else:
                self.preview_path = item.file
                self.editor.new.set_path(item.file)
                self.editor.set_ready(True, item.game.verified)

    def remove_batch(self):
        key = self._batch_key()
        if key and not self.busy:
            self.service.remove(key)
            self.refresh_batch()

    def export_all(self):
        if not self.service.queue:
            self.show_error("Add at least one cover to the batch first.")
            return
        self.run_job(self.service.export_all,
                     lambda result: self.statusBar().showMessage("%d PNGs exported; %d failed" %
                                                                  (len(result[0]), len(result[1]))))

    def generate_all(self):
        if self.busy:
            return
        self.busy = True
        self.cancel_auto = False
        self.cancel_generation.show()
        self.library_progress.setRange(0, 0)
        self.library_progress.show()

        def progress(done, total, _appid, name, _status):
            self.bridge.progress.emit("", "%d/%d · %s" % (done, total, name))

        skip = self.skip_blurry.isChecked()
        self.run_job(lambda: self.service.automatic(progress=progress,
                                                    cancelled=lambda: self.cancel_auto,
                                                    skip_auto_art=skip), self._automatic_done,
                     lambda error: (self._automatic_end(), self.show_error(error)))

    def _automatic_end(self):
        self.busy = False
        self.cancel_generation.hide()
        self.library_progress.hide()

    def _automatic_done(self, result):
        self.service.add_automatic(result)
        self._automatic_end()
        self.refresh_batch()
        message = "%d covers ready; %d missing, %d failed." % (
            result["ok"], len(result["missing"]), len(result["failed"]))
        self.statusBar().showMessage(message)

    def browse_export_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Export folder", self.export_folder.text())
        if path:
            self.export_folder.setText(path)
            self.save_preferences()

    def save_preferences(self, *_args):
        settings = self.service.settings
        settings.export_dir = self.export_folder.text().strip() or str(sc.default_covers_dir())
        settings.default_source = self.default_source.currentText()
        settings.restart_steam = self.restart_checkbox.isChecked()
        settings.account = self.account_combo.currentData()
        settings.save()

    def account_changed(self, *_args):
        self.save_preferences()
        self.refresh_library()
        if self.game and self.game.steam_id:
            game, token = self.game, self.selection_token
            self.editor.current.set_path(None, "Loading current cover…")
            self.run_job(lambda: self.service.current_cover(game),
                         lambda path: self.editor.current.set_path(path) if token == self.selection_token else None,
                         lambda _error: self.editor.current.set_path(None, "Current cover unavailable")
                         if token == self.selection_token else None)
        self.refresh_backups()

    def save_key(self):
        key = self.api_key.text().strip()
        if not key:
            self.show_error("Enter a SteamGridDB key first.")
            return

        def work():
            cw.ArtworkClient(key).verify_key()
            cw.save_api_key(key)
            return True

        self.run_job(work, lambda _value: (self.api_key.clear(),
                                          self.sgdb_status.setText("SteamGridDB · ready"),
                                          self.statusBar().showMessage("API key checked and stored securely")))

    def verify_key(self):
        self.run_job(lambda: cw.ArtworkClient(cw.load_api_key()).verify_key(),
                     lambda _value: (self.sgdb_status.setText("SteamGridDB · ready"),
                                     self.statusBar().showMessage("Stored API key is valid")))

    def delete_key(self):
        self.run_job(lambda: cw.save_api_key(""),
                     lambda _value: (self.api_key.clear(),
                                     self.sgdb_status.setText("SteamGridDB · key needed"),
                                     self.statusBar().showMessage("API key deleted")))

    def refresh_accounts(self):
        self.run_job(lambda: sc.list_accounts(self.service.steam()), self._accounts_loaded,
                     lambda _error: None)

    def _accounts_loaded(self, accounts):
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        self.account_combo.addItem("Most recent account", None)
        for account, label in accounts:
            self.account_combo.addItem("%s · %s" % (label, account), account)
        index = self.account_combo.findData(self.service.settings.account)
        self.account_combo.setCurrentIndex(max(0, index))
        self.account_combo.blockSignals(False)
        if index < 0 and self.service.settings.account is not None:
            self.service.settings.account = None
            self.service.settings.save()
            self.refresh_library()

    def refresh_backups(self):
        self.run_job(lambda: sc.list_backups(self.service.steam(), self.service.account()),
                     lambda backups: self.backup_label.setText("%d backups available for this account." % len(backups)),
                     lambda error: self.backup_label.setText(error))

    def _update_backup_account(self):
        choice = self.account_combo.currentText() or "Most recent account"
        if self.service.account() and self.account_combo.currentData() != self.service.account():
            choice = "folder %s" % self.service.account()
        self.backup_account.setText("Steam account: %s · change it in Settings" % choice)
        if self.backup_preview and self.backup_preview.get("selected_account") != self.service.account():
            self.backup_preview = None
            self.backup_table.setRowCount(0)
            self.backup_image.set_path(None, "Select a backup entry")
            self.backup_summary.setText("Steam account changed. Preview the backup again before importing.")
            self.backup_import_button.setEnabled(False)

    def _backup_begin(self, message):
        self.busy = True
        self.backup_export_button.setEnabled(False)
        self.backup_import_button.setEnabled(False)
        self.backup_progress.setRange(0, 0)
        self.backup_progress.show()
        self.backup_progress_label.setText(message)
        self.backup_result.setText("")

    def _backup_end(self):
        self.busy = False
        self.backup_export_button.setEnabled(True)
        plan = self.backup_preview
        self.backup_import_button.setEnabled(bool(plan and plan["can_import"] and
                                               (plan["new"] or plan["overwrite"] or plan["removals"])))
        self.backup_progress.hide()

    def _backup_failed(self, error):
        self._backup_end()
        self.backup_progress_label.setText("Operation failed")
        self.backup_result.setText(error)
        self.show_error(error)

    def export_current_artwork(self):
        if self.busy:
            return
        parent = QFileDialog.getExistingDirectory(self, "Choose a folder for the artwork backup",
                                                   str(Path(self.service.settings.export_dir).parent))
        if not parent:
            return
        base = "CaseCovers-artwork-%s" % time.strftime("%Y%m%d-%H%M%S")
        destination = Path(parent) / base
        suffix = 2
        while destination.exists():
            destination = Path(parent) / ("%s-%d" % (base, suffix))
            suffix += 1
        account = self.service.account()
        self._backup_begin("Reading locally stored artwork…")
        self.run_job(lambda: self.service.export_artwork_backup(
            str(destination), account,
            lambda done, total, phase: self.bridge.backup_progress.emit(done, total, phase)),
            self._backup_exported, self._backup_failed)

    def _backup_exported(self, result):
        self._backup_end()
        skipped = result["skipped"]
        message = "%d local covers exported to %s." % (result["exported"], result["path"])
        if skipped:
            message += "\n%d files skipped: %s" % (
                len(skipped), "; ".join("%s: %s" % (item["filename"], item["reason"])
                                          for item in skipped[:5]))
        self.backup_result.setText(message)
        self.backup_progress_label.setText("Export complete")
        self.statusBar().showMessage("%d local covers exported" % result["exported"])

    def choose_artwork_backup(self):
        if self.busy:
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose a Case Covers artwork backup",
                                                  str(Path(self.service.settings.export_dir).parent))
        if folder:
            self._preview_artwork_backup(folder, self.service.account())

    def _preview_artwork_backup(self, folder, account):
        self.backup_preview = None
        self.backup_import_button.setEnabled(False)
        self.backup_table.setRowCount(0)
        self.backup_image.set_path(None, "Select a backup entry")
        self.backup_path_label.setText(folder)
        self.backup_summary.setText("Checking manifest, files and current artwork…")
        self.run_job(lambda: self.service.preview_artwork_backup(folder, account),
                     lambda plan: self._backup_preview_loaded(plan, account),
                     lambda error: self.backup_summary.setText(error))

    def _backup_preview_loaded(self, plan, account):
        if self.service.account() != account:
            self.backup_summary.setText("Steam account changed. Preview the backup again.")
            return
        plan["selected_account"] = account
        self.backup_preview = plan
        self.backup_table.setRowCount(len(plan["rows"]) + len(plan["removal_rows"]))
        for index, row in enumerate(plan["rows"]):
            name = QTableWidgetItem("%s\nArtwork ID %s" % (row["filename"], row["id"]))
            self.backup_table.setItem(index, 0, name)
            self.backup_table.setItem(index, 1, QTableWidgetItem("%.1f KB" % (row["size"] / 1024)))
            self.backup_table.setItem(index, 2, QTableWidgetItem(row["status"]))
            self.backup_table.setRowHeight(index, 44)
        for offset, row in enumerate(plan["removal_rows"]):
            index = len(plan["rows"]) + offset
            self.backup_table.setItem(index, 0, QTableWidgetItem(
                "%s\nArtwork ID %s" % (row["filename"], row["id"])))
            self.backup_table.setItem(index, 1, QTableWidgetItem("—"))
            self.backup_table.setItem(index, 2, QTableWidgetItem("Remove conflict"))
            self.backup_table.setRowHeight(index, 44)
        parts = ["%d file%s" % (len(plan["rows"]), "" if len(plan["rows"]) == 1 else "s")]
        for key, label in (("new", "new"), ("overwrite", "overwrite"), ("identical", "identical")):
            if plan[key]:
                parts.append("%d %s" % (plan[key], label))
        if plan["removals"]:
            parts.append("%d format conflict%s to remove (backed up)" % (
                len(plan["removals"]), "" if len(plan["removals"]) == 1 else "s"))
        summary = " · ".join(parts)
        if plan["source_account"] != plan["target_account"]:
            summary += " · Source account %s → selected account %s" % (
                plan["source_account"], plan["target_account"])
        if plan["issues"]:
            summary += " · IMPORT BLOCKED: %s" % "; ".join(plan["issues"][:3])
        self.backup_summary.setText(summary)
        self.backup_import_button.setEnabled(bool(plan["can_import"] and not self.busy and
                                                (plan["new"] or plan["overwrite"] or plan["removals"])))
        if plan["rows"]:
            self.backup_table.selectRow(0)

    def _backup_row_selected(self, row, _column, _previous_row, _previous_column):
        plan = self.backup_preview
        if not plan or not 0 <= row < len(plan["rows"]) + len(plan["removal_rows"]):
            self.backup_image.set_path(None, "Select a backup entry")
            return
        path = (plan["rows"][row]["path"] if row < len(plan["rows"])
                else plan["removal_rows"][row - len(plan["rows"])]["path"])
        if not path:
            self.backup_image.set_path(None, "Image unavailable")
            return
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        dimensions = reader.size()
        if dimensions.isValid():
            scale = min(240 / dimensions.width(), 360 / dimensions.height(), 1)
            reader.setScaledSize(QSize(max(1, int(dimensions.width() * scale)),
                                       max(1, int(dimensions.height() * scale))))
        image = reader.read()
        if image.isNull():
            self.backup_image.set_path(None, "Image unavailable")
        else:
            self.backup_image.original = QPixmap.fromImage(image)
            self.backup_image.setText("")
            self.backup_image._fit()

    def import_selected_backup(self):
        plan = self.backup_preview
        if self.busy or not plan or not plan["can_import"]:
            return
        if self.service.account() != plan["selected_account"]:
            self._update_backup_account()
            return
        changes = plan["new"] + plan["overwrite"] + len(plan["removals"])
        if not changes:
            self.backup_result.setText("The selected artwork is already current. Nothing needs to be imported.")
            return
        warning = ("Import %d artwork files into Steam account %s?\n\n"
                   "%d new, %d overwritten, %d conflicting formats removed. "
                   "The original files and IDs will be preserved. "
                   "Current artwork affected by this import will be backed up automatically.\n\n"
                   "If Steam is open, it will close once. Save any running game first." %
                   (len(plan["rows"]), plan["target_account"], plan["new"],
                    plan["overwrite"], len(plan["removals"])))
        if plan["source_account"] != plan["target_account"]:
            warning += "\n\nThis backup came from a different Steam account (%s)." % plan["source_account"]
        if QMessageBox.question(self, "Import artwork backup", warning,
                                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Ok:
            return
        folder, account, token = plan["path"], plan["selected_account"], plan["token"]
        self._backup_begin("Preparing artwork import…")
        self.run_job(lambda: self.service.import_artwork_backup(
            folder, token, account,
            lambda done, total, phase: self.bridge.backup_progress.emit(done, total, phase)),
            lambda result: self._backup_imported(result, folder, account), self._backup_failed)

    def _backup_imported(self, result, folder, account):
        self._backup_end()
        message = "%d files imported, %d conflicting files removed, %d already current." % (
            result["imported"], result["removed"], result["unchanged"])
        if result["backup"]:
            message += " Safety backup: %s" % result["backup"]
        self.backup_result.setText(message)
        self.backup_progress_label.setText("Import complete")
        self.statusBar().showMessage(message)
        self.refresh_backups()
        self._preview_artwork_backup(folder, account)
        if self.game and self.game.steam_id:
            game, token = self.game, self.selection_token
            self.run_job(lambda: self.service.current_cover(game),
                         lambda path: self.editor.current.set_path(path) if token == self.selection_token else None,
                         lambda _error: None)

    def restore(self):
        if self.busy:
            return
        if not self._confirm_recovery("Restore previous artwork", "The latest backup will replace current custom covers."):
            return
        self.busy = True
        self.run_job(self.service.restore, lambda count: self._recovery_done("Restored %d files." % count),
                     self._recovery_failed)

    def reset_default(self):
        if self.busy:
            return
        everything = self.reset_everything.isChecked()
        scope = ("All custom portraits will be removed with a backup." if everything else
                 "Case Covers artwork will be removed with a backup. Other custom art is kept.")
        if not self._confirm_recovery("Reset to Steam default", scope):
            return
        self.busy = True
        self.run_job(lambda: self.service.reset_default(everything),
                     lambda result: self._recovery_done("Removed %d covers. Backup saved." % result["removed"]),
                     self._recovery_failed)

    def _confirm_recovery(self, title, action):
        return QMessageBox.question(self, title, action + "\n\nIf Steam is open, it will close once. Save your game first.",
                                    QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Ok

    def _recovery_done(self, message):
        self.busy = False
        self.statusBar().showMessage(message)
        self.editor.status.setText(message)
        self.refresh_backups()
        if self.game and self.game.steam_id:
            game, token = self.game, self.selection_token
            self.run_job(lambda: self.service.current_cover(game),
                         lambda path: self.editor.current.set_path(path) if token == self.selection_token else None,
                         lambda _error: None)

    def _recovery_failed(self, error):
        self.busy = False
        self.show_error(error)


def selftest():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    window = MainWindow(auto_refresh=False)
    assert window.pages.count() == 5
    assert window.editor.platform.count() == 29
    assert window.editor.apply.text() == "Apply to Steam"
    window.close()
    print("Qt selftest ok")


def main():
    if "--selftest" in sys.argv:
        selftest()
        return 0
    if any(flag in sys.argv for flag in ("--diagnose-batch", "--diagnose-batch-large",
                                        "--diagnose-batch-race", "--diagnose-batch-library",
                                        "--diagnose-batch-grid")):
        from batch_diagnostics import run
        return run(large="--diagnose-batch-large" in sys.argv,
                   race="--diagnose-batch-race" in sys.argv,
                   realistic="--diagnose-batch-library" in sys.argv,
                   grid="--diagnose-batch-grid" in sys.argv)
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    result = app.exec()
    logging.getLogger("casecovers").info("Qt event loop finished: exit_code=%d", result)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
