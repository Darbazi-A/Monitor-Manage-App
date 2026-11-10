"""
The sound desk: eight cues, each its own player, and the pads that show them.

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
    QCursor,
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
        self.muted = False       # silenced for now, the level kept (not saved)
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
                tr('Not a sound file'),
                tr('{0} is {1}.').format(os.path.basename(path), 'an image' if kind == 'image' else 'a video'),
                tr('Sound cues take audio files - mp3, wav, m4a, flac and the like.'),
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
        if self.muted:
            return 0.0
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
        self._level_now()

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)
        self._level_now()
        self.changed.emit()

    def set_master(self, percent: int) -> None:
        self._master = max(0, min(100, percent))
        self._level_now()

    def _level_now(self) -> None:
        # A fade to a stop or a pause ends at silence and restores the level by itself;
        # the short fade in at the start gives way to a level changed by hand.
        if self._fade_mode:
            return
        self._fade.stop()
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
        self.card: Optional["CueCard"] = None      # the small player over the pad, shared by all eight
        self.cue: Optional[SoundCue] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 6, 9, 7)
        layout.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(3)
        self.key_label = QLabel("F" + str(index + 1))
        self.key_label.setObjectName("cueKey")
        top.addWidget(self.key_label)
        top.addStretch(1)

        self.loop_btn = icon_button("repeat", tr('Loop this cue'), CLR_MUTED, 13)
        self.loop_btn.setObjectName("ghost")
        self.loop_btn.setCheckable(True)
        self.loop_btn.setFixedSize(19, 19)
        self.loop_btn.toggled.connect(self.loopToggled.emit)
        top.addWidget(self.loop_btn)

        self.clear_btn = icon_button("close", tr('Empty this cue'), CLR_MUTED, 12)
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
        self.play_btn = icon_button("play", tr('Play / pause'), CLR_TEXT, 13)
        self.play_btn.setObjectName("ghost")
        self.play_btn.setFixedSize(21, 19)
        self.play_btn.clicked.connect(self.playPauseRequested.emit)
        transport.addWidget(self.play_btn)

        self.stop_btn = icon_button("stop", tr('Stop and rewind'), CLR_MUTED, 12)
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
        self.scrub.setToolTip(tr('Position - drag to move through the sound'))
        self.scrub.sliderPressed.connect(lambda: setattr(self, "_scrubbing", True))
        self.scrub.sliderReleased.connect(self._on_scrub_released)
        layout.addWidget(self.scrub)

        self.show_cue(None)

    # -- display ------------------------------------------------------------ #

    def _restyle(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)

    def show_cue(self, cue: Optional[SoundCue]) -> None:
        self.cue = cue
        filled = bool(cue and cue.path)
        playing = bool(cue and cue.is_playing())
        paused = bool(cue and cue.is_paused())

        # This runs four times a second for all eight pads. Re-polishing a
        # widget re-resolves the whole stylesheet, so the heavy part only runs
        # when something the pad shows has actually changed.
        key = (filled, playing, paused, cue.path if filled else "",
               bool(cue and cue.loop), self.width(),
               (cue.level, cue.muted) if filled else None)
        if key == getattr(self, "_shown_key", None):
            if filled:
                self._show_position(cue)
            return
        self._shown_key = key

        if filled:
            metrics = self.name_label.fontMetrics()
            self.name_label.setText(
                metrics.elidedText(cue.label(), Qt.ElideRight, max(70, self.width() - 24)))
            self.setToolTip("")              # the small player says it all
            self.key_label.setText(f"F{self.index + 1}  ·  " + (tr("muted") if cue.muted else f"{cue.level}%"))
        else:
            self.key_label.setText("F" + str(self.index + 1))
            self.name_label.setText(tr('drop a sound'))
            self.setToolTip(tr('Drop a sound file here, or click to choose one for F')
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

    def _has_sound(self) -> bool:
        return bool(self.card is not None and self.cue is not None and self.cue.path)

    def enterEvent(self, event) -> None:  # noqa: N802
        if self._has_sound():
            self.card.hover(self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self.card is not None:
            self.card.unhover(self)
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        # The wheel over a pad: this cue's level, five at a time.
        if self._has_sound():
            steps = event.angleDelta().y() // 120 or (1 if event.angleDelta().y() > 0 else -1)
            self.card.nudge(self, 5 * steps)
            event.accept()
        else:
            super().wheelEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        if self._has_sound():
            self.card.open_now(self)          # a right click (or a long press) opens it at once
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            if self.property("filled") == "true":
                self.playPauseRequested.emit()
            else:
                chooser = "Sound files (" + " ".join(
                    sorted("*" + e for e in AUDIO_EXTENSIONS)) + ");;All files (*.*)"
                path, _ = QFileDialog.getOpenFileName(
                    self, tr('Sound for F') + str(self.index + 1), "", chooser)
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


class PlayDisc(QPushButton):
    """The card's big round play / pause, drawn: the desk's button rules would square it."""

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#e2bd68" if self.underMouse() else CLR_ACCENT))
        painter.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        size = 20
        self.icon().paint(painter, QRect((self.width() - size) // 2, (self.height() - size) // 2, size, size))
        painter.end()


class CueCard(QWidget):
    """
    A small player over a sound pad while the mouse is on it: the whole name, play / pause,
    stop, ten seconds back or on, the position, this cue's own level and mute, a gentle
    fade, loop and another file. One card serves all eight pads; it never takes the
    keyboard, so F1-F8 and the clicker keep working with it open.
    """

    playPauseRequested = Signal(int)
    stopRequested = Signal(int)
    replaceRequested = Signal(int, str)
    edited = Signal(int)                 # the level or the loop changed: the preset has changed

    SHOW_MS = 280                        # the mouse rests on a pad this long before it opens
    MISSES = 3                           # checks (every 120 ms) with the mouse away before it closes

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.pad: Optional[CuePad] = None
        self._wanted: Optional[CuePad] = None
        self._misses = 0
        self._scrubbing = False
        self._duration = 0

        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(lambda: self._wanted is not None and self.open_now(self._wanted))
        self._watch = QTimer(self)
        self._watch.timeout.connect(self._tick)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setObjectName("cueCard")
        outer.addWidget(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 11, 14, 12)
        layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.key = QLabel()
        self.key.setObjectName("cueCardKey")
        head.addWidget(self.key)
        self.name = QLabel()
        self.name.setObjectName("cueCardName")
        head.addWidget(self.name, 1)
        self.loop_btn = self._button("repeat", tr('Loop this cue'), CLR_MUTED, 14)
        self.loop_btn.setCheckable(True)
        self.loop_btn.toggled.connect(self._on_loop)
        head.addWidget(self.loop_btn)
        self.file_btn = self._button("folder", tr('Another sound for this key…'), CLR_MUTED, 14)
        self.file_btn.clicked.connect(self._choose_file)
        head.addWidget(self.file_btn)
        layout.addLayout(head)

        self.scrub = QSlider(Qt.Horizontal)
        self.scrub.setObjectName("scrub")
        self.scrub.setFocusPolicy(Qt.NoFocus)
        self.scrub.setRange(0, 1)
        self.scrub.sliderPressed.connect(lambda: setattr(self, "_scrubbing", True))
        self.scrub.sliderReleased.connect(self._on_scrub_released)
        layout.addWidget(self.scrub)
        times = QHBoxLayout()
        self.elapsed = QLabel()
        self.elapsed.setObjectName("timecode")
        self.remaining = QLabel()
        self.remaining.setObjectName("timecode")
        times.addWidget(self.elapsed)
        times.addStretch(1)
        times.addWidget(self.remaining)
        layout.addLayout(times)

        transport = QHBoxLayout()
        transport.setSpacing(4)
        self.back_btn = self._button("rewind", tr('10 seconds back'), CLR_TEXT, 16)
        self.back_btn.clicked.connect(lambda: self._jump(-10000))
        transport.addWidget(self.back_btn)
        self.play_btn = PlayDisc()
        self.play_btn.setFocusPolicy(Qt.NoFocus)
        self.play_btn.setFixedSize(46, 46)
        self.play_btn.clicked.connect(lambda: self.pad and self.playPauseRequested.emit(self.pad.index))
        transport.addWidget(self.play_btn)
        self.fwd_btn = self._button("forward", tr('10 seconds on'), CLR_TEXT, 16)
        self.fwd_btn.clicked.connect(lambda: self._jump(10000))
        transport.addWidget(self.fwd_btn)
        self.stop_btn = self._button("stop", tr('Stop and rewind'), CLR_TEXT, 15)
        self.stop_btn.clicked.connect(lambda: self.pad and self.stopRequested.emit(self.pad.index))
        transport.addWidget(self.stop_btn)
        transport.addStretch(1)
        self.fade_btn = QPushButton(tr('Fade out'))
        self.fade_btn.setFocusPolicy(Qt.NoFocus)
        self.fade_btn.setToolTip(tr('Fade this sound out gently, over three seconds'))
        self.fade_btn.clicked.connect(self._fade_out)
        transport.addWidget(self.fade_btn)
        layout.addLayout(transport)

        level = QHBoxLayout()
        level.setSpacing(6)
        self.mute_btn = self._button("volume", tr('Mute this cue (it keeps playing)'), CLR_TEXT, 15)
        self.mute_btn.setCheckable(True)
        self.mute_btn.toggled.connect(self._on_mute)
        level.addWidget(self.mute_btn)
        self.level = QSlider(Qt.Horizontal)
        self.level.setObjectName("cueLevel")
        self.level.setFocusPolicy(Qt.NoFocus)
        self.level.setRange(0, 100)
        self.level.setPageStep(10)
        self.level.setToolTip(tr("This cue's own level - the master level is on top of it"))
        self.level.valueChanged.connect(self._on_level)
        level.addWidget(self.level, 1)
        self.level_text = QLabel()
        self.level_text.setObjectName("cueCardLevel")
        self.level_text.setMinimumWidth(40)
        self.level_text.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        level.addWidget(self.level_text)
        layout.addLayout(level)

        self.hint = QLabel()
        self.hint.setObjectName("keyHint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.setFixedWidth(330)

    @staticmethod
    def _button(icon: str, tip: str, colour: str, size: int) -> QPushButton:
        button = icon_button(icon, tip, colour, size)
        button.setObjectName("ghost")
        button.setFocusPolicy(Qt.NoFocus)
        button.setFixedSize(32, 32)
        return button

    # -- opening and closing -------------------------------------------------- #

    def hover(self, pad: CuePad) -> None:
        self._wanted = pad
        if self.isVisible():
            if pad is not self.pad:
                self.open_now(pad)          # moving along the pads: the card follows at once
            return
        self._show_timer.start(self.SHOW_MS)

    def unhover(self, pad: CuePad) -> None:
        if self._wanted is pad:
            self._wanted = None
        if not self.isVisible():
            self._show_timer.stop()

    def open_now(self, pad: CuePad) -> None:
        if pad.cue is None or not pad.cue.path or not pad.isVisible():
            return
        self.pad = pad
        self._misses = 0
        self._shown_key = None
        self.refresh()
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        self._watch.start(120)

    def close_card(self) -> None:
        self._watch.stop()
        self._show_timer.stop()
        self.hide()
        self.pad = None

    def _place(self) -> None:
        """Over the pad, centred on it, kept on its screen; under it if there is no room above."""
        pad = self.pad
        top_left = pad.mapToGlobal(QPoint(0, 0))
        screen = pad.screen().availableGeometry()
        x = top_left.x() + (pad.width() - self.width()) // 2
        x = max(screen.left() + 6, min(x, screen.right() - self.width() - 6))
        y = top_left.y() - self.height() - 6
        if y < screen.top() + 6:
            y = top_left.y() + pad.height() + 6
        self.move(x, y)

    def _near(self, widget: QWidget) -> bool:
        rect = QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size()).adjusted(-8, -8, 8, 8)
        return rect.contains(QCursor.pos())

    def _tick(self) -> None:
        pad = self.pad
        if pad is None or pad.cue is None or not pad.cue.path or not pad.window().isVisible() \
                or pad.window().isMinimized():
            self.close_card()
            return
        busy = self._scrubbing or self.level.isSliderDown()
        if busy or self._near(self) or self._near(pad):
            self._misses = 0
        else:
            self._misses += 1
            if self._misses >= self.MISSES:
                self.close_card()
                return
        self.refresh()

    # -- what it shows -------------------------------------------------------- #

    def refresh(self) -> None:
        pad = self.pad
        if pad is None or pad.cue is None:
            return
        cue = pad.cue
        playing, paused = cue.is_playing(), cue.is_paused()
        key = (cue.path, playing, paused, cue.loop, cue.muted, cue.level, cue._master)
        if key != getattr(self, "_shown_key", None):
            self._shown_key = key
            self.key.setText("F" + str(pad.index + 1))
            self.key.setProperty("state", "playing" if playing else "paused" if paused else "")
            self.key.style().unpolish(self.key)
            self.key.style().polish(self.key)
            self.name.setText(self.name.fontMetrics().elidedText(cue.label(), Qt.ElideMiddle, 200))
            self.name.setToolTip(cue.path)
            self.play_btn.setIcon(Icons.get("pause" if playing else "play", CLR_INK, 20))
            self.play_btn.setToolTip(tr('Pause') if playing else tr('Play'))
            for widget, on in ((self.loop_btn, cue.loop), (self.mute_btn, cue.muted)):
                widget.blockSignals(True)
                widget.setChecked(on)
                widget.blockSignals(False)
            self.loop_btn.setIcon(Icons.get("repeat", CLR_ACCENT if cue.loop else CLR_MUTED, 14))
            self.mute_btn.setIcon(Icons.get("mute" if cue.muted else "volume",
                                            CLR_DANGER if cue.muted else CLR_TEXT, 15))
            if not self.level.isSliderDown() and self.level.value() != cue.level:
                self.level.blockSignals(True)
                self.level.setValue(cue.level)
                self.level.blockSignals(False)
            self.level.setEnabled(not cue.muted)
            self.level_text.setText(tr("muted") if cue.muted else f"{cue.level}%")
            self.fade_btn.setEnabled(playing)
            self.hint.setText(tr('F{0} plays / pauses · Shift+F{0} stops · wheel on the pad: level · master {1}%')
                              .format(pad.index + 1, cue._master))
        self._show_position(cue)

    def _show_position(self, cue: SoundCue) -> None:
        duration = cue.duration()
        if duration != self._duration:
            self._duration = duration
            self.scrub.setRange(0, max(1, duration))
        for widget in (self.back_btn, self.fwd_btn, self.scrub):
            widget.setEnabled(duration > 0)
        if duration <= 0:
            self.elapsed.setText("")
            self.remaining.setText("")
            return
        position = cue.position()
        if not self._scrubbing and self.scrub.value() != position:
            self.scrub.setValue(position)
        shown = self.scrub.value() if self._scrubbing else position
        self.elapsed.setText(format_time(shown))
        self.remaining.setText(tr("looping") if cue.loop else "−" + format_time(max(0, duration - shown)))

    # -- what it does --------------------------------------------------------- #

    def _cue(self) -> Optional[SoundCue]:
        return self.pad.cue if self.pad is not None else None

    def _on_level(self, value: int) -> None:
        cue = self._cue()
        if cue is not None:
            cue.set_level(value)
            self.level_text.setText(f"{value}%")
            self.edited.emit(self.pad.index)

    def nudge(self, pad: CuePad, delta: int) -> None:
        """The mouse wheel over a pad."""
        if pad.cue is None or not pad.cue.path:
            return
        if pad.cue.muted:
            pad.cue.set_muted(False)
        if self.pad is not pad or not self.isVisible():
            self.open_now(pad)
        pad.cue.set_level(pad.cue.level + delta)
        self.edited.emit(pad.index)
        self.refresh()
        pad.show_cue(pad.cue)

    def _on_mute(self, on: bool) -> None:
        cue = self._cue()
        if cue is not None:
            cue.set_muted(on)
            self.refresh()

    def _on_loop(self, on: bool) -> None:
        cue = self._cue()
        if cue is not None:
            cue.set_loop(on)
            self.edited.emit(self.pad.index)
            self.refresh()

    def _jump(self, delta_ms: int) -> None:
        cue = self._cue()
        if cue is not None and cue.duration() > 0:
            cue.seek(max(0, min(cue.duration() - 250, cue.position() + delta_ms)))
            self.refresh()

    def _on_scrub_released(self) -> None:
        self._scrubbing = False
        cue = self._cue()
        if cue is not None and self._duration > 0:
            cue.seek(self.scrub.value())

    def _fade_out(self) -> None:
        cue = self._cue()
        if cue is not None:
            cue.stop(3000)

    def _choose_file(self) -> None:
        pad = self.pad
        if pad is None:
            return
        self.close_card()
        chooser = "Sound files (" + " ".join(sorted("*" + e for e in AUDIO_EXTENSIONS)) + ");;All files (*.*)"
        path, _ = QFileDialog.getOpenFileName(pad.window(), tr('Sound for F') + str(pad.index + 1), "", chooser)
        if path:
            self.replaceRequested.emit(pad.index, os.path.normpath(path))
