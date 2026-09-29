"""
Screens & Setup: which monitor each output goes to, and its exact geometry.

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

# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #

@dataclass
class RouteConfig:
    """One output's monitor assignment, its rectangle, and its stacking."""

    screen_name: Optional[str] = None
    custom: bool = False
    offset_x: int = 0
    offset_y: int = 0
    width: int = 1920
    height: int = 1080
    on_top: bool = True

    def to_dict(self) -> dict:
        return {
            "screen": self.screen_name,
            "custom": self.custom,
            "x": self.offset_x,
            "y": self.offset_y,
            "w": self.width,
            "h": self.height,
            "on_top": self.on_top,
        }

    @staticmethod
    def from_dict(data: dict, default_on_top: bool = True) -> "RouteConfig":
        return RouteConfig(
            screen_name=data.get("screen"),
            custom=bool(data.get("custom", False)),
            offset_x=int(data.get("x", 0)),
            offset_y=int(data.get("y", 0)),
            width=int(data.get("w", 1920)),
            height=int(data.get("h", 1080)),
            on_top=bool(data.get("on_top", default_on_top)),
        )


class RoutingRow(QWidget):
    """
    One row of the Screens tab: which monitor, and exactly which rectangle.

    "Fullscreen" follows whatever Windows reports for the monitor. "Custom size"
    is the escape hatch for LED processors: the strip reports 2816x256 but its
    mapped canvas is 2818x132, so the window must be sized by hand.

    "On top" is per-output on purpose: the Main Stage usually needs it OFF so a
    PowerPoint deck or a browser can be shown over the background, while the
    side and ceiling screens should stay above everything.
    """

    onTopChanged = Signal(str, bool)

    def __init__(self, role: str, allow_custom: bool = True, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.role = role

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)

        label = QLabel(ROLE_LABELS[role])
        label.setMinimumWidth(104)
        label.setStyleSheet("font-weight: 600;")
        layout.addWidget(label, 0, 0)

        self.screen_combo = QComboBox()
        self.screen_combo.setMinimumWidth(320)
        layout.addWidget(self.screen_combo, 0, 1)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem(tr('Fullscreen'), False)
        self.mode_combo.addItem(tr('Custom size'), True)
        self.mode_combo.currentIndexChanged.connect(self._sync_enabled)
        layout.addWidget(self.mode_combo, 0, 2)

        self.spins: Dict[str, QSpinBox] = {}
        self._spin_wrappers: List[QWidget] = []
        for column, (key, caption) in enumerate(
            (("w", "W"), ("h", "H"), ("x", "X"), ("y", "Y")), start=3
        ):
            holder = QHBoxLayout()
            holder.setContentsMargins(0, 0, 0, 0)
            holder.setSpacing(4)
            caption_label = QLabel(caption)
            caption_label.setStyleSheet(f"color: {CLR_MUTED};")
            holder.addWidget(caption_label)
            spin = QSpinBox()
            spin.setRange(-20000 if key in ("x", "y") else 1, 20000)
            spin.setMaximumWidth(80)
            holder.addWidget(spin)
            self.spins[key] = spin
            wrapper = QWidget()
            wrapper.setLayout(holder)
            self._spin_wrappers.append(wrapper)
            layout.addWidget(wrapper, 0, column)

        self.spins["x"].setToolTip(tr("Offset from the monitor's left edge"))
        self.spins["y"].setToolTip(tr("Offset from the monitor's top edge"))

        self.on_top_check = QCheckBox(tr('On top'))
        self.on_top_check.setChecked(True)
        self.on_top_check.setToolTip(
            tr('Keep this output above other windows.\nSwitch it OFF to show a presentation or a browser over this screen.')
        )
        self.on_top_check.toggled.connect(
            lambda checked: self.onTopChanged.emit(self.role, checked)
        )
        layout.addWidget(self.on_top_check, 0, 7)

        if not allow_custom:
            self.mode_combo.hide()
            self.on_top_check.hide()
            for wrapper in self._spin_wrappers:
                wrapper.hide()

        layout.setColumnStretch(1, 1)
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        enabled = bool(self.mode_combo.currentData())
        for spin in self.spins.values():
            spin.setEnabled(enabled)

    def config(self) -> RouteConfig:
        return RouteConfig(
            screen_name=self.screen_combo.currentData(),
            custom=bool(self.mode_combo.currentData()),
            offset_x=self.spins["x"].value(),
            offset_y=self.spins["y"].value(),
            width=self.spins["w"].value(),
            height=self.spins["h"].value(),
            on_top=self.on_top_check.isChecked(),
        )

    def apply_config(self, config: RouteConfig, screen_names: List[str]) -> None:
        index = screen_names.index(config.screen_name) + 1 if config.screen_name in screen_names else 0
        self.screen_combo.setCurrentIndex(index)
        self.mode_combo.setCurrentIndex(1 if config.custom else 0)
        self.spins["x"].setValue(config.offset_x)
        self.spins["y"].setValue(config.offset_y)
        self.spins["w"].setValue(config.width)
        self.spins["h"].setValue(config.height)
        self.on_top_check.setChecked(config.on_top)
        self._sync_enabled()

    def set_size(self, width: int, height: int) -> None:
        self.spins["w"].setValue(width)
        self.spins["h"].setValue(height)
