"""
The look: the navy-and-gold palette, the stylesheet, and the line icons.

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
from i18n import language

# Palette. A quiet graphite-navy ground, flat surfaces told apart by a step in
# lightness and a hairline - no gradients, no lit edges. One accent, a soft gold,
# for the one action that matters and for what is selected; green, amber and red
# are kept for state (on air, needs attention, live / blackout), nothing else.
CLR_BG = "#0d1016"
CLR_NAV = "#090b10"
CLR_CARD = "#141820"
CLR_RAISED = "#1a1f29"
CLR_INPUT = "#10131a"
CLR_HOVER = "#1e2430"
CLR_LINE = "#232937"
CLR_LINE_SOFT = "#1b202a"
CLR_EDGE = "#21262f"
CLR_EDGE_SOFT = "#1a1e27"
CLR_EDGE_HI = "#2f3644"
CLR_EDGE_LIT = "#262c37"
CLR_WELL = "#0f1218"
CLR_BTN_TOP = "#1a1f29"
CLR_BTN_BOTTOM = "#1a1f29"
CLR_TEXT = "#e6e9ef"
CLR_DIM = "#a1a9b8"
CLR_MUTED = "#6c7484"
CLR_ACCENT = "#d6ad52"
CLR_ACCENT_SOFT = "rgba(214, 173, 82, 0.13)"
CLR_INK = "#16120a"
CLR_OK = "#4cbb83"
CLR_WARN = "#d8994a"
CLR_DANGER = "#df5d58"

# The palette as handed to the modules that cannot import this one.
THEME = {
    "accent": CLR_ACCENT, "text": CLR_TEXT, "dim": CLR_DIM, "muted": CLR_MUTED,
    "ok": CLR_OK, "warn": CLR_WARN, "danger": CLR_DANGER, "card": CLR_CARD,
    "raised": CLR_RAISED, "well": CLR_WELL, "edge": CLR_EDGE, "ink": CLR_INK,
    "rehearse": "#7d97e0", "nav": CLR_NAV, "bg": CLR_BG,
}


# --------------------------------------------------------------------------- #
# Icons
# --------------------------------------------------------------------------- #

# On Windows 11 the icons come from Segoe Fluent Icons, the system's own icon
# font, so the desk looks like the rest of Windows; anywhere else (Windows 10)
# they are drawn below. Not every drawn icon has a Fluent twin: "target" and
# "grip" stay drawn.
FLUENT_GLYPHS = {
    "play": 0xE768, "pause": 0xE769, "stop": 0xE71A, "prev": 0xE892, "next": 0xE893, "plus": 0xE710,
    "minus": 0xE738, "close": 0xE711, "trash": 0xE74D, "folder": 0xE8B7, "save": 0xE74E, "open": 0xE898,
    "monitor": 0xE7F4, "phone": 0xE8EA, "moon": 0xE708, "power": 0xE7E8, "refresh": 0xE72C,
    "repeat": 0xE8EE, "volume": 0xE767, "mute": 0xE74F, "palette": 0xE790, "text": 0xE8D2, "list": 0xE8FD,
    "image": 0xE91B, "compress": 0xE73F, "expand": 0xE740, "warning": 0xE7BA, "video": 0xE714,
    "gear": 0xE713, "lock": 0xE72E, "unlock": 0xE785, "user": 0xE77B, "home": 0xE80F, "broadcast": 0xE93E,
    "slides": 0xE786, "disc": 0xE8D6, "help": 0xE897, "keyboard": 0xE765,
    "rewind": 0xEB9E, "forward": 0xEB9D, "globe": 0xE774, "timer": 0xE916,
}
_fluent_family: Optional[str] = None


def fluent_family() -> str:
    """'Segoe Fluent Icons' when the system has it (Windows 11), else ""."""
    global _fluent_family
    if _fluent_family is None:
        from PySide6.QtGui import QFontDatabase
        _fluent_family = "Segoe Fluent Icons" if "Segoe Fluent Icons" in QFontDatabase.families() else ""
    return _fluent_family


class Icons:
    """
    Line icons: Segoe Fluent Icons on Windows 11, drawn with QPainter on a 24x24
    grid elsewhere.

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
    def _rewind(p: QPainter) -> None:
        brush = p.pen().brush()
        for tip in (3.5, 11.5):
            path = QPainterPath()
            path.moveTo(tip, 12)
            path.lineTo(tip + 8.5, 6)
            path.lineTo(tip + 8.5, 18)
            path.closeSubpath()
            p.fillPath(path, brush)

    @staticmethod
    def _forward(p: QPainter) -> None:
        brush = p.pen().brush()
        for tip in (12.5, 20.5):
            path = QPainterPath()
            path.moveTo(tip, 12)
            path.lineTo(tip - 8.5, 6)
            path.lineTo(tip - 8.5, 18)
            path.closeSubpath()
            p.fillPath(path, brush)

    @staticmethod
    def _timer(p: QPainter) -> None:
        p.drawEllipse(QPointF(12, 13.5), 7.6, 7.6)
        p.drawLine(QPointF(12, 13.5), QPointF(12, 9))
        p.drawLine(QPointF(12, 13.5), QPointF(15, 15.2))
        p.drawLine(QPointF(10, 3.5), QPointF(14, 3.5))
        p.drawLine(QPointF(12, 3.5), QPointF(12, 5.9))

    @staticmethod
    def _globe(p: QPainter) -> None:
        p.drawEllipse(QPointF(12, 12), 8.4, 8.4)
        p.drawEllipse(QPointF(12, 12), 3.6, 8.4)
        p.drawLine(QPointF(3.8, 12), QPointF(20.2, 12))

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
    def _moon(p: QPainter) -> None:
        """A crescent: the dark-room switch."""
        outer = QPainterPath()
        outer.addEllipse(QPointF(12, 12), 8.5, 8.5)
        bite = QPainterPath()
        bite.addEllipse(QPointF(16.5, 8.5), 7.0, 7.0)
        p.drawPath(outer.subtracted(bite))

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

    @staticmethod
    def _gear(p: QPainter) -> None:
        p.drawEllipse(QPointF(12, 12), 3.2, 3.2)
        path = QPainterPath()
        import math
        for i in range(16):
            angle = math.pi * 2 * i / 16 - math.pi / 2
            radius = 8.6 if i % 2 == 0 else 6.6
            point = QPointF(12 + radius * math.cos(angle), 12 + radius * math.sin(angle))
            if i == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        path.closeSubpath()
        p.drawPath(path)

    @staticmethod
    def _lock(p: QPainter) -> None:
        body = QPainterPath()
        body.addRoundedRect(QRectF(5.5, 10.5, 13, 9.5), 2, 2)
        p.drawPath(body)
        p.drawArc(QRectF(8, 4, 8, 10), 0, 180 * 16)
        p.drawLine(QPointF(8, 9), QPointF(8, 10.5))
        p.drawLine(QPointF(16, 9), QPointF(16, 10.5))

    @staticmethod
    def _unlock(p: QPainter) -> None:
        body = QPainterPath()
        body.addRoundedRect(QRectF(5.5, 10.5, 13, 9.5), 2, 2)
        p.drawPath(body)
        p.drawArc(QRectF(8, 3.5, 8, 10), 0, 180 * 16)
        p.drawLine(QPointF(16, 8.5), QPointF(16, 10.5))

    @staticmethod
    def _user(p: QPainter) -> None:
        p.drawEllipse(QPointF(12, 8.5), 3.6, 3.6)
        path = QPainterPath()
        path.moveTo(5, 20)
        path.cubicTo(5.5, 15.5, 8.5, 13.6, 12, 13.6)
        path.cubicTo(15.5, 13.6, 18.5, 15.5, 19, 20)
        p.drawPath(path)

    @staticmethod
    def _home(p: QPainter) -> None:
        path = QPainterPath()
        path.moveTo(4, 11)
        path.lineTo(12, 4.5)
        path.lineTo(20, 11)
        p.drawPath(path)
        body = QPainterPath()
        body.moveTo(6.5, 9.5)
        body.lineTo(6.5, 19.5)
        body.lineTo(17.5, 19.5)
        body.lineTo(17.5, 9.5)
        p.drawPath(body)

    @staticmethod
    def _broadcast(p: QPainter) -> None:
        """The Live page: a screen with waves - what goes out to the hall."""
        path = QPainterPath()
        path.addRoundedRect(QRectF(4, 7, 16, 11), 2, 2)
        p.drawPath(path)
        dot = QPainterPath()
        dot.addEllipse(QPointF(12, 12.5), 1.8, 1.8)
        p.fillPath(dot, p.pen().brush())
        p.drawArc(QRectF(8, 3, 8, 6), 30 * 16, 120 * 16)

    @staticmethod
    def _slides(p: QPainter) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(3.5, 4.5, 17, 11.5), 1.6, 1.6)
        p.drawPath(path)
        p.drawLine(QPointF(12, 16), QPointF(12, 18.5))
        p.drawLine(QPointF(8, 20), QPointF(12, 18.5))
        p.drawLine(QPointF(16, 20), QPointF(12, 18.5))
        p.drawLine(QPointF(7.5, 12.5), QPointF(10.5, 9.5))
        p.drawLine(QPointF(10.5, 9.5), QPointF(13, 11.5))
        p.drawLine(QPointF(13, 11.5), QPointF(16.5, 8))

    @staticmethod
    def _disc(p: QPainter) -> None:
        p.drawEllipse(QPointF(12, 12), 8.2, 8.2)
        p.drawEllipse(QPointF(12, 12), 2.2, 2.2)
        p.drawArc(QRectF(6.5, 6.5, 11, 11), 100 * 16, 70 * 16)

    @staticmethod
    def _help(p: QPainter) -> None:
        p.drawEllipse(QPointF(12, 12), 8.4, 8.4)
        path = QPainterPath()
        path.moveTo(9.4, 9.6)
        path.cubicTo(9.4, 7.6, 10.7, 6.8, 12.1, 6.8)
        path.cubicTo(13.7, 6.8, 14.8, 7.9, 14.8, 9.3)
        path.cubicTo(14.8, 11.4, 12.2, 11.6, 12.2, 13.8)
        p.drawPath(path)
        dot = QPainterPath()
        dot.addEllipse(QPointF(12.2, 16.8), 1.1, 1.1)
        p.fillPath(dot, p.pen().brush())

    @staticmethod
    def _keyboard(p: QPainter) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(3, 6.5, 18, 11), 2, 2)
        p.drawPath(path)
        p.drawLine(QPointF(8, 14), QPointF(16, 14))
        for x in (7, 10.3, 13.6, 17):
            dot = QPainterPath()
            dot.addEllipse(QPointF(x, 10.3), 0.9, 0.9)
            p.fillPath(dot, p.pen().brush())

    # -- factory ------------------------------------------------------------ #

    @classmethod
    def get(cls, name: str, colour: str = CLR_TEXT, size: int = 18) -> QIcon:
        key = (name, colour, size)
        cached = cls._cache.get(key)
        if cached is not None:
            return cached

        scale = 2  # render at 2x so the icon stays crisp on HiDPI screens
        if name in FLUENT_GLYPHS and fluent_family():
            pixmap = QPixmap(size * scale, size * scale)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            font = QFont(fluent_family())
            font.setPixelSize(int(size * scale * 0.92))
            painter.setFont(font)
            painter.setPen(QColor(colour))
            painter.drawText(QRectF(0, 0, size * scale, size * scale), Qt.AlignCenter, chr(FLUENT_GLYPHS[name]))
            painter.end()
            pixmap.setDevicePixelRatio(float(scale))
            icon = QIcon(pixmap)
            cls._cache[key] = icon
            return icon

        draw: Optional[Callable] = getattr(cls, "_" + name, None)
        if draw is None:
            return QIcon()

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
QMainWindow {{ background: {CLR_BG}; }}
QWidget {{
    background-color: {CLR_BG};
    color: {CLR_TEXT};
    font-family: "Segoe UI Variable Text", "Segoe UI", "Noto Sans Georgian", sans-serif;
    font-size: 13px;
}}
QLabel {{ background: transparent; }}

