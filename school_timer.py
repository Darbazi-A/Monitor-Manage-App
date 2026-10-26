"""
The school timer: a countdown (or a stopwatch, a countdown to a time of day, or
just the clock) on a stage screen - full screen in the school's own look, or a
box in a corner over whatever the screen shows, or a band along the bottom.

Its look follows the European School timer made for the hall: deep blue with a
soft glow, the school's logo, the clock in the corner, the name in gold, large
light digits and a thin gold line that fills as the time runs; red, counting
on with a "+", once the time is up. Other looks sit beside it: black, light,
bold, a ring, and glass over the picture.

    TimerClock    the time itself: start, pause, reset, add a minute, modes
    paint_timer   one painter for every look and size - the stage, the
                  preview on the desk and the look buttons all use it
    TimerItem     the timer as a layer of a stage window's scene, above
                  everything (a dissolve underneath does not disturb it)
    TimerPage     the desk's page (the simple desk has it too)

Kept free of main.py imports: the dashboard owns a TimerClock and a TimerPage
and tells the stage windows what to draw.
"""
from __future__ import annotations

from i18n import tr  # noqa: E402 - the interface's language

import math
import os
import struct
import time
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTime, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QFontMetricsF, QIcon, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QGraphicsObject,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
                               QSpinBox, QTimeEdit, QToolButton, QVBoxLayout, QWidget)

MODES = (("countdown", "Countdown"), ("until", "Until a time"), ("stopwatch", "Stopwatch"), ("clock", "Clock"))
STYLES = (("school", "School"), ("black", "Black"), ("light", "Light"), ("bold", "Bold"), ("ring", "Ring"),
          ("glass", "Over the picture"))
SIZES = (("full", "Full screen"), ("large", "Large"), ("medium", "Medium"), ("small", "Small"), ("strip", "Band"))
POSITIONS = (("br", "↘"), ("bl", "↙"), ("tr", "↗"), ("tl", "↖"), ("c", "●"))
WARNINGS = ((0, "no warning"), (60, "last minute"), (120, "last 2 minutes"), (300, "last 5 minutes"))
OVERTIMES = (("count", "counts on, red (+)"), ("stop", "stops at 0:00"), ("flash", "0:00, flashing"))
SOUNDS = (("beeps", "three beeps"), ("off", "silent"))
PRESET_MINUTES = (1, 2, 3, 5, 10, 15, 20, 30, 45, 60)

DEFAULT_LOOK = {"style": "school", "size": "full", "position": "br", "clock": True, "logo": True, "bar": True,
                "title": True, "warn": 60, "overtime": "count", "sound": "beeps"}


def default_logo() -> str:
    """The school's logo, kept with the app's own files (taken from the hall's timer page)."""
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                        "StageDisplayController", "timer_logo.png")


def clean_look(look: Optional[dict]) -> dict:
    """A look with every key, every value one the painter knows."""
    result = dict(DEFAULT_LOOK)
    for key, value in (look or {}).items():
        if key in result:
            result[key] = value
    allowed = {"style": dict(STYLES), "size": dict(SIZES), "position": dict(POSITIONS),
               "overtime": dict(OVERTIMES), "sound": dict(SOUNDS)}
    for key, options in allowed.items():
        if result[key] not in options:
            result[key] = DEFAULT_LOOK[key]
    for key in ("clock", "logo", "bar", "title"):
        result[key] = bool(result[key])
    try:
        result["warn"] = max(0, int(result["warn"]))
    except (TypeError, ValueError):
        result["warn"] = DEFAULT_LOOK["warn"]
    return result


def format_ms(ms: float, plus: bool = True, up: bool = False) -> str:
    """10:00, 1:05:00, +0:12 - counting down, a second shows until it is over (like a kitchen
    timer); counting up (`up`), only once it is complete."""
    over = ms < 0
    if over:
        total = int(math.floor(-ms / 1000))
    else:
        total = int(math.floor(ms / 1000)) if up else int(math.ceil(ms / 1000 - 1e-6))
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    text = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
    return ("+" + text) if over and plus else text


# --------------------------------------------------------------------------- #
# The time
# --------------------------------------------------------------------------- #

