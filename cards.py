"""
One screen's live controls on the Live tab: drop zone, playlist, transport, marquee.

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
from media import *  # noqa: F401,F403
from outputs import *  # noqa: F401,F403
from sound import *  # noqa: F401,F403

# --------------------------------------------------------------------------- #
# Drop zone
# --------------------------------------------------------------------------- #

class DropZone(QFrame):
    """
    Drag & drop target with a thumbnail of whatever is currently on that screen.

    Clicking it opens the file dialog, so the operator never has to hunt for a
    "Browse" button mid-show. Dropping several files at once fills the playlist.
    """

    filesDropped = Signal(list)
    browseRequested = Signal()

    THUMB = QSize(250, 132)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(76)
        self.setMaximumHeight(156)
        self.setProperty("dragActive", "false")
        self.setProperty("loaded", "false")
        self._path = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        self.thumb = QLabel()
        self.thumb.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.thumb, 1)

        self.caption = QLabel()
        self.caption.setObjectName("cardHint")
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setWordWrap(False)
        self.caption.setTextFormat(Qt.PlainText)
        layout.addWidget(self.caption)

        # A real frame arrives a moment after a video is queued.
        thumbnailer().ready.connect(self._on_poster_ready)

        self._show_empty()

    # -- appearance --------------------------------------------------------- #

    def _restyle(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)

    def _show_empty(self) -> None:
        self._path = ""
        self.thumb.setPixmap(Icons.get("plus", CLR_LINE, 28).pixmap(28, 28))
        self.caption.setText(tr('drop media here  ·  or click to browse'))
        self.setProperty("loaded", "false")
        self._restyle()

    def _elide(self, text: str) -> str:
        metrics = self.caption.fontMetrics()
        return metrics.elidedText(text, Qt.ElideMiddle, max(120, self.width() - 26))

    def set_file(self, path: str) -> None:
        self._path = path
        poster = None
        if is_image(path):
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                poster = pixmap
        else:
            poster = thumbnailer().cached(path)
            if poster is None:
                # Placeholder until the real frame is extracted.
                self.thumb.setPixmap(Icons.get("video", CLR_ACCENT, 34).pixmap(34, 34))
                thumbnailer().request(path)

        if poster is not None:
            self.thumb.setPixmap(
                poster.scaled(self.THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        self.caption.setText(self._elide(os.path.basename(path)))
        self.caption.setToolTip(path)
        self.setProperty("loaded", "true")
        self._restyle()

    def _on_poster_ready(self, path: str, pixmap: QPixmap) -> None:
        if path == self._path and not pixmap.isNull():
            self.thumb.setPixmap(
                pixmap.scaled(self.THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._path:
            self.caption.setText(self._elide(os.path.basename(self._path)))

    def clear(self) -> None:
        self.caption.setToolTip("")
        self._show_empty()

    # -- interaction -------------------------------------------------------- #

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.browseRequested.emit()
        event.accept()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if urls_to_paths(event.mimeData()):
            self.setProperty("dragActive", "true")
            self._restyle()
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if urls_to_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.setProperty("dragActive", "false")
        self._restyle()
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        self.setProperty("dragActive", "false")
        self._restyle()
        paths = urls_to_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        self.filesDropped.emit(paths)
        event.acceptProposedAction()


# --------------------------------------------------------------------------- #
# Playlist
# --------------------------------------------------------------------------- #

class Playlist(QListWidget):
    """
    The media prepared in advance for one output.

    Click an entry to put it on that screen immediately - that is the whole
    point during an event, when someone asks for "the next background".
    """

    itemChosen = Signal(str)
    filesAdded = Signal(list)

    ICON = QSize(44, 26)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        # InternalMove so the running order can be arranged before an event;
        # dropEvent still handles files dragged in from Explorer.
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setIconSize(self.ICON)
        self.setUniformItemSizes(True)
        self.setMinimumHeight(56)
        self.setMaximumHeight(150)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setToolTip(tr('Click an entry to put it on the screen · drag to reorder'))
        self.itemClicked.connect(self._on_item_clicked)
        self.model().rowsMoved.connect(lambda *_a: self._renumber())
        thumbnailer().ready.connect(self._on_poster_ready)
        thumbnailer().failed.connect(self._on_poster_failed)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.count():
            return
        # An empty list is where an event gets prepared, so say so.
        painter = QPainter(self.viewport())
        painter.setPen(QColor(CLR_LINE))
        painter.drawText(
            self.viewport().rect(),
            Qt.AlignCenter,
            "drop several files here\nto build the running order",
        )

    # -- content ------------------------------------------------------------ #

    def paths(self) -> List[str]:
        return [self.item(row).data(Qt.UserRole) for row in range(self.count())]

    def add_paths(self, paths: List[str], announce: bool = True) -> List[str]:
        """Append files, skipping ones already queued. Returns what was added."""
        existing = set(self.paths())
        added = []
        for path in paths:
            if not is_supported(path) or path in existing:
                continue
            item = QListWidgetItem(os.path.basename(path))
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            item.setIcon(self._thumb_for(path))
            self.addItem(item)
            existing.add(path)
            added.append(path)
        if added:
            self._renumber()
            if announce:
                self.filesAdded.emit(added)
        return added

    def _thumb_for(self, path: str) -> QIcon:
        if is_image(path):
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                return QIcon(pixmap.scaled(self.ICON, Qt.KeepAspectRatioByExpanding,
                                           Qt.SmoothTransformation))
            return Icons.get("image", CLR_MUTED, 16)

        poster = thumbnailer().cached(path)
        if poster is not None:
            return QIcon(poster.scaled(self.ICON, Qt.KeepAspectRatioByExpanding,
                                       Qt.SmoothTransformation))
        thumbnailer().request(path)
        return Icons.get("video", CLR_MUTED, 16)

    def _on_poster_ready(self, path: str, pixmap: QPixmap) -> None:
        for row in range(self.count()):
            item = self.item(row)
            if item.data(Qt.UserRole) == path:
                item.setIcon(QIcon(pixmap.scaled(self.ICON, Qt.KeepAspectRatioByExpanding,
                                                 Qt.SmoothTransformation)))

    def _on_poster_failed(self, path: str) -> None:
        """Flag a clip no frame could be read from - it will not play either."""
        for row in range(self.count()):
            item = self.item(row)
            if item.data(Qt.UserRole) == path:
                item.setIcon(Icons.get("warning", CLR_DANGER, 16))
                item.setForeground(QColor(CLR_DANGER))
                item.setToolTip(
                    tr('{0}\n\nNo frame could be read from this clip, so it will most likely not play on stage.\nConvert it to H.264 MP4 before the show.').format(path)
                )

    def _renumber(self) -> None:
        """Keep the visible running order in step after adds and reorders."""
        for row in range(self.count()):
            item = self.item(row)
            path = item.data(Qt.UserRole)
            item.setText(f"{row + 1}.  {os.path.basename(path)}")

    def remove_current(self) -> None:
        row = self.currentRow()
        if row >= 0:
            self.takeItem(row)
            self._renumber()

    def clear_all(self) -> None:
        self.clear()

    # -- navigation --------------------------------------------------------- #

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self.itemChosen.emit(item.data(Qt.UserRole))

    def step(self, delta: int) -> None:
        """Move to the next/previous entry and send it, wrapping around."""
        if self.count() == 0:
            return
        row = self.currentRow()
        row = (row + delta) % self.count() if row >= 0 else (0 if delta > 0 else self.count() - 1)
        self.setCurrentRow(row)
        self.itemChosen.emit(self.item(row).data(Qt.UserRole))

    def mark_active(self, path: str) -> None:
        """Highlight whichever entry is currently on the screen."""
        for row in range(self.count()):
            item = self.item(row)
            entry = item.data(Qt.UserRole)
            active = entry == path
            font = item.font()
            font.setBold(active)
            item.setFont(font)
            if thumbnailer().is_suspect(entry):
                item.setForeground(QColor(CLR_DANGER))  # keep the warning visible
            else:
                item.setForeground(QColor(CLR_ACCENT if active else CLR_MUTED))
            if active:
                self.setCurrentRow(row)

    # -- drag & drop -------------------------------------------------------- #

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.source() is self:
            super().dragEnterEvent(event)
        elif urls_to_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.source() is self:
            super().dragMoveEvent(event)
        elif urls_to_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        if event.source() is self:
            super().dropEvent(event)  # reordering within the list
            self._renumber()
            return
        paths = urls_to_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        self.add_paths(paths)
        event.acceptProposedAction()


class OutputCard(QFrame):
    """Live controls for a single output: preview, playlist, transport, volume."""

    loadRequested = Signal(str)
    queueRequested = Signal(list)
    scaleModeChanged = Signal(object)  # ScaleMode
    playRequested = Signal()
    pauseRequested = Signal()
    stopRequested = Signal()
    clearRequested = Signal()
    volumeChanged = Signal(int)
    muteChanged = Signal(bool)
    repeatChanged = Signal(bool)
    seekRequested = Signal(int)
    activated = Signal()

    def __init__(self, title: str, subtitle: str, default_mode: ScaleMode,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setProperty("active", "false")
        self._last_dir = ""
        self._path = ""
        self._duration = 0
        self._scrubbing = False

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(13, 9, 13, 10)
        self.root.setSpacing(6)

        # --- header -------------------------------------------------------- #
        header = QHBoxLayout()
        header.setSpacing(8)
        glyph = QLabel()
        glyph.setPixmap(Icons.get("monitor", CLR_ACCENT, 17).pixmap(17, 17))
        header.addWidget(glyph)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        name = QLabel(tr(title))
        name.setObjectName("cardTitle")
        hint = QLabel(tr(subtitle))
        hint.setObjectName("cardSub")
        title_box.addWidget(name)
        title_box.addWidget(hint)
        header.addLayout(title_box)
        header.addStretch(1)

        self.state_badge = QLabel(tr('CLOSED'))
        self.state_badge.setObjectName("badgeOff")
        header.addWidget(self.state_badge)
        self.root.addLayout(header)

        # --- preview / drop zone ------------------------------------------- #
        self.zone = DropZone()
        self.zone.filesDropped.connect(self._on_files_chosen)
        self.zone.browseRequested.connect(self._on_browse)
        self.root.addWidget(self.zone)

        # --- playback position --------------------------------------------- #
        scrub_row = QHBoxLayout()
        scrub_row.setSpacing(8)
        self.scrub = QSlider(Qt.Horizontal)
        self.scrub.setObjectName("scrub")
        self.scrub.setRange(0, 0)
        self.scrub.setEnabled(False)
        self.scrub.setToolTip(tr('Playback position — drag to seek'))
        self.scrub.sliderPressed.connect(lambda: setattr(self, "_scrubbing", True))
        self.scrub.sliderReleased.connect(self._on_scrub_released)
        scrub_row.addWidget(self.scrub, 1)

        self.timecode = QLabel("–:––")
        self.timecode.setObjectName("timecode")
        self.timecode.setMinimumWidth(78)
        self.timecode.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.timecode.setToolTip(tr('Elapsed / total'))
        scrub_row.addWidget(self.timecode)
        self.root.addLayout(scrub_row)

        # --- scaling + repeat ---------------------------------------------- #
        options = QHBoxLayout()
        options.setSpacing(6)
        self.scale_combo = QComboBox()
        for mode in ScaleMode:
            self.scale_combo.addItem(tr(mode.value), mode)
        self.scale_combo.setCurrentIndex(list(ScaleMode).index(default_mode))
        self.scale_combo.setToolTip(tr('How media is fitted to this screen'))
        self.scale_combo.currentIndexChanged.connect(
            lambda _i: self.scaleModeChanged.emit(self.scale_combo.currentData())
        )
        options.addWidget(self.scale_combo, 1)

        self.repeat_btn = icon_button("repeat", tr('Repeat / loop video'), CLR_TEXT)
        self.repeat_btn.setObjectName("ghost")
        self.repeat_btn.setCheckable(True)
        self.repeat_btn.setChecked(True)  # repeat is ON by default
        self.repeat_btn.toggled.connect(self._on_repeat_toggled)
        options.addWidget(self.repeat_btn)

        self.mute_btn = icon_button("volume", tr('Mute audio'), CLR_TEXT)
        self.mute_btn.setObjectName("ghost")
        self.mute_btn.setCheckable(True)
        self.mute_btn.toggled.connect(self._on_mute_toggled)
        options.addWidget(self.mute_btn)
        self.root.addLayout(options)

        # --- transport: one control, not five boxes -------------------------- #
        segment = QFrame()
        segment.setObjectName("segment")
        transport = QHBoxLayout(segment)
        transport.setContentsMargins(3, 3, 3, 3)
        transport.setSpacing(2)
        for icon_name, tip, signal in (
            ("prev", "Previous item in the playlist", None),
            ("play", "Play", self.playRequested),
            ("pause", "Pause", self.pauseRequested),
            ("stop", "Stop (rewind to first frame)", self.stopRequested),
            ("next", "Next item in the playlist", None),
        ):
            button = icon_button(icon_name, tr(tip), CLR_DIM)
            button.setObjectName("segmentButton")
            button.setMinimumHeight(30)
            if signal is not None:
                button.clicked.connect(signal.emit)
            transport.addWidget(button, 1)
            if icon_name == "prev":
                self.prev_btn = button
            elif icon_name == "next":
                self.next_btn = button
        self.root.addWidget(segment)

        # --- volume + blackout --------------------------------------------- #
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setToolTip(tr('Playback volume'))
        self.volume_slider.valueChanged.connect(self.volumeChanged.emit)
        bottom.addWidget(self.volume_slider, 1)

        black = icon_button("power", tr('Blackout this screen'), CLR_DANGER)
        black.setObjectName("ghost")
        black.clicked.connect(self._on_clear)
        bottom.addWidget(black)
        self.root.addLayout(bottom)

        # --- playlist ------------------------------------------------------ #
        queue_header = QHBoxLayout()
        queue_header.setSpacing(4)
        queue_title = QLabel(tr('Playlist'))
        queue_title.setObjectName("sectionTitle")
        queue_header.addWidget(queue_title)
        queue_header.addStretch(1)

        add_btn = icon_button("plus", tr('Add files to the playlist'), CLR_MUTED, 15)
        add_btn.setObjectName("ghost")
        add_btn.clicked.connect(self._on_add_to_queue)
        queue_header.addWidget(add_btn)

        remove_btn = icon_button("minus", tr('Remove the selected entry'), CLR_MUTED, 15)
        remove_btn.setObjectName("ghost")
        remove_btn.clicked.connect(lambda: self.playlist.remove_current())
        queue_header.addWidget(remove_btn)

        clear_btn = icon_button("trash", tr('Empty the playlist'), CLR_MUTED, 15)
        clear_btn.setObjectName("ghost")
        clear_btn.clicked.connect(self._on_clear_queue)
        queue_header.addWidget(clear_btn)
        self.root.addLayout(queue_header)

        self.playlist = Playlist()
        self.playlist.itemChosen.connect(self.loadRequested.emit)
        self.playlist.filesAdded.connect(lambda paths: self.queueRequested.emit(paths))
        self.root.addWidget(self.playlist)

        self.prev_btn.clicked.connect(lambda: self.playlist.step(-1))
        self.next_btn.clicked.connect(lambda: self.playlist.step(1))

        if type(self) is OutputCard:
            self.root.addStretch(1)

        self.set_output_open(False)

    # -- state -------------------------------------------------------------- #

    def set_output_open(self, is_open: bool) -> None:
        self.state_badge.setText(tr('OPEN') if is_open else tr('CLOSED'))
        self.state_badge.setObjectName("badgeLive" if is_open else "badgeOff")
        self.state_badge.setToolTip(
            tr("This screen's output window is open") if is_open else
            tr('No output window — press OPEN OUTPUTS')
        )
        self.state_badge.style().unpolish(self.state_badge)
        self.state_badge.style().polish(self.state_badge)
        if not is_open:
            self.set_duration(0)

    def set_active(self, active: bool) -> None:
        """Mark the card the keyboard shortcuts act on."""
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.activated.emit()
        super().mousePressEvent(event)

    # -- playback position -------------------------------------------------- #

    def set_duration(self, milliseconds: int) -> None:
        self._duration = max(0, milliseconds)
        self.scrub.setEnabled(self._duration > 0)
        if self._duration == 0:
            # A zero-width range paints as a *full* bar, which reads as "playing";
            # give it a range it can actually sit empty in.
            self.scrub.setRange(0, 1)
            self.scrub.setValue(0)
            self.timecode.setText("–:––")
        else:
            self.scrub.setRange(0, self._duration)
            self._update_timecode(self.scrub.value())

    def set_position(self, milliseconds: int) -> None:
        if self._scrubbing or self._duration <= 0:
            return
        self.scrub.setValue(milliseconds)
        self._update_timecode(milliseconds)

    def _update_timecode(self, position: int) -> None:
        self.timecode.setText(f"{format_time(position)} / {format_time(self._duration)}")

    @Slot()
    def _on_scrub_released(self) -> None:
        self._scrubbing = False
        self.seekRequested.emit(self.scrub.value())
        self._update_timecode(self.scrub.value())

    def current_scale_mode(self) -> ScaleMode:
        return self.scale_combo.currentData()

    def set_scale_mode(self, mode: ScaleMode) -> None:
        self.scale_combo.setCurrentIndex(list(ScaleMode).index(mode))

    def current_path(self) -> str:
        return self._path

    def show_loaded(self, path: str) -> None:
        self._path = path
        self.zone.set_file(path)
        self.playlist.add_paths([path], announce=False)
        self.playlist.mark_active(path)

    def reset_file(self) -> None:
        self._path = ""
        self.zone.clear()
        self.playlist.mark_active("")

    def is_repeating(self) -> bool:
        return self.repeat_btn.isChecked()

    # -- slots -------------------------------------------------------------- #

    @Slot()
    def _on_browse(self) -> None:
        start = self._last_dir or os.path.dirname(self._path)
        paths, _ = QFileDialog.getOpenFileNames(self, tr('Select images or videos'), start, MEDIA_FILTER)
        if paths:
            self._on_files_chosen([os.path.normpath(p) for p in paths])

    def _on_files_chosen(self, paths: List[str]) -> None:
        """
        Queue everything that was dropped, then put the first item on screen.

        The playlist is filled before the load so the entries keep the order they
        were dropped in - loading first would append the played file last.
        """
        if not paths:
            return
        self._last_dir = os.path.dirname(paths[0])
        self.playlist.add_paths(paths, announce=False)
        self.loadRequested.emit(paths[0])

    @Slot()
    def _on_add_to_queue(self) -> None:
        start = self._last_dir or os.path.dirname(self._path)
        paths, _ = QFileDialog.getOpenFileNames(self, tr('Add to playlist'), start, MEDIA_FILTER)
        if paths:
            self._last_dir = os.path.dirname(paths[0])
            self.playlist.add_paths([os.path.normpath(p) for p in paths])

    @Slot()
    def _on_clear_queue(self) -> None:
        if self.playlist.count() == 0:
            return
        answer = QMessageBox.question(self, tr('Empty playlist'), tr('Remove every entry from this playlist?'))
        if answer == QMessageBox.Yes:
            self.playlist.clear_all()

    @Slot()
    def _on_clear(self) -> None:
        self.clearRequested.emit()      # first: an undo can still see what was there
        self.reset_file()

    @Slot(bool)
    def _on_repeat_toggled(self, enabled: bool) -> None:
        self.repeat_btn.setIcon(Icons.get("repeat", CLR_ACCENT if enabled else CLR_MUTED))
        self.repeat_btn.setToolTip(tr('Repeat is ON') if enabled else tr('Repeat is OFF - plays once'))
        self.repeatChanged.emit(enabled)

    @Slot(bool)
    def _on_mute_toggled(self, muted: bool) -> None:
        self.mute_btn.setIcon(Icons.get("mute" if muted else "volume",
                                        CLR_DANGER if muted else CLR_TEXT))
        self.mute_btn.setToolTip(tr('Audio muted') if muted else tr('Mute audio'))
        self.muteChanged.emit(muted)


class TopCard(OutputCard):
    """OutputCard plus solid-colour background and the marquee controls."""

    colorRequested = Signal(QColor)
    marqueeTextChanged = Signal(str)
    marqueeFontSizeChanged = Signal(int)
    marqueeFamilyChanged = Signal(str)
    marqueeColorChanged = Signal(QColor)
    marqueeSpeedChanged = Signal(int)
    marqueeStart = Signal()
    marqueeStop = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Top Screen", "ceiling LED strip", ScaleMode.CROP, parent)
        self._bg_color = QColor("#101828")
        self._text_color = QColor("#ffd23f")

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet(f"color: {CLR_LINE}; max-height: 1px;")
        self.root.addWidget(divider)

        # One row for the heading, the typeface and both colours: the card is
        # the tallest on the Live tab and has to fit a 1080p screen with
        # finger-sized controls.
        font_row = QHBoxLayout()
        font_row.setSpacing(6)
        glyph = QLabel()
        glyph.setPixmap(Icons.get("text", CLR_MUTED, 14).pixmap(14, 14))
        glyph.setToolTip(tr('Marquee'))
        font_row.addWidget(glyph)
        label = QLabel(tr('Marquee'))
        label.setObjectName("sectionTitle")
        font_row.addWidget(label)
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont("Segoe UI"))
        self.font_combo.setToolTip(tr('Marquee typeface'))
        self.font_combo.currentFontChanged.connect(
            lambda font: self.marqueeFamilyChanged.emit(font.family())
        )
        font_row.addWidget(self.font_combo, 1)

        self.size_spin = QSpinBox()
        self.size_spin.setRange(8, 400)
        self.size_spin.setValue(96)
        self.size_spin.setSuffix(tr(' px'))
        self.size_spin.setToolTip(tr('Text height in pixels - match it to the strip height'))
        self.size_spin.valueChanged.connect(self.marqueeFontSizeChanged.emit)
        font_row.addWidget(self.size_spin)

        colour_btn = icon_button("palette", tr('Marquee text colour'), CLR_MUTED, 15)
        colour_btn.setObjectName("ghost")
        colour_btn.clicked.connect(self._pick_text_colour)
        font_row.addWidget(colour_btn)
        self.text_preview = QLabel()
        self.text_preview.setFixedSize(16, 16)
        self.text_preview.setToolTip(tr('Text colour'))
        font_row.addWidget(self.text_preview)
        font_row.addSpacing(4)
        bg_btn = icon_button("palette", tr('Solid colour background for this screen'), CLR_MUTED, 15)
        bg_btn.setObjectName("ghost")
        bg_btn.clicked.connect(self._pick_background)
        font_row.addWidget(bg_btn)
        self.bg_preview = QLabel()
        self.bg_preview.setFixedSize(16, 16)
        self.bg_preview.setToolTip(tr('Background colour'))
        font_row.addWidget(self.bg_preview)
        self.root.addLayout(font_row)
        self._update_swatch(self.text_preview, self._text_color)
        self._update_swatch(self.bg_preview, self._bg_color)

        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText(tr('Text to scroll across the strip…'))
        self.text_edit.textChanged.connect(self.marqueeTextChanged.emit)

        # the text, its speed and Start / Stop share one row: the card is the
        # tallest on the Live tab, and the Live tab has to fit a 1080p desk
        speed_row = QHBoxLayout()
        speed_row.setSpacing(8)
        speed_row.addWidget(self.text_edit, 3)
        speed_caption = QLabel(tr('Speed'))
        speed_caption.setObjectName("cardHint")
        speed_row.addWidget(speed_caption)
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(20, 800)
        self.speed_slider.setValue(180)
        self.speed_slider.valueChanged.connect(self._on_speed)
        self.speed_slider.setMinimumWidth(70)
        speed_row.addWidget(self.speed_slider, 1)
        self.speed_label = QLabel(tr('180 px/s'))
        self.speed_label.setObjectName("cardHint")
        self.speed_label.setMinimumWidth(58)
        speed_row.addWidget(self.speed_label)
        start = QPushButton(tr('  Start'))
        start.setIcon(Icons.get("play", CLR_TEXT))
        start.setToolTip(tr('Start scrolling the text across the strip'))
        start.clicked.connect(self.marqueeStart.emit)
        stop = QPushButton(tr('  Stop'))
        stop.setIcon(Icons.get("stop", CLR_TEXT))
        stop.clicked.connect(self.marqueeStop.emit)
        speed_row.addWidget(start)
        speed_row.addWidget(stop)
        self.root.addLayout(speed_row)
        self.root.addStretch(1)

    # -- helpers ------------------------------------------------------------ #

    @staticmethod
    def _update_swatch(label: QLabel, colour: QColor) -> None:
        label.setStyleSheet(
            f"background-color: {colour.name()}; border: 1px solid {CLR_LINE}; border-radius: 4px;"
        )

    @Slot()
    def _pick_background(self) -> None:
        colour = QColorDialog.getColor(self._bg_color, self, tr("Top screen background colour"))
        if colour.isValid():
            self._bg_color = colour
            self._update_swatch(self.bg_preview, colour)
            self.reset_file()
            self.colorRequested.emit(colour)

    @Slot()
    def _pick_text_colour(self) -> None:
        colour = QColorDialog.getColor(self._text_color, self, "Marquee text colour")
        if colour.isValid():
            self._text_color = colour
            self._update_swatch(self.text_preview, colour)
            self.marqueeColorChanged.emit(colour)

    @Slot(int)
    def _on_speed(self, value: int) -> None:
        self.speed_label.setText(tr('{0} px/s').format(value))
        self.marqueeSpeedChanged.emit(value)

    # -- preset access ------------------------------------------------------ #

    def marquee_state(self) -> dict:
        return {
            "text": self.text_edit.text(),
            "family": self.font_combo.currentFont().family(),
            "size": self.size_spin.value(),
            "colour": self._text_color.name(),
            "speed": self.speed_slider.value(),
        }

    def apply_marquee_state(self, data: dict) -> None:
        self.text_edit.setText(data.get("text", ""))
        family = data.get("family")
        if family:
            self.font_combo.setCurrentFont(QFont(family))
        self.size_spin.setValue(int(data.get("size", 96)))
        self._text_color = QColor(data.get("colour", "#ffd23f"))
        self._update_swatch(self.text_preview, self._text_color)
        self.marqueeColorChanged.emit(self._text_color)
        self.speed_slider.setValue(int(data.get("speed", 180)))

    def background_colour(self) -> QColor:
        return self._bg_color

    def set_background_colour_value(self, colour: QColor) -> None:
        self._bg_color = colour
        self._update_swatch(self.bg_preview, colour)
