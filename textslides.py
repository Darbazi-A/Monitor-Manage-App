"""
Names on screen: the running order of names, their looks and a true-to-stage preview.

Part of Stage Display Controller; main.py builds the dashboard from these.
"""

from __future__ import annotations

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

# Ready-made looks for names on screen; the operator can save more.
TEXT_LOOKS = {
    "Name + role, low (lower third)": {"title_px": 72, "subtitle_px": 40, "position": "bottom", "scrim": True,
                                        "colour": "#ffffff", "subtitle_colour": "#cfd8e6"},
    "Big title, centre": {"title_px": 130, "subtitle_px": 56, "position": "middle", "scrim": False,
                          "colour": "#ffffff", "subtitle_colour": "#e9edf5"},
    "Award: gold name": {"title_px": 96, "subtitle_px": 46, "position": "middle", "scrim": True,
                         "colour": "#ffd23f", "subtitle_colour": "#ffffff"},
    "Caption at the top": {"title_px": 64, "subtitle_px": 36, "position": "top", "scrim": True,
                           "colour": "#ffffff", "subtitle_colour": "#cfd8e6"},
}


class TextSlides(QWidget):
    """
    Names on screen, prepared in advance and stepped through live.

    The running order is a plain text box, one slide per line, because that is
    the fastest way in: an award list already exists in a document and can be
    pasted straight here. A line may carry a second, smaller line after "|".
    """

    showRequested = Signal(str, str)     # title, subtitle
    hideRequested = Signal()
    styleChanged = Signal()
    targetChanged = Signal(str)
    looksChanged = Signal()

    SEPARATOR = "|"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title_colour = QColor("#ffffff")
        self._subtitle_colour = QColor("#cfd8e6")
        self.custom_looks: Dict[str, dict] = {}
        # set by the dashboard: a live picture of a screen, and a screen's real size
        self.preview_source: Optional[Callable[[str, QSize], Optional[QPixmap]]] = None
        self.stage_size: Optional[Callable[[str], QSize]] = None
        self._preview_window: Optional[SceneOutputWindow] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 10, 0, 0)
        root.setSpacing(11)

        card = QFrame()
        card.setObjectName("card")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(10)

        # --- header -------------------------------------------------------- #
        header = QHBoxLayout()
        header.setSpacing(8)
        glyph = QLabel()
        glyph.setPixmap(Icons.get("text", CLR_ACCENT, 16).pixmap(16, 16))
        header.addWidget(glyph)
        title = QLabel("TEXT SLIDES")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        hint = QLabel("one line per slide · use “|” for a second, smaller line")
        hint.setObjectName("keyHint")
        header.addWidget(hint)
        header.addStretch(1)

        header.addWidget(QLabel("Show on"))
        self.target = QComboBox()
        for role in STAGE_ROLES:
            self.target.addItem(ROLE_LABELS[role], role)
        self.target.setToolTip("Which screen the names appear on")
        self.target.currentIndexChanged.connect(
            lambda _i: self.targetChanged.emit(self.target.currentData()))
        header.addWidget(self.target)
        outer.addLayout(header)

        # --- running order + list ------------------------------------------ #
        body = QHBoxLayout()
        body.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(5)
        caption = QLabel("RUNNING ORDER")
        caption.setObjectName("sectionTitle")
        left.addWidget(caption)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "Nino Beridze | Grade 5, Mathematics\n"
            "Giorgi Kapanadze | Grade 7, Science\n"
            "\n"
            "Welcome to the Spring Concert")
        self.editor.textChanged.connect(self._rebuild_list)
        left.addWidget(self.editor, 1)
        body.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(5)
        self.preview_caption = QLabel("PREVIEW")
        self.preview_caption.setObjectName("sectionTitle")
        right.addWidget(self.preview_caption)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(140)
        self.preview_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.preview_label.setStyleSheet("background: #05070b; border-radius: 8px;")
        self.preview_label.setToolTip("The selected name, as it will look on that screen - over what it shows now")
        right.addWidget(self.preview_label)
        caption2 = QLabel("SLIDES  —  click one to put it on screen")
        caption2.setObjectName("sectionTitle")
        right.addWidget(caption2)
        self.slides = QListWidget()
        self.slides.setAlternatingRowColors(False)
        self.slides.itemClicked.connect(self._on_slide_clicked)
        right.addWidget(self.slides, 1)
        body.addLayout(right, 1)
        outer.addLayout(body, 1)

        # --- look ----------------------------------------------------------- #
        look = QHBoxLayout()
        look.setSpacing(7)
        self.look_combo = QComboBox()
        self.look_combo.setToolTip("Ready-made looks: size, position, colours and shade in one go")
        self.look_combo.activated.connect(self._on_look_chosen)
        look.addWidget(self.look_combo)
        save_look = QPushButton("  Save look…")
        save_look.setIcon(Icons.get("save", CLR_TEXT, 15))
        save_look.setToolTip("Keep the current size, position and colours as a look of your own")
        save_look.clicked.connect(self._save_look)
        look.addWidget(save_look)
        look.addSpacing(8)
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont("Segoe UI"))
        self.font_combo.setMaximumWidth(210)
        self.font_combo.currentFontChanged.connect(lambda _f: self.styleChanged.emit())
        look.addWidget(self.font_combo)

        look.addWidget(QLabel("Name"))
        self.title_size = QSpinBox()
        self.title_size.setRange(12, 400)
        self.title_size.setValue(84)
        self.title_size.setSuffix(" px")
        self.title_size.valueChanged.connect(lambda _v: self.styleChanged.emit())
        look.addWidget(self.title_size)

        title_colour = icon_button("palette", "Colour of the big line", CLR_MUTED, 15)
        title_colour.setObjectName("ghost")
        title_colour.clicked.connect(lambda: self._pick_colour("title"))
        look.addWidget(title_colour)
        self.title_swatch = QLabel()
        self.title_swatch.setFixedSize(16, 16)
        look.addWidget(self.title_swatch)

        look.addSpacing(8)
        look.addWidget(QLabel("Second line"))
        self.subtitle_size = QSpinBox()
        self.subtitle_size.setRange(10, 300)
        self.subtitle_size.setValue(44)
        self.subtitle_size.setSuffix(" px")
        self.subtitle_size.valueChanged.connect(lambda _v: self.styleChanged.emit())
        look.addWidget(self.subtitle_size)

        sub_colour = icon_button("palette", "Colour of the small line", CLR_MUTED, 15)
        sub_colour.setObjectName("ghost")
        sub_colour.clicked.connect(lambda: self._pick_colour("subtitle"))
        look.addWidget(sub_colour)
        self.subtitle_swatch = QLabel()
        self.subtitle_swatch.setFixedSize(16, 16)
        look.addWidget(self.subtitle_swatch)

        look.addSpacing(8)
        look.addWidget(QLabel("Position"))
        self.position = QComboBox()
        for caption_text, value in (("Middle", "middle"), ("Top", "top"), ("Bottom", "bottom")):
            self.position.addItem(caption_text, value)
        self.position.currentIndexChanged.connect(lambda _i: self.styleChanged.emit())
        look.addWidget(self.position)

        self.scrim = QCheckBox("Shade behind")
        self.scrim.setChecked(True)
        self.scrim.setToolTip("A dark band behind the text so it stays readable over video")
        self.scrim.toggled.connect(lambda _v: self.styleChanged.emit())
        look.addWidget(self.scrim)
        look.addStretch(1)
        outer.addLayout(look)
        self._update_swatches()
        self._fill_looks()
        self.styleChanged.connect(self.refresh_preview)
        self.slides.currentRowChanged.connect(lambda _r: self.refresh_preview())
        self.target.currentIndexChanged.connect(lambda _i: self.refresh_preview())
        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self.refresh_preview)
        self._preview_timer.start(1500)      # the screen behind the text keeps moving

        # --- transport ------------------------------------------------------ #
        transport = QHBoxLayout()
        transport.setSpacing(7)
        prev_btn = QPushButton("  Previous")
        prev_btn.setIcon(Icons.get("prev", CLR_TEXT, 15))
        prev_btn.clicked.connect(lambda: self.step(-1))
        transport.addWidget(prev_btn)

        self.show_btn = QPushButton("  SHOW THIS NAME")
        self.show_btn.setObjectName("primary")
        self.show_btn.setIcon(Icons.get("play", "#0b0e13", 15))
        self.show_btn.setMinimumWidth(210)
        self.show_btn.clicked.connect(self.show_current)
        transport.addWidget(self.show_btn)

        next_btn = QPushButton("  Next")
        next_btn.setIcon(Icons.get("next", CLR_TEXT, 15))
        next_btn.clicked.connect(lambda: self.step(1))
        transport.addWidget(next_btn)

        hide_btn = QPushButton("  Hide text")
        hide_btn.setObjectName("danger")
        hide_btn.setIcon(Icons.get("close", CLR_DANGER, 15))
        hide_btn.clicked.connect(self.hideRequested.emit)
        transport.addWidget(hide_btn)

        transport.addSpacing(12)
        keys = QLabel("Ctrl+→ next · Ctrl+← previous · Ctrl+H hide")
        keys.setObjectName("keyHint")
        transport.addWidget(keys)
        transport.addStretch(1)
        outer.addLayout(transport)

        root.addWidget(card, 1)

    # -- looks ---------------------------------------------------------------- #

    def _fill_looks(self) -> None:
        self.look_combo.blockSignals(True)
        self.look_combo.clear()
        self.look_combo.addItem("Look…", "")
        for name in TEXT_LOOKS:
            self.look_combo.addItem(name, name)
        for name in self.custom_looks:
            self.look_combo.addItem(f"★ {name}", name)
        self.look_combo.blockSignals(False)

    def set_custom_looks(self, looks: Dict[str, dict]) -> None:
        self.custom_looks = {k: v for k, v in looks.items() if isinstance(v, dict)}
        self._fill_looks()

    def _on_look_chosen(self, index: int) -> None:
        name = self.look_combo.itemData(index)
        self.look_combo.setCurrentIndex(0)
        look = self.custom_looks.get(name) or TEXT_LOOKS.get(name)
        if look:
            self.apply_look(look)

    def apply_look(self, look: dict) -> None:
        widgets = (self.font_combo, self.title_size, self.subtitle_size, self.position, self.scrim)
        for widget in widgets:
            widget.blockSignals(True)
        if look.get("family"):
            self.font_combo.setCurrentFont(QFont(look["family"]))
        self.title_size.setValue(int(look.get("title_px", self.title_size.value())))
        self.subtitle_size.setValue(int(look.get("subtitle_px", self.subtitle_size.value())))
        self.position.setCurrentIndex(max(0, self.position.findData(look.get("position", "middle"))))
        self.scrim.setChecked(bool(look.get("scrim", True)))
        self._title_colour = QColor(look.get("colour", self._title_colour.name()))
        self._subtitle_colour = QColor(look.get("subtitle_colour", self._subtitle_colour.name()))
        for widget in widgets:
            widget.blockSignals(False)
        self._update_swatches()
        self.styleChanged.emit()

    def _save_look(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save look", "Name for this look:")
        name = name.strip()
        if not accepted or not name:
            return
        self.custom_looks[name] = self.style_dict()
        self._fill_looks()
        self.looksChanged.emit()

    # -- preview --------------------------------------------------------------- #

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self.refresh_preview)

    def refresh_preview(self) -> None:
        """
        The selected name as it will look: drawn by the same machinery as the
        stage, at the screen's real size, over a picture of what it shows now.
        """
        if not self.isVisible() or self.stage_size is None:
            return
        role = self.target.currentData() or ROLE_MAIN
        size = self.stage_size(role)
        if size.isEmpty():
            return
        if self._preview_window is None:
            self._preview_window = StandardOutputWindow("text preview")
            self._preview_window.setWindowFlags(Qt.Widget)
        window = self._preview_window
        window.set_virtual_size(size)
        width = max(160, self.preview_label.width() - 8)
        height = int(width * size.height() / size.width())
        if height > 220:
            height = 220
            width = int(height * size.width() / size.height())
        backdrop = self.preview_source(role, QSize(max(1, width), max(1, height))) if self.preview_source else None
        window.set_backdrop(backdrop)
        item = self.slides.currentItem()
        title, subtitle = item.data(Qt.UserRole) if item is not None else ("Nino Beridze", "Grade 5 · Mathematics")
        window.set_slide_style(self.style_dict())
        window.show_slide(title, subtitle, 0)
        self.preview_label.setFixedHeight(max(40, height + 8))
        self.preview_label.setPixmap(window.preview(QSize(max(1, width), max(1, height))))
        self.preview_caption.setText(f"PREVIEW  ·  {ROLE_LABELS[role].upper()}  ·  {size.width()}×{size.height()}"
                                     + ("" if item is not None else "  ·  sample name"))

    # -- running order ------------------------------------------------------ #

    def _rebuild_list(self) -> None:
        current = self.slides.currentRow()
        self.slides.clear()
        for index, (title, subtitle) in enumerate(self.entries(), start=1):
            item = QListWidgetItem(f"{index}.  {title}" + (f"    —  {subtitle}" if subtitle else ""))
            item.setData(Qt.UserRole, (title, subtitle))
            self.slides.addItem(item)
        if 0 <= current < self.slides.count():
            self.slides.setCurrentRow(current)
        elif self.slides.count():
            self.slides.setCurrentRow(0)
        self.styleChanged.emit()   # keeps presets marked as changed

    def entries(self) -> List[tuple]:
        found = []
        for raw in self.editor.toPlainText().splitlines():
            line = raw.strip()
            if not line:
                continue
            if self.SEPARATOR in line:
                title, subtitle = line.split(self.SEPARATOR, 1)
                found.append((title.strip(), subtitle.strip()))
            else:
                found.append((line, ""))
        return found

    def set_text(self, text: str) -> None:
        self.editor.setPlainText(text or "")

    def text(self) -> str:
        return self.editor.toPlainText()

    # -- performing --------------------------------------------------------- #

    @Slot(QListWidgetItem)
    def _on_slide_clicked(self, item: QListWidgetItem) -> None:
        title, subtitle = item.data(Qt.UserRole)
        self.showRequested.emit(title, subtitle)

    def show_current(self) -> None:
        item = self.slides.currentItem()
        if item is None and self.slides.count():
            self.slides.setCurrentRow(0)
            item = self.slides.currentItem()
        if item is not None:
            self._on_slide_clicked(item)

    def step(self, delta: int) -> None:
        if not self.slides.count():
            return
        row = self.slides.currentRow()
        row = (row + delta) % self.slides.count() if row >= 0 else 0
        self.slides.setCurrentRow(row)
        self.show_current()

    # -- look --------------------------------------------------------------- #

    def _pick_colour(self, which: str) -> None:
        current = self._title_colour if which == "title" else self._subtitle_colour
        colour = QColorDialog.getColor(current, self, "Text colour")
        if not colour.isValid():
            return
        if which == "title":
            self._title_colour = colour
        else:
            self._subtitle_colour = colour
        self._update_swatches()
        self.styleChanged.emit()

    def _update_swatches(self) -> None:
        for label, colour in ((self.title_swatch, self._title_colour),
                              (self.subtitle_swatch, self._subtitle_colour)):
            label.setStyleSheet(
                f"background-color: {colour.name()}; border: 1px solid {CLR_LINE};"
                "border-radius: 4px;")

    def style_dict(self) -> dict:
        return {
            "family": self.font_combo.currentFont().family(),
            "title_px": self.title_size.value(),
            "subtitle_px": self.subtitle_size.value(),
            "colour": self._title_colour.name(),
            "subtitle_colour": self._subtitle_colour.name(),
            "position": self.position.currentData(),
            "scrim": self.scrim.isChecked(),
        }

    def to_dict(self) -> dict:
        data = {"text": self.text(), "target": self.target.currentData()}
        data.update(self.style_dict())
        return data

    def from_dict(self, data: dict) -> None:
        blocked = (self.editor, self.font_combo, self.title_size, self.subtitle_size,
                   self.position, self.scrim, self.target)
        for widget in blocked:
            widget.blockSignals(True)
        family = data.get("family")
        if family:
            self.font_combo.setCurrentFont(QFont(family))
        self.title_size.setValue(int(data.get("title_px", 84)))
        self.subtitle_size.setValue(int(data.get("subtitle_px", 44)))
        self._title_colour = QColor(data.get("colour", "#ffffff"))
        self._subtitle_colour = QColor(data.get("subtitle_colour", "#cfd8e6"))
        index = self.position.findData(data.get("position", "middle"))
        self.position.setCurrentIndex(max(0, index))
        self.scrim.setChecked(bool(data.get("scrim", True)))
        index = self.target.findData(data.get("target", ROLE_MAIN))
        self.target.setCurrentIndex(max(0, index))
        self.editor.setPlainText(data.get("text", ""))
        for widget in blocked:
            widget.blockSignals(False)
        self._update_swatches()
        self._rebuild_list()