/* -- navigation ----------------------------------------------------------- */
QFrame#navRail {{ background: {CLR_NAV}; border: none; border-right: 1px solid {CLR_EDGE_SOFT}; }}
QFrame#navRail QWidget {{ background: transparent; }}
QToolButton#navButton {{
    background: transparent; border: none; border-radius: 6px;
    color: {CLR_MUTED}; font-size: 11px; font-weight: 500;
    padding: 9px 2px 8px 2px;
}}
QToolButton#navButton:hover {{ background: {CLR_CARD}; color: {CLR_DIM}; }}
QToolButton#navButton:checked {{ background: {CLR_RAISED}; color: {CLR_TEXT}; font-weight: 600; }}
QLabel#navRole {{ color: {CLR_MUTED}; font-size: 10px; font-weight: 600; }}
QLabel#pageTitle {{
    font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif; font-size: 20px; font-weight: 600;
}}
QLabel#pageLead {{ color: {CLR_DIM}; font-size: 13px; }}

/* Tabs that still show (dialogs, the DJ desk) read as navigation, not buttons. */
QTabWidget::pane {{ border: none; background: {CLR_BG}; }}
QTabBar::tab {{
    background: transparent; color: {CLR_MUTED};
    padding: 8px 18px 9px 4px; margin-right: 18px; border: none;
    font-size: 13px; font-weight: 500;
}}
QTabBar::tab:hover {{ color: {CLR_DIM}; }}
QTabBar::tab:selected {{ color: {CLR_TEXT}; font-weight: 600; border-bottom: 2px solid {CLR_ACCENT}; }}

