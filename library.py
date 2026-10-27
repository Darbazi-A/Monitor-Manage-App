"""
The media library, and building a show from an event folder.

Part of Stage Display Controller; main.py builds the dashboard from these.
"""

from __future__ import annotations

from i18n import tr  # noqa: E402 - the interface's language

# noqa: F401 - one import block for every module of the app
import argparse
import ctypes
from contextlib import contextmanager
import json
import os
import sys
import threading
import time

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional

try:  # Windows only; the rest of the app runs without it.
    import winreg
except ImportError:  # pragma: no cover - non-Windows
    winreg = None

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QMimeData,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QVariantAnimation,
    QRect,
    QRectF,
    QSettings,
    QSize,
    QSizeF,
    Qt,
    QTime,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QInputDevice,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QScreen,
    QShortcut,
    QTransform,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFontComboBox,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QScroller,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from config import *  # noqa: F401,F403
from theme import *  # noqa: F401,F403
from widgets import ElidedLabel  # noqa: E402
from media import *  # noqa: F401,F403
from outputs import *  # noqa: F401,F403
from sound import *  # noqa: F401,F403
from cards import *  # noqa: F401,F403

class FileGrid(QListWidget):
    """The Library's files: dragged out, they carry the files themselves - onto a screen, a card, a step."""

    def mimeTypes(self):  # noqa: N802
        return ["text/uri-list"]

    def mimeData(self, items):  # noqa: N802
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(item.data(Qt.UserRole)) for item in items])
        return data


FAVOURITES = "*favourites*"


