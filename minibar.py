"""
The compact bar the dashboard shrinks to.

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
from cards import *  # noqa: F401,F403
from library import *  # noqa: F401,F403
from textslides import *  # noqa: F401,F403
from routing import *  # noqa: F401,F403

class MiniBar(QWidget):
    """
    The dashboard shrunk to a strip that stays on top of everything.

    It carries the controls that get used under pressure, and - just as
    important - enough state to act without expanding: which screen the arrows
    will move, what is on it, and which cues are running.
    """

    expandRequested = Signal()
    presetRequested = Signal(str)
    blackoutRequested = Signal()
    stopSoundRequested = Signal()
    stepRequested = Signal(int)
    playPauseRequested = Signal()
    cueRequested = Signal(int)
    screenChosen = Signal(str)
    showNextRequested = Signal()
    showBackRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool)
        self.setObjectName("miniBar")
        self._drag_from = None

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("miniCard")
        shell.addWidget(card)

        body = QVBoxLayout(card)
        body.setContentsMargins(12, 9, 12, 10)
        body.setSpacing(8)

        # --- row 1: which screen, what is on it, and the running order ------- #
        top = QHBoxLayout()
        top.setSpacing(6)

        grip = QLabel()
        grip.setPixmap(Icons.get("grip", CLR_MUTED, 15).pixmap(15, 15))
        grip.setToolTip(tr('Drag to move'))
        top.addWidget(grip)
        top.addSpacing(2)

        self.screen_buttons: Dict[str, QPushButton] = {}
        for role, short in ((ROLE_MAIN, "Main"), (ROLE_SIDES, "Sides"), (ROLE_TOP, "Top")):
            button = QPushButton(tr(short))
            button.setObjectName("miniScreen")
            button.setCheckable(True)
            button.setToolTip(tr('Arrows and play act on {0}').format(ROLE_LABELS[role]))
            button.clicked.connect(lambda _c=False, r=role: self.screenChosen.emit(r))
            top.addWidget(button)
            self.screen_buttons[role] = button

        top.addSpacing(4)
        prev_btn = icon_button("prev", tr("Previous in that screen's playlist"), CLR_TEXT, 15)
        prev_btn.clicked.connect(lambda: self.stepRequested.emit(-1))
        top.addWidget(prev_btn)

        self.play_btn = icon_button("play", tr('Play / pause that screen'), CLR_TEXT, 15)
        self.play_btn.clicked.connect(self.playPauseRequested.emit)
        top.addWidget(self.play_btn)

        next_btn = icon_button("next", tr("Next in that screen's playlist"), CLR_TEXT, 15)
        next_btn.clicked.connect(lambda: self.stepRequested.emit(1))
        top.addWidget(next_btn)

        top.addSpacing(6)
        self.now_label = QLabel()
        self.now_label.setObjectName("miniNow")
        self.now_label.setMinimumWidth(210)
        top.addWidget(self.now_label, 1)

        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(140)
        self.preset_combo.setToolTip(tr('Saved shows'))
        top.addWidget(self.preset_combo)

        load = QPushButton(tr('Load'))
        load.setObjectName("primary")
        load.setToolTip(tr('Put this preset on the screens'))
        load.clicked.connect(lambda: self.presetRequested.emit(self.preset_combo.currentText()))
        top.addWidget(load)
        body.addLayout(top)

        # --- row 2: sound and the panic buttons ------------------------------ #
        bottom = QHBoxLayout()
        bottom.setSpacing(5)

        self.cue_buttons: List[QPushButton] = []
        for slot in range(SOUND_SLOTS):
            button = QPushButton(f"F{slot + 1}")
            button.setObjectName("miniCue")
            button.setFixedWidth(40)
            button.clicked.connect(lambda _c=False, i=slot: self.cueRequested.emit(i))
            bottom.addWidget(button)
            self.cue_buttons.append(button)

        bottom.addSpacing(6)
        self.sound_label = QLabel()
        self.sound_label.setObjectName("miniNow")
        bottom.addWidget(self.sound_label, 1)

        quiet = QPushButton(tr('  Silence'))
        quiet.setIcon(Icons.get("mute", CLR_DIM, 15))
        quiet.setToolTip(tr('Fade out every sound cue'))
        quiet.clicked.connect(self.stopSoundRequested.emit)
        bottom.addWidget(quiet)

        blackout = QPushButton(tr('BLACKOUT'))
        blackout.setObjectName("danger")
        blackout.clicked.connect(self.blackoutRequested.emit)
        bottom.addWidget(blackout)

        expand = icon_button("expand", tr('Back to the full dashboard'), CLR_DIM, 16)
        expand.clicked.connect(self.expandRequested.emit)
        bottom.addWidget(expand)
        body.addLayout(bottom)

        # --- row 3: the running order, when there is one -------------------- #
        self.show_row = QWidget()
        show = QHBoxLayout(self.show_row)
        show.setContentsMargins(0, 0, 0, 0)
        show.setSpacing(6)
        back = icon_button("prev", tr('Back one step (Page Up)'), CLR_TEXT, 15)
        back.clicked.connect(self.showBackRequested.emit)
        show.addWidget(back)
        self.show_label = QLabel()
        self.show_label.setObjectName("miniNow")
        show.addWidget(self.show_label, 1)
        self.show_next = QPushButton(tr('  NEXT'))
        self.show_next.setObjectName("primary")
        self.show_next.setIcon(Icons.get("next", "#0b0e13", 15))
        self.show_next.setToolTip(tr('Run the next step of the running order (Page Down)'))
        self.show_next.clicked.connect(self.showNextRequested.emit)
        show.addWidget(self.show_next)
        body.addWidget(self.show_row)
        self.show_row.hide()

    # -- state --------------------------------------------------------------- #

    def show_running(self, text: str, can_next: bool, visible: bool) -> None:
        self.show_row.setVisible(visible)
        if not visible:
            return
        metrics = self.show_label.fontMetrics()
        self.show_label.setText(metrics.elidedText(text, Qt.ElideRight, max(160, self.show_label.width())))
        self.show_label.setToolTip(text)
        self.show_next.setEnabled(can_next)

    @staticmethod
    def _restyle_if(button: QPushButton, name: str, value: str) -> None:
        """Re-polish only when the property really changes: it re-resolves the stylesheet."""
        if button.property(name) != value:
            button.setProperty(name, value)
            button.style().unpolish(button)
            button.style().polish(button)

    def set_presets(self, names: List[str], current: Optional[str]) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        if names:
            self.preset_combo.addItems(names)
            self.preset_combo.setEnabled(True)
            if current:
                index = self.preset_combo.findText(current)
                if index >= 0:
                    self.preset_combo.setCurrentIndex(index)
        else:
            self.preset_combo.addItem(tr('no presets'))
            self.preset_combo.setEnabled(False)
        self.preset_combo.blockSignals(False)

    def show_screen(self, role: str, name: str, live: bool, playing: bool) -> None:
        for key, button in self.screen_buttons.items():
            button.setChecked(key == role)
            self._restyle_if(button, "live", "true" if live and key == role else "false")
        metrics = self.now_label.fontMetrics()
        self.now_label.setText(
            metrics.elidedText(name or "nothing on this screen", Qt.ElideMiddle,
                               max(140, self.now_label.width())))
        self.now_label.setToolTip(name)
        self.play_btn.setIcon(Icons.get("pause" if playing else "play", CLR_TEXT, 15))

    def show_cues(self, cues) -> None:
        running = []
        for button, cue in zip(self.cue_buttons, cues):
            filled = bool(cue.path)
            button.setEnabled(filled)
            self._restyle_if(button, "playing", "true" if cue.is_playing() else "false")
            self._restyle_if(button, "paused", "true" if cue.is_paused() else "false")
            button.setToolTip(cue.label() if filled else tr('F{0} is empty').format(cue.index + 1))
            if cue.is_playing():
                running.append(f"{cue.label()}  {format_time(cue.position())}")
        metrics = self.sound_label.fontMetrics()
        text = "   \u00b7   ".join(running) if running else ""
        self.sound_label.setText(
            metrics.elidedText(text, Qt.ElideRight, max(120, self.sound_label.width())))
        self.sound_label.setToolTip(text)

    # -- dragging ------------------------------------------------------------ #

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_from = None
        event.accept()