/* -- surfaces ------------------------------------------------------------- */
QFrame#card, QFrame#bar {{
    background: {CLR_CARD};
    border: 1px solid {CLR_EDGE};
    border-radius: 8px;
}}
QFrame#card[active="true"] {{ border: 1px solid rgba(214, 173, 82, 0.45); }}
QFrame#plain {{ background: transparent; border: none; }}

QLabel#cardTitle {{ font-size: 14px; font-weight: 600; }}
QLabel#cardSub {{ color: {CLR_MUTED}; font-size: 11px; }}
QLabel#cardHint {{ color: {CLR_DIM}; }}
QLabel#sectionTitle {{ color: {CLR_MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 0.3px; }}
QLabel#brand {{ font-size: 13px; font-weight: 700; letter-spacing: 0.3px; }}
QLabel#clock {{
    color: {CLR_TEXT}; font-size: 20px; font-weight: 500;
    font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif;
}}
QLabel#timecode {{ color: {CLR_MUTED}; font-family: "Consolas", monospace; font-size: 11px; }}
QLabel#keyHint {{ color: {CLR_MUTED}; font-size: 11px; }}

QLabel#badgeLive, QLabel#badgeOff {{
    font-size: 10px; font-weight: 700; letter-spacing: 0.4px;
    padding: 3px 9px; border-radius: 9px;
}}
QLabel#badgeLive {{ color: {CLR_OK}; background: rgba(76, 187, 131, 0.12); border: none; }}
QLabel#badgeOff {{ color: {CLR_MUTED}; background: rgba(108, 116, 132, 0.12); border: none; }}

