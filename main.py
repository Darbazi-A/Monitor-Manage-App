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
    FadeOverlay          - crossfades or dips one output between pictures.
    BaseOutputWindow     - frameless, un-closable, taskbar-less stage window.
    SceneOutputWindow    - any stage output, drawn through a QGraphicsScene.
    StandardOutputWindow / TopOutputWindow - Main+Sides / the ceiling strip.
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
import ctypes
from contextlib import contextmanager
import json
import os
import sys
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
import desk as desk_mod  # noqa: E402 - multiview, SETUP / SHOW, TAKE, ready check
import presentation as pres_mod  # noqa: E402 - PDF / PowerPoint slides
import remote as remote_mod  # noqa: E402 - the phone remote (QtNetwork)
from show import (ShowStore, ShowTab, fold as show_fold, missing_files as show_missing_files,  # noqa: E402
                  new_step, summary as step_summary)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

APP_DIR =os.path.dirname(os.path.abspath(__file__))
PRESET_FILE = os.path.join(APP_DIR, "presets.json")
SHOW_FILE = os.path.join(APP_DIR, "shows.json")
ICON_FILE = os.path.join(APP_DIR, "stage_icon.ico")

# Per-user "run at login" entry. HKCU needs no administrator rights, and it
# starts nothing until the operator ticks the box in Screens & Setup.
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "StageDisplayController"

# LED processors and video walls often finish enumerating well after the
# desktop appears, so an autostart waits before applying the routing.
DEFAULT_STARTUP_DELAY = 20

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

ROLE_LABELS = {
    ROLE_CONTROL: "Control Panel",
    ROLE_MAIN: "Main Stage",
    ROLE_SIDES: "Side Screens",
    ROLE_TOP: "Top Screen",
}

# The LED strip's real canvas, as mapped in Nova Studio - NOT what Windows reports.
DEFAULT_TOP_WIDTH = 2818
DEFAULT_TOP_HEIGHT = 132

# Transition lengths, total.
FADE_PRESETS = (("Off (hard cut)", 0), ("Fast", 240), ("Normal", 500), ("Slow", 1000))
DEFAULT_FADE_MS = 500

# QSettings scope. Tests override these so a test run cannot rewrite the
# operator's real preferences.
SETTINGS_ORG = "StageDisplayController"
SETTINGS_APP = "StageDisplayController"

TRANSITION_CROSSFADE = "crossfade"
TRANSITION_DIP = "dip"
TRANSITION_STYLES = (
    ("Crossfade", TRANSITION_CROSSFADE),
    ("Through black", TRANSITION_DIP),
)

# Palette. Navy ground and a gold accent, taken from the school's own colours -
# a generic dark-grey-and-blue theme looked like every other dark-grey-and-blue
# theme. One accent only; green, amber and red are kept for state, nothing else.
CLR_BG = "#0c1018"
CLR_CARD = "#141a26"
CLR_RAISED = "#1a2130"
CLR_INPUT = "#111724"
CLR_HOVER = "#1f2838"
CLR_LINE = "#232c3d"
CLR_LINE_SOFT = "#1b2230"
# Edges: a lit hairline on top, a darker one elsewhere. Depth without shadows.
CLR_EDGE = "#222b3c"
CLR_EDGE_SOFT = "#1a2130"
CLR_EDGE_HI = "#2c3750"
CLR_EDGE_LIT = "#313d55"
CLR_WELL = "#0f141e"
CLR_BTN_TOP = "#212a3a"
CLR_BTN_BOTTOM = "#182030"
CLR_TEXT = "#e9edf5"
CLR_DIM = "#9aa6bb"
CLR_MUTED = "#6c7891"
CLR_ACCENT = "#e3b23c"
CLR_ACCENT_SOFT = "rgba(227, 178, 60, 0.14)"
CLR_INK = "#12161f"
CLR_OK = "#57c98a"
CLR_WARN = "#d9853f"
CLR_DANGER = "#e0605c"

# The palette as handed to the modules that cannot import this one.
THEME = {
    "accent": CLR_ACCENT, "text": CLR_TEXT, "dim": CLR_DIM, "muted": CLR_MUTED,
    "ok": CLR_OK, "warn": CLR_WARN, "danger": CLR_DANGER, "card": CLR_CARD,
    "raised": CLR_RAISED, "well": CLR_WELL, "edge": CLR_EDGE, "ink": CLR_INK,
    "rehearse": "#7c9cf0",
}


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


class MediaProblem(Exception):
    """A file the app will not put on stage, with a plain-language reason."""

    def __init__(self, title: str, detail: str, advice: str = "") -> None:
        super().__init__(title)
        self.title = title
        self.detail = detail
        self.advice = advice

    def message(self) -> str:
        parts = [self.detail]
        if self.advice:
            parts.append("\n" + self.advice)
        return "\n".join(parts)


CONVERT_ADVICE = (
    "Convert it to H.264 in an MP4 container and it will play.\n"
    "In VLC:  Media → Convert / Save → Profile “Video - H.264 + MP3 (MP4)”."
)


def supported_video_containers() -> set:
    """Container names the multimedia backend reports it can decode."""
    try:
        from PySide6.QtMultimedia import QMediaFormat
        media_format = QMediaFormat()
        return {
            QMediaFormat.fileFormatName(f)
            for f in media_format.supportedFileFormats(QMediaFormat.Decode)
        }
    except Exception:  # pragma: no cover - backend without introspection
        return set()


def describe_media(path: str) -> str:
    """
    Check a file well enough to refuse it clearly, before anything reaches a
    screen. Returns "image" or "video"; raises MediaProblem otherwise.
    """
    if not path:
        raise MediaProblem("No file", "No file was given.")

    if not os.path.exists(path):
        raise MediaProblem(
            "File not found",
            f"{path}\n\nThe file is not there any more.",
            "If it lives on a USB stick or a network drive, check that it is still connected.",
        )
    if not os.path.isfile(path):
        raise MediaProblem("Not a file", f"{path}\n\nThat is a folder, not a media file.")

    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise MediaProblem("Cannot read the file", f"{path}\n\nWindows said: {exc}") from exc
    if size == 0:
        raise MediaProblem(
            "Empty file", f"{os.path.basename(path)} is 0 bytes.",
            "The copy probably failed - copy it again from the original.",
        )

    extension = os.path.splitext(path)[1].lower()
    if not extension:
        raise MediaProblem(
            "No file extension",
            f"{os.path.basename(path)} has no extension, so its type is unknown.",
            "Rename it with the right ending, for example .jpg or .mp4.",
        )

    if extension in IMAGE_EXTENSIONS:
        _check_image(path, extension)
        return "image"

    if extension in VIDEO_EXTENSIONS:
        _check_video(path, extension)
        return "video"

    if extension in AUDIO_EXTENSIONS:
        _check_audio(path, extension)
        return "audio"

    raise MediaProblem(
        "Unsupported file type",
        f"{os.path.basename(path)}\n\n“{extension}” is not a type this app can use.",
        "Supported images: " + ", ".join(sorted(e[1:] for e in IMAGE_EXTENSIONS)) + "\n"
        "Supported video: " + ", ".join(sorted(e[1:] for e in VIDEO_EXTENSIONS)) + "\n"
        "Supported sound: " + ", ".join(sorted(e[1:] for e in AUDIO_EXTENSIONS)),
    )


def _check_image(path: str, extension: str) -> None:
    from PySide6.QtGui import QImageReader

    reader = QImageReader(path)
    reader.setDecideFormatFromContent(True)  # a .jpg that is really a .png still works
    if not reader.canRead():
        raise MediaProblem(
            "Damaged or mislabelled image",
            f"{os.path.basename(path)}\n\nQt could not read it: {reader.errorString()}",
            "The file may be corrupt, or it may be a different type wearing the wrong "
            "extension (a Photoshop .psd renamed to .jpg, for instance).\n"
            "Open it in Paint and re-save it as PNG or JPG.",
        )
    size = reader.size()
    if size.isValid() and size.width() * size.height() > MAX_IMAGE_PIXELS * 4:
        raise MediaProblem(
            "Image is enormous",
            f"{os.path.basename(path)} is {size.width()}×{size.height()} pixels.",
            "Resize it to something near the screen resolution before the show - "
            "decoding it would stall the app.",
        )

    # canRead() only sniffs the header, so a truncated or half-copied file still
    # passes it. Decode a thumbnail-sized version: cheap, but it walks enough of
    # the stream to catch damage before anything reaches a screen.
    probe = QImageReader(path)
    probe.setDecideFormatFromContent(True)
    probe.setScaledSize(QSize(32, 32))
    if probe.read().isNull():
        raise MediaProblem(
            "Damaged image file",
            f"{os.path.basename(path)}\n\nThe file starts like an image but could not be "
            f"decoded: {probe.errorString() or 'unexpected end of file'}",
            "It was most likely copied incompletely. Copy it again from the original, "
            "or re-save it as PNG or JPG.",
        )


def _check_video(path: str, extension: str) -> None:
    container = CONTAINER_BY_EXTENSION.get(extension, "")
    available = supported_video_containers()
    if available and container and container not in available:
        raise MediaProblem(
            "Container not supported on this PC",
            f"{os.path.basename(path)}\n\nThis machine's video backend cannot open "
            f"{container} files.\nIt can open: " + ", ".join(sorted(available)) + ".",
            CONVERT_ADVICE,
        )


# Words that say which screen a file belongs to, in the two languages the
# material is actually named in. Checked against the file name and every folder
# above it, which is why "VIDEO ZEDA" and "ფონი გვერდების" land correctly.
ROLE_HINTS = {
    ROLE_TOP: ("top", "zeda", "\u10d6\u10d4\u10d3\u10d0", "ceiling", "strip", "\u10ed\u10d4\u10e0"),
    ROLE_SIDES: ("side", "gverd", "\u10d2\u10d5\u10d4\u10e0\u10d3", "left", "right"),
    ROLE_MAIN: ("main", "centre", "center", "\u10ea\u10d4\u10dc\u10e2\u10e0", "\u10db\u10d7\u10d0\u10d5\u10d0\u10e0"),
}

# Shape thresholds. The ceiling clips really are 2816x128 and the side clips
# really are 256x640, so the media sorts itself if you just look at it.
WIDE_RATIO = 4.0
TALL_RATIO = 0.95


def probe_media_size(path: str) -> Optional[QSize]:
    """
    Pixel size of an image or video, without decoding a frame.

    Videos come from container metadata, which is near-instant - six clips took
    0.2s - so a whole event folder can be sorted while the operator waits.
    """
    extension = os.path.splitext(path)[1].lower()
    if extension in IMAGE_EXTENSIONS:
        try:
            from PySide6.QtGui import QImageReader

            reader = QImageReader(path)
            reader.setDecideFormatFromContent(True)
            size = reader.size()
            return size if size.isValid() else None
        except Exception:
            return None
    if extension not in VIDEO_EXTENSIONS:
        return None

    from PySide6.QtCore import QEventLoop
    from PySide6.QtMultimedia import QMediaMetaData

    player = QMediaPlayer()
    sink = QVideoSink()
    player.setVideoSink(sink)
    loop = QEventLoop()
    found = {}

    def on_status(status):
        media_status = getattr(QMediaPlayer, "MediaStatus", None)
        ready = {getattr(media_status, "LoadedMedia", None),
                 getattr(media_status, "BufferedMedia", None)}
        invalid = {getattr(media_status, "InvalidMedia", None),
                   getattr(media_status, "NoMedia", None)}
        if status in ready:
            found["size"] = player.metaData().value(QMediaMetaData.Key.Resolution)
            loop.quit()
        elif status in invalid:
            loop.quit()

    player.mediaStatusChanged.connect(on_status)
    player.errorOccurred.connect(lambda *_a: loop.quit())
    QTimer.singleShot(2500, loop.quit)          # never hang on one bad file
    player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
    loop.exec()
    player.stop()
    player.setSource(QUrl())

    size = found.get("size")
    return size if isinstance(size, QSize) and size.isValid() else None


def classify_media(path: str, size: Optional[QSize] = None,
                   within: str = "") -> str:
    """
    Decide where a file belongs: a stage role, or "sound".

    Names win over shape, because an operator who wrote "gverdebis" in the file
    name meant it, and a 16:9 clip can still be destined for the side screens.
    """
    extension = os.path.splitext(path)[1].lower()
    if extension in AUDIO_EXTENSIONS:
        return "sound"

    relative = path[len(within):] if within and path.startswith(within) else path
    haystack = relative.lower().replace("\\", "/")
    for role, words in ROLE_HINTS.items():
        if any(word in haystack for word in words):
            return role

    if size is not None and size.height():
        ratio = size.width() / size.height()
        if ratio >= WIDE_RATIO:
            return ROLE_TOP
        if ratio <= TALL_RATIO:
            return ROLE_SIDES
    return ROLE_MAIN


def scan_event_folder(folder: str, depth: int = 3) -> List[str]:
    """Every playable file under `folder`, sorted, subfolders included."""
    found = []
    root_depth = folder.rstrip("\\/").count(os.sep)
    for current, dirs, files in os.walk(folder):
        if current.count(os.sep) - root_depth >= depth:
            dirs[:] = []
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            extension = os.path.splitext(name)[1].lower()
            if extension in IMAGE_EXTENSIONS or extension in VIDEO_EXTENSIONS \
                    or extension in AUDIO_EXTENSIONS:
                found.append(os.path.join(current, name))
    return found


def load_pixmap(path: str) -> QPixmap:
    """
    Decode an image, or explain why not.

    QImageReader rather than QPixmap(path) so the format is judged by content,
    very large files are scaled down while decoding instead of unpacked whole,
    and a failure comes back with a reason rather than a silent null pixmap.
    """
    from PySide6.QtGui import QImageReader

    reader = QImageReader(path)
    reader.setDecideFormatFromContent(True)
    reader.setAutoTransform(True)  # honour EXIF rotation from phone cameras

    size = reader.size()
    if size.isValid() and size.width() * size.height() > MAX_IMAGE_PIXELS:
        scaled = size.scaled(QSize(7680, 4320), Qt.KeepAspectRatio)
        reader.setScaledSize(scaled)

    image = reader.read()
    if image.isNull():
        raise MediaProblem(
            "Could not open the image",
            f"{os.path.basename(path)}\n\nQt said: {reader.errorString() or 'unknown error'}",
            "The file may be corrupt or only partly copied. Re-save it as PNG or JPG.",
        )
    pixmap = QPixmap.fromImage(image)
    if pixmap.isNull():
        raise MediaProblem(
            "Could not open the image",
            f"{os.path.basename(path)}\n\nThe image decoded but could not be prepared "
            "for display.",
        )
    return pixmap


def _check_audio(path: str, extension: str) -> None:
    container = AUDIO_CONTAINER_BY_EXTENSION.get(extension, "")
    available = supported_video_containers()   # one list covers audio and video
    if available and container and container not in available:
        raise MediaProblem(
            "Sound format not supported on this PC",
            f"{os.path.basename(path)}\n\nThis machine's audio backend cannot open "
            f"{container} files.\nIt can open: " + ", ".join(sorted(available)) + ".",
            "Convert it to MP3 or WAV and it will play.",
        )


def format_time(milliseconds: int) -> str:
    """m:ss, or h:mm:ss for anything past an hour."""
    if milliseconds is None or milliseconds < 0:
        milliseconds = 0
    seconds = milliseconds // 1000
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


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
    def _phone(p: QPainter) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(7, 2.5, 10, 19), 2.2, 2.2)
        p.drawPath(path)
        p.drawLine(QPointF(10.5, 18), QPointF(13.5, 18))

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
    def _compress(p: QPainter) -> None:
        """Two arrows pulling inwards - corner brackets read as a plus at 16px."""
        p.drawLine(QPointF(20.5, 3.5), QPointF(13.5, 10.5))
        head = QPainterPath()
        head.moveTo(13.5, 6.0)
        head.lineTo(13.5, 10.5)
        head.lineTo(18.0, 10.5)
        p.drawPath(head)
        p.drawLine(QPointF(3.5, 20.5), QPointF(10.5, 13.5))
        tail = QPainterPath()
        tail.moveTo(10.5, 18.0)
        tail.lineTo(10.5, 13.5)
        tail.lineTo(6.0, 13.5)
        p.drawPath(tail)

    @staticmethod
    def _expand(p: QPainter) -> None:
        p.drawLine(QPointF(13.5, 10.5), QPointF(20.5, 3.5))
        head = QPainterPath()
        head.moveTo(15.5, 3.5)
        head.lineTo(20.5, 3.5)
        head.lineTo(20.5, 8.5)
        p.drawPath(head)
        p.drawLine(QPointF(10.5, 13.5), QPointF(3.5, 20.5))
        tail = QPainterPath()
        tail.moveTo(8.5, 20.5)
        tail.lineTo(3.5, 20.5)
        tail.lineTo(3.5, 15.5)
        p.drawPath(tail)

    @staticmethod
    def _grip(p: QPainter) -> None:
        brush = p.pen().brush()
        for y in (8.0, 12.0, 16.0):
            for x in (9.5, 14.5):
                dot = QPainterPath()
                dot.addEllipse(QPointF(x, y), 1.2, 1.2)
                p.fillPath(dot, brush)

    @staticmethod
    def _warning(p: QPainter) -> None:
        path = QPainterPath()
        path.moveTo(12, 3.8)
        path.lineTo(21.5, 20)
        path.lineTo(2.5, 20)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(12, 10), QPointF(12, 14.6))
        dot = QPainterPath()
        dot.addEllipse(QPointF(12, 17.4), 1.1, 1.1)
        p.fillPath(dot, p.pen().brush())

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


class VideoThumbnailer(QObject):
    """
    Pulls one real frame out of a video file so playlists and previews show the
    clip instead of a generic film icon.

    A single hidden QMediaPlayer works through a queue: seek a little way in
    (the first frame is often black), take the first valid frame, cache it.
    A per-item timeout keeps one unreadable file from stalling the queue.
    """

    ready = Signal(str, QPixmap)
    failed = Signal(str)   # no frame could be read - the clip is suspect

    TARGET = QSize(480, 270)
    SEEK_MS = 1200
    TIMEOUT_MS = 6000

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._cache: Dict[str, QPixmap] = {}
        self._failures: set = set()
        self._queue: List[str] = []
        self._current: Optional[str] = None
        self._started = False

        self._player = QMediaPlayer(self)
        self._sink = QVideoSink(self)
        self._player.setVideoSink(self._sink)   # no audio output -> silent
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.errorOccurred.connect(lambda *_a: self._finish(None))

        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(self.TIMEOUT_MS)
        self._timeout.timeout.connect(lambda: self._finish(None))

    def cached(self, path: str) -> Optional[QPixmap]:
        return self._cache.get(path)

    def is_suspect(self, path: str) -> bool:
        """True once a frame grab has failed for this file."""
        return path in self._failures

    def request(self, path: str) -> None:
        pixmap = self._cache.get(path)
        if pixmap is not None:
            self.ready.emit(path, pixmap)
            return
        if path == self._current or path in self._queue:
            return
        self._queue.append(path)
        self._pump()

    # -- internals ---------------------------------------------------------- #

    def _pump(self) -> None:
        if self._current is not None or not self._queue:
            return
        self._current = self._queue.pop(0)
        self._started = False
        self._player.stop()
        self._player.setSource(QUrl())
        self._player.setSource(QUrl.fromLocalFile(self._current))
        self._timeout.start()

    def _on_status(self, status) -> None:
        # Seek + play exactly once per item: seeking makes the player re-buffer,
        # which re-emits Loaded/Buffered, and acting on that restarts the
        # pipeline forever so no frame is ever rendered.
        if self._current is None or self._started:
            return
        media_status = getattr(QMediaPlayer, "MediaStatus", None)
        ready_states = {
            getattr(media_status, "LoadedMedia", None),
            getattr(media_status, "BufferedMedia", None),
        }
        if status in ready_states:
            self._started = True
            duration = self._player.duration()
            self._player.setPosition(min(self.SEEK_MS, max(0, duration // 3)))
            self._player.play()

    def _on_frame(self, frame) -> None:
        if self._current is None or not frame.isValid():
            return
        image = frame.toImage()
        if image.isNull():
            return
        self._finish(QPixmap.fromImage(image).scaled(
            self.TARGET, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _finish(self, pixmap: Optional[QPixmap]) -> None:
        self._timeout.stop()
        path, self._current = self._current, None
        self._player.stop()
        self._player.setSource(QUrl())
        if path and pixmap is not None and not pixmap.isNull():
            self._failures.discard(path)
            self._cache[path] = pixmap
            self.ready.emit(path, pixmap)
        elif path:
            # No frame came back, so this clip will not play on stage either.
            # Better the operator learns that now than during the assembly.
            self._failures.add(path)
            self.failed.emit(path)
        QTimer.singleShot(0, self._pump)


_THUMBNAILER: Optional[VideoThumbnailer] = None


def thumbnailer() -> VideoThumbnailer:
    """Lazily created singleton; needs a running QApplication."""
    global _THUMBNAILER
    if _THUMBNAILER is None:
        _THUMBNAILER = VideoThumbnailer()
    return _THUMBNAILER


def small_picture(path: str, size: QSize) -> Optional[QPixmap]:
    """
    A thumbnail of an image or a video, without blocking: a video's frame is
    only returned once the thumbnailer has it (it is asked for meanwhile).
    """
    if not path or not os.path.isfile(path):
        return None
    extension = os.path.splitext(path)[1].lower()
    if extension in IMAGE_EXTENSIONS:
        from PySide6.QtGui import QImageReader

        reader = QImageReader(path)
        reader.setDecideFormatFromContent(True)
        found = reader.size()
        if found.isValid():
            reader.setScaledSize(found.scaled(size, Qt.KeepAspectRatio))
        image = reader.read()
        return None if image.isNull() else QPixmap.fromImage(image)
    if extension in VIDEO_EXTENSIONS:
        poster = thumbnailer().cached(path)
        if poster is not None:
            return poster.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        thumbnailer().request(path)
    return None


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
QMainWindow {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #111725, stop:0.35 {CLR_BG}, stop:1 {CLR_BG});
}}
QWidget {{
    background-color: {CLR_BG};
    color: {CLR_TEXT};
    font-family: "Segoe UI Variable Text", "Segoe UI", "Noto Sans Georgian", sans-serif;
    font-size: 13px;
}}

/* Tabs read as navigation, not as buttons. */
QTabWidget::pane {{ border: none; background: {CLR_BG}; }}
QTabBar::tab {{
    background: transparent;
    color: {CLR_MUTED};
    padding: 9px 20px 10px 4px;
    margin-right: 22px;
    border: none;
    font-size: 14px;
    font-weight: 500;
}}
QTabBar::tab:hover {{ color: {CLR_DIM}; }}
QTabBar::tab:selected {{
    color: {CLR_TEXT};
    font-weight: 600;
    border-bottom: 2px solid {CLR_ACCENT};
}}

/* Surfaces: a hairline lit from above, and the faintest vertical gradient, so a
   card reads as a raised sheet rather than a flat rectangle with a box around it. */
QFrame#card, QFrame#bar {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {CLR_RAISED}, stop:0.55 {CLR_CARD}, stop:1 {CLR_CARD});
    border: 1px solid {CLR_EDGE};
    border-top: 1px solid {CLR_EDGE_LIT};
    border-radius: 15px;
}}
QFrame#card[active="true"] {{
    border: 1px solid rgba(227, 178, 60, 0.42);
    border-top: 1px solid rgba(227, 178, 60, 0.58);
}}

QLabel#cardTitle {{ font-size: 15px; font-weight: 600; letter-spacing: 0.2px; }}
QLabel#cardSub {{ color: {CLR_MUTED}; font-size: 11px; }}
QLabel#cardHint {{ color: {CLR_DIM}; }}
QLabel#sectionTitle {{ color: {CLR_MUTED}; font-size: 11px; font-weight: 600; }}
QLabel#brand {{ font-size: 14px; font-weight: 700; letter-spacing: 0.4px; }}
QLabel#clock {{
    color: {CLR_DIM}; font-size: 16px; font-weight: 500;
    font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif;
}}
QLabel#timecode {{ color: {CLR_MUTED}; font-family: "Consolas", monospace; font-size: 11px; }}
QLabel#keyHint {{ color: {CLR_MUTED}; font-size: 11px; }}
QLabel {{ background: transparent; }}

QLabel#badgeLive, QLabel#badgeOff {{
    font-size: 10px; font-weight: 700; letter-spacing: 0.4px;
    padding: 3px 10px; border-radius: 10px;
}}
QLabel#badgeLive {{
    color: {CLR_OK};
    background: rgba(87, 201, 138, 0.13);
    border: 1px solid rgba(87, 201, 138, 0.28);
}}
QLabel#badgeOff {{
    color: {CLR_MUTED};
    background: rgba(108, 120, 145, 0.10);
    border: 1px solid rgba(108, 120, 145, 0.22);
}}

QFrame#dropZone {{
    background: {CLR_WELL};
    border: 1px solid {CLR_EDGE};
    border-radius: 12px;
}}
QFrame#dropZone[dragActive="true"] {{
    background: {CLR_ACCENT_SOFT};
    border: 1px solid rgba(227, 178, 60, 0.6);
}}

/* Buttons: a hairline, a whisper of a gradient, and a lit top edge. */
QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {CLR_BTN_TOP}, stop:1 {CLR_BTN_BOTTOM});
    border: 1px solid {CLR_EDGE};
    border-top: 1px solid {CLR_EDGE_LIT};
    border-radius: 10px;
    padding: 8px 15px;
    color: {CLR_TEXT};
    font-weight: 500;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #262f42, stop:1 #1d2533);
    border-color: {CLR_EDGE_HI};
}}
QPushButton:pressed {{
    background: {CLR_WELL};
    border-top: 1px solid {CLR_EDGE};
}}
QPushButton:disabled {{
    background: {CLR_WELL}; color: #48526640; color: #485266;
    border-color: {CLR_EDGE_SOFT}; border-top-color: {CLR_EDGE_SOFT};
}}
QPushButton:checked {{
    background: {CLR_ACCENT_SOFT};
    border: 1px solid rgba(227, 178, 60, 0.45);
    border-top: 1px solid rgba(227, 178, 60, 0.6);
}}

QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #f2c556, stop:1 {CLR_ACCENT});
    color: {CLR_INK};
    font-weight: 600;
    border: 1px solid #c9992f;
    border-top: 1px solid #f7d783;
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f7ce63, stop:1 #e8ba46);
}}
QPushButton#primary:pressed {{ background: {CLR_ACCENT}; border-top-color: #c9992f; }}
QPushButton#primary:disabled {{
    background: {CLR_WELL}; color: #485266; border-color: {CLR_EDGE_SOFT};
}}