class MediaLibrary(QWidget):
    """
    Browse the folders the event material lives in, without leaving the app.

    Folder navigation is done by hand rather than with QFileSystemModel: the
    list only ever shows folders and playable media, counts what is inside, and
    cannot wander into system directories mid-show.
    """

    showRequested = Signal(str, str)      # role, path
    queueRequested = Signal(str, list)    # role, paths
    cueRequested = Signal(int, str)       # slot, path
    buildRequested = Signal()
    favouritesChanged = Signal()

    GRID = QSize(158, 132)
    THUMB = QSize(138, 78)
    MAX_ITEMS = 400

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._folder = ""
        self._pinned: List[str] = []
        self._favourites: List[str] = []
        self._show_favourites = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 10, 0, 0)
        root.setSpacing(10)

        # --- toolbar ------------------------------------------------------- #
        card = QFrame()
        card.setObjectName("card")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        glyph = QLabel()
        glyph.setPixmap(Icons.get("folder", CLR_ACCENT, 16).pixmap(16, 16))
        bar.addWidget(glyph)
        title = QLabel(tr('MEDIA LIBRARY'))
        title.setObjectName("sectionTitle")
        bar.addWidget(title)

        self.places = QComboBox()
        self.places.setMinimumWidth(240)
        self.places.setToolTip(tr('Pinned folders'))
        self.places.activated.connect(self._on_place_chosen)
        bar.addWidget(self.places)

        pin = QPushButton(tr('  Pin this folder'))
        pin.setIcon(Icons.get("plus", CLR_TEXT, 15))
        pin.setToolTip(tr('Keep this folder in the list above'))
        pin.clicked.connect(self._pin_current)
        bar.addWidget(pin)

        unpin = QPushButton(tr('  Unpin'))
        unpin.setIcon(Icons.get("minus", CLR_TEXT, 15))
        unpin.clicked.connect(self._unpin_current)
        bar.addWidget(unpin)

        build = QPushButton(tr('  Build a show from a folder…'))
        build.setIcon(Icons.get("folder", CLR_TEXT, 15))
        build.setToolTip(tr('Scan an event folder and sort everything onto the right screens'))
        build.clicked.connect(self.buildRequested.emit)
        bar.addWidget(build)

        browse = QPushButton(tr('  Open folder…'))
        browse.setIcon(Icons.get("open", CLR_TEXT, 15))
        browse.clicked.connect(self._browse_folder)
        bar.addWidget(browse)

        bar.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr('filter by name…'))
        self.search.setMaximumWidth(220)
        self.search.textChanged.connect(lambda _t: self._fill_files())
        bar.addWidget(self.search)

        refresh = icon_button("refresh", tr('Re-read this folder'), CLR_MUTED, 16)
        refresh.setObjectName("ghost")
        refresh.clicked.connect(lambda: self.set_folder(self._folder))
        bar.addWidget(refresh)
        outer.addLayout(bar)

        self.path_label = QLabel()
        self.path_label.setObjectName("cardHint")
        outer.addWidget(self.path_label)

        # --- folders + files ----------------------------------------------- #
        split = QHBoxLayout()
        split.setSpacing(10)

        self.folders = QListWidget()
        self.folders.setMaximumWidth(250)
        self.folders.setMinimumWidth(190)
        self.folders.setIconSize(QSize(16, 16))
        self.folders.itemActivated.connect(self._on_folder_activated)
        self.folders.itemClicked.connect(self._on_folder_activated)
        split.addWidget(self.folders)

        self.files = FileGrid()
        self.files.setViewMode(QListView.ViewMode.IconMode)
        self.files.setResizeMode(QListView.ResizeMode.Adjust)
        self.files.setMovement(QListView.Movement.Static)
        self.files.setIconSize(self.THUMB)
        self.files.setGridSize(self.GRID)
        self.files.setSpacing(4)
        # One elided line per item: wrapped names ran to three lines and
        # shoved the thumbnails around into a ragged grid.
        self.files.setWordWrap(False)
        self.files.setTextElideMode(Qt.ElideMiddle)
        self.files.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.files.setUniformItemSizes(True)
        self.files.itemSelectionChanged.connect(self._sync_actions)
        self.files.itemDoubleClicked.connect(self._on_double_click)
        self.files.setDragEnabled(True)
        self.files.setDragDropMode(QAbstractItemView.DragOnly)
        self.files.setDefaultDropAction(Qt.CopyAction)
        split.addWidget(self.files, 1)
        outer.addLayout(split, 1)

        # --- actions ------------------------------------------------------- #
        actions = QHBoxLayout()
        actions.setSpacing(7)
        self.selection_label = ElidedLabel(tr('nothing selected'))
        self.selection_label.setObjectName("cardHint")
        self.selection_label.setMinimumWidth(150)
        actions.addWidget(self.selection_label)
        self.fav_button = QPushButton(tr('  ☆ Favourite'))
        self.fav_button.setToolTip(tr('Keep the selected files under ★ Favourites, whichever folder they are in'))
        self.fav_button.clicked.connect(self._toggle_favourite)
        actions.addWidget(self.fav_button)

        actions.addSpacing(10)
        show_caption = QLabel(tr('Show now on'))
        show_caption.setObjectName("cardHint")
        actions.addWidget(show_caption)
        self.show_buttons: Dict[str, QPushButton] = {}
        for role in STAGE_ROLES:
            button = QPushButton(ROLE_LABELS[role])
            button.clicked.connect(lambda _c=False, r=role: self._send(r))
            actions.addWidget(button)
            self.show_buttons[role] = button

        actions.addSpacing(14)
        queue_caption = QLabel(tr('Add to playlist'))
        queue_caption.setObjectName("cardHint")
        actions.addWidget(queue_caption)
        self.queue_buttons: Dict[str, QPushButton] = {}
        for role in STAGE_ROLES:
            button = QPushButton(ROLE_LABELS[role])
            button.clicked.connect(lambda _c=False, r=role: self._queue(r))
            actions.addWidget(button)
            self.queue_buttons[role] = button

        actions.addSpacing(14)
        cue_caption = QLabel(tr('Sound cue'))
        cue_caption.setObjectName("cardHint")
        actions.addWidget(cue_caption)
        self.cue_slot = QComboBox()
        for slot in range(SOUND_SLOTS):
            self.cue_slot.addItem(f"F{slot + 1}", slot)
        actions.addWidget(self.cue_slot)
        self.cue_button = QPushButton(tr('Assign'))
        self.cue_button.clicked.connect(self._assign_cue)
        actions.addWidget(self.cue_button)

        actions.addStretch(1)
        outer.addLayout(actions)

        root.addWidget(card, 1)
        thumbnailer().ready.connect(self._on_poster_ready)
        self._sync_actions()

    # -- folders ------------------------------------------------------------ #

    def default_places(self) -> List[str]:
        from PySide6.QtCore import QStandardPaths as SP

        wanted = ("DesktopLocation", "MoviesLocation", "MusicLocation", "PicturesLocation")
        places = []
        for name in wanted:
            location = getattr(SP.StandardLocation, name, None)
            if location is None:
                continue
            path = SP.writableLocation(location)
            if path and os.path.isdir(path):
                places.append(os.path.normpath(path))
        return places

    def set_pinned(self, folders: List[str]) -> None:
        self._pinned = [f for f in folders if os.path.isdir(f)] or self.default_places()
        self._rebuild_places()

    def pinned(self) -> List[str]:
        return list(self._pinned)

    def _rebuild_places(self) -> None:
        self.places.blockSignals(True)
        self.places.clear()
        self.places.addItem(tr('★  Favourites'), FAVOURITES)
        # An unpinned folder still gets an entry, otherwise the picker goes blank
        # and it looks as though nothing is open.
        if self._folder and self._folder not in self._pinned and not self._show_favourites:
            self.places.addItem(
                (os.path.basename(self._folder) or self._folder) + tr('   (not pinned)'), self._folder)
        for folder in self._pinned:
            self.places.addItem(os.path.basename(folder) or folder, folder)
        index = self.places.findData(FAVOURITES if self._show_favourites else self._folder)
        self.places.setCurrentIndex(index if index >= 0 else 0)
        self.places.blockSignals(False)

    @Slot(int)
    def _on_place_chosen(self, index: int) -> None:
        folder = self.places.itemData(index)
        if folder == FAVOURITES:
            self.show_favourites()
        elif folder:
            self.set_folder(folder)

    def _pin_current(self) -> None:
        if self._folder and self._folder not in self._pinned:
            self._pinned.append(self._folder)
            self._rebuild_places()

    def _unpin_current(self) -> None:
        if self._folder in self._pinned:
            self._pinned.remove(self._folder)
            self._rebuild_places()

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr('Open a media folder'), self._folder or "")
        if folder:
            self.set_folder(os.path.normpath(folder))

    def set_folder(self, folder: str, defer_files: bool = False) -> None:
        """
        Show `folder`. With `defer_files`, the thumbnails wait until the
        Library is first looked at: reading every image and pulling a frame
        out of every video at start-up cost a second and ~130 MB for a tab
        that may never be opened.
        """
        if not folder or not os.path.isdir(folder):
            return
        self._show_favourites = False
        self._folder = os.path.normpath(folder)
        self.path_label.setText(self._folder)
        self._fill_folders()
        if defer_files and not self.isVisible():
            self._files_stale = True
        else:
            self._files_stale = False
            self._fill_files()
        self._rebuild_places()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if getattr(self, "_files_stale", False):
            self._files_stale = False
            self._fill_files()

    def current_folder(self) -> str:
        return self._folder

    def _fill_folders(self) -> None:
        self.folders.clear()
        parent = os.path.dirname(self._folder)
        if parent and parent != self._folder:
            item = QListWidgetItem(tr('..  up one level'))
            item.setData(Qt.UserRole, parent)
            item.setIcon(Icons.get("folder", CLR_MUTED, 16))
            self.folders.addItem(item)
        try:
            entries = sorted(
                (e for e in os.scandir(self._folder) if e.is_dir() and not e.name.startswith(".")),
                key=lambda e: e.name.lower())
        except OSError as exc:
            self.path_label.setText(tr('{0}   —   cannot read: {1}').format(self._folder, exc))
            return
        for entry in entries:
            item = QListWidgetItem(entry.name)
            item.setData(Qt.UserRole, entry.path)
            item.setIcon(Icons.get("folder", CLR_MUTED, 16))
            self.folders.addItem(item)

    @Slot(QListWidgetItem)
    def _on_folder_activated(self, item: QListWidgetItem) -> None:
        self.set_folder(item.data(Qt.UserRole))

    # -- files -------------------------------------------------------------- #

    def _fill_files(self) -> None:
        self.files.clear()
        needle = self.search.text().strip().lower()
        if self._show_favourites:
            candidates = [(os.path.basename(p), p) for p in self._favourites if os.path.isfile(p)]
            where = "★  Favourites  -  from every folder"
        else:
            if not self._folder:
                return
            try:
                entries = sorted(
                    (e for e in os.scandir(self._folder) if e.is_file()),
                    key=lambda e: e.name.lower())
            except OSError:
                return
            candidates = [(e.name, e.path) for e in entries]
            where = self._folder
        starred = {os.path.normcase(p) for p in self._favourites}

        shown = 0
        for name, path in candidates:
            extension = os.path.splitext(name)[1].lower()
            if extension not in IMAGE_EXTENSIONS and extension not in VIDEO_EXTENSIONS \
                    and extension not in AUDIO_EXTENSIONS:
                continue
            if needle and needle not in name.lower():
                continue
            if shown >= self.MAX_ITEMS:
                break
            label = ("★ " if os.path.normcase(os.path.normpath(path)) in starred else "") + name
            item = QListWidgetItem(
                self.files.fontMetrics().elidedText(label, Qt.ElideMiddle, self.GRID.width() - 18))
            item.setData(Qt.UserRole, os.path.normpath(path))
            item.setToolTip(path + tr('\n\nDrag it onto a screen in the header, or onto a card, to show it.'))
            item.setIcon(self._thumb_for(path, extension))
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self.files.addItem(item)
            shown += 1

        note = tr("{0}      {1} item(s)").format(where, shown)
        if shown >= self.MAX_ITEMS:
            note += tr("  —  showing the first {0}, use the filter to narrow it").format(self.MAX_ITEMS)
        if self._show_favourites and not candidates:
            note = "★  Favourites  -  none yet: select files in any folder and press ☆ Favourite"
        self.path_label.setText(note)
        self._sync_actions()

    # -- favourites ----------------------------------------------------------- #

    def favourites(self) -> List[str]:
        return list(self._favourites)

    def set_favourites(self, paths: List[str]) -> None:
        self._favourites = [os.path.normpath(p) for p in paths if p]

    def show_favourites(self) -> None:
        self._show_favourites = True
        self.folders.clear()
        self._fill_files()
        self._rebuild_places()

    def _toggle_favourite(self) -> None:
        paths = self.selected_paths()
        if not paths:
            return
        starred = {os.path.normcase(p) for p in self._favourites}
        if all(os.path.normcase(p) in starred for p in paths):
            wanted = {os.path.normcase(p) for p in paths}
            self._favourites = [p for p in self._favourites if os.path.normcase(p) not in wanted]
        else:
            self._favourites += [p for p in paths if os.path.normcase(p) not in starred]
        self.favouritesChanged.emit()
        selected = set(paths)
        self._fill_files()
        for row in range(self.files.count()):
            item = self.files.item(row)
            item.setSelected(item.data(Qt.UserRole) in selected)

    def _tile(self, pixmap: QPixmap) -> QIcon:
        """
        Centre a thumbnail on a fixed-size tile.

        Icons of differing heights make Qt place each caption at a different
        height, and the grid ends up ragged. One canvas size fixes that, and a
        2816x128 ceiling-strip clip stops rendering as a 6-pixel sliver.
        """
        canvas = QPixmap(self.THUMB)
        canvas.fill(QColor(CLR_INPUT))
        scaled = pixmap.scaled(self.THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter = QPainter(canvas)
        painter.drawPixmap((self.THUMB.width() - scaled.width()) // 2,
                           (self.THUMB.height() - scaled.height()) // 2, scaled)
        painter.end()
        return QIcon(canvas)

    def _thumb_for(self, path: str, extension: str) -> QIcon:
        if extension in AUDIO_EXTENSIONS:
            return self._tile(Icons.get("volume", CLR_ACCENT, 34).pixmap(34, 34))
        if extension in IMAGE_EXTENSIONS:
            try:
                from PySide6.QtGui import QImageReader

                reader = QImageReader(path)
                reader.setDecideFormatFromContent(True)
                size = reader.size()
                if size.isValid():
                    reader.setScaledSize(size.scaled(self.THUMB, Qt.KeepAspectRatio))
                image = reader.read()
                if not image.isNull():
                    return self._tile(QPixmap.fromImage(image))
            except Exception:
                pass
            return self._tile(Icons.get("image", CLR_MUTED, 34).pixmap(34, 34))

        poster = thumbnailer().cached(path)
        if poster is not None:
            return self._tile(poster)
        thumbnailer().request(path)
        return self._tile(Icons.get("video", CLR_MUTED, 34).pixmap(34, 34))

    def _on_poster_ready(self, path: str, pixmap: QPixmap) -> None:
        for row in range(self.files.count()):
            item = self.files.item(row)
            if item.data(Qt.UserRole) == path:
                item.setIcon(self._tile(pixmap))

    # -- selection and actions ---------------------------------------------- #

    def selected_paths(self) -> List[str]:
        return [item.data(Qt.UserRole) for item in self.files.selectedItems()]

    def _sync_actions(self) -> None:
        paths = self.selected_paths()
        audio = [p for p in paths if os.path.splitext(p)[1].lower() in AUDIO_EXTENSIONS]
        visual = [p for p in paths if p not in audio]

        if not paths:
            self.selection_label.setText(tr('nothing selected'))
        elif len(paths) == 1:
            self.selection_label.setText(os.path.basename(paths[0]))
        else:
            self.selection_label.setText(tr('{0} items selected').format(len(paths)))

        starred = {os.path.normcase(p) for p in self._favourites}
        self.fav_button.setEnabled(bool(paths))
        self.fav_button.setText(tr('  ★ Unfavourite') if paths and all(os.path.normcase(p) in starred for p in paths)
                                else tr('  ☆ Favourite'))
        for button in self.show_buttons.values():
            button.setEnabled(len(visual) == 1 and not audio)
        for button in self.queue_buttons.values():
            button.setEnabled(bool(visual) and not audio)
        self.cue_button.setEnabled(len(audio) == 1 and not visual)
        self.cue_slot.setEnabled(len(audio) == 1 and not visual)

    def _send(self, role: str) -> None:
        paths = self.selected_paths()
        if len(paths) == 1:
            self.showRequested.emit(role, paths[0])

    def _queue(self, role: str) -> None:
        paths = self.selected_paths()
        if paths:
            self.queueRequested.emit(role, paths)

    def _assign_cue(self) -> None:
        paths = self.selected_paths()
        if len(paths) == 1:
            self.cueRequested.emit(self.cue_slot.currentData(), paths[0])

    @Slot(QListWidgetItem)
    def _on_double_click(self, item: QListWidgetItem) -> None:
        """Double-click is the quickest route: queue it on the active screen."""
        path = item.data(Qt.UserRole)
        if os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS:
            self.cueRequested.emit(self.cue_slot.currentData(), path)
        else:
            self.queueRequested.emit("", [path])   # "" means the active card


# --------------------------------------------------------------------------- #
# Control panel
# --------------------------------------------------------------------------- #

class EventFolderDialog(QDialog):
    """
    What the app worked out about an event folder, before it acts on it.

    Nothing is applied until the operator has seen the list and can change any
    row - an import that silently guessed wrong would be worse than no import.
    """

    # every screen of the hall, then a sound cue, or nothing
    DEST_LABELS = tuple((dict.__getitem__(ROLE_LABELS, role), role) for role in STAGE_ROLES) + (
        ("Sound cue", "sound"),
        ("Skip", "skip"),
    )

    def __init__(self, folder: str, rows: List[tuple], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr('Build a show from a folder'))
        self.setMinimumSize(760, 560)
        self._rows = rows

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        heading = QLabel(os.path.basename(folder) or folder)
        heading.setObjectName("cardTitle")
        layout.addWidget(heading)

        self.summary = QLabel()
        self.summary.setObjectName("cardHint")
        layout.addWidget(self.summary)

        self.table = QTableWidget(len(rows), 3)
        self.table.setHorizontalHeaderLabels(["File", "Shape", "Goes to"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 400)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(2, 160)
        self.combos: List[QComboBox] = []

        for index, (path, size, role) in enumerate(rows):
            name = QTableWidgetItem(os.path.relpath(path, folder))
            name.setToolTip(path)
            self.table.setItem(index, 0, name)

            if os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS:
                shape = "sound"
            elif size is not None and size.height():
                ratio = size.width() / size.height()
                shape = f"{size.width()}\u00d7{size.height()}   {ratio:.2f}:1"
            else:
                shape = "unknown"
            item = QTableWidgetItem(shape)
            item.setForeground(QColor(CLR_MUTED))
            self.table.setItem(index, 1, item)

            combo = QComboBox()
            for label, value in self.DEST_LABELS:
                combo.addItem(tr(label), value)
            combo.setCurrentIndex(max(0, combo.findData(role)))
            combo.currentIndexChanged.connect(lambda _i: self._update_summary())
            self.table.setCellWidget(index, 2, combo)
            self.combos.append(combo)

        layout.addWidget(self.table, 1)

        self.replace_check = QCheckBox(tr('Clear the current show first'))
        self.replace_check.setChecked(True)
        layout.addWidget(self.replace_check)

        self.go_live_check = QCheckBox(tr('Put the first item of each screen on straight away'))
        layout.addWidget(self.go_live_check)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(tr('Cancel'))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        build = QPushButton(tr('  Build the show'))
        build.setObjectName("primary")
        build.setIcon(Icons.get("play", CLR_INK, 15))
        build.clicked.connect(self.accept)
        buttons.addWidget(build)
        layout.addLayout(buttons)

        self._update_summary()

    def _update_summary(self) -> None:
        counts = {}
        for combo in self.combos:
            counts[combo.currentData()] = counts.get(combo.currentData(), 0) + 1
        parts = []
        for label, value in self.DEST_LABELS:
            if counts.get(value):
                parts.append(f"{counts[value]} \u2192 {tr(label)}")
        self.summary.setText("   \u00b7   ".join(parts) if parts else tr('nothing to import'))

    def assignments(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        for (path, _size, _role), combo in zip(self._rows, self.combos):
            destination = combo.currentData()
            if destination == "skip":
                continue
            result.setdefault(destination, []).append(path)
        return result
