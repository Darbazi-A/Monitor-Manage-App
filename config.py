"""
Constants the whole app shares: the stage roles, media types, sizes, transitions.

Part of Stage Display Controller; main.py builds the dashboard from these.
"""

from __future__ import annotations

from i18n import Labels, tr  # noqa: E402

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

# Video decoding on the graphics card where Windows offers it (DXVA2). Measured
# with the hall's three screens at their real sizes it takes 10-15 points of a
# CPU core off the playback; FFmpeg falls back to the processor by itself on a
# machine that cannot. Set before any player exists; an explicit setting wins.
os.environ.setdefault("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", "dxva2")

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

APP_DIR =os.path.dirname(os.path.abspath(__file__))
ICON_FILE = os.path.join(APP_DIR, "stage_icon.ico")

def _readable_image_extensions() -> set:
    """
    Every image type this machine's Qt build can actually read.

    Hardcoding a list meant rejecting files Qt handles perfectly well - .svg
    logos, .ico, the .jfif that browsers save - so ask the plugins instead.
    """
    try:
        from PySide6.QtGui import QImageReader
        formats = {"." + bytes(f).decode().lower() for f in QImageReader.supportedImageFormats()}
    except Exception:  # pragma: no cover - ancient/odd builds
        formats = set()
    formats |= {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
    formats.discard(".pdf")  # a document, not a stage background
    return formats


# Containers this machine's multimedia backend can demux. Anything outside it is
# refused up front with an explanation instead of stalling the player.
# The names must match QMediaFormat.fileFormatName() exactly - it says "MPEG-4",
# hyphen and all, so spelling it "MPEG4" here would refuse every .mp4 on the disk.
CONTAINER_BY_EXTENSION = {
    ".mp4": "MPEG-4", ".m4v": "MPEG-4", ".mov": "QuickTime", ".qt": "QuickTime",
    ".avi": "AVI", ".divx": "AVI", ".mkv": "Matroska", ".wmv": "WMV", ".asf": "WMV",
    ".mpg": "MPEG-4", ".mpeg": "MPEG-4", ".m2v": "MPEG-4", ".ts": "MPEG-4",
    ".mts": "MPEG-4", ".m2ts": "MPEG-4", ".3gp": "MPEG-4", ".3g2": "MPEG-4",
    ".ogv": "Ogg", ".webm": "WebM", ".flv": "Flash Video", ".vob": "MPEG program stream",
    ".rm": "RealMedia", ".rmvb": "RealMedia", ".f4v": "Flash Video",
}

# Sound files. Same idea as video: the extension names a container, and the
# container has to be one the backend can actually open.
AUDIO_CONTAINER_BY_EXTENSION = {
    ".mp3": "MP3", ".wav": "Wave", ".wave": "Wave", ".flac": "FLAC",
    ".m4a": "MPEG-4 Audio", ".aac": "AAC", ".wma": "WMA",
    ".ogg": "Ogg", ".oga": "Ogg", ".opus": "Ogg",
    ".aiff": "AIFF", ".aif": "AIFF", ".alac": "MPEG-4 Audio",
}

IMAGE_EXTENSIONS = _readable_image_extensions()
VIDEO_EXTENSIONS = set(CONTAINER_BY_EXTENSION)
AUDIO_EXTENSIONS = set(AUDIO_CONTAINER_BY_EXTENSION)

# Sound desk: eight cues on F1-F8, which is what an award ceremony needs -
# a fanfare per category, the anthem, and a bed of background music.
SOUND_SLOTS = 8
SOUND_FADE_MS = 400


def _filter_clause(extensions) -> str:
    return " ".join(sorted("*" + ext for ext in extensions))


MEDIA_FILTER = (
    f"Media files ({_filter_clause(IMAGE_EXTENSIONS | VIDEO_EXTENSIONS)});;"
    f"Images ({_filter_clause(IMAGE_EXTENSIONS)});;"
    f"Videos ({_filter_clause(VIDEO_EXTENSIONS)});;"
    "All files (*.*)"
)

# Above this an image is decoded at a reduced size: a 100-megapixel scan would
# otherwise lock the interface for seconds while it is unpacked.
MAX_IMAGE_PIXELS = 40_000_000

ROLE_CONTROL = "control"
ROLE_MAIN = "main"
ROLE_SIDES = "sides"
ROLE_TOP = "top"

STAGE_ROLES = (ROLE_MAIN, ROLE_SIDES, ROLE_TOP)

ROLE_LABELS = Labels({         # answers in the chosen language
    ROLE_CONTROL: "Control Panel",
    ROLE_MAIN: "Main Stage",
    ROLE_SIDES: "Side Screens",
    ROLE_TOP: "Top Screen",
})

# The LED strip's real canvas, as mapped in Nova Studio - NOT what Windows reports.
DEFAULT_TOP_WIDTH = 2818
DEFAULT_TOP_HEIGHT = 132

# Transition lengths, total.
FADE_PRESETS = (("Off (hard cut)", 0), ("Fast", 240), ("Normal", 500), ("Slow", 1000))
DEFAULT_FADE_MS = 500

TRANSITION_CROSSFADE = "crossfade"
TRANSITION_DIP = "dip"
TRANSITION_STYLES = (
    ("Crossfade", TRANSITION_CROSSFADE),
    ("Through black", TRANSITION_DIP),
)


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
