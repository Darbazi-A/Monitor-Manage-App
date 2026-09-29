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
                            + " plays and pauses, Shift+F" + str(self.index + 1) + tr(' stops'))
        else:
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