QPushButton#danger {{
    background: transparent;
    color: {CLR_DANGER};
    border: 1px solid rgba(224, 96, 92, 0.32);
    border-top: 1px solid rgba(224, 96, 92, 0.45);
    font-weight: 600;
}}
QPushButton#danger:hover {{ background: rgba(224, 96, 92, 0.1); }}
QPushButton#ghost {{ background: transparent; border: none; padding: 5px; }}
QPushButton#ghost:hover {{ background: {CLR_HOVER}; border: none; }}
QPushButton#ghost:disabled {{ background: transparent; border: none; }}
QPushButton#transport {{ font-size: 15px; font-weight: 600; padding: 9px 0px; }}
QPushButton#healthChip {{
    background: transparent; border: 1px solid {CLR_EDGE}; border-radius: 9px;
    padding: 2px 10px; font-size: 11px; font-weight: 600; color: {CLR_MUTED};
}}
QPushButton#healthChip:hover {{ background: {CLR_HOVER}; border-color: {CLR_EDGE_HI}; }}

/* Inputs sit in a well: recessed, no outline until they matter. */
QComboBox, QSpinBox, QLineEdit, QFontComboBox, QPlainTextEdit {{
    background: {CLR_WELL};
    border: 1px solid {CLR_EDGE_SOFT};
    border-top: 1px solid #0c1119;
    border-radius: 10px;
    padding: 7px 11px;
    selection-background-color: {CLR_ACCENT};
    selection-color: {CLR_INK};
}}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover, QFontComboBox:hover {{
    border-color: {CLR_EDGE_HI};
}}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid rgba(227, 178, 60, 0.55);
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {CLR_RAISED};
    border: 1px solid {CLR_EDGE};
    border-radius: 10px;
    padding: 5px;
    selection-background-color: {CLR_ACCENT};
    selection-color: {CLR_INK};
    outline: none;
}}
QSpinBox:disabled, QComboBox:disabled {{ color: #485266; background: #0e131c; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 14px; border: none; background: transparent; }}

QListWidget {{
    background: {CLR_WELL};
    border: 1px solid {CLR_EDGE_SOFT};
    border-radius: 11px;
    outline: none;
    padding: 5px;
}}
QListWidget::item {{ padding: 6px 8px; border-radius: 8px; color: {CLR_DIM}; }}
QListWidget::item:hover {{ background: {CLR_HOVER}; color: {CLR_TEXT}; }}
QListWidget::item:selected {{
    background: {CLR_ACCENT_SOFT};
    color: {CLR_TEXT};
    border: 1px solid rgba(227, 178, 60, 0.3);
}}

QSlider::groove:horizontal {{ height: 4px; background: #1b2231; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #c9d2e2);
    width: 13px; height: 13px; margin: -5px 0; border-radius: 7px;
    border: 1px solid #0c1119;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #c79a32, stop:1 {CLR_ACCENT});
    border-radius: 2px;
}}
QSlider#scrub::groove:horizontal {{ height: 3px; background: #1b2231; border-radius: 2px; }}
QSlider#scrub::sub-page:horizontal {{ background: {CLR_ACCENT}; border-radius: 2px; }}
QSlider#scrub::handle:horizontal {{
    background: transparent; border: none; width: 10px; margin: -4px 0; border-radius: 5px;
}}
QSlider#scrub:hover::handle:horizontal {{ background: {CLR_TEXT}; border: none; }}
QSlider#scrub:disabled::sub-page:horizontal {{ background: #1b2231; }}

QCheckBox {{ background: transparent; color: {CLR_DIM}; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid {CLR_EDGE_HI}; background: {CLR_WELL};
}}
QCheckBox::indicator:checked {{ background: {CLR_ACCENT}; border-color: #c9992f; }}
QCheckBox:disabled {{ color: #485266; }}
QCheckBox::indicator:disabled {{ background: #0e131c; border-color: {CLR_EDGE_SOFT}; }}
QCheckBox::indicator:checked:disabled {{ background: #3a3f4a; border-color: {CLR_EDGE}; }}

QFrame#cuePad {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {CLR_BTN_TOP}, stop:1 {CLR_WELL});
    border: 1px solid {CLR_EDGE};
    border-top: 1px solid {CLR_EDGE_LIT};
    border-radius: 12px;
}}
QFrame#cuePad[filled="false"] {{
    background: transparent;
    border: 1px dashed {CLR_EDGE_HI};
    border-top: 1px dashed {CLR_EDGE_HI};
}}
QFrame#cuePad[filled="true"]:hover {{ border-color: {CLR_EDGE_HI}; }}
QFrame#cuePad[playing="true"] {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 rgba(87, 201, 138, 0.17), stop:1 rgba(87, 201, 138, 0.07));
    border: 1px solid rgba(87, 201, 138, 0.45);
    border-top: 1px solid rgba(87, 201, 138, 0.6);
}}
QFrame#cuePad[paused="true"] {{
    background: {CLR_ACCENT_SOFT};
    border: 1px solid rgba(227, 178, 60, 0.42);
    border-top: 1px solid rgba(227, 178, 60, 0.55);
}}
QLabel#cueKey {{ color: {CLR_MUTED}; font-size: 10px; font-weight: 700; }}
QFrame#cuePad[playing="true"] QLabel#cueKey {{ color: {CLR_OK}; }}
QFrame#cuePad[paused="true"] QLabel#cueKey {{ color: {CLR_ACCENT}; }}
QLabel#cueName {{ font-size: 12px; font-weight: 500; }}
QFrame#cuePad[filled="false"] QLabel#cueName {{ color: #465063; }}

/* The floating strip. */
QFrame#miniCard {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {CLR_RAISED}, stop:1 {CLR_CARD});
    border: 1px solid {CLR_EDGE_HI};
    border-top: 1px solid {CLR_EDGE_LIT};
    border-radius: 14px;
}}
QPushButton#miniScreen {{
    padding: 6px 12px; font-size: 12px; font-weight: 600; color: {CLR_MUTED};
}}
QPushButton#miniScreen:checked {{
    background: {CLR_ACCENT_SOFT}; color: {CLR_TEXT};
    border-color: rgba(227, 178, 60, 0.5);
}}
QPushButton#miniScreen[live="true"] {{ color: {CLR_OK}; }}
QLabel#miniNow {{ color: {CLR_DIM}; font-size: 12px; }}
QPushButton#miniCue {{
    padding: 7px 0px; font-size: 11px; font-weight: 600; color: {CLR_DIM};
}}
QPushButton#miniCue[playing="true"] {{
    background: rgba(87, 201, 138, 0.18); color: {CLR_OK};
    border-color: rgba(87, 201, 138, 0.45);
}}
QPushButton#miniCue[paused="true"] {{
    background: {CLR_ACCENT_SOFT}; color: {CLR_ACCENT};
    border-color: rgba(227, 178, 60, 0.45);
}}

/* SETUP / SHOW: one control, two halves. */
QFrame#modeSwitch {{
    background: {CLR_WELL}; border: 1px solid {CLR_EDGE}; border-radius: 12px;
}}
QPushButton#modeButton {{
    background: transparent; border: 1px solid transparent; border-radius: 9px;
    padding: 7px 18px; color: {CLR_MUTED}; font-weight: 700; letter-spacing: 1px;
}}
QPushButton#modeButton:hover {{ color: {CLR_DIM}; background: transparent; }}
QPushButton#modeButton:checked {{
    background: {CLR_RAISED}; color: {CLR_TEXT}; border: 1px solid {CLR_EDGE_HI};
}}
/* A change waiting for TAKE, or one that can still be undone. */
QFrame#takeBar {{
    background: rgba(227, 178, 60, 0.07);
    border: 1px solid rgba(227, 178, 60, 0.35);
    border-radius: 12px;
}}

