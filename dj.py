"""
The DJ desk: two turntables, a three-channel mixer, a techno machine and a crate.

Everything is drawn with QPainter in the dashboard's navy and gold. The sound
runs on dj_engine's own thread and tracks are decoded in a separate process,
so the panel only reads state and writes knob values. It repaints a control
only when what it shows has changed, and slows its refresh right down when
nothing is moving.

Every control takes touch as well as the mouse, each finger on its own
control, so a scratch and a fader move can happen at once. What the mouse does
with a right-click, a finger does with a long press; double-tap resets a knob.
"""
from __future__ import annotations

import json
import math
import os
import time
from typing import Dict, List, Optional

# numpy's BLAS reserves memory per CPU core on import (about 180 MB here). The
# desk only uses FFTs and array arithmetic, so one thread is all it needs.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
from PySide6.QtCore import QEvent, QMimeData, QPointF, QRectF, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import (QColor, QConicalGradient, QDesktopServices, QFont, QImage,
                           QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMenu, QPushButton, QScrollArea, QScroller,
                               QSizePolicy, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import dj_engine as de

# The dashboard's palette, repeated here so this module stands on its own.
BG = "#0c1018"
CARD = "#141a26"
RAISED = "#1a2130"
WELL = "#0f141e"
EDGE = "#222b3c"
EDGE_HI = "#2c3750"
TEXT = "#e9edf5"
DIM = "#9aa6bb"
MUTED = "#6c7891"
GOLD = "#e3b23c"
OK = "#57c98a"
WARN = "#d9853f"
DANGER = "#e0605c"

DECK_COLOURS = ("#5aa9ff", GOLD)
MACHINE_COLOUR = "#b58cff"
HOT_COLOURS = ("#e0605c", "#57c98a", "#5aa9ff", "#e3b23c")
ROW_COLOURS = {"kick": GOLD, "clap": "#ff8a5c", "hat": "#5aa9ff", "open": "#4fd1c5",
               "rim": "#b58cff", "stab": "#ff6fae", "acid": "#57c98a"}
REVOLUTION_DEG_PER_SEC = 200.0          # 33 1/3 rpm


class Sizes:
    """Control sizes; touch mode makes everything a finger can hit comfortably."""

    def __init__(self, touch: bool) -> None:
        self.touch = touch
        self.button = 36 if touch else 32
        self.transport = 42 if touch else 38
        self.knob = 32 if touch else 30
        self.machine_knob = 32 if touch else 32
        self.grid_row = 25 if touch else 22
        self.crate_pad = 8 if touch else 5


SIZE = Sizes(False)


def _style() -> str:
    pad = "8px 10px" if SIZE.touch else "6px 9px"
    return f"""
QWidget#djRoot {{ background: {BG}; }}
QLabel {{ color: {TEXT}; }}
QLabel#djTitle {{ font-size: 13px; font-weight: 700; letter-spacing: 1.2px; color: {DIM}; }}
QLabel#djHint {{ color: {MUTED}; font-size: 11px; }}
QLabel#djTrack {{ font-size: 15px; font-weight: 600; }}
QLabel#djSub {{ color: {MUTED}; font-size: 11px; }}
QLabel#djSmall {{ color: {DIM}; font-family: "Consolas", monospace; font-size: 11px; }}
QLabel#djTime {{ font-family: "Consolas", monospace; font-size: 15px; color: {TEXT}; }}
QPushButton#dj {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1f2737, stop:1 #171d29);
    border: 1px solid {EDGE_HI}; border-radius: 8px; color: {TEXT};
    font-size: 11px; font-weight: 700; letter-spacing: 0.8px; padding: {pad};
    min-height: {SIZE.button - 14}px;
}}
QPushButton#dj:hover {{ border-color: #3d4a63; }}
QPushButton#dj:pressed {{ background: #151b26; }}
QPushButton#dj:checked {{ background: rgba(227, 178, 60, 0.15); border-color: {GOLD}; color: {GOLD}; }}
QPushButton#dj:disabled {{ color: #4a5468; border-color: {EDGE}; }}
QPushButton#djBpm {{
    background: transparent; border: 1px solid transparent; border-radius: 8px;
    font-family: "Consolas", monospace; font-size: 24px; font-weight: 700; padding: 0px 6px;
}}
QPushButton#djBpm:hover {{ border-color: {EDGE_HI}; }}
QPushButton#djBpm:pressed {{ background: #151b26; }}
QComboBox#dj, QDoubleSpinBox#dj, QLineEdit#dj {{
    background: {WELL}; border: 1px solid {EDGE_HI}; border-radius: 7px; padding: 4px 8px;
    color: {TEXT}; font-size: 12px; min-height: {SIZE.button - 12}px;
}}
QTreeWidget#djCrate {{
    background: {WELL}; border: 1px solid {EDGE}; border-radius: 8px; color: {TEXT};
    font-size: 12px; outline: none;
}}
QTreeWidget#djCrate::item {{ padding: {SIZE.crate_pad}px 4px; }}
QTreeWidget#djCrate::item:selected {{ background: rgba(227, 178, 60, 0.16); color: {TEXT}; }}
QTreeWidget#djCrate::item:hover {{ background: #1a2130; }}
QHeaderView::section {{
    background: {CARD}; color: {MUTED}; border: none; border-bottom: 1px solid {EDGE};
    padding: 5px 6px; font-size: 10px; font-weight: 700; letter-spacing: 0.8px;
}}
QMenu {{ background: {RAISED}; border: 1px solid {EDGE_HI}; border-radius: 8px; padding: 5px; color: {TEXT}; }}
QMenu::item {{ padding: {"11px 26px" if SIZE.touch else "7px 20px"}; border-radius: 6px; font-size: 12px; }}
QMenu::item:selected {{ background: rgba(227, 178, 60, 0.16); }}
QMenu::separator {{ height: 1px; background: {EDGE}; margin: 4px 8px; }}
QFrame#djCard {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #161c29, stop:1 #121722);
    border: 1px solid {EDGE}; border-radius: 12px;
}}
QLabel#djPill {{ border-radius: 9px; padding: 2px 10px; font-size: 11px; font-weight: 600; }}
"""


def _font(size: float, weight: int = QFont.Normal, family: str = "Segoe UI") -> QFont:
    font = QFont(family)
    font.setPointSizeF(size)
    font.setWeight(QFont.Weight(weight))
    return font


def _alpha(colour: str, alpha: int) -> QColor:
    c = QColor(colour)
    c.setAlpha(alpha)
    return c


def _clock(seconds: float) -> str:
    seconds = max(0.0, seconds)
    return f"{int(seconds // 60):d}:{int(seconds % 60):02d}.{int(seconds * 10 % 10):d}"


def _button(text: str, tip: str = "", checkable: bool = False, name: str = "dj") -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(name)
    button.setCheckable(checkable)
    button.setToolTip(tip)
    button.setCursor(Qt.PointingHandCursor)
    button.setFocusPolicy(Qt.NoFocus)
    return button


def _set_text(label, text: str) -> None:
    """setText only when it changes: every call relays out and repaints."""
    if label.text() != text:
        label.setText(text)


# --------------------------------------------------------------------------- #
# Touch and mouse through one path
# --------------------------------------------------------------------------- #

class TouchInput:
    """
    Mixin: routes mouse and touch into on_press / on_move / on_release, and
    adds long-press (the finger's right-click) and double-tap. Accepting touch
    per widget is what lets two fingers work two controls at the same time.
    """

    LONG_MS = 550

    def _init_touch(self) -> None:
        self.setAttribute(Qt.WA_AcceptTouchEvents, True)
        self._t_start: Optional[QPointF] = None
        self._t_moved = False
        self._t_last = (0.0, QPointF(-99, -99))
        self._t_timer = QTimer(self)
        self._t_timer.setSingleShot(True)
        self._t_timer.timeout.connect(self._t_fire_long)

    # overridable
    def on_press(self, pos: QPointF, button: str) -> None: ...
    def on_move(self, pos: QPointF) -> None: ...
    def on_release(self, pos: QPointF) -> None: ...
    def on_long_press(self, pos: QPointF) -> None: ...
    def on_double(self, pos: QPointF) -> None: ...

    def _t_begin(self, pos: QPointF, button: str) -> None:
        now = time.monotonic()
        last_time, last_pos = self._t_last
        if button == "left" and now - last_time < 0.33 and \
                abs(pos.x() - last_pos.x()) + abs(pos.y() - last_pos.y()) < 30:
            self._t_last = (0.0, QPointF(-99, -99))
            self._t_start = None
            self.on_double(pos)
            return
        self._t_last = (now, pos)
        self._t_start = pos
        self._t_moved = False
        if button == "left":
            self._t_timer.start(self.LONG_MS)
        self.on_press(pos, button)

    def _t_update(self, pos: QPointF) -> None:
        if self._t_start is None:
            return
        if not self._t_moved and abs(pos.x() - self._t_start.x()) + abs(pos.y() - self._t_start.y()) > 12:
            self._t_moved = True
            self._t_timer.stop()
        self.on_move(pos)

    def _t_end(self, pos: QPointF) -> None:
        self._t_timer.stop()
        if self._t_start is None:
            return
        self._t_start = None
        self.on_release(pos)

    def _t_fire_long(self) -> None:
        if self._t_start is not None and not self._t_moved:
            self.on_long_press(self._t_start)

    def event(self, event) -> bool:  # noqa: D401
        kind = event.type()
        if kind in (QEvent.TouchBegin, QEvent.TouchUpdate, QEvent.TouchEnd, QEvent.TouchCancel):
            points = event.points()
            pos = points[0].position() if points else QPointF()
            if kind == QEvent.TouchBegin:
                self._t_begin(pos, "left")
            elif kind == QEvent.TouchUpdate:
                self._t_update(pos)
            else:
                self._t_end(pos)
            event.accept()
            return True
        return super().event(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._t_begin(event.position(), "right" if event.button() == Qt.RightButton else "left")

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._t_begin(event.position(), "right" if event.button() == Qt.RightButton else "left")

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons():
            self._t_update(event.position())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._t_end(event.position())


class HoldButton(QPushButton):
    """A button with a long-press (or right-click) action as well as a click."""

    held = Signal()

    def __init__(self, text: str, tip: str = "") -> None:
        super().__init__(text)
        self.setObjectName("dj")
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self._fired = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)
        self.pressed.connect(self._start)
        self.released.connect(self._timer.stop)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda _p: self.held.emit())

    def _start(self) -> None:
        self._fired = False
        self._timer.start(600)

    def _fire(self) -> None:
        if self.isDown():
            self._fired = True
            self.held.emit()

    def nextCheckState(self) -> None:  # noqa: N802
        if not self._fired:
            super().nextCheckState()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._fired:
            self._fired = False
            self.setDown(False)
            self._timer.stop()
            return                        # a hold is not also a click
        super().mouseReleaseEvent(event)


# --------------------------------------------------------------------------- #
# Controls
# --------------------------------------------------------------------------- #

