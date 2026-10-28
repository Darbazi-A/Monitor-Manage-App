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
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# Video decoding on the graphics card where Windows offers it, through D3D11VA.
# Not DXVA2, though it was cheaper (47% of a core for three screens against 65%
# here and 76% in software): its decoders draw from a small fixed pool of frames,
# and a second in which the dashboard is busy - a big file opening, a dialog -
# used the pool up and froze the stage screens for good. D3D11VA rides that out,
# like software decoding does. FFmpeg falls back to the processor by itself on a
# machine that cannot. Set before any player exists; an explicit setting wins.
os.environ.setdefault("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", "d3d11va")

# The laptop screen share plays in Chromium (QtWebEngine), started the first time
# it is used. Its WebRTC must offer this PC's real LAN address - by default
# Chromium hides it behind a random .local name a laptop may not resolve - and its
# sound must start without anyone clicking the stage. Both before Chromium starts;
# sharing GL contexts must be asked for before the QApplication exists.
_chromium = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
for _flag in ("--disable-features=WebRtcHideLocalIpsWithMdns", "--autoplay-policy=no-user-gesture-required",
              "--log-level=3"):
    if _flag not in _chromium:
        _chromium = (_chromium + " " + _flag).strip()
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = _chromium
if QApplication.instance() is None:
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

VERSION = "1.3.0"
APP_NAME = "Stage Display Controller"

# Run from the source folder, the code and the hall's files (presets, running
# orders, backups) live side by side, as they always have. Installed (a frozen
# build in AppData\Local\Programs), the program's folder is not the place to
# write: the hall's files go to AppData\Roaming\StageDisplayController.
FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = os.path.dirname(os.path.abspath(__file__))
RESOURCE_DIR = getattr(sys, "_MEIPASS", APP_DIR)        # files packed with a frozen build
ICON_FILE = os.path.join(RESOURCE_DIR, "stage_icon.ico")


def _data_dir() -> str:
    if os.environ.get("SDC_DATA_DIR"):              # the built program's self-test: not the hall's files
        os.makedirs(os.environ["SDC_DATA_DIR"], exist_ok=True)
        return os.environ["SDC_DATA_DIR"]
    if not FROZEN:
        return APP_DIR
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "StageDisplayController")
    os.makedirs(folder, exist_ok=True)
    return folder


DATA_DIR = _data_dir()

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

# --------------------------------------------------------------------------- #
# The hall: which stage screens there are (hall.json beside the hall's files)
# --------------------------------------------------------------------------- #
# A hall is a list of screens. The first is always the Main Stage ("main") - the
# one presentations, Canva and laptops go to. A screen is a plain "screen", or
# the one "strip": a wide LED band with the running text, driven at its own
# canvas size. Without a hall.json the hall is the one this program was made
# for: Main Stage, Side Screens and the ceiling strip (ids main / sides / top),
# so presets and running orders keep their meaning. The hall is read once, at
# start; Settings -> Hall writes a new one and restarts the program.

MAX_SCREENS = 8
SCREEN_KINDS = ("screen", "strip")
DEFAULT_HALL = {
    "name": "",
    "screens": [
        {"id": "main", "name": "Main Stage", "kind": "screen", "note": "large central screen"},
        {"id": "sides", "name": "Side Screens", "kind": "screen", "note": "left + right, mirrored"},
        {"id": "top", "name": "Top Screen", "kind": "strip", "note": "ceiling LED strip", "width": 2818, "height": 132},
    ],
}


def hall_file() -> str:
    return os.environ.get("SDC_HALL_FILE") or os.path.join(DATA_DIR, "hall.json")


def clean_hall(data) -> dict:
    """A hall that can be used: known keys, unique ids, the Main Stage first, at most one strip."""
    import copy
    import re
    screens = []
    seen = set()
    strip_taken = False
    for entry in (data or {}).get("screens", []) if isinstance(data, dict) else []:
        if not isinstance(entry, dict):
            continue
        sid = str(entry.get("id", "")).strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,15}", sid) or sid in seen or sid == "control":
            continue
        kind = entry.get("kind") if entry.get("kind") in SCREEN_KINDS else "screen"
        if kind == "strip":
            if strip_taken:
                kind = "screen"
            strip_taken = True if kind == "strip" else strip_taken
        screen = {"id": sid, "name": str(entry.get("name") or sid).strip()[:40] or sid, "kind": kind,
                  "note": str(entry.get("note") or "")[:60]}
        for key in ("width", "height"):
            try:
                if int(entry.get(key) or 0) > 0:
                    screen[key] = int(entry[key])
            except (TypeError, ValueError):
                pass
        if entry.get("monitor"):
            screen["monitor"] = str(entry["monitor"])[:120]
        seen.add(sid)
        screens.append(screen)
        if len(screens) >= MAX_SCREENS:
            break
    if not screens or "main" not in seen:
        return copy.deepcopy(DEFAULT_HALL) if not screens else clean_hall(
            {"name": data.get("name", ""), "screens": [dict(screens[0], id="main")] + screens[1:]})
    screens.sort(key=lambda s: s["id"] != "main")          # the Main Stage first
    if screens[0]["kind"] == "strip":
        screens[0]["kind"] = "screen"                       # the Main Stage is never a strip
    return {"name": str(data.get("name", ""))[:60], "screens": screens}


def load_hall() -> dict:
    import copy
    import json
    try:
        with open(hall_file(), encoding="utf-8") as handle:
            return clean_hall(json.load(handle))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULT_HALL)


HALL = load_hall()
SCREENS = {screen["id"]: screen for screen in HALL["screens"]}

ROLE_CONTROL = "control"
ROLE_MAIN = "main"
STAGE_ROLES = tuple(screen["id"] for screen in HALL["screens"])
# the hall's LED strip with the running text, if it has one
ROLE_TOP = next((s["id"] for s in HALL["screens"] if s["kind"] == "strip"), None)
# the one screen beside the Main Stage that the original hall's shortcuts and
# file sorting call "sides" (portrait clips go there), if there is such a screen
ROLE_SIDES = "sides" if "sides" in SCREENS else next(
    (s["id"] for s in HALL["screens"][1:] if s["kind"] == "screen"), None)

ROLE_LABELS = Labels({         # answers in the chosen language (a hall's own names stay as typed)
    ROLE_CONTROL: "Control Panel",
    **{screen["id"]: screen["name"] for screen in HALL["screens"]},
})
SCREEN_NOTES = {screen["id"]: screen.get("note", "") for screen in HALL["screens"]}


def is_strip(role: Optional[str]) -> bool:
    return bool(role) and SCREENS.get(role, {}).get("kind") == "strip"


# The LED strip's real canvas, as mapped in its processor (Nova Studio) - NOT what Windows reports.
DEFAULT_TOP_WIDTH = int(SCREENS.get(ROLE_TOP, {}).get("width") or 2818)
DEFAULT_TOP_HEIGHT = int(SCREENS.get(ROLE_TOP, {}).get("height") or 132)

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
