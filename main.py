"""
Stage Display Controller
========================

A multi-screen playback controller for a school assembly hall stage (PySide6 / Qt 6).

Physical setup
--------------
* Operator PC -> the Control Panel lives on the operator's monitor.
* Stage outputs (3 logical outputs):
    1. "Main Stage"   - the large central screen.
    2. "Side Screens" - left + right screens, mirrored by the hardware, so the
                        app produces ONE window that feeds both.
    3. "Top Screen"   - the wide LED strip near the ceiling. Supports an
                        image/video/solid-colour background plus scrolling text.

LED walls and Windows
---------------------
An LED processor (Nova Studio, LVP, ...) often reports a desktop resolution that
does not match the canvas the wall actually maps. The Top strip here reports
2816x256 to Windows while the real canvas is 2818x132. Every output therefore
supports a CUSTOM geometry: an exact width/height/offset used instead of
fullscreen. See RoutingRow and BaseOutputWindow.show_with_geometry().

Running a show
--------------
Each output has a PLAYLIST: the backgrounds prepared in advance for an event.
Click an entry (or the prev/next arrows) to put it on that screen instantly.
Playlists, routing, marquee and volumes all travel inside a named preset.

Architecture
------------
    Icons                - line icons drawn with QPainter (no image assets).
    MediaEngine          - QMediaPlayer wrapper: looping, safe source swapping.
    ImageView            - paints a QPixmap with a ScaleMode.
    BaseOutputWindow     - frameless, un-closable, taskbar-less stage window.
    StandardOutputWindow - Main / Sides output (QVideoWidget + ImageView).
    TopOutputWindow      - Top output (QGraphicsView, so text composites over video).
    DropZone             - drag & drop target with a thumbnail preview.
    Playlist             - the prepared-media list for one output.
    OutputCard / TopCard - one output's live controls.
    RoutingRow           - one row of the Screens tab: monitor + geometry.
    PresetStore          - named presets saved as JSON next to this file.
    ControlPanel         - the main window (Live tab + Screens tab).

Requirements:  Python 3.9+   and   pip install PySide6
Run with:      python main.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional

try:  # Windows only; the rest of the app runs without it.
    import winreg
except ImportError:  # pragma: no cover - non-Windows
    winreg = None

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPointF,
    QRect,
    QRectF,
    QSize,
    QSizeF,
    Qt,
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
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QScreen,
    QTransform,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem, QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
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
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QStackedLayout,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PRESET_FILE = os.path.join(APP_DIR, "presets.json")
ICON_FILE = os.path.join(APP_DIR, "stage_icon.ico")

# Per-user "run at login" entry. HKCU needs no administrator rights, and it
# starts nothing until the operator ticks the box in Screens & Setup.
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "StageDisplayController"

# LED processors and video walls often finish enumerating well after the
# desktop appears, so an autostart waits before applying the routing.
DEFAULT_STARTUP_DELAY = 20

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".mpg", ".mpeg", ".webm"}

MEDIA_FILTER = (
    "Media files (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff "
    "*.mp4 *.mov *.avi *.mkv *.wmv *.m4v *.mpg *.mpeg *.webm);;"
    "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff);;"
    "Videos (*.mp4 *.mov *.avi *.mkv *.wmv *.m4v *.mpg *.mpeg *.webm);;"
    "All files (*.*)"
)

ROLE_CONTROL = "control"
ROLE_MAIN = "main"
ROLE_SIDES = "sides"
ROLE_TOP = "top"

STAGE_ROLES = (ROLE_MAIN, ROLE_SIDES, ROLE_TOP)

ROLE_LABELS = {
    ROLE_CONTROL: "Control Panel",
    ROLE_MAIN: "Main Stage",
    ROLE_SIDES: "Side Screens",
    ROLE_TOP: "Top Screen",
}

# The LED strip's real canvas, as mapped in Nova Studio - NOT what Windows reports.
DEFAULT_TOP_WIDTH = 2818
DEFAULT_TOP_HEIGHT = 132

# Palette - a quiet, low-contrast dark theme so the stage stays the bright thing.
CLR_BG = "#12151b"
CLR_CARD = "#1a1f27"
CLR_INPUT = "#151a21"
CLR_HOVER = "#242b36"
CLR_LINE = "#2a323e"
CLR_TEXT = "#e3e8f0"
CLR_MUTED = "#79839a"
CLR_ACCENT = "#5aa9f0"
CLR_OK = "#4cc98a"
CLR_WARN = "#e8a44c"
CLR_DANGER = "#e8615f"


class ScaleMode(Enum):
    """How media is fitted into an output window."""

    STRETCH = "Stretch"
    FIT = "Fit (keep aspect)"
    CROP = "Fill (crop to cover)"

    @property
    def aspect_mode(self) -> Qt.AspectRatioMode:
        return {
            ScaleMode.STRETCH: Qt.IgnoreAspectRatio,
            ScaleMode.FIT: Qt.KeepAspectRatio,
            ScaleMode.CROP: Qt.KeepAspectRatioByExpanding,
        }[self]


def is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS


def is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS


def is_supported(path: str) -> bool:
    return is_image(path) or is_video(path)


def urls_to_paths(mime) -> List[str]:
    """Local, supported files from a drag & drop payload, in drop order."""
    if not mime.hasUrls():
        return []
    paths = []
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        # toLocalFile() yields forward slashes; normalise to Windows paths.
        path = os.path.normpath(url.toLocalFile())
        if is_supported(path):
            paths.append(path)
    return paths


# --------------------------------------------------------------------------- #
# Icons
# --------------------------------------------------------------------------- #

class Icons:
    """
    Minimal line icons drawn with QPainter on a 24x24 grid.

    Drawing them keeps the app a single file with no image assets, and every
    icon inherits the palette, so there is never a mismatched PNG.
    """

    _cache: Dict[tuple, QIcon] = {}

    # -- individual glyphs -------------------------------------------------- #

    @staticmethod
    def _play(p: QPainter) -> None:
        path = QPainterPath()
        path.moveTo(7.5, 4.8)
        path.lineTo(19.5, 12)
        path.lineTo(7.5, 19.2)
        path.closeSubpath()
        p.fillPath(path, p.pen().brush())

    @staticmethod
    def _pause(p: QPainter) -> None:
        brush = p.pen().brush()
        p.fillRect(QRectF(7.4, 5, 3.4, 14), brush)
        p.fillRect(QRectF(13.2, 5, 3.4, 14), brush)

    @staticmethod
    def _stop(p: QPainter) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(6.5, 6.5, 11, 11), 1.6, 1.6)
        p.fillPath(path, p.pen().brush())

    @staticmethod
    def _prev(p: QPainter) -> None:
        brush = p.pen().brush()
        p.fillRect(QRectF(5.6, 5.5, 2.2, 13), brush)
        path = QPainterPath()
        path.moveTo(18.8, 5.5)
        path.lineTo(18.8, 18.5)
        path.lineTo(9.6, 12)
        path.closeSubpath()
        p.fillPath(path, brush)

    @staticmethod
    def _next(p: QPainter) -> None:
        brush = p.pen().brush()
        p.fillRect(QRectF(16.2, 5.5, 2.2, 13), brush)
        path = QPainterPath()
        path.moveTo(5.2, 5.5)
        path.lineTo(5.2, 18.5)
        path.lineTo(14.4, 12)
        path.closeSubpath()
        p.fillPath(path, brush)

    @staticmethod
    def _plus(p: QPainter) -> None:
        p.drawLine(QPointF(12, 6), QPointF(12, 18))
        p.drawLine(QPointF(6, 12), QPointF(18, 12))

    @staticmethod
    def _minus(p: QPainter) -> None:
        p.drawLine(QPointF(6, 12), QPointF(18, 12))

    @staticmethod
    def _close(p: QPainter) -> None:
        p.drawLine(QPointF(7, 7), QPointF(17, 17))
        p.drawLine(QPointF(17, 7), QPointF(7, 17))

    @staticmethod
    def _trash(p: QPainter) -> None:
        p.drawLine(QPointF(4.5, 7), QPointF(19.5, 7))
        p.drawLine(QPointF(9.5, 4.5), QPointF(14.5, 4.5))
        path = QPainterPath()
        path.moveTo(6.8, 7)
        path.lineTo(7.8, 19.2)
        path.lineTo(16.2, 19.2)
        path.lineTo(17.2, 7)
        p.drawPath(path)

    @staticmethod
    def _folder(p: QPainter) -> None:
        path = QPainterPath()
        path.moveTo(3.5, 18.5)
        path.lineTo(3.5, 5.5)
        path.lineTo(9.5, 5.5)
        path.lineTo(11.5, 8.5)
        path.lineTo(20.5, 8.5)
        path.lineTo(20.5, 18.5)
        path.closeSubpath()
        p.drawPath(path)

    @staticmethod
    def _save(p: QPainter) -> None:
        path = QPainterPath()
        path.moveTo(4.5, 14.5)
        path.lineTo(4.5, 19.5)
        path.lineTo(19.5, 19.5)
        path.lineTo(19.5, 14.5)
        p.drawPath(path)
        p.drawLine(QPointF(12, 3.5), QPointF(12, 14.5))
        arrow = QPainterPath()
        arrow.moveTo(7.8, 10.3)
        arrow.lineTo(12, 14.6)
        arrow.lineTo(16.2, 10.3)
        p.drawPath(arrow)

    @staticmethod
    def _open(p: QPainter) -> None:
        path = QPainterPath()
        path.moveTo(4.5, 14.5)
        path.lineTo(4.5, 19.5)
        path.lineTo(19.5, 19.5)
        path.lineTo(19.5, 14.5)
        p.drawPath(path)
        p.drawLine(QPointF(12, 15), QPointF(12, 4))
        arrow = QPainterPath()
        arrow.moveTo(7.8, 8.2)
        arrow.lineTo(12, 3.9)
        arrow.lineTo(16.2, 8.2)
        p.drawPath(arrow)

    @staticmethod
    def _monitor(p: QPainter) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(3.5, 4.5, 17, 11.5), 2, 2)
        p.drawPath(path)
        p.drawLine(QPointF(12, 16), QPointF(12, 19.5))
        p.drawLine(QPointF(8.5, 19.5), QPointF(15.5, 19.5))

    @staticmethod
    def _target(p: QPainter) -> None:
        p.drawEllipse(QPointF(12, 12), 8.0, 8.0)
        path = QPainterPath()
        path.addEllipse(QPointF(12, 12), 2.4, 2.4)
        p.fillPath(path, p.pen().brush())

    @staticmethod
    def _power(p: QPainter) -> None:
        rect = QRectF(4.5, 4.5, 15, 15)
        p.drawArc(rect, int(-55 * 16), int(290 * 16))
        p.drawLine(QPointF(12, 3), QPointF(12, 11))

    @staticmethod
    def _refresh(p: QPainter) -> None:
        rect = QRectF(5, 5, 14, 14)
        p.drawArc(rect, int(35 * 16), int(280 * 16))
        arrow = QPainterPath()
        arrow.moveTo(14.5, 3.2)
        arrow.lineTo(18.8, 6.4)
        arrow.lineTo(14.8, 9.4)
        p.drawPath(arrow)

    @staticmethod
    def _repeat(p: QPainter) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(5.5, 7, 13, 10), 3.2, 3.2)
        p.drawPath(path)
        top = QPainterPath()
        top.moveTo(11.5, 4.4)
        top.lineTo(14.4, 7)
        top.lineTo(11.5, 9.6)
        p.drawPath(top)
        bottom = QPainterPath()
        bottom.moveTo(12.5, 14.4)
        bottom.lineTo(9.6, 17)
        bottom.lineTo(12.5, 19.6)
        p.drawPath(bottom)

    @staticmethod
    def _volume(p: QPainter) -> None:
        path = QPainterPath()
        path.moveTo(4.5, 9.5)
        path.lineTo(8, 9.5)
        path.lineTo(12.5, 5.5)
        path.lineTo(12.5, 18.5)
        path.lineTo(8, 14.5)
        path.lineTo(4.5, 14.5)
        path.closeSubpath()
        p.drawPath(path)
        p.drawArc(QRectF(12.5, 7.5, 7, 9), int(-70 * 16), int(140 * 16))

    @staticmethod
    def _mute(p: QPainter) -> None:
        path = QPainterPath()
        path.moveTo(4.5, 9.5)
        path.lineTo(8, 9.5)
        path.lineTo(12.5, 5.5)
        path.lineTo(12.5, 18.5)
        path.lineTo(8, 14.5)
        path.lineTo(4.5, 14.5)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(15.5, 9.5), QPointF(20.5, 14.5))
        p.drawLine(QPointF(20.5, 9.5), QPointF(15.5, 14.5))

    @staticmethod
    def _palette(p: QPainter) -> None:
        path = QPainterPath()
        path.moveTo(12, 3.5)
        path.lineTo(18, 11)
        path.cubicTo(20.5, 15, 17, 20, 12, 20)
        path.cubicTo(7, 20, 3.5, 15, 6, 11)
        path.closeSubpath()
        p.drawPath(path)

    @staticmethod
    def _text(p: QPainter) -> None:
        p.drawLine(QPointF(5.5, 6), QPointF(18.5, 6))
        p.drawLine(QPointF(12, 6), QPointF(12, 18.5))

    @staticmethod
    def _list(p: QPainter) -> None:
        for y in (7.0, 12.0, 17.0):
            p.drawLine(QPointF(9, y), QPointF(19, y))
            dot = QPainterPath()
            dot.addEllipse(QPointF(5.2, y), 1.3, 1.3)
            p.fillPath(dot, p.pen().brush())

    @staticmethod
    def _image(p: QPainter) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(3.5, 5, 17, 14), 2, 2)
        p.drawPath(path)
        inner = QPainterPath()
        inner.moveTo(5.5, 17)
        inner.lineTo(10, 11)
        inner.lineTo(13.5, 15)
        inner.lineTo(16, 12.5)
        inner.lineTo(18.5, 17)
        p.drawPath(inner)

    @staticmethod
    def _video(p: QPainter) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(3.5, 6, 12.5, 12), 2, 2)
        p.drawPath(path)
        tri = QPainterPath()
        tri.moveTo(20.5, 7.5)
        tri.lineTo(20.5, 16.5)
        tri.lineTo(17.2, 13.6)
        tri.lineTo(17.2, 10.4)
        tri.closeSubpath()
        p.drawPath(tri)

    # -- factory ------------------------------------------------------------ #

    @classmethod
    def get(cls, name: str, colour: str = CLR_TEXT, size: int = 18) -> QIcon:
        key = (name, colour, size)
        cached = cls._cache.get(key)
        if cached is not None:
            return cached

        draw: Optional[Callable] = getattr(cls, "_" + name, None)
        if draw is None:
            return QIcon()

        scale = 2  # render at 2x so the icon stays crisp on HiDPI screens
        pixmap = QPixmap(size * scale, size * scale)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.scale(size * scale / 24.0, size * scale / 24.0)
        pen = QPen(QColor(colour))
        pen.setWidthF(1.9)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        draw(painter)
        painter.end()

        pixmap.setDevicePixelRatio(float(scale))
        icon = QIcon(pixmap)
        cls._cache[key] = icon
        return icon


def icon_button(name: str, tooltip: str, colour: str = CLR_TEXT, size: int = 18) -> QPushButton:
    button = QPushButton()
    button.setIcon(Icons.get(name, colour, size))
    button.setIconSize(QSize(size, size))
    button.setToolTip(tooltip)
    return button


# --------------------------------------------------------------------------- #
# Stylesheet
# --------------------------------------------------------------------------- #

STYLESHEET = f"""
QWidget {{
    background-color: {CLR_BG};
    color: {CLR_TEXT};
    font-family: "Segoe UI", "Noto Sans Georgian", sans-serif;
    font-size: 13px;
}}
QTabWidget::pane {{ border: none; background: {CLR_BG}; }}
QTabBar::tab {{
    background: transparent;
    color: {CLR_MUTED};
    padding: 8px 18px;
    margin-right: 2px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}}