class Knob(TouchInput, QWidget):
    """Rotary knob: drag up/down, wheel, double-tap to reset. Shift = fine."""

    valueChanged = Signal(float)

    def __init__(self, label: str, minimum: float = -1.0, maximum: float = 1.0,
                 default: float = 0.0, colour: str = GOLD, dial: Optional[int] = None,
                 formatter=None, tip: str = "") -> None:
        super().__init__()
        self._init_touch()
        self.label, self.minimum, self.maximum = label, minimum, maximum
        self.default, self.colour = default, colour
        self.dial = dial or SIZE.knob
        self.formatter = formatter
        self.bipolar = minimum < 0 < maximum
        self._value = default
        self._drag_y: Optional[float] = None
        self._hover = False
        self.setFixedSize(max(self.dial + 16, 52), self.dial + 20)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip(tip or f"{label} - drag up/down · double-tap resets")

    def value(self) -> float:
        return self._value

    def setValue(self, value: float, emit: bool = True) -> None:
        value = max(self.minimum, min(self.maximum, value))
        if abs(value - self._value) < 1e-9:
            return
        self._value = value
        self.update()
        if emit:
            self.valueChanged.emit(value)

    def _fraction(self) -> float:
        return (self._value - self.minimum) / (self.maximum - self.minimum)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        d = self.dial
        cx = self.width() / 2
        rect = QRectF(cx - d / 2 + 3, 3, d - 6, d - 6)
        p.setPen(QPen(QColor(EDGE_HI), 3, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, 225 * 16, -270 * 16)
        f = self._fraction()
        start = 0.5 if self.bipolar else 0.0
        if abs(f - start) > 0.004:
            p.setPen(QPen(QColor(self.colour), 3, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect, int((225 - 270 * start) * 16), int(-270 * (f - start) * 16))
        cap = rect.adjusted(5, 5, -5, -5)
        grad = QRadialGradient(cap.center() - QPointF(0, cap.height() * 0.3), cap.width() * 0.8)
        grad.setColorAt(0.0, QColor("#343e52"))
        grad.setColorAt(1.0, QColor("#161c27"))
        p.setPen(QPen(QColor("#0a0d13"), 1))
        p.setBrush(grad)
        p.drawEllipse(cap)
        angle = math.radians(225 - 270 * f)
        r = cap.width() / 2
        c = cap.center()
        at_default = abs(self._value - self.default) < 1e-6
        p.setPen(QPen(QColor(TEXT if at_default else self.colour), 2.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(c.x() + math.cos(angle) * r * 0.25, c.y() - math.sin(angle) * r * 0.25),
                   QPointF(c.x() + math.cos(angle) * r * 0.8, c.y() - math.sin(angle) * r * 0.8))
        showing_value = self._hover or self._drag_y is not None
        text = self.formatter(self._value) if (showing_value and self.formatter) else self.label
        p.setPen(QColor(TEXT if showing_value else DIM))
        p.setFont(_font(7.2, QFont.DemiBold))
        p.drawText(QRectF(0, d - 1, self.width(), 16), Qt.AlignHCenter | Qt.AlignTop, text)

    def on_press(self, pos: QPointF, button: str) -> None:
        self._drag_y = pos.y()
        self.update()

    def on_move(self, pos: QPointF) -> None:
        if self._drag_y is None:
            return
        from PySide6.QtWidgets import QApplication
        fine = QApplication.keyboardModifiers() & Qt.ShiftModifier
        span = 600.0 if fine else 140.0
        self.setValue(self._value + (self._drag_y - pos.y()) / span * (self.maximum - self.minimum))
        self._drag_y = pos.y()

    def on_release(self, pos: QPointF) -> None:
        self._drag_y = None
        self.update()

    def on_double(self, pos: QPointF) -> None:
        self.setValue(self.default)

    def wheelEvent(self, event) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120.0
        fine = 200.0 if event.modifiers() & Qt.ShiftModifier else 40.0
        self.setValue(self._value + steps * (self.maximum - self.minimum) / fine)

    def enterEvent(self, _event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._hover = False
        self.update()


class Fader(TouchInput, QWidget):
    """Channel fader, pitch fader or crossfader. Double-tap resets."""

    valueChanged = Signal(float)

    def __init__(self, vertical: bool = True, minimum: float = 0.0, maximum: float = 1.0,
                 default: float = 0.0, colour: str = GOLD, length: int = 150,
                 tip: str = "") -> None:
        super().__init__()
        self._init_touch()
        self.vertical, self.minimum, self.maximum = vertical, minimum, maximum
        self.default, self.colour = default, colour
        self.bipolar = minimum < 0 < maximum
        self._value = default
        self._grab = 0.0                    # where on the cap the finger took hold
        thickness = 48 if SIZE.touch else 40
        if vertical:
            self.setFixedWidth(thickness)
            self.setMinimumHeight(length)
        else:
            self.setFixedHeight(thickness)
            self.setMinimumWidth(length)
        self.setCursor(Qt.SizeVerCursor if vertical else Qt.SizeHorCursor)
        self.setToolTip(tip)

    def value(self) -> float:
        return self._value

    def setValue(self, value: float, emit: bool = True) -> None:
        value = max(self.minimum, min(self.maximum, value))
        if abs(value - self._value) < 1e-9:
            return
        self._value = value
        self.update()
        if emit:
            self.valueChanged.emit(value)

    def _track(self) -> QRectF:
        cap = 11
        if self.vertical:
            return QRectF(self.width() / 2 - 2, cap + 2, 4, self.height() - 2 * cap - 4)
        return QRectF(cap + 12, self.height() / 2 - 2, self.width() - 2 * cap - 24, 4)

    def _fraction(self) -> float:
        return (self._value - self.minimum) / (self.maximum - self.minimum)

    def _cap_centre(self) -> QPointF:
        track = self._track()
        f = self._fraction()
        if self.vertical:
            return QPointF(track.center().x(), track.bottom() - f * track.height())
        return QPointF(track.left() + f * track.width(), track.center().y())

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track = self._track()
        p.setPen(QPen(QColor(MUTED), 1))
        for i in range(11):
            t = i / 10
            size = 6 if i in (0, 5, 10) else 3
            if self.vertical:
                y = track.bottom() - t * track.height()
                p.drawLine(QPointF(track.left() - 8 - size, y), QPointF(track.left() - 8, y))
                p.drawLine(QPointF(track.right() + 8, y), QPointF(track.right() + 8 + size, y))
            else:
                x = track.left() + t * track.width()
                p.drawLine(QPointF(x, track.top() - 8 - size), QPointF(x, track.top() - 8))
        p.setPen(QPen(QColor("#05070b"), 1))
        p.setBrush(QColor(WELL))
        p.drawRoundedRect(track.adjusted(-1, -1, 1, 1), 2, 2)
        f = self._fraction()
        start = 0.5 if self.bipolar else 0.0
        lo, hi = min(start, f), max(start, f)
        p.setPen(Qt.NoPen)
        p.setBrush(_alpha(self.colour, 170))
        centre = self._cap_centre()
        big = SIZE.touch
        if self.vertical:
            p.drawRect(QRectF(track.left(), track.bottom() - hi * track.height(),
                              track.width(), (hi - lo) * track.height()))
            w, h = (36, 20) if big else (30, 18)
        else:
            p.drawRect(QRectF(track.left() + lo * track.width(), track.top(),
                              (hi - lo) * track.width(), track.height()))
            w, h = (22, 38) if big else (20, 32)
        cap = QRectF(centre.x() - w / 2, centre.y() - h / 2, w, h)
        grad = QLinearGradient(cap.topLeft(), cap.bottomLeft() if self.vertical else cap.topRight())
        grad.setColorAt(0.0, QColor("#475168"))
        grad.setColorAt(0.5, QColor("#2a3244"))
        grad.setColorAt(1.0, QColor("#1b212d"))
        p.setPen(QPen(QColor("#07090d"), 1))
        p.setBrush(grad)
        p.drawRoundedRect(cap, 3, 3)
        p.setPen(QPen(QColor(self.colour), 2))
        if self.vertical:
            p.drawLine(QPointF(cap.left() + 4, centre.y()), QPointF(cap.right() - 4, centre.y()))
        else:
            p.drawLine(QPointF(centre.x(), cap.top() + 4), QPointF(centre.x(), cap.bottom() - 4))

    def _value_at(self, pos: QPointF) -> float:
        track = self._track()
        if self.vertical:
            f = (track.bottom() - (pos.y() - self._grab)) / track.height()
        else:
            f = ((pos.x() - self._grab) - track.left()) / track.width()
        value = self.minimum + max(0.0, min(1.0, f)) * (self.maximum - self.minimum)
        if self.bipolar and abs(value) < (self.maximum - self.minimum) * 0.012:
            value = 0.0          # a gentle detent at the centre
        return value

    def on_press(self, pos: QPointF, button: str) -> None:
        centre = self._cap_centre()
        offset = (pos.y() - centre.y()) if self.vertical else (pos.x() - centre.x())
        # Grabbing the cap moves it relative to the finger; touching the slot jumps.
        self._grab = offset if abs(offset) < 16 else 0.0
        self.setValue(self._value_at(pos))

    def on_move(self, pos: QPointF) -> None:
        self.setValue(self._value_at(pos))

    def on_double(self, pos: QPointF) -> None:
        self.setValue(self.default)

    def wheelEvent(self, event) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120.0
        fine = 400.0 if event.modifiers() & Qt.ShiftModifier else 60.0
        self.setValue(self._value + steps * (self.maximum - self.minimum) / fine)


class Meter(QWidget):
    """Segmented LED level meter with peak hold. Repaints only when a segment changes."""

    SEGMENTS = 18

    def __init__(self, channels: int = 1, height: int = 150) -> None:
        super().__init__()
        self.channels = channels
        self.levels = [0.0] * channels
        self.holds = [0.0] * channels
        self.hold_time = [0.0] * channels
        self._shown = None
        self.setFixedWidth(8 * channels + 4 * (channels - 1) + 2)
        self.setMinimumHeight(height)

    def push(self, peaks: List[float]) -> None:
        now = time.monotonic()
        for i, peak in enumerate(peaks[: self.channels]):
            db = 20 * math.log10(peak) if peak > 1e-5 else -60.0
            level = max(0.0, min(1.0, (db + 42.0) / 42.0))
            self.levels[i] = level if level > self.levels[i] else self.levels[i] * 0.86
            if level >= self.holds[i] or now - self.hold_time[i] > 1.2:
                self.holds[i] = level
                self.hold_time[i] = now
        n = self.SEGMENTS
        shown = tuple((int(round(l * n)), int(round(h * n))) for l, h in zip(self.levels, self.holds))
        if shown != self._shown:
            self._shown = shown
            self.update()

    def active(self) -> bool:
        return any(l > 0.01 for l in self.levels) or any(h > 0.01 for h in self.holds)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        n = self.SEGMENTS
        gap = 2
        seg_h = (self.height() - gap * (n - 1)) / n
        for c in range(self.channels):
            x = 1 + c * 12
            lit = int(round(self.levels[c] * n))
            hold = int(round(self.holds[c] * n)) - 1
            for i in range(n):
                y = self.height() - (i + 1) * seg_h - i * gap
                colour = DANGER if i >= n - 2 else WARN if i >= n - 5 else OK
                on = i < lit or i == hold
                p.fillRect(QRectF(x, y, 8, seg_h), QColor(colour) if on else QColor("#18202c"))


class Platter(TouchInput, QWidget):
    """
    An animated turntable. The record turns with the audio the room hears, so it
    stops, reverses and speeds up exactly as the sound does. Hold the record to
    scratch; drag the outer ring to nudge the tempo.
    """

    def __init__(self, colour: str, letter: str) -> None:
        super().__init__()
        self._init_touch()
        self.colour, self.letter = colour, letter
        self.angle = 0.0
        self.progress = 0.0
        self.loaded = False
        self.playing = False
        self.wheel_nudge = 0.0
        self._cache: Dict[str, QPixmap] = {}
        self._cache_key = None
        self._painted = None
        self.mode: Optional[str] = None        # "scratch" or "bend" while held
        self._last_angle = 0.0
        self._motion = 0.0
        self.setMinimumSize(190, 190)
        self.setMaximumHeight(330)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Hold the record to scratch · drag the outer ring to nudge")

    def take_motion(self) -> float:
        motion, self._motion = self._motion, 0.0
        return motion

    def show_state(self, angle: float, progress: float, loaded: bool, playing: bool) -> None:
        """Repaint only if something visible moved (a tenth of a degree, or a state change)."""
        key = (round(angle * 5) / 5.0, round(progress, 3), loaded, playing)
        self.angle, self.progress, self.loaded, self.playing = angle, progress, loaded, playing
        if key != self._painted:
            self._painted = key
            self.update()

    def _geometry(self):
        side = min(self.width(), self.height()) - 6
        radius = side / 2
        centre = QPointF(self.width() / 2 - radius * 0.06, self.height() / 2)
        return centre, radius * 0.9

    def _angle_at(self, pos: QPointF) -> float:
        centre, _ = self._geometry()
        return math.degrees(math.atan2(pos.y() - centre.y(), pos.x() - centre.x()))

    def _layers(self, radius: float) -> None:
        side = int(radius * 2) + 2
        key = (side, self.width(), self.height())
        if key == self._cache_key:
            return
        self._cache_key = key
        self._cache = {}
        size = side
        c = QPointF(size / 2, size / 2)

        plate = QPixmap(size + 20, size + 20)
        plate.fill(Qt.transparent)
        p = QPainter(plate)
        p.setRenderHint(QPainter.Antialiasing)
        pc = QPointF((size + 20) / 2, (size + 20) / 2)
        grad = QRadialGradient(pc, radius * 1.05)
        grad.setColorAt(0.85, QColor("#1b2130"))
        grad.setColorAt(0.97, QColor("#2f384b"))
        grad.setColorAt(1.0, QColor("#12161f"))
        p.setPen(QPen(QColor("#07090d"), 1.2))
        p.setBrush(grad)
        p.drawEllipse(pc, radius * 1.04, radius * 1.04)
        p.end()
        self._cache["plate"] = plate

        record = QPixmap(size, size)
        record.fill(Qt.transparent)
        p = QPainter(record)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#08090c"))
        p.drawEllipse(c, radius * 0.9, radius * 0.9)
        for i in range(46):
            r = radius * (0.36 + 0.53 * i / 45)
            shade = 22 + (i * 7) % 11
            p.setPen(QPen(QColor(shade, shade, shade + 4), 0.8))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, r, r)
        for r0 in (0.52, 0.7):
            p.setPen(QPen(QColor("#050608"), 2.2))
            p.drawEllipse(c, radius * r0, radius * r0)
        # the fixed sheen of the room's light on the vinyl
        cone = QConicalGradient(c, 45)
        for stop, alpha in ((0.0, 34), (0.08, 0), (0.42, 0), (0.5, 26), (0.58, 0), (0.92, 0), (1.0, 34)):
            cone.setColorAt(stop, QColor(255, 255, 255, alpha))
        p.setPen(Qt.NoPen)
        p.setBrush(cone)
        path = QPainterPath()
        path.addEllipse(c, radius * 0.9, radius * 0.9)
        inner = QPainterPath()
        inner.addEllipse(c, radius * 0.35, radius * 0.35)
        p.drawPath(path.subtracted(inner))
        p.end()
        self._cache["record"] = record

        # dots and label turn together, so they share one layer
        spin = QPixmap(size, size)
        spin.fill(Qt.transparent)
        p = QPainter(spin)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        for i in range(90):
            a = math.radians(i * 4)
            r = radius * 0.955
            p.setBrush(QColor("#c8ccd6") if i % 2 == 0 else QColor("#3b4252"))
            p.drawEllipse(QPointF(c.x() + math.cos(a) * r, c.y() + math.sin(a) * r), 1.6, 1.6)
        self._cache["dots"] = spin.copy()
        lr = radius * 0.33
        grad = QRadialGradient(c - QPointF(lr * 0.3, lr * 0.4), lr * 1.3)
        grad.setColorAt(0.0, QColor(self.colour).lighter(125))
        grad.setColorAt(1.0, QColor(self.colour).darker(210))
        p.setPen(QPen(QColor(0, 0, 0, 120), 1))
        p.setBrush(grad)
        p.drawEllipse(c, lr, lr)
        p.setPen(QPen(QColor(255, 255, 255, 60), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, lr * 0.78, lr * 0.78)
        p.setPen(QColor("#0b0e14"))
        p.setFont(_font(max(9.0, lr * 0.42), QFont.Black))
        p.drawText(QRectF(c.x() - lr, c.y() - lr * 0.85, lr * 2, lr * 0.9), Qt.AlignCenter, self.letter)
        p.setPen(QPen(QColor(255, 255, 255, 235), max(2.0, lr * 0.06), Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(c.x(), c.y() + lr * 0.35), QPointF(c.x(), c.y() + lr * 0.95))
        spindle = QRadialGradient(c - QPointF(2, 2), 7)
        spindle.setColorAt(0, QColor("#f2f4f8"))
        spindle.setColorAt(1, QColor("#6d7486"))
        p.setPen(QPen(QColor("#0a0c10"), 1))
        p.setBrush(spindle)
        p.drawEllipse(c, 5.5, 5.5)
        p.end()
        self._cache["spin"] = spin

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        centre, radius = self._geometry()
        self._layers(radius)
        size = self._cache_key[0]
        plate = self._cache["plate"]
        p.drawPixmap(QPointF(centre.x() - plate.width() / 2, centre.y() - plate.height() / 2), plate)
        if self.playing:
            p.setPen(QPen(_alpha(self.colour, 150), 2.2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(centre, radius * 1.02, radius * 1.02)
        corner = QPointF(centre.x() - size / 2, centre.y() - size / 2)

        def rotated(name: str) -> None:
            p.save()
            p.translate(centre)
            p.rotate(self.angle)
            p.translate(-size / 2, -size / 2)
            p.drawPixmap(0, 0, self._cache[name])
            p.restore()

        if self.loaded:
            p.drawPixmap(corner, self._cache["record"])
            rotated("spin")
        else:
            rotated("dots")
            p.setPen(QPen(QColor(EDGE_HI), 1, Qt.DashLine))
            p.setBrush(QColor("#10141c"))
            p.drawEllipse(centre, radius * 0.9, radius * 0.9)
            p.setPen(QColor(MUTED))
            p.setFont(_font(9, QFont.DemiBold))
            p.drawText(QRectF(centre.x() - radius, centre.y() - 22, radius * 2, 44), Qt.AlignCenter,
                       "drop a track here\nor pick one in the crate")
        self._paint_arm(p, centre, radius)

    def _paint_arm(self, p: QPainter, centre: QPointF, radius: float) -> None:
        a = radius * 1.0
        pivot = QPointF(centre.x() + a, centre.y() - a)
        length = radius * 1.22
        if self.loaded:
            target = radius * (0.86 - 0.47 * min(1.0, max(0.0, self.progress)))
        else:
            target = radius * 1.14
        arg = (target ** 2 - 2 * a * a - length ** 2) / (2 * length * a * math.sqrt(2))
        theta = math.acos(max(-1.0, min(1.0, arg))) - math.pi / 4
        stylus = QPointF(pivot.x() + length * math.cos(theta), pivot.y() + length * math.sin(theta))
        back = QPointF(pivot.x() - math.cos(theta) * radius * 0.22, pivot.y() - math.sin(theta) * radius * 0.22)
        p.setPen(QPen(QColor("#0a0c10"), 1))
        p.setBrush(QColor("#2b3243"))
        p.drawEllipse(back, radius * 0.07, radius * 0.07)
        p.setPen(QPen(QColor(0, 0, 0, 110), 5.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(pivot + QPointF(3, 4), stylus + QPointF(3, 4))
        p.setPen(QPen(QColor("#c9ced9"), 3.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(pivot, stylus)
        p.save()
        p.translate(stylus)
        p.rotate(math.degrees(theta) + 90)
        p.setPen(QPen(QColor("#0a0c10"), 1))
        p.setBrush(QColor("#e9edf5"))
        p.drawRoundedRect(QRectF(-5, -3, 10, 13), 2, 2)
        p.setBrush(QColor(self.colour))
        p.drawRect(QRectF(-5, 7, 10, 3))
        p.restore()
        base = QRadialGradient(pivot - QPointF(3, 3), radius * 0.12)
        base.setColorAt(0, QColor("#5c6477"))
        base.setColorAt(1, QColor("#1b2130"))
        p.setBrush(base)
        p.setPen(QPen(QColor("#07090d"), 1))
        p.drawEllipse(pivot, radius * 0.1, radius * 0.1)

    def on_press(self, pos: QPointF, button: str) -> None:
        if not self.loaded or button != "left":
            return
        centre, radius = self._geometry()
        distance = math.hypot(pos.x() - centre.x(), pos.y() - centre.y())
        if distance > radius * 1.08:
            return
        self.mode = "bend" if distance > radius * 0.9 else "scratch"
        self._last_angle = self._angle_at(pos)
        self._motion = 0.0
        self.setCursor(Qt.ClosedHandCursor)

    def on_move(self, pos: QPointF) -> None:
        if self.mode is None:
            return
        angle = self._angle_at(pos)
        self._motion += (angle - self._last_angle + 180) % 360 - 180
        self._last_angle = angle

    def on_release(self, pos: QPointF) -> None:
        self.mode = None
        self.setCursor(Qt.OpenHandCursor)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.loaded:
            self.wheel_nudge += event.angleDelta().y() / 120.0


class BeatBar(QWidget):
    """Four beats of the bar: which one is playing, and how far through it."""

    def __init__(self, colour: str) -> None:
        super().__init__()
        self.colour = colour
        self.beat: Optional[float] = None           # beats since the grid start
        self._shown = None
        self.setFixedHeight(8)

    def show_beat(self, beat: Optional[float]) -> None:
        self.beat = beat
        key = None if beat is None else (int(beat) % 4, round((beat % 1) * 24))
        if key != self._shown:
            self._shown = key
            self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        w, h = self.width(), self.height()
        gap = 4
        seg = (w - gap * 3) / 4
        current = None if self.beat is None else int(self.beat) % 4
        for i in range(4):
            x = i * (seg + gap)
            p.fillRect(QRectF(x, 0, seg, h), QColor("#222b3c"))
            if current == i:
                p.fillRect(QRectF(x, 0, seg, h), _alpha(self.colour, 60))
                p.fillRect(QRectF(x, 0, seg * (self.beat % 1), h), _alpha(self.colour, 190))
            if i == 0:
                p.fillRect(QRectF(x, 0, 3, h), QColor("#ffffff") if current == 0 else QColor(MUTED))


class WaveDetail(TouchInput, QWidget):
    """
    The scrolling three-band waveform around the playhead, with the beat grid.
    Filled in while the track is still decoding. Tap to zoom; with the deck
    paused, drag to move through the track.
    """

    scrubbed = Signal(float)            # seconds to move by

    ZOOMS = (0.8, 1.6, 3.2)

    def __init__(self, colour: str) -> None:
        super().__init__()
        self._init_touch()
        self.colour = colour
        self.track: Optional[de.Track] = None
        self.pos_sec = 0.0
        self.cue_sec: Optional[float] = None
        self.hot: List[Optional[float]] = []
        self.loop: Optional[tuple] = None
        self.loading: Optional[float] = None
        self.message = ""
        self.zoom = 1.6
        self.can_scrub = False
        self._arr: Optional[np.ndarray] = None
        self._image: Optional[QImage] = None
        self._built = 0
        self._refs = None
        self._refs_at = 0
        self._shown = None
        self._drag_x: Optional[float] = None
        self.setFixedHeight(de.DETAIL_H + 8)
        self.setToolTip("Tap to zoom · drag while paused to move through the track")

    # -- building the picture ---------------------------------------------- #
    def set_track(self, track: Optional[de.Track]) -> None:
        self.track = track
        self._arr = None
        self._image = None
        self._built = 0
        self._refs = None
        self._refs_at = 0
        self.sync()

    def sync(self, final: bool = False) -> None:
        """Draw the columns the decoder has finished since last time."""
        track = self.track
        if track is None or track.levels is None:
            self.update()
            return
        levels = track.levels
        cols = min(track.cols, len(levels))
        if self._arr is None or self._arr.shape[1] != len(levels):
            self._arr = np.zeros((de.DETAIL_H, len(levels)), np.uint32)
            self._built = 0
        rebuild = False
        if final and track.refs:
            if self._refs != track.refs:
                self._refs = track.refs
                rebuild = True
        elif self._refs is None or (cols > self._refs_at * 2 and cols > 300):
            # scale from what has arrived; re-scale as the track fills in
            self._refs = de.level_refs(levels[:cols])
            self._refs_at = cols
            rebuild = True
        start = 0 if rebuild else self._built
        if cols > start:
            heights = de.band_levels_display(levels[start:cols], self._refs)
            self._arr[:, start:cols] = de.detail_columns(heights)
            self._built = cols
        h, w = self._arr.shape
        self._image = QImage(self._arr.data, w, h, w * 4, QImage.Format_ARGB32)
        self._shown = None
        self.update()

    def show_state(self, pos_sec: float, cue, hot, loop) -> None:
        self.pos_sec, self.cue_sec, self.hot, self.loop = pos_sec, cue, hot, loop
        key = (round(pos_sec * de.DETAIL_FPS * self.zoom), cue, tuple(hot), loop, self.zoom,
               self.loading is None)
        if key != self._shown:
            self._shown = key
            self.update()

    # -- input -------------------------------------------------------------- #
    def on_press(self, pos: QPointF, button: str) -> None:
        self._drag_x = pos.x()

    def on_move(self, pos: QPointF) -> None:
        if self._drag_x is None or not self._t_moved or not self.can_scrub:
            return
        dx = pos.x() - self._drag_x
        self._drag_x = pos.x()
        self.scrubbed.emit(-dx / (self.zoom * de.DETAIL_FPS))

    def on_release(self, pos: QPointF) -> None:
        if not self._t_moved:
            i = min(range(len(self.ZOOMS)), key=lambda k: abs(self.ZOOMS[k] - self.zoom))
            self.zoom = self.ZOOMS[(i + 1) % len(self.ZOOMS)]
            self.update()
        self._drag_x = None

    def wheelEvent(self, event) -> None:  # noqa: N802
        self.zoom = max(0.5, min(6.0, self.zoom * (1.15 if event.angleDelta().y() > 0 else 1 / 1.15)))
        self.update()

    # -- painting ----------------------------------------------------------- #
    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(QColor(EDGE), 1))
        p.setBrush(QColor(WELL))
        p.drawRoundedRect(rect, 8, 8)
        clip = QPainterPath()
        clip.addRoundedRect(rect.adjusted(1, 1, -1, -1), 7, 7)
        p.setClipPath(clip)
        w, h = self.width(), self.height()
        mid = w / 2
        top = (h - de.DETAIL_H) / 2
        track = self.track
        if self._image is not None and track is not None:
            x0 = self.pos_sec * de.DETAIL_FPS - mid / self.zoom
            s0, s1 = max(0.0, x0), min(float(self._built), x0 + w / self.zoom)
            if s1 > s0:
                p.drawImage(QRectF((s0 - x0) * self.zoom, top, (s1 - s0) * self.zoom, de.DETAIL_H),
                            self._image, QRectF(s0, 0, s1 - s0, de.DETAIL_H))
            p.fillRect(QRectF(0, 0, mid, h), QColor(8, 10, 15, 95))
            if self.loop is not None:
                la = (self.loop[0] * de.DETAIL_FPS - x0) * self.zoom
                lb = (self.loop[1] * de.DETAIL_FPS - x0) * self.zoom
                p.fillRect(QRectF(la, 0, lb - la, h), _alpha(OK, 45))
                p.setPen(QPen(QColor(OK), 1.5))
                p.drawLine(QPointF(la, 0), QPointF(la, h))
                p.drawLine(QPointF(lb, 0), QPointF(lb, h))
            if track.bpm:
                beat = 60.0 / track.bpm
                k = math.ceil((x0 / de.DETAIL_FPS - track.first_beat) / beat)
                while True:
                    x = ((track.first_beat + k * beat) * de.DETAIL_FPS - x0) * self.zoom
                    if x > w:
                        break
                    bar = k % 4 == 0
                    p.setPen(QPen(QColor(255, 255, 255, 120 if bar else 45), 1.4 if bar else 1))
                    p.drawLine(QPointF(x, 0), QPointF(x, h if bar else 7))
                    if bar:
                        p.drawLine(QPointF(x, h - 7), QPointF(x, h))
                    k += 1
            for i, cue in enumerate(self.hot):
                if cue is not None:
                    x = (cue * de.DETAIL_FPS - x0) * self.zoom
                    p.fillRect(QRectF(x - 1, 0, 2, h), QColor(HOT_COLOURS[i]))
            if self.cue_sec is not None:
                x = (self.cue_sec * de.DETAIL_FPS - x0) * self.zoom
                path = QPainterPath()
                path.moveTo(x - 6, 0)
                path.lineTo(x + 6, 0)
                path.lineTo(x, 8)
                path.closeSubpath()
                p.fillPath(path, QColor(WARN))
            p.setPen(QPen(_alpha(self.colour, 110), 5))
            p.drawLine(QPointF(mid, 0), QPointF(mid, h))
            p.setPen(QPen(QColor("#ffffff"), 1.6))
            p.drawLine(QPointF(mid, 0), QPointF(mid, h))
        p.setClipping(False)
        if self.loading is not None:
            p.fillRect(QRectF(8, h - 3, (w - 16) * self.loading, 2), QColor(self.colour))
            p.setPen(QColor(DIM))
            p.setFont(_font(8, QFont.DemiBold))
            p.drawText(rect.adjusted(10, 4, -10, -4), Qt.AlignTop | Qt.AlignRight,
                       f"analysing  {int(self.loading * 100)}%")
        text = self.message or ("" if track is not None else "No track loaded")
        if text:
            p.setPen(QColor(DIM))
            p.setFont(_font(9, QFont.DemiBold))
            p.drawText(rect, Qt.AlignCenter, text)


class WaveOverview(TouchInput, QWidget):
    """Whole-track waveform. Tap or drag to jump."""

    seekRequested = Signal(float)       # fraction 0..1

    def __init__(self, colour: str) -> None:
        super().__init__()
        self._init_touch()
        self.colour = colour
        self.track: Optional[de.Track] = None
        self.fraction = 0.0
        self.cue: Optional[float] = None
        self.hot: List[Optional[float]] = []
        self.loop: Optional[tuple] = None
        self._pixmap: Optional[QPixmap] = None
        self._pix_key = None
        self._shown = None
        self.setFixedHeight(36)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Tap to jump to that point")

    def set_track(self, track: Optional[de.Track]) -> None:
        self.track = track
        self._pix_key = None
        self.update()

    def sync(self) -> None:
        self._pix_key = None
        self._shown = None
        self.update()

    def show_state(self, fraction: float, cue, hot, loop) -> None:
        self.fraction, self.cue, self.hot, self.loop = fraction, cue, hot, loop
        key = (int(fraction * (self.width() - 4)), cue, tuple(hot), loop)
        if key != self._shown:
            self._shown = key
            self.update()

    def _render(self) -> None:
        track = self.track
        key = (id(track), track.cols if track else 0, self.width(), self.height())
        if key == self._pix_key:
            return
        self._pix_key = key
        self._pixmap = None
        if track is None or track.levels is None or track.cols < 2 or self.width() < 10:
            return
        w, h = self.width() - 4, self.height() - 6
        total_cols = max(track.cols, int(track.duration * de.DETAIL_FPS))
        edges = np.linspace(0, total_cols, w + 1).astype(np.int64)
        starts = np.minimum(edges[:-1], track.cols - 1)
        levels = track.levels[: track.cols]
        refs = track.refs or de.level_refs(levels)
        cols = np.maximum.reduceat(levels, starts, axis=0)
        cols[edges[:-1] >= track.cols] = 0.0          # not decoded yet
        heights = de.band_levels_display(cols, refs)
        half = (h - 1) / 2.0
        distance = (np.abs(np.arange(h, dtype=np.float32) - half) / (half + 1.0))[:, None]
        image = np.zeros((h, w), np.uint32)
        for band, argb in enumerate(de.BAND_ARGB):
            image[distance <= heights[:, band][None, :]] = argb
        self._pixmap = QPixmap.fromImage(QImage(image.data, w, h, w * 4, QImage.Format_ARGB32))

    def paintEvent(self, _event) -> None:  # noqa: N802
        self._render()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(QColor(EDGE), 1))
        p.setBrush(QColor(WELL))
        p.drawRoundedRect(rect, 6, 6)
        if self._pixmap is None or self.track is None:
            return
        p.drawPixmap(2, 3, self._pixmap)
        w = self.width() - 4
        played = self.fraction * w
        p.fillRect(QRectF(2, 3, played, self.height() - 6), QColor(8, 10, 15, 140))
        duration = self.track.duration or 1.0
        if self.loop is not None:
            a = 2 + self.loop[0] / duration * w
            b = 2 + self.loop[1] / duration * w
            p.fillRect(QRectF(a, 1, max(2.0, b - a), self.height() - 2), _alpha(OK, 90))
        for i, cue in enumerate(self.hot):
            if cue is not None:
                p.fillRect(QRectF(2 + cue / duration * w - 1, 1, 2, 7), QColor(HOT_COLOURS[i]))
        if self.cue is not None:
            p.fillRect(QRectF(2 + self.cue / duration * w - 1, self.height() - 8, 2, 7), QColor(WARN))
        p.setPen(QPen(QColor("#ffffff"), 1.6))
        p.drawLine(QPointF(2 + played, 1), QPointF(2 + played, self.height() - 1))

    def _seek(self, x: float) -> None:
        if self.track is not None:
            self.seekRequested.emit(max(0.0, min(1.0, (x - 2) / max(1, self.width() - 4))))

    def on_press(self, pos: QPointF, button: str) -> None:
        self._seek(pos.x())

    def on_move(self, pos: QPointF) -> None:
        self._seek(pos.x())


class StepGrid(TouchInput, QWidget):
    """
    16 steps × 7 rows. Drums: tap toggles, long-press (or right-click) accents,
    drag paints. Acid: tap toggles, drag up/down (or wheel) sets the note,
    long-press cycles accent / slide. Tap a row name to mute it.
    """

    changed = Signal()
    acidChanged = Signal()

    ROWS = de.ROWS + ("acid",)
    LABEL_W = 84
    GAP = 3

    def __init__(self, machine: de.Machine) -> None:
        super().__init__()
        self._init_touch()
        self.machine = machine
        self.playhead = -1
        self.row_h = SIZE.grid_row
        self._paint_value = None
        self._paint_row = None
        self._press = None                 # (row, step, original level / note, pos)
        self._acid_dragged = False
        self._long_done = False
        self.setMinimumHeight(len(self.ROWS) * (self.row_h + self.GAP))
        self.setMinimumWidth(self.LABEL_W + 16 * 26)

    def _cell(self, row: int, step: int) -> QRectF:
        width = (self.width() - self.LABEL_W - self.GAP * 15 - 12) / 16
        x = self.LABEL_W + step * (width + self.GAP) + (step // 4) * 4
        return QRectF(x, row * (self.row_h + self.GAP), width, self.row_h)

    def _hit(self, pos: QPointF):
        row = int(pos.y() // (self.row_h + self.GAP))
        if not 0 <= row < len(self.ROWS):
            return None, None
        if pos.x() < self.LABEL_W - 6:
            return row, -1
        for step in range(16):
            if self._cell(row, step).adjusted(-2, -2, 2, 2).contains(pos):
                return row, step
        return row, None

    def set_playhead(self, step: int) -> None:
        if step != self.playhead:
            self.playhead = step
            self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        m = self.machine
        if self.playhead >= 0:
            first, last = self._cell(0, self.playhead), self._cell(len(self.ROWS) - 1, self.playhead)
            p.fillRect(QRectF(first.left() - 2, 0, first.width() + 4, last.bottom()), QColor(255, 255, 255, 16))
        for r, name in enumerate(self.ROWS):
            colour = ROW_COLOURS[name]
            muted = name in m.mutes
            y = r * (self.row_h + self.GAP)
            label_rect = QRectF(0, y, self.LABEL_W - 10, self.row_h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#1a2130") if not muted else QColor("#2a1a1e"))
            p.drawRoundedRect(label_rect, 5, 5)
            p.setBrush(QColor(colour) if not muted else QColor("#4a3035"))
            p.drawRoundedRect(QRectF(4, y + 6, 4, self.row_h - 12), 2, 2)
            p.setPen(QColor(MUTED if muted else TEXT))
            p.setFont(_font(7.6, QFont.Bold))
            p.drawText(label_rect.adjusted(14, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft,
                       de.ROW_LABELS[name] + ("  (M)" if muted else ""))
            for s in range(16):
                cell = self._cell(r, s)
                if name == "acid":
                    step = m.acid[s]
                    level = (2 if step["accent"] else 1) if step["on"] else 0
                else:
                    level = m.rows[name][s]
                if level:
                    fill = QColor(colour)
                    if level == 1:
                        fill = fill.darker(135)
                    if muted:
                        fill.setAlpha(90)
                    if level == 2:
                        p.setPen(QPen(QColor(colour).lighter(130), 1.2))
                    else:
                        p.setPen(Qt.NoPen)
                    p.setBrush(fill)
                else:
                    p.setPen(QPen(QColor("#222a39"), 1))
                    p.setBrush(QColor("#1c2331") if (s // 4) % 2 == 0 else QColor("#171d29"))
                p.drawRoundedRect(cell, 4, 4)
                if s == self.playhead and level:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(255, 255, 255, 90))
                    p.drawRoundedRect(cell, 4, 4)
                if name == "acid" and m.acid[s]["on"]:
                    step = m.acid[s]
                    note = de.NOTE_NAMES[(m.key + step["note"]) % 12]
                    octave = "↑" if step["note"] >= 12 else "↓" if step["note"] < 0 else ""
                    p.setPen(QColor("#0b0e14"))
                    p.setFont(_font(7, QFont.Bold))
                    p.drawText(cell, Qt.AlignCenter, note + octave)
                    if step["slide"]:
                        p.setPen(QPen(QColor("#0b0e14"), 1.5))
                        p.drawLine(QPointF(cell.left() + 4, cell.bottom() - 3),
                                   QPointF(cell.right() + self.GAP, cell.bottom() - 3))

    def on_press(self, pos: QPointF, button: str) -> None:
        row, step = self._hit(pos)
        self._press = None
        self._long_done = False
        if row is None or step is None:
            return
        name = self.ROWS[row]
        m = self.machine
        if step == -1:
            if name in m.mutes:
                m.mutes.discard(name)
            else:
                m.mutes.add(name)
            self.changed.emit()
            self.update()
            return
        if name == "acid":
            cell = m.acid[step]
            if button == "right":
                self._cycle_acid(step)
                return
            self._press = (row, step, cell["note"], pos)
            self._acid_dragged = False
            return
        current = m.rows[name][step]
        self._press = (row, step, current, pos)
        value = (0 if current == 2 else 2) if button == "right" else (0 if current else 1)
        m.rows[name][step] = value
        self._paint_value, self._paint_row = value, row
        self.changed.emit()
        self.update()

    def on_move(self, pos: QPointF) -> None:
        if self._press is None:
            return
        row0, step0, original, start = self._press
        name = self.ROWS[row0]
        if name == "acid":
            dy = pos.y() - start.y()
            if abs(dy) > 10 or self._acid_dragged:
                self._acid_dragged = True
                cell = self.machine.acid[step0]
                note = max(-12, min(24, original + int(round(-dy / 12.0))))
                if note != cell["note"] or not cell["on"]:
                    cell["note"] = note
                    cell["on"] = True
                    self.acidChanged.emit()
                    self.update()
            return
        row, step = self._hit(pos)
        if row != self._paint_row or step is None or step < 0:
            return
        if self.machine.rows[name][step] != self._paint_value:
            self.machine.rows[name][step] = self._paint_value
            self.changed.emit()
            self.update()

    def on_release(self, pos: QPointF) -> None:
        press, self._press = self._press, None
        self._paint_row = None
        if press is None or self._long_done:
            return
        row, step, _original, _start = press
        if self.ROWS[row] == "acid" and not self._acid_dragged:
            cell = self.machine.acid[step]
            cell["on"] = not cell["on"]
            self.acidChanged.emit()
            self.update()

    def on_long_press(self, pos: QPointF) -> None:
        if self._press is None:
            return
        row, step, original, _start = self._press
        self._long_done = True
        name = self.ROWS[row]
        if name == "acid":
            self._cycle_acid(step)
        else:
            self.machine.rows[name][step] = 1 if original == 2 else 2
            self.changed.emit()
            self.update()

    def _cycle_acid(self, step: int) -> None:
        cell = self.machine.acid[step]
        if not cell["on"]:
            cell["on"] = True
        else:
            order = [(False, False), (True, False), (False, True), (True, True)]
            cell["accent"], cell["slide"] = order[(order.index((cell["accent"], cell["slide"])) + 1) % 4]
        self.acidChanged.emit()
        self.update()

    def wheelEvent(self, event) -> None:  # noqa: N802
        row, step = self._hit(event.position())
        if row is None or step is None or step < 0 or self.ROWS[row] != "acid":
            return
        cell = self.machine.acid[step]
        delta = 1 if event.angleDelta().y() > 0 else -1
        if event.modifiers() & Qt.ShiftModifier:
            delta *= 12
        cell["note"] = max(-12, min(24, cell["note"] + delta))
        cell["on"] = True
        self.acidChanged.emit()
        self.update()


# --------------------------------------------------------------------------- #
# Deck, mixer, machine, crate
# --------------------------------------------------------------------------- #

class DeckView(QFrame):
    """One turntable with its waveform, pitch, transport, hot cues and loops."""

    status = Signal(str)

    def __init__(self, panel: "DJPanel", index: int) -> None:
        super().__init__()
        self.setObjectName("djCard")
        self.panel = panel
        self.engine = panel.engine
        self.deck = self.engine.decks[index]
        self.index = index
        self.colour = DECK_COLOURS[index]
        self.letter = "AB"[index]
        self.job: Optional[de.LoadJob] = None
        self._scratch_rate = 0.0
        self._bend = 0.0
        self._last_tick = time.monotonic()
        self._last_sync = 0.0
        self.pitch_range = 0.08
        self.setAcceptDrops(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(7)

        header = QHBoxLayout()
        header.setSpacing(10)
        badge = QLabel(self.letter)
        badge.setFixedSize(30, 30)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f"background: {self.colour}; color: #0b0e14; border-radius: 8px; "
                            f"font-size: 15px; font-weight: 800;")
        header.addWidget(badge)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.title = QLabel("Empty deck")
        self.title.setObjectName("djTrack")
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.sub = QLabel("drop a track, or double-tap one in the crate")
        self.sub.setObjectName("djSub")
        self.sub.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        names.addWidget(self.title)
        names.addWidget(self.sub)
        header.addLayout(names, 1)
        tempo = QVBoxLayout()
        tempo.setSpacing(0)
        self.bpm_btn = QPushButton("---.--")
        self.bpm_btn.setObjectName("djBpm")
        self.bpm_btn.setFocusPolicy(Qt.NoFocus)
        self.bpm_btn.setCursor(Qt.PointingHandCursor)
        self.bpm_btn.setStyleSheet(f"color: {self.colour};")
        self.bpm_btn.setToolTip("Tap: double / halve the tempo, or move beat 1 here")
        self.bpm_btn.clicked.connect(self._bpm_menu)
        self.bpm_sub = QLabel("BPM")
        self.bpm_sub.setObjectName("djSmall")
        self.bpm_sub.setAlignment(Qt.AlignRight)
        tempo.addWidget(self.bpm_btn, 0, Qt.AlignRight)
        tempo.addWidget(self.bpm_sub)
        header.addLayout(tempo)
        times = QVBoxLayout()
        times.setSpacing(0)
        self.time_label = QLabel("0:00.0")
        self.time_label.setObjectName("djTime")
        self.time_label.setAlignment(Qt.AlignRight)
        self.time_label.setMinimumWidth(78)
        self.remain_label = QLabel("-0:00.0")
        self.remain_label.setObjectName("djSmall")
        self.remain_label.setAlignment(Qt.AlignRight)
        times.addWidget(self.time_label)
        times.addWidget(self.remain_label)
        header.addLayout(times)
        outer.addLayout(header)

        self.detail = WaveDetail(self.colour)
        self.detail.scrubbed.connect(self._scrub)
        outer.addWidget(self.detail)
        self.beatbar = BeatBar(self.colour)
        outer.addWidget(self.beatbar)
        self.overview = WaveOverview(self.colour)
        self.overview.seekRequested.connect(self._seek_fraction)
        outer.addWidget(self.overview)

        body = QHBoxLayout()
        body.setSpacing(10)
        self.platter = Platter(self.colour, self.letter)
        side = QVBoxLayout()
        side.setSpacing(6)
        self.sync_btn = _button("SYNC", "Match tempo and lock the beat to the other deck "
                                        "(or to the techno machine)", True)
        # clicked, not toggled: the per-frame refresh mirrors the engine into the
        # button and must not be mistaken for the DJ pressing it
        self.sync_btn.clicked.connect(lambda: self._on_sync(self.sync_btn.isChecked()))
        side.addWidget(self.sync_btn)
        self.pitch = Fader(True, -1.0, 1.0, 0.0, self.colour, 90,
                           "Tempo. Double-tap resets to 0 %")
        self.pitch.valueChanged.connect(self._on_pitch)
        side.addWidget(self.pitch, 1, Qt.AlignHCenter)
        self.pitch_label = QLabel("0.00 %")
        self.pitch_label.setObjectName("djSmall")
        self.pitch_label.setAlignment(Qt.AlignCenter)
        side.addWidget(self.pitch_label)
        self.range_btn = _button("±8", "Pitch range: ±8 % / ±16 % / ±50 %")
        self.range_btn.clicked.connect(self._cycle_range)
        side.addWidget(self.range_btn)
        if index == 0:
            body.addWidget(self.platter, 1)
            body.addLayout(side)
        else:
            body.addLayout(side)
            body.addWidget(self.platter, 1)
        outer.addLayout(body, 1)

        transport = QHBoxLayout()
        transport.setSpacing(6)
        self.cue_btn = _button("CUE", "Playing: back to the cue point and stop.\n"
                                      "Stopped: set the cue point here.")
        self.cue_btn.setMinimumHeight(SIZE.transport)
        self.cue_btn.clicked.connect(self._on_cue)
        self.play_btn = _button("▶  PLAY", "Play / pause", True)
        self.play_btn.setMinimumHeight(SIZE.transport)
        self.play_btn.clicked.connect(self._on_play)
        self.play_btn.setStyleSheet(
            f"QPushButton#dj:checked {{ background: rgba(87, 201, 138, 0.18); "
            f"border-color: {OK}; color: {OK}; }}")
        transport.addWidget(self.cue_btn, 2)
        transport.addWidget(self.play_btn, 3)
        transport.addSpacing(6)
        self.hot_btns: List[HoldButton] = []
        self._hot_shown: List[Optional[bool]] = [None] * 4
        for i in range(4):
            btn = HoldButton(str(i + 1), "Hot cue: tap to set or jump · hold (or right-click) to clear")
            btn.setMinimumHeight(SIZE.transport)
            btn.clicked.connect(lambda _c=False, i=i: self._on_hot(i))
            btn.held.connect(lambda i=i: self._clear_hot(i))
            transport.addWidget(btn, 1)
            self.hot_btns.append(btn)
        outer.addLayout(transport)

        loops = QHBoxLayout()
        loops.setSpacing(5)
        caption = QLabel("LOOP")
        caption.setObjectName("djSmall")
        loops.addWidget(caption)
        self.loop_btns: Dict[int, QPushButton] = {}
        for beats in (1, 2, 4, 8, 16):
            btn = _button(str(beats), f"Loop {beats} beat(s) from the nearest beat · tap again to exit",
                          True)
            btn.clicked.connect(lambda _c=False, b=beats: self._on_loop(b))
            loops.addWidget(btn, 1)
            self.loop_btns[beats] = btn
        loops.addSpacing(6)
        back = _button("◀ 4", "Jump back 4 beats")
        back.clicked.connect(lambda: self._jump(-4))
        fwd = _button("4 ▶", "Jump forward 4 beats")
        fwd.clicked.connect(lambda: self._jump(4))
        loops.addWidget(back, 1)
        loops.addWidget(fwd, 1)
        loops.addSpacing(6)
        load = _button("LOAD…", "Open an audio file on this deck")
        load.clicked.connect(self._browse)
        loops.addWidget(load, 1)
        outer.addLayout(loops)

    # -- loading ------------------------------------------------------------ #
    def load(self, path: str) -> None:
        if self.deck.playing:
            self.status.emit(f"Deck {self.letter} is playing - pause it before loading a new track.")
            return
        if not de.is_audio(path) or not os.path.isfile(path):
            self.status.emit(f"Not an audio file: {os.path.basename(path)}")
            return
        if self.job is not None:
            if self.job.track is not None:
                self.job.track.complete = True        # keep what arrived playable
            self.panel.decoder.cancel(self.job)
        job = self.panel.decoder.load(path, self.engine.sr)
        self.job = job
        job.opened.connect(lambda track, j=job: self._on_opened(j, track))
        job.progress.connect(lambda value, j=job: self._on_progress(j, value))
        job.done.connect(lambda track, j=job: self._on_done(j, track))
        job.failed.connect(lambda message, j=job: self._on_failed(j, message))
        _set_text(self.title, os.path.splitext(os.path.basename(path))[0])
        _set_text(self.sub, "loading…")
        self.detail.message = ""
        self.detail.loading = 0.0
        self.detail.update()

    def _on_opened(self, job: de.LoadJob, track: de.Track) -> None:
        if job is not self.job:
            self.panel.decoder.retire(track)
            return
        deck = self.deck
        old = deck.track

        def install():
            deck.track = track
            deck.pos = track.first_beat * track.sr if track.bpm else 0.0
            deck.cue = deck.pos
            deck.hot = [None] * 4
            deck.loop = None
            deck.loop_beats = 0
            deck.playing = False
            deck.rate_now = 0.0
            if not deck.sync:
                deck.pitch = 0.0
        self.engine.post(install)
        if old is not None and old is not track:
            self.panel.decoder.retire(old)
        if not deck.sync:
            self.pitch.setValue(0.0, emit=False)
        self.detail.set_track(track)
        self.overview.set_track(track)
        folder = os.path.basename(os.path.dirname(track.path))
        _set_text(self.sub, f"{int(track.duration // 60)}:{int(track.duration % 60):02d}  ·  {folder}")

    def _on_progress(self, job: de.LoadJob, value: float) -> None:
        if job is not self.job:
            return
        self.detail.loading = value
        now = time.monotonic()
        if now - self._last_sync > 0.25:
            self._last_sync = now
            self.detail.sync()
            self.overview.sync()

    def _on_done(self, job: de.LoadJob, track: de.Track) -> None:
        if job is not self.job:
            return
        self.job = None
        self.detail.loading = None
        self.detail.sync(final=True)
        self.overview.sync()
        deck = self.deck
        if track.bpm and not deck.playing and deck.pos < track.sr * 0.05:
            # the grid is known now: park on the first beat, like a CDJ's auto-cue
            first = track.first_beat * track.sr

            def park():
                if not deck.playing and deck.track is track:
                    deck.pos = deck.cue = first
            self.engine.post(park)
        folder = os.path.basename(os.path.dirname(track.path))
        _set_text(self.sub, f"{int(track.duration // 60)}:{int(track.duration % 60):02d}  ·  {folder}")
        self.panel.crate.update_row(track.path)
        if not track.bpm:
            self.status.emit(f"Deck {self.letter}: no steady beat found - sync and loops are off.")
        else:
            self.status.emit(f"Deck {self.letter}: {track.title} - {track.bpm:g} BPM")

    def _on_failed(self, job: de.LoadJob, message: str) -> None:
        if job is not self.job:
            return
        self.job = None
        self.detail.loading = None
        self.detail.message = "Could not load this file"
        self.detail.update()
        _set_text(self.sub, message)
        self.status.emit(f"Deck {self.letter}: {message}")

    def _browse(self) -> None:
        start = self.panel.crate.current_folder() or os.path.expanduser("~/Music")
        path, _ = QFileDialog.getOpenFileName(
            self, f"Load on deck {self.letter}", start,
            "Audio (" + " ".join(f"*{e}" for e in de.AUDIO_EXTENSIONS) + ")")
        if path:
            self.load(path)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls and de.is_audio(urls[0].toLocalFile()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        self.load(event.mimeData().urls()[0].toLocalFile())

    # -- transport ---------------------------------------------------------- #
    def _on_play(self) -> None:
        deck = self.deck
        if deck.track is None:
            self.play_btn.setChecked(False)
            return

        def toggle():
            if deck.playing:
                deck.playing = False
            else:
                if deck.track.complete and deck.pos >= deck.track.frames - 2:
                    deck.pos = deck.cue
                deck.playing = True
                deck.snap_pending = deck.sync
        self.engine.post(toggle)

    def _on_cue(self) -> None:
        deck = self.deck
        if deck.track is None:
            return

        def cue():
            if deck.playing:
                deck.playing = False
                deck.pos = deck.cue
                deck.rate_now = 0.0
            else:
                deck.cue = deck.pos
        self.engine.post(cue)

    def _on_hot(self, i: int) -> None:
        deck = self.deck
        if deck.track is None:
            return

        def hot():
            if deck.hot[i] is None:
                heard = deck.heard_pos()      # where the DJ heard it, not what was just rendered
                deck.hot[i] = deck.track.nearest_beat(heard) if deck.track.bpm else heard
            else:
                deck.pos = deck.hot[i]
                if deck.loop and not deck.loop[0] <= deck.pos < deck.loop[1]:
                    deck.loop, deck.loop_beats = None, 0
                deck.snap_pending = deck.sync
        self.engine.post(hot)

    def _clear_hot(self, i: int) -> None:
        deck = self.deck
        self.engine.post(lambda: deck.hot.__setitem__(i, None))
        self.status.emit(f"Deck {self.letter}: hot cue {i + 1} cleared")

    def _on_loop(self, beats: int) -> None:
        deck = self.deck
        track = deck.track
        if track is None or not track.bpm:
            self.loop_btns[beats].setChecked(False)
            self.status.emit("Loops need a detected tempo.")
            return

        def loop():
            if deck.loop is not None and deck.loop_beats == beats:
                deck.loop, deck.loop_beats = None, 0
                return
            length = beats * track.beat_frames()
            if deck.loop is not None:
                start = deck.loop[0]          # resize the running loop in place
            else:
                heard = deck.heard_pos()
                start = track.nearest_beat(heard)
                if start > heard + 1:
                    start -= track.beat_frames()
            deck.loop, deck.loop_beats = (start, start + length), beats
        self.engine.post(loop)

    def _jump(self, beats: int) -> None:
        deck = self.deck
        if deck.track is None:
            return
        size = deck.track.beat_frames() or deck.sr * 0.5

        def jump():
            deck.pos = max(0.0, min(deck.track.frames - 2.0, deck.pos + beats * size))
            if deck.loop is not None:
                deck.loop = (deck.loop[0] + beats * size, deck.loop[1] + beats * size)
        self.engine.post(jump)

    def _seek_fraction(self, fraction: float) -> None:
        deck = self.deck
        track = deck.track
        if track is None:
            return
        target = fraction * track.duration * track.sr

        def seek():
            deck.pos = max(0.0, min(target, track.frames - 2.0))
            deck.loop, deck.loop_beats = None, 0
            deck.snap_pending = deck.sync
        self.engine.post(seek)

    def _scrub(self, seconds: float) -> None:
        deck = self.deck
        if deck.track is None or deck.playing:
            return
        frames = seconds * deck.sr

        def move():
            deck.pos = max(0.0, min(deck.track.frames - 2.0, deck.pos + frames))
        self.engine.post(move)

    def _on_sync(self, on: bool) -> None:
        deck = self.deck
        if on and (deck.track is None or not deck.track.bpm):
            self.sync_btn.setChecked(False)
            self.status.emit("Sync needs a track with a detected tempo.")
            return
        deck.snap_pending = on
        deck.sync = on

    def _on_pitch(self, value: float) -> None:
        if self.deck.sync:
            return                    # sync owns the tempo; the fader only mirrors it
        self.deck.pitch = value * self.pitch_range

    def _cycle_range(self) -> None:
        ranges = (0.08, 0.16, 0.5)
        self.pitch_range = ranges[(ranges.index(self.pitch_range) + 1) % len(ranges)]
        self.range_btn.setText(f"±{int(self.pitch_range * 100)}")
        self.pitch.setValue(max(-1.0, min(1.0, self.deck.pitch / self.pitch_range)), emit=False)

    def _bpm_menu(self) -> None:
        track = self.deck.track
        if track is None or not track.complete:
            return
        menu = QMenu(self)
        double = menu.addAction("Tempo × 2")
        half = menu.addAction("Tempo ÷ 2")
        menu.addSeparator()
        here = menu.addAction("Beat 1 is here (move the grid)")
        for action in (double, half, here):
            action.setEnabled(bool(track.bpm))
        chosen = menu.exec(self.bpm_btn.mapToGlobal(self.bpm_btn.rect().bottomLeft()))
        if chosen is None:
            return
        if chosen is double:
            track.bpm *= 2
        elif chosen is half:
            track.bpm /= 2
        elif chosen is here:
            track.first_beat = self.deck.heard_pos() / track.sr
        self.panel.cache.remember(track)            # the correction sticks for next time
        self.panel.crate.update_row(track.path)
        self.detail.update()

    # -- per-frame ---------------------------------------------------------- #
    def refresh(self) -> bool:
        """Mirror the engine into the widgets. Returns True while anything is moving."""
        deck = self.deck
        track = deck.track
        now = time.monotonic()
        dt = max(1e-3, now - self._last_tick)
        self._last_tick = now

        motion = self.platter.take_motion()
        wheel, self.platter.wheel_nudge = self.platter.wheel_nudge, 0.0
        if self.platter.mode == "scratch":
            target = (motion / dt) / REVOLUTION_DEG_PER_SEC
            self._scratch_rate += (target - self._scratch_rate) * 0.55
            deck.scratch_rate = max(-6.0, min(6.0, self._scratch_rate))
            deck.scratching = True
        else:
            deck.scratching = False
            self._scratch_rate = 0.0
            if self.platter.mode == "bend":
                self._bend = max(-0.25, min(0.25, (motion / dt) / REVOLUTION_DEG_PER_SEC * 0.12))
            else:
                self._bend *= 0.8
            self._bend = max(-0.3, min(0.3, self._bend + wheel * 0.03))
            deck.bend = self._bend if abs(self._bend) > 1e-3 else 0.0

        if track is None:
            self.platter.show_state(0.0, 0.0, False, False)
            return self.platter.mode is not None
        heard = deck.heard_pos()
        sec = heard / track.sr
        rate = abs(deck.rate_now) or 1.0
        _set_text(self.time_label, _clock(sec))
        _set_text(self.remain_label, "-" + _clock((track.duration - sec) / max(0.05, rate)))
        bpm = deck.effective_bpm()
        _set_text(self.bpm_btn, f"{bpm:6.2f}" if bpm else ("…" if not track.complete else "---.--"))
        sub = (f"{track.bpm:g} orig" if track.bpm else
               "analysing…" if not track.complete else "no beat found")
        _set_text(self.bpm_sub, ("SYNC · " + sub) if deck.sync else sub)

        duration = track.duration or 1.0
        self.platter.show_state(sec * REVOLUTION_DEG_PER_SEC, sec / duration, True, deck.playing)
        cue = round(deck.cue / track.sr, 3)
        hot = [None if h is None else round(h / track.sr, 3) for h in deck.hot]
        loop = None if deck.loop is None else (round(deck.loop[0] / track.sr, 3),
                                               round(deck.loop[1] / track.sr, 3))
        self.detail.can_scrub = not deck.playing
        self.detail.show_state(sec, cue, hot, loop)
        self.overview.show_state(sec / duration, cue, hot, loop)
        if track.bpm:
            self.beatbar.show_beat(max(0.0, (sec - track.first_beat) * track.bpm / 60.0))
        else:
            self.beatbar.show_beat(None)

        if self.play_btn.isChecked() != deck.playing:
            self.play_btn.setChecked(deck.playing)
            self.play_btn.setText("❚❚  PAUSE" if deck.playing else "▶  PLAY")
        for i, btn in enumerate(self.hot_btns):
            is_set = deck.hot[i] is not None
            if self._hot_shown[i] != is_set:
                self._hot_shown[i] = is_set
                btn.setStyleSheet((f"QPushButton#dj {{ background: {HOT_COLOURS[i]}; color: #0b0e14; "
                                   f"border-color: {HOT_COLOURS[i]}; }}") if is_set else "")
        for beats, btn in self.loop_btns.items():
            active = deck.loop is not None and deck.loop_beats == beats
            if btn.isChecked() != active:
                btn.setChecked(active)
        if deck.sync != self.sync_btn.isChecked():
            self.sync_btn.setChecked(deck.sync)
        if deck.sync and abs(deck.pitch) > self.pitch_range + 1e-6:
            fitting = [r for r in (0.08, 0.16, 0.5) if r >= abs(deck.pitch)]
            self.pitch_range = fitting[0] if fitting else 0.5
            self.range_btn.setText(f"±{int(self.pitch_range * 100)}")
        shown = max(-1.0, min(1.0, deck.pitch / self.pitch_range))
        if deck.sync and abs(shown - self.pitch.value()) > 1e-4:
            self.pitch.setValue(shown, emit=False)
        _set_text(self.pitch_label, f"{deck.pitch * 100:+.2f} %")
        return deck.playing or abs(deck.rate_now) > 1e-4 or self.platter.mode is not None \
            or self.job is not None


class ChannelStrip(QWidget):
    """Three-band EQ, filter, echo, headphone cue, meter and fader."""

    def __init__(self, name: str, colour: str, target, has_eq: bool = True) -> None:
        super().__init__()
        self.target = target
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        title = QLabel(name)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"color: {colour}; font-weight: 800; font-size: 13px;")
        layout.addWidget(title)

        def eqfmt(v):
            return "KILL" if v <= -0.99 else f"{20 * math.log10(max(1e-4, de.SpectralEQ.band_gain(v))):+.0f} dB"

        self.knobs: Dict[str, Knob] = {}
        if has_eq:
            # No trim knob: every track is loudness-matched when it loads.
            specs = (("hi", "HI", -1, 1, 0, eqfmt), ("mid", "MID", -1, 1, 0, eqfmt),
                     ("low", "LOW", -1, 1, 0, eqfmt),
                     ("filt", "FILTER", -1, 1, 0, lambda v: "LPF" if v < -0.03 else "HPF" if v > 0.03 else "OFF"),
                     ("echo", "ECHO", 0, 1, 0, lambda v: f"{int(v * 100)} %"))
            for key, label, lo, hi, default, fmt in specs:
                knob = Knob(label, lo, hi, default, GOLD if key != "filt" else "#4fd1c5", SIZE.knob, fmt)
                knob.valueChanged.connect(lambda v, k=key: self._apply(k, v))
                layout.addWidget(knob, 0, Qt.AlignHCenter)
                self.knobs[key] = knob
        self.pfl = _button("CUE", "Send this channel to the headphones", True)
        self.pfl.setFixedWidth(56)
        self.pfl.toggled.connect(lambda on: setattr(self.target, "pfl", on))
        layout.addWidget(self.pfl, 0, Qt.AlignHCenter)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.meter = Meter(1, 96)
        self.fader = Fader(True, 0.0, 1.0, 0.85 if has_eq else 0.8, colour, 96, "Channel volume")
        self.fader.setValue(getattr(target, "volume"), emit=False)
        self.fader.valueChanged.connect(lambda v: setattr(self.target, "volume", v))
        row.addWidget(self.meter)
        row.addWidget(self.fader)
        layout.addLayout(row, 1)

    def _apply(self, key: str, value: float) -> None:
        t = self.target
        if key == "filt":
            t.filt = value
        elif key == "echo":
            t.echo_send = value
        else:
            t.eq[{"low": 0, "mid": 1, "hi": 2}[key]] = value

    def refresh(self) -> bool:
        peak, self.target.peak = self.target.peak, 0.0
        self.meter.push([peak])
        return self.meter.active()


class MixerView(QFrame):
    def __init__(self, panel: "DJPanel") -> None:
        super().__init__()
        self.setObjectName("djCard")
        self.panel = panel
        engine = panel.engine
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        title = QLabel("MIXER")
        title.setObjectName("djTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        strips = QHBoxLayout()
        strips.setSpacing(8)
        self.strip_a = ChannelStrip("A", DECK_COLOURS[0], engine.decks[0])
        self.strip_m = ChannelStrip("M", MACHINE_COLOUR, engine.machine, has_eq=False)
        self.strip_b = ChannelStrip("B", DECK_COLOURS[1], engine.decks[1])
        strips.addWidget(self.strip_a)
        strips.addWidget(self.strip_m, 0, Qt.AlignBottom)
        strips.addWidget(self.strip_b)

        master = QVBoxLayout()
        master.setSpacing(4)
        self.master = Knob("MASTER", 0, 1, 0.8, GOLD, SIZE.knob + 4, lambda v: f"{int(v * 100)} %")
        self.master.setValue(engine.master_volume, emit=False)
        self.master.valueChanged.connect(lambda v: setattr(engine, "master_volume", v))
        master.addWidget(self.master, 0, Qt.AlignHCenter)
        self.master_meter = Meter(2, 90)
        master.addWidget(self.master_meter, 1, Qt.AlignHCenter)
        self.cue_mix = Knob("CUE/MST", 0, 1, 0.0, "#4fd1c5", SIZE.knob - 2,
                            lambda v: f"{int((1 - v) * 100)}/{int(v * 100)}",
                            "Headphones: cued channels ↔ master")
        self.cue_mix.valueChanged.connect(lambda v: setattr(engine, "cue_mix", v))
        self.phones = Knob("PHONES", 0, 1, 0.8, "#4fd1c5", SIZE.knob - 2, lambda v: f"{int(v * 100)} %")
        self.phones.valueChanged.connect(lambda v: setattr(engine, "cue_volume", v))
        master.addWidget(self.cue_mix, 0, Qt.AlignHCenter)
        master.addWidget(self.phones, 0, Qt.AlignHCenter)
        self.rec_btn = _button("● REC", "Record the master output to a WAV file", True)
        self.rec_btn.setFixedWidth(70)
        self.rec_btn.setStyleSheet(
            f"QPushButton#dj:checked {{ background: rgba(224, 96, 92, 0.2); border-color: {DANGER}; "
            f"color: #ff8c88; }}")
        self.rec_btn.toggled.connect(self._on_rec)
        master.addWidget(self.rec_btn, 0, Qt.AlignHCenter)
        folder = _button("MIXES", "Open the folder with recorded mixes")
        folder.setFixedWidth(70)
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.mix_folder())))
        master.addWidget(folder, 0, Qt.AlignHCenter)
        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background: {EDGE};")
        strips.addWidget(divider)
        strips.addLayout(master)
        layout.addLayout(strips, 1)

        xf_row = QHBoxLayout()
        la = QLabel("A")
        la.setStyleSheet(f"color: {DECK_COLOURS[0]}; font-weight: 800;")
        lb = QLabel("B")
        lb.setStyleSheet(f"color: {DECK_COLOURS[1]}; font-weight: 800;")
        self.crossfader = Fader(False, 0.0, 1.0, 0.5, GOLD, 170, "Crossfader · double-tap centres")
        self.crossfader.setValue(0.5, emit=False)
        self.crossfader.valueChanged.connect(lambda v: setattr(engine, "crossfader", v))
        xf_row.addWidget(la)
        xf_row.addWidget(self.crossfader, 1)
        xf_row.addWidget(lb)
        layout.addLayout(xf_row)

    @staticmethod
    def mix_folder() -> str:
        music = os.path.join(os.path.expanduser("~"), "Music")
        path = os.path.join(music if os.path.isdir(music) else os.path.expanduser("~"), "DJ Mixes")
        os.makedirs(path, exist_ok=True)
        return path

    def _on_rec(self, on: bool) -> None:
        engine = self.panel.engine
        if on:
            path = os.path.join(self.mix_folder(), time.strftime("Mix %Y-%m-%d %H-%M-%S.wav"))
            engine.start_recording(path)
            self.panel.show_status(f"Recording to {path}")
        else:
            engine.stop_recording()
            if engine.rec_path:
                self.panel.show_status(f"Mix saved: {engine.rec_path}")

    def refresh(self) -> bool:
        engine = self.panel.engine
        active = False
        for strip in (self.strip_a, self.strip_m, self.strip_b):
            active = strip.refresh() or active
        peaks, engine.master_peak = engine.master_peak, [0.0, 0.0]
        self.master_meter.push(peaks)
        active = active or self.master_meter.active()
        if self.rec_btn.isChecked() and engine.rec_file is not None:
            seconds = engine.rec_frames / engine.sr
            _set_text(self.rec_btn, f"● {int(seconds // 60):02d}:{int(seconds % 60):02d}")
        elif not self.rec_btn.isChecked():
            _set_text(self.rec_btn, "● REC")
        return active


class MachineView(QFrame):
    """The techno machine: transport, tempo, pattern bank, grid and sound knobs."""

    def __init__(self, panel: "DJPanel") -> None:
        super().__init__()
        self.setObjectName("djCard")
        self.panel = panel
        self.engine = panel.engine
        m = self.engine.machine
        self._acid_bpm = m.bpm
        self._taps: List[float] = []
        self._acid_timer = QTimer(self)
        self._acid_timer.setSingleShot(True)
        self._acid_timer.timeout.connect(self.engine.request_acid)
        self._drum_timer = QTimer(self)
        self._drum_timer.setSingleShot(True)
        self._drum_timer.timeout.connect(self.engine.rebuild_drums)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(9)

        top = QHBoxLayout()
        top.setSpacing(7)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {MACHINE_COLOUR}; font-size: 14px;")
        top.addWidget(dot)
        title = QLabel("TECHNO MACHINE")
        title.setObjectName("djTitle")
        top.addWidget(title)
        top.addSpacing(8)
        self.play_btn = _button("▶  PLAY", "Start / stop the machine", True)
        self.play_btn.setMinimumWidth(96)
        self.play_btn.setStyleSheet(
            f"QPushButton#dj:checked {{ background: rgba(181, 140, 255, 0.18); "
            f"border-color: {MACHINE_COLOUR}; color: {MACHINE_COLOUR}; }}")
        self.play_btn.toggled.connect(self._on_play)
        top.addWidget(self.play_btn)
        self.bpm = QDoubleSpinBox()
        self.bpm.setObjectName("dj")
        self.bpm.setRange(60.0, 200.0)
        self.bpm.setDecimals(1)
        self.bpm.setSingleStep(0.5)
        self.bpm.setSuffix(" BPM")
        self.bpm.setValue(m.bpm)
        self.bpm.setFixedWidth(108)
        self.bpm.valueChanged.connect(self._on_bpm)
        top.addWidget(self.bpm)
        tap = _button("TAP", "Tap in time to set the tempo")
        tap.clicked.connect(self._tap)
        top.addWidget(tap)
        self.sync_btn = _button("SYNC", "Follow the playing deck's tempo and beat", True)
        self.sync_btn.toggled.connect(self._on_sync)
        top.addWidget(self.sync_btn)
        top.addSpacing(8)
        key_label = QLabel("KEY")
        key_label.setObjectName("djSmall")
        top.addWidget(key_label)
        self.key = QComboBox()
        self.key.setObjectName("dj")
        self.key.addItems(de.NOTE_NAMES)
        self.key.setCurrentIndex(m.key)
        self.key.currentIndexChanged.connect(self._on_key)
        top.addWidget(self.key)
        top.addSpacing(8)
        self.pattern = QComboBox()
        self.pattern.setObjectName("dj")
        self.pattern.addItems(list(de.PATTERNS))
        self.pattern.setToolTip("Pattern bank")
        top.addWidget(self.pattern)
        load = _button("LOAD", "Load the chosen pattern (also sets its tempo and swing)")
        load.clicked.connect(self._load_pattern)
        top.addWidget(load)
        rnd = _button("RANDOM", "A fresh pattern that still grooves")
        rnd.clicked.connect(self._randomise)
        top.addWidget(rnd)
        clear = _button("CLEAR", "Empty every row")
        clear.clicked.connect(self._clear)
        top.addWidget(clear)
        top.addStretch(1)
        outer.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(14)
        grid_column = QVBoxLayout()
        grid_column.setSpacing(4)
        self.grid = StepGrid(m)
        self.grid.changed.connect(self.panel.save_machine_later)
        self.grid.acidChanged.connect(self._acid_changed)
        grid_column.addWidget(self.grid, 1)
        # Spelled out, not in a tooltip: there is no hover on a touch screen.
        hint = QLabel("tap = step on/off  ·  hold = accent (ACID: accent / slide)  ·  "
                      "drag an ACID step up or down = note  ·  tap a row name = mute")
        hint.setObjectName("djHint")
        hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        grid_column.addWidget(hint)
        body.addLayout(grid_column, 1)

        knobs = QGridLayout()
        knobs.setHorizontalSpacing(2)
        knobs.setVerticalSpacing(2)
        pct = lambda v: f"{int(v * 100)} %"  # noqa: E731
        specs = [
            (0, 0, "kick_tune", "TUNE", -1, 1, ROW_COLOURS["kick"], lambda v: f"{v * 6:+.1f} st", True),
            (0, 1, "kick_decay", "K.DECAY", 0, 1, ROW_COLOURS["kick"], pct, True),
            (0, 2, "kick_drive", "K.DRIVE", 0, 1, ROW_COLOURS["kick"], pct, True),
            (0, 3, "hat_decay", "HATS", 0, 1, ROW_COLOURS["hat"], pct, True),
            (0, 4, "stab_tone", "STAB", 0, 1, ROW_COLOURS["stab"], pct, True),
            (0, 5, "swing", "SWING", 0, 0.5, "#9aa6bb", pct, False),
            (1, 0, "cutoff", "CUTOFF", 0, 1, ROW_COLOURS["acid"], pct, False),
            (1, 1, "reso", "RESO", 0, 1, ROW_COLOURS["acid"], pct, False),
            (1, 2, "envmod", "ENV MOD", 0, 1, ROW_COLOURS["acid"], pct, False),
            (1, 3, "decay", "DECAY", 0, 1, ROW_COLOURS["acid"], pct, False),
            (1, 4, "accent", "ACCENT", 0, 1, ROW_COLOURS["acid"], pct, False),
            (1, 5, "drive", "DRIVE", 0, 1, ROW_COLOURS["acid"], pct, False),
            (2, 0, "send", "DELAY", 0, 1, MACHINE_COLOUR, pct, None),
            (2, 1, "feedback", "FEEDBACK", 0, 0.85, MACHINE_COLOUR, pct, None),
        ]
        self.knobs: Dict[str, Knob] = {}
        for row, col, key, label, lo, hi, colour, fmt, drums in specs:
            default = 0.0 if key == "swing" else de.MACHINE_DEFAULTS[key]
            knob = Knob(label, lo, hi, default, colour, SIZE.machine_knob, fmt)
            knob.setValue(m.swing if key == "swing" else m.params[key], emit=False)
            knob.valueChanged.connect(lambda v, k=key, d=drums: self._on_knob(k, v, d))
            knobs.addWidget(knob, row, col)
            self.knobs[key] = knob
        body.addLayout(knobs)
        outer.addLayout(body)

    def _on_play(self, on: bool) -> None:
        m = self.engine.machine

        def apply():
            m.playing = on
            if on and not m.sync:
                m.step_pos = 0.0
        self.engine.post(apply)
        _set_text(self.play_btn, "■  STOP" if on else "▶  PLAY")

    def _on_bpm(self, value: float) -> None:
        m = self.engine.machine
        if m.sync:
            return
        m.bpm = value
        self._acid_timer.start(120)
        self.panel.save_machine_later()

    def _tap(self) -> None:
        now = time.monotonic()
        self._taps = [t for t in self._taps if now - t < 2.5] + [now]
        if len(self._taps) >= 3:
            gaps = np.diff(self._taps[-5:])
            self.bpm.setValue(round(60.0 / float(np.mean(gaps)), 1))

    def _on_sync(self, on: bool) -> None:
        self.engine.machine.sync = on
        self.bpm.setEnabled(not on)

    def _on_key(self, index: int) -> None:
        self.engine.machine.key = index
        self._drum_timer.start(60)
        self._acid_timer.start(40)
        self.grid.update()
        self.panel.save_machine_later()

    def _on_knob(self, key: str, value: float, drums) -> None:
        m = self.engine.machine
        if key == "swing":
            m.swing = value
            self._acid_timer.start(60)
        else:
            m.params[key] = value
            if drums:
                self._drum_timer.start(60)
            elif drums is False:
                self._acid_timer.start(30)
        self.panel.save_machine_later()

    def _acid_changed(self) -> None:
        self._acid_timer.start(20)
        self.panel.save_machine_later()

    def _apply_pattern(self, pattern: dict, bpm: Optional[float] = None,
                       swing: Optional[float] = None) -> None:
        m = self.engine.machine
        m.rows = {row: list(pattern["rows"][row]) for row in de.ROWS}
        m.acid = [dict(step) for step in pattern["acid"]]
        if bpm is not None and not m.sync:
            self.bpm.setValue(bpm)
        if swing is not None:
            self.knobs["swing"].setValue(swing)
        self.grid.update()
        self._acid_timer.start(10)
        self.panel.save_machine_later()

    def _load_pattern(self) -> None:
        name = self.pattern.currentText()
        preset = de.PATTERNS[name]
        pattern = dict(rows={row: de._pattern(t) for row, t in preset["rows"].items()},
                       acid=de._acid(preset["acid"]))
        self._apply_pattern(pattern, preset["bpm"], preset["swing"])
        self.panel.show_status(f"Machine: {name} pattern loaded")

    def _randomise(self) -> None:
        self._apply_pattern(de.random_pattern())

    def _clear(self) -> None:
        self._apply_pattern(dict(rows={row: [0] * 16 for row in de.ROWS},
                                 acid=[dict(on=False, note=0, accent=False, slide=False)
                                       for _ in range(16)]))

    def refresh(self) -> bool:
        m = self.engine.machine
        self.grid.set_playhead(m.current_step if m.playing else -1)
        if m.sync and abs(self.bpm.value() - m.bpm) > 0.04:
            self.bpm.blockSignals(True)
            self.bpm.setValue(m.bpm)
            self.bpm.blockSignals(False)
        if abs(m.bpm - self._acid_bpm) / max(1.0, m.bpm) > 0.004:
            self._acid_bpm = m.bpm
            if not self._acid_timer.isActive():
                self._acid_timer.start(100)
        if self.play_btn.isChecked() != m.playing:
            self.play_btn.blockSignals(True)
            self.play_btn.setChecked(m.playing)
            _set_text(self.play_btn, "■  STOP" if m.playing else "▶  PLAY")
            self.play_btn.blockSignals(False)
        return m.playing


class CrateTree(QTreeWidget):
    """The track list: its rows drag out as real file URLs."""

    def mimeData(self, items):  # noqa: N802
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(item.data(0, Qt.UserRole)) for item in items])
        return data


class SortItem(QTreeWidgetItem):
    """Sorts BPM and length as numbers, not text."""

    def __lt__(self, other) -> bool:
        column = self.treeWidget().sortColumn() if self.treeWidget() else 0
        if column in (1, 2):
            return (self.data(column, Qt.UserRole) or 0) < (other.data(column, Qt.UserRole) or 0)
        return self.text(0).lower() < other.text(0).lower()


class CrateView(QFrame):
    loadRequested = Signal(str, int)            # path, deck (-1 = whichever is free)

    def __init__(self, panel: "DJPanel") -> None:
        super().__init__()
        self.setObjectName("djCard")
        self.panel = panel
        self.files: List[str] = []
        self.items: Dict[str, QTreeWidgetItem] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        top = QHBoxLayout()
        title = QLabel("CRATE")
        title.setObjectName("djTitle")
        top.addWidget(title)
        self.folder = QComboBox()
        self.folder.setObjectName("dj")
        self.folder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.folder.setMinimumWidth(80)
        self.folder.currentIndexChanged.connect(self._scan)
        top.addWidget(self.folder, 1)
        add = _button("+", "Add a music folder")
        add.setFixedWidth(38)
        add.clicked.connect(self._add_folder)
        top.addWidget(add)
        remove = _button("−", "Remove this folder from the list (files stay on disk)")
        remove.setFixedWidth(38)
        remove.clicked.connect(self._remove_folder)
        top.addWidget(remove)
        layout.addLayout(top)
        self.search = QLineEdit()
        self.search.setObjectName("dj")
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.list = CrateTree()
        self.list.setObjectName("djCrate")
        self.list.setColumnCount(3)
        self.list.setHeaderLabels(["TRACK", "BPM", "TIME"])
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setSortingEnabled(True)
        self.list.sortByColumn(0, Qt.AscendingOrder)
        header = self.list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.resizeSection(1, 58)
        header.resizeSection(2, 52)
        self.list.setDragEnabled(True)
        self.list.setDragDropMode(QAbstractItemView.DragOnly)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        # a finger flicks the list; the mouse still drags tracks onto decks
        QScroller.grabGesture(self.list.viewport(), QScroller.TouchGesture)
        self.list.itemDoubleClicked.connect(
            lambda item, _c: self.loadRequested.emit(item.data(0, Qt.UserRole), -1))
        layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        for i, letter in enumerate("AB"):
            btn = _button(f"→ DECK {letter}", f"Load the selected track on deck {letter}")
            btn.setMinimumHeight(SIZE.transport - 4)
            btn.setStyleSheet(f"QPushButton#dj {{ color: {DECK_COLOURS[i]}; }}")
            btn.clicked.connect(lambda _c=False, i=i: self._load_selected(i))
            buttons.addWidget(btn)
        layout.addLayout(buttons)

    def set_folders(self, folders: List[str]) -> None:
        self.folder.blockSignals(True)
        self.folder.clear()
        for folder in folders:
            if os.path.isdir(folder):
                self.folder.addItem(os.path.basename(folder) or folder, folder)
                self.folder.setItemData(self.folder.count() - 1, folder, Qt.ToolTipRole)
        self.folder.blockSignals(False)
        self._scan()

    def folders(self) -> List[str]:
        return [self.folder.itemData(i) for i in range(self.folder.count())]

    def current_folder(self) -> Optional[str]:
        return self.folder.currentData()

    def _add_folder(self) -> None:
        start = self.current_folder() or os.path.expanduser("~/Music")
        path = QFileDialog.getExistingDirectory(self, "Add a music folder", start)
        if path and path not in self.folders():
            self.folder.addItem(os.path.basename(path) or path, path)
            self.folder.setCurrentIndex(self.folder.count() - 1)
            self.panel.save_settings()

    def _remove_folder(self) -> None:
        index = self.folder.currentIndex()
        if index >= 0:
            self.folder.removeItem(index)
            self.panel.save_settings()

    def _scan(self) -> None:
        folder = self.current_folder()
        self.files = []
        if folder and os.path.isdir(folder):
            for root, _dirs, names in os.walk(folder):
                for name in sorted(names, key=str.lower):
                    if de.is_audio(name):
                        self.files.append(os.path.join(root, name))
                if len(self.files) > 3000:
                    break
        self._filter()

    def _fill(self, item: QTreeWidgetItem, path: str) -> None:
        known = self.panel.cache.peek(path)
        bpm = known.get("bpm") if known else None
        length = known.get("duration") if known else None
        item.setText(1, f"{bpm:.1f}" if bpm else "")
        item.setData(1, Qt.UserRole, bpm or 0.0)
        item.setText(2, f"{int(length // 60)}:{int(length % 60):02d}" if length else "")
        item.setData(2, Qt.UserRole, length or 0.0)
        for column in (1, 2):
            item.setTextAlignment(column, Qt.AlignRight | Qt.AlignVCenter)
            item.setForeground(column, QColor(DIM))

    def _filter(self) -> None:
        needle = self.search.text().strip().lower()
        self.list.setSortingEnabled(False)
        self.list.clear()
        self.items = {}
        for path in self.files:
            name = os.path.splitext(os.path.basename(path))[0]
            if needle and needle not in name.lower():
                continue
            item = SortItem([name, "", ""])
            item.setData(0, Qt.UserRole, path)
            item.setToolTip(0, path)
            self._fill(item, path)
            self.list.addTopLevelItem(item)
            self.items[os.path.normcase(path)] = item
        self.list.setSortingEnabled(True)
        if not self.files:
            item = QTreeWidgetItem(["Add a music folder with +", "", ""])
            item.setFlags(Qt.NoItemFlags)
            self.list.addTopLevelItem(item)

    def update_row(self, path: str) -> None:
        item = self.items.get(os.path.normcase(path))
        if item is not None:
            self._fill(item, path)

    def _load_selected(self, deck: int) -> None:
        item = self.list.currentItem()
        if item is not None and item.data(0, Qt.UserRole):
            self.loadRequested.emit(item.data(0, Qt.UserRole), deck)


# --------------------------------------------------------------------------- #
# The page
# --------------------------------------------------------------------------- #

def cache_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "StageDisplayController", "dj_analysis.json")


class DJPanel(QWidget):
    """The whole DJ tab. Starts its audio engine and decoder process on construction."""

    FAST_MS = 16          # while anything moves
    IDLE_MS = 120         # nothing playing, nothing held

    def __init__(self, settings, default_device: Optional[str] = None, touch: bool = False) -> None:
        super().__init__()
        global SIZE
        SIZE = Sizes(touch)
        self.setObjectName("djRoot")
        self.setStyleSheet(_style())
        self.settings = settings
        self.cache = de.AnalysisCache(cache_path())
        self.decoder = de.DecoderClient(self.cache, self)
        self.host = de.EngineHost(de.engine_sample_rate(), self)
        self.engine = self.host.engine
        self.engine.status.connect(self.show_status)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_machine)
        self._restore_machine()
        self.engine.rebuild_drums()
        self.engine.request_acid()
        self._underruns_seen = 0
        self._health_at = 0.0
        self._warn_until = 0.0

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background: {BG}; border: none; }}")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 0)
        root.addWidget(scroll)
        page = QWidget()
        page.setObjectName("djRoot")
        scroll.setWidget(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 4, 2)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.health = QLabel("● AUDIO")
        self.health.setObjectName("djPill")
        bar.addWidget(self.health)
        self.status = QLabel("")
        self.status.setObjectName("djHint")
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        bar.addWidget(self.status, 1)
        out_label = QLabel("OUTPUT")
        out_label.setObjectName("djSmall")
        bar.addWidget(out_label)
        self.out_combo = QComboBox()
        self.out_combo.setObjectName("dj")
        self.out_combo.setMinimumWidth(200)
        bar.addWidget(self.out_combo)
        phones_label = QLabel("HEADPHONES")
        phones_label.setObjectName("djSmall")
        bar.addWidget(phones_label)
        self.phones_combo = QComboBox()
        self.phones_combo.setObjectName("dj")
        self.phones_combo.setMinimumWidth(180)
        bar.addWidget(self.phones_combo)
        layout.addLayout(bar)

        decks = QHBoxLayout()
        decks.setSpacing(10)
        self.crate = None                          # decks refer to it; built below
        self.deck_a = DeckView(self, 0)
        self.mixer = MixerView(self)
        self.deck_b = DeckView(self, 1)
        for deck in (self.deck_a, self.deck_b):
            deck.status.connect(self.show_status)
        decks.addWidget(self.deck_a, 1)
        decks.addWidget(self.mixer)
        decks.addWidget(self.deck_b, 1)
        layout.addLayout(decks, 1)

        lower = QHBoxLayout()
        lower.setSpacing(10)
        self.machine_view = MachineView(self)
        self.crate = CrateView(self)
        self.crate.loadRequested.connect(self._load_from_crate)
        lower.addWidget(self.machine_view, 3)
        lower.addWidget(self.crate, 1)
        layout.addLayout(lower)
        self.crate.setMinimumHeight(self.machine_view.sizeHint().height())

        self._fill_devices(default_device)
        self.out_combo.currentIndexChanged.connect(self._devices_changed)
        self.phones_combo.currentIndexChanged.connect(self._devices_changed)
        self._devices_changed(save=False)
        folders = settings.value("dj/folders", [])
        if isinstance(folders, str):
            folders = [folders]
        if not folders:
            music = os.path.join(os.path.expanduser("~"), "Music")
            folders = [music] if os.path.isdir(music) else []
        self.crate.set_folders(list(folders))

        self._ticker = QTimer(self)
        self._ticker.setTimerType(Qt.PreciseTimer)
        self._ticker.timeout.connect(self._refresh)
        self._ticker.start(self.FAST_MS)

    # -- devices ------------------------------------------------------------ #
    def _fill_devices(self, default_device: Optional[str]) -> None:
        names = [d.description() for d in QMediaDevices.audioOutputs()]
        wanted = self.settings.value("dj/device", "") or default_device or ""
        self.out_combo.addItem("System default", "")
        for name in names:
            self.out_combo.addItem(name, name)
        self.out_combo.setCurrentIndex(max(0, self.out_combo.findData(wanted)))
        phones = self.settings.value("dj/phones", "")
        self.phones_combo.addItem("Off", "")
        for name in names:
            self.phones_combo.addItem(name, name)
        self.phones_combo.setCurrentIndex(max(0, self.phones_combo.findData(phones)))

    def _devices_changed(self, *_args, save: bool = True) -> None:
        main = self.out_combo.currentData() or None
        phones = self.phones_combo.currentData() or None
        if phones and phones == main:
            self.show_status("Headphones and output are the same device - pick a different one "
                             "for headphones.")
            phones = None
        self.engine.set_devices(main, phones)
        if save:
            self.save_settings()

    # -- misc --------------------------------------------------------------- #
    @Slot(str)
    def show_status(self, text: str) -> None:
        _set_text(self.status, text)

    def _load_from_crate(self, path: str, deck: int) -> None:
        if deck < 0:
            a, b = self.engine.decks
            if a.playing and b.playing:
                self.show_status("Both decks are playing - pause one first.")
                return
            deck = 0 if not a.playing and (a.track is None or b.playing) else 1
        (self.deck_a if deck == 0 else self.deck_b).load(path)

    def _refresh(self) -> None:
        if not self.isVisible():
            if self._ticker.interval() != self.IDLE_MS * 4:
                self._ticker.setInterval(self.IDLE_MS * 4)
            return
        moving = self.deck_a.refresh()
        moving = self.deck_b.refresh() or moving
        moving = self.mixer.refresh() or moving
        moving = self.machine_view.refresh() or moving
        self._show_health()
        interval = self.FAST_MS if moving else self.IDLE_MS
        if self._ticker.interval() != interval:
            self._ticker.setInterval(interval)

    def _show_health(self) -> None:
        now = time.monotonic()
        if now - self._health_at < 0.5:
            return
        self._health_at = now
        engine = self.engine
        if engine.underruns > self._underruns_seen:
            self._underruns_seen = engine.underruns
            self._warn_until = now + 6.0
        latency = int(round((engine.queued / engine.sr) * 1000)) if engine.sr else 0
        if now < self._warn_until:
            text, colour = "● DROPOUT", WARN
            tip = "The sound card ran dry - something else is keeping the computer busy."
        else:
            text, colour = f"● AUDIO  {latency} ms", OK
            tip = "Sound is flowing. The figure is how far the sound card runs behind the screen."
        if self.health.text() != text:
            self.health.setText(text)
            self.health.setToolTip(tip)
            self.health.setStyleSheet(f"color: {colour}; background: {_alpha(colour, 30).name(QColor.HexArgb)};")

    # -- persistence -------------------------------------------------------- #
    def save_settings(self) -> None:
        self.settings.setValue("dj/folders", self.crate.folders())
        self.settings.setValue("dj/device", self.out_combo.currentData() or "")
        self.settings.setValue("dj/phones", self.phones_combo.currentData() or "")

    def save_machine_later(self) -> None:
        self._save_timer.start(800)

    def save_machine(self) -> None:
        m = self.engine.machine
        state = dict(rows=m.rows, acid=m.acid, params=m.params, key=m.key, bpm=m.bpm,
                     swing=m.swing, mutes=sorted(m.mutes))
        self.settings.setValue("dj/machine", json.dumps(state))

    def _restore_machine(self) -> None:
        raw = self.settings.value("dj/machine", "")
        if not raw:
            return
        try:
            state = json.loads(raw)
            m = self.engine.machine
            rows = state.get("rows", {})
            if all(len(rows.get(row, [])) == 16 for row in de.ROWS):
                m.rows = {row: [int(v) for v in rows[row]] for row in de.ROWS}
            acid = state.get("acid", [])
            if len(acid) == 16:
                m.acid = [dict(on=bool(s.get("on")), note=int(s.get("note", 0)),
                               accent=bool(s.get("accent")), slide=bool(s.get("slide")))
                          for s in acid]
            for key, value in state.get("params", {}).items():
                if key in m.params:
                    m.params[key] = float(value)
            m.key = int(state.get("key", m.key)) % 12
            m.bpm = float(state.get("bpm", m.bpm))
            m.swing = float(state.get("swing", m.swing))
            m.mutes = set(state.get("mutes", []))
        except (ValueError, TypeError, AttributeError):
            pass

    def shutdown(self) -> None:
        self._ticker.stop()
        self.save_machine()
        self.save_settings()
        self.host.stop()
        self.decoder.stop()