QFrame#dropZone {{ background: {CLR_WELL}; border: 1px dashed {CLR_EDGE_HI}; border-radius: 6px; }}
QFrame#dropZone[dragActive="true"] {{ background: {CLR_ACCENT_SOFT}; border: 1px dashed {CLR_ACCENT}; }}

/* -- buttons -------------------------------------------------------------- */
QPushButton, QToolButton {{
    background: {CLR_RAISED};
    border: 1px solid {CLR_EDGE_HI};
    border-radius: 5px;
    padding: 7px 14px;
    color: {CLR_TEXT};
    font-weight: 500;
}}
QPushButton:hover, QToolButton:hover {{ background: {CLR_HOVER}; border-color: #3a4252; }}
QPushButton:pressed, QToolButton:pressed {{ background: {CLR_WELL}; }}
QPushButton:disabled, QToolButton:disabled {{
    background: {CLR_WELL}; color: #485062; border-color: {CLR_EDGE_SOFT};
}}
QPushButton:checked, QToolButton:checked {{
    background: {CLR_ACCENT_SOFT}; border: 1px solid rgba(214, 173, 82, 0.42); color: {CLR_TEXT};
}}

QPushButton#primary {{
    background: {CLR_ACCENT}; color: {CLR_INK}; font-weight: 600; border: 1px solid {CLR_ACCENT};
}}
QPushButton#primary:hover {{ background: #e0b85e; border-color: #e0b85e; }}
QPushButton#primary:pressed {{ background: #c39a42; }}
QPushButton#primary:disabled {{ background: {CLR_WELL}; color: #485062; border-color: {CLR_EDGE_SOFT}; }}