class TimerClock(QObject):
    """
    The timer's time, whatever it is drawn on. Countdown and stopwatch can be
    paused; "until" counts down to a time of day; "clock" is the time now.
    """

    changed = Signal()
    reachedZero = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.mode = "countdown"
        self.title = ""
        self.duration_ms = 10 * 60 * 1000
        self.until = QTime(11, 0)
        self.running = False
        self._left_ms = float(self.duration_ms)     # countdown, while stopped
        self._ends_at = 0.0                          # countdown, while running (monotonic)
        self._elapsed_ms = 0.0                       # stopwatch, while stopped
        self._started_at = 0.0                       # stopwatch, while running
        self._until_from = time.time()               # "until": when it was set, for the line's length
        self._zero_fired = False

    # -- reading it ------------------------------------------------------------- #
    def left_ms(self) -> float:
        if self.mode == "until":
            return self._until_target() - time.time() * 1000
        if self.running:
            return (self._ends_at - time.monotonic()) * 1000
        return self._left_ms

    def elapsed_ms(self) -> float:
        if self.running:
            return (time.monotonic() - self._started_at) * 1000
        return self._elapsed_ms

    def _until_target(self) -> float:
        """The chosen time of day, as epoch milliseconds - today, or tomorrow if it is long gone."""
        now = time.localtime()
        target = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, self.until.hour(), self.until.minute(),
                              self.until.second(), 0, 0, -1))
        if target < time.time() - 12 * 3600:
            target += 24 * 3600
        return target * 1000

    def is_counting_down(self) -> bool:
        return self.mode in ("countdown", "until")

    def frame(self, look: Optional[dict] = None) -> dict:
        """Everything the painter needs for this moment."""
        look = clean_look(look)
        now = time.localtime()
        frame = {"mode": self.mode, "title": self.title, "running": self.running or self.mode in ("until", "clock"),
                 "clock": f"{now.tm_hour:02d}:{now.tm_min:02d}", "fraction": None, "state": "running"}
        if self.mode == "clock":
            frame["text"] = f"{now.tm_hour:02d}:{now.tm_min:02d}:{now.tm_sec:02d}"
            frame["state"] = "running"
            return frame
        if self.mode == "stopwatch":
            frame["text"] = format_ms(self.elapsed_ms(), up=True)
            frame["state"] = "running" if self.running else ("idle" if self._elapsed_ms == 0 else "paused")
            return frame
        left = self.left_ms()
        if self.mode == "until":
            total = max(1000.0, self._until_target() - self._until_from * 1000)
        else:
            total = max(1000.0, float(self.duration_ms))
        over = left <= 0
        if over:
            frame["text"] = format_ms(left) if look["overtime"] == "count" else "00:00"
            frame["state"] = "over"
        else:
            frame["text"] = format_ms(left)
            warn = look["warn"] * 1000
            if not frame["running"]:
                frame["state"] = "idle" if abs(left - total) < 1 and self.mode == "countdown" else "paused"
            elif warn and left <= warn:
                frame["state"] = "warn"
        frame["fraction"] = min(1.0, max(0.0, 1 - left / total))
        frame["flash"] = over and look["overtime"] == "flash"
        return frame

    # -- changing it ---------------------------------------------------------------- #
    def set_mode(self, mode: str) -> None:
        if mode in dict(MODES) and mode != self.mode:
            self.pause()
            self.mode = mode
            self.reset()

    def set_duration(self, ms: int) -> None:
        """A new time: ready at the top, waiting for Start."""
        self.running = False
        self.duration_ms = max(1000, int(ms))
        self.reset()

    def set_until(self, when: QTime) -> None:
        self.until = QTime(when)
        self._until_from = time.time()
        self._zero_fired = self.left_ms() <= 0
        self.changed.emit()

    def start(self) -> None:
        if self.running or self.mode in ("until", "clock"):
            return
        if self.mode == "countdown":
            if self._left_ms <= 0:
                self._left_ms = float(self.duration_ms)
                self._zero_fired = False
            self._ends_at = time.monotonic() + self._left_ms / 1000
        else:
            self._started_at = time.monotonic() - self._elapsed_ms / 1000
        self.running = True
        self.changed.emit()

    def pause(self) -> None:
        if not self.running:
            return
        if self.mode == "countdown":
            self._left_ms = self.left_ms()
        elif self.mode == "stopwatch":
            self._elapsed_ms = self.elapsed_ms()
        self.running = False
        self.changed.emit()

    def toggle(self) -> None:
        (self.pause if self.running else self.start)()

    def reset(self) -> None:
        """Back to the full time (a running countdown runs on from the top)."""
        self._zero_fired = False
        if self.mode == "countdown":
            self._left_ms = float(self.duration_ms)
            self._ends_at = time.monotonic() + self.duration_ms / 1000
        elif self.mode == "stopwatch":
            self._elapsed_ms = 0.0
            self._started_at = time.monotonic()
        elif self.mode == "until":
            self._until_from = time.time()
            self._zero_fired = self.left_ms() <= 0
        self.changed.emit()

    def add(self, ms: int) -> None:
        """A minute more (or less) - the line keeps its sense: the whole grows with it."""
        if self.mode != "countdown":
            return
        if self.running:
            self._ends_at += ms / 1000
        else:
            self._left_ms += ms
        self.duration_ms = max(1000, self.duration_ms + ms)
        if self.left_ms() > 0:
            self._zero_fired = False
        self.changed.emit()

    def poll(self) -> None:
        """Called a few times a second: says when the time has just run out."""
        if self.is_counting_down() and not self._zero_fired and self.left_ms() <= 0 \
                and (self.running or self.mode == "until"):
            self._zero_fired = True
            self.reachedZero.emit()

    # -- remembering it ---------------------------------------------------------------- #
    def to_dict(self) -> dict:
        return {"mode": self.mode, "title": self.title, "duration": self.duration_ms,
                "until": self.until.toString("HH:mm")}

    def load(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        self.title = str(data.get("title", ""))[:120]
        if data.get("mode") in dict(MODES):
            self.mode = data["mode"]
        try:
            self.duration_ms = max(1000, int(data.get("duration", self.duration_ms)))
        except (TypeError, ValueError):
            pass
        until = QTime.fromString(str(data.get("until", "")), "HH:mm")
        if until.isValid():
            self.until = until
        self.running = False
        self.reset()


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #

PALETTES = {
    #          ground top, ground mid, ground bottom, glow,      ink,       soft,              accent,    warn,      over,      track
    "school": ("#0f2a58", "#0b1f43", "#061529", "#1b4590", "#ffffff", (255, 255, 255, 150), "#f8c96b", "#f8c96b", "#ff9a9a", (255, 255, 255, 36)),
    "black": ("#000000", "#000000", "#000000", None, "#ffffff", (255, 255, 255, 130), "#ffffff", "#ffb02e", "#ff5a52", (255, 255, 255, 40)),
    "light": ("#ffffff", "#f1f4f9", "#e3e9f2", None, "#0b1f43", (11, 31, 67, 150), "#1b4590", "#c76a00", "#c62828", (11, 31, 67, 36)),
    "bold": ("#15191f", "#111418", "#0b0d10", None, "#ffffff", (255, 255, 255, 140), "#3ddc84", "#ffc233", "#ff4d4d", (255, 255, 255, 30)),
    "ring": ("#14213d", "#0c1426", "#070b14", "#24407a", "#ffffff", (255, 255, 255, 140), "#f8c96b", "#ffb347", "#ff7a7a", (255, 255, 255, 34)),
    "glass": (None, None, None, None, "#ffffff", (255, 255, 255, 170), "#f8c96b", "#ffc04d", "#ff8a80", (255, 255, 255, 50)),
}
_family_cache: Dict[str, str] = {}


def _family(kind: str) -> str:
    """The best font this PC has: Segoe UI Variable on Windows 11, Segoe UI otherwise."""
    if kind not in _family_cache:
        families = set(QFontDatabase.families())
        wanted = {"digits": ("Segoe UI Variable Display", "Segoe UI", "Arial"),
                  "text": ("Segoe UI Variable Display", "Segoe UI", "Noto Sans Georgian", "Arial")}[kind]
        _family_cache[kind] = next((f for f in wanted if f in families), wanted[-1])
    return _family_cache[kind]


def _font(kind: str, pixels: float, weight: QFont.Weight) -> QFont:
    font = QFont(_family(kind))
    # Segoe UI Variable has no Georgian letters; left to itself Qt borrows them from
    # whatever font comes first (a decorative one) - Segoe UI, then Sylfaen, have them
    font.setFamilies([_family(kind), "Segoe UI", "Sylfaen"])
    font.setPixelSize(max(1, int(pixels)))
    font.setWeight(weight)
    font.setHintingPreference(QFont.PreferNoHinting)
    return font


def _colour(value) -> QColor:
    return QColor(*value) if isinstance(value, tuple) else QColor(value)


def _digit_weight(style: str) -> QFont.Weight:
    return {"school": QFont.ExtraLight, "black": QFont.Light, "light": QFont.Light, "bold": QFont.Black,
            "ring": QFont.Light, "glass": QFont.Normal}.get(style, QFont.Light)


def draw_digits(p: QPainter, text: str, box: QRectF, colour: QColor, weight: QFont.Weight,
                align: Qt.AlignmentFlag = Qt.AlignCenter, shadow: bool = False) -> None:
    """
    The time, as large as fits - each digit in a cell of the same width, so
    nothing jumps as the seconds change, and the size stays put while they do.
    """
    if not text or box.width() < 2 or box.height() < 2:
        return
    reference = _font("digits", 100, weight)
    metrics = QFontMetricsF(reference)
    cell = max(metrics.horizontalAdvance(d) for d in "0123456789")
    widths = {":": metrics.horizontalAdvance(":") * 0.92, "+": metrics.horizontalAdvance("+")}
    total = sum(widths.get(ch, cell) for ch in text)
    digit_height = metrics.tightBoundingRect("0").height()
    scale = min(box.width() / max(1.0, total), box.height() / max(1.0, digit_height))
    font = _font("digits", 100 * scale, weight)
    p.setFont(font)
    cell *= scale
    widths = {k: v * scale for k, v in widths.items()}
    width = total * scale
    height = digit_height * scale
    if align & Qt.AlignLeft:
        x = box.left()
    elif align & Qt.AlignRight:
        x = box.right() - width
    else:
        x = box.center().x() - width / 2
    baseline = box.center().y() + height / 2
    for ch in text:
        w = widths.get(ch, cell)
        advance = QFontMetricsF(font).horizontalAdvance(ch)
        at = QPointF(x + (w - advance) / 2, baseline - (height * 0.06 if ch == ":" else 0))
        if shadow:
            p.setPen(QColor(0, 0, 0, 150))
            p.drawText(at + QPointF(0, max(1.0, height * 0.025)), ch)
        p.setPen(colour)
        p.drawText(at, ch)
        x += w


def _text(p: QPainter, text: str, box: QRectF, colour: QColor, weight: QFont.Weight, align, shadow=False) -> None:
    if not text or box.height() < 4:
        return
    size = box.height()
    font = _font("text", size, weight)
    metrics = QFontMetricsF(font)
    while metrics.horizontalAdvance(text) > box.width() and size > 8:
        size *= 0.9
        font = _font("text", size, weight)
        metrics = QFontMetricsF(font)
    shown = metrics.elidedText(text, Qt.ElideRight, box.width())
    p.setFont(font)
    if shadow:
        p.setPen(QColor(0, 0, 0, 150))
        p.drawText(box.translated(0, max(1.0, size * 0.04)), align | Qt.AlignVCenter, shown)
    p.setPen(colour)
    p.drawText(box, align | Qt.AlignVCenter, shown)


def _ground(p: QPainter, area: QRectF, style: str, palette, radius: float) -> None:
    """The look's background over `area` (rounded when it is a box)."""
    path = QPainterPath()
    if radius > 0:
        path.addRoundedRect(area, radius, radius)
    else:
        path.addRect(area)
    if style == "glass":
        p.fillPath(path, QColor(0, 0, 0, 150 if radius > 0 else 90))
    else:
        top, mid, bottom, glow = palette[0], palette[1], palette[2], palette[3]
        gradient = QLinearGradient(area.topLeft(), area.bottomRight())
        gradient.setColorAt(0.0, QColor(top))
        gradient.setColorAt(0.52, QColor(mid))
        gradient.setColorAt(1.0, QColor(bottom))
        p.fillPath(path, gradient)
        if glow:
            radial = QRadialGradient(QPointF(area.center().x(), area.top() - area.height() * 0.12),
                                     max(area.width(), area.height()) * 0.62)
            light = QColor(glow)
            light.setAlpha(230)
            radial.setColorAt(0.0, light)
            light.setAlpha(0)
            radial.setColorAt(1.0, light)
            p.fillPath(path, radial)
    if radius > 0:
        p.setPen(QPen(QColor(255, 255, 255, 40) if style != "light" else QColor(11, 31, 67, 40), max(1.0, radius * 0.06)))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


def timer_area(rect: QRectF, look: dict) -> Tuple[QRectF, float]:
    """Where the timer goes on the screen, and the corner radius of its box (0 = full screen)."""
    size = look["size"]
    wide = rect.width() / max(1.0, rect.height()) > 4          # the ceiling strip
    if size == "full":
        return QRectF(rect), 0.0
    if wide:
        share = {"large": 0.42, "medium": 0.32, "small": 0.22, "strip": 1.0}[size]
        width = rect.width() * share
        x = {"tl": rect.left(), "bl": rect.left(), "c": rect.center().x() - width / 2}.get(look["position"], rect.right() - width)
        return QRectF(x, rect.top(), width, rect.height()), 0.0
    margin = min(rect.width(), rect.height()) * 0.035
    if size == "strip":
        height = rect.height() * 0.16
        top = look["position"] in ("tl", "tr")
        y = rect.top() + margin if top else rect.bottom() - height - margin
        return QRectF(rect.left() + margin, y, rect.width() - 2 * margin, height), height * 0.18
    share = {"large": 0.46, "medium": 0.32, "small": 0.21}[size]
    width = rect.width() * share
    height = width * 0.5
    position = look["position"]
    x = rect.left() + margin if position in ("tl", "bl") else rect.right() - width - margin
    y = rect.top() + margin if position in ("tl", "tr") else rect.bottom() - height - margin
    if position == "c":
        x, y = rect.center().x() - width / 2, rect.center().y() - height / 2
    return QRectF(x, y, width, height), height * 0.1


def paint_timer(p: QPainter, rect: QRectF, frame: dict, look: dict, logo: Optional[QPixmap] = None) -> None:
    """The whole timer, in `rect` (the screen), as `look` says - used for the stage and every preview."""
    look = clean_look(look)
    style = look["style"]
    palette = PALETTES[style]
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    area, radius = timer_area(rect, look)
    _ground(p, area, style, palette, radius)

    state = frame.get("state", "running")
    ink = QColor(palette[4])
    accent = QColor(palette[6])
    colour = {"warn": QColor(palette[7]), "over": QColor(palette[8])}.get(state, ink)
    if style == "bold" and state in ("running", "idle", "paused"):
        colour = ink
    soft = _colour(palette[5])
    track = _colour(palette[9])
    blink_off = frame.get("flash") and int(time.monotonic() * 2) % 2 == 1
    shadow = style == "glass"
    weight = _digit_weight(style)
    title = frame.get("title", "") if look["title"] else ""
    fraction = frame.get("fraction")
    bar = look["bar"] and fraction is not None and style != "ring"
    line_colour = QColor(palette[8]) if state == "over" else (QColor(palette[7]) if state == "warn" else accent)
    pad = min(area.width(), area.height()) * (0.06 if radius else 0.045)
    inner = area.adjusted(pad, pad * 0.8, -pad, -pad * 0.8)
    line_layout = inner.width() / max(1.0, inner.height()) > 3.2

    if line_layout:
        # one row: [logo] title ........ time [clock], the line along the bottom
        x = inner.left()
        if look["logo"] and logo is not None and not logo.isNull() and look["size"] in ("full", "strip", "large"):
            h = inner.height() * 0.86
            w = h * logo.width() / max(1, logo.height())
            p.drawPixmap(QRectF(x, inner.center().y() - h / 2, w, h).toRect(), logo)
            x += w + pad
        clock_w = 0.0
        if look["clock"] and frame.get("mode") != "clock" and look["size"] in ("full", "strip"):
            clock_w = inner.height() * 1.7
            _text(p, frame.get("clock", ""), QRectF(inner.right() - clock_w, inner.top(), clock_w, inner.height() * 0.45),
                  soft, QFont.Normal, Qt.AlignRight)
        time_w = (inner.right() - clock_w - x) * (0.55 if title else 1.0)
        time_box = QRectF(inner.right() - clock_w - time_w - (pad * 0.5 if clock_w else 0), inner.top(),
                          time_w, inner.height() * (0.86 if bar else 1.0))
        if title:
            _text(p, title, QRectF(x, inner.center().y() - inner.height() * 0.25, time_box.left() - x - pad, inner.height() * 0.5),
                  accent if style != "light" else accent, QFont.DemiBold, Qt.AlignLeft, shadow)
        if not blink_off:
            draw_digits(p, frame.get("text", ""), time_box, colour, weight, Qt.AlignRight if title else Qt.AlignCenter, shadow)
        if bar:
            _bar(p, QRectF(area.left(), area.bottom() - max(2.0, area.height() * 0.05), area.width(), max(2.0, area.height() * 0.05)),
                 fraction, track, line_colour, style)
        p.restore()
        return

    # stacked: head (logo, clock), title, the time, the line
    full = look["size"] == "full"
    head_h = inner.height() * (0.085 if full else 0.0)
    y = inner.top()
    if full and look["logo"] and logo is not None and not logo.isNull():
        h = head_h * 1.25
        w = h * logo.width() / max(1, logo.height())
        p.drawPixmap(QRectF(inner.left(), y, w, h).toRect(), logo)
    if full and look["clock"] and frame.get("mode") != "clock":
        _text(p, frame.get("clock", ""), QRectF(inner.right() - inner.width() * 0.3, y, inner.width() * 0.3, head_h * 0.55),
              soft, QFont.Normal, Qt.AlignRight)
    body = QRectF(inner.left(), y + head_h, inner.width(), inner.height() - head_h)
    if not full and look["clock"] and frame.get("mode") != "clock" and look["size"] == "large":
        _text(p, frame.get("clock", ""), QRectF(inner.right() - inner.width() * 0.3, inner.top(), inner.width() * 0.3, inner.height() * 0.11),
              soft, QFont.Normal, Qt.AlignRight)

    if style == "ring":
        title_h = body.height() * (0.09 if title else 0)
        if title:
            _text(p, title, QRectF(body.left(), body.top(), body.width(), title_h), accent, QFont.DemiBold, Qt.AlignHCenter)
        ring_box = body.adjusted(0, title_h + body.height() * 0.03, 0, 0)
        diameter = min(ring_box.width(), ring_box.height()) * 0.94
        circle = QRectF(ring_box.center().x() - diameter / 2, ring_box.center().y() - diameter / 2, diameter, diameter)
        thick = max(2.0, diameter * 0.045)
        p.setPen(QPen(track, thick, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(circle.adjusted(thick / 2, thick / 2, -thick / 2, -thick / 2))
        if fraction is not None:
            p.setPen(QPen(line_colour, thick, Qt.SolidLine, Qt.RoundCap))
            span = -int(360 * 16 * (1 - fraction)) if state != "over" else -360 * 16
            p.drawArc(circle.adjusted(thick / 2, thick / 2, -thick / 2, -thick / 2), 90 * 16, span)
        if not blink_off:
            side = diameter * 0.62
            draw_digits(p, frame.get("text", ""), QRectF(circle.center().x() - side / 2, circle.center().y() - side * 0.2,
                                                         side, side * 0.4), colour, weight)
        p.restore()
        return

    title_h = body.height() * ((0.085 if full else 0.16) if title else 0)
    bar_h = body.height() * (0.12 if bar else 0.02)
    time_h = body.height() - title_h - bar_h
    if title:
        _text(p, title, QRectF(body.left(), body.top() + body.height() * (0.12 if full else 0.0), body.width(), title_h),
              accent, QFont.DemiBold, Qt.AlignHCenter, shadow)
    time_box = QRectF(body.left(), body.top() + title_h + (body.height() * 0.1 if full and title else 0), body.width(),
                      time_h * (0.48 if full else 0.92))       # full screen: about a third of its height
    if full:
        time_box.moveCenter(QPointF(body.center().x(), body.top() + title_h + time_h * 0.52 + (body.height() * 0.05 if title else 0)))
    if not blink_off:
        draw_digits(p, frame.get("text", ""), time_box, colour, weight, Qt.AlignCenter, shadow)
    if bar:
        width = body.width() * (0.84 if full else 1.0)
        thick = max(2.0, body.height() * (0.006 if style in ("school", "black", "light", "glass") else 0.03)) if full \
            else max(2.0, body.height() * (0.03 if style == "bold" else 0.018))
        y_bar = time_box.bottom() + body.height() * (0.07 if full else 0.03)
        _bar(p, QRectF(body.center().x() - width / 2, y_bar, width, thick), fraction, track, line_colour, style)
    p.restore()


def _bar(p: QPainter, box: QRectF, fraction: float, track: QColor, colour: QColor, style: str) -> None:
    radius = box.height() / 2 if style == "bold" else 0
    p.setPen(Qt.NoPen)
    p.setBrush(track)
    p.drawRoundedRect(box, radius, radius)
    done = QRectF(box.left(), box.top(), box.width() * max(0.0, min(1.0, fraction)), box.height())
    p.setBrush(colour)
    p.drawRoundedRect(done, radius, radius)


def sample_frame(title: str = "") -> dict:
    """A moment to draw the look buttons and an empty preview with."""
    now = time.localtime()
    return {"mode": "countdown", "title": title, "running": True, "clock": f"{now.tm_hour:02d}:{now.tm_min:02d}",
            "text": "05:00", "fraction": 0.42, "state": "running", "flash": False}


def look_picture(look: dict, size: QSize, logo: Optional[QPixmap], title: str) -> QPixmap:
    """A small picture of a look over a stand-in stage picture."""
    pixmap = QPixmap(size)
    pixmap.fill(QColor("#05070b"))
    p = QPainter(pixmap)
    stand_in = QLinearGradient(0, 0, size.width(), size.height())
    stand_in.setColorAt(0, QColor("#3a2a52"))
    stand_in.setColorAt(1, QColor("#1d3a4a"))
    p.fillRect(pixmap.rect(), stand_in)
    paint_timer(p, QRectF(0, 0, size.width(), size.height()), sample_frame(title), look, logo)
    p.end()
    return pixmap


def beeps_wav() -> bytes:
    """Three short beeps (880 Hz) - the signal the hall's timer page made, as a WAV file."""
    rate = 44100
    samples = bytearray()
    length = int(rate * 1.3)
    for i in range(length):
        t = i / rate
        value = 0.0
        for start in (0.0, 0.45, 0.9):
            local = t - start
            if 0 <= local < 0.35:
                envelope = min(1.0, local / 0.03) * math.exp(-local * 9)
                value += 0.3 * envelope * math.sin(2 * math.pi * 880 * local)
        samples += struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32000))
    header = b"RIFF" + struct.pack("<I", 36 + len(samples)) + b"WAVEfmt " + struct.pack(
        "<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(samples))
    return header + bytes(samples)


# --------------------------------------------------------------------------- #
# On a stage screen
# --------------------------------------------------------------------------- #

class TimerItem(QGraphicsObject):
    """The timer as one layer of a stage window's scene, over everything else."""

    def __init__(self) -> None:
        super().__init__()
        self._rect = QRectF(0, 0, 1, 1)
        self.look = dict(DEFAULT_LOOK)
        self.frame = sample_frame()
        self.logo: Optional[QPixmap] = None
        self.setZValue(60)

    def set_rect(self, rect: QRectF) -> None:
        if rect != self._rect:
            self.prepareGeometryChange()
            self._rect = QRectF(rect)

    def set_state(self, look: dict, frame: dict, logo: Optional[QPixmap]) -> bool:
        """True when what is drawn changes (the screen's picture then counts as changed)."""
        changed = (look != self.look or frame.get("text") != self.frame.get("text")
                   or frame.get("state") != self.frame.get("state") or logo is not self.logo
                   or frame.get("title") != self.frame.get("title") or frame.get("clock") != self.frame.get("clock"))
        moved = round(frame.get("fraction") or 0, 3) != round(self.frame.get("fraction") or 0, 3) or frame.get("flash")
        self.look, self.frame, self.logo = dict(look), dict(frame), logo
        if changed or moved:
            self.update()
        return changed

    def boundingRect(self) -> QRectF:  # noqa: N802
        return self._rect

    def paint(self, painter: QPainter, _option, _widget=None) -> None:
        paint_timer(painter, self._rect, self.frame, self.look, self.logo)


# --------------------------------------------------------------------------- #
# The desk's page
# --------------------------------------------------------------------------- #

class TimerPreview(QWidget):
    """The screen with its timer: the real screen while it is up, a sketch until then."""

    def __init__(self) -> None:
        super().__init__()
        self.picture: Optional[QPixmap] = None
        self.aspect = 16 / 9
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def show_picture(self, picture: Optional[QPixmap], aspect: float) -> None:
        self.picture, self.aspect = picture, aspect
        self.update()

    def screen_rect(self) -> QRectF:
        width, height = self.width() - 2, self.height() - 2
        if width / max(1, height) > self.aspect:
            w = height * self.aspect
            return QRectF(1 + (width - w) / 2, 1, w, height)
        h = width / self.aspect
        return QRectF(1, 1 + (height - h) / 2, width, h)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        box = self.screen_rect()
        p.fillRect(box, QColor("#05070b"))
        if self.picture is not None and not self.picture.isNull():
            p.drawPixmap(box.toRect(), self.picture)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(box)


class TimerPage(QWidget):
    """
    The Timer page: what to count, its look, which screen - and the buttons
    a teacher needs while it runs. The simple desk shows it as it is.
    """

    showRequested = Signal(str)          # a screen
    hideRequested = Signal()
    lookChanged = Signal(dict)
    logoRequested = Signal()

    def __init__(self, clock: TimerClock, icons, theme: dict, roles: List[Tuple[str, str]]) -> None:
        super().__init__()
        self.clock = clock
        self.icons = icons
        self.theme = theme
        self.roles = roles
        self.look = dict(DEFAULT_LOOK)
        self.logo: Optional[QPixmap] = None
        self.on_screen = ""                 # the screen the timer is on, "" = none
        self._syncing = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(12)
        heading = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel(tr("Timer"))
        title.setObjectName("pageTitle")
        titles.addWidget(title)
        lead = QLabel(tr("A countdown on a stage screen - for a speech, a test, a break. Set it here, then show it."))
        lead.setObjectName("pageLead")
        lead.setWordWrap(True)
        titles.addWidget(lead)
        heading.addLayout(titles, 1)
        outer.addLayout(heading)

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._build_time_card())
        middle = QVBoxLayout()
        middle.setSpacing(10)
        self.preview = TimerPreview()
        middle.addWidget(self.preview, 1)
        middle.addWidget(self._build_run_row())
        middle.addWidget(self._build_screen_row())
        body.addLayout(middle, 1)
        outer.addLayout(body, 3)
        outer.addWidget(self._build_look_card())

        clock.changed.connect(self.refresh)
        self.refresh()

    # -- building ------------------------------------------------------------------- #
    def _card(self, heading: str) -> Tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 14)
        box.setSpacing(8)
        caption = QLabel(heading)
        caption.setObjectName("sectionTitle")
        box.addWidget(caption)
        return card, box

    def _chips(self, options, on_pick, wrap: int = 0) -> Tuple[QWidget, QButtonGroup]:
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        group = QButtonGroup(holder)
        group.setExclusive(True)
        for index, (value, label) in enumerate(options):
            button = QPushButton(tr(label) if isinstance(label, str) and not label.isdigit() else str(label))
            button.setCheckable(True)
            button.setProperty("value", value)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda _c=False, v=value: on_pick(v))
            group.addButton(button)
            row, column = (divmod(index, wrap) if wrap else (0, index))
            grid.addWidget(button, row, column)
        return holder, group

    @staticmethod
    def _check(group: QButtonGroup, value) -> None:
        for button in group.buttons():
            want = button.property("value") == value
            if button.isChecked() != want:
                button.setChecked(want)

    def _build_time_card(self) -> QWidget:
        card, box = self._card(tr("WHAT IT COUNTS"))
        card.setFixedWidth(430)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText(tr("Name on the screen (optional) - e.g. Mathematics test"))
        self.title_edit.setMaxLength(80)
        self.title_edit.textChanged.connect(self._on_title)
        box.addWidget(self.title_edit)
        modes, self.mode_group = self._chips(MODES, self._on_mode, wrap=2)
        box.addWidget(modes)

        self.duration_box = QWidget()
        duration = QVBoxLayout(self.duration_box)
        duration.setContentsMargins(0, 4, 0, 0)
        duration.setSpacing(8)
        dial = QHBoxLayout()
        dial.setSpacing(6)
        self.spins = []
        for maximum, suffix in ((23, tr(" h")), (59, tr(" min")), (59, tr(" s"))):
            spin = QSpinBox()
            spin.setRange(0, maximum)
            spin.setSuffix(suffix)
            spin.setMinimumHeight(48)
            spin.setStyleSheet("font-size: 22px; font-weight: 600;")
            spin.valueChanged.connect(self._on_dial)
            dial.addWidget(spin)
            self.spins.append(spin)
        duration.addLayout(dial)
        presets, self.preset_group = self._chips([(m, f"{m} {tr('min')}") for m in PRESET_MINUTES],
                                                 lambda minutes: self._set_duration(minutes * 60000), wrap=5)
        duration.addWidget(presets)
        box.addWidget(self.duration_box)

        self.until_box = QWidget()
        until = QHBoxLayout(self.until_box)
        until.setContentsMargins(0, 4, 0, 0)
        caption = QLabel(tr("Counts down to"))
        until.addWidget(caption)
        self.until_edit = QTimeEdit()
        self.until_edit.setDisplayFormat("HH:mm")
        self.until_edit.setMinimumHeight(48)
        self.until_edit.setStyleSheet("font-size: 22px; font-weight: 600;")
        self.until_edit.timeChanged.connect(self._on_until)
        until.addWidget(self.until_edit, 1)
        box.addWidget(self.until_box)

        self.mode_note = QLabel("")
        self.mode_note.setObjectName("cardHint")
        self.mode_note.setWordWrap(True)
        box.addWidget(self.mode_note)
        box.addStretch(1)
        return card

    def _build_run_row(self) -> QWidget:
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.start_btn = QPushButton()
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumHeight(52)
        self.start_btn.setStyleSheet("font-size: 17px; font-weight: 700;")
        self.start_btn.clicked.connect(self.clock.toggle)
        row.addWidget(self.start_btn, 3)
        self.reset_btn = QPushButton(tr("  From the top"))
        self.reset_btn.setIcon(self.icons.get("refresh", self.theme["text"], 16))
        self.reset_btn.setMinimumHeight(52)
        self.reset_btn.clicked.connect(self.clock.reset)
        row.addWidget(self.reset_btn, 2)
        self.minus_btn = QPushButton(tr("−1 min"))
        self.minus_btn.setMinimumHeight(52)
        self.minus_btn.clicked.connect(lambda: self.clock.add(-60000))
        row.addWidget(self.minus_btn, 1)
        self.plus_btn = QPushButton(tr("+1 min"))
        self.plus_btn.setMinimumHeight(52)
        self.plus_btn.clicked.connect(lambda: self.clock.add(60000))
        row.addWidget(self.plus_btn, 1)
        return row_widget

    def _build_screen_row(self) -> QWidget:
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(QLabel(tr("Screen")))
        self.screen_combo = QComboBox()
        for role, label in self.roles:
            self.screen_combo.addItem(label, role)
        self.screen_combo.setMinimumHeight(44)
        self.screen_combo.currentIndexChanged.connect(self._on_screen_choice)
        row.addWidget(self.screen_combo, 1)
        self.show_btn = QPushButton()
        self.show_btn.setMinimumHeight(48)
        self.show_btn.clicked.connect(self._on_show)
        row.addWidget(self.show_btn, 2)
        return row_widget

    def _build_look_card(self) -> QWidget:
        card, box = self._card(tr("HOW IT LOOKS"))
        styles = QHBoxLayout()
        styles.setSpacing(8)
        self.style_buttons: Dict[str, QToolButton] = {}
        for value, label in STYLES:
            button = QToolButton()
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setText(tr(label))
            button.setIconSize(QSize(176, 99))
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda _c=False, v=value: self._set_look(style=v))
            styles.addWidget(button)
            self.style_buttons[value] = button
        styles.addStretch(1)
        box.addLayout(styles)

        row = QHBoxLayout()
        row.setSpacing(16)
        sizes = QVBoxLayout()
        sizes.addWidget(self._small_caption(tr("Size")))
        widget, self.size_group = self._chips(SIZES, lambda v: self._set_look(size=v))
        sizes.addWidget(widget)
        row.addLayout(sizes)
        places = QVBoxLayout()
        places.addWidget(self._small_caption(tr("Where (when not full screen)")))
        widget, self.position_group = self._chips(POSITIONS, lambda v: self._set_look(position=v))
        places.addWidget(widget)
        row.addLayout(places)
        shown = QVBoxLayout()
        shown.addWidget(self._small_caption(tr("On it")))
        checks = QHBoxLayout()
        self.checks: Dict[str, QCheckBox] = {}
        for key, label in (("title", "Name"), ("clock", "Clock"), ("logo", "Logo"), ("bar", "Line")):
            check = QCheckBox(tr(label))
            check.toggled.connect(lambda on, k=key: self._set_look(**{k: on}))
            checks.addWidget(check)
            self.checks[key] = check
        logo = QPushButton(tr("  Logo…"))
        logo.setIcon(self.icons.get("image", self.theme["text"], 14))
        logo.setToolTip(tr("Choose the picture shown as the logo"))
        logo.clicked.connect(self.logoRequested.emit)
        checks.addWidget(logo)
        shown.addLayout(checks)
        row.addLayout(shown)
        row.addStretch(1)
        box.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(10)
        for caption, options, key in ((tr("Warning colour"), WARNINGS, "warn"),
                                      (tr("When the time is up"), OVERTIMES, "overtime"),
                                      (tr("Sound at the end"), SOUNDS, "sound")):
            row.addWidget(QLabel(caption))
            combo = QComboBox()
            for value, label in options:
                combo.addItem(tr(label), value)
            combo.currentIndexChanged.connect(lambda _i, c=combo, k=key: self._set_look(**{k: c.currentData()}))
            row.addWidget(combo)
            setattr(self, f"{key}_combo", combo)
        row.addStretch(1)
        box.addLayout(row)
        return card

    @staticmethod
    def _small_caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("cardHint")
        return label

    # -- choices ---------------------------------------------------------------------- #
    def _on_title(self, text: str) -> None:
        if not self._syncing:
            self.clock.title = text.strip()
            self.clock.changed.emit()

    def _on_mode(self, mode: str) -> None:
        if not self._syncing:
            self.clock.set_mode(mode)

    def _dial_ms(self) -> int:
        h, m, s = (spin.value() for spin in self.spins)
        return ((h * 60 + m) * 60 + s) * 1000

    def _on_dial(self) -> None:
        if not self._syncing and self._dial_ms() > 0:
            self.clock.set_duration(self._dial_ms())

    def _set_duration(self, ms: int) -> None:
        self.clock.set_duration(ms)

    def _on_until(self, when: QTime) -> None:
        if not self._syncing:
            self.clock.set_until(when)

    def _on_screen_choice(self) -> None:
        role = self.screen_combo.currentData()
        if self.on_screen and role and role != self.on_screen and not self._syncing:
            self.showRequested.emit(role)            # it moves with the choice
        self.refresh()

    def _on_show(self) -> None:
        if self.on_screen:
            self.hideRequested.emit()
        else:
            self.showRequested.emit(self.screen_combo.currentData())

    def _set_look(self, **changes) -> None:
        if self._syncing:
            return
        look = clean_look(dict(self.look, **changes))
        if look != self.look:
            self.look = look
            self.lookChanged.emit(dict(look))
            self.refresh()

    # -- fed by the dashboard ---------------------------------------------------------------- #
    def set_look(self, look: dict) -> None:
        self.look = clean_look(look)
        self._redraw_styles()
        self.refresh()

    def set_logo(self, logo: Optional[QPixmap]) -> None:
        self.logo = logo
        self._redraw_styles()

    def set_on_screen(self, role: str) -> None:
        self.on_screen = role or ""
        if role:
            self._syncing = True
            self.screen_combo.setCurrentIndex(max(0, self.screen_combo.findData(role)))
            self._syncing = False
        self.refresh()

    def chosen_screen(self) -> str:
        return self.screen_combo.currentData() or ""

    def _redraw_styles(self) -> None:
        for value, button in self.style_buttons.items():
            look = dict(self.look, style=value, size="full")
            button.setIcon(QIcon(look_picture(look, QSize(352, 198), self.logo, tr("Example"))))

    def refresh(self) -> None:
        clock = self.clock
        self._syncing = True
        try:
            if self.title_edit.text().strip() != clock.title and not self.title_edit.hasFocus():
                self.title_edit.setText(clock.title)
            self._check(self.mode_group, clock.mode)
            total = clock.duration_ms // 1000
            for spin, value in zip(self.spins, (total // 3600, total % 3600 // 60, total % 60)):
                if spin.value() != value and not spin.hasFocus():
                    spin.setValue(value)
            minutes = clock.duration_ms / 60000
            self._check(self.preset_group, int(minutes) if minutes == int(minutes) else None)
            if self.until_edit.time() != clock.until:
                self.until_edit.setTime(clock.until)
            self._check(self.size_group, self.look["size"])
            self._check(self.position_group, self.look["position"])
            for key, check in self.checks.items():
                if check.isChecked() != self.look[key]:
                    check.setChecked(self.look[key])
            for key in ("warn", "overtime", "sound"):
                combo = getattr(self, f"{key}_combo")
                combo.setCurrentIndex(max(0, combo.findData(self.look[key])))
            for value, button in self.style_buttons.items():
                button.setChecked(value == self.look["style"])
        finally:
            self._syncing = False
        mode = clock.mode
        self.duration_box.setVisible(mode == "countdown")
        self.until_box.setVisible(mode == "until")
        self.mode_note.setText({"countdown": tr("Start, pause and add a minute while it runs. At 0:00 it turns red and, if you like, beeps."),
                                "until": tr("Counts down to that time of day - for the end of a break, say. It needs no start."),
                                "stopwatch": tr("Counts up from 0:00 - for how long something takes."),
                                "clock": tr("The time of day, large - before an event starts.")}[mode])
        pausable = mode in ("countdown", "stopwatch")
        self.start_btn.setEnabled(pausable)
        self.reset_btn.setEnabled(mode != "clock")
        self.minus_btn.setEnabled(mode == "countdown")
        self.plus_btn.setEnabled(mode == "countdown")
        if clock.running:
            self.start_btn.setText(tr("  Pause"))
            self.start_btn.setIcon(self.icons.get("pause", self.theme["ink"], 18))
        else:
            self.start_btn.setText(tr("  Start") if pausable else tr("  Runs by itself"))
            self.start_btn.setIcon(self.icons.get("play", self.theme["ink"], 18))
        if self.on_screen:
            label = dict(self.roles).get(self.on_screen, self.on_screen)
            self.show_btn.setText(tr("  Take it off {0}").format(label))
            self.show_btn.setIcon(self.icons.get("stop", self.theme["danger"], 16))
            self.show_btn.setObjectName("danger")
        else:
            self.show_btn.setText(tr("  Show on the screen"))
            self.show_btn.setIcon(self.icons.get("monitor", self.theme["ink"], 16))
            self.show_btn.setObjectName("primary")
        self.show_btn.style().unpolish(self.show_btn)
        self.show_btn.style().polish(self.show_btn)

    def show_frame(self, frame: dict, screen_picture: Optional[QPixmap], aspect: float) -> None:
        """The preview: the real screen while the timer is on it, else the timer over a stand-in."""
        if screen_picture is None:
            width = 480
            height = max(30, int(width / max(0.1, aspect)))
            picture = QPixmap(width, height)
            p = QPainter(picture)
            stand_in = QLinearGradient(0, 0, width, height)
            stand_in.setColorAt(0, QColor("#2b2140"))
            stand_in.setColorAt(1, QColor("#16303d"))
            p.fillRect(picture.rect(), stand_in)
            paint_timer(p, QRectF(0, 0, width, height), frame, self.look, self.logo)
            p.end()
            screen_picture = picture
        self.preview.show_picture(screen_picture, aspect)
