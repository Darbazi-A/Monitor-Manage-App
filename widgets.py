"""
Small widgets every part of the dashboard shares.

    ElidedLabel     one line of text - usually a file name - that never asks for
                    more width than it is given: too long, it ends in "…" (the
                    whole text on hover). A plain QLabel asks for its whole text,
                    so one long file name used to push a page past the window's
                    right edge.
    VideoTransport  pause / play, ten seconds back or on, and a bar to drag to
                    any point - for the video playing in the middle of a talk.
"""
from __future__ import annotations

from i18n import tr  # noqa: E402 - the interface's language

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider, QStyle,
                               QStyleOptionSlider, QVBoxLayout, QWidget)


class ElidedLabel(QLabel):
    MIN_WIDTH = 40

    def __init__(self, text: str = "", parent=None, mode: Qt.TextElideMode = Qt.ElideMiddle) -> None:
        super().__init__(parent)
        self._full = ""
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text or ""
        self._refit()

    def text(self) -> str:
        return self._full

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), self.MIN_WIDTH), hint.height())

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        return QSize(self.fontMetrics().horizontalAdvance(self._full) + 6, hint.height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refit()

    def _refit(self) -> None:
        shown = self.fontMetrics().elidedText(self._full, self._mode, max(0, self.width() - 2))
        if QLabel.text(self) != shown:
            QLabel.setText(self, shown)
        self.setToolTip(self._full if shown != self._full else "")


class _SeekBar(QSlider):
    """A press anywhere on the bar puts the handle there, already held: release to jump."""

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.maximum() > self.minimum():
            option = QStyleOptionSlider()
            self.initStyleOption(option)
            handle = self.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderHandle, self)
            if not handle.contains(event.position().toPoint()):
                groove = self.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderGroove, self)
                span = max(1, groove.width() - handle.width())
                x = int(event.position().x() - groove.x() - handle.width() / 2)
                self.setSliderPosition(QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
                                                                      max(0, min(x, span)), span))
        super().mousePressEvent(event)


def _clock(ms: int) -> str:
    seconds = max(0, int(ms) // 1000)
    hours, rest = divmod(seconds, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"


class VideoTransport(QWidget):
    """
    The controls of one QMediaPlayer: the bar (time, drag or click anywhere,
    length) above, and back 10 s, pause / play, on 10 s below. attach(player)
    follows a player, attach(None) lets go. Nothing here takes the keyboard
    focus, so the clicker's keys keep driving the talk.
    """

    STEP_MS = 10000

    def __init__(self, icons, theme: dict, height: int = 32) -> None:
        super().__init__()
        self.icons = icons
        self.theme = theme
        self._player = None
        self._dragging = False
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        line = QHBoxLayout()
        line.setSpacing(8)
        self.time = QLabel("0:00")
        self.time.setObjectName("timecode")
        self.time.setStyleSheet("font-size: 12px;")
        line.addWidget(self.time)
        self.bar = _SeekBar(Qt.Horizontal)
        self.bar.setRange(0, 0)
        self.bar.setFocusPolicy(Qt.NoFocus)
        self.bar.setToolTip(tr("Drag to any point of the video"))
        self.bar.sliderPressed.connect(lambda: setattr(self, "_dragging", True))
        self.bar.sliderMoved.connect(lambda ms: self.time.setText(_clock(ms)))
        self.bar.sliderReleased.connect(self._on_released)
        line.addWidget(self.bar, 1)
        self.length = QLabel("0:00")
        self.length.setObjectName("timecode")
        self.length.setStyleSheet("font-size: 12px;")
        line.addWidget(self.length)
        box.addLayout(line)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)

        def button(icon: str, text: str, tip: str, slot) -> QPushButton:
            made = QPushButton(text)
            made.setIcon(icons.get(icon, theme["text"], 15))
            made.setToolTip(tip)
            made.setFocusPolicy(Qt.NoFocus)
            made.setMinimumHeight(height)       # the theme's own minimum may be taller
            made.clicked.connect(slot)
            buttons.addWidget(made)
            return made

        self.back_btn = button("rewind", tr(" 10 s"), tr("10 seconds back"), lambda: self.skip(-self.STEP_MS))
        self.play_btn = button("pause", tr(" Pause"), tr("Pause the video - it waits on the screen"), self.toggle)
        self.play_btn.setMinimumWidth(96)
        self.forward_btn = button("forward", tr(" 10 s"), tr("10 seconds on"), lambda: self.skip(self.STEP_MS))
        buttons.addStretch(1)
        box.addLayout(buttons)
        self.attach(None)

    # -- the player ------------------------------------------------------------ #
    def attach(self, player) -> None:
        if player is not self._player:
            old, self._player = self._player, player
            if old is not None:
                for signal, slot in self._links(old):
                    try:
                        signal.disconnect(slot)
                    except (RuntimeError, TypeError):
                        pass                # gone with its window, or never connected
            if player is not None:
                for signal, slot in self._links(player):
                    signal.connect(slot)
        self._dragging = False
        self.setEnabled(player is not None)
        self._sync()

    def _links(self, player):
        return ((player.positionChanged, self._on_position), (player.durationChanged, self._on_duration),
                (player.playbackStateChanged, self._on_state))

    def player(self):
        return self._player

    def playing(self) -> bool:
        try:
            return self._player is not None and \
                self._player.playbackState() == self._player.PlaybackState.PlayingState
        except RuntimeError:
            return False

    def toggle(self) -> None:
        if self._player is None:
            return
        try:
            if self.playing():
                self._player.pause()
            else:
                self._player.play()
        except RuntimeError:
            self.attach(None)

    def skip(self, delta_ms: int) -> None:
        if self._player is not None:
            try:
                self.seek(self._player.position() + delta_ms)
            except RuntimeError:
                self.attach(None)

    def seek(self, ms: int) -> None:
        if self._player is None:
            return
        try:
            duration = self._player.duration()
            # never quite the end: that would count as the video finishing
            top = max(0, duration - 250) if duration > 0 else max(0, ms)
            self._player.setPosition(max(0, min(int(ms), top)))
        except RuntimeError:
            self.attach(None)

    # -- following it ---------------------------------------------------------- #
    def _sync(self) -> None:
        try:
            duration = self._player.duration() if self._player is not None else 0
            position = self._player.position() if self._player is not None else 0
        except RuntimeError:
            self._player, duration, position = None, 0, 0
        self._on_duration(duration)
        self._on_position(position)
        self._on_state()

    def _on_duration(self, ms: int) -> None:
        self.bar.setRange(0, max(0, int(ms)))
        self.length.setText(_clock(ms))

    def _on_position(self, ms: int) -> None:
        if self._dragging:
            return
        self.bar.blockSignals(True)
        self.bar.setValue(int(ms))
        self.bar.blockSignals(False)
        self.time.setText(_clock(ms))

    def _on_state(self, *_args) -> None:
        playing = self.playing()
        self.play_btn.setIcon(self.icons.get("pause" if playing else "play", self.theme["text"], 15))
        self.play_btn.setText(tr(" Pause") if playing else tr(" Play"))
        self.play_btn.setToolTip(tr("Pause the video - it waits on the screen") if playing
                                 else tr("Play the video on from here"))

    def _on_released(self) -> None:
        self._dragging = False
        self.seek(self.bar.value())
