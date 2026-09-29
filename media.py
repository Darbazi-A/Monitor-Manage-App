"""
Media files: what they are, whether they will play, thumbnails, reading ahead.

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


_WARMED: List[str] = []


def warm_file(path: str, limit: int = 64 * 1024 * 1024) -> None:
    """
    Read a file once, in the background, so it is already in memory when it is
    wanted - the next item of a playlist, the next step's clips. From a slow
    disk or a USB stick the first frames then arrive at once.
    """
    if not path or path in _WARMED or not os.path.isfile(path):
        return
    _WARMED.append(path)
    del _WARMED[:-24]

    def read() -> None:
        try:
            with open(path, "rb") as handle:
                left = limit
                while left > 0 and handle.read(min(1 << 20, left)):
                    left -= 1 << 20
        except OSError:
            pass

    threading.Thread(target=read, name="warm", daemon=True).start()


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
