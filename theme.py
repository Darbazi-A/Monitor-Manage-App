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
        path = os.path.join(folder, f"switch_v1_{name}.png")
        if not os.path.exists(path):
            os.makedirs(folder, exist_ok=True)
            picture = QPixmap(92, 52)
            picture.fill(Qt.transparent)
            painter = QPainter(picture)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setOpacity(1.0 if enabled else 0.4)
            track = QRectF(2, 4, 88, 44)
            painter.setPen(QPen(QColor("#c9992f" if on else CLR_EDGE_HI), 2))
            painter.setBrush(QColor(CLR_ACCENT if on else "#1b2231"))
            painter.drawRoundedRect(track, 22, 22)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(CLR_INK if on else "#c9d2e2"))
            painter.drawEllipse(QPointF(66 if on else 26, 26), 16, 16)
            painter.end()
            picture.save(path)
        paths[name] = path.replace("\\", "/")
    return paths


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