QPushButton#danger {{
    background: rgba(223, 93, 88, 0.08); color: {CLR_DANGER};
    border: 1px solid rgba(223, 93, 88, 0.38); font-weight: 600;
}}
QPushButton#danger:hover {{ background: rgba(223, 93, 88, 0.16); border-color: rgba(223, 93, 88, 0.6); }}
QPushButton#ghost, QToolButton#ghost {{ background: transparent; border: 1px solid transparent; padding: 5px; }}
QPushButton#ghost:hover, QToolButton#ghost:hover {{ background: {CLR_HOVER}; border-color: transparent; }}
QPushButton#ghost:checked {{ background: {CLR_ACCENT_SOFT}; border-color: transparent; }}
QPushButton#ghost:disabled {{ background: transparent; border-color: transparent; }}
QPushButton#transport {{ font-size: 15px; font-weight: 600; padding: 9px 0px; }}
QFrame#segment {{ background: {CLR_INPUT}; border: 1px solid {CLR_EDGE}; border-radius: 6px; }}
QPushButton#segmentButton {{ background: transparent; border: none; border-radius: 4px; padding: 5px 0px; }}
QPushButton#segmentButton:hover {{ background: {CLR_HOVER}; }}
QPushButton#segmentButton:pressed {{ background: {CLR_WELL}; }}
QPushButton#healthChip {{
    background: transparent; border: 1px solid {CLR_EDGE}; border-radius: 9px;
    padding: 2px 10px; font-size: 11px; font-weight: 600; color: {CLR_MUTED};
}}
QPushButton#healthChip:hover {{ background: {CLR_HOVER}; border-color: {CLR_EDGE_HI}; }}
QPushButton#tile {{
    background: {CLR_CARD}; border: 1px solid {CLR_EDGE}; border-radius: 8px;
    padding: 14px; font-size: 14px; font-weight: 600; text-align: left;
}}
QPushButton#tile:hover {{ background: {CLR_RAISED}; border-color: {CLR_EDGE_HI}; }}
QPushButton#big {{ font-size: 15px; font-weight: 600; padding: 12px 18px; border-radius: 6px; }}