QTabBar::tab:hover {{ color: {CLR_TEXT}; }}
QTabBar::tab:selected {{
    color: {CLR_TEXT};
    border-bottom: 2px solid {CLR_ACCENT};
}}

QFrame#card, QFrame#bar {{
    background: {CLR_CARD};
    border: 1px solid {CLR_LINE};
    border-radius: 10px;
}}
QLabel#cardTitle {{ font-size: 14px; font-weight: 700; }}
QLabel#cardHint {{ color: {CLR_MUTED}; }}
QLabel#sectionTitle {{
    color: {CLR_MUTED};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.4px;
}}
QLabel#brand {{ font-size: 13px; font-weight: 800; letter-spacing: 1.2px; }}
QLabel {{ background: transparent; }}

QFrame#dropZone {{
    background: {CLR_INPUT};
    border: 1px dashed {CLR_LINE};
    border-radius: 9px;
}}
QFrame#dropZone[dragActive="true"] {{
    background: {CLR_HOVER};
    border: 1px dashed {CLR_ACCENT};
}}
QFrame#dropZone[loaded="true"] {{ border: 1px solid {CLR_LINE}; }}

QPushButton {{
    background: {CLR_INPUT};
    border: 1px solid {CLR_LINE};
    border-radius: 7px;
    padding: 6px 12px;
}}
QPushButton:hover {{ background: {CLR_HOVER}; border-color: #3b4657; }}
QPushButton:pressed {{ background: #11151b; }}
QPushButton:disabled {{ color: #4d5769; border-color: #232a34; }}
QPushButton:checked {{
    background: rgba(90, 169, 240, 0.16);
    border-color: {CLR_ACCENT};
}}
QPushButton#primary {{
    background: {CLR_ACCENT};
    color: #0b0e13;
    font-weight: 700;
    border: 1px solid {CLR_ACCENT};
}}
QPushButton#primary:hover {{ background: #74b8f5; }}
QPushButton#danger {{
    background: transparent;
    color: {CLR_DANGER};
    border: 1px solid rgba(232, 97, 95, 0.45);
    font-weight: 700;
}}
QPushButton#danger:hover {{ background: rgba(232, 97, 95, 0.12); }}
QPushButton#ghost {{ background: transparent; border: 1px solid transparent; padding: 5px; }}
QPushButton#ghost:hover {{ background: {CLR_HOVER}; }}

QComboBox, QSpinBox, QLineEdit, QFontComboBox {{
    background: {CLR_INPUT};
    border: 1px solid {CLR_LINE};
    border-radius: 7px;
    padding: 6px 9px;
    selection-background-color: {CLR_ACCENT};
    selection-color: #0b0e13;
}}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border-color: {CLR_ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {CLR_CARD};
    border: 1px solid {CLR_LINE};
    selection-background-color: {CLR_ACCENT};
    selection-color: #0b0e13;
    outline: none;
}}
QSpinBox:disabled, QComboBox:disabled {{ color: #4d5769; background: #101419; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 14px; border: none; background: transparent; }}

QListWidget {{
    background: {CLR_INPUT};
    border: 1px solid {CLR_LINE};
    border-radius: 8px;
    outline: none;
    padding: 3px;
}}
QListWidget::item {{ padding: 4px 6px; border-radius: 5px; color: {CLR_MUTED}; }}
QListWidget::item:hover {{ background: {CLR_HOVER}; color: {CLR_TEXT}; }}
QListWidget::item:selected {{ background: rgba(90, 169, 240, 0.18); color: {CLR_TEXT}; }}

QSlider::groove:horizontal {{ height: 4px; background: #262e3a; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {CLR_TEXT}; width: 12px; height: 12px;
    margin: -5px 0; border-radius: 6px;
}}
QSlider::sub-page:horizontal {{ background: {CLR_ACCENT}; border-radius: 2px; }}

QCheckBox {{ background: transparent; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid {CLR_LINE}; background: {CLR_INPUT};
}}
QCheckBox::indicator:checked {{ background: {CLR_ACCENT}; border-color: {CLR_ACCENT}; }}

QStatusBar {{ background: {CLR_CARD}; color: {CLR_MUTED}; border-top: 1px solid {CLR_LINE}; }}
QToolTip {{
    background: {CLR_CARD}; color: {CLR_TEXT};
    border: 1px solid {CLR_LINE}; padding: 5px; border-radius: 4px;
}}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #303a49; border-radius: 4px; min-height: 26px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


# --------------------------------------------------------------------------- #
# Media engine
# --------------------------------------------------------------------------- #

class MediaEngine(QObject):
    """
    Wrapper around QMediaPlayer that handles the awkward bits:

    * looping, on or off (native ``setLoops`` on Qt >= 6.4, manual restart otherwise),
    * swapping the source while something is already playing, without crashing,
    * audio output (Qt 6 requires an explicit QAudioOutput).
    """

    errorOccurred = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._audio.setVolume(0.8)

        self._loop = True  # repeat is ON by default, as a stage background should be
        self._has_set_loops = hasattr(self._player, "setLoops")
        self._apply_loop_mode()

        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._player.errorOccurred.connect(self._on_error)

    @property
    def player(self) -> QMediaPlayer:
        return self._player

    def load(self, path: str, autoplay: bool = True) -> None:
        """
        Load a video file.

        Clearing the source first releases the previous decoder and file handle,
        which is what makes back-to-back loads smooth instead of crashy.
        """
        self._player.stop()
        self._player.setSource(QUrl())
        self._player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
        self._apply_loop_mode()
        if autoplay:
            self._player.play()

    def clear(self) -> None:
        self._player.stop()
        self._player.setSource(QUrl())

    def play(self) -> None:
        if not self._player.source().isEmpty():
            self._player.play()

    def pause(self) -> None:
        self._player.pause()

    def stop(self) -> None:
        self._player.stop()

    def set_volume(self, percent: int) -> None:
        self._audio.setVolume(max(0, min(100, percent)) / 100.0)

    def set_muted(self, muted: bool) -> None:
        self._audio.setMuted(muted)

    def set_loop(self, enabled: bool) -> None:
        self._loop = enabled
        self._apply_loop_mode()

    def is_looping(self) -> bool:
        return self._loop

    # -- internals ---------------------------------------------------------- #

    def _apply_loop_mode(self) -> None:
        """Use Qt's own looping when available; _on_media_status_changed is the fallback."""
        if not self._has_set_loops:
            return
        value = self._infinite_loop_value() if self._loop else 1
        if value is None:
            self._has_set_loops = False
            return
        try:
            self._player.setLoops(value)
        except (TypeError, ValueError):  # very old bindings
            self._has_set_loops = False

    @staticmethod
    def _infinite_loop_value():
        loops = getattr(QMediaPlayer, "Loops", None)
        if loops is not None and hasattr(loops, "Infinite"):
            return loops.Infinite
        return getattr(QMediaPlayer, "Infinite", None)

    @staticmethod
    def _end_of_media_value():
        status = getattr(QMediaPlayer, "MediaStatus", None)
        if status is not None and hasattr(status, "EndOfMedia"):
            return status.EndOfMedia
        return getattr(QMediaPlayer, "EndOfMedia", None)

    def _on_media_status_changed(self, status) -> None:
        if self._has_set_loops or not self._loop:
            return
        if status == self._end_of_media_value():
            self._player.setPosition(0)
            self._player.play()

    def _on_error(self, _error, error_string: str) -> None:
        if error_string:
            self.errorOccurred.emit(error_string)


# --------------------------------------------------------------------------- #
# Image rendering widget
# --------------------------------------------------------------------------- #

class ImageView(QWidget):
    """Paints a pixmap on a black background, honouring the current ScaleMode."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._mode = ScaleMode.FIT

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def clear(self) -> None:
        self._pixmap = QPixmap()
        self.update()

    def set_scale_mode(self, mode: ScaleMode) -> None:
        self._mode = mode
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("black"))
        if self._pixmap.isNull():
            return

        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        target = QRectF(self.rect())
        source = QRectF(self._pixmap.rect())

        if self._mode is ScaleMode.FIT:
            scale = min(target.width() / source.width(), target.height() / source.height())
            width, height = source.width() * scale, source.height() * scale
            target = QRectF((target.width() - width) / 2, (target.height() - height) / 2, width, height)
        elif self._mode is ScaleMode.CROP:
            scale = max(target.width() / source.width(), target.height() / source.height())
            visible_w, visible_h = target.width() / scale, target.height() / scale
            source = QRectF(
                (source.width() - visible_w) / 2,
                (source.height() - visible_h) / 2,
                visible_w,
                visible_h,
            )
        painter.drawPixmap(target, self._pixmap, source)


# --------------------------------------------------------------------------- #
# Output windows
# --------------------------------------------------------------------------- #

class BaseOutputWindow(QWidget):
    """
    Frameless, borderless window shown on a stage monitor.

    Qt.Tool is what keeps the taskbar clean: a Tool window gets no taskbar
    button and no Alt+Tab entry, so opening all three outputs still leaves the
    operator with a single "Stage Display Controller" button.

    The audience must never see chrome, so there is no title bar and no close
    button, and window-manager close requests (Alt+F4) are ignored. The operator
    closes outputs from the Control Panel - or with Escape, an invisible safety
    valve that is handy when rehearsing on a single monitor.
    """

    closedByUser = Signal()

    BASE_FLAGS = Qt.Window | Qt.FramelessWindowHint | Qt.Tool

    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, self.BASE_FLAGS)
        self.setWindowTitle(title)
        self.setCursor(Qt.BlankCursor)
        self.setStyleSheet("background-color: black;")
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._allow_close = False
        self._screen: Optional[QScreen] = None
        self._geometry: Optional[QRect] = None

    # -- placement ---------------------------------------------------------- #

    def show_with_geometry(self, screen: QScreen, rect: Optional[QRect] = None) -> None:
        """
        Place the window on `screen`.

        `rect` is an absolute desktop rectangle; pass None for fullscreen on the
        whole monitor. A custom rectangle is what makes LED walls work when
        Windows reports a resolution that differs from the mapped canvas.
        """
        self._screen = screen
        self._geometry = rect
        target = rect if rect is not None else screen.geometry()

        # Leaving fullscreen first makes a cross-monitor move reliable on Windows.
        if self.isFullScreen() or self.isVisible():
            self.showNormal()
        self.setGeometry(target)
        if not self.isVisible():
            self.show()

        handle = self.windowHandle()
        if handle is not None:
            handle.setScreen(screen)

        self.setGeometry(target)
        if rect is None:
            self.showFullScreen()
        self.raise_()

    def set_always_on_top(self, on_top: bool) -> None:
        flags = self.BASE_FLAGS
        if on_top:
            flags |= Qt.WindowStaysOnTopHint
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible and self._screen is not None:
            self.show_with_geometry(self._screen, self._geometry)

    def force_close(self) -> None:
        """The only sanctioned way to close a stage window."""
        self._allow_close = True
        self.close()
        self._allow_close = False

    # -- event handling ----------------------------------------------------- #

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._allow_close:
            event.accept()
        else:
            event.ignore()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        # Swallow every key, so a stray keyboard on stage cannot disturb output.
        if event.key() == Qt.Key_Escape:
            self.force_close()
            self.closedByUser.emit()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        event.accept()

    # -- interface implemented by subclasses -------------------------------- #

    def load_media(self, path: str) -> bool:
        raise NotImplementedError

    def clear_output(self) -> None:
        raise NotImplementedError

    def set_scale_mode(self, mode: ScaleMode) -> None:
        raise NotImplementedError


class StandardOutputWindow(BaseOutputWindow):
    """
    Main Stage / Side Screens output.

    A QStackedLayout swaps between the image view and the QVideoWidget, so only
    one of them is ever on screen; that avoids flashes when switching media.
    """

    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(title, parent)

        self.engine = MediaEngine(self)
        self._scale_mode = ScaleMode.FIT

        self._image_view = ImageView(self)
        self._video_widget = QVideoWidget(self)
        self._video_widget.setStyleSheet("background-color: black;")
        self.engine.player.setVideoOutput(self._video_widget)

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.setStackingMode(QStackedLayout.StackingMode.StackOne)
        self._stack.addWidget(self._image_view)    # index 0
        self._stack.addWidget(self._video_widget)  # index 1
        self._stack.setCurrentIndex(0)

        self.set_scale_mode(self._scale_mode)

    def load_media(self, path: str) -> bool:
        if is_image(path):
            pixmap = QPixmap(path)
            if pixmap.isNull():
                return False
            self.engine.clear()  # release any playing video first
            self._image_view.set_pixmap(pixmap)
            self._stack.setCurrentIndex(0)
            return True

        if is_video(path):
            self._image_view.clear()
            self._stack.setCurrentIndex(1)
            self.engine.load(path)
            return True

        return False

    def clear_output(self) -> None:
        self.engine.clear()
        self._image_view.clear()
        self._stack.setCurrentIndex(0)

    def set_scale_mode(self, mode: ScaleMode) -> None:
        self._scale_mode = mode
        self._image_view.set_scale_mode(mode)
        self._video_widget.setAspectRatioMode(mode.aspect_mode)


class TopOutputWindow(BaseOutputWindow):
    """
    Top / horizontal LED strip output.

    Implemented with a QGraphicsScene so the marquee text can be composited over
    a live QGraphicsVideoItem (not possible over a plain QVideoWidget).

    Scene layers (Z value):
        0   background colour rectangle
        1   background image OR background video
        10  marquee text
    """

    MARQUEE_INTERVAL_MS = 16  # ~60 fps

    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(title, parent)

        self.engine = MediaEngine(self)
        self._scale_mode = ScaleMode.CROP
        self._bg_color = QColor("black")

        self._scene = QGraphicsScene(self)
        self._view = QGraphicsView(self._scene, self)
        self._view.setFrameShape(QFrame.Shape.NoFrame)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setRenderHints(
            QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing
        )
        self._view.setBackgroundBrush(QBrush(QColor("black")))
        self._view.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._view.setInteractive(False)

        # The window's own resizeEvent fires BEFORE the layout has resized the
        # view, so reading the viewport there yields a stale (tiny) size and the
        # whole scene ends up laid out for the wrong geometry. Watching the
        # viewport itself is the only reliable trigger.
        self._view.viewport().installEventFilter(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

        self._bg_item = self._scene.addRect(QRectF(0, 0, 1, 1), QPen(Qt.NoPen), QBrush(self._bg_color))
        self._bg_item.setZValue(0)

        self._pixmap_item = QGraphicsPixmapItem()
        self._pixmap_item.setTransformationMode(Qt.SmoothTransformation)
        self._pixmap_item.setZValue(1)
        self._pixmap_item.setVisible(False)
        self._scene.addItem(self._pixmap_item)

        self._video_item = QGraphicsVideoItem()
        self._video_item.setZValue(1)
        self._video_item.setVisible(False)
        self._scene.addItem(self._video_item)
        self.engine.player.setVideoOutput(self._video_item)
        self._video_item.nativeSizeChanged.connect(lambda _size: self._layout_video())

        self._text_item = QGraphicsSimpleTextItem("")
        self._text_item.setZValue(10)
        self._text_item.setVisible(False)
        self._scene.addItem(self._text_item)

        self._marquee_text = ""
        self._marquee_color = QColor("white")
        self._marquee_font_size = 64
        self._marquee_family = ""
        self._marquee_speed = 180  # pixels per second
        self._marquee_timer = QTimer(self)
        self._marquee_timer.setInterval(self.MARQUEE_INTERVAL_MS)
        self._marquee_timer.timeout.connect(self._advance_marquee)

        self._apply_marquee_style()

    # -- background --------------------------------------------------------- #

    def load_media(self, path: str) -> bool:
        if is_image(path):
            pixmap = QPixmap(path)
            if pixmap.isNull():
                return False
            self.engine.clear()
            self._video_item.setVisible(False)
            self._pixmap_item.setPixmap(pixmap)
            self._pixmap_item.setVisible(True)
            self._layout_pixmap()
            return True

        if is_video(path):
            self._pixmap_item.setVisible(False)
            self._pixmap_item.setPixmap(QPixmap())
            self._video_item.setVisible(True)
            self.engine.load(path)
            self._layout_video()
            return True

        return False

    def set_background_color(self, color: QColor) -> None:
        """Solid-colour background; also clears any image or video."""
        self._bg_color = color
        self._bg_item.setBrush(QBrush(color))
        self.engine.clear()
        self._pixmap_item.setVisible(False)
        self._pixmap_item.setPixmap(QPixmap())
        self._video_item.setVisible(False)

    def clear_output(self) -> None:
        self.engine.clear()
        self._pixmap_item.setVisible(False)
        self._pixmap_item.setPixmap(QPixmap())
        self._video_item.setVisible(False)

    def set_scale_mode(self, mode: ScaleMode) -> None:
        self._scale_mode = mode
        self._layout_pixmap()
        self._layout_video()

    # -- marquee ------------------------------------------------------------ #

    def set_marquee_text(self, text: str) -> None:
        self._marquee_text = text
        self._text_item.setText(text)
        self._apply_marquee_style()
        if self._marquee_timer.isActive():
            self._reset_marquee_position()

    def set_marquee_font_size(self, size: int) -> None:
        self._marquee_font_size = max(8, size)
        self._apply_marquee_style()

    def set_marquee_family(self, family: str) -> None:
        self._marquee_family = family
        self._apply_marquee_style()

    def set_marquee_color(self, color: QColor) -> None:
        self._marquee_color = color
        self._apply_marquee_style()

    def set_marquee_speed(self, pixels_per_second: int) -> None:
        self._marquee_speed = max(10, pixels_per_second)

    def start_marquee(self) -> None:
        if not self._marquee_text.strip():
            return
        # Refresh the scene rect first: the text is parked just off the right
        # edge, so a stale width would make it start mid-screen.
        self._relayout()
        self._text_item.setVisible(True)
        self._reset_marquee_position()
        self._marquee_timer.start()

    def stop_marquee(self) -> None:
        # Hide the text as well, so the audience never sees a frozen line.
        self._marquee_timer.stop()
        self._text_item.setVisible(False)

    def is_marquee_running(self) -> bool:
        return self._marquee_timer.isActive()

    def _apply_marquee_style(self) -> None:
        font = QFont()
        if self._marquee_family:
            font.setFamily(self._marquee_family)
        font.setPixelSize(max(8, self._marquee_font_size))
        font.setBold(True)
        self._text_item.setFont(font)
        self._text_item.setBrush(QBrush(self._marquee_color))
        self._text_item.setPen(QPen(Qt.NoPen))
        self._position_marquee_vertically()

    def _position_marquee_vertically(self) -> None:
        scene_rect = self._scene.sceneRect()
        text_rect = self._text_item.boundingRect()
        y = (scene_rect.height() - text_rect.height()) / 2.0
        self._text_item.setPos(QPointF(self._text_item.pos().x(), y))

    def _reset_marquee_position(self) -> None:
        self._text_item.setPos(QPointF(self._scene.sceneRect().width(), self._text_item.pos().y()))
        self._position_marquee_vertically()

    @Slot()
    def _advance_marquee(self) -> None:
        step = self._marquee_speed * (self.MARQUEE_INTERVAL_MS / 1000.0)
        x = self._text_item.pos().x() - step
        if x + self._text_item.boundingRect().width() < 0:
            x = self._scene.sceneRect().width()  # wrap back around to the right edge
        self._text_item.setPos(QPointF(x, self._text_item.pos().y()))

    # -- layout ------------------------------------------------------------- #

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        """Re-layout the scene whenever the view's viewport actually resizes."""
        if watched is self._view.viewport() and event.type() == QEvent.Resize:
            self._relayout()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        size = self._view.viewport().size()
        rect = QRectF(0, 0, size.width(), size.height())
        self._scene.setSceneRect(rect)
        self._bg_item.setRect(rect)
        self._layout_pixmap()
        self._layout_video()
        self._position_marquee_vertically()

    def _layout_pixmap(self) -> None:
        pixmap = self._pixmap_item.pixmap()
        if pixmap.isNull():
            return
        rect = self._scene.sceneRect()
        pw, ph = pixmap.width(), pixmap.height()
        if pw == 0 or ph == 0 or rect.isEmpty():
            return

        if self._scale_mode is ScaleMode.STRETCH:
            sx, sy = rect.width() / pw, rect.height() / ph
        elif self._scale_mode is ScaleMode.FIT:
            sx = sy = min(rect.width() / pw, rect.height() / ph)
        else:  # CROP - cover the screen; the viewport clips the overflow
            sx = sy = max(rect.width() / pw, rect.height() / ph)

        self._pixmap_item.setTransform(QTransform().scale(sx, sy))
        self._pixmap_item.setPos((rect.width() - pw * sx) / 2.0, (rect.height() - ph * sy) / 2.0)

    def _layout_video(self) -> None:
        rect = self._scene.sceneRect()
        if rect.isEmpty():
            return
        native = self._video_item.nativeSize()

        if self._scale_mode is ScaleMode.CROP and not native.isEmpty():
            scale = max(rect.width() / native.width(), rect.height() / native.height())
            size = QSizeF(native.width() * scale, native.height() * scale)
            self._video_item.setAspectRatioMode(Qt.IgnoreAspectRatio)
            self._video_item.setSize(size)
            self._video_item.setPos(
                (rect.width() - size.width()) / 2.0,
                (rect.height() - size.height()) / 2.0,
            )
            return

        self._video_item.setAspectRatioMode(
            Qt.IgnoreAspectRatio if self._scale_mode is ScaleMode.STRETCH else Qt.KeepAspectRatio
        )
        self._video_item.setSize(QSizeF(rect.width(), rect.height()))
        self._video_item.setPos(0, 0)


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

    THUMB = QSize(230, 118)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(150)
        self.setMaximumHeight(170)
        self.setProperty("dragActive", "false")
        self.setProperty("loaded", "false")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        self.thumb = QLabel()
        self.thumb.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.thumb, 1)

        self.caption = QLabel()
        self.caption.setObjectName("cardHint")
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setWordWrap(True)
        layout.addWidget(self.caption)

        self._show_empty()

    # -- appearance --------------------------------------------------------- #

    def _restyle(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)

    def _show_empty(self) -> None:
        self.thumb.setPixmap(Icons.get("plus", CLR_LINE, 30).pixmap(30, 30))
        self.caption.setText("drop media here  ·  or click to browse")
        self.setProperty("loaded", "false")
        self._restyle()

    def set_file(self, path: str) -> None:
        if is_image(path):
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self.thumb.setPixmap(
                    pixmap.scaled(self.THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
        else:
            self.thumb.setPixmap(Icons.get("video", CLR_ACCENT, 40).pixmap(40, 40))
        self.caption.setText(os.path.basename(path))
        self.caption.setToolTip(path)
        self.setProperty("loaded", "true")
        self._restyle()

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

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setIconSize(QSize(38, 22))
        self.setUniformItemSizes(True)
        self.setMinimumHeight(104)
        self.setMaximumHeight(150)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.itemClicked.connect(self._on_item_clicked)

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
        if added and announce:
            self.filesAdded.emit(added)
        return added

    @staticmethod
    def _thumb_for(path: str) -> QIcon:
        if is_image(path):
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                return QIcon(pixmap.scaled(QSize(38, 22), Qt.KeepAspectRatioByExpanding,
                                           Qt.SmoothTransformation))
            return Icons.get("image", CLR_MUTED, 16)
        return Icons.get("video", CLR_MUTED, 16)

    def remove_current(self) -> None:
        row = self.currentRow()
        if row >= 0:
            self.takeItem(row)

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
            active = item.data(Qt.UserRole) == path
            font = item.font()
            font.setBold(active)
            item.setFont(font)
            item.setForeground(QColor(CLR_ACCENT if active else CLR_MUTED))
            if active:
                self.setCurrentRow(row)

    # -- drag & drop -------------------------------------------------------- #

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if urls_to_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if urls_to_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = urls_to_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        self.add_paths(paths)
        event.acceptProposedAction()


# --------------------------------------------------------------------------- #
# Output card (live controls for one output)
# --------------------------------------------------------------------------- #

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

    def __init__(self, title: str, subtitle: str, default_mode: ScaleMode,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._last_dir = ""
        self._path = ""

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(14, 12, 14, 12)
        self.root.setSpacing(9)

        # --- header -------------------------------------------------------- #
        header = QHBoxLayout()
        header.setSpacing(8)
        glyph = QLabel()
        glyph.setPixmap(Icons.get("monitor", CLR_ACCENT, 17).pixmap(17, 17))
        header.addWidget(glyph)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        name = QLabel(title)
        name.setObjectName("cardTitle")
        hint = QLabel(subtitle)
        hint.setObjectName("cardHint")
        title_box.addWidget(name)
        title_box.addWidget(hint)
        header.addLayout(title_box)
        header.addStretch(1)

        self.state_dot = QLabel("●")
        header.addWidget(self.state_dot)
        self.root.addLayout(header)

        # --- preview / drop zone ------------------------------------------- #
        self.zone = DropZone()
        self.zone.filesDropped.connect(self._on_files_chosen)
        self.zone.browseRequested.connect(self._on_browse)
        self.root.addWidget(self.zone)

        # --- scaling + repeat ---------------------------------------------- #
        options = QHBoxLayout()
        options.setSpacing(6)
        self.scale_combo = QComboBox()
        for mode in ScaleMode:
            self.scale_combo.addItem(mode.value, mode)
        self.scale_combo.setCurrentIndex(list(ScaleMode).index(default_mode))
        self.scale_combo.setToolTip("How media is fitted to this screen")
        self.scale_combo.currentIndexChanged.connect(
            lambda _i: self.scaleModeChanged.emit(self.scale_combo.currentData())
        )
        options.addWidget(self.scale_combo, 1)

        self.repeat_btn = icon_button("repeat", "Repeat / loop video", CLR_TEXT)
        self.repeat_btn.setCheckable(True)
        self.repeat_btn.setChecked(True)  # repeat is ON by default
        self.repeat_btn.toggled.connect(self._on_repeat_toggled)
        options.addWidget(self.repeat_btn)

        self.mute_btn = icon_button("volume", "Mute audio", CLR_TEXT)
        self.mute_btn.setCheckable(True)
        self.mute_btn.toggled.connect(self._on_mute_toggled)
        options.addWidget(self.mute_btn)
        self.root.addLayout(options)

        # --- transport ----------------------------------------------------- #
        transport = QHBoxLayout()
        transport.setSpacing(6)
        for icon_name, tip, signal in (
            ("prev", "Previous item in the playlist", None),
            ("play", "Play", self.playRequested),
            ("pause", "Pause", self.pauseRequested),
            ("stop", "Stop (rewind to first frame)", self.stopRequested),
            ("next", "Next item in the playlist", None),
        ):
            button = icon_button(icon_name, tip)
            button.setMinimumHeight(32)
            if signal is not None:
                button.clicked.connect(signal.emit)
            transport.addWidget(button, 1)
            if icon_name == "prev":
                self.prev_btn = button
            elif icon_name == "next":
                self.next_btn = button
        self.root.addLayout(transport)

        # --- volume + blackout --------------------------------------------- #
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setToolTip("Playback volume")
        self.volume_slider.valueChanged.connect(self.volumeChanged.emit)
        bottom.addWidget(self.volume_slider, 1)

        black = icon_button("power", "Blackout this screen", CLR_DANGER)
        black.setObjectName("ghost")
        black.clicked.connect(self._on_clear)
        bottom.addWidget(black)
        self.root.addLayout(bottom)

        # --- playlist ------------------------------------------------------ #
        queue_header = QHBoxLayout()
        queue_header.setSpacing(4)
        queue_title = QLabel("PLAYLIST")
        queue_title.setObjectName("sectionTitle")
        queue_header.addWidget(queue_title)
        queue_header.addStretch(1)

        add_btn = icon_button("plus", "Add files to the playlist", CLR_MUTED, 15)
        add_btn.setObjectName("ghost")
        add_btn.clicked.connect(self._on_add_to_queue)
        queue_header.addWidget(add_btn)

        remove_btn = icon_button("minus", "Remove the selected entry", CLR_MUTED, 15)
        remove_btn.setObjectName("ghost")
        remove_btn.clicked.connect(lambda: self.playlist.remove_current())
        queue_header.addWidget(remove_btn)

        clear_btn = icon_button("trash", "Empty the playlist", CLR_MUTED, 15)
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
        colour = CLR_OK if is_open else CLR_WARN
        self.state_dot.setStyleSheet(f"color: {colour}; font-size: 13px;")
        self.state_dot.setToolTip("Output window is OPEN" if is_open else "Output window is CLOSED")

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
        paths, _ = QFileDialog.getOpenFileNames(self, "Select images or videos", start, MEDIA_FILTER)
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
        paths, _ = QFileDialog.getOpenFileNames(self, "Add to playlist", start, MEDIA_FILTER)
        if paths:
            self._last_dir = os.path.dirname(paths[0])
            self.playlist.add_paths([os.path.normpath(p) for p in paths])

    @Slot()
    def _on_clear_queue(self) -> None:
        if self.playlist.count() == 0:
            return
        answer = QMessageBox.question(self, "Empty playlist", "Remove every entry from this playlist?")
        if answer == QMessageBox.Yes:
            self.playlist.clear_all()

    @Slot()
    def _on_clear(self) -> None:
        self.reset_file()
        self.clearRequested.emit()

    @Slot(bool)
    def _on_repeat_toggled(self, enabled: bool) -> None:
        self.repeat_btn.setIcon(Icons.get("repeat", CLR_ACCENT if enabled else CLR_MUTED))
        self.repeat_btn.setToolTip("Repeat is ON" if enabled else "Repeat is OFF - plays once")
        self.repeatChanged.emit(enabled)

    @Slot(bool)
    def _on_mute_toggled(self, muted: bool) -> None:
        self.mute_btn.setIcon(Icons.get("mute" if muted else "volume",
                                        CLR_DANGER if muted else CLR_TEXT))
        self.mute_btn.setToolTip("Audio muted" if muted else "Mute audio")
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

        section = QHBoxLayout()
        section.setSpacing(6)
        glyph = QLabel()
        glyph.setPixmap(Icons.get("text", CLR_MUTED, 14).pixmap(14, 14))
        section.addWidget(glyph)
        label = QLabel("MARQUEE")
        label.setObjectName("sectionTitle")
        section.addWidget(label)
        section.addStretch(1)

        bg_btn = icon_button("palette", "Solid colour background for this screen", CLR_MUTED, 15)
        bg_btn.setObjectName("ghost")
        bg_btn.clicked.connect(self._pick_background)
        section.addWidget(bg_btn)
        self.bg_preview = QLabel()
        self.bg_preview.setFixedSize(16, 16)
        section.addWidget(self.bg_preview)
        self.root.addLayout(section)
        self._update_swatch(self.bg_preview, self._bg_color)

        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText("Text to scroll across the strip…")
        self.text_edit.textChanged.connect(self.marqueeTextChanged.emit)
        self.root.addWidget(self.text_edit)

        font_row = QHBoxLayout()
        font_row.setSpacing(6)
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont("Segoe UI"))
        self.font_combo.setToolTip("Marquee typeface")
        self.font_combo.currentFontChanged.connect(
            lambda font: self.marqueeFamilyChanged.emit(font.family())
        )
        font_row.addWidget(self.font_combo, 1)

        self.size_spin = QSpinBox()
        self.size_spin.setRange(8, 400)
        self.size_spin.setValue(96)
        self.size_spin.setSuffix(" px")
        self.size_spin.setToolTip("Text height in pixels - match it to the strip height")
        self.size_spin.valueChanged.connect(self.marqueeFontSizeChanged.emit)
        font_row.addWidget(self.size_spin)

        colour_btn = icon_button("palette", "Marquee text colour", CLR_MUTED, 15)
        colour_btn.setObjectName("ghost")
        colour_btn.clicked.connect(self._pick_text_colour)
        font_row.addWidget(colour_btn)
        self.text_preview = QLabel()
        self.text_preview.setFixedSize(16, 16)
        font_row.addWidget(self.text_preview)
        self.root.addLayout(font_row)
        self._update_swatch(self.text_preview, self._text_color)

        speed_row = QHBoxLayout()
        speed_row.setSpacing(8)
        speed_caption = QLabel("Speed")
        speed_caption.setObjectName("cardHint")
        speed_row.addWidget(speed_caption)
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(20, 800)
        self.speed_slider.setValue(180)
        self.speed_slider.valueChanged.connect(self._on_speed)
        speed_row.addWidget(self.speed_slider, 1)
        self.speed_label = QLabel("180 px/s")
        self.speed_label.setObjectName("cardHint")
        self.speed_label.setMinimumWidth(58)
        speed_row.addWidget(self.speed_label)
        self.root.addLayout(speed_row)

        marquee_buttons = QHBoxLayout()
        marquee_buttons.setSpacing(6)
        start = QPushButton("  Start scrolling")
        start.setObjectName("primary")
        start.setIcon(Icons.get("play", "#0b0e13"))
        start.clicked.connect(self.marqueeStart.emit)
        stop = QPushButton("  Stop")
        stop.setIcon(Icons.get("stop", CLR_TEXT))
        stop.clicked.connect(self.marqueeStop.emit)
        marquee_buttons.addWidget(start, 2)
        marquee_buttons.addWidget(stop, 1)
        self.root.addLayout(marquee_buttons)
        self.root.addStretch(1)

    # -- helpers ------------------------------------------------------------ #

    @staticmethod
    def _update_swatch(label: QLabel, colour: QColor) -> None:
        label.setStyleSheet(
            f"background-color: {colour.name()}; border: 1px solid {CLR_LINE}; border-radius: 4px;"
        )

    @Slot()
    def _pick_background(self) -> None:
        colour = QColorDialog.getColor(self._bg_color, self, "Top screen background colour")
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
        self.speed_label.setText(f"{value} px/s")
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
        self.mode_combo.addItem("Fullscreen", False)
        self.mode_combo.addItem("Custom size", True)
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

        self.spins["x"].setToolTip("Offset from the monitor's left edge")
        self.spins["y"].setToolTip("Offset from the monitor's top edge")

        self.on_top_check = QCheckBox("On top")
        self.on_top_check.setChecked(True)
        self.on_top_check.setToolTip(
            "Keep this output above other windows.\n"
            "Switch it OFF to show a presentation or a browser over this screen."
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


# --------------------------------------------------------------------------- #
# Presets
# --------------------------------------------------------------------------- #

class Autostart:
    """
    "Open this preset when the PC starts", via the per-user Run registry key.

    HKCU\\...\\Run needs no administrator rights and affects only this account.
    The command launches pythonw.exe so no console window appears behind the
    stage output, and passes the preset name plus a delay - see
    DEFAULT_STARTUP_DELAY for why the delay matters.
    """

    @staticmethod
    def available() -> bool:
        return winreg is not None and sys.platform == "win32"

    @staticmethod
    def _launcher() -> str:
        """pythonw.exe if we can find it, so the app starts without a console."""
        if getattr(sys, "frozen", False):  # packaged with PyInstaller etc.
            return sys.executable
        executable = sys.executable
        if os.path.basename(executable).lower() == "python.exe":
            quiet = os.path.join(os.path.dirname(executable), "pythonw.exe")
            if os.path.exists(quiet):
                return quiet
        return executable

    @classmethod
    def command(cls, preset: str, delay: int) -> str:
        if getattr(sys, "frozen", False):
            return f'"{cls._launcher()}" --preset "{preset}" --delay {delay}'
        script = os.path.join(APP_DIR, os.path.basename(__file__))
        return f'"{cls._launcher()}" "{script}" --preset "{preset}" --delay {delay}'

    @classmethod
    def read(cls) -> Optional[str]:
        """The currently registered command line, or None when disabled."""
        if not cls.available():
            return None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, _kind = winreg.QueryValueEx(key, RUN_VALUE)
                return value
        except OSError:
            return None

    @classmethod
    def enable(cls, preset: str, delay: int) -> Optional[str]:
        """Returns an error message, or None on success."""
        if not cls.available():
            return "Autostart is only supported on Windows."
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                    winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, cls.command(preset, delay))
            return None
        except OSError as exc:
            return str(exc)

    @classmethod
    def disable(cls) -> Optional[str]:
        if not cls.available():
            return None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, RUN_VALUE)
        except FileNotFoundError:
            return None
        except OSError as exc:
            return str(exc)
        return None

    @staticmethod
    def parse(command: Optional[str]) -> tuple:
        """Pull (preset, delay) back out of a registered command line."""
        if not command:
            return None, DEFAULT_STARTUP_DELAY
        preset, delay = None, DEFAULT_STARTUP_DELAY
        if "--preset" in command:
            rest = command.split("--preset", 1)[1].strip()
            if rest.startswith('"'):
                preset = rest[1:].split('"', 1)[0]
            else:
                preset = rest.split(" ", 1)[0]
        if "--delay" in command:
            tail = command.split("--delay", 1)[1].strip().split(" ", 1)[0]
            if tail.isdigit():
                delay = int(tail)
        return preset, delay


class PresetStore:
    """Named presets persisted as JSON next to this script."""

    def __init__(self, path: Optional[str] = None) -> None:
        # Resolved at call time, not import time, so PRESET_FILE stays overridable.
        self.path = path or PRESET_FILE
        self.data: Dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.data = payload.get("presets", {}) if isinstance(payload, dict) else {}
        except (OSError, ValueError):
            self.data = {}

    def save(self) -> Optional[str]:
        """Write to disk; returns an error message on failure, None on success."""
        try:
            with open(self.path, "w", encoding="utf-8") as handle:
                json.dump({"presets": self.data}, handle, indent=2, ensure_ascii=False)
            return None
        except OSError as exc:
            return str(exc)

    def names(self) -> List[str]:
        return sorted(self.data.keys())

    def put(self, name: str, payload: dict) -> None:
        self.data[name] = payload

    def get(self, name: str) -> Optional[dict]:
        return self.data.get(name)

    def remove(self, name: str) -> None:
        self.data.pop(name, None)


# --------------------------------------------------------------------------- #
# Control panel
# --------------------------------------------------------------------------- #

class ControlPanel(QMainWindow):
    """Operator-facing window: a Live tab for the show, a Screens tab for setup."""

    WIDE_ASPECT_THRESHOLD = 2.5
    OUTPUT_ATTRS = {ROLE_MAIN: "main_output", ROLE_SIDES: "sides_output", ROLE_TOP: "top_output"}

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Stage Display Controller")
        if os.path.exists(ICON_FILE):
            self.setWindowIcon(QIcon(ICON_FILE))

        available = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(min(1380, available.width() - 60), min(940, available.height() - 60))

        self.main_output: Optional[StandardOutputWindow] = None
        self.sides_output: Optional[StandardOutputWindow] = None
        self.top_output: Optional[TopOutputWindow] = None

        self.routing_rows: Dict[str, RoutingRow] = {}
        self.presets = PresetStore()

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 8)
        root.setSpacing(9)
        root.addWidget(self._build_header())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_live_tab(), "  Live  ")
        # "&&" because a single & would be swallowed as a keyboard mnemonic.
        self.tabs.addTab(self._build_screens_tab(), "  Screens && Setup  ")
        root.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        app = QGuiApplication.instance()
        app.screenAdded.connect(lambda _s: self._refresh_screen_combos())
        app.screenRemoved.connect(lambda _s: self._refresh_screen_combos())

        self._refresh_screen_combos(initial=True)
        self._refresh_preset_combo()
        self._load_autostart_state()
        self._update_output_status()
        self.statusBar().showMessage(
            "Screens & Setup → assign monitors → OPEN OUTPUTS.   "
            "Then drop media onto a card, or build a playlist."
        )

    # ------------------------------------------------------------------ UI -- #

    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("bar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 9, 12, 9)
        layout.setSpacing(10)

        mark = QLabel()
        mark.setPixmap(Icons.get("monitor", CLR_ACCENT, 19).pixmap(19, 19))
        layout.addWidget(mark)

        title = QLabel("STAGE DISPLAY")
        title.setObjectName("brand")
        layout.addWidget(title)
        layout.addSpacing(14)

        self.status_pill = QLabel()
        layout.addWidget(self.status_pill)
        layout.addStretch(1)

        # --- presets ------------------------------------------------------- #
        preset_label = QLabel()
        preset_label.setPixmap(Icons.get("list", CLR_MUTED, 15).pixmap(15, 15))
        preset_label.setToolTip("Presets")
        layout.addWidget(preset_label)

        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(190)
        self.preset_combo.setToolTip("Saved show presets")
        layout.addWidget(self.preset_combo)

        for icon_name, tip, handler in (
            ("folder", "Load the selected preset", self._load_preset),
            ("save", "Save / overwrite the selected preset", self._save_preset),
            ("plus", "Save the current setup as a new preset", self._save_preset_as),
            ("trash", "Delete the selected preset", self._delete_preset),
        ):
            button = icon_button(icon_name, tip, CLR_MUTED, 16)
            button.setObjectName("ghost")
            button.clicked.connect(handler)
            layout.addWidget(button)

        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setStyleSheet(f"color: {CLR_LINE};")
        layout.addWidget(separator)

        # --- global actions ------------------------------------------------ #
        open_btn = QPushButton("  OPEN OUTPUTS")
        open_btn.setObjectName("primary")
        open_btn.setIcon(Icons.get("monitor", "#0b0e13", 16))
        open_btn.setToolTip("Apply the Screens tab settings and open every stage window")
        open_btn.clicked.connect(self._apply_routing)
        layout.addWidget(open_btn)

        blackout = QPushButton("  BLACKOUT")
        blackout.setObjectName("danger")
        blackout.setIcon(Icons.get("power", CLR_DANGER, 16))
        blackout.setToolTip("Instantly clear every stage screen to black")
        blackout.clicked.connect(self._blackout_all)
        layout.addWidget(blackout)
        # "Close outputs" deliberately lives on the Screens tab: an X in the
        # header corner reads like "quit the app" during a show.
        return bar

    def _build_live_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(11)

        self.main_card = OutputCard("Main Stage", "large central screen", ScaleMode.FIT)
        self._wire_card(self.main_card, ROLE_MAIN)
        layout.addWidget(self.main_card, 1)

        self.sides_card = OutputCard("Side Screens", "left + right, mirrored", ScaleMode.CROP)
        self._wire_card(self.sides_card, ROLE_SIDES)
        layout.addWidget(self.sides_card, 1)

        self.top_card = TopCard()
        self._wire_card(self.top_card, ROLE_TOP)
        self.top_card.colorRequested.connect(self._on_top_colour)
        self.top_card.marqueeTextChanged.connect(
            lambda text: self.top_output and self.top_output.set_marquee_text(text)
        )
        self.top_card.marqueeFontSizeChanged.connect(
            lambda size: self.top_output and self.top_output.set_marquee_font_size(size)
        )
        self.top_card.marqueeFamilyChanged.connect(
            lambda family: self.top_output and self.top_output.set_marquee_family(family)
        )
        self.top_card.marqueeColorChanged.connect(
            lambda colour: self.top_output and self.top_output.set_marquee_color(colour)
        )
        self.top_card.marqueeSpeedChanged.connect(
            lambda speed: self.top_output and self.top_output.set_marquee_speed(speed)
        )
        self.top_card.marqueeStart.connect(self._start_marquee)
        self.top_card.marqueeStop.connect(self._stop_marquee)
        layout.addWidget(self.top_card, 1)

        self.cards: Dict[str, OutputCard] = {
            ROLE_MAIN: self.main_card,
            ROLE_SIDES: self.sides_card,
            ROLE_TOP: self.top_card,
        }
        return page

    def _build_screens_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(11)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 16)
        card_layout.setSpacing(10)

        heading = QLabel("DISPLAY ROUTING")
        heading.setObjectName("sectionTitle")
        card_layout.addWidget(heading)

        note = QLabel(
            "Assign each role to a monitor. Use “Custom size” when an LED processor's "
            "mapped canvas differs from the resolution Windows reports — the ceiling strip "
            f"is driven at {DEFAULT_TOP_WIDTH}×{DEFAULT_TOP_HEIGHT}."
        )
        note.setObjectName("cardHint")
        note.setWordWrap(True)
        card_layout.addWidget(note)

        for role in (ROLE_CONTROL, ROLE_MAIN, ROLE_SIDES, ROLE_TOP):
            row = RoutingRow(role, allow_custom=(role != ROLE_CONTROL))
            row.onTopChanged.connect(self._on_output_on_top_changed)
            self.routing_rows[role] = row
            card_layout.addWidget(row)
        # The Main Stage is the screen a presentation or browser gets shown on,
        # so it must not float above everything else.
        self.routing_rows[ROLE_MAIN].on_top_check.setChecked(False)

        buttons = QHBoxLayout()
        buttons.setSpacing(7)
        apply_btn = QPushButton("  Apply routing / Open outputs")
        apply_btn.setObjectName("primary")
        apply_btn.setIcon(Icons.get("monitor", "#0b0e13", 16))
        apply_btn.clicked.connect(self._apply_routing)
        buttons.addWidget(apply_btn)

        identify = QPushButton("  Identify monitors")
        identify.setIcon(Icons.get("target", CLR_TEXT, 16))
        identify.setToolTip("Flash a big number on every monitor for 3 seconds")
        identify.clicked.connect(self._identify_screens)
        buttons.addWidget(identify)

        redetect = QPushButton("  Re-detect")
        redetect.setIcon(Icons.get("refresh", CLR_TEXT, 16))
        redetect.clicked.connect(lambda: self._refresh_screen_combos())
        buttons.addWidget(redetect)

        use_reported = QPushButton("  Copy reported size")
        use_reported.setIcon(Icons.get("open", CLR_TEXT, 16))
        use_reported.setToolTip("Fill the W/H boxes with what Windows reports for each monitor")
        use_reported.clicked.connect(self._copy_reported_sizes)
        buttons.addWidget(use_reported)

        close_outputs = QPushButton("  Close outputs")
        close_outputs.setIcon(Icons.get("close", CLR_TEXT, 16))
        close_outputs.setToolTip("Close every stage output window (the app keeps running)")
        close_outputs.clicked.connect(self._close_all_outputs)
        buttons.addWidget(close_outputs)
        buttons.addStretch(1)
        card_layout.addLayout(buttons)
        layout.addWidget(card)
        layout.addWidget(self._build_autostart_card())

        tips = QFrame()
        tips.setObjectName("card")
        tips_layout = QVBoxLayout(tips)
        tips_layout.setContentsMargins(16, 14, 16, 16)
        tips_layout.setSpacing(8)
        tip_title = QLabel("RUNNING A SHOW")
        tip_title.setObjectName("sectionTitle")
        tips_layout.addWidget(tip_title)
        tip_text = QLabel(
            "Prepare the event by dropping several backgrounds onto a card — they land in "
            "that screen's playlist.\n"
            "During the show, click a playlist entry, or use the ‹ › arrows, to switch "
            "instantly.\n"
            "Repeat is on by default, so videos loop; switch it off per screen to play once.\n"
            "“On top” is off for the Main Stage, so a PowerPoint deck or a browser can be "
            "shown over its background — the side and ceiling screens stay above everything.\n"
            "Save everything as a preset, and the next assembly is one click away.\n"
            "Stage windows stay out of the taskbar, so only this dashboard appears there."
        )
        tip_text.setObjectName("cardHint")
        tips_layout.addWidget(tip_text)
        layout.addWidget(tips)

        layout.addStretch(1)
        return page

    def _build_autostart_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 14, 16, 16)
        box.setSpacing(9)

        heading = QLabel("START WITH WINDOWS")
        heading.setObjectName("sectionTitle")
        box.addWidget(heading)

        note = QLabel(
            "Open the app and put a preset on the screens automatically when this PC starts. "
            "The delay gives LED processors and video walls time to come up first — without it "
            "the outputs can land on the wrong monitors."
        )
        note.setObjectName("cardHint")
        note.setWordWrap(True)
        box.addWidget(note)

        row = QHBoxLayout()
        row.setSpacing(9)

        self.autostart_check = QCheckBox("Start automatically")
        self.autostart_check.toggled.connect(self._on_autostart_toggled)
        row.addWidget(self.autostart_check)

        row.addWidget(QLabel("Preset"))
        self.autostart_preset = QComboBox()
        self.autostart_preset.setMinimumWidth(200)
        self.autostart_preset.currentIndexChanged.connect(self._refresh_autostart_entry)
        row.addWidget(self.autostart_preset)

        row.addWidget(QLabel("Wait"))
        self.autostart_delay = QSpinBox()
        self.autostart_delay.setRange(0, 600)
        self.autostart_delay.setValue(DEFAULT_STARTUP_DELAY)
        self.autostart_delay.setSuffix(" s")
        self.autostart_delay.setToolTip("Seconds to wait for the monitors before applying the preset")
        self.autostart_delay.valueChanged.connect(self._refresh_autostart_entry)
        row.addWidget(self.autostart_delay)

        row.addStretch(1)
        box.addLayout(row)

        self.autostart_status = QLabel()
        self.autostart_status.setObjectName("cardHint")
        self.autostart_status.setWordWrap(True)
        box.addWidget(self.autostart_status)

        if not Autostart.available():
            self.autostart_check.setEnabled(False)
            self.autostart_preset.setEnabled(False)
            self.autostart_delay.setEnabled(False)
        return card

    def _load_autostart_state(self) -> None:
        """Reflect whatever is registered in the Run key, without changing it."""
        preset, delay = Autostart.parse(Autostart.read())
        self.autostart_delay.blockSignals(True)
        self.autostart_delay.setValue(delay)
        self.autostart_delay.blockSignals(False)

        if preset:
            index = self.autostart_preset.findText(preset)
            if index >= 0:
                self.autostart_preset.blockSignals(True)
                self.autostart_preset.setCurrentIndex(index)
                self.autostart_preset.blockSignals(False)

        self.autostart_check.blockSignals(True)
        self.autostart_check.setChecked(preset is not None)
        self.autostart_check.blockSignals(False)
        self._describe_autostart()

    def _describe_autostart(self) -> None:
        if not Autostart.available():
            self.autostart_status.setText("Autostart is only available on Windows.")
            return
        if not self.autostart_check.isChecked():
            self.autostart_status.setText("Currently off — nothing runs at login.")
            return
        preset = self.autostart_preset.currentText()
        delay = self.autostart_delay.value()
        self.autostart_status.setText(
            f"On: at login the app opens and applies “{preset}” after {delay} seconds."
        )
        self.autostart_status.setStyleSheet(f"color: {CLR_OK};")

    @Slot(bool)
    def _on_autostart_toggled(self, enabled: bool) -> None:
        if enabled and not self.autostart_preset.isEnabled():
            # No presets saved yet, so there would be nothing to apply.
            QMessageBox.information(
                self, "No preset",
                "Save a preset first — autostart needs to know what to put on the screens.",
            )
            self.autostart_check.setChecked(False)
            return
        error = self._refresh_autostart_entry()
        if error:
            QMessageBox.critical(self, "Could not change autostart", error)
            self.autostart_check.blockSignals(True)
            self.autostart_check.setChecked(not enabled)
            self.autostart_check.blockSignals(False)
        self._describe_autostart()

    @Slot()
    def _refresh_autostart_entry(self) -> Optional[str]:
        """Write (or remove) the Run entry so it matches the controls."""
        if not Autostart.available():
            return None
        if self.autostart_check.isChecked():
            preset = self.autostart_preset.currentText()
            if not preset or not self.autostart_preset.isEnabled():
                return None
            error = Autostart.enable(preset, self.autostart_delay.value())
        else:
            error = Autostart.disable()
        if not error:
            self._describe_autostart()
        return error

    # -- autostart run ------------------------------------------------------ #

    def run_autostart(self, preset: str, delay: int) -> None:
        """
        Apply `preset` once the monitors have had `delay` seconds to appear.

        Called only when the app was launched with --preset, i.e. by the Run
        registry entry at login.
        """
        remaining = {"seconds": max(0, delay)}
        ticker = QTimer(self)

        def tick() -> None:
            if remaining["seconds"] <= 0:
                ticker.stop()
                self._fire_autostart(preset)
                return
            self.statusBar().showMessage(
                f"Autostart: applying “{preset}” in {remaining['seconds']}s "
                "(waiting for the monitors)…"
            )
            remaining["seconds"] -= 1

        ticker.timeout.connect(tick)
        ticker.start(1000)
        tick()

    def _fire_autostart(self, preset: str) -> None:
        self._refresh_screen_combos()  # pick up monitors that appeared while waiting
        payload = self.presets.get(preset)
        if not payload:
            self.statusBar().showMessage(
                f"Autostart: preset “{preset}” not found — nothing applied.", 0
            )
            return
        self._apply_preset(payload)
        self.statusBar().showMessage(f"Autostart: “{preset}” applied.", 10000)

    def _wire_card(self, card: OutputCard, role: str) -> None:
        """Connect a card's signals to whichever output window that role owns."""

        def output():
            return getattr(self, self.OUTPUT_ATTRS[role], None)

        def on_load(path: str) -> None:
            window = output()
            if window is None:
                QMessageBox.warning(
                    self,
                    "Output not open",
                    f"“{ROLE_LABELS[role]}” has no output window yet.\n\n"
                    "Open the “Screens & Setup” tab, pick a monitor for it, then press "
                    "“OPEN OUTPUTS” and try again.",
                )
                return
            if not os.path.isfile(path):
                QMessageBox.warning(self, "File not found", f"Cannot find:\n{path}")
                return
            window.set_scale_mode(card.current_scale_mode())
            window.engine.set_loop(card.is_repeating())
            if window.load_media(path):
                card.show_loaded(path)
                self.statusBar().showMessage(
                    f"{ROLE_LABELS[role]}: {os.path.basename(path)}", 6000
                )
            else:
                QMessageBox.warning(
                    self,
                    "Unsupported file",
                    f"“{os.path.basename(path)}” is not a supported image or video.",
                )

        card.loadRequested.connect(on_load)
        card.queueRequested.connect(
            lambda paths: self.statusBar().showMessage(
                f"{ROLE_LABELS[role]}: {len(paths)} item(s) added to the playlist", 5000
            )
        )
        card.scaleModeChanged.connect(lambda mode: output() and output().set_scale_mode(mode))
        card.playRequested.connect(lambda: output() and output().engine.play())
        card.pauseRequested.connect(lambda: output() and output().engine.pause())
        card.stopRequested.connect(lambda: output() and output().engine.stop())
        card.clearRequested.connect(lambda: output() and output().clear_output())
        card.volumeChanged.connect(lambda value: output() and output().engine.set_volume(value))
        card.muteChanged.connect(lambda muted: output() and output().engine.set_muted(muted))
        card.repeatChanged.connect(lambda on: output() and output().engine.set_loop(on))

    # -------------------------------------------------------------- routing -- #

    @staticmethod
    def _screen_caption(index: int, screen: QScreen) -> str:
        geo = screen.geometry()
        primary = "  [primary]" if screen is QGuiApplication.primaryScreen() else ""
        return (f"#{index + 1}  {screen.name()}  —  {geo.width()}×{geo.height()} "
                f"@ ({geo.x()},{geo.y()}){primary}")

    @staticmethod
    def _screen_by_name(name: Optional[str]) -> Optional[QScreen]:
        """
        Resolve a stored screen name to a live QScreen.

        Combos store names rather than QScreen objects on purpose: if a monitor
        is unplugged, a stored object would become a dangling reference, whereas
        an unknown name simply resolves to None.
        """
        if not name:
            return None
        for screen in QGuiApplication.screens():
            if screen.name() == name:
                return screen
        return None

    def _refresh_screen_combos(self, initial: bool = False) -> None:
        screens = QGuiApplication.screens()
        names = [screen.name() for screen in screens]
        previous = {role: row.screen_combo.currentData() for role, row in self.routing_rows.items()}

        for row in self.routing_rows.values():
            combo = row.screen_combo
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("— None (disabled) —", None)
            for index, screen in enumerate(screens):
                combo.addItem(self._screen_caption(index, screen), screen.name())
            combo.blockSignals(False)

        if initial:
            self._apply_default_assignment(screens)
        else:
            for role, row in self.routing_rows.items():
                wanted = previous.get(role)
                if wanted in names:
                    row.screen_combo.setCurrentIndex(names.index(wanted) + 1)

        self.statusBar().showMessage(f"{len(screens)} monitor(s) detected.", 4000)

    def _apply_default_assignment(self, screens) -> None:
        """
        Sensible first guess - the operator can override every choice:

        * Control Panel -> the primary monitor (the operator's desk).
        * Top Screen    -> the most extremely wide monitor, pre-filled with the
          real LED canvas size rather than the resolution Windows reports.
        * Main Stage    -> the largest of the remaining monitors.
        * Side Screens  -> whatever is left.
        """
        primary = QGuiApplication.primaryScreen()
        names = [screen.name() for screen in screens]
        candidates = [screen for screen in screens if screen is not primary]

        def aspect(screen: QScreen) -> float:
            geo = screen.geometry()
            return geo.width() / geo.height() if geo.height() else 0.0

        def area(screen: QScreen) -> int:
            geo = screen.geometry()
            return geo.width() * geo.height()

        top_screen = None
        wide = [screen for screen in candidates if aspect(screen) >= self.WIDE_ASPECT_THRESHOLD]
        if wide:
            top_screen = max(wide, key=aspect)
            candidates.remove(top_screen)

        candidates.sort(key=area, reverse=True)
        chosen = {
            ROLE_CONTROL: primary,
            ROLE_MAIN: candidates[0] if len(candidates) > 0 else None,
            ROLE_SIDES: candidates[1] if len(candidates) > 1 else None,
            ROLE_TOP: top_screen,
        }

        for role, screen in chosen.items():
            row = self.routing_rows[role]
            name = screen.name() if screen is not None else None
            row.screen_combo.setCurrentIndex(names.index(name) + 1 if name in names else 0)
            if screen is not None and role != ROLE_CONTROL:
                geo = screen.geometry()
                row.set_size(geo.width(), geo.height())

        # The ceiling strip's mapped canvas, not what Windows reports.
        top_row = self.routing_rows[ROLE_TOP]
        top_row.set_size(DEFAULT_TOP_WIDTH, DEFAULT_TOP_HEIGHT)
        top_row.mode_combo.setCurrentIndex(1 if top_screen is not None else 0)
        self.top_card.size_spin.setValue(max(24, int(DEFAULT_TOP_HEIGHT * 0.72)))

    @Slot()
    def _copy_reported_sizes(self) -> None:
        for role in STAGE_ROLES:
            row = self.routing_rows[role]
            screen = self._screen_by_name(row.screen_combo.currentData())
            if screen is not None:
                geo = screen.geometry()
                row.set_size(geo.width(), geo.height())
        self.statusBar().showMessage("Custom sizes filled from the monitors' reported resolutions.", 5000)

    def _rect_for(self, role: str, screen: QScreen) -> Optional[QRect]:
        """Absolute rectangle for an output, or None for plain fullscreen."""
        config = self.routing_rows[role].config()
        if not config.custom:
            return None
        origin = screen.geometry()
        return QRect(
            origin.x() + config.offset_x,
            origin.y() + config.offset_y,
            max(1, config.width),
            max(1, config.height),
        )

    @Slot()
    def _apply_routing(self) -> None:
        assignments = {
            role: self._screen_by_name(row.screen_combo.currentData())
            for role, row in self.routing_rows.items()
        }

        used = [screen for role, screen in assignments.items()
                if screen is not None and role != ROLE_CONTROL]
        if len(used) != len(set(used)):
            QMessageBox.information(
                self,
                "Duplicate monitors",
                "Two or more outputs are assigned to the same monitor.\n"
                "They will overlap — fine for testing, but check this before the show.",
            )

        control_screen = assignments[ROLE_CONTROL]
        if control_screen is not None:
            self._move_self_to(control_screen)

        specs = (
            (ROLE_MAIN, StandardOutputWindow, "Main Stage Output", self.main_card),
            (ROLE_SIDES, StandardOutputWindow, "Side Screens Output", self.sides_card),
            (ROLE_TOP, TopOutputWindow, "Top Screen Output", self.top_card),
        )
        for role, cls, title, card in specs:
            attr = self.OUTPUT_ATTRS[role]
            window = self._ensure_output(role, getattr(self, attr), assignments[role], cls, title, card)
            setattr(self, attr, window)

        if self.top_output is not None:
            self._push_top_settings()

        self._restore_media_to_outputs()
        self._update_output_status()

        self.raise_()
        self.activateWindow()

        active = [ROLE_LABELS[role] for role in STAGE_ROLES if assignments[role] is not None]
        self.statusBar().showMessage(
            "Outputs open: " + (", ".join(active) if active else "none"), 8000
        )

    def _ensure_output(self, role: str, window, screen: Optional[QScreen], cls, title: str,
                       card: OutputCard):
        """Create, move or close one output window so it matches its assigned screen."""
        if screen is None:
            if window is not None:
                window.clear_output()
                window.force_close()
                window.deleteLater()
            return None

        if window is None:
            window = cls(title)
            window.set_scale_mode(card.current_scale_mode())
            window.closedByUser.connect(
                lambda bound_role=role, name=title: self._on_output_closed(bound_role, name)
            )

        window.engine.set_loop(card.is_repeating())
        window.engine.set_volume(card.volume_slider.value())
        window.engine.set_muted(card.mute_btn.isChecked())
        window.set_always_on_top(self.routing_rows[role].on_top_check.isChecked())
        window.show_with_geometry(screen, self._rect_for(role, screen))
        return window

    def _restore_media_to_outputs(self) -> None:
        """Re-send whatever each card has loaded, e.g. after reopening a window."""
        for role, card in self.cards.items():
            window = getattr(self, self.OUTPUT_ATTRS[role], None)
            path = card.current_path()
            if window is not None and path and os.path.isfile(path):
                window.set_scale_mode(card.current_scale_mode())
                window.load_media(path)

    def _on_output_closed(self, role: str, title: str) -> None:
        """
        Forget a window the operator dismissed with Escape.

        Without this the panel would keep sending media to a hidden window -
        which looks exactly like a screen that has gone black.
        """
        window = getattr(self, self.OUTPUT_ATTRS[role], None)
        if window is not None:
            window.deleteLater()
        setattr(self, self.OUTPUT_ATTRS[role], None)
        self._update_output_status()
        self.statusBar().showMessage(
            f"{title} closed with Escape — press OPEN OUTPUTS to bring it back.", 8000
        )

    def _move_self_to(self, screen: QScreen) -> None:
        geometry = screen.geometry()
        handle = self.windowHandle()
        if handle is not None:
            handle.setScreen(screen)
        self.move(geometry.x() + 50, geometry.y() + 40)

    @Slot(str, bool)
    def _on_output_on_top_changed(self, role: str, on_top: bool) -> None:
        """Apply a stacking change live, without reopening the whole routing."""
        window = getattr(self, self.OUTPUT_ATTRS.get(role, ""), None)
        if window is None:
            return
        window.set_always_on_top(on_top)
        self.raise_()
        self.activateWindow()
        self.statusBar().showMessage(
            f"{ROLE_LABELS[role]}: always-on-top {'ON' if on_top else 'OFF'}"
            + ("" if on_top else " — other windows can now cover this screen."),
            6000,
        )

    @Slot()
    def _close_all_outputs(self) -> None:
        for window in self._outputs():
            window.clear_output()
            window.force_close()
            window.deleteLater()
        self.main_output = self.sides_output = self.top_output = None
        self._update_output_status()
        self.statusBar().showMessage("All stage outputs closed.", 5000)

    @Slot()
    def _blackout_all(self) -> None:
        for window in self._outputs():
            window.clear_output()
        if self.top_output is not None:
            self.top_output.stop_marquee()
        for card in self.cards.values():
            card.reset_file()
        self.statusBar().showMessage("BLACKOUT — every stage screen cleared.", 6000)

    def _outputs(self):
        return [w for w in (self.main_output, self.sides_output, self.top_output) if w is not None]

    def _update_output_status(self) -> None:
        parts = []
        for role in STAGE_ROLES:
            is_open = getattr(self, self.OUTPUT_ATTRS[role], None) is not None
            colour = CLR_OK if is_open else CLR_WARN
            parts.append(
                f"<span style='color:{colour};'>●</span> "
                f"<span style='color:{CLR_MUTED};'>{ROLE_LABELS[role]}</span>"
            )
            if role in getattr(self, "cards", {}):
                self.cards[role].set_output_open(is_open)
        self.status_pill.setText("&nbsp;&nbsp;".join(parts))

    @Slot()
    def _identify_screens(self) -> None:
        """Flash a large number on every monitor for ~3 seconds."""
        overlays = []
        for index, screen in enumerate(QGuiApplication.screens()):
            label = QLabel(f"{index + 1}\n{screen.name()}")
            label.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(
                "background-color: rgba(0,0,0,225); color: #5aa9f0;"
                "font-size: 120px; font-weight: bold;"
            )
            label.setGeometry(screen.geometry())
            label.show()
            handle = label.windowHandle()
            if handle is not None:
                handle.setScreen(screen)
            label.setGeometry(screen.geometry())
            overlays.append(label)

        def dismiss() -> None:
            for overlay in overlays:
                overlay.close()
                overlay.deleteLater()

        QTimer.singleShot(3000, dismiss)

    # ---------------------------------------------------------- top screen -- #

    @Slot(QColor)
    def _on_top_colour(self, colour: QColor) -> None:
        if self.top_output is None:
            QMessageBox.warning(self, "Output not open", "The Top Screen output window is not open yet.")
            return
        self.top_output.set_background_color(colour)
        self.statusBar().showMessage(f"Top Screen: solid background {colour.name()}", 5000)

    def _push_top_settings(self) -> None:
        """Send every marquee/background setting to a (possibly new) Top window."""
        top = self.top_output
        if top is None:
            return
        state = self.top_card.marquee_state()
        top.set_background_color(self.top_card.background_colour())
        top.set_marquee_family(state["family"])
        top.set_marquee_font_size(state["size"])
        top.set_marquee_color(QColor(state["colour"]))
        top.set_marquee_speed(state["speed"])
        top.set_marquee_text(state["text"])

    @Slot()
    def _start_marquee(self) -> None:
        if self.top_output is None:
            QMessageBox.warning(self, "Output not open", "The Top Screen output window is not open yet.")
            return
        if not self.top_card.text_edit.text().strip():
            QMessageBox.information(self, "No text", "Type the marquee text first.")
            return
        state = self.top_card.marquee_state()
        self.top_output.set_marquee_family(state["family"])
        self.top_output.set_marquee_font_size(state["size"])
        self.top_output.set_marquee_color(QColor(state["colour"]))
        self.top_output.set_marquee_speed(state["speed"])
        self.top_output.set_marquee_text(state["text"])
        self.top_output.start_marquee()
        self.statusBar().showMessage("Marquee scrolling.", 4000)

    @Slot()
    def _stop_marquee(self) -> None:
        if self.top_output is not None:
            self.top_output.stop_marquee()
            self.statusBar().showMessage("Marquee stopped.", 4000)

    # ------------------------------------------------------------- presets -- #

    def _refresh_preset_combo(self, select: Optional[str] = None) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        names = self.presets.names()
        if names:
            self.preset_combo.addItems(names)
            self.preset_combo.setEnabled(True)
        else:
            self.preset_combo.addItem("no presets yet")
            self.preset_combo.setEnabled(False)
        if select:
            index = self.preset_combo.findText(select)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)
        self.preset_combo.blockSignals(False)

        # The autostart picker offers the same list.
        wanted = self.autostart_preset.currentText()
        self.autostart_preset.blockSignals(True)
        self.autostart_preset.clear()
        if names:
            self.autostart_preset.addItems(names)
            self.autostart_preset.setEnabled(Autostart.available())
            target = select or wanted
            index = self.autostart_preset.findText(target) if target else -1
            self.autostart_preset.setCurrentIndex(max(0, index))
        else:
            self.autostart_preset.addItem("no presets yet")
            self.autostart_preset.setEnabled(False)
        self.autostart_preset.blockSignals(False)
        # Keep the registered command in step with a renamed or deleted preset.
        if self.autostart_check.isChecked():
            self._refresh_autostart_entry()

    def _collect_preset(self) -> dict:
        payload = {
            "routing": {role: row.config().to_dict() for role, row in self.routing_rows.items()},
            "outputs": {},
            "top": {
                "background": self.top_card.background_colour().name(),
                "marquee": self.top_card.marquee_state(),
                # Remembered so an unattended autostart brings the text back too.
                "marquee_running": (self.top_output.is_marquee_running()
                                    if self.top_output is not None else False),
            },
        }
        for role, card in self.cards.items():
            payload["outputs"][role] = {
                "file": card.current_path(),
                "playlist": card.playlist.paths(),
                "scale": card.current_scale_mode().name,
                "volume": card.volume_slider.value(),
                "muted": card.mute_btn.isChecked(),
                "repeat": card.is_repeating(),
            }
        return payload

    def _apply_preset(self, payload: dict) -> None:
        names = [screen.name() for screen in QGuiApplication.screens()]
        missing: List[str] = []

        # Presets written before per-output stacking existed only carry a single
        # "always_on_top"; fall back to it, but never float the Main Stage.
        legacy_on_top = bool(payload.get("always_on_top", True))
        for role, row in self.routing_rows.items():
            data = payload.get("routing", {}).get(role)
            if data:
                default_on_top = False if role == ROLE_MAIN else legacy_on_top
                row.apply_config(RouteConfig.from_dict(data, default_on_top), names)

        top_data = payload.get("top", {})
        self.top_card.set_background_colour_value(QColor(top_data.get("background", "#101828")))
        self.top_card.apply_marquee_state(top_data.get("marquee", {}))

        for role, card in self.cards.items():
            data = payload.get("outputs", {}).get(role, {})
            try:
                card.set_scale_mode(ScaleMode[data.get("scale", "FIT")])
            except KeyError:
                pass
            card.volume_slider.setValue(int(data.get("volume", 80)))
            card.mute_btn.setChecked(bool(data.get("muted", False)))
            card.repeat_btn.setChecked(bool(data.get("repeat", True)))

            card.playlist.clear_all()
            queued = [p for p in data.get("playlist", []) if os.path.isfile(p)]
            missing += [os.path.basename(p) for p in data.get("playlist", []) if not os.path.isfile(p)]
            card.playlist.add_paths(queued, announce=False)

            path = data.get("file", "")
            if path and os.path.isfile(path):
                card.show_loaded(path)
            else:
                card.reset_file()

        # Open the windows, then push the remembered media into them.
        self._apply_routing()

        if (top_data.get("marquee_running")
                and self.top_output is not None
                and self.top_card.text_edit.text().strip()):
            self.top_output.start_marquee()

        if missing:
            QMessageBox.warning(
                self,
                "Missing files",
                "These files from the preset were not found and were skipped:\n\n"
                + "\n".join(sorted(set(missing))),
            )

    @Slot()
    def _load_preset(self) -> None:
        name = self.preset_combo.currentText()
        payload = self.presets.get(name) if self.preset_combo.isEnabled() else None
        if not payload:
            QMessageBox.information(self, "No preset", "Save a preset first, then it can be loaded.")
            return
        self._apply_preset(payload)
        self.statusBar().showMessage(f"Preset loaded: {name}", 6000)

    @Slot()
    def _save_preset(self) -> None:
        name = self.preset_combo.currentText()
        if not self.preset_combo.isEnabled() or not name:
            self._save_preset_as()  # nothing to overwrite yet - ask for a name
            return
        self.presets.put(name, self._collect_preset())
        self._write_presets(name)

    @Slot()
    def _save_preset_as(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save preset", "Preset name:")
        name = name.strip()
        if not accepted or not name:
            return
        if name in self.presets.names():
            answer = QMessageBox.question(
                self, "Overwrite?", f"A preset called “{name}” already exists. Replace it?"
            )
            if answer != QMessageBox.Yes:
                return
        self.presets.put(name, self._collect_preset())
        self._write_presets(name)

    @Slot()
    def _delete_preset(self) -> None:
        name = self.preset_combo.currentText()
        if not self.preset_combo.isEnabled() or not name:
            return
        answer = QMessageBox.question(self, "Delete preset", f"Delete “{name}”?")
        if answer != QMessageBox.Yes:
            return
        self.presets.remove(name)
        self._write_presets()

    def _write_presets(self, select: Optional[str] = None) -> None:
        error = self.presets.save()
        if error:
            QMessageBox.critical(self, "Could not save presets", error)
            return
        self._refresh_preset_combo(select)
        self.statusBar().showMessage(f"Presets saved to {PRESET_FILE}", 6000)

    # ------------------------------------------------------------ shutdown -- #

    def closeEvent(self, event) -> None:  # noqa: N802
        """Closing the control panel tears down every stage window, then quits."""
        for window in self._outputs():
            window.clear_output()
            window.force_close()
            window.deleteLater()
        self.main_output = self.sides_output = self.top_output = None
        event.accept()
        QApplication.quit()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Multi-screen playback controller for an assembly hall stage."
    )
    parser.add_argument(
        "--preset",
        help="Apply this saved preset on startup (used by the Start-with-Windows entry).",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=DEFAULT_STARTUP_DELAY,
        help="Seconds to wait for the monitors before applying --preset.",
    )
    # parse_known_args so Qt's own switches (-platform, -style, ...) pass through.
    options, _unknown = parser.parse_known_args(argv)
    return options


def main() -> int:
    options = parse_args(sys.argv[1:])
    app = QApplication(sys.argv)
    app.setApplicationName("Stage Display Controller")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    if os.path.exists(ICON_FILE):
        app.setWindowIcon(QIcon(ICON_FILE))
    # Output windows must never keep the app alive on their own;
    # ControlPanel.closeEvent() calls QApplication.quit() explicitly.
    app.setQuitOnLastWindowClosed(False)

    panel = ControlPanel()
    panel.show()
    if options.preset:
        panel.run_autostart(options.preset, options.delay)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
