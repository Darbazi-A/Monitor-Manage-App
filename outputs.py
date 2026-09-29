"""
The stage windows: the video engine, the scene every output is drawn through, transitions, and the rehearsal window.

Part of Stage Display Controller; main.py builds the dashboard from these.
"""

from __future__ import annotations

from i18n import caps, tr  # noqa: E402 - the interface's language

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
        # Goes up whenever the picture changes; a still screen is not redrawn
        # for the multiview until it does.
        self.picture_version = 0

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
                tr('That is a sound file'),
                tr('{0} is audio, and a screen cannot show it.').format(os.path.basename(path)),
                tr('Drop it on one of the sound cues at the bottom of the Live tab instead.'),
            )
        return ("video", path)

    def commit_media(self, payload) -> None:
        self.picture_version += 1
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
        self.picture_version += 1
        self._bg_color = color
        self._bg_item.setBrush(QBrush(color))
        self.engine.clear()
        self._pixmap_item.setVisible(False)
        self._pixmap_item.setPixmap(QPixmap())
        self._video_item.setVisible(False)

    def clear_output(self) -> None:
        self.picture_version += 1
        self.engine.clear()
        self._pixmap_item.setVisible(False)
        self._pixmap_item.setPixmap(QPixmap())
        self._video_item.setVisible(False)
        self.hide_slide(0)

    def set_scale_mode(self, mode: ScaleMode) -> None:
        self.picture_version += 1
        self._scale_mode = mode
        self._layout_pixmap()
        self._layout_video()

    # -- marquee ------------------------------------------------------------ #

    def set_marquee_text(self, text: str) -> None:
        self.picture_version += 1
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
        self.picture_version += 1
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
        self.picture_version += 1
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
        """
        Crossfades happen inside the scene; dips still use the black overlay window.

        A new video takes a moment to show its first frame. Both a dissolve and a
        plain cut hold the old picture until that frame has actually arrived -
        not for a fixed guess - so the audience never sees black in between.
        """
        crossfade = fade_ms > 0 and style == TRANSITION_CROSSFADE
        if crossfade or (fade_ms <= 0 and self.has_picture()):
            still = self.snapshot()       # includes a dissolve already in progress
            if not still.isNull():
                self._still_anim.stop()
                self._still_item.setPixmap(still)
                self._still_item.setPos(0, 0)
                self._still_item.setOpacity(1.0)
                self._still_item.setVisible(True)
                action()                  # the new picture is built underneath, unseen
                if crossfade:
                    def dissolve() -> None:
                        self._still_anim.setDuration(max(60, fade_ms))
                        self._still_anim.setStartValue(1.0)
                        self._still_anim.setEndValue(0.0)
                        self._still_anim.start()
                    self._when_picture_ready(dissolve)
                else:
                    self._when_picture_ready(self._after_dissolve)   # a cut: gone the moment it is there
                return
        if fade_ms <= 0:
            action()
            return
        super().transition(action, fade_ms, style)

    def _when_picture_ready(self, then: Callable[[], None], longest_ms: int = 600) -> None:
        """Run `then` once the new video's first frame is on screen (at once for a picture)."""
        if not self._video_item.isVisible():
            then()
            return
        sink = self._video_item.videoSink()
        state = {"done": False}

        def fire() -> None:
            if state["done"]:
                return
            state["done"] = True
            try:
                sink.videoFrameChanged.disconnect(on_frame)
            except (RuntimeError, TypeError):
                pass
            then()

        def on_frame(frame) -> None:
            if frame.isValid():
                QTimer.singleShot(0, fire)    # after it has been painted

        sink.videoFrameChanged.connect(on_frame)
        QTimer.singleShot(longest_ms, fire)

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
        self.picture_version += 1
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

    def is_moving(self) -> bool:
        """Whether the picture changes by itself: video, a scrolling marquee, a fade under way."""
        return (self._video_item.isVisible() or self.is_marquee_running()
                or self._still_anim.state() == QVariantAnimation.Running
                or self._slide_anim.state() == QVariantAnimation.Running)

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
        self.setWindowTitle(tr('Rehearsal - nothing reaches the stage'))
        if os.path.exists(ICON_FILE):
            self.setWindowIcon(QIcon(ICON_FILE))
        self.resize(1200, 760)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        tag = QLabel(tr('REHEARSAL'))
        tag.setStyleSheet(f"color: {THEME['rehearse']}; font-weight: 800; letter-spacing: 1px;"
                          f"border: 1px solid {THEME['rehearse']}; border-radius: 9px; padding: 3px 10px;")
        head.addWidget(tag)
        note = QLabel(tr('The dashboard drives these screens now; the hall keeps what it had. Slides show as pictures here.'))
        note.setObjectName("cardHint")
        head.addWidget(note, 1)
        head.addWidget(QLabel(tr('Sound')))
        self.sound_combo = QComboBox()
        self.sound_combo.addItem(tr('Silent'), "")
        from PySide6.QtMultimedia import QMediaDevices
        for device in QMediaDevices.audioOutputs():
            self.sound_combo.addItem(device.description(), device.description())
        self.sound_combo.setToolTip(tr('New sounds started while rehearsing: silent, or on a device of your choice\n(headphones) - never the hall unless you pick it.'))
        self.sound_combo.currentIndexChanged.connect(
            lambda _i: self.soundChosen.emit(self.sound_combo.currentData() or ""))
        head.addWidget(self.sound_combo)
        end = QPushButton(tr('  End rehearsal'))
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
            window = cls(tr("{0} (rehearsal)").format(ROLE_LABELS[role]))
            window.setWindowFlags(Qt.Widget)
            window.setCursor(Qt.ArrowCursor)
            window.setFocusPolicy(Qt.NoFocus)
            window._view.setFocusPolicy(Qt.NoFocus)
            size = sizes[role]
            window.set_virtual_size(size)
            self.outputs[role] = window
            box = QVBoxLayout()
            box.setSpacing(4)
            caption = QLabel(f"{caps(ROLE_LABELS[role])}   {size.width()}×{size.height()}")
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