/* -- inputs --------------------------------------------------------------- */
QComboBox, QSpinBox, QLineEdit, QFontComboBox, QPlainTextEdit {{
    background: {CLR_INPUT};
    border: 1px solid {CLR_EDGE};
    border-bottom: 1px solid #3a4252;
    border-radius: 5px;
    padding: 6px 10px;
    selection-background-color: {CLR_ACCENT};
    selection-color: {CLR_INK};
}}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover, QFontComboBox:hover {{ border-color: {CLR_EDGE_HI}; }}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {CLR_EDGE}; border-bottom: 2px solid {CLR_ACCENT};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {CLR_RAISED}; border: 1px solid {CLR_EDGE_HI}; border-radius: 8px; padding: 4px;
    selection-background-color: {CLR_HOVER}; selection-color: {CLR_TEXT}; outline: none;
}}
QSpinBox:disabled, QComboBox:disabled, QLineEdit:disabled {{ color: #485062; background: {CLR_WELL}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 14px; border: none; background: transparent; }}

QListWidget {{
    background: {CLR_WELL}; border: 1px solid {CLR_EDGE_SOFT}; border-radius: 8px;
    outline: none; padding: 4px;
}}
QListWidget::item {{ padding: 6px 8px; border-radius: 5px; color: {CLR_DIM}; }}
QListWidget::item:hover {{ background: {CLR_HOVER}; color: {CLR_TEXT}; }}
QListWidget::item:selected {{ background: {CLR_ACCENT_SOFT}; color: {CLR_TEXT}; border: none; }}

QListWidget#settingsNav {{ background: transparent; border: none; padding: 0px; }}
QListWidget#settingsNav::item {{ padding: 10px 12px; margin: 1px 0px; border-radius: 5px; color: {CLR_DIM}; }}
QListWidget#settingsNav::item:hover {{ background: {CLR_CARD}; color: {CLR_TEXT}; }}
QListWidget#settingsNav::item:selected {{ background: {CLR_RAISED}; color: {CLR_TEXT}; font-weight: 600; }}

QSlider::groove:horizontal {{ height: 4px; background: {CLR_LINE}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {CLR_ACCENT}; width: 8px; height: 8px; margin: -6px 0; border-radius: 8px;
    border: 4px solid #39404e;
}}
QSlider::handle:horizontal:hover {{ background: #e0b85e; border-width: 3px; width: 10px; height: 10px; }}
QSlider::sub-page:horizontal {{ background: #8d96a8; border-radius: 2px; }}
QSlider::groove:horizontal:disabled {{ background: {CLR_EDGE_SOFT}; }}
QSlider::sub-page:horizontal:disabled {{ background: #3a404d; }}
QSlider#scrub::groove:horizontal {{ height: 3px; background: {CLR_LINE}; border-radius: 2px; }}
QSlider#scrub::sub-page:horizontal {{ background: {CLR_ACCENT}; border-radius: 2px; }}
QSlider#scrub::handle:horizontal {{
    background: transparent; border: none; width: 10px; margin: -4px 0; border-radius: 5px;
}}
QSlider#scrub:hover::handle:horizontal {{ background: {CLR_TEXT}; }}
QSlider#scrub:disabled::sub-page:horizontal {{ background: {CLR_LINE}; }}

QCheckBox {{ background: transparent; color: {CLR_DIM}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {CLR_EDGE_HI}; background: {CLR_INPUT};
}}
QCheckBox::indicator:checked {{ background: {CLR_ACCENT}; border-color: {CLR_ACCENT}; }}
QCheckBox:disabled {{ color: #485062; }}
QCheckBox::indicator:disabled {{ background: {CLR_WELL}; border-color: {CLR_EDGE_SOFT}; }}
QCheckBox::indicator:checked:disabled {{ background: #3a404d; border-color: {CLR_EDGE}; }}

/* -- sound pads ----------------------------------------------------------- */
QFrame#cuePad {{ background: {CLR_RAISED}; border: 1px solid {CLR_EDGE}; border-radius: 8px; }}
QFrame#cuePad[filled="false"] {{ background: transparent; border: 1px dashed {CLR_EDGE_HI}; }}
QFrame#cuePad[filled="true"]:hover {{ border-color: {CLR_EDGE_HI}; }}
QFrame#cuePad[playing="true"] {{ background: rgba(76, 187, 131, 0.12); border: 1px solid rgba(76, 187, 131, 0.5); }}
QFrame#cuePad[paused="true"] {{ background: {CLR_ACCENT_SOFT}; border: 1px solid rgba(214, 173, 82, 0.45); }}
QLabel#cueKey {{ color: {CLR_MUTED}; font-size: 10px; font-weight: 700; }}
QFrame#cuePad[playing="true"] QLabel#cueKey {{ color: {CLR_OK}; }}
QFrame#cuePad[paused="true"] QLabel#cueKey {{ color: {CLR_ACCENT}; }}
QLabel#cueName {{ font-size: 12px; font-weight: 500; }}
QFrame#cuePad[filled="false"] QLabel#cueName {{ color: #4a5264; }}

/* -- the floating strip --------------------------------------------------- */
QFrame#miniCard {{ background: {CLR_CARD}; border: 1px solid {CLR_EDGE_HI}; border-radius: 8px; }}
QPushButton#miniScreen {{ padding: 6px 12px; font-size: 12px; font-weight: 600; color: {CLR_MUTED}; }}
QPushButton#miniScreen:checked {{ background: {CLR_ACCENT_SOFT}; color: {CLR_TEXT}; border-color: rgba(214, 173, 82, 0.5); }}
QPushButton#miniScreen[live="true"] {{ color: {CLR_OK}; }}
QLabel#miniNow {{ color: {CLR_DIM}; font-size: 12px; }}
QPushButton#miniCue {{ padding: 7px 0px; font-size: 11px; font-weight: 600; color: {CLR_DIM}; }}
QPushButton#miniCue[playing="true"] {{ background: rgba(76, 187, 131, 0.16); color: {CLR_OK}; border-color: rgba(76, 187, 131, 0.45); }}
QPushButton#miniCue[paused="true"] {{ background: {CLR_ACCENT_SOFT}; color: {CLR_ACCENT}; border-color: rgba(214, 173, 82, 0.45); }}

/* -- SETUP / SHOW, TAKE --------------------------------------------------- */
QFrame#modeSwitch {{ background: {CLR_WELL}; border: 1px solid {CLR_EDGE}; border-radius: 6px; }}
QPushButton#modeButton {{
    background: transparent; border: 1px solid transparent; border-radius: 4px;
    padding: 6px 16px; color: {CLR_MUTED}; font-weight: 700; letter-spacing: 0.8px;
}}
QPushButton#modeButton:hover {{ color: {CLR_DIM}; background: transparent; }}
QPushButton#modeButton:checked {{ background: {CLR_RAISED}; color: {CLR_TEXT}; border: 1px solid {CLR_EDGE_HI}; }}
QFrame#takeBar {{ background: rgba(214, 173, 82, 0.06); border: 1px solid rgba(214, 173, 82, 0.32); border-radius: 8px; }}

QMenu {{ background: {CLR_RAISED}; border: 1px solid {CLR_EDGE_HI}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 7px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {CLR_HOVER}; }}
QMenu::separator {{ height: 1px; background: {CLR_EDGE}; margin: 4px 6px; }}
QDialog {{ background: {CLR_BG}; }}
QStatusBar {{ background: transparent; color: {CLR_MUTED}; border: none; }}
QStatusBar::item {{ border: none; }}
QToolTip {{
    background: {CLR_RAISED}; color: {CLR_TEXT};
    border: 1px solid {CLR_EDGE_HI}; padding: 6px 9px; border-radius: 4px;
}}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #3a4252; border-radius: 2px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: #384052; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2a3140; border-radius: 4px; min-width: 28px; }}
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
QToolButton#navButton {{ padding: 12px 2px 11px 2px; }}
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


def _switch_images() -> Dict[str, str]:
    """
    Finger-sized on/off switches for the touch look, drawn once and kept as
    small PNGs - a stylesheet can only show a picture as a check box's box.
    """
    folder = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                          "StageDisplayController", "ui")
    paths = {}
    for name, on, enabled in (("off", False, True), ("on", True, True),
                              ("off_dis", False, False), ("on_dis", True, False)):
        path = os.path.join(folder, f"switch_v2_{name}.png")
        if not os.path.exists(path):
            os.makedirs(folder, exist_ok=True)
            picture = QPixmap(92, 52)
            picture.fill(Qt.transparent)
            painter = QPainter(picture)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setOpacity(1.0 if enabled else 0.4)
            track = QRectF(2, 4, 88, 44)
            painter.setPen(QPen(QColor(CLR_ACCENT if on else CLR_EDGE_HI), 2))
            painter.setBrush(QColor(CLR_ACCENT if on else CLR_LINE))
            painter.drawRoundedRect(track, 22, 22)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(CLR_INK if on else "#c9d2e2"))
            painter.drawEllipse(QPointF(66 if on else 26, 26), 16, 16)
            painter.end()
            picture.save(path)
        paths[name] = path.replace("\\", "/")
    return paths


def language_stylesheet() -> str:
    """Consolas has no Georgian letters - Qt's stand-in draws them as capitals - so
    the timecodes, which carry words, are set in Segoe UI when the app speaks Georgian."""
    return "" if language() == "en" else 'QLabel#timecode { font-family: "Segoe UI"; }\n'


def touch_stylesheet() -> str:
    """The touch look, with check boxes drawn as switches."""
    try:
        images = _switch_images()
    except OSError:
        return TOUCH_STYLESHEET
    return TOUCH_STYLESHEET + f"""
QCheckBox {{ spacing: 12px; }}
QCheckBox::indicator {{
    width: 46px; height: 26px; border: none; border-radius: 0px; background: transparent;
    image: url("{images['off']}");
}}
QCheckBox::indicator:checked {{ image: url("{images['on']}"); border: none; background: transparent; }}
QCheckBox::indicator:disabled {{ image: url("{images['off_dis']}"); border: none; background: transparent; }}
QCheckBox::indicator:checked:disabled {{ image: url("{images['on_dis']}"); background: transparent; }}
"""


def touch_screen_present() -> bool:
    return any(device.type() == QInputDevice.DeviceType.TouchScreen
               for device in QInputDevice.devices())