QStatusBar {{ background: transparent; color: {CLR_MUTED}; border: none; }}
QStatusBar::item {{ border: none; }}
QToolTip {{
    background: {CLR_RAISED}; color: {CLR_TEXT};
    border: 1px solid {CLR_EDGE_HI}; padding: 6px 9px; border-radius: 8px;
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2b3547; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: #3a4659; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2b3547; border-radius: 5px; min-width: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""

# Laid over STYLESHEET on a touch screen: the same look, sized for a fingertip
# (about 9 mm, so roughly 40 px on a 24" 1080p panel). There is no hover on
# glass, so nothing that matters may appear only on hover.
TOUCH_STYLESHEET = f"""
QPushButton {{ padding: 8px 16px; min-height: 19px; }}
QPushButton#ghost {{ padding: 9px; }}
QComboBox, QSpinBox, QLineEdit, QFontComboBox {{ padding: 8px 12px; min-height: 19px; }}
QComboBox::drop-down {{ width: 32px; }}
QComboBox QAbstractItemView::item {{ min-height: 40px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 24px; }}
QListWidget::item {{ padding: 9px 10px; }}
QTabBar::tab {{ padding: 10px 22px 11px 6px; }}
QSlider::groove:horizontal {{ height: 6px; border-radius: 3px; }}
QSlider::handle:horizontal {{ width: 24px; height: 24px; margin: -10px 0; border-radius: 12px; }}
QSlider#scrub::groove:horizontal {{ height: 5px; }}
QSlider#scrub::handle:horizontal {{
    background: {CLR_TEXT}; width: 18px; margin: -7px 0; border-radius: 9px;
}}
QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{ width: 24px; height: 24px; border-radius: 7px; }}
QScrollBar:vertical {{ width: 16px; }}
QScrollBar::handle:vertical {{ border-radius: 7px; min-height: 44px; }}
QScrollBar:horizontal {{ height: 16px; }}
QScrollBar::handle:horizontal {{ border-radius: 7px; min-width: 44px; }}
QMenu::item {{ padding: 11px 26px; }}
"""

TOUCH_MODES = (("Automatic", "auto"), ("Larger controls", "on"), ("Mouse sizes", "off"))


def touch_screen_present() -> bool:
    return any(device.type() == QInputDevice.DeviceType.TouchScreen
               for device in QInputDevice.devices())


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
        self._wanted_muted = muted
        self._audio.setMuted(muted or getattr(self, "_silenced", False))

    def set_silenced(self, silenced: bool) -> None:
        """Rehearsal: no sound, whatever the card's mute button says."""
        self._silenced = silenced
        self._audio.setMuted(silenced or getattr(self, "_wanted_muted", False))

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

    def set_device(self, device) -> None:
        if device is not None:
            self._audio.setDevice(device)


# --------------------------------------------------------------------------- #
# Sound desk
# --------------------------------------------------------------------------- #

class SoundCue(QObject):
    """
    One sound on one key.

    Every cue owns its own player, so a fanfare can fire over a bed of music
    instead of interrupting it. Stopping fades the level down first: cutting a
    hall's PA dead is far more noticeable than the sound itself.
    """

    changed = Signal()
    failed = Signal(str)

    def __init__(self, index: int, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.index = index
        self.path = ""
        self.loop = False
        self.level = 90          # this cue's own level, 0-100
        self._master = 90

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._apply_volume()

        self._fade = QPropertyAnimation(self._audio, b"volume", self)
        self._fade.setEasingCurve(QEasingCurve.OutQuad)
        self._fade.finished.connect(self._after_fade)
        self._fade_mode: Optional[str] = None

        self._player.playbackStateChanged.connect(lambda _s: self.changed.emit())
        self._player.errorOccurred.connect(
            lambda _e, message: self.failed.emit(message or "playback failed")
        )

    # -- content ------------------------------------------------------------ #

    def assign(self, path: str) -> None:
        """Point this cue at a file. Raises MediaProblem if it is unusable."""
        kind = describe_media(path)
        if kind != "audio":
            raise MediaProblem(
                "Not a sound file",
                f"{os.path.basename(path)} is {'an image' if kind == 'image' else 'a video'}.",
                "Sound cues take audio files - mp3, wav, m4a, flac and the like.",
            )
        self.stop(0)
        self.path = path
        self._player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
        self.changed.emit()

    def clear(self) -> None:
        self.stop(0)
        self.path = ""
        self._player.setSource(QUrl())
        self.changed.emit()

    def label(self) -> str:
        return os.path.splitext(os.path.basename(self.path))[0] if self.path else ""

    # -- transport ---------------------------------------------------------- #

    def _state(self):
        return self._player.playbackState()

    @staticmethod
    def _states():
        return getattr(QMediaPlayer, "PlaybackState", None)

    def is_playing(self) -> bool:
        return self._state() == getattr(self._states(), "PlayingState", None)

    def is_paused(self) -> bool:
        return self._state() == getattr(self._states(), "PausedState", None)

    def target_volume(self) -> float:
        return (self.level / 100.0) * (self._master / 100.0)

    # Rehearsal: a sound started now is kept away from the hall - silent, or on
    # the device given here - and stopped when the rehearsal ends. Sounds that
    # were already playing for the hall are left alone.
    rehearsal = None            # None | "silent" | a QAudioDevice
    started_in_rehearsal = False

    def end_rehearsal(self, device) -> None:
        if self.started_in_rehearsal:
            self.stop(0)
        self.started_in_rehearsal = False
        self.rehearsal = None
        self._audio.setMuted(False)
        if device is not None:
            self._audio.setDevice(device)

    def play(self) -> None:
        """Start, or pick up where a pause left off."""
        if not self.path:
            return
        if self.rehearsal is not None and not self.is_playing() and not self.is_paused():
            self.started_in_rehearsal = True
            if self.rehearsal == "silent":
                self._audio.setMuted(True)
            else:
                self._audio.setDevice(self.rehearsal)
                self._audio.setMuted(False)
        self._fade.stop()
        self._fade_mode = None
        self._apply_loop()
        self._audio.setVolume(0.0)
        self._player.play()
        self._fade_volume(self.target_volume(), 220)
        self.changed.emit()

    def pause(self) -> None:
        if not self.is_playing():
            return
        self._fade_volume(0.0, 200, "pause")

    def toggle(self) -> None:
        """What a play button does: pause if it is running, otherwise play."""
        self.pause() if self.is_playing() else self.play()

    def stop(self, fade_ms: int = SOUND_FADE_MS) -> None:
        """Back to the start. Fades first - a hall PA cut dead is jarring."""
        if self.is_paused():
            self._player.stop()
            self._audio.setVolume(self.target_volume())
            self.changed.emit()
            return
        if not self.is_playing():
            self._player.stop()
            return
        if fade_ms <= 0:
            self._fade.stop()
            self._fade_mode = None
            self._player.stop()
            self._audio.setVolume(self.target_volume())
            self.changed.emit()
            return
        self._fade_volume(0.0, fade_ms, "stop")

    def seek(self, milliseconds: int) -> None:
        if self.path:
            self._player.setPosition(max(0, milliseconds))
            self.changed.emit()

    def _fade_volume(self, target: float, duration_ms: int, mode: Optional[str] = None) -> None:
        self._fade_mode = mode
        self._fade.stop()
        self._fade.setDuration(max(40, duration_ms))
        self._fade.setStartValue(float(self._audio.volume()))
        self._fade.setEndValue(float(target))
        self._fade.start()

    def _after_fade(self) -> None:
        mode, self._fade_mode = self._fade_mode, None
        if mode == "stop":
            self._player.stop()
        elif mode == "pause":
            self._player.pause()
        if mode:
            self._audio.setVolume(self.target_volume())   # ready for next time
            self.changed.emit()

    # -- settings ----------------------------------------------------------- #

    def set_loop(self, enabled: bool) -> None:
        self.loop = enabled
        self._apply_loop()
        self.changed.emit()

    def set_level(self, percent: int) -> None:
        self.level = max(0, min(100, percent))
        if not self._fade_mode:
            self._apply_volume()

    def set_master(self, percent: int) -> None:
        self._master = max(0, min(100, percent))
        if not self._fade_mode:
            self._apply_volume()

    def set_device(self, device) -> None:
        if device is not None:
            self._audio.setDevice(device)

    def position(self) -> int:
        return self._player.position()

    def duration(self) -> int:
        return self._player.duration()

    def _apply_volume(self) -> None:
        self._audio.setVolume(self.target_volume())

    def _apply_loop(self) -> None:
        loops = getattr(QMediaPlayer, "Loops", None)
        infinite = getattr(loops, "Infinite", None) if loops else None
        if hasattr(self._player, "setLoops") and infinite is not None:
            try:
                self._player.setLoops(infinite if self.loop else 1)
            except (TypeError, ValueError):
                pass

    def to_dict(self) -> dict:
        return {"file": self.path, "loop": self.loop, "level": self.level}

    def from_dict(self, data: dict) -> Optional[str]:
        """Restore a saved cue; returns the file name if it has gone missing."""
        self.set_loop(bool(data.get("loop", False)))
        self.set_level(int(data.get("level", 90)))
        path = data.get("file", "")
        if not path:
            self.clear()
            return None
        if not os.path.isfile(path):
            self.clear()
            return os.path.basename(path)
        try:
            self.assign(path)
        except MediaProblem:
            self.clear()
            return os.path.basename(path)
        return None


class SoundDeck(QObject):
    """The eight cues, a master level, and which device they play out of."""

    changed = Signal()
    failed = Signal(int, str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.master = 90
        self.cues: List[SoundCue] = []
        for index in range(SOUND_SLOTS):
            cue = SoundCue(index, self)
            cue.set_master(self.master)
            cue.changed.connect(self.changed.emit)
            cue.failed.connect(lambda message, i=index: self.failed.emit(i, message))
            self.cues.append(cue)

    def set_master(self, percent: int) -> None:
        self.master = max(0, min(100, percent))
        for cue in self.cues:
            cue.set_master(self.master)

    def set_device(self, device) -> None:
        for cue in self.cues:
            cue.set_device(device)

    def stop_all(self, fade_ms: int = SOUND_FADE_MS) -> None:
        for cue in self.cues:
            cue.stop(fade_ms)

    def anything_playing(self) -> bool:
        return any(cue.is_playing() for cue in self.cues)

    def to_list(self) -> List[dict]:
        return [cue.to_dict() for cue in self.cues]

    def from_list(self, data: List[dict]) -> List[str]:
        missing = []
        for cue, saved in zip(self.cues, list(data) + [{}] * SOUND_SLOTS):
            gone = cue.from_dict(saved or {})
            if gone:
                missing.append(gone)
        return missing


# --------------------------------------------------------------------------- #
# Output windows
# --------------------------------------------------------------------------- #

def no_window_animation(widget: QWidget) -> None:
    """
    Switch off Windows' own show / hide animation for a stage window. Windows
    fades new windows in; on a stage that reads as a flash of whatever is
    underneath.
    """
    hwnd = int(widget.winId())
    if sys.platform != "win32" or not hwnd:
        return
    try:
        disabled = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 3,   # DWMWA_TRANSITIONS_FORCEDISABLED
                                                   ctypes.byref(disabled), ctypes.sizeof(disabled))
    except (AttributeError, OSError):
        pass


def set_topmost(widget: QWidget, on_top: bool) -> None:
    """
    Lift a window above others, or let it sit among them, without Qt's
    setWindowFlags (which rebuilds the window and flashes the stage).
    """
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        after = ctypes.c_void_p(-1 if on_top else -2)            # HWND_TOPMOST / HWND_NOTOPMOST
        user32.SetWindowPos(ctypes.c_void_p(int(widget.winId())), after, 0, 0, 0, 0,
                            0x0001 | 0x0002 | 0x0010)             # no size, no move, no activate
    except (AttributeError, OSError):
        pass


class FadeOverlay(QWidget):
    """
    A black pane held directly above one output window, used to dip to black.

    Why dip instead of a true A/B crossfade: blending two sources needs two
    decoders and two surfaces per screen, and mixing a QVideoWidget's surface
    with anything else is not something to gamble on mid-assembly. Dipping is
    what broadcast does for the same reason, and it behaves identically for
    image->video, video->video and video->image.

    It is a separate top-level window rather than a child widget because a child
    cannot reliably paint over a video surface. Setting the output window as its
    transient parent keeps it above that output and nothing else - so a
    presentation covering the Main Stage is never dimmed by a transition on
    another screen.
    """

    BASE_FLAGS = Qt.Window | Qt.FramelessWindowHint | Qt.Tool

    def __init__(self, target: QWidget) -> None:
        # Constructed WITH the output as its parent: a top-level widget that has
        # a parent becomes an owned window, and Windows keeps an owned window
        # above its owner. Setting a transient parent after winId() has already
        # created the native window is too late - the owner is fixed at creation,
        # which left the overlay fading away underneath a non-topmost output.
        super().__init__(target, FadeOverlay.BASE_FLAGS)
        self._target = target
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background-color: black;")
        self.setCursor(Qt.BlankCursor)
        self.setWindowOpacity(0.0)

        # Holds a still of the outgoing picture during a crossfade.
        self._still = QPixmap()

        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("black"))
        if not self._still.isNull():
            painter.drawPixmap(self.rect(), self._still, QRectF(self._still.rect()).toRect())

    # -- internals ---------------------------------------------------------- #

    def _clear_handlers(self) -> None:
        try:
            self._anim.finished.disconnect()
        except (RuntimeError, TypeError):
            pass  # nothing connected, which is fine

    def _cover_target(self) -> None:
        geometry = self._target.geometry()

        # A topmost window always sits above a non-topmost one, whoever owns
        # whom - so the overlay has to match the output's stacking or it fades
        # away behind the very screen it is supposed to be dimming.
        flags = self.BASE_FLAGS
        if self._target.windowFlags() & Qt.WindowStaysOnTopHint:
            flags |= Qt.WindowStaysOnTopHint
        if flags != self.windowFlags():
            opacity = self.windowOpacity()
            self.setWindowFlags(flags)     # this hides the window
            self.setWindowOpacity(opacity)

        self.setGeometry(geometry)
        no_window_animation(self)  # force the native handle, and no DWM fade when it shows
        handle, target_handle = self.windowHandle(), self._target.windowHandle()
        if handle is not None and target_handle is not None:
            handle.setTransientParent(target_handle)
        if not self.isVisible():
            self.show()
        self.setGeometry(geometry)
        self.raise_()

    # -- public API --------------------------------------------------------- #

    def crossfade(self, action: Callable[[], None], duration_ms: int) -> bool:
        """
        Swap instantly behind a still of the old picture, then dissolve it away.

        Smoother than dipping because the hall never goes dark - but it needs a
        usable still of what is currently on screen, which only the graphics
        scene outputs can give. Returns False when no still could be taken, so
        the caller can fall back to a dip.
        """
        still = self._target.snapshot() if hasattr(self._target, "snapshot") else QPixmap()
        if still.isNull():
            return False

        self._still = still
        self._cover_target()
        self._anim.stop()
        self._clear_handlers()
        self.setWindowOpacity(1.0)
        self.repaint()

        action()        # the new picture is built underneath, unseen

        def done() -> None:
            self._clear_handlers()
            self._still = QPixmap()
            self.hide()

        self._anim.finished.connect(done)
        self._anim.setDuration(max(80, duration_ms))
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        # A short hold lets the first video frame arrive before it is revealed.
        QTimer.singleShot(90, self._anim.start)
        return True

    def dip(self, action: Callable[[], None], duration_ms: int) -> None:
        """Fade to black, run `action` while nothing is visible, fade back."""
        self._still = QPixmap()
        half = max(60, duration_ms // 2)
        self._cover_target()
        self._anim.stop()
        self._clear_handlers()

        def midpoint() -> None:
            self._clear_handlers()
            action()
            # Give the new image or the first video frame a moment to land,
            # otherwise the fade-in reveals the previous content.
            QTimer.singleShot(70, lambda: self._fade_in(half))

        self._anim.finished.connect(midpoint)
        self._anim.setDuration(half)
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _fade_in(self, duration_ms: int) -> None:
        self._anim.stop()
        self._clear_handlers()

        def done() -> None:
            self._clear_handlers()
            self.hide()

        self._anim.finished.connect(done)
        self._anim.setDuration(duration_ms)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def abort(self) -> None:
        self._anim.stop()
        self._clear_handlers()
        self.setWindowOpacity(0.0)
        self.hide()


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
        self._fader: Optional[FadeOverlay] = None

    # -- placement ---------------------------------------------------------- #

    def show_with_geometry(self, screen: QScreen, rect: Optional[QRect] = None) -> None:
        """
        Place the window on `screen`.

        `rect` is an absolute desktop rectangle; pass None for fullscreen on the
        whole monitor. A custom rectangle is what makes LED walls work when
        Windows reports a resolution that differs from the mapped canvas.
        """
        target = rect if rect is not None else screen.geometry()
        if (self.isVisible() and self._screen is screen and self._geometry == rect
                and self.geometry() == target):
            self.raise_()      # already exactly here; re-showing would only flicker
            return

        self._screen = screen
        self._geometry = rect

        # Leaving fullscreen first makes a cross-monitor move reliable on Windows.
        if self.isFullScreen() or self.isVisible():
            self.showNormal()
        self.setGeometry(target)
        if not self.isVisible():
            no_window_animation(self)
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
        if flags == self.windowFlags():
            return   # setWindowFlags would destroy and rebuild the window for nothing
        was_visible = self.isVisible()

        # setWindowFlags destroys and recreates this window, which leaves the
        # overlay owned by an HWND that no longer exists - and an overlay with a
        # dead owner sinks behind the output. Throw it away and build a fresh one.
        if self._fader is not None:
            self._fader.abort()
            self._fader.setParent(None)
            self._fader.deleteLater()
            self._fader = None

        self.setWindowFlags(flags)
        if was_visible and self._screen is not None:
            self.show_with_geometry(self._screen, self._geometry)

    def force_close(self) -> None:
        """The only sanctioned way to close a stage window."""
        if self._fader is not None:
            self._fader.abort()
        self._allow_close = True
        self.close()
        self._allow_close = False

    # -- transitions -------------------------------------------------------- #

    def fader(self) -> FadeOverlay:
        if self._fader is None:
            self._fader = FadeOverlay(self)
        return self._fader

    def transition(self, action: Callable[[], None], fade_ms: int, style: str) -> None:
        """Run `action` behind whichever transition the operator chose."""
        if fade_ms <= 0:
            action()
            return
        if style == TRANSITION_CROSSFADE and self.fader().crossfade(action, fade_ms):
            return
        self.fader().dip(action, fade_ms)   # also the fallback when no still exists

    def present(self, path: str, fade_ms: int = 0,
                style: str = TRANSITION_CROSSFADE) -> None:
        """
        Put `path` on this screen, transitioning on the way.

        Raises MediaProblem if the file cannot be shown. The media is prepared
        (checked, decoded) before any transition starts, so a bad file is
        reported instantly instead of after a pointless fade.
        """
        payload = self.prepare_media(path)
        self.transition(lambda: self.commit_media(payload), fade_ms, style)

    def fade_clear(self, fade_ms: int = 0, style: str = TRANSITION_DIP) -> None:
        """Blackout. Always through black - there is nothing to dissolve into."""
        self.transition(self.clear_output, fade_ms, TRANSITION_DIP)

    def snapshot(self) -> QPixmap:
        """A still of what is on screen, or a null pixmap if it cannot be taken."""
        return QPixmap()

    def load_media(self, path: str) -> bool:
        """Immediate swap, no transition. False instead of raising."""
        try:
            self.present(path, 0)
            return True
        except MediaProblem:
            return False

    # -- event handling ----------------------------------------------------- #

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._allow_close:
            event.accept()
        else:
            event.ignore()

    # Set by the dashboard: gets first look at keys pressed while a stage
    # window has focus, so a clicker still turns slides (and its Esc does not
    # close the screen mid-presentation). Returns True when it used the key.
    key_router: Optional[Callable] = None

    def keyPressEvent(self, event) -> None:  # noqa: N802
        router = BaseOutputWindow.key_router
        if router is not None and router(event):
            event.accept()
            return
        # Swallow every other key, so a stray keyboard on stage cannot disturb output.
        if event.key() == Qt.Key_Escape:
            self.force_close()
            self.closedByUser.emit()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        event.accept()

    # -- interface implemented by subclasses -------------------------------- #

    def prepare_media(self, path: str):
        """Decode/validate; return an opaque payload, or None if unusable."""
        raise NotImplementedError

    def commit_media(self, payload) -> None:
        """Put a prepared payload on screen. Must be quick - it runs mid-fade."""
        raise NotImplementedError

    def clear_output(self) -> None:
        raise NotImplementedError

    def set_scale_mode(self, mode: ScaleMode) -> None:
        raise NotImplementedError


class SceneOutputWindow(BaseOutputWindow):
    """
    One stage output, drawn through a QGraphicsScene.

    Every output uses this, not just the ceiling strip. A QVideoWidget renders
    straight to its own surface, which means nothing can be composited over it
    and it cannot be captured - so no text overlay and, more importantly, no
    crossfade, because a crossfade needs a still of the outgoing picture. Going
    through the scene costs a texture blit and buys both.

    Scene layers (Z value):
        0   background colour rectangle
        1   background image OR background video
        10  marquee text (used by the ceiling strip)
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

        # --- slide layer: a name and a line under it, over whatever is running #
        self._slide_scrim = self._scene.addRect(QRectF(), QPen(Qt.NoPen),
                                                QBrush(QColor(0, 0, 0, 150)))
        self._slide_scrim.setZValue(15)
        self._slide_scrim.setVisible(False)

        self._slide_title = QGraphicsSimpleTextItem("")
        self._slide_title.setZValue(20)
        self._slide_title.setVisible(False)
        self._scene.addItem(self._slide_title)

        self._slide_subtitle = QGraphicsSimpleTextItem("")
        self._slide_subtitle.setZValue(20)
        self._slide_subtitle.setVisible(False)
        self._scene.addItem(self._slide_subtitle)

        # --- dissolve layer: a still of the outgoing picture, faded away ------- #
        # Drawn inside this window's own scene. The old way laid a second,
        # transparent window over the screen, and Windows animates every new
        # window in - for a moment the new picture showed through, flicked
        # back to the old one, then dissolved: a visible "refresh".
        self._still_item = QGraphicsPixmapItem()
        self._still_item.setZValue(50)
        self._still_item.setVisible(False)
        self._scene.addItem(self._still_item)
        self._still_anim = QVariantAnimation(self)
        self._still_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._still_anim.valueChanged.connect(lambda value: self._still_item.setOpacity(float(value)))
        self._still_anim.finished.connect(self._after_dissolve)

        # Rehearsal windows lay the scene out at the real stage size and scale
        # the view down, so text and marquee sizes look exactly as on stage.
        self._virtual: Optional[QSize] = None

        # --- corner: the speaker's countdown, small, over everything else ------ #
        self._corner_scrim = self._scene.addRect(QRectF(), QPen(Qt.NoPen), QBrush(QColor(0, 0, 0, 160)))
        self._corner_scrim.setZValue(29)
        self._corner_scrim.setVisible(False)
        self._corner_text = QGraphicsSimpleTextItem("")
        self._corner_text.setZValue(30)
        self._corner_text.setVisible(False)
        self._scene.addItem(self._corner_text)

        self._slide_style = {
            "family": "", "title_px": 84, "subtitle_px": 44,
            "colour": "#ffffff", "subtitle_colour": "#cfd8e6",
            "position": "middle", "scrim": True,
        }
        self._slide_opacity = 0.0
        self._slide_wanted = False
        self._slide_anim = QVariantAnimation(self)
        self._slide_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._slide_anim.valueChanged.connect(self._set_slide_opacity)
        self._slide_anim.finished.connect(self._after_slide_fade)

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

    def prepare_media(self, path: str):
        kind = describe_media(path)          # raises MediaProblem
        if kind == "image":
            return ("image", load_pixmap(path))
        if kind == "audio":
            raise MediaProblem(
                "That is a sound file",
                f"{os.path.basename(path)} is audio, and a screen cannot show it.",
                "Drop it on one of the sound cues at the bottom of the Live tab instead.",
            )
        return ("video", path)

    def commit_media(self, payload) -> None:
        kind, value = payload
        if kind == "image":
            self.engine.clear()
            self._video_item.setVisible(False)
            self._pixmap_item.setPixmap(value)
            self._pixmap_item.setVisible(True)
            self._layout_pixmap()
        else:
            self._pixmap_item.setVisible(False)
            self._pixmap_item.setPixmap(QPixmap())
            self._video_item.setVisible(True)
            self.engine.load(value)
            self._layout_video()

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
        self.hide_slide(0)

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

    def set_virtual_size(self, size: QSize) -> None:
        self._virtual = QSize(size)
        self._view.setAlignment(Qt.AlignCenter)
        self._relayout()

    def _relayout(self) -> None:
        size = self._view.viewport().size()
        if self._virtual is not None and not self._virtual.isEmpty():
            if size.width() > 0 and size.height() > 0:
                scale = min(size.width() / self._virtual.width(), size.height() / self._virtual.height())
                self._view.resetTransform()
                self._view.scale(scale, scale)
            size = self._virtual
        rect = QRectF(0, 0, size.width(), size.height())
        self._scene.setSceneRect(rect)
        self._bg_item.setRect(rect)
        self._layout_pixmap()
        self._layout_video()
        self._position_marquee_vertically()
        self._layout_slide()
        self._layout_corner()

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

    # -- text slides -------------------------------------------------------- #

    def set_slide_style(self, style: dict) -> None:
        self._slide_style.update(style)
        self._apply_slide_style()

    def show_slide(self, title: str, subtitle: str = "", fade_ms: int = 300) -> None:
        """
        Put a name (and an optional line under it) over whatever is running.

        Drawn into the same scene as the background, so it composites over live
        video - which is the whole reason the outputs stopped using QVideoWidget.
        """
        self._slide_title.setText(title)
        self._slide_subtitle.setText(subtitle)
        self._apply_slide_style()
        self._layout_slide()
        for item in self._slide_items():
            item.setVisible(True)
        self._slide_scrim.setVisible(bool(self._slide_style.get("scrim")))
        self._slide_wanted = True
        self._fade_slide_to(1.0, fade_ms)

    def hide_slide(self, fade_ms: int = 300) -> None:
        if not self._slide_wanted and self._slide_opacity <= 0.0:
            return
        self._slide_wanted = False
        self._fade_slide_to(0.0, fade_ms)

    def slide_visible(self) -> bool:
        """Whether a slide is meant to be on screen - true from the moment it is
        asked for, not only once the fade-in has ticked."""
        return self._slide_wanted or self._slide_opacity > 0.01

    def _slide_items(self):
        return (self._slide_scrim, self._slide_title, self._slide_subtitle)

    def _fade_slide_to(self, target: float, fade_ms: int) -> None:
        self._slide_anim.stop()
        if fade_ms <= 0:
            self._set_slide_opacity(target)
            self._after_slide_fade()
            return
        self._slide_anim.setDuration(max(60, fade_ms))
        self._slide_anim.setStartValue(float(self._slide_opacity))
        self._slide_anim.setEndValue(float(target))
        self._slide_anim.start()

    def _set_slide_opacity(self, value) -> None:
        self._slide_opacity = float(value)
        for item in self._slide_items():
            item.setOpacity(self._slide_opacity)

    def _after_slide_fade(self) -> None:
        if not self._slide_wanted and self._slide_opacity <= 0.01:
            for item in self._slide_items():
                item.setVisible(False)

    def _apply_slide_style(self) -> None:
        style = self._slide_style
        for item, colour_key in ((self._slide_title, "colour"),
                                 (self._slide_subtitle, "subtitle_colour")):
            item.setBrush(QBrush(QColor(style.get(colour_key, "#ffffff"))))
            item.setPen(QPen(Qt.NoPen))
        self._layout_slide()

    def _fit_text(self, item, requested_px: int, available: float) -> None:
        """
        Size the text, shrinking it if the line is too long for the screen.

        A name that does not fit used to be chopped off at both edges, which is
        not something anyone wants to discover during an awards ceremony.
        """
        style = self._slide_style
        font = QFont()
        if style.get("family"):
            font.setFamily(style["family"])
        font.setBold(item is self._slide_title)
        size = max(8, int(requested_px))
        font.setPixelSize(size)
        item.setFont(font)
        if not item.text() or available <= 0:
            return
        width = item.boundingRect().width()
        if width <= available:
            return
        fitted = max(10, int(size * available / width))
        font.setPixelSize(fitted)
        item.setFont(font)

    def _layout_slide(self) -> None:
        rect = self._scene.sceneRect()
        if rect.isEmpty():
            return
        available = rect.width() * 0.92
        self._fit_text(self._slide_title, self._slide_style.get("title_px", 84), available)
        self._fit_text(self._slide_subtitle, self._slide_style.get("subtitle_px", 44), available)
        title_rect = self._slide_title.boundingRect()
        sub_rect = self._slide_subtitle.boundingRect() if self._slide_subtitle.text() else QRectF()

        gap = title_rect.height() * 0.18 if sub_rect.height() else 0
        block = title_rect.height() + gap + sub_rect.height()

        position = self._slide_style.get("position", "middle")
        if position == "top":
            top = rect.height() * 0.10
        elif position == "bottom":
            top = rect.height() - block - rect.height() * 0.12
        else:
            top = (rect.height() - block) / 2.0
        top = max(0.0, min(top, max(0.0, rect.height() - block)))

        self._slide_title.setPos((rect.width() - title_rect.width()) / 2.0, top)
        if sub_rect.height():
            self._slide_subtitle.setPos((rect.width() - sub_rect.width()) / 2.0,
                                        top + title_rect.height() + gap)

        pad = max(18.0, block * 0.22)
        self._slide_scrim.setRect(QRectF(0, max(0.0, top - pad), rect.width(),
                                         min(rect.height(), block + pad * 2)))

    # -- transitions -------------------------------------------------------- #

    def transition(self, action: Callable[[], None], fade_ms: int, style: str) -> None:
        """Crossfades happen inside the scene; dips still use the black overlay window."""
        if fade_ms > 0 and style == TRANSITION_CROSSFADE:
            still = self.snapshot()       # includes a dissolve already in progress
            if not still.isNull():
                self._still_anim.stop()
                self._still_item.setPixmap(still)
                self._still_item.setPos(0, 0)
                self._still_item.setOpacity(1.0)
                self._still_item.setVisible(True)
                action()                  # the new picture is built underneath, unseen
                # a video's first frame needs a moment to land; a picture is there at once
                hold = 90 if self._video_item.isVisible() else 0
                self._still_anim.setDuration(max(60, fade_ms))
                self._still_anim.setStartValue(1.0)
                self._still_anim.setEndValue(0.0)
                QTimer.singleShot(hold, self._still_anim.start)
                return
        super().transition(action, fade_ms, style)

    def _after_dissolve(self) -> None:
        self._still_item.setVisible(False)
        self._still_item.setPixmap(QPixmap())

    def snapshot(self) -> QPixmap:
        """
        A still of exactly what this screen is showing, video included.

        This is the piece a crossfade is built on, and the reason every output
        goes through a graphics scene rather than a QVideoWidget.
        """
        if self._virtual is not None:
            # scene coordinates are the stage's; a grab of the small view would not fit them
            self._still_item.setVisible(False)
            still = self.preview(self._virtual)
            return still
        try:
            return self.grab()
        except Exception:
            return QPixmap()

    def set_corner_text(self, text: str, colour: str = "#ffffff") -> None:
        """Small text in the bottom-right corner - the speaker's time left. "" takes it away."""
        self._corner_text.setText(text)
        self._corner_text.setBrush(QBrush(QColor(colour or "#ffffff")))
        self._corner_text.setPen(QPen(Qt.NoPen))
        shown = bool(text)
        self._corner_text.setVisible(shown)
        self._corner_scrim.setVisible(shown)
        self._layout_corner()

    def corner_text(self) -> str:
        return self._corner_text.text() if self._corner_text.isVisible() else ""

    def _layout_corner(self) -> None:
        rect = self._scene.sceneRect()
        if rect.isEmpty() or not self._corner_text.text():
            return
        wide = rect.width() / max(1.0, rect.height()) > 4
        font = QFont("Segoe UI")
        font.setBold(True)
        font.setPixelSize(max(14, int(rect.height() * (0.62 if wide else 0.075))))
        self._corner_text.setFont(font)
        box = self._corner_text.boundingRect()
        pad = font.pixelSize() * 0.3
        x = rect.width() - box.width() - pad * 2
        y = rect.height() - box.height() - (pad * 0.2 if wide else pad * 1.5)
        self._corner_text.setPos(x, y)
        self._corner_scrim.setRect(QRectF(x - pad, y - pad * 0.2, box.width() + pad * 2, box.height() + pad * 0.4))

    def set_backdrop(self, pixmap: Optional[QPixmap]) -> None:
        """A still picture as the background, stretched to the screen - for previews."""
        self.engine.clear()
        self._video_item.setVisible(False)
        self._scale_mode = ScaleMode.STRETCH
        self._pixmap_item.setPixmap(pixmap if pixmap is not None else QPixmap())
        self._pixmap_item.setVisible(pixmap is not None and not pixmap.isNull())
        self._layout_pixmap()

    def slide_state(self) -> Optional[tuple]:
        """The name on screen (title, subtitle), or None."""
        if not self._slide_wanted:
            return None
        return (self._slide_title.text(), self._slide_subtitle.text())

    def preview(self, size: QSize) -> QPixmap:
        """
        A small picture of this screen for the dashboard's multiview, drawn
        straight from the scene - about 9 ms for a 1080p video, so a few a
        second cost nothing noticeable.
        """
        pixmap = QPixmap(size)
        pixmap.fill(Qt.black)
        rect = self._scene.sceneRect()
        if rect.isEmpty():
            return pixmap
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        self._scene.render(painter, QRectF(0, 0, size.width(), size.height()), rect, Qt.IgnoreAspectRatio)
        painter.end()
        return pixmap

    def has_picture(self) -> bool:
        """Whether anything but black is on this screen."""
        return (self._pixmap_item.isVisible() or self._video_item.isVisible() or self.slide_visible()
                or self.is_marquee_running() or self._bg_color.value() > 45)


class StandardOutputWindow(SceneOutputWindow):
    """Main Stage / Side Screens: a plain full-frame output."""


class TopOutputWindow(SceneOutputWindow):
    """
    The ceiling LED strip.

    Identical machinery to any other output; this is where the marquee is
    actually used, composited over whatever background is running.
    """


# --------------------------------------------------------------------------- #
# Rehearsal
# --------------------------------------------------------------------------- #

class AspectHolder(QWidget):
    """Keeps one child at a fixed shape, centred, however the space around it changes."""

    def __init__(self, child: QWidget, aspect: float) -> None:
        super().__init__()
        self.child = child
        self.aspect = aspect
        child.setParent(self)
        self.setMinimumSize(120, 20)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        width, height = self.width(), self.height()
        child_w = min(width, height * self.aspect)
        child_h = child_w / self.aspect
        # centred across, but right under its caption
        self.child.setGeometry(int((width - child_w) / 2), 0, max(1, int(child_w)), max(1, int(child_h)))


class RehearsalMonitor(QWidget):
    """
    Rehearsal: the three stage screens in one window on the desk.

    While it is open the dashboard drives these instead of the stage - presets,
    the running order, names, slides - at the stage's real sizes, scaled down.
    The hall keeps whatever it had, and new sounds stay silent (or go to a
    device of the operator's choosing, headphones say).
    """

    endRequested = Signal()
    soundChosen = Signal(str)          # "" = silent, else a device description

    def __init__(self, sizes: Dict[str, QSize]) -> None:
        super().__init__(None, Qt.Window)
        self.setWindowTitle("Rehearsal - nothing reaches the stage")
        if os.path.exists(ICON_FILE):
            self.setWindowIcon(QIcon(ICON_FILE))
        self.resize(1200, 760)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        tag = QLabel("REHEARSAL")
        tag.setStyleSheet(f"color: {THEME['rehearse']}; font-weight: 800; letter-spacing: 1px;"
                          f"border: 1px solid {THEME['rehearse']}; border-radius: 9px; padding: 3px 10px;")
        head.addWidget(tag)
        note = QLabel("The dashboard drives these screens now; the hall keeps what it had. "
                      "Slides show as pictures here.")
        note.setObjectName("cardHint")
        head.addWidget(note, 1)
        head.addWidget(QLabel("Sound"))
        self.sound_combo = QComboBox()
        self.sound_combo.addItem("Silent", "")
        from PySide6.QtMultimedia import QMediaDevices
        for device in QMediaDevices.audioOutputs():
            self.sound_combo.addItem(device.description(), device.description())
        self.sound_combo.setToolTip("New sounds started while rehearsing: silent, or on a device of your choice\n"
                                    "(headphones) - never the hall unless you pick it.")
        self.sound_combo.currentIndexChanged.connect(
            lambda _i: self.soundChosen.emit(self.sound_combo.currentData() or ""))
        head.addWidget(self.sound_combo)
        end = QPushButton("  End rehearsal")
        end.setIcon(Icons.get("close", CLR_TEXT, 15))
        end.clicked.connect(self.endRequested.emit)
        head.addWidget(end)
        root.addLayout(head)

        self.outputs: Dict[str, SceneOutputWindow] = {}
        screens = QHBoxLayout()
        screens.setSpacing(12)
        strip = QVBoxLayout()
        for role, cls in ((ROLE_MAIN, StandardOutputWindow), (ROLE_SIDES, StandardOutputWindow),
                          (ROLE_TOP, TopOutputWindow)):
            window = cls(f"{ROLE_LABELS[role]} (rehearsal)")
            window.setWindowFlags(Qt.Widget)
            window.setCursor(Qt.ArrowCursor)
            window.setFocusPolicy(Qt.NoFocus)
            window._view.setFocusPolicy(Qt.NoFocus)
            size = sizes[role]
            window.set_virtual_size(size)
            self.outputs[role] = window
            box = QVBoxLayout()
            box.setSpacing(4)
            caption = QLabel(f"{ROLE_LABELS[role].upper()}   {size.width()}×{size.height()}")
            caption.setObjectName("sectionTitle")
            box.addWidget(caption)
            box.addWidget(AspectHolder(window, size.width() / max(1, size.height())), 1)
            if role == ROLE_TOP:
                strip.addLayout(box)
            else:
                screens.addLayout(box, 1)
        root.addLayout(screens, 5)
        root.addLayout(strip, 1)

    def closeEvent(self, event) -> None:  # noqa: N802
        event.ignore()                     # closing the window ends the rehearsal properly
        self.endRequested.emit()


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
        self.caption.setText("drop media here  ·  or click to browse")
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
        self.setToolTip("Click an entry to put it on the screen · drag to reorder")
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
                    f"{path}\n\nNo frame could be read from this clip, so it will most "
                    "likely not play on stage.\nConvert it to H.264 MP4 before the show."
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


# --------------------------------------------------------------------------- #
# Output card (live controls for one output)
# --------------------------------------------------------------------------- #

class CuePad(QFrame):
    """
    One sound cue as a small player: play/pause, stop, and a seek bar.

    It used to be a single toggle that always restarted from zero - fine for a
    two-second fanfare, useless for the anthem. Clicking the body still plays or
    pauses, because that is the fast path when a name has just been read out.
    """

    assignRequested = Signal(str)
    playPauseRequested = Signal()
    stopRequested = Signal()
    seekRequested = Signal(int)
    cleared = Signal()
    loopToggled = Signal(bool)

    def __init__(self, index: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.index = index
        self.setObjectName("cuePad")
        self.setAcceptDrops(True)
        self.setProperty("playing", "false")
        self.setProperty("paused", "false")
        self.setProperty("filled", "false")
        self.setFixedHeight(76)
        self.setMinimumWidth(140)
        self._scrubbing = False
        self._duration = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 6, 9, 7)
        layout.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(3)
        self.key_label = QLabel("F" + str(index + 1))
        self.key_label.setObjectName("cueKey")
        top.addWidget(self.key_label)
        top.addStretch(1)

        self.loop_btn = icon_button("repeat", "Loop this cue", CLR_MUTED, 13)
        self.loop_btn.setObjectName("ghost")
        self.loop_btn.setCheckable(True)
        self.loop_btn.setFixedSize(19, 19)
        self.loop_btn.toggled.connect(self.loopToggled.emit)
        top.addWidget(self.loop_btn)

        self.clear_btn = icon_button("close", "Empty this cue", CLR_MUTED, 12)
        self.clear_btn.setObjectName("ghost")
        self.clear_btn.setFixedSize(19, 19)
        self.clear_btn.clicked.connect(self.cleared.emit)
        top.addWidget(self.clear_btn)
        layout.addLayout(top)

        self.name_label = QLabel()
        self.name_label.setObjectName("cueName")
        layout.addWidget(self.name_label)

        transport = QHBoxLayout()
        transport.setSpacing(4)
        self.play_btn = icon_button("play", "Play / pause", CLR_TEXT, 13)
        self.play_btn.setObjectName("ghost")
        self.play_btn.setFixedSize(21, 19)
        self.play_btn.clicked.connect(self.playPauseRequested.emit)
        transport.addWidget(self.play_btn)

        self.stop_btn = icon_button("stop", "Stop and rewind", CLR_MUTED, 12)
        self.stop_btn.setObjectName("ghost")
        self.stop_btn.setFixedSize(21, 19)
        self.stop_btn.clicked.connect(self.stopRequested.emit)
        transport.addWidget(self.stop_btn)

        self.time_label = QLabel()
        self.time_label.setObjectName("timecode")
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        transport.addWidget(self.time_label, 1)
        layout.addLayout(transport)

        self.scrub = QSlider(Qt.Horizontal)
        self.scrub.setObjectName("scrub")
        self.scrub.setRange(0, 1)
        self.scrub.setFixedHeight(12)
        self.scrub.setToolTip("Position - drag to move through the sound")
        self.scrub.sliderPressed.connect(lambda: setattr(self, "_scrubbing", True))
        self.scrub.sliderReleased.connect(self._on_scrub_released)
        layout.addWidget(self.scrub)

        self.show_cue(None)

    # -- display ------------------------------------------------------------ #

    def _restyle(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)

    def show_cue(self, cue: Optional[SoundCue]) -> None:
        filled = bool(cue and cue.path)
        playing = bool(cue and cue.is_playing())
        paused = bool(cue and cue.is_paused())

        # This runs four times a second for all eight pads. Re-polishing a
        # widget re-resolves the whole stylesheet, so the heavy part only runs
        # when something the pad shows has actually changed.
        key = (filled, playing, paused, cue.path if filled else "",
               bool(cue and cue.loop), self.width())
        if key == getattr(self, "_shown_key", None):
            if filled:
                self._show_position(cue)
            return
        self._shown_key = key

        if filled:
            metrics = self.name_label.fontMetrics()
            self.name_label.setText(
                metrics.elidedText(cue.label(), Qt.ElideRight, max(70, self.width() - 24)))
            self.setToolTip(cue.path + "\n\nF" + str(self.index + 1)
                            + " plays and pauses, Shift+F" + str(self.index + 1) + " stops")
        else:
            self.name_label.setText("drop a sound")
            self.setToolTip("Drop a sound file here, or click to choose one for F"
                            + str(self.index + 1))

        if filled:
            self._show_position(cue)
        else:
            self._duration = 0
            self.scrub.setRange(0, 1)
            self.scrub.setValue(0)
            self.time_label.setText("")

        self.play_btn.setIcon(Icons.get("pause" if playing else "play",
                                        CLR_TEXT if filled else CLR_LINE, 13))
        for widget in (self.play_btn, self.stop_btn):
            widget.setEnabled(filled)
        # An empty pad shows no transport at all: a dead position bar on seven
        # unused pads was just noise along the bottom of the window.
        self.scrub.setVisible(filled)
        self.play_btn.setVisible(filled)
        self.stop_btn.setVisible(filled)
        self.clear_btn.setVisible(filled)
        self.loop_btn.setVisible(filled)
        self.loop_btn.blockSignals(True)
        self.loop_btn.setChecked(bool(cue and cue.loop))
        self.loop_btn.blockSignals(False)
        self.loop_btn.setIcon(
            Icons.get("repeat", CLR_ACCENT if (cue and cue.loop) else CLR_MUTED, 13))

        self.setProperty("filled", "true" if filled else "false")
        self.setProperty("playing", "true" if playing else "false")
        self.setProperty("paused", "true" if paused else "false")
        self._restyle()

    def _show_position(self, cue: SoundCue) -> None:
        duration = cue.duration()
        if duration != self._duration:
            self._duration = duration
            self.scrub.setRange(0, max(1, duration))
            if duration > 0:
                # the duration arrives after loading: the key above cannot see it
                self._shown_key = None
        if duration <= 0:
            return
        position = cue.position()
        if not self._scrubbing and self.scrub.value() != position:
            self.scrub.setValue(position)
        text = format_time(position) + " / " + format_time(duration)
        if self.time_label.text() != text:
            self.time_label.setText(text)

    @Slot()
    def _on_scrub_released(self) -> None:
        self._scrubbing = False
        if self._duration > 0:
            self.seekRequested.emit(self.scrub.value())

    # -- interaction -------------------------------------------------------- #

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            if self.property("filled") == "true":
                self.playPauseRequested.emit()
            else:
                chooser = "Sound files (" + " ".join(
                    sorted("*" + e for e in AUDIO_EXTENSIONS)) + ");;All files (*.*)"
                path, _ = QFileDialog.getOpenFileName(
                    self, "Sound for F" + str(self.index + 1), "", chooser)
                if path:
                    self.assignRequested.emit(os.path.normpath(path))
        event.accept()

    @staticmethod
    def _sound_from(mime) -> Optional[str]:
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = os.path.normpath(url.toLocalFile())
            if os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS:
                return path
        return None

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._sound_from(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._sound_from(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        path = self._sound_from(event.mimeData())
        if not path:
            event.ignore()
            return
        self.assignRequested.emit(path)
        event.acceptProposedAction()


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
        title = QLabel("MEDIA LIBRARY")
        title.setObjectName("sectionTitle")
        bar.addWidget(title)

        self.places = QComboBox()
        self.places.setMinimumWidth(240)
        self.places.setToolTip("Pinned folders")
        self.places.activated.connect(self._on_place_chosen)
        bar.addWidget(self.places)

        pin = QPushButton("  Pin this folder")
        pin.setIcon(Icons.get("plus", CLR_TEXT, 15))
        pin.setToolTip("Keep this folder in the list above")
        pin.clicked.connect(self._pin_current)
        bar.addWidget(pin)

        unpin = QPushButton("  Unpin")
        unpin.setIcon(Icons.get("minus", CLR_TEXT, 15))
        unpin.clicked.connect(self._unpin_current)
        bar.addWidget(unpin)

        build = QPushButton("  Build a show from a folder…")
        build.setIcon(Icons.get("folder", CLR_TEXT, 15))
        build.setToolTip("Scan an event folder and sort everything onto the right screens")
        build.clicked.connect(self.buildRequested.emit)
        bar.addWidget(build)

        browse = QPushButton("  Open folder…")
        browse.setIcon(Icons.get("open", CLR_TEXT, 15))
        browse.clicked.connect(self._browse_folder)
        bar.addWidget(browse)

        bar.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("filter by name…")
        self.search.setMaximumWidth(220)
        self.search.textChanged.connect(lambda _t: self._fill_files())
        bar.addWidget(self.search)

        refresh = icon_button("refresh", "Re-read this folder", CLR_MUTED, 16)
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
        self.selection_label = QLabel("nothing selected")
        self.selection_label.setObjectName("cardHint")
        self.selection_label.setMinimumWidth(150)
        actions.addWidget(self.selection_label)
        self.fav_button = QPushButton("  ☆ Favourite")
        self.fav_button.setToolTip("Keep the selected files under ★ Favourites, whichever folder they are in")
        self.fav_button.clicked.connect(self._toggle_favourite)
        actions.addWidget(self.fav_button)

        actions.addSpacing(10)
        show_caption = QLabel("Show now on")
        show_caption.setObjectName("cardHint")
        actions.addWidget(show_caption)
        self.show_buttons: Dict[str, QPushButton] = {}
        for role in STAGE_ROLES:
            button = QPushButton(ROLE_LABELS[role])
            button.clicked.connect(lambda _c=False, r=role: self._send(r))
            actions.addWidget(button)
            self.show_buttons[role] = button

        actions.addSpacing(14)
        queue_caption = QLabel("Add to playlist")
        queue_caption.setObjectName("cardHint")
        actions.addWidget(queue_caption)
        self.queue_buttons: Dict[str, QPushButton] = {}
        for role in STAGE_ROLES:
            button = QPushButton(ROLE_LABELS[role])
            button.clicked.connect(lambda _c=False, r=role: self._queue(r))
            actions.addWidget(button)
            self.queue_buttons[role] = button

        actions.addSpacing(14)
        cue_caption = QLabel("Sound cue")
        cue_caption.setObjectName("cardHint")
        actions.addWidget(cue_caption)
        self.cue_slot = QComboBox()
        for slot in range(SOUND_SLOTS):
            self.cue_slot.addItem(f"F{slot + 1}", slot)
        actions.addWidget(self.cue_slot)
        self.cue_button = QPushButton("Assign")
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
        self.places.addItem("★  Favourites", FAVOURITES)
        # An unpinned folder still gets an entry, otherwise the picker goes blank
        # and it looks as though nothing is open.
        if self._folder and self._folder not in self._pinned and not self._show_favourites:
            self.places.addItem(
                (os.path.basename(self._folder) or self._folder) + "   (not pinned)", self._folder)
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
        folder = QFileDialog.getExistingDirectory(self, "Open a media folder", self._folder or "")
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
            item = QListWidgetItem("..  up one level")
            item.setData(Qt.UserRole, parent)
            item.setIcon(Icons.get("folder", CLR_MUTED, 16))
            self.folders.addItem(item)
        try:
            entries = sorted(
                (e for e in os.scandir(self._folder) if e.is_dir() and not e.name.startswith(".")),
                key=lambda e: e.name.lower())
        except OSError as exc:
            self.path_label.setText(f"{self._folder}   —   cannot read: {exc}")
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
            item.setToolTip(path + "\n\nDrag it onto a screen in the header, or onto a card, to show it.")
            item.setIcon(self._thumb_for(path, extension))
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self.files.addItem(item)
            shown += 1

        note = f"{where}      {shown} item(s)"
        if shown >= self.MAX_ITEMS:
            note += f"  —  showing the first {self.MAX_ITEMS}, use the filter to narrow it"
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
            self.selection_label.setText("nothing selected")
        elif len(paths) == 1:
            self.selection_label.setText(os.path.basename(paths[0]))
        else:
            self.selection_label.setText(f"{len(paths)} items selected")

        starred = {os.path.normcase(p) for p in self._favourites}
        self.fav_button.setEnabled(bool(paths))
        self.fav_button.setText("  ★ Unfavourite" if paths and all(os.path.normcase(p) in starred for p in paths)
                                else "  ☆ Favourite")
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
        name = QLabel(title)
        name.setObjectName("cardTitle")
        hint = QLabel(subtitle)
        hint.setObjectName("cardSub")
        title_box.addWidget(name)
        title_box.addWidget(hint)
        header.addLayout(title_box)
        header.addStretch(1)

        self.state_badge = QLabel("CLOSED")
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
        self.scrub.setToolTip("Playback position — drag to seek")
        self.scrub.sliderPressed.connect(lambda: setattr(self, "_scrubbing", True))
        self.scrub.sliderReleased.connect(self._on_scrub_released)
        scrub_row.addWidget(self.scrub, 1)

        self.timecode = QLabel("–:––")
        self.timecode.setObjectName("timecode")
        self.timecode.setMinimumWidth(78)
        self.timecode.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.timecode.setToolTip("Elapsed / total")
        scrub_row.addWidget(self.timecode)
        self.root.addLayout(scrub_row)

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
        queue_title = QLabel("Playlist")
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
        self.state_badge.setText("OPEN" if is_open else "CLOSED")
        self.state_badge.setObjectName("badgeLive" if is_open else "badgeOff")
        self.state_badge.setToolTip(
            "This screen's output window is open" if is_open else
            "No output window — press OPEN OUTPUTS"
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
        self.clearRequested.emit()      # first: an undo can still see what was there
        self.reset_file()

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

        # One row for the heading, the typeface and both colours: the card is
        # the tallest on the Live tab and has to fit a 1080p screen with
        # finger-sized controls.
        font_row = QHBoxLayout()
        font_row.setSpacing(6)
        glyph = QLabel()
        glyph.setPixmap(Icons.get("text", CLR_MUTED, 14).pixmap(14, 14))
        glyph.setToolTip("Marquee")
        font_row.addWidget(glyph)
        label = QLabel("Marquee")
        label.setObjectName("sectionTitle")
        font_row.addWidget(label)
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
        self.text_preview.setToolTip("Text colour")
        font_row.addWidget(self.text_preview)
        font_row.addSpacing(4)
        bg_btn = icon_button("palette", "Solid colour background for this screen", CLR_MUTED, 15)
        bg_btn.setObjectName("ghost")
        bg_btn.clicked.connect(self._pick_background)
        font_row.addWidget(bg_btn)
        self.bg_preview = QLabel()
        self.bg_preview.setFixedSize(16, 16)
        self.bg_preview.setToolTip("Background colour")
        font_row.addWidget(self.bg_preview)
        self.root.addLayout(font_row)
        self._update_swatch(self.text_preview, self._text_color)
        self._update_swatch(self.bg_preview, self._bg_color)

        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText("Text to scroll across the strip…")
        self.text_edit.textChanged.connect(self.marqueeTextChanged.emit)

        # the text, its speed and Start / Stop share one row: the card is the
        # tallest on the Live tab, and the Live tab has to fit a 1080p desk
        speed_row = QHBoxLayout()
        speed_row.setSpacing(8)
        speed_row.addWidget(self.text_edit, 3)
        speed_caption = QLabel("Speed")
        speed_caption.setObjectName("cardHint")
        speed_row.addWidget(speed_caption)
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(20, 800)
        self.speed_slider.setValue(180)
        self.speed_slider.valueChanged.connect(self._on_speed)
        self.speed_slider.setMinimumWidth(70)
        speed_row.addWidget(self.speed_slider, 1)
        self.speed_label = QLabel("180 px/s")
        self.speed_label.setObjectName("cardHint")
        self.speed_label.setMinimumWidth(58)
        speed_row.addWidget(self.speed_label)
        start = QPushButton("  Start")
        start.setIcon(Icons.get("play", CLR_TEXT))
        start.setToolTip("Start scrolling the text across the strip")
        start.clicked.connect(self.marqueeStart.emit)
        stop = QPushButton("  Stop")
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

class EventFolderDialog(QDialog):
    """
    What the app worked out about an event folder, before it acts on it.

    Nothing is applied until the operator has seen the list and can change any
    row - an import that silently guessed wrong would be worse than no import.
    """

    DEST_LABELS = (
        ("Main Stage", ROLE_MAIN),
        ("Side Screens", ROLE_SIDES),
        ("Top Screen", ROLE_TOP),
        ("Sound cue", "sound"),
        ("Skip", "skip"),
    )

    def __init__(self, folder: str, rows: List[tuple], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Build a show from a folder")
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
                combo.addItem(label, value)
            combo.setCurrentIndex(max(0, combo.findData(role)))
            combo.currentIndexChanged.connect(lambda _i: self._update_summary())
            self.table.setCellWidget(index, 2, combo)
            self.combos.append(combo)

        layout.addWidget(self.table, 1)

        self.replace_check = QCheckBox("Clear the current show first")
        self.replace_check.setChecked(True)
        layout.addWidget(self.replace_check)

        self.go_live_check = QCheckBox("Put the first item of each screen on straight away")
        layout.addWidget(self.go_live_check)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        build = QPushButton("  Build the show")
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
                parts.append(f"{counts[value]} \u2192 {label}")
        self.summary.setText("   \u00b7   ".join(parts) if parts else "nothing to import")

    def assignments(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        for (path, _size, _role), combo in zip(self._rows, self.combos):
            destination = combo.currentData()
            if destination == "skip":
                continue
            result.setdefault(destination, []).append(path)
        return result


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
        grip.setToolTip("Drag to move")
        top.addWidget(grip)
        top.addSpacing(2)

        self.screen_buttons: Dict[str, QPushButton] = {}
        for role, short in ((ROLE_MAIN, "Main"), (ROLE_SIDES, "Sides"), (ROLE_TOP, "Top")):
            button = QPushButton(short)
            button.setObjectName("miniScreen")
            button.setCheckable(True)
            button.setToolTip(f"Arrows and play act on {ROLE_LABELS[role]}")
            button.clicked.connect(lambda _c=False, r=role: self.screenChosen.emit(r))
            top.addWidget(button)
            self.screen_buttons[role] = button

        top.addSpacing(4)
        prev_btn = icon_button("prev", "Previous in that screen's playlist", CLR_TEXT, 15)
        prev_btn.clicked.connect(lambda: self.stepRequested.emit(-1))
        top.addWidget(prev_btn)

        self.play_btn = icon_button("play", "Play / pause that screen", CLR_TEXT, 15)
        self.play_btn.clicked.connect(self.playPauseRequested.emit)
        top.addWidget(self.play_btn)

        next_btn = icon_button("next", "Next in that screen's playlist", CLR_TEXT, 15)
        next_btn.clicked.connect(lambda: self.stepRequested.emit(1))
        top.addWidget(next_btn)

        top.addSpacing(6)
        self.now_label = QLabel()
        self.now_label.setObjectName("miniNow")
        self.now_label.setMinimumWidth(210)
        top.addWidget(self.now_label, 1)

        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(140)
        self.preset_combo.setToolTip("Saved shows")
        top.addWidget(self.preset_combo)

        load = QPushButton("Load")
        load.setObjectName("primary")
        load.setToolTip("Put this preset on the screens")
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

        quiet = QPushButton("  Silence")
        quiet.setIcon(Icons.get("mute", CLR_DIM, 15))
        quiet.setToolTip("Fade out every sound cue")
        quiet.clicked.connect(self.stopSoundRequested.emit)
        bottom.addWidget(quiet)

        blackout = QPushButton("BLACKOUT")
        blackout.setObjectName("danger")
        blackout.clicked.connect(self.blackoutRequested.emit)
        bottom.addWidget(blackout)

        expand = icon_button("expand", "Back to the full dashboard", CLR_DIM, 16)
        expand.clicked.connect(self.expandRequested.emit)
        bottom.addWidget(expand)
        body.addLayout(bottom)

        # --- row 3: the running order, when there is one -------------------- #
        self.show_row = QWidget()
        show = QHBoxLayout(self.show_row)
        show.setContentsMargins(0, 0, 0, 0)
        show.setSpacing(6)
        back = icon_button("prev", "Back one step (Page Up)", CLR_TEXT, 15)
        back.clicked.connect(self.showBackRequested.emit)
        show.addWidget(back)
        self.show_label = QLabel()
        self.show_label.setObjectName("miniNow")
        show.addWidget(self.show_label, 1)
        self.show_next = QPushButton("  NEXT")
        self.show_next.setObjectName("primary")
        self.show_next.setIcon(Icons.get("next", "#0b0e13", 15))
        self.show_next.setToolTip("Run the next step of the running order (Page Down)")
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
            self.preset_combo.addItem("no presets")
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
            button.setToolTip(cue.label() if filled else f"F{cue.index + 1} is empty")
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


class SlideStage:
    """
    What the presenter may do to the stage: put a slide on a screen, black it,
    and give the screen back to whatever its card holds when the talk ends.
    The card is never changed, so the background is exactly where it was.
    """

    def __init__(self, panel: "ControlPanel") -> None:
        self.panel = panel

    def label(self, role: str) -> str:
        return ROLE_LABELS.get(role, role)

    def size(self, role: str) -> QSize:
        window = self.panel._show_output(role)
        if window is not None and window.width() >= 640 and window.height() >= 360:
            return QSize(window.width(), window.height())
        return QSize(1920, 1080)

    def present(self, role: str, path: str, fade_ms: int) -> Optional[str]:
        panel = self.panel
        window = panel._show_output(role)
        if window is None and panel.routing_rows[role].screen_combo.currentData():
            panel._apply_routing()
            window = panel._show_output(role)
        if window is None:
            return f"{self.label(role)} has no monitor - pick one on Screens & Setup."
        window.set_scale_mode(ScaleMode.FIT)
        try:
            window.present(path, fade_ms, TRANSITION_CROSSFADE)
        except MediaProblem as problem:
            return f"{problem.title}: {os.path.basename(path)}"
        return None

    def clear(self, role: str, fade_ms: int) -> None:
        window = self.panel._show_output(role)
        if window is not None:
            window.fade_clear(fade_ms)

    # -- PowerPoint's own slide show on a stage screen ------------------------ #
    def _rect(self, role: str) -> Optional[QRect]:
        window = self.panel._show_output(role)
        if window is not None and window.isVisible():
            return QRect(window.mapToGlobal(QPoint(0, 0)), window.size())
        name = self.panel.routing_rows[role].screen_combo.currentData()
        screen = next((s for s in QGuiApplication.screens() if s.name() == name), None)
        return screen.geometry() if screen is not None else None

    def points(self, role: str) -> Optional[QRectF]:
        """Where PowerPoint should put its slide show, in points (logical pixels x 0.75)."""
        rect = self._rect(role)
        if rect is None:
            return None
        return QRectF(rect.x() * 0.75, rect.y() * 0.75, rect.width() * 0.75, rect.height() * 0.75)

    def make_room(self, role: str) -> None:
        """Stage windows kept on top would hide PowerPoint: let them sit under it for now."""
        rect = self._rect(role)
        self._lowered = []
        if rect is None or sys.platform != "win32":
            return
        for other in STAGE_ROLES:
            window = self.panel._show_output(other)
            if (window is not None and window.isVisible() and window.geometry().intersects(rect)
                    and window.windowFlags() & Qt.WindowStaysOnTopHint):
                set_topmost(window, False)
                self._lowered.append(window)

    def give_back_room(self, role: str) -> None:
        for window in getattr(self, "_lowered", []):
            try:
                if window.isVisible() and window.windowFlags() & Qt.WindowStaysOnTopHint:
                    set_topmost(window, True)
            except RuntimeError:
                pass              # the window was rebuilt meanwhile
        self._lowered = []

    def refocus(self) -> None:
        """PowerPoint takes the focus when its show starts; the desk keeps it."""
        QTimer.singleShot(250, self.panel.activateWindow)

    def restore(self, role: str, fade_ms: int) -> None:
        panel = self.panel
        window = panel._show_output(role)
        if window is None:
            return
        card = panel.cards[role]
        window.set_scale_mode(card.current_scale_mode())
        path = card.current_path()
        if path and os.path.isfile(path):
            try:
                window.engine.set_loop(card.is_repeating())
                window.present(path, fade_ms, TRANSITION_CROSSFADE)
                return
            except MediaProblem:
                pass
        window.fade_clear(fade_ms)


# Windows hotkey plumbing, for a clicker that must work whichever window has focus.
WM_HOTKEY = 0x0312
VK_BY_NAME = {"PgDown": 0x22, "PgUp": 0x21}


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
        self.active_role = ROLE_MAIN
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self._freshly_opened: set = set()
        self.mini: Optional[MiniBar] = None
        self._mini_ticker = QTimer(self)
        self._mini_ticker.timeout.connect(self._refresh_mini)
        self.sound = SoundDeck(self)
        self.sound.failed.connect(self._on_cue_failed)
        self.loaded_preset: Optional[str] = None
        self._preset_dirty = False

        # Running order: where we are, and its own pair of players so one
        # step's music can fade out while the next one's fades in.
        self.show_index = -1
        self._show_started = 0.0
        self._show_auto: Optional[float] = None
        self._show_sound_started = False
        self._show_text_shown: Optional[tuple] = None
        self._show_players = [SoundCue(-1, self), SoundCue(-2, self)]
        self._show_active = 0
        self._show_timer = QTimer(self)
        self._show_timer.timeout.connect(self._show_tick)
        self.remote = remote_mod.RemoteServer(self.remote_state, self.remote_action, self,
                                              image=self._remote_slide_image)
        self._remote_dialog = None
        self._guest_dialog = None

        # Presentations: one presenter, driven by the dashboard, the clicker,
        # the keyboard, the phone and the running order alike.
        self.presenter = pres_mod.Presenter(SlideStage(self), self)
        self.presenter.in_powerpoint = str(self.settings.value("slides/powerpoint", "true")).lower() == "true"
        self.presenter.note.connect(self._on_presenter_note)
        self.presenter.changed.connect(self._on_presenter_changed)
        self._hotkeys: Dict[int, tuple] = {}
        self._slide_shortcuts: List[QShortcut] = []
        self._learned_shortcuts: List[QShortcut] = []
        self._was_live = False

        # The desk: SETUP / SHOW, and preview-then-TAKE with the change waiting.
        self.ui_mode = "setup"
        self.preview_first = str(self.settings.value("ui/preview_first", "false")).lower() == "true"
        self._pending_change: Optional[dict] = None
        self._direct_depth = 0          # >0 while a TAKE, a step or an undo is changing the stage
        self._ready_dialog = None
        self._undo_snapshot: Optional[dict] = None
        self._rehearsal: Optional[RehearsalMonitor] = None
        self._thumb_cache: Dict[tuple, QPixmap] = {}

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 8)
        root.setSpacing(9)
        root.addWidget(self._build_header())
        self.take_bar = desk_mod.TakeBar(Icons, THEME)
        self.take_bar.takeRequested.connect(self._take)
        self.take_bar.cancelRequested.connect(self._cancel_take)
        self.take_bar.undoRequested.connect(self._undo)
        root.addWidget(self.take_bar)
        self.preset_bar = self._build_preset_bar()
        root.addWidget(self.preset_bar)

        self.tabs = desk_mod.PageTabs()
        self.tabs.addTab(self._build_live_tab(), "  Live  ")
        self.tabs.addTab(self._build_show_tab(), "  Show  ")
        self.tabs.addTab(self._build_presentation_tab(), "  Slides  ")
        self.tabs.addTab(self._build_library_tab(), "  Library  ")
        self.tabs.addTab(self._build_text_tab(), "  Text  ")
        # The DJ desk is built the first time its tab opens: it starts an audio
        # engine, and a show that never uses it should not pay for one.
        self.dj_panel = None
        self.dj_page = QWidget()
        dj_layout = QVBoxLayout(self.dj_page)
        dj_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs.addTab(self.dj_page, "  DJ  ", scroll=False)   # the DJ desk sizes itself
        # "&&" because a single & would be swallowed as a keyboard mnemonic.
        self.screens_page = self._build_screens_tab()
        self.tabs.addTab(self.screens_page, "  Screens && Setup  ")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)
        # NOW / NEXT follows the operator onto every tab.
        self.show_strip = desk_mod.ShowStrip(Icons, THEME)
        self.show_strip.nextRequested.connect(self.show_next)
        self.show_strip.backRequested.connect(self.show_back)
        self.show_strip.openRequested.connect(lambda: self.tabs.setCurrentWidget(self.show_tab))
        root.addWidget(self.show_strip)
        self.setCentralWidget(central)

        app = QGuiApplication.instance()
        app.screenAdded.connect(lambda _s: self._refresh_screen_combos())
        app.screenRemoved.connect(lambda _s: self._refresh_screen_combos())

        self._refresh_screen_combos(initial=True)
        self._refresh_preset_combo()
        self._load_fade_setting()
        self._refresh_audio_devices()
        self._restore_library_places()
        self.sound_master.setValue(int(self.settings.value('sound/master', 90)))
        self._load_autostart_state()
        self._describe_preset_state()
        self._update_output_status()
        self._install_shortcuts()
        self.set_active_role(ROLE_MAIN)
        self._apply_touch_mode()
        self._restore_window_geometry()
        self._restore_remote()
        self._multiview_timer = QTimer(self)
        self._multiview_timer.timeout.connect(self._refresh_multiview)
        self._multiview_timer.start(500)
        self._set_mode(str(self.settings.value("ui/mode", "setup")), check=False)
        self._refresh_show_strip()

        self.health = desk_mod.HealthBar(THEME)
        self.health.checkRequested.connect(self._open_ready_check)
        self.health.helpRequested.connect(self._show_shortcuts)
        self.statusBar().addPermanentWidget(self.health)
        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._refresh_health)
        self._health_timer.start(2000)
        self._refresh_health()
        self.statusBar().showMessage(
            "Screens & Setup → assign monitors → OPEN OUTPUTS.   "
            "Then drop media onto a card, or build a playlist."
        )

    # ------------------------------------------------------------------ UI -- #

    def _build_header(self) -> QWidget:
        """
        Name and time; a live picture of every stage screen; and the controls
        that matter whatever tab is open - SETUP / SHOW, PREVIEW -> TAKE, the
        ready check, and BLACKOUT.
        """
        bar = QFrame()
        bar.setObjectName("bar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 6, 12, 6)
        layout.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(3)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(8)
        mark = QLabel()
        mark.setPixmap(Icons.get("monitor", CLR_ACCENT, 19).pixmap(19, 19))
        brand_row.addWidget(mark)
        title = QLabel("Stage Display")
        title.setObjectName("brand")
        brand_row.addWidget(title)
        brand_row.addStretch(1)
        left.addLayout(brand_row)
        # A wall clock the operator can glance at without leaving the app.
        self.clock = QLabel()
        self.clock.setObjectName("clock")
        self.clock.setToolTip("Current time")
        left.addWidget(self.clock)
        self.mode_note = QLabel()
        self.mode_note.setObjectName("keyHint")
        left.addWidget(self.mode_note)
        left.addStretch(1)
        layout.addLayout(left)
        self._tick_clock()
        clock_timer = QTimer(self)
        clock_timer.timeout.connect(self._tick_clock)
        clock_timer.start(1000)

        # What the audience sees, on every screen, all the time.
        aspects = {ROLE_MAIN: 16 / 9, ROLE_SIDES: 16 / 9,
                   ROLE_TOP: DEFAULT_TOP_WIDTH / DEFAULT_TOP_HEIGHT}
        self.multiview = desk_mod.MultiView({role: ROLE_LABELS[role] for role in STAGE_ROLES},
                                            aspects, THEME)
        for tile in self.multiview.tiles.values():
            tile.clicked.connect(self._on_tile_clicked)
            tile.filesDropped.connect(self._on_tile_files)
        layout.addWidget(self.multiview)
        layout.addStretch(1)

        # --- global actions ------------------------------------------------ #
        right = QVBoxLayout()
        right.setSpacing(8)
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        top_row.addStretch(1)
        self.mode_switch = desk_mod.ModeSwitch(THEME)
        self.mode_switch.modeChanged.connect(self._set_mode)
        top_row.addWidget(self.mode_switch)
        self.preview_btn = QPushButton("  PREVIEW → TAKE")
        self.preview_btn.setCheckable(True)
        self.preview_btn.setIcon(Icons.get("target", CLR_TEXT, 15))
        self.preview_btn.setToolTip(
            "On: a file, preset or name chosen by hand waits in PREVIEW until you press TAKE,\n"
            "so nothing reaches the stage by accident. NEXT in the running order goes straight on.")
        self.preview_btn.setChecked(self.preview_first)
        self.preview_btn.toggled.connect(self._set_preview_first)
        top_row.addWidget(self.preview_btn)
        self.rehearse_btn = QPushButton("  Rehearse")
        self.rehearse_btn.setCheckable(True)
        self.rehearse_btn.setIcon(Icons.get("play", CLR_TEXT, 15))
        self.rehearse_btn.setToolTip("Try the show out in a window on this desk: presets, running order, names and\n"
                                     "slides go there instead of the stage, and the hall keeps what it has.")
        self.rehearse_btn.clicked.connect(self._toggle_rehearsal)
        top_row.addWidget(self.rehearse_btn)
        ready = QPushButton("  Ready check")
        ready.setIcon(Icons.get("list", CLR_TEXT, 15))
        ready.setToolTip("Screens, sound, clicker, files - everything worth knowing before the doors open")
        ready.clicked.connect(self._open_ready_check)
        top_row.addWidget(ready)
        right.addLayout(top_row)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        bottom_row.addStretch(1)
        self.open_btn = QPushButton("  Open outputs")
        self.open_btn.setIcon(Icons.get("monitor", CLR_TEXT, 16))
        self.open_btn.setToolTip("Apply the Screens tab settings and open every stage window  (Ctrl+O)")
        self.open_btn.clicked.connect(self._apply_routing)
        bottom_row.addWidget(self.open_btn)

        blackout = QPushButton("  BLACKOUT")
        blackout.setObjectName("danger")
        blackout.setIcon(Icons.get("power", CLR_DANGER, 16))
        blackout.setMinimumWidth(150)
        blackout.setToolTip("Instantly clear every stage screen to black  (B)")
        blackout.clicked.connect(self._blackout_all)
        bottom_row.addWidget(blackout)

        shrink = icon_button("compress", "Shrink to a small bar that stays on top",
                             CLR_DIM, 16)
        shrink.setObjectName("ghost")
        shrink.clicked.connect(self.shrink_to_bar)
        bottom_row.addWidget(shrink)
        right.addLayout(bottom_row)
        layout.addLayout(right)
        # "Close outputs" deliberately lives on the Screens tab: an X in the
        # header corner reads like "quit the app" during a show.
        return bar

    # ------------------------------------------------------------ the desk -- #

    def _refresh_multiview(self) -> None:
        """What each stage screen shows right now, a couple of times a second."""
        if not self.isVisible() or self.isMinimized():
            return
        presenter = self.presenter
        rehearsing = getattr(self, "_rehearsal", None) is not None
        for role, tile in self.multiview.tiles.items():
            window = self._show_output(role)
            if window is None:
                tile.set_state(desk_mod.STATE_CLOSED, None, "closed - click to open")
                continue
            card = self.cards.get(role) if hasattr(self, "cards") else None
            if presenter.live and presenter.role == role and presenter.playing_in_powerpoint():
                pixmap = None
                if presenter.deck is not None and presenter.count() and not presenter.black:
                    pixmap = presenter.deck.thumb(presenter.index, 256)
                caption = (f"PowerPoint  ·  {presenter.index + 1} / {presenter.count() or '…'}"
                           + ("  ·  black" if presenter.black else ""))
                live = not presenter.black
            else:
                pixmap = window.preview(tile.preview_size())
                live = window.has_picture()
                parts = []
                if presenter.live and presenter.role == role and presenter.deck is not None:
                    parts.append(f"slides {presenter.index + 1}/{presenter.count()}")
                elif card is not None and card.current_path():
                    parts.append(os.path.basename(card.current_path()))
                if window.slide_visible():
                    parts.append("text")
                if role == ROLE_TOP and window.is_marquee_running():
                    parts.append("marquee")
                caption = "  +  ".join(parts) if parts else ("colour" if live else "black")
            state = desk_mod.STATE_REHEARSAL if rehearsing else (
                desk_mod.STATE_LIVE if live else desk_mod.STATE_BLACK)
            tile.set_state(state, pixmap, caption)

    @Slot(str)
    def _on_tile_clicked(self, role: str) -> None:
        self.set_active_role(role)
        if self._show_output(role) is not None:
            return
        if self.routing_rows[role].screen_combo.currentData():
            self._apply_routing()
        else:
            self.statusBar().showMessage(
                f"{ROLE_LABELS[role]} has no monitor - pick one on Screens & Setup.", 6000)

    @Slot(str, list)
    def _on_tile_files(self, role: str, paths: List[str]) -> None:
        """Files dropped on a screen in the header go on that screen."""
        media = [os.path.normpath(p) for p in paths
                 if os.path.isfile(p) and os.path.splitext(p)[1].lower() in (IMAGE_EXTENSIONS | VIDEO_EXTENSIONS)]
        if not media:
            self.statusBar().showMessage("Only pictures and videos can go on a screen.", 6000)
            return
        card = self.cards[role]
        card.playlist.add_paths(media, announce=False)
        self.set_active_role(role)
        card.loadRequested.emit(media[0])

    # -- SETUP / SHOW ---------------------------------------------------------- #

    @Slot(str)
    def _set_mode(self, mode: str, check: bool = True) -> None:
        """
        SETUP: everything can be prepared and edited. SHOW: the event is on -
        the library and the screen setup step away, and nothing can be deleted,
        renamed or rebuilt by a stray tap.
        """
        mode = "show" if mode == "show" else "setup"
        if mode == "show" and self._rehearsal is not None:
            self.end_rehearsal()
        self.ui_mode = mode
        self.settings.setValue("ui/mode", mode)
        show = mode == "show"
        self.mode_switch.set_mode(mode)
        setup_pages = (self.library, self.screens_page)
        if show and self.tabs.currentWidget() in setup_pages:
            self.tabs.setCurrentIndex(0)      # before hiding: Qt would pick a neighbour
        for page in setup_pages:
            index = self.tabs.indexOf(page)
            if index >= 0:
                self.tabs.setTabVisible(index, not show)
        self.open_btn.setVisible(not show)
        self.rehearse_btn.setVisible(not show)
        for widget in getattr(self, "_preset_edit_widgets", []):
            widget.setVisible(not show)
        self.show_tab.set_locked(show)
        if show:
            self.mode_note.setText("SHOW  ·  editing locked")
            self.mode_note.setStyleSheet(f"color: {CLR_DANGER}; font-weight: 700;")
        else:
            self.mode_note.setText("SETUP  ·  preparing")
            self.mode_note.setStyleSheet("")
        if show and check and any(row["status"] == "fail" for row in self._ready_checks()):
            self._open_ready_check()

    # -- PREVIEW -> TAKE ------------------------------------------------------- #

    @Slot(bool)
    def _set_preview_first(self, on: bool) -> None:
        self.preview_first = on
        self.settings.setValue("ui/preview_first", "true" if on else "false")
        if not on and self._pending_change is not None:
            self._cancel_take()
        self.statusBar().showMessage(
            "PREVIEW → TAKE on: choices wait for TAKE." if on else
            "PREVIEW → TAKE off: choices go straight on stage.", 6000)

    @contextmanager
    def _direct(self):
        """Stage changes made inside this go straight on: a TAKE, a running-order step, an undo."""
        self._direct_depth += 1
        try:
            yield
        finally:
            self._direct_depth -= 1

    def _change_stage(self, title: str, apply: Callable[[], None], thumb: Optional[QPixmap] = None,
                      detail: str = "") -> None:
        """
        Every change made by hand comes through here: straight on stage, or -
        with PREVIEW -> TAKE on - into the bar under the header until TAKE.
        """
        if self._direct_depth > 0:
            apply()                     # part of a TAKE, a step or an undo already under way
            return
        if self.preview_first and self.isVisible():
            self._pending_change = {"title": title, "apply": apply, "thumb": thumb}
            self.take_bar.show_pending(title, detail, thumb)
            self._sync_take_keys()
            return
        self._record_change(title, apply, thumb)

    def _record_change(self, title: str, apply: Callable[[], None], thumb: Optional[QPixmap] = None) -> None:
        """Change the stage, keeping what was there so Undo can put it back for a few seconds."""
        if self._direct_depth > 0:
            apply()
            return
        before = self._stage_snapshot()
        with self._direct():
            apply()
        self._undo_snapshot = before
        self.take_bar.show_done(title, thumb)

    def _stage_snapshot(self) -> dict:
        screens = {}
        for role in STAGE_ROLES:
            card = self.cards[role]
            window = self._show_output(role)
            screens[role] = {
                "path": card.current_path(), "loop": card.is_repeating(), "muted": card.mute_btn.isChecked(),
                "scale": card.current_scale_mode(),
                "slide": window.slide_state() if window is not None else None,
                "colour": window._bg_color.name() if window is not None else None,
            }
        top = self.top_output
        return {"screens": screens,
                "marquee": {"running": bool(top and top.is_marquee_running()),
                            "text": self.top_card.text_edit.text()},
                "preset": (self.loaded_preset, self._preset_dirty)}

    @Slot()
    def _undo(self) -> None:
        """Put the stage back to how it was before the last change made by hand."""
        snapshot = self._undo_snapshot
        if snapshot is None or not self.take_bar.undo_available():
            self.statusBar().showMessage("Nothing to undo.", 3000)
            return
        self._undo_snapshot = None
        self.take_bar.forget_undo()
        fade = self.fade_ms()
        with self._direct():
            for role, want in snapshot["screens"].items():
                card = self.cards[role]
                window = self._show_output(role)
                if window is None:
                    continue
                if want["colour"] and want["colour"] != window._bg_color.name():
                    window.set_background_color(QColor(want["colour"]))
                if want["path"] != card.current_path():
                    card.set_scale_mode(want["scale"])
                    self._set_checked(card.repeat_btn, want["loop"])
                    self._set_checked(card.mute_btn, want["muted"])
                    if want["path"] and os.path.isfile(want["path"]):
                        card.loadRequested.emit(want["path"])
                    else:
                        window.fade_clear(fade)
                        card.reset_file()
                if want["slide"] != window.slide_state():
                    if want["slide"]:
                        window.set_slide_style(self.text_slides.style_dict())
                        window.show_slide(want["slide"][0], want["slide"][1], max(120, fade // 2))
                    else:
                        window.hide_slide(max(120, fade // 2))
            marquee = snapshot["marquee"]
            top = self.top_output
            if top is not None and marquee["running"] != top.is_marquee_running():
                if marquee["running"]:
                    self.top_card.text_edit.setText(marquee["text"])
                    self._start_marquee()
                else:
                    self._stop_marquee()
        self.loaded_preset, self._preset_dirty = snapshot["preset"]
        self._describe_preset_state()
        self.statusBar().showMessage("Undone - the stage is back to how it was.", 5000)

    # -- rehearsal --------------------------------------------------------------- #

    def _stage_size(self, role: str) -> QSize:
        config = self.routing_rows[role].config()
        if config.custom and config.width > 0 and config.height > 0:
            return QSize(config.width, config.height)
        screen = self._screen_by_name(config.screen_name)
        if screen is not None:
            return screen.geometry().size()
        return QSize(DEFAULT_TOP_WIDTH, DEFAULT_TOP_HEIGHT) if role == ROLE_TOP else QSize(1920, 1080)

    @Slot()
    def _toggle_rehearsal(self) -> None:
        if self._rehearsal is None:
            self.start_rehearsal()
        else:
            self.end_rehearsal()

    def start_rehearsal(self) -> None:
        """
        Swap the stage windows for three in a desk window. Everything that drives
        a screen goes through the same attributes, so the whole dashboard follows
        without knowing; the real windows keep playing what they had.
        """
        if self._rehearsal is not None:
            return
        if self.presenter.live:
            self.rehearse_btn.setChecked(False)
            QMessageBox.information(self, "Rehearsal", "A presentation is on the stage. End it first, "
                                    "then rehearse - the rehearsal must not take it off the screen.")
            return
        if self._pending_change is not None:
            self._cancel_take()
        self._rehearsal_before = {
            "snapshot": self._stage_snapshot(),
            "outputs": {role: self._show_output(role) for role in STAGE_ROLES},
            "show": (self.show_index, getattr(self, "_show_step_id", None), self._show_started),
            "players": (self._show_players, self._show_active),
        }
        monitor = RehearsalMonitor({role: self._stage_size(role) for role in STAGE_ROLES})
        monitor.endRequested.connect(self.end_rehearsal)
        monitor.soundChosen.connect(self._set_rehearsal_sound)
        for role, window in monitor.outputs.items():
            card = self.cards[role]
            player = window.engine.player
            player.positionChanged.connect(card.set_position)
            player.durationChanged.connect(card.set_duration)
            card.seekRequested.connect(player.setPosition)
            window.engine.errorOccurred.connect(lambda message, bound=role: self._on_engine_error(bound, message))
            window.engine.set_loop(card.is_repeating())
            window.engine.set_volume(card.volume_slider.value())
            window.engine.set_muted(card.mute_btn.isChecked())
            window.set_scale_mode(card.current_scale_mode())
            setattr(self, self.OUTPUT_ATTRS[role], window)
        self._rehearsal = monitor
        # the running order gets its own music players, so the hall's keep playing
        self._show_players = [SoundCue(-3, self), SoundCue(-4, self)]
        self._show_active = 0
        for player in self._show_players:
            player.set_master(self.sound_master.value())
        self.presenter.rehearsing = True
        self._set_rehearsal_sound("")
        self._push_top_settings()
        self._freshly_opened = set(STAGE_ROLES)
        self._restore_media_to_outputs()        # start from what the stage shows now
        self._freshly_opened = set()
        monitor.show()
        self.rehearse_btn.setChecked(True)
        self.rehearse_btn.setText("  End rehearsal")
        self._update_output_status()
        self.statusBar().showMessage("REHEARSAL - everything goes to the rehearsal window; the stage is untouched.",
                                     10000)

    def _set_rehearsal_sound(self, device_name: str) -> None:
        from PySide6.QtMultimedia import QMediaDevices

        device = next((d for d in QMediaDevices.audioOutputs() if d.description() == device_name), None) \
            if device_name else None
        mode = device if device is not None else "silent"
        for cue in list(self.sound.cues) + list(self._show_players):
            cue.rehearsal = mode
        for role in STAGE_ROLES:
            window = self._show_output(role)
            if window is None:
                continue
            window.engine.set_silenced(device is None)
            if device is not None:
                window.engine.set_device(device)

    def end_rehearsal(self) -> None:
        """Give the dashboard back the stage windows - which never stopped showing what they had."""
        monitor = self._rehearsal
        if monitor is None:
            return
        before = self._rehearsal_before
        if self.presenter.live:
            self.presenter.end()
        from PySide6.QtMultimedia import QMediaDevices

        wanted = self.audio_device_combo.currentData()
        device = next((d for d in QMediaDevices.audioOutputs() if d.description() == wanted), None) \
            if wanted else QMediaDevices.defaultAudioOutput()
        for cue in self.sound.cues:
            cue.end_rehearsal(device)
        for player in self._show_players:
            player.stop(0)
            player.deleteLater()
        self._show_players, self._show_active = before["players"]
        for role in STAGE_ROLES:
            window = self._show_output(role)
            if window is not None:
                window.engine.clear()
            setattr(self, self.OUTPUT_ATTRS[role], before["outputs"][role])
        self._rehearsal = None
        self.presenter.rehearsing = False
        monitor.hide()
        monitor.deleteLater()

        # the cards go back to describing the stage - without touching it
        snapshot = before["snapshot"]
        for role, want in snapshot["screens"].items():
            card = self.cards[role]
            card.blockSignals(True)
            card.set_scale_mode(want["scale"])
            card.blockSignals(False)
            for button, value in ((card.repeat_btn, want["loop"]), (card.mute_btn, want["muted"])):
                button.blockSignals(True)
                button.setChecked(value)
                button.blockSignals(False)
            if want["path"]:
                card.show_loaded(want["path"])
            else:
                card.reset_file()
            window = self._show_output(role)
            if window is not None:
                card.set_duration(window.engine.player.duration())
        self.top_card.text_edit.blockSignals(True)
        self.top_card.text_edit.setText(snapshot["marquee"]["text"])
        self.top_card.text_edit.blockSignals(False)
        self.loaded_preset, self._preset_dirty = snapshot["preset"]
        self._describe_preset_state()
        index, step_id, started = before["show"]
        self.show_index, self._show_step_id, self._show_started = index, step_id, started
        self._show_auto = None
        self.show_tab.set_running(index)
        if index < 0:
            self._show_timer.stop()
            self.show_tab.set_clock(None, None)
        self._undo_snapshot = None
        self.take_bar.forget_undo()
        self.rehearse_btn.setChecked(False)
        self.rehearse_btn.setText("  Rehearse")
        self._update_output_status()
        self._refresh_mini()
        self.statusBar().showMessage("Rehearsal over - the dashboard drives the stage again, as it was.", 8000)

    @Slot()
    def _take(self) -> None:
        change, self._pending_change = self._pending_change, None
        self.take_bar.clear_pending()
        self._sync_take_keys()
        if change is not None:
            self._record_change(change["title"], change["apply"], change["thumb"])

    @Slot()
    def _cancel_take(self) -> None:
        self._pending_change = None
        self.take_bar.clear_pending()
        self._sync_take_keys()
        self.statusBar().showMessage("Preview cancelled - the stage was not changed.", 4000)

    def _sync_take_keys(self) -> None:
        pending = self._pending_change is not None
        self._take_shortcut.setEnabled(pending)
        # Esc cancels, unless slides are on screen: then it is the clicker's "end"
        self._cancel_shortcut.setEnabled(pending and not self.presenter.live)

    def _thumb_for_path(self, path: str) -> Optional[QPixmap]:
        return small_picture(path, QSize(160, 90))

    def _text_thumb(self, title: str, subtitle: str) -> QPixmap:
        pixmap = QPixmap(160, 90)
        pixmap.fill(QColor("#05070b"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.TextAntialiasing)
        font = QFont("Segoe UI")
        font.setPixelSize(15)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(QRectF(4, 20, 152, 30), Qt.AlignCenter,
                         painter.fontMetrics().elidedText(title, Qt.ElideRight, 150))
        if subtitle:
            font.setPixelSize(10)
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(QColor("#cfd8e6"))
            painter.drawText(QRectF(4, 50, 152, 20), Qt.AlignCenter,
                             painter.fontMetrics().elidedText(subtitle, Qt.ElideRight, 150))
        painter.end()
        return pixmap

    # -- NEXT everywhere ------------------------------------------------------- #

    def _refresh_show_strip(self) -> None:
        steps = self.show_tab.steps()
        visible = bool(steps) and self.tabs.currentWidget() is not self.show_tab
        self.show_strip.setVisible(visible)
        if not visible:
            return
        index = self.show_index
        now = steps[index] if 0 <= index < len(steps) else None
        upcoming = steps[index + 1] if index + 1 < len(steps) else None
        caption = f"NOW  ·  {index + 1} / {len(steps)}" if now else "READY"
        now_text = (now["title"] or "Untitled") if now else "Press NEXT to start"
        next_text = (upcoming["title"] or "Untitled") if upcoming else "— end of the show —"
        clock = ""
        if now is not None:
            elapsed = time.monotonic() - self._show_started
            clock = f"{int(elapsed // 60)}:{int(elapsed % 60):02d}"
        auto = f"auto in {int(self._show_auto + 0.99)} s" if self._show_auto is not None else ""
        self.show_strip.set_state(caption, now_text, next_text, clock, auto, upcoming is not None)
        # Slides, Text and Screens have a gold button of their own; there, the step NEXT steps back
        self.show_strip.set_emphasis(self.tabs.currentWidget() in (self.tabs.widget(0), self.library, self.dj_page))

    # -- ready check ----------------------------------------------------------- #

    @Slot()
    def _open_ready_check(self) -> None:
        if self._ready_dialog is None:
            self._ready_dialog = desk_mod.ReadyCheckDialog(self._ready_checks, self._ready_action,
                                                           THEME, Icons, self)
        self._ready_dialog.refresh()
        self._ready_dialog.show()
        self._ready_dialog.raise_()
        self._ready_dialog.activateWindow()

    def _ready_check_open(self) -> bool:
        return self._ready_dialog is not None and self._ready_dialog.isVisible()

    def _audio_device_name(self) -> str:
        from PySide6.QtMultimedia import QMediaDevices

        chosen = self.audio_device_combo.currentData()
        if chosen:
            return str(chosen)
        return QMediaDevices.defaultAudioOutput().description()

    def _ready_checks(self) -> List[dict]:
        rows: List[dict] = []

        def add(status, title, detail="", action=None):
            rows.append({"status": status, "title": title, "detail": detail, "action": action})

        # -- screens -- #
        for role in STAGE_ROLES:
            label = ROLE_LABELS[role]
            name = self.routing_rows[role].screen_combo.currentData()
            window = self._show_output(role)
            if not name:
                add("fail", f"{label}: no monitor chosen", "Pick its monitor on Screens & Setup.",
                    ("Screens & Setup", "screens"))
            elif self._screen_by_name(name) is None:
                add("fail", f"{label}: its monitor is not connected",
                    f"Windows does not report “{name}” - check the cable or the LED processor.")
            elif window is None:
                add("warn", f"{label}: closed", "The monitor is there; its window is not open.",
                    ("Open outputs", "open"))
            else:
                card = self.cards[role]
                what = os.path.basename(card.current_path()) if card.current_path() else "black"
                add("ok", f"{label}: open", f"on screen: {what}")
        # -- sound -- #
        device = self._audio_device_name()
        hall = str(self.settings.value("ready/hall_audio", "") or "")
        if not device:
            add("fail", "No sound output device", "Windows reports no speakers or mixer.")
        elif hall and device != hall:
            add("warn", f"Sound goes to {device}", f"The hall's device is {hall}.",
                ("This is the hall's device", "hall_audio"))
        elif hall:
            add("ok", f"Sound: {device}", "the hall's device")
        else:
            add("info", f"Sound: {device}", "Is this the hall's mixer? Remember it, and the check will "
                "warn if the sound ever goes somewhere else.", ("Yes, this is the hall's", "hall_audio"))
        if self.sound_master.value() == 0:
            add("warn", "Master volume is at 0", "Sound cues and running-order music will be silent.")
        # -- files -- #
        steps = self.show_tab.steps()
        gone = show_missing_files(steps)
        if not steps:
            add("info", "The running order is empty", "Fine if this event is run by hand.")
        elif gone:
            add("fail", f"Running order: {len(gone)} file(s) missing",
                ", ".join(os.path.basename(p) for p in gone[:5]) + ("…" if len(gone) > 5 else ""))
        else:
            add("ok", f"Running order “{self.show_store.current}”: {len(steps)} step(s)", "every file is there")
        lost = sorted({os.path.basename(p) for card in self.cards.values()
                       for p in card.playlist.paths() + [card.current_path()] if p and not os.path.isfile(p)}
                      | {os.path.basename(cue.path) for cue in self.sound.cues
                         if cue.path and not os.path.isfile(cue.path)})
        if lost:
            add("warn", f"{len(lost)} file(s) on the Live tab are missing", ", ".join(lost[:5]))
        # -- presentation -- #
        deck = self.presenter.deck
        if deck is not None:
            if deck.error:
                add("fail", f"Presentation “{deck.name}” did not open", deck.error.splitlines()[0])
            elif deck.kind == "powerpoint" and self.presenter.in_powerpoint and not pres_mod.powerpoint_available():
                add("warn", f"Presentation “{deck.name}”", "PowerPoint is not installed: it will show as pictures.")
            else:
                add("ok", f"Presentation “{deck.name}”", f"{deck.count or '…'} slides ready")
        # -- clicker -- #
        last = self.presentation_tab._last_key
        ago = time.monotonic() - last[2] if last[2] else None
        if ago is not None and ago < 1800:
            minutes = int(ago // 60)
            add("ok", "Clicker works", f"last press: {last[0]} → {last[1]}, "
                + (f"{minutes} min ago" if minutes else f"{int(ago)} s ago"))
        else:
            add("warn", "Clicker not tested", "Press any clicker button now - this row turns green. "
                "(Presses here are only a test: nothing moves.)")
        # -- phone remote -- #
        if self.remote.running:
            guest = "  ·  guest link on" if self.remote.guest else ""
            add("ok", "Phone remote is on", f"{self.remote.clients()} phone(s) connected{guest}")
        else:
            add("info", "Phone remote is off", "Only needed if someone runs the show from a phone.",
                ("Phone remote…", "remote"))
        if self.preview_first:
            add("info", "PREVIEW → TAKE is on", "Files, presets and names chosen by hand wait for TAKE.")
        return rows

    def _refresh_health(self) -> None:
        """The status bar's chips: screens, sound, clicker, phones, files."""
        if not self.isVisible():
            return
        items = []
        open_count = sum(1 for role in STAGE_ROLES if self._show_output(role) is not None)
        routed = sum(1 for role in STAGE_ROLES if self.routing_rows[role].screen_combo.currentData())
        items.append((f"Screens {open_count}/{len(STAGE_ROLES)}",
                      "ok" if open_count == len(STAGE_ROLES) else ("warn" if open_count < routed else "info"),
                      "Stage windows open"))
        device = self._audio_device_name()
        hall = str(self.settings.value("ready/hall_audio", "") or "")
        short = device if len(device) <= 30 else device[:28] + "…"
        if self.sound_master.value() == 0:
            items.append((f"Sound muted  ·  {short}", "warn", "Master volume is at 0"))
        elif hall and device != hall:
            items.append((f"Sound: {short}", "warn", f"Not the hall's device ({hall})"))
        else:
            items.append((f"Sound: {short}", "ok" if hall else "info", device))
        last = self.presentation_tab._last_key
        ago = time.monotonic() - last[2] if last[2] else None
        if ago is not None and ago < 1800:
            items.append((f"Clicker {int(ago // 60)} min" if ago >= 60 else "Clicker ✓", "ok",
                          f"Last press: {last[0]}"))
        else:
            items.append(("Clicker untested", "info", "No clicker press seen yet"))
        if self.remote.running:
            items.append((f"Phones {self.remote.clients()}", "ok", "The phone remote is on"))
        gone = show_missing_files(self.show_tab.steps())
        if gone:
            items.append((f"{len(gone)} file(s) missing", "fail", "\n".join(gone[:8])))
        self.health.set_items(items)

    @Slot()
    def _show_shortcuts(self) -> None:
        desk_mod.ShortcutsDialog(THEME, self).exec()

    def _ready_action(self, key: str) -> None:
        if key == "identify":
            self._identify_screens()
        elif key == "open":
            self._apply_routing()
        elif key == "screens":
            self._set_mode("setup", check=False)
            self.tabs.setCurrentWidget(self.screens_page)
        elif key == "hall_audio":
            self.settings.setValue("ready/hall_audio", self._audio_device_name())
        elif key == "remote":
            self._open_remote_dialog()

    def _build_preset_bar(self) -> QWidget:
        """
        Presets as pictures: what each one puts on the screens, the one that is
        on the screens now marked green (amber once it has been changed). One
        tap loads; saving, renaming and deleting are SETUP work, at the end of
        the row and on a right-click.
        """
        bar = QFrame()
        bar.setObjectName("bar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 6, 14, 6)
        layout.setSpacing(12)

        caption_box = QVBoxLayout()
        caption_box.setSpacing(4)
        caption_row = QHBoxLayout()
        caption_row.setSpacing(6)
        glyph = QLabel()
        glyph.setPixmap(Icons.get("list", CLR_MUTED, 16).pixmap(16, 16))
        caption_row.addWidget(glyph)
        caption = QLabel("PRESETS")
        caption.setObjectName("sectionTitle")
        caption.setToolTip(f"Saved in {PRESET_FILE}")
        caption_row.addWidget(caption)
        caption_row.addStretch(1)
        caption_box.addLayout(caption_row)
        self.preset_state = QLabel()
        self.preset_state.setObjectName("cardHint")
        self.preset_state.setWordWrap(True)
        self.preset_state.setFixedWidth(150)
        caption_box.addWidget(self.preset_state)
        caption_box.addStretch(1)
        layout.addLayout(caption_box)

        # The chosen preset lives in a combo nobody sees: saving, deleting and
        # the autostart all read it, as they always have.
        self.preset_combo = QComboBox()
        self.preset_combo.hide()
        layout.addWidget(self.preset_combo)

        self.preset_strip = desk_mod.PresetStrip(THEME)
        self.preset_strip.presetClicked.connect(self._on_preset_tile)
        self.preset_strip.menuRequested.connect(self._preset_menu)
        layout.addWidget(self.preset_strip, 1)

        edit = QGridLayout()
        edit.setHorizontalSpacing(6)
        edit.setVerticalSpacing(6)
        new_btn = QPushButton("  Save as new…")
        new_btn.setIcon(Icons.get("plus", CLR_TEXT, 15))
        new_btn.setToolTip("Store what is set up now under a new name")
        new_btn.clicked.connect(self._save_preset_as)
        save_btn = QPushButton("  Save")
        save_btn.setIcon(Icons.get("save", CLR_TEXT, 15))
        save_btn.setToolTip("Overwrite the chosen preset with what is set up now")
        save_btn.clicked.connect(self._save_preset)
        new_preset_btn = desk_mod.HoldButton("  Blank", THEME)
        new_preset_btn.setIcon(Icons.get("refresh", CLR_TEXT, 15))
        new_preset_btn.setToolTip("Clear everything and start a fresh show from blank - hold to confirm")
        new_preset_btn.clicked.connect(self._new_preset)
        delete_btn = desk_mod.HoldButton("  Delete", THEME)
        delete_btn.setIcon(Icons.get("trash", CLR_TEXT, 15))
        delete_btn.setToolTip("Remove the chosen preset - hold to confirm")
        delete_btn.clicked.connect(self._delete_preset)
        edit.addWidget(new_btn, 0, 0)
        edit.addWidget(save_btn, 0, 1)
        edit.addWidget(new_preset_btn, 1, 0)
        edit.addWidget(delete_btn, 1, 1)
        layout.addLayout(edit)
        # hidden in SHOW mode
        self._preset_edit_widgets = [new_preset_btn, save_btn, new_btn, delete_btn]

        # video frames for the pictures arrive later; rebuild once they have
        self._preset_pictures_timer = QTimer(self)
        self._preset_pictures_timer.setSingleShot(True)
        self._preset_pictures_timer.timeout.connect(self._rebuild_preset_strip)
        thumbnailer().ready.connect(lambda *_a: self._preset_pictures_timer.start(400))
        return bar

    def _preset_picture(self, payload: dict) -> QPixmap:
        """A preset at a glance: the Main Stage, the side screens inset, the ceiling strip on top."""
        canvas = QPixmap(176, 99)
        canvas.fill(QColor("#05070b"))
        outputs = payload.get("outputs", {})
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        def cover(path: str, rect: QRect) -> bool:
            picture = small_picture(path, QSize(320, 180)) if path else None
            if picture is None or picture.isNull():
                return False
            scale = max(rect.width() / picture.width(), rect.height() / picture.height())
            sw, sh = rect.width() / scale, rect.height() / scale
            painter.drawPixmap(QRectF(rect), picture,
                               QRectF((picture.width() - sw) / 2, (picture.height() - sh) / 2, sw, sh))
            return True

        cover(outputs.get(ROLE_MAIN, {}).get("file", ""), QRect(0, 0, 176, 99))
        top_rect = QRect(0, 0, 176, 9)
        if not cover(outputs.get(ROLE_TOP, {}).get("file", ""), top_rect):
            painter.fillRect(top_rect, QColor(payload.get("top", {}).get("background", "#101828")))
        sides = outputs.get(ROLE_SIDES, {}).get("file", "")
        if sides:
            inset = QRect(6, 99 - 6 - 27, 48, 27)
            painter.fillRect(inset.adjusted(-1, -1, 1, 1), QColor(CLR_BG))
            if not cover(sides, inset):
                painter.fillRect(inset, QColor("#05070b"))
        painter.end()
        return canvas

    def _rebuild_preset_strip(self) -> None:
        items = [(name, self._preset_picture(self.presets.get(name) or {})) for name in self.presets.names()]
        self.preset_strip.set_presets(items)
        self._mark_preset_strip()

    def _mark_preset_strip(self) -> None:
        if hasattr(self, "preset_strip"):
            chosen = self.preset_combo.currentText() if self.preset_combo.isEnabled() else None
            self.preset_strip.mark(self.loaded_preset, self._preset_dirty, chosen)

    @Slot(str)
    def _on_preset_tile(self, name: str) -> None:
        self.preset_combo.setCurrentText(name)
        self._mark_preset_strip()
        self._load_preset()

    def _preset_menu(self, name: str, position) -> None:
        self.preset_combo.setCurrentText(name)
        self._mark_preset_strip()
        menu = QMenu(self)
        menu.addAction(f"Put “{name}” on the screens", self._load_preset)
        if self.ui_mode == "setup":
            menu.addSeparator()
            menu.addAction(f"Save what is set up now into “{name}”", self._save_preset)
            menu.addAction(f"Delete “{name}”…", self._delete_preset)
        menu.exec(position)

    def _mark_preset_dirty(self) -> None:
        if not self._preset_dirty:
            self._preset_dirty = True
            self._describe_preset_state()

    def _describe_preset_state(self) -> None:
        self._mark_preset_strip()
        if self.loaded_preset is None:
            self.preset_state.setText("nothing loaded")
            self.preset_state.setStyleSheet(f"color: {CLR_MUTED};")
            return
        if self._preset_dirty:
            self.preset_state.setText(f"●  {self.loaded_preset} — changed, not saved")
            self.preset_state.setStyleSheet(f"color: {CLR_WARN}; font-weight: 600;")
        else:
            self.preset_state.setText(f"●  {self.loaded_preset} is on the screens")
            self.preset_state.setStyleSheet(f"color: {CLR_OK}; font-weight: 600;")

    def _build_live_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 10, 0, 0)
        outer.setSpacing(11)

        screens = QWidget()
        layout = QHBoxLayout(screens)
        layout.setContentsMargins(0, 0, 0, 0)
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
        for changed in (self.top_card.marqueeTextChanged, self.top_card.marqueeColorChanged,
                        self.top_card.marqueeSpeedChanged, self.top_card.colorRequested):
            changed.connect(lambda *_a: self._mark_preset_dirty())
        layout.addWidget(self.top_card, 1)

        self.cards: Dict[str, OutputCard] = {
            ROLE_MAIN: self.main_card,
            ROLE_SIDES: self.sides_card,
            ROLE_TOP: self.top_card,
        }
        for role, card in self.cards.items():
            card.activated.connect(lambda bound=role: self.set_active_role(bound))

        outer.addWidget(screens, 1)
        outer.addWidget(self._build_sound_bar())
        return page

    # -------------------------------------------------------- mini bar ----- #

    def shrink_to_bar(self) -> None:
        """Hide the dashboard and leave a strip floating over everything else."""
        if self.mini is None:
            self.mini = MiniBar()
            self.mini.expandRequested.connect(self.restore_from_bar)
            self.mini.presetRequested.connect(self._mini_load_preset)
            self.mini.blackoutRequested.connect(self._blackout_all)
            self.mini.stopSoundRequested.connect(self._stop_all_sound)
            self.mini.stepRequested.connect(
                lambda delta: self._active_card().playlist.step(delta))
            self.mini.cueRequested.connect(self._fire_cue)
            self.mini.playPauseRequested.connect(self._toggle_active_playback)
            self.mini.screenChosen.connect(self.set_active_role)
            self.mini.showNextRequested.connect(self.show_next)
            self.mini.showBackRequested.connect(self.show_back)

        self.mini.set_presets(self.presets.names(), self.loaded_preset)
        self._refresh_mini_now()
        self.mini.adjustSize()

        stored = self.settings.value("window/mini_pos")
        if stored is not None:
            self.mini.move(stored)
        else:
            available = QGuiApplication.primaryScreen().availableGeometry()
            self.mini.move(available.center().x() - self.mini.width() // 2,
                           available.bottom() - self.mini.height() - 60)
        self.mini.show()
        self.mini.raise_()
        self.hide()
        self._mini_ticker.start(400)

    def _refresh_mini_now(self) -> None:
        """Fill the bar before it is shown, so it never appears blank."""
        was_visible = self.mini.isVisible()
        self.mini.setVisible(True)
        self._refresh_mini()
        self.mini.setVisible(was_visible)

    def restore_from_bar(self) -> None:
        if self.mini is not None:
            self.settings.setValue("window/mini_pos", self.mini.pos())
            self.mini.hide()
        self._mini_ticker.stop()
        self.show()
        self.raise_()
        self.activateWindow()

    def _refresh_mini(self) -> None:
        self._refresh_show_strip()
        if self.mini is None or not self.mini.isVisible():
            return
        role = self.active_role
        card = self.cards[role]
        window = getattr(self, self.OUTPUT_ATTRS[role], None)
        playing = False
        if window is not None:
            states = getattr(QMediaPlayer, "PlaybackState", None)
            playing = window.engine.player.playbackState() == getattr(
                states, "PlayingState", None)
        name = os.path.basename(card.current_path()) if card.current_path() else ""
        self.mini.show_screen(role, name, window is not None, playing)
        self.mini.show_cues(self.sound.cues)
        steps = self.show_tab.steps()
        now = steps[self.show_index] if 0 <= self.show_index < len(steps) else None
        upcoming = steps[self.show_index + 1] if self.show_index + 1 < len(steps) else None
        if now is None:
            text = f"Running order ready · next: {upcoming['title']}" if upcoming else ""
        else:
            text = f"{self.show_index + 1}/{len(steps)}  {now['title']}" + (
                f"   →   {upcoming['title']}" if upcoming else "   ·   last step")
        self.mini.show_running(text, upcoming is not None, bool(steps))

    @Slot(str)
    def _mini_load_preset(self, name: str) -> None:
        payload = self.presets.get(name)
        if not payload:
            return
        self._apply_preset(payload)
        self.loaded_preset = name
        self._preset_dirty = False
        self._describe_preset_state()
        self._refresh_preset_combo(name)

    # ---------------------------------------------------- running order ---- #

    def _build_show_tab(self) -> QWidget:
        self.show_store = ShowStore(SHOW_FILE)
        self.show_tab = ShowTab(self.show_store, Icons, THEME, touch=self.touch_enabled(),
                                thumbs=lambda path: self._cached_thumb(path))
        thumbnailer().ready.connect(lambda *_a: self.show_tab.list.viewport().update())
        self.show_tab.nextRequested.connect(self.show_next)
        self.show_tab.backRequested.connect(self.show_back)
        self.show_tab.restartRequested.connect(self.show_restart)
        self.show_tab.goRequested.connect(self.show_go)
        self.show_tab.captureRequested.connect(self._capture_show_step)
        self.show_tab.remoteRequested.connect(self._open_remote_dialog)
        self.show_tab.showSwitched.connect(self.show_restart)
        self.show_tab.edited.connect(self._on_show_edited)
        self.show_tab.set_running(-1)
        return self.show_tab

    def _show_output(self, role: str):
        return getattr(self, self.OUTPUT_ATTRS[role], None)

    def _cached_thumb(self, path: str, width: int = 112, height: int = 64) -> Optional[QPixmap]:
        """Small pictures for lists that repaint often: made once, kept."""
        key = (path, width, height)
        picture = self._thumb_cache.get(key)
        if picture is None:
            picture = small_picture(path, QSize(width, height))
            if picture is not None:
                if len(self._thumb_cache) > 400:
                    self._thumb_cache.clear()
                self._thumb_cache[key] = picture
        return picture

    def _on_show_edited(self) -> None:
        """Steps added, moved or deleted mid-show: NOW stays on the step that is running."""
        ids = [s["id"] for s in self.show_tab.steps()]
        running = getattr(self, "_show_step_id", None)
        if self.show_index >= 0:
            self.show_index = ids.index(running) if running in ids else -1
            if self.show_index < 0:
                self.show_restart()
                return
        self.show_tab.set_running(self.show_index)
        self._refresh_mini()

    @Slot()
    def show_next(self) -> None:
        steps = self.show_tab.steps()
        if self.show_index + 1 < len(steps):
            self.show_go(self.show_index + 1)
        elif steps:
            self.statusBar().showMessage("That was the last step of the running order.", 5000)

    @Slot()
    def show_back(self) -> None:
        if self.show_index > 0:
            self.show_go(self.show_index - 1)

    @Slot()
    def show_restart(self) -> None:
        """Back to before step 1. The stage is left as it is until NEXT."""
        self.show_index = -1
        self._show_auto = None
        self._show_timer.stop()
        self.show_tab.set_running(-1)
        self.show_tab.set_clock(None, None)
        self._refresh_mini()

    @Slot(int)
    def show_go(self, index: int) -> None:
        """
        Put step `index` on stage. Everything the step sets is done; everything
        it leaves alone is brought to where the earlier steps put it, so a jump
        or a step back lands exactly where walking there would have.
        """
        steps = self.show_tab.steps()
        if not 0 <= index < len(steps):
            return
        target = show_fold(steps, index)
        step = steps[index]
        # One step forward does just what that step says, so anything the
        # operator changed by hand stays changed. Back and jumps replay the
        # earlier steps to land where walking there would have.
        only_explicit = index == self.show_index + 1
        self._open_outputs_for(target)
        with self._direct():
            problems = self._apply_show_state(target, step, only_explicit)
        self.show_index = index
        self._show_step_id = step["id"]
        self._show_started = time.monotonic()
        self._show_sound_started = step["sound"]["mode"] == "play" and not problems
        self.show_tab.set_running(index)
        self._show_tick()
        self._show_timer.start(250)
        self._refresh_mini()
        message = f"Step {index + 1} of {len(steps)}: {step['title']}"
        if problems:
            message += "   —   " + "; ".join(problems)
        self.statusBar().showMessage(message, 12000)

    def _open_outputs_for(self, target: dict) -> None:
        """A step that needs a screen that is closed opens the outputs, like OPEN OUTPUTS."""
        needed = [role for role in STAGE_ROLES if target["screens"][role] is not None]
        if target["text"] is not None and target["text"]["mode"] == "show":
            needed.append(target["text"].get("target") or ROLE_MAIN)
        if target["marquee"] is not None and target["marquee"]["mode"] == "start":
            needed.append(ROLE_TOP)
        closed = [role for role in needed if self._show_output(role) is None
                  and self.routing_rows[role].screen_combo.currentData()]
        if closed:
            self._apply_routing()

    @staticmethod
    def _set_checked(button: QPushButton, checked: bool) -> None:
        if button.isChecked() != checked:
            button.setChecked(checked)          # emits, so the output follows

    def _apply_show_state(self, target: dict, step: dict, only_explicit: bool = False) -> List[str]:
        problems: List[str] = []
        fade = self.fade_ms()
        if only_explicit:
            target = dict(target)
            target["screens"] = {role: (target["screens"][role] if step["screens"][role]["mode"] != "keep"
                                        else None) for role in STAGE_ROLES}
            for part in ("sound", "text", "marquee", "slides"):
                if step.get(part, {}).get("mode", "keep") == "keep":
                    target[part] = None

        # -- screens -- #
        for role in STAGE_ROLES:
            entry = target["screens"][role]
            if entry is None:
                continue
            explicit = step["screens"][role]["mode"] != "keep"
            card = self.cards[role]
            window = self._show_output(role)
            if window is None:
                problems.append(f"{ROLE_LABELS[role]} is not open")
                continue
            if explicit and self.presenter.live and self.presenter.role == role:
                self.presenter.release()     # this step puts something else on that screen
            if entry["mode"] == "black":
                if card.current_path() or explicit:
                    window.fade_clear(fade)
                    card.reset_file()
                continue
            path = entry["path"]
            if not path or not os.path.isfile(path):
                problems.append(f"missing file {os.path.basename(path) or '(none chosen)'}")
                continue
            current = card.current_path()
            same = bool(current) and os.path.normcase(os.path.abspath(current)) == \
                os.path.normcase(os.path.abspath(path))
            self._set_checked(card.repeat_btn, bool(entry["loop"]))
            self._set_checked(card.mute_btn, not entry["audio"])
            if same and (entry["loop"] or not explicit):
                continue                    # already there: do not restart it
            card.show_loaded(path)
            card.loadRequested.emit(path)

        # -- sound -- #
        entry = target["sound"]
        if entry is not None:
            explicit = step["sound"]["mode"] != "keep"
            active = self._show_players[self._show_active]
            if entry["mode"] == "play":
                playing_same = active.is_playing() and os.path.normcase(active.path) == \
                    os.path.normcase(entry["path"] or "")
                # a one-off fanfare from an earlier step is not replayed on a jump
                wanted = (explicit and not (playing_same and entry["loop"])) or \
                         (not explicit and entry["loop"] and not playing_same)
                if wanted:
                    problem = self._show_play(entry)
                    if problem:
                        problems.append(problem)
            elif entry["mode"] in ("fade", "silence"):
                for player in self._show_players:
                    player.stop(1500)
                if entry["mode"] == "silence":
                    self.sound.stop_all(1500)

        # -- words on screen -- #
        entry = target["text"]
        if entry is not None:
            explicit = step["text"]["mode"] != "keep"
            if entry["mode"] == "show":
                role = entry.get("target") or ROLE_MAIN
                key = (role, entry["title"], entry["subtitle"])
                for other in STAGE_ROLES:
                    window = self._show_output(other)
                    if other != role and window is not None and window.slide_visible():
                        window.hide_slide(max(120, fade // 2))
                window = self._show_output(role)
                if window is None:
                    problems.append(f"{ROLE_LABELS[role]} is not open for the text")
                elif explicit or self._show_text_shown != key or not window.slide_visible():
                    window.set_slide_style(self.text_slides.style_dict())
                    window.show_slide(entry["title"], entry["subtitle"], max(120, fade // 2))
                    self._show_text_shown = key
            else:
                for window in self._outputs():
                    if window.slide_visible():
                        window.hide_slide(max(120, fade // 2))
                self._show_text_shown = None

        # -- ceiling marquee -- #
        entry = target["marquee"]
        if entry is not None:
            explicit = step["marquee"]["mode"] != "keep"
            top = self.top_output
            if entry["mode"] == "start" and entry["text"].strip():
                if self.top_card.text_edit.text() != entry["text"]:
                    self.top_card.text_edit.setText(entry["text"])
                if top is None:
                    problems.append("Top Screen is not open for the marquee")
                elif explicit or not top.is_marquee_running():
                    self._start_marquee()
            elif entry["mode"] == "stop" and top is not None and top.is_marquee_running():
                self._stop_marquee()

        # -- presentation -- #
        entry = target.get("slides")
        presenter = self.presenter
        if entry is not None:
            explicit = step.get("slides", {}).get("mode", "keep") != "keep"
            if entry["mode"] == "start":
                path = entry["path"]
                role = entry.get("target") or ROLE_MAIN
                if not path or not os.path.exists(path):
                    problems.append(f"missing presentation {os.path.basename(path) or '(none chosen)'}")
                else:
                    same = presenter.deck is not None and \
                        os.path.normcase(presenter.deck.path) == os.path.normcase(os.path.normpath(path))
                    error = None if same else presenter.open(path)
                    if error:
                        problems.append(error)
                    else:
                        if same and explicit:
                            presenter.goto(0)
                        if explicit or not presenter.live or presenter.role != role:
                            presenter.go_live_when_ready(role)
            elif entry["mode"] == "end" and presenter.live:
                presenter.end()
        return problems

    def _show_play(self, entry: dict) -> Optional[str]:
        """Fade the running order's music over to `entry`, on the other player."""
        path = entry["path"]
        if not path or not os.path.isfile(path):
            return f"missing sound {os.path.basename(path) or '(none chosen)'}"
        old = self._show_players[self._show_active]
        new = self._show_players[1 - self._show_active]
        try:
            new.assign(path)
        except MediaProblem as problem:
            return f"{os.path.basename(path)}: {problem.title}"
        new.set_master(self.sound_master.value())
        new.set_level(int(entry.get("level", 90)))
        new.set_loop(bool(entry["loop"]))
        if old.is_playing() or old.is_paused():
            old.stop(1200)
        new.play()
        self._show_active = 1 - self._show_active
        return None

    def _show_tick(self) -> None:
        steps = self.show_tab.steps()
        if not 0 <= self.show_index < len(steps):
            self._show_timer.stop()
            self.show_tab.set_clock(None, None)
            self._show_auto = None
            return
        step = steps[self.show_index]
        elapsed = time.monotonic() - self._show_started
        has_next = self.show_index + 1 < len(steps)
        advance = step["advance"]
        remaining, note, go_on = None, "", False
        if has_next and advance["mode"] == "after":
            remaining = max(0.0, float(advance["seconds"]) - elapsed)
            go_on = remaining <= 0
        elif has_next and advance["mode"] == "video":
            note = "goes on when the video ends"
            window = self.main_output
            status = getattr(QMediaPlayer, "MediaStatus", None)
            end = getattr(status, "EndOfMedia", None)
            go_on = window is not None and elapsed > 1.0 and \
                window.engine.player.mediaStatus() == end
        elif has_next and advance["mode"] == "sound":
            note = "goes on when the sound ends"
            player = self._show_players[self._show_active]
            go_on = self._show_sound_started and elapsed > 1.0 and \
                not player.is_playing() and not player.is_paused()
        self._show_auto = remaining
        self.show_tab.set_clock(elapsed, remaining, note)
        self._refresh_show_strip()
        if go_on:
            self.show_next()

    @Slot()
    def _capture_show_step(self) -> None:
        """A new step that recreates what is on stage right now."""
        step = new_step(f"Step {len(self.show_tab.steps()) + 1}")
        for role in STAGE_ROLES:
            card = self.cards[role]
            path = card.current_path()
            if path:
                step["screens"][role] = {"mode": "file", "path": path, "loop": card.is_repeating(),
                                         "audio": not card.mute_btn.isChecked()}
            elif self._show_output(role) is not None:
                step["screens"][role]["mode"] = "black"
        player = self._show_players[self._show_active]
        if player.is_playing() and player.path:
            step["sound"] = {"mode": "play", "path": player.path, "loop": player.loop, "level": player.level}
        if self.top_output is not None and self.top_output.is_marquee_running():
            step["marquee"] = {"mode": "start", "text": self.top_card.text_edit.text()}
        if self.presenter.live and self.presenter.deck is not None:
            step["slides"] = {"mode": "start", "path": self.presenter.deck.path, "target": self.presenter.role}
        self.show_tab.add_step(step)
        self.statusBar().showMessage("Step added from what is on stage now - give it a name.", 6000)

    # ------------------------------------------------------ phone remote --- #

    def _restore_remote(self) -> None:
        pin = str(self.settings.value("remote/pin", "") or "")
        if len(pin) != 4 or not pin.isdigit():
            pin = remote_mod.new_pin()
            self.settings.setValue("remote/pin", pin)
        self.remote.pin = pin
        self.remote.guest = str(self.settings.value("remote/guest", "") or "")
        try:
            self.remote.port = int(self.settings.value("remote/port", remote_mod.DEFAULT_PORT))
        except (TypeError, ValueError):
            self.remote.port = remote_mod.DEFAULT_PORT
        self.remote.clientsChanged.connect(lambda _n: self._describe_remote())
        if str(self.settings.value("remote/enabled", "false")).lower() == "true":
            self.remote.start(self.remote.port)
        self._describe_remote()

    def _describe_remote(self) -> None:
        if self.remote.running:
            count = self.remote.clients()
            self.show_tab.remote_btn.setText(f"  Phone remote · ON" + (f" ({count})" if count else ""))
            self.show_tab.remote_btn.setStyleSheet(f"color: {CLR_OK}; font-weight: 600;")
        else:
            self.show_tab.remote_btn.setText("  Phone remote")
            self.show_tab.remote_btn.setStyleSheet("")

    @Slot()
    def _open_remote_dialog(self) -> None:
        if self._remote_dialog is None:
            qr_pin = str(self.settings.value("remote/qr_pin", "false")).lower() == "true"
            dialog = remote_mod.RemoteDialog(self.remote, THEME, self, qr_with_pin=qr_pin)
            dialog.toggled.connect(self._toggle_remote)
            dialog.portChanged.connect(lambda port: setattr(self.remote, "port", port))
            dialog.pinRenewed.connect(self._renew_remote_pin)
            dialog.qrPinToggled.connect(
                lambda on: self.settings.setValue("remote/qr_pin", "true" if on else "false"))
            dialog.guestRequested.connect(self._open_guest_dialog)
            self._remote_dialog = dialog
        self._remote_dialog.refresh()
        self._remote_dialog.show()
        self._remote_dialog.raise_()

    def _toggle_remote(self, on: bool) -> None:
        error = ""
        if on:
            error = self.remote.start(self.remote.port) or ""
            self.settings.setValue("remote/port", self.remote.port)
        else:
            self.remote.stop()
        self.settings.setValue("remote/enabled", "true" if self.remote.running else "false")
        if self._remote_dialog is not None:
            self._remote_dialog.refresh(error)
        if self._guest_dialog is not None:
            self._guest_dialog.refresh(error)
        self._describe_remote()
        return error

    @Slot()
    def _open_guest_dialog(self) -> None:
        """The guest slide clicker: its own QR code, slides only. Switches the remote on if needed."""
        if not self.remote.guest:
            self._set_guest_link(True)
        error = "" if self.remote.running else self._toggle_remote(True)
        if self._guest_dialog is None:
            dialog = remote_mod.GuestDialog(self.remote, THEME, self)
            dialog.enabledToggled.connect(self._set_guest_link)
            dialog.renewRequested.connect(lambda: self._set_guest_link(True, renew=True))
            self._guest_dialog = dialog
        self._guest_dialog.refresh(error)
        self._guest_dialog.show()
        self._guest_dialog.raise_()
        self._guest_dialog.activateWindow()

    def _set_guest_link(self, on: bool, renew: bool = False) -> None:
        if on and (renew or not self.remote.guest):
            self.remote.guest = remote_mod.new_guest_token()
        elif not on:
            self.remote.guest = ""
        self.settings.setValue("remote/guest", self.remote.guest)
        if self._guest_dialog is not None:
            self._guest_dialog.refresh()

    def _renew_remote_pin(self) -> None:
        self.remote.pin = remote_mod.new_pin()
        self.settings.setValue("remote/pin", self.remote.pin)
        if self._remote_dialog is not None:
            self._remote_dialog.refresh()

    def remote_state(self) -> dict:
        """Everything the phone page draws, in one small JSON object."""
        steps = self.show_tab.steps()
        index = self.show_index if self.show_index < len(steps) else -1
        screens = []
        for role in STAGE_ROLES:
            path = self.cards[role].current_path()
            screens.append({"role": role, "label": ROLE_LABELS[role],
                            "open": self._show_output(role) is not None,
                            "file": os.path.basename(path) if path else ""})
        cues = [{"index": cue.index, "label": cue.label(), "filled": bool(cue.path),
                 "playing": cue.is_playing(), "paused": cue.is_paused()} for cue in self.sound.cues]
        return {
            "show": {"name": self.show_store.current, "index": index,
                     "steps": [{"title": s["title"] or "Untitled", "notes": s["notes"],
                                "summary": step_summary(s)} for s in steps],
                     "elapsed": time.monotonic() - self._show_started if index >= 0 else 0,
                     "auto": self._show_auto if index >= 0 else None},
            "screens": screens,
            "cues": cues,
            "presets": self.presets.names(),
            "preset": self.loaded_preset or "",
            "master": self.sound_master.value(),
            "slides": self._slides_state(),
        }

    def _slides_state(self) -> dict:
        presenter = self.presenter
        deck = presenter.deck
        return {"loaded": bool(deck and presenter.count()), "name": deck.name if deck else "",
                "count": presenter.count(), "index": presenter.index, "live": presenter.live,
                "black": presenter.black, "elapsed": presenter.elapsed(),
                "deck": deck.token if deck else "", "notes": presenter.notes(),
                "target": ROLE_LABELS.get(presenter.role, presenter.role),
                "powerpoint": presenter.playing_in_powerpoint()}

    def remote_action(self, action: str, data: dict):
        """One tap on the phone. Returns (ok, message for the phone)."""
        steps = self.show_tab.steps()
        if action == "next":
            if self.show_index + 1 >= len(steps):
                return False, "That was the last step."
            self.show_next()
            return True, f"{self.show_index + 1}. {steps[self.show_index]['title']}"
        if action == "back":
            if self.show_index <= 0:
                return False, "Already at the first step."
            self.show_back()
            return True, f"{self.show_index + 1}. {steps[self.show_index]['title']}"
        if action == "goto":
            try:
                index = int(data.get("index", -1))
            except (TypeError, ValueError):
                index = -1
            if not 0 <= index < len(steps):
                return False, "No such step."
            self.show_go(index)
            return True, f"{index + 1}. {steps[index]['title']}"
        if action == "restart":
            self.show_restart()
            return True, "Ready - NEXT starts step 1."
        if action == "blackout":
            self._blackout_all()
            return True, "Blackout."
        if action == "cue":
            try:
                index = int(data.get("index", -1))
            except (TypeError, ValueError):
                index = -1
            if not 0 <= index < len(self.sound.cues) or not self.sound.cues[index].path:
                return False, "That sound pad is empty."
            self._fire_cue(index)
            return True, ""
        if action == "silence":
            self._stop_all_sound()
            return True, "Fading out all sound."
        if action == "master":
            try:
                self.sound_master.setValue(max(0, min(100, int(data.get("value", 90)))))
            except (TypeError, ValueError):
                return False, "Bad volume."
            return True, ""
        if action.startswith("slide_"):
            return self._remote_slide_action(action, data)
        if action == "preset":
            name = str(data.get("name", ""))
            if name not in self.presets.names():
                return False, "No such preset."
            # later, so a dialog about a missing file cannot hold the phone's answer
            QTimer.singleShot(0, lambda: self._mini_load_preset(name))
            return True, f"Loading {name}."
        return False, "Unknown action."

    # ------------------------------------------------------ text slides ---- #

    def _build_text_tab(self) -> QWidget:
        self.text_slides = TextSlides()
        self.text_slides.showRequested.connect(self._show_slide)
        self.text_slides.hideRequested.connect(self._hide_slide)
        self.text_slides.styleChanged.connect(self._on_slide_style_changed)
        self.text_slides.targetChanged.connect(self._on_slide_target_changed)
        self.text_slides.stage_size = self._stage_size
        self.text_slides.preview_source = (
            lambda role, size: self._show_output(role).preview(size) if self._show_output(role) else None)
        try:
            self.text_slides.set_custom_looks(json.loads(self.settings.value("text/looks", "") or "{}"))
        except (ValueError, TypeError):
            pass
        self.text_slides.looksChanged.connect(
            lambda: self.settings.setValue("text/looks", json.dumps(self.text_slides.custom_looks)))
        return self.text_slides

    def _slide_output(self):
        role = self.text_slides.target.currentData() or ROLE_MAIN
        return role, getattr(self, self.OUTPUT_ATTRS[role], None)

    @Slot(str, str)
    def _show_slide(self, title: str, subtitle: str) -> None:
        role, window = self._slide_output()
        if window is None:
            QMessageBox.warning(
                self, "Output not open",
                f"“{ROLE_LABELS[role]}” has no output window yet.\n\n"
                "Open the “Screens & Setup” tab, pick a monitor for it, then press "
                "“OPEN OUTPUTS”.")
            return

        def apply() -> None:
            role_now, target = self._slide_output()
            if target is None:
                return
            target.set_slide_style(self.text_slides.style_dict())
            target.show_slide(title, subtitle, max(120, self.fade_ms() // 2))
            self.statusBar().showMessage(
                f"{ROLE_LABELS[role_now]}: {title}" + (f" — {subtitle}" if subtitle else ""), 8000)

        self._change_stage(f"{ROLE_LABELS[role]}  ←  “{title}”", apply,
                           self._text_thumb(title, subtitle), subtitle)

    @Slot()
    def _hide_slide(self) -> None:
        role, window = self._slide_output()
        if window is None:
            return
        window.hide_slide(max(120, self.fade_ms() // 2))
        self.statusBar().showMessage(f"{ROLE_LABELS[role]}: text hidden.", 5000)

    @Slot()
    def _on_slide_style_changed(self) -> None:
        self._mark_preset_dirty()
        _role, window = self._slide_output()
        if window is not None and window.slide_visible():
            window.set_slide_style(self.text_slides.style_dict())

    @Slot(str)
    def _on_slide_target_changed(self, _role: str) -> None:
        """Moving the text to another screen must not leave it on the old one."""
        for window in self._outputs():
            window.hide_slide(200)
        self._mark_preset_dirty()

    # --------------------------------------------------------- library ----- #

    @Slot()
    def build_show_from_folder(self) -> None:
        """
        Turn one event folder into a whole show.

        Everything for an assembly usually lives in a single folder already -
        the backgrounds, the clips, the fanfares. Reading the shape of each file
        is enough to sort it: the ceiling clips are 2816x128, the side clips are
        portrait, the rest is 16:9, and the sound is whatever is audio.
        """
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the folder for this event", self.library.current_folder() or "")
        if not folder:
            return
        folder = os.path.normpath(folder)

        files = scan_event_folder(folder)
        if not files:
            QMessageBox.information(
                self, "Nothing to import",
                f"No images, videos or sounds were found in\n{folder}")
            return

        progress = QProgressDialog("Looking at the files…", "Cancel", 0, len(files), self)
        progress.setWindowTitle("Building a show")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        rows = []
        for index, path in enumerate(files):
            if progress.wasCanceled():
                return
            progress.setValue(index)
            progress.setLabelText(os.path.basename(path))
            QApplication.processEvents()
            size = probe_media_size(path)
            rows.append((path, size, classify_media(path, size, folder)))
        progress.setValue(len(files))

        dialog = EventFolderDialog(folder, rows, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._apply_event_folder(folder, dialog.assignments(),
                                 dialog.replace_check.isChecked(),
                                 dialog.go_live_check.isChecked())

    def _apply_event_folder(self, folder: str, assignments: Dict[str, List[str]],
                            replace: bool, go_live: bool) -> None:
        if replace:
            for card in self.cards.values():
                card.playlist.clear_all()
                card.reset_file()
            for cue in self.sound.cues:
                cue.clear()

        placed = []
        for role in STAGE_ROLES:
            paths = assignments.get(role, [])
            if not paths:
                continue
            self.cards[role].playlist.add_paths(paths, announce=False)
            placed.append(f"{len(paths)} on {ROLE_LABELS[role]}")

        sounds = assignments.get("sound", [])
        skipped_sounds = max(0, len(sounds) - SOUND_SLOTS)
        for slot, path in enumerate(sounds[:SOUND_SLOTS]):
            try:
                self.sound.cues[slot].assign(path)
            except MediaProblem:
                pass
        if sounds:
            placed.append(f"{min(len(sounds), SOUND_SLOTS)} sound cue(s)")
        self._refresh_cue_pads()

        live_note = ""
        if go_live:
            # Only screens that actually have a window; otherwise this would
            # fire one "output not open" dialog per screen, in a row.
            open_roles = [r for r in STAGE_ROLES
                          if getattr(self, self.OUTPUT_ATTRS[r], None) is not None]
            with self._direct():
                for role in open_roles:
                    card = self.cards[role]
                    if card.playlist.count():
                        card.playlist.setCurrentRow(0)
                        card.loadRequested.emit(card.playlist.item(0).data(Qt.UserRole))
            if not open_roles:
                live_note = "  — nothing is on yet: press OPEN OUTPUTS first"


        self._mark_preset_dirty()
        self.library.set_folder(folder)
        self.tabs.setCurrentIndex(0)
        message = "Built from " + os.path.basename(folder) + ": " + ", ".join(placed)
        if skipped_sounds:
            message += f"  ({skipped_sounds} extra sound file(s) left out - only {SOUND_SLOTS} cues)"
        message += live_note
        self.statusBar().showMessage(message, 15000)

    def _build_library_tab(self) -> QWidget:
        self.library = MediaLibrary()
        self.library.showRequested.connect(self._library_show)
        self.library.queueRequested.connect(self._library_queue)
        self.library.cueRequested.connect(self._assign_cue)
        self.library.buildRequested.connect(self.build_show_from_folder)
        self.library.favouritesChanged.connect(
            lambda: self.settings.setValue("library/favourites", self.library.favourites()))
        return self.library

    def _restore_library_places(self) -> None:
        stored = self.settings.value("library/folders", [])
        if isinstance(stored, str):
            stored = [stored] if stored else []
        self.library.set_pinned([str(f) for f in (stored or [])])
        favourites = self.settings.value("library/favourites", [])
        if isinstance(favourites, str):
            favourites = [favourites] if favourites else []
        self.library.set_favourites([str(f) for f in (favourites or [])])
        last = self.settings.value("library/last", "")
        folders = self.library.pinned()
        self.library.set_folder(last if last and os.path.isdir(last)
                                else (folders[0] if folders else ""), defer_files=True)

    def _remember_library_places(self) -> None:
        self.settings.setValue("library/folders", self.library.pinned())
        self.settings.setValue("library/last", self.library.current_folder())

    @Slot(str, str)
    def _library_show(self, role: str, path: str) -> None:
        card = self.cards[role]
        card.playlist.add_paths([path], announce=False)   # keeps the playlist in step
        self.set_active_role(role)
        card.loadRequested.emit(path)

    @Slot(str, list)
    def _library_queue(self, role: str, paths: List[str]) -> None:
        target = role or self.active_role
        card = self.cards[target]
        added = card.playlist.add_paths(list(paths), announce=False)
        self._mark_preset_dirty()
        self.statusBar().showMessage(
            f"{ROLE_LABELS[target]}: {len(added)} item(s) added to the playlist"
            if added else "Already in that playlist.", 6000)

    # ----------------------------------------------------------- sound ----- #

    def _build_sound_bar(self) -> QWidget:
        """
        The sound desk, kept on the Live tab rather than a tab of its own.

        During a ceremony the operator is switching backgrounds and firing
        fanfares in the same minute; putting sound behind a tab would mean
        looking away from the screens at exactly the wrong moment.
        """
        bar = QFrame()
        bar.setObjectName("card")
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(14, 8, 14, 10)
        layout.setSpacing(7)

        header = QHBoxLayout()
        header.setSpacing(8)
        glyph = QLabel()
        glyph.setPixmap(Icons.get("volume", CLR_ACCENT, 16).pixmap(16, 16))
        header.addWidget(glyph)
        title = QLabel("Sound cues")
        title.setObjectName("sectionTitle")
        header.addWidget(title)

        hint = QLabel("drop sound files onto a pad · F1–F8 play and pause "
                      "· Shift+F… stops")
        hint.setObjectName("keyHint")
        header.addWidget(hint)
        header.addStretch(1)
        self.now_playing = QLabel("")
        self.now_playing.setToolTip("The sound that ends soonest, and how long it has left")
        header.addWidget(self.now_playing)
        header.addSpacing(10)

        header.addWidget(QLabel("Output"))
        self.audio_device_combo = QComboBox()
        self.audio_device_combo.setMinimumWidth(190)
        self.audio_device_combo.setToolTip("Which sound device every cue and video plays out of")
        self.audio_device_combo.currentIndexChanged.connect(self._on_audio_device_changed)
        header.addWidget(self.audio_device_combo)

        header.addSpacing(8)
        header.addWidget(QLabel("Master"))
        self.sound_master = QSlider(Qt.Horizontal)
        self.sound_master.setRange(0, 100)
        self.sound_master.setValue(self.sound.master)
        self.sound_master.setMaximumWidth(130)
        self.sound_master.valueChanged.connect(self._on_master_volume)
        header.addWidget(self.sound_master)

        fade_all = QPushButton("  Fade out")
        fade_all.setIcon(Icons.get("volume", CLR_TEXT, 15))
        fade_all.setToolTip("Fade every sound out gently, over three seconds")
        fade_all.clicked.connect(self._fade_all_sound)
        header.addWidget(fade_all)
        stop_all = QPushButton("  STOP SOUND")
        stop_all.setObjectName("danger")
        stop_all.setIcon(Icons.get("stop", CLR_DANGER, 15))
        stop_all.setToolTip("Fade out and rewind every cue (Ctrl+Space)")
        stop_all.clicked.connect(self._stop_all_sound)
        header.addWidget(stop_all)
        layout.addLayout(header)

        pads = QHBoxLayout()
        pads.setSpacing(7)
        self.cue_pads: List[CuePad] = []
        for index in range(SOUND_SLOTS):
            pad = CuePad(index)
            pad.assignRequested.connect(lambda path, i=index: self._assign_cue(i, path))
            pad.playPauseRequested.connect(lambda i=index: self._fire_cue(i))
            pad.stopRequested.connect(lambda i=index: self._stop_cue(i))
            pad.seekRequested.connect(lambda ms, i=index: self.sound.cues[i].seek(ms))
            pad.cleared.connect(lambda i=index: self._clear_cue(i))
            pad.loopToggled.connect(lambda on, i=index: self.sound.cues[i].set_loop(on))
            pads.addWidget(pad, 1)
            self.cue_pads.append(pad)
        layout.addLayout(pads)

        # One timer keeps the countdowns honest without a signal per cue.
        ticker = QTimer(self)
        ticker.timeout.connect(self._refresh_cue_pads)
        ticker.start(250)
        return bar

    def _refresh_audio_devices(self) -> None:
        from PySide6.QtMultimedia import QMediaDevices

        wanted = self.settings.value("sound/device", "")
        devices = QMediaDevices.audioOutputs()
        self.audio_device_combo.blockSignals(True)
        self.audio_device_combo.clear()
        self.audio_device_combo.addItem("System default", None)
        for device in devices:
            self.audio_device_combo.addItem(device.description(), device.description())
        index = self.audio_device_combo.findData(wanted) if wanted else -1
        self.audio_device_combo.setCurrentIndex(max(0, index))
        self.audio_device_combo.blockSignals(False)
        self._apply_audio_device()

    def _apply_audio_device(self) -> None:
        from PySide6.QtMultimedia import QMediaDevices

        wanted = self.audio_device_combo.currentData()
        device = None
        if wanted:
            device = next((d for d in QMediaDevices.audioOutputs()
                           if d.description() == wanted), None)
        if device is None:
            device = QMediaDevices.defaultAudioOutput()
        self.sound.set_device(device)
        for player in self._show_players:
            player.set_device(device)
        for window in self._outputs():
            window.engine.set_device(device)

    @Slot()
    def _on_audio_device_changed(self) -> None:
        self.settings.setValue("sound/device", self.audio_device_combo.currentData() or "")
        self._apply_audio_device()
        self.statusBar().showMessage(
            f"Sound output: {self.audio_device_combo.currentText()}", 5000)

    @Slot(int)
    def _on_master_volume(self, value: int) -> None:
        self.sound.set_master(value)
        for player in self._show_players:
            player.set_master(value)
        self.settings.setValue("sound/master", value)

    def _refresh_cue_pads(self) -> None:
        for pad, cue in zip(self.cue_pads, self.sound.cues):
            pad.show_cue(cue)
        self._refresh_now_playing()

    def _refresh_now_playing(self) -> None:
        """Big and plain: what is playing, and how long until it stops."""
        playing = [cue for cue in list(self.sound.cues) + list(self._show_players) if cue.is_playing()]
        if not playing:
            if self.now_playing.text():
                self.now_playing.setText("")
            return

        def left(cue) -> float:
            if cue.loop or cue.duration() <= 0:
                return float("inf")
            return max(0, cue.duration() - cue.position())

        cue = min(playing, key=left)
        remaining = left(cue)
        name = cue.label() + ("  (running order)" if cue in self._show_players else "")
        more = f"   +{len(playing) - 1}" if len(playing) > 1 else ""
        if remaining == float("inf"):
            text, colour = f"♪  {name}  ·  looping{more}", CLR_OK
        else:
            text = f"♪  {name}  ·  {format_time(int(remaining))} left{more}"
            colour = CLR_WARN if remaining < 10000 else CLR_OK
        self.now_playing.setText(text)
        self.now_playing.setStyleSheet(f"color: {colour}; font-size: 15px; font-weight: 700;")

    @Slot()
    def _fade_all_sound(self) -> None:
        self.sound.stop_all(3000)
        for player in self._show_players:
            player.stop(3000)
        self.statusBar().showMessage("Fading every sound out…", 4000)

    def _assign_cue(self, index: int, path: str) -> None:
        try:
            self.sound.cues[index].assign(path)
        except MediaProblem as problem:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle(problem.title)
            box.setText(f"<b>{problem.title}</b><br>Cue F{index + 1} was not changed.")
            box.setInformativeText(problem.message())
            box.setDetailedText(f"File:\n{path}")
            box.exec()
            return
        self._mark_preset_dirty()
        self._refresh_cue_pads()
        self.statusBar().showMessage(
            f"F{index + 1}: {os.path.basename(path)}", 5000)

    def _fire_cue(self, index: int) -> None:
        """Play, or pause if it is already running."""
        cue = self.sound.cues[index]
        if not cue.path:
            self.statusBar().showMessage(
                f"F{index + 1} is empty — drop a sound file on it first.", 5000)
            return
        cue.toggle()
        self._refresh_cue_pads()
        self.statusBar().showMessage(
            f"F{index + 1} {'playing' if cue.is_playing() else 'paused'}: {cue.label()}", 4000)

    def _stop_cue(self, index: int) -> None:
        cue = self.sound.cues[index]
        if not cue.path:
            return
        cue.stop()
        self._refresh_cue_pads()
        self.statusBar().showMessage(f"F{index + 1} stopped: {cue.label()}", 4000)

    def _clear_cue(self, index: int) -> None:
        self.sound.cues[index].clear()
        self._mark_preset_dirty()
        self._refresh_cue_pads()

    @Slot()
    def _stop_all_sound(self) -> None:
        self.sound.stop_all()
        for player in self._show_players:
            player.stop()
        self.statusBar().showMessage("All sound cues fading out.", 4000)

    def _on_cue_failed(self, index: int, message: str) -> None:
        cue = self.sound.cues[index]
        name = cue.label() or f"cue F{index + 1}"
        cue.clear()
        self._refresh_cue_pads()
        QMessageBox.warning(
            self, "Sound will not play",
            f"<b>{name}</b> could not be played.<br><br>"
            f"The audio backend said: {message}<br><br>"
            "Convert it to MP3 or WAV and assign it again.",
        )

    # ------------------------------------------------------- keyboard ------ #

    def _tick_clock(self) -> None:
        self.clock.setText(QTime.currentTime().toString("HH:mm:ss"))

    # ------------------------------------------------------- transitions --- #

    def fade_ms(self) -> int:
        """Current transition length; 0 means hard cut."""
        value = self.fade_combo.currentData()
        return int(value) if value is not None else 0

    def fade_style(self) -> str:
        return self.style_combo.currentData() or TRANSITION_CROSSFADE

    def _load_fade_setting(self) -> None:
        stored = self.settings.value("playback/fade_ms", DEFAULT_FADE_MS)
        try:
            stored = int(stored)
        except (TypeError, ValueError):
            stored = DEFAULT_FADE_MS
        index = self.fade_combo.findData(stored)
        self.fade_combo.blockSignals(True)
        self.fade_combo.setCurrentIndex(index if index >= 0 else
                                        self.fade_combo.findData(DEFAULT_FADE_MS))
        self.fade_combo.blockSignals(False)

        style = self.settings.value("playback/fade_style", TRANSITION_CROSSFADE)
        index = self.style_combo.findData(style)
        self.style_combo.blockSignals(True)
        self.style_combo.setCurrentIndex(max(0, index))
        self.style_combo.blockSignals(False)

    @Slot()
    def _on_fade_changed(self) -> None:
        milliseconds = self.fade_ms()
        self.settings.setValue("playback/fade_ms", milliseconds)
        self.settings.setValue("playback/fade_style", self.fade_style())
        if milliseconds == 0:
            self.statusBar().showMessage("Transitions off — pictures change instantly.", 5000)
        else:
            name = "crossfade" if self.fade_style() == TRANSITION_CROSSFADE else "fade through black"
            self.statusBar().showMessage(f"Transition: {name} over {milliseconds} ms.", 5000)

    def set_active_role(self, role: str) -> None:
        """Choose which card the keyboard shortcuts drive."""
        self.active_role = role
        for name, card in self.cards.items():
            card.set_active(name == role)

    def _active_card(self) -> OutputCard:
        return self.cards[self.active_role]

    def _install_shortcuts(self) -> None:
        """
        Live-operation keys. During a show the mouse is slow and the operator is
        often looking at the stage, not the screen.
        """
        def clicker_or(name: str, fallback=None):
            # While slides are on screen these keys turn slides, the way a
            # clicker expects; otherwise they keep their stage meaning.
            return lambda: self._clicker_key(name, fallback)

        bindings = (
            ("1", lambda: self.set_active_role(ROLE_MAIN)),
            ("2", lambda: self.set_active_role(ROLE_SIDES)),
            ("3", lambda: self.set_active_role(ROLE_TOP)),
            ("Space", clicker_or("Space", self._toggle_active_playback)),
            ("Right", clicker_or("Right", lambda: self._active_card().playlist.step(1))),
            ("Left", clicker_or("Left", lambda: self._active_card().playlist.step(-1))),
            ("B", clicker_or("B", self._blackout_all)),
            ("Ctrl+O", self._apply_routing),
            ("Ctrl+Space", self._stop_all_sound),
            ("Ctrl+Right", lambda: self.text_slides.step(1)),
            ("Ctrl+Left", lambda: self.text_slides.step(-1)),
            ("Ctrl+H", self._hide_slide),
            # What a wireless presenter clicker sends: slides when a
            # presentation is on screen, the running order otherwise.
            ("PgDown", clicker_or("PgDown")),
            ("PgUp", clicker_or("PgUp")),
        )
        bindings += tuple(
            (f"F{slot + 1}", clicker_or(f"F{slot + 1}", lambda i=slot: self._fire_cue(i)))
            for slot in range(SOUND_SLOTS)
        )
        bindings += tuple(
            (f"Shift+F{slot + 1}", clicker_or(f"Shift+F{slot + 1}", lambda i=slot: self._stop_cue(i)))
            for slot in range(SOUND_SLOTS)
        )

        # Keys that drive the stage screens step aside on the DJ tab, where Space
        # and the arrows would otherwise pause a background mid-mix.
        self._stage_shortcuts: List[QShortcut] = []
        for key, handler in bindings:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(handler)
            if key in ("1", "2", "3", "Space", "Left", "Right"):
                self._stage_shortcuts.append(shortcut)

        # Other keys clickers send, live only while slides are on screen.
        for name in ("Down", "Up", "Return", "Enter", "Backspace", "N", "P", ".", "Esc"):
            shortcut = QShortcut(QKeySequence(name), self)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(lambda n=name: self._clicker_key(n))
            shortcut.setEnabled(False)
            self._slide_shortcuts.append(shortcut)
        self._install_learned_keys()
        BaseOutputWindow.key_router = self._route_output_key
        # PREVIEW -> TAKE
        self._take_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        self._take_shortcut.setContext(Qt.ApplicationShortcut)
        self._take_shortcut.activated.connect(self._take)
        self._cancel_shortcut = QShortcut(QKeySequence("Esc"), self)
        self._cancel_shortcut.setContext(Qt.ApplicationShortcut)
        self._cancel_shortcut.activated.connect(self._cancel_take)
        self._take_shortcut.setEnabled(False)
        self._cancel_shortcut.setEnabled(False)
        undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        undo.setContext(Qt.ApplicationShortcut)
        undo.activated.connect(self._undo)

    # ----------------------------------------------------------- clicker --- #

    def _learned(self) -> Dict[str, dict]:
        try:
            data = json.loads(self.settings.value("clicker/learned", "") or "{}")
            return {k: v for k, v in data.items() if isinstance(v, dict) and v.get("name")}
        except (ValueError, TypeError, AttributeError):
            return {}

    def _slide_action_for(self, name: str) -> Optional[str]:
        for action, info in self._learned().items():
            if info.get("name") == name:
                return action
        if name in pres_mod.NEXT_KEYS:
            return "next"
        if name in pres_mod.BACK_KEYS:
            return "back"
        if name in pres_mod.BLACK_KEYS:
            return "black"
        if name in ("F5", "Shift+F5"):
            return "start"              # the clicker's "start slideshow" button
        if name == "Esc":
            return "end"
        return None

    def _clicker_key(self, name: str, fallback=None, source: str = "") -> bool:
        """
        One key from the keyboard or a clicker. Slides get it while they are on
        screen; otherwise the clicker's forward / back walk the running order,
        and every other key does what it always did.
        """
        action = self._slide_action_for(name)
        if self._ready_check_open():
            # the operator is testing the clicker: note it, move nothing
            self.presentation_tab.show_key(name, "test ✓", source)
            return True
        if self.presenter.live and action:
            self._do_slide(action, name, source)
            return True
        learned = any(info.get("name") == name for info in self._learned().values())
        if action in ("next", "back") and (name in ("PgDown", "PgUp") or learned):
            self.presentation_tab.show_key(name, f"running order {action}", source)
            (self.show_next if action == "next" else self.show_back)()
            return True
        if fallback is not None:
            fallback()
            return True
        return False

    def _do_slide(self, action: str, name: str, source: str) -> None:
        presenter = self.presenter
        if action == "next":
            presenter.next()
        elif action == "back":
            presenter.back()
        elif action == "black":
            presenter.toggle_black()
        elif action == "start":
            if presenter.black:
                presenter.toggle_black()
        elif action == "end":
            presenter.end()
        labels = {"next": "next slide", "back": "previous slide", "black": "black",
                  "start": "show", "end": "end presentation"}
        self.presentation_tab.show_key(name, labels.get(action, action), source)

    def _route_output_key(self, event) -> bool:
        """Keys pressed while a stage window has focus (see BaseOutputWindow.key_router)."""
        name = QKeySequence(event.key()).toString()
        if event.modifiers() & Qt.ShiftModifier and name.startswith("F"):
            name = "Shift+" + name
        return self._clicker_key(name, None, "stage screen had focus")

    def _install_learned_keys(self) -> None:
        for shortcut in self._learned_shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._learned_shortcuts = []
        taken = {QKeySequence(s.key()).toString() for s in self.findChildren(QShortcut)
                 if s.isEnabled() or s in self._slide_shortcuts}
        for info in self._learned().values():
            name = info["name"]
            if name in taken or not info.get("key"):
                continue                   # an ordinary key: already routed above
            shortcut = QShortcut(QKeySequence(int(info["key"])), self)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(lambda n=name: self._clicker_key(n))
            self._learned_shortcuts.append(shortcut)

    def _clicker_global(self) -> bool:
        return str(self.settings.value("clicker/global", "true")).lower() == "true"

    def _on_clicker_global(self, on: bool) -> None:
        self.settings.setValue("clicker/global", "true" if on else "false")
        self._update_hotkeys()

    def _update_hotkeys(self) -> None:
        want = self.presenter.live and self._clicker_global()
        if want and not self._hotkeys:
            self._register_hotkeys()
        elif not want and self._hotkeys:
            self._unregister_hotkeys()

    def _register_hotkeys(self) -> None:
        """
        While slides are on screen, the clicker's keys reach this app even when
        another program has focus (Windows RegisterHotKey). Released the moment
        the presentation ends.
        """
        if sys.platform != "win32":
            return
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        keys = dict(VK_BY_NAME)
        for info in self._learned().values():
            if info.get("vk"):
                keys.setdefault(info["name"], int(info["vk"]))
        hwnd = int(self.winId())
        refused = []
        for number, (name, vk) in enumerate(keys.items()):
            hotkey_id = 0xB100 + number
            if user32.RegisterHotKey(hwnd, hotkey_id, 0x4000, vk):      # MOD_NOREPEAT
                self._hotkeys[hotkey_id] = name
            else:
                refused.append(name)
        if refused:
            self.presentation_tab.show_status(
                "Another program already uses " + ", ".join(refused)
                + " - the clicker works while this window is in front.", CLR_WARN)

    def _unregister_hotkeys(self) -> None:
        if sys.platform == "win32":
            user32 = ctypes.WinDLL("user32")
            hwnd = int(self.winId())
            for hotkey_id in list(self._hotkeys):
                user32.UnregisterHotKey(ctypes.c_void_p(hwnd), hotkey_id)
        self._hotkeys = {}

    def nativeEvent(self, event_type, message):  # noqa: N802
        if self._hotkeys:
            try:
                if bytes(event_type) == b"windows_generic_MSG":
                    from ctypes import wintypes
                    msg = wintypes.MSG.from_address(int(message))
                    name = self._hotkeys.get(int(msg.wParam)) if msg.message == WM_HOTKEY else None
                    if name:
                        QTimer.singleShot(0, lambda n=name: self._clicker_key(n, None, "from any program"))
                        return True, 0
            except (TypeError, ValueError, OSError):
                pass
        return super().nativeEvent(event_type, message)

    @Slot()
    def _learn_clicker(self) -> None:
        # The clicker's keys must reach the dialog, not the shortcuts they would trigger.
        shortcuts = [s for s in self.findChildren(QShortcut) if s.isEnabled()]
        for shortcut in shortcuts:
            shortcut.setEnabled(False)
        had_hotkeys = bool(self._hotkeys)
        self._unregister_hotkeys()
        dialog = pres_mod.LearnDialog(THEME, self)
        accepted = dialog.exec() == QDialog.Accepted
        for shortcut in shortcuts:
            shortcut.setEnabled(True)
        if accepted and dialog.learned:
            self.settings.setValue("clicker/learned", json.dumps(dialog.learned))
            self._install_learned_keys()
            names = ", ".join(f"{k}: {v['name']}" for k, v in dialog.learned.items())
            self.presentation_tab.show_status(f"Clicker learned - {names}", CLR_OK)
        if had_hotkeys:
            self._update_hotkeys()

    # ----------------------------------------------------- presentations --- #

    def _build_presentation_tab(self) -> QWidget:
        tab = pres_mod.PresentationTab(self.presenter, Icons, THEME,
                                       {role: ROLE_LABELS[role] for role in STAGE_ROLES},
                                       touch=self.touch_enabled())
        self.presentation_tab = tab
        tab.set_recent(self._recent_decks())
        tab.openedPath.connect(self._remember_deck)
        tab.learnRequested.connect(self._learn_clicker)
        tab.guestRequested.connect(self._open_guest_dialog)
        tab.global_check.setChecked(self._clicker_global())
        tab.globalToggled.connect(self._on_clicker_global)
        tab.powerpointToggled.connect(
            lambda on: self.settings.setValue("slides/powerpoint", "true" if on else "false"))
        tab.limit_spin.setValue(int(self.settings.value("slides/limit", 0) or 0))
        tab.countdown_combo.setCurrentIndex(max(0, tab.countdown_combo.findData(
            str(self.settings.value("slides/countdown", "") or ""))))
        tab.limitChanged.connect(lambda minutes: self.settings.setValue("slides/limit", minutes))
        tab.countdownTargetChanged.connect(lambda role: self.settings.setValue("slides/countdown", role))
        tab.countdown.connect(self._on_countdown)
        return tab

    @Slot(str, str, str)
    def _on_countdown(self, role: str, text: str, colour: str) -> None:
        window = self._show_output(role) if role in STAGE_ROLES else None
        if window is not None:
            window.set_corner_text(text, colour)

    def _recent_decks(self) -> List[str]:
        stored = self.settings.value("slides/recent", [])
        if isinstance(stored, str):
            stored = [stored] if stored else []
        return [p for p in (stored or []) if os.path.exists(p)]

    def _remember_deck(self, path: str) -> None:
        recent = [path] + [p for p in self._recent_decks() if os.path.normcase(p) != os.path.normcase(path)]
        self.settings.setValue("slides/recent", recent[:8])
        self.presentation_tab.set_recent(recent[:8])

    @Slot(str)
    def _on_presenter_note(self, text: str) -> None:
        self.statusBar().showMessage(text, 6000)
        self.presentation_tab.show_status(text, CLR_WARN)

    @Slot()
    def _on_presenter_changed(self) -> None:
        if hasattr(self, "_cancel_shortcut"):
            self._sync_take_keys()
        live = self.presenter.live
        for shortcut in self._slide_shortcuts:
            shortcut.setEnabled(live)
        self._update_hotkeys()
        if live != self._was_live:
            self._was_live = live
            deck = self.presenter.deck
            self.statusBar().showMessage(
                (f"Slides on {ROLE_LABELS.get(self.presenter.role)}: {deck.name}" if live and deck
                 else "Presentation ended - background back on screen."), 6000)

    def _remote_slide_action(self, action: str, data: dict):
        presenter = self.presenter
        count = presenter.count()
        if not count:
            return False, "No presentation is open."
        if action in ("slide_next", "slide_back") and presenter.playing_in_powerpoint():
            # PowerPoint plays the next animation or slide; the phone sees the result on its next poll
            (presenter.next if action == "slide_next" else presenter.back)()
            self.presentation_tab.show_key("phone", "next" if action == "slide_next" else "back")
            return True, "Next." if action == "slide_next" else "Back."
        if action == "slide_next":
            moved = presenter.next()
            self.presentation_tab.show_key("phone", "next slide")
            return (True, f"{presenter.index + 1} / {count}") if moved else (False, "Last slide.")
        if action == "slide_back":
            moved = presenter.back()
            self.presentation_tab.show_key("phone", "previous slide")
            return (True, f"{presenter.index + 1} / {count}") if moved else (False, "First slide.")
        if action == "slide_goto":
            try:
                presenter.goto(int(data.get("index", 0)))
            except (TypeError, ValueError):
                return False, "No such slide."
            return True, f"{presenter.index + 1} / {count}"
        if action == "slide_black":
            if not presenter.live:
                return False, "The slides are not on screen."
            presenter.toggle_black()
            return True, "Black." if presenter.black else "Back on screen."
        if action == "slide_live":
            if data.get("on", True):
                presenter.go_live()
                return True, f"Slides on {ROLE_LABELS.get(presenter.role)}."
            presenter.end()
            return True, "Presentation ended."
        return False, "Unknown action."

    def _remote_slide_image(self, token: str, index: int) -> Optional[bytes]:
        deck = self.presenter.deck
        if deck is None or deck.token != token:
            return None
        return deck.jpeg(index)

    @Slot(int)
    def _on_tab_changed(self, index: int) -> None:
        on_dj = self.tabs.widget(index) is self.dj_page
        for shortcut in self._stage_shortcuts:
            shortcut.setEnabled(not on_dj)
        # Presets describe the stage screens; the DJ desk wants the height.
        # The header, with BLACKOUT, stays.
        self.preset_bar.setVisible(self.tabs.widget(index) in (self.tabs.widget(0), self.library))
        if on_dj and self.dj_panel is None:
            self._build_dj_panel()
        self._refresh_show_strip()

    def _build_dj_panel(self) -> None:
        try:
            import dj
        except ImportError as exc:
            note = QLabel(
                "The DJ desk needs numpy, which is not installed.\n\n"
                "Install it with:   python -m pip install numpy\n\n"
                f"({exc})"
            )
            note.setAlignment(Qt.AlignCenter)
            note.setObjectName("cardHint")
            self.dj_page.layout().addWidget(note)
            self.dj_panel = False
            return
        self.dj_panel = dj.DJPanel(self.settings, self.settings.value("sound/device", "") or None,
                                   touch=self.touch_enabled())
        self.dj_page.layout().addWidget(self.dj_panel)

    @Slot()
    def _toggle_active_playback(self) -> None:
        window = getattr(self, self.OUTPUT_ATTRS[self.active_role], None)
        if window is None:
            return
        player = window.engine.player
        playing = getattr(QMediaPlayer, "PlaybackState", None)
        state_playing = getattr(playing, "PlayingState", None) if playing else None
        if player.playbackState() == state_playing:
            window.engine.pause()
        else:
            window.engine.play()

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

        heading = QLabel("Display routing")
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

        close_outputs = desk_mod.HoldButton("  Close outputs", THEME)
        close_outputs.setIcon(Icons.get("close", CLR_TEXT, 16))
        close_outputs.setToolTip("Close every stage output window (the app keeps running) - hold to confirm")
        close_outputs.clicked.connect(self._close_all_outputs)
        buttons.addWidget(close_outputs)

        buttons.addSpacing(14)
        fade_label = QLabel("Transition")
        fade_label.setObjectName("cardHint")
        buttons.addWidget(fade_label)
        self.fade_combo = QComboBox()
        for caption, milliseconds in FADE_PRESETS:
            self.fade_combo.addItem(caption, milliseconds)
        self.fade_combo.setToolTip(
            "How long a change of picture takes.\n"
            "Applies to every screen, to playlist steps and to blackouts."
        )
        self.fade_combo.currentIndexChanged.connect(self._on_fade_changed)
        buttons.addWidget(self.fade_combo)

        self.style_combo = QComboBox()
        for caption, value in TRANSITION_STYLES:
            self.style_combo.addItem(caption, value)
        self.style_combo.setToolTip(
            "Crossfade dissolves the old picture into the new one - the hall never "
            "goes dark.\nThrough black fades out, swaps, then fades in."
        )
        self.style_combo.currentIndexChanged.connect(self._on_fade_changed)
        buttons.addWidget(self.style_combo)

        buttons.addStretch(1)
        card_layout.addLayout(buttons)
        layout.addWidget(card)
        layout.addWidget(self._build_autostart_card())
        layout.addWidget(self._build_touch_card())

        tips = QFrame()
        tips.setObjectName("card")
        tips_layout = QVBoxLayout(tips)
        tips_layout.setContentsMargins(16, 14, 16, 16)
        tips_layout.setSpacing(8)
        tip_title = QLabel("Running a show")
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

    def _build_touch_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        box = QHBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(10)
        heading = QLabel("Touch screen")
        heading.setObjectName("sectionTitle")
        box.addWidget(heading)
        self.touch_combo = QComboBox()
        for caption, value in TOUCH_MODES:
            self.touch_combo.addItem(caption, value)
        wanted = self.settings.value("ui/touch", "auto")
        self.touch_combo.setCurrentIndex(max(0, self.touch_combo.findData(wanted)))
        self.touch_combo.setToolTip(
            "Larger buttons, sliders and lists for fingers, and lists that scroll with a flick.\n"
            "Automatic switches them on when Windows reports a touch screen.")
        self.touch_combo.currentIndexChanged.connect(self._on_touch_changed)
        box.addWidget(self.touch_combo)
        self.touch_note = QLabel()
        self.touch_note.setObjectName("cardHint")
        box.addWidget(self.touch_note, 1)
        return card

    def touch_enabled(self) -> bool:
        mode = self.settings.value("ui/touch", "auto")
        if mode == "on":
            return True
        if mode == "off":
            return False
        return touch_screen_present()

    def _apply_touch_mode(self) -> None:
        touch = self.touch_enabled()
        app = QApplication.instance()
        sheet = STYLESHEET + (TOUCH_STYLESHEET if touch else "")
        if app.styleSheet() != sheet:
            app.setStyleSheet(sheet)
        # A finger flicks a list rather than rubber-banding a selection; the
        # mouse still drags items as before. Only item lists: a scroller over
        # a panel of sliders would steal every drag from the sliders.
        for area in self.findChildren(QAbstractItemView):
            if touch:
                QScroller.grabGesture(area.viewport(), QScroller.TouchGesture)
            else:
                QScroller.ungrabGesture(area.viewport())
        detected = "a touch screen is connected" if touch_screen_present() else "no touch screen found"
        self.touch_note.setText(
            f"{'On' if touch else 'Off'} — {detected}."
            + ("  The DJ tab picks up the change the next time the app starts."
               if self.dj_panel else ""))

    @Slot()
    def _on_touch_changed(self) -> None:
        self.settings.setValue("ui/touch", self.touch_combo.currentData())
        self._apply_touch_mode()

    def _build_autostart_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 14, 16, 16)
        box.setSpacing(9)

        heading = QLabel("Start with Windows")
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
            if output() is None:
                put_on(path)          # says why it cannot, at once
                return
            self._change_stage(f"{ROLE_LABELS[role]}  ←  {os.path.basename(path)}",
                               lambda: put_on(path), self._thumb_for_path(path))

        def put_on(path: str) -> None:
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
            try:
                window.set_scale_mode(card.current_scale_mode())
                window.engine.set_loop(card.is_repeating())
                window.present(path, self.fade_ms(), self.fade_style())
            except MediaProblem as problem:
                self._report_media_problem(role, path, problem)
                return
            except Exception as exc:  # never let one bad file take the app down
                self._report_media_problem(
                    role, path,
                    MediaProblem("Could not show this file",
                                 f"{os.path.basename(path)}\n\n{type(exc).__name__}: {exc}"),
                )
                return
            card.show_loaded(path)
            self._mark_preset_dirty()
            self.statusBar().showMessage(f"{ROLE_LABELS[role]}: {os.path.basename(path)}", 6000)

        card.loadRequested.connect(on_load)
        card.queueRequested.connect(
            lambda paths: self.statusBar().showMessage(
                f"{ROLE_LABELS[role]}: {len(paths)} item(s) added to the playlist", 5000
            )
        )
        card.scaleModeChanged.connect(lambda mode: output() and output().set_scale_mode(mode))
        for changed in (card.scaleModeChanged, card.repeatChanged, card.muteChanged,
                        card.queueRequested, card.volumeChanged):
            changed.connect(lambda *_a: self._mark_preset_dirty())
        card.playRequested.connect(lambda: output() and output().engine.play())
        card.pauseRequested.connect(lambda: output() and output().engine.pause())
        card.stopRequested.connect(lambda: output() and output().engine.stop())
        card.clearRequested.connect(lambda: self._record_change(
            f"{ROLE_LABELS[role]}  →  black", lambda: output() and output().fade_clear(self.fade_ms())))
        card.volumeChanged.connect(lambda value: output() and output().engine.set_volume(value))
        card.muteChanged.connect(lambda muted: output() and output().engine.set_muted(muted))
        card.repeatChanged.connect(lambda on: output() and output().engine.set_loop(on))

    # -------------------------------------------------- problem reporting -- #

    def _report_media_problem(self, role: str, path: str, problem: MediaProblem) -> None:
        """One clear dialog instead of a frozen or blank screen."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(problem.title)
        box.setText(f"<b>{problem.title}</b><br>{ROLE_LABELS[role]} was not changed.")
        box.setInformativeText(problem.message())
        box.setDetailedText(f"File:\n{path}")
        box.setStandardButtons(QMessageBox.Ok)
        box.exec()
        self.statusBar().showMessage(
            f"{ROLE_LABELS[role]}: {os.path.basename(path)} refused — {problem.title}", 12000
        )

    def _on_engine_error(self, role: str, message: str) -> None:
        """
        Playback errors used to vanish silently: the signal was never connected,
        so an unplayable codec looked like the app hanging for no reason.
        """
        card = self.cards.get(role)
        name = os.path.basename(card.current_path()) if card and card.current_path() else "the clip"
        window = getattr(self, self.OUTPUT_ATTRS[role], None)
        if window is not None:
            window.clear_output()      # do not leave a frozen half-frame on stage
        if card is not None:
            card.reset_file()
        self._report_media_problem(
            role,
            card.current_path() if card else "",
            MediaProblem(
                "This video will not play on this PC",
                f"{name}\n\nThe video backend reported:\n{message}\n\n"
                "The container opened, so this is almost certainly the codec inside it - "
                "H.265/HEVC, VP9 and AV1 are not supported here.",
                CONVERT_ADVICE,
            ),
        )

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
        if self._rehearsal is not None:
            # the rehearsal screens follow; the stage windows are not touched
            self._push_top_settings()
            self._restore_media_to_outputs()
            self._update_output_status()
            return
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

        self._freshly_opened = set()   # filled by _ensure_output below

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
            self._freshly_opened.add(role)   # nothing on it yet, so do not fade in
            window = cls(title)
            window.set_scale_mode(card.current_scale_mode())
            window.closedByUser.connect(
                lambda bound_role=role, name=title: self._on_output_closed(bound_role, name)
            )
            # Feed the card's position bar; these die with the window.
            player = window.engine.player
            player.positionChanged.connect(card.set_position)
            player.durationChanged.connect(card.set_duration)
            card.seekRequested.connect(player.setPosition)
            window.engine.errorOccurred.connect(
                lambda message, bound=role: self._on_engine_error(bound, message)
            )

        window.engine.set_loop(card.is_repeating())
        window.engine.set_volume(card.volume_slider.value())
        window.engine.set_muted(card.mute_btn.isChecked())
        window.set_always_on_top(self.routing_rows[role].on_top_check.isChecked())
        window.show_with_geometry(screen, self._rect_for(role, screen))
        return window

    def _restore_media_to_outputs(self) -> None:
        """
        Re-send whatever each card has loaded - after reopening a window, or
        when a preset changes every screen at once.

        A screen that was already showing something transitions into the new
        picture; one whose window has only just been created cuts straight in,
        because there is nothing to dissolve away from.
        """
        for role, card in self.cards.items():
            window = getattr(self, self.OUTPUT_ATTRS[role], None)
            path = card.current_path()
            if window is None or not path or not os.path.isfile(path):
                continue
            window.set_scale_mode(card.current_scale_mode())
            fade = 0 if role in self._freshly_opened else self.fade_ms()
            try:
                window.present(path, fade, self.fade_style())
            except MediaProblem as problem:
                self._report_media_problem(role, path, problem)
                card.reset_file()

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
        """
        Put the dashboard on the operator's monitor - but only if it is not
        already there.

        Applying a preset used to drag the window to a fixed offset every time,
        un-maximising it and shoving it off to one side, which then had to be
        dragged back by hand before every show.
        """
        handle = self.windowHandle()
        if handle is not None and handle.screen() is screen:
            return
        was_maximised = self.isMaximized()
        if was_maximised:
            self.showNormal()
        geometry = screen.geometry()
        if handle is not None:
            handle.setScreen(screen)
        self.move(geometry.x() + 50, geometry.y() + 40)
        if was_maximised:
            self.showMaximized()

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
        if self._rehearsal is not None:
            self.statusBar().showMessage("End the rehearsal first.", 5000)
            return
        for window in self._outputs():
            window.clear_output()
            window.force_close()
            window.deleteLater()
        self.main_output = self.sides_output = self.top_output = None
        self._update_output_status()
        self.statusBar().showMessage("All stage outputs closed.", 5000)

    @Slot()
    def _blackout_all(self) -> None:
        def black() -> None:
            fade = self.fade_ms()
            for window in self._outputs():
                window.fade_clear(fade)
            if self.top_output is not None:
                self.top_output.stop_marquee()
            for card in self.cards.values():
                card.reset_file()
        self._record_change("BLACKOUT  -  every screen to black", black)
        self.statusBar().showMessage("BLACKOUT — every stage screen cleared.  (Ctrl+Z puts it back)", 6000)

    def _outputs(self):
        return [w for w in (self.main_output, self.sides_output, self.top_output) if w is not None]

    def _update_output_status(self) -> None:
        for role in STAGE_ROLES:
            is_open = getattr(self, self.OUTPUT_ATTRS[role], None) is not None
            if role in getattr(self, "cards", {}):
                self.cards[role].set_output_open(is_open)
        if hasattr(self, "cards"):
            self._refresh_multiview()

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
        fade = self.fade_ms()
        self.top_output.transition(
            lambda: self.top_output.set_background_color(colour), fade, self.fade_style()
        )
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

        self._rebuild_preset_strip()

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
            "sound": {"master": self.sound.master, "cues": self.sound.to_list()},
            "slides": self.text_slides.to_dict(),
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

        self.text_slides.from_dict(payload.get("slides", {}))

        sound_data = payload.get("sound", {})
        if sound_data:
            self.sound_master.setValue(int(sound_data.get("master", self.sound.master)))
            missing += self.sound.from_list(sound_data.get("cues", []))
            self._refresh_cue_pads()

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
    def _new_preset(self) -> None:
        """
        Blank slate for building a fresh show.

        Monitor routing is deliberately kept: that describes the hall's wiring,
        not the event, and re-picking three screens every time would be a chore.
        """
        if self._preset_dirty and self.loaded_preset:
            answer = QMessageBox.question(
                self,
                "Unsaved changes",
                f"“{self.loaded_preset}” has changes that are not saved.\n\n"
                "Save them before starting a new show?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if answer == QMessageBox.Cancel:
                return
            if answer == QMessageBox.Save:
                self._save_preset()

        for role, card in self.cards.items():
            card.reset_file()
            card.playlist.clear_all()
            card.set_scale_mode(ScaleMode.FIT if role == ROLE_MAIN else ScaleMode.CROP)
            card.volume_slider.setValue(80)
            card.mute_btn.setChecked(False)
            card.repeat_btn.setChecked(True)

        self.top_card.text_edit.clear()
        self.top_card.size_spin.setValue(max(24, int(DEFAULT_TOP_HEIGHT * 0.72)))
        self.top_card.speed_slider.setValue(180)
        self.top_card.set_background_colour_value(QColor("#101828"))

        self.text_slides.set_text("")
        self._hide_slide()

        for cue in self.sound.cues:
            cue.clear()
        self.sound_master.setValue(90)
        self._refresh_cue_pads()

        for window in self._outputs():
            window.clear_output()
        if self.top_output is not None:
            self.top_output.stop_marquee()

        self.loaded_preset = None
        self._preset_dirty = False
        self._describe_preset_state()
        self.preset_state.setText("blank — build the show, then “Save as new…”")
        self.preset_state.setStyleSheet(f"color: {CLR_ACCENT}; font-weight: 600;")
        self.statusBar().showMessage(
            "Cleared. Screens are black, cues are empty, monitor routing kept.", 8000)

    @Slot()
    def _load_preset(self) -> None:
        name = self.preset_combo.currentText()
        payload = self.presets.get(name) if self.preset_combo.isEnabled() else None
        if not payload:
            QMessageBox.information(self, "No preset", "Save a preset first, then it can be loaded.")
            return

        def apply() -> None:
            self._apply_preset(payload)
            self.loaded_preset = name
            self._preset_dirty = False
            self._describe_preset_state()
            self.statusBar().showMessage(f"Preset loaded: {name}", 6000)

        main_file = payload.get("outputs", {}).get(ROLE_MAIN, {}).get("file", "")
        self._change_stage(f"Preset  “{name}”", apply,
                           self._thumb_for_path(main_file) if main_file else None,
                           "every screen, the sound cues and the marquee")

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
        if self.sender() is not None and not isinstance(self.sender(), desk_mod.HoldButton):
            # from the right-click menu: no hold there, so ask
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
        if select:
            self.loaded_preset = select
            self._preset_dirty = False
        self._refresh_preset_combo(select)
        self._describe_preset_state()
        self.statusBar().showMessage(f"Presets saved to {PRESET_FILE}", 6000)

    # ------------------------------------------------------------ shutdown -- #

    def _restore_window_geometry(self) -> None:
        """
        Come back the size it was left, and fill the screen the first time.

        The key is versioned: the old one held a small hand-sized window from
        before this defaulted to maximised, and that would have kept winning.
        """
        saved = self.settings.value("window/geometry2")
        restored = bool(saved is not None and self.restoreGeometry(saved))

        # A saved geometry is only worth keeping if it still lands on a screen
        # that exists. The LED processors come and go, and a rectangle recorded
        # against yesterday's monitor arrangement leaves the window stranded at
        # an odd size or half off the desktop.
        if restored and not self.isMaximized():
            frame = self.frameGeometry()
            on_screen = any(s.availableGeometry().intersects(frame)
                            for s in QGuiApplication.screens())
            too_small = frame.width() < 900 or frame.height() < 600
            if not on_screen or too_small:
                restored = False

        if not restored:
            # Windows ignores "maximised" for a window whose starting size is
            # below its minimum, which finger-sized controls can push past the
            # default 1380x940 - and the minimum is not known until the
            # stylesheet is applied at show time. Start at the work area's size.
            area = QGuiApplication.primaryScreen().availableGeometry()
            self.resize(area.width() - 16, area.height() - 40)
            self.setWindowState(self.windowState() | Qt.WindowMaximized)

    def closeEvent(self, event) -> None:  # noqa: N802
        """Closing the control panel tears down every stage window, then quits."""
        live = self._outputs()
        if live:
            # Quitting mid-show blacks out the hall; make it a deliberate act.
            answer = QMessageBox.question(
                self,
                "Stage outputs are live",
                f"{len(live)} stage screen(s) are still showing content.\n\n"
                "Quitting closes them and blacks out the stage. Quit anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return

        self.sound.stop_all(0)
        for player in self._show_players:
            player.stop(0)
        self._unregister_hotkeys()
        self.presenter.release()             # a PowerPoint slide show closes with the app
        if self.presenter.deck is not None:
            self.presenter.deck.stop()
        self.remote.stop()
        self.show_store.save()
        if self.dj_panel:
            self.dj_panel.shutdown()
        if self.mini is not None:
            self.settings.setValue("window/mini_pos", self.mini.pos())
            self.mini.close()
        self._remember_library_places()
        self.settings.setValue("window/geometry2", self.saveGeometry())
        for window in live:
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
