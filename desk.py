"""
The operator's desk: the parts of the dashboard that are about running the
event rather than about any one screen.

    NavRail          the pages down the left edge; settings and who is at the desk below
    MultiView        a live picture of every stage screen, in the header
    ModeSwitch       SETUP (prepare, edit) / SHOW (run it, editing locked)
    TakeBar          preview-then-TAKE, and the undo that follows a change
    ShowStrip        NOW / NEXT and the NEXT button, under every tab
    ReadyCheckDialog the pre-show check: screens, sound, clicker, files

Kept free of main.py imports on purpose, like show.py: main imports this, and
the colours and icons are handed in.
"""
from __future__ import annotations

from i18n import caps, tr  # noqa: E402 - the interface's language

import time
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSizePolicy, QTabWidget, QToolButton, QToolTip, QVBoxLayout,
                               QWidget)

STATE_CLOSED = "closed"        # no window on that screen
STATE_BLACK = "black"          # window open, nothing on it
STATE_LIVE = "live"            # something is on the screen, in front of the audience
STATE_REHEARSAL = "rehearsal"  # a rehearsal window: nothing reaches the stage


def _font(pixels: int, weight: int = QFont.Normal) -> QFont:
    font = QFont("Segoe UI")
    font.setPixelSize(pixels)
    font.setWeight(QFont.Weight(weight))
    return font


# --------------------------------------------------------------------------- #
# Navigation
# --------------------------------------------------------------------------- #

class NavRail(QFrame):
    """
    The pages down the left edge, as in any modern desktop app: an icon and a
    word each, the open one lit. Settings and the person at the desk (administrator
    or the simple desk) sit at the bottom, away from the pages used during a show.
    It drives a PageTabs whose own tab bar is hidden, and follows it back.
    """

    pageRequested = Signal(int)
    accountRequested = Signal()
    helpRequested = Signal()

    WIDTH = 100

    def __init__(self, icons, theme: dict, parent=None) -> None:
        super().__init__(parent)
        self.icons = icons
        self.theme = theme
        self.setObjectName("navRail")
        self.setFixedWidth(self.WIDTH)
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 16, 8, 12)
        box.setSpacing(4)
        logo = QLabel()
        logo.setPixmap(icons.get("monitor", theme["accent"], 26).pixmap(26, 26))
        logo.setAlignment(Qt.AlignHCenter)
        logo.setToolTip("Stage Display Controller")
        box.addWidget(logo)
        box.addSpacing(18)
        self._pages = QVBoxLayout()
        self._pages.setSpacing(4)
        box.addLayout(self._pages)
        box.addStretch(1)
        self._lower = QVBoxLayout()
        self._lower.setSpacing(4)
        box.addLayout(self._lower)
        self.buttons: Dict[int, tuple] = {}         # page index -> (button, icon name)
        self._group = QButtonGroup(self)
        self._group.setExclusive(False)             # the rail follows the pages, it does not lead them
        self.help_btn = self._button("help", tr("Help"))
        self.help_btn.setCheckable(False)
        self.help_btn.setToolTip(tr("Keyboard shortcuts and how things work"))
        self.help_btn.clicked.connect(self.helpRequested.emit)
        self.account_btn = self._button("unlock", tr("Admin"))
        self.account_btn.setCheckable(False)
        self.account_btn.clicked.connect(self.accountRequested.emit)
        self._lower_items: List[QWidget] = []

    def _button(self, icon: str, label: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("navButton")
        button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        button.setIcon(self.icons.get(icon, self.theme["muted"], 22))
        button.setIconSize(QSize(22, 22))
        button.setText(label)
        button.setCheckable(True)
        button.setFixedWidth(self.WIDTH - 16)
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.NoFocus)
        return button

    def add_page(self, index: int, icon: str, label: str, lower: bool = False) -> QToolButton:
        button = self._button(icon, label)
        button.setToolTip(label)
        button.clicked.connect(lambda _checked=False, i=index: self.pageRequested.emit(i))
        self._group.addButton(button)
        self.buttons[index] = (button, icon)
        if lower:
            self._lower.addWidget(button, 0, Qt.AlignHCenter)
        else:
            self._pages.addWidget(button, 0, Qt.AlignHCenter)
        return button

    def finish(self) -> None:
        """Help and the account go last, under the lower pages."""
        self._lower.addWidget(self.help_btn, 0, Qt.AlignHCenter)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {self.theme['edge']};")
        self._lower.addSpacing(4)
        self._lower.addWidget(line)
        self._lower.addSpacing(4)
        self._lower.addWidget(self.account_btn, 0, Qt.AlignHCenter)

    def paintEvent(self, event) -> None:  # noqa: N802
        """The open page gets Windows 11's selection pill beside it."""
        super().paintEvent(event)
        for button, _icon in self.buttons.values():
            if button.isChecked() and button.isVisible():
                painter = QPainter(self)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(self.theme["accent"]))
                top = button.mapTo(self, button.rect().topLeft())
                painter.drawRoundedRect(QRectF(2, top.y() + button.height() / 2 - 9, 3.5, 18), 1.75, 1.75)
                painter.end()
                break

    def sync(self, tabs: QTabWidget) -> None:
        """Show the buttons of the pages that can be opened; light the open one."""
        current = tabs.currentIndex()
        for index, (button, icon) in self.buttons.items():
            visible = tabs.isTabVisible(index)
            button.setVisible(visible)
            on = index == current
            if button.isChecked() != on or getattr(button, "_lit", None) != on:
                button.setChecked(on)
                button.setIcon(self.icons.get(icon, self.theme["accent"] if on else self.theme["muted"], 22))
                button._lit = on
        self.update()

    def set_account(self, admin: bool, has_pin: bool) -> None:
        if admin:
            self.account_btn.setIcon(self.icons.get("unlock", self.theme["muted"], 22))
            self.account_btn.setText(tr("Admin"))
            self.account_btn.setToolTip(tr("Administrator: everything is open.\nClick to hand the desk over in the simple mode.")
                                        if has_pin else
                                        tr("Administrator: everything is open, and no PIN is set.\nClick to set one and switch to the simple mode."))
        else:
            self.account_btn.setIcon(self.icons.get("lock", self.theme["accent"], 22))
            self.account_btn.setText(tr("Simple"))
            self.account_btn.setToolTip(tr("The simple desk. Click and type the admin PIN for everything else."))


# --------------------------------------------------------------------------- #
# Multiview
# --------------------------------------------------------------------------- #

class ScreenTile(QWidget):
    """
    One stage screen, small: what is on it right now, and whether it is on air.

    The frame's colour is the state - red is in front of the audience, grey is
    black, dashed is closed - so a glance at the header says what the hall sees.
    Media files dropped on a tile go to that screen.
    """

    clicked = Signal(str)
    filesDropped = Signal(str, list)

    PREVIEW_H = 52

    def __init__(self, role: str, label: str, aspect: float, theme: dict, width: int) -> None:
        super().__init__()
        self.role = role
        self.label = label
        self.aspect = aspect
        self.theme = theme
        self.state = STATE_CLOSED
        self.caption = "closed"
        self.pixmap: Optional[QPixmap] = None
        self._drag = False
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(width, self.PREVIEW_H + 34)
        self.setToolTip(tr('{0} - click to make it the screen the keys act on; drop a file to show it here').format(label))

    def preview_rect(self) -> QRectF:
        """Where the picture goes: the screen's own shape, fitted in the tile."""
        box = QRectF(1, 15, self.width() - 2, self.PREVIEW_H)
        width = box.width()
        height = width / self.aspect
        if height > box.height():
            height = box.height()
            width = height * self.aspect
        height = max(8.0, height)
        return QRectF(box.center().x() - width / 2, box.center().y() - height / 2, width, height)

    def preview_size(self) -> QSize:
        rect = self.preview_rect()
        return QSize(max(1, int(rect.width())), max(1, int(rect.height())))

    def set_state(self, state: str, pixmap: Optional[QPixmap], caption: str) -> None:
        self.state = state
        self.pixmap = pixmap
        self.caption = caption
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        theme = self.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        colour = {STATE_LIVE: theme["danger"], STATE_BLACK: theme["muted"],
                  STATE_REHEARSAL: theme.get("rehearse", "#7c9cf0"),
                  STATE_CLOSED: theme["muted"]}[self.state]
        # name + state
        p.setFont(_font(10, QFont.Bold))
        tag = tr({STATE_LIVE: "ON AIR", STATE_BLACK: "BLACK", STATE_REHEARSAL: "REHEARSAL",
                  STATE_CLOSED: "CLOSED"}[self.state])
        p.setPen(QColor(colour))
        p.drawText(QRectF(2, 0, self.width() - 4, 13), Qt.AlignRight | Qt.AlignVCenter, tag)
        # the name gets what the tag leaves; Georgian has no capitals to shout with
        room = self.width() - 4 - p.fontMetrics().horizontalAdvance(tag) - 6
        name = caps(self.label)
        p.setPen(QColor(theme["dim"]))
        p.drawText(QRectF(2, 0, room, 13), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(name, Qt.ElideRight, int(room)))
        # picture
        rect = self.preview_rect()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#05070b"))
        p.drawRoundedRect(rect, 4, 4)
        if self.pixmap is not None and not self.pixmap.isNull() and self.state != STATE_CLOSED:
            clip = QPainterPath()
            clip.addRoundedRect(rect, 4, 4)
            p.save()
            p.setClipPath(clip)
            p.drawPixmap(rect, self.pixmap, QRectF(self.pixmap.rect()))
            p.restore()
        elif self.state == STATE_CLOSED:
            p.setPen(QColor(theme["muted"]))
            p.setFont(_font(10))
            p.drawText(rect, Qt.AlignCenter, tr("click to open"))
        pen = QPen(QColor(colour), 2 if self.state in (STATE_LIVE, STATE_REHEARSAL) else 1)
        if self.state == STATE_CLOSED:
            pen.setStyle(Qt.DashLine)
        if self._drag:
            pen = QPen(QColor(theme["accent"]), 2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 5, 5)
        # what it is
        p.setFont(_font(11))
        p.setPen(QColor(theme["text"] if self.state == STATE_LIVE else theme["dim"]))
        text_rect = QRectF(2, self.height() - 17, self.width() - 4, 16)
        p.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self.caption, Qt.ElideMiddle, int(text_rect.width())))
        p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.role)
        super().mousePressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            self._drag = True
            self.update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, _event) -> None:  # noqa: N802
        self._drag = False
        self.update()

    def dropEvent(self, event) -> None:  # noqa: N802
        self._drag = False
        self.update()
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.filesDropped.emit(self.role, paths)
            event.acceptProposedAction()


class MultiView(QWidget):
    """The three stage screens side by side, as the audience sees them."""

    def __init__(self, labels: Dict[str, str], aspects: Dict[str, float], theme: dict) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.tiles: Dict[str, ScreenTile] = {}
        for role, label in labels.items():
            aspect = aspects.get(role, 16 / 9)
            width = 250 if aspect > 3 else 120
            tile = ScreenTile(role, label, aspect, theme, width)
            row.addWidget(tile)
            self.tiles[role] = tile


# --------------------------------------------------------------------------- #
# Tabs that never push the window off the screen
# --------------------------------------------------------------------------- #

class _PageScroll(QScrollArea):
    pass


class PageTabs(QTabWidget):
    """
    A tab widget whose pages scroll when the screen is short, instead of the
    tallest page making the whole window taller than the monitor. Code asks for
    pages as before - widget(), currentWidget(), indexOf(), setCurrentWidget()
    all speak of the page itself, not of the scroll area around it.
    """

    def addTab(self, page, label, scroll: bool = True):  # noqa: N802
        if not scroll:
            return super().addTab(page, label)
        holder = _PageScroll()
        holder.setWidgetResizable(True)
        holder.setFrameShape(QFrame.NoFrame)
        holder.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder.setStyleSheet("QScrollArea { background: transparent; } "
                             "QScrollArea > QWidget > QWidget { background: transparent; }")
        holder.setWidget(page)
        return super().addTab(holder, label)

    def widget(self, index):
        holder = super().widget(index)
        return holder.widget() if isinstance(holder, _PageScroll) else holder

    def currentWidget(self):  # noqa: N802
        return self.widget(self.currentIndex())

    def indexOf(self, page):  # noqa: N802
        for index in range(self.count()):
            if self.widget(index) is page or super().widget(index) is page:
                return index
        return -1

    def setCurrentWidget(self, page) -> None:  # noqa: N802
        index = self.indexOf(page)
        if index >= 0:
            self.setCurrentIndex(index)


# --------------------------------------------------------------------------- #
# SETUP / SHOW
# --------------------------------------------------------------------------- #

class ModeSwitch(QFrame):
    """Two halves of one control: SETUP to prepare, SHOW to run the event."""

    modeChanged = Signal(str)

    def __init__(self, theme: dict) -> None:
        super().__init__()
        self.setObjectName("modeSwitch")
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: Dict[str, QPushButton] = {}
        for mode, text, tip in (
                ("setup", "SETUP", "Prepare: presets, running order, library, screens - everything can be edited"),
                ("show", "SHOW", "Run the event: the controls you need, editing and deleting locked")):
            button = QPushButton(tr(text))
            button.setObjectName("modeButton")
            button.setCheckable(True)
            button.setToolTip(tr(tip))
            button.clicked.connect(lambda _c=False, m=mode: self.modeChanged.emit(m))
            self.group.addButton(button)
            row.addWidget(button)
            self.buttons[mode] = button

    def set_mode(self, mode: str) -> None:
        self.buttons[mode].setChecked(True)


# --------------------------------------------------------------------------- #
# Preview -> TAKE, and undo
# --------------------------------------------------------------------------- #

class TakeBar(QFrame):
    """
    A thin bar under the header, only there when it has something to say.

    PREVIEW: a change is waiting - what, where, and TAKE / Cancel.
    DONE:    a change just went on stage - and a short while to undo it.
    """

    takeRequested = Signal()
    cancelRequested = Signal()
    undoRequested = Signal()

    UNDO_SECONDS = 10

    def __init__(self, icons, theme: dict) -> None:
        super().__init__()
        self.setObjectName("takeBar")
        self.theme = theme
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 8, 6)
        row.setSpacing(10)
        self.thumb = QLabel()
        self.thumb.setFixedSize(80, 45)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet("background: #05070b; border-radius: 4px;")
        row.addWidget(self.thumb)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.tag = QLabel()
        self.tag.setObjectName("takeTag")
        texts.addWidget(self.tag, 0, Qt.AlignLeft)
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        texts.addWidget(self.title)
        self.detail = QLabel()
        self.detail.setObjectName("cardHint")
        self.detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        texts.addWidget(self.detail)
        row.addLayout(texts, 1)
        self.take_btn = QPushButton(tr('  TAKE'))
        self.take_btn.setObjectName("primary")
        self.take_btn.setIcon(icons.get("play", theme["ink"], 16))
        self.take_btn.setMinimumSize(120, 40)
        self.take_btn.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.take_btn.setToolTip(tr('Put it on stage now  (Ctrl+Enter)'))
        self.take_btn.clicked.connect(self.takeRequested.emit)
        row.addWidget(self.take_btn)
        self.cancel_btn = QPushButton(tr('Cancel'))
        self.cancel_btn.setToolTip(tr('Leave the stage as it is  (Esc)'))
        self.cancel_btn.clicked.connect(self.cancelRequested.emit)
        row.addWidget(self.cancel_btn)
        self.undo_btn = QPushButton(tr('  Undo'))
        self.undo_btn.setIcon(icons.get("prev", theme["text"], 15))
        self.undo_btn.setToolTip(tr('Put back what was on stage before  (Ctrl+Z)'))
        self.undo_btn.clicked.connect(self.undoRequested.emit)
        row.addWidget(self.undo_btn)
        self.pending = False
        self._undo_until = 0.0
        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self._tick)
        self.hide()

    def show_pending(self, title: str, detail: str, thumb: Optional[QPixmap]) -> None:
        self.pending = True
        self._ticker.stop()
        self._set_tag("PREVIEW", self.theme["accent"])
        self._set_thumb(thumb)
        self.title.setText(title)
        self.detail.setText(detail or tr("not on stage yet - TAKE puts it there"))
        self.take_btn.show()
        self.cancel_btn.show()
        self.undo_btn.hide()
        self.show()

    def clear_pending(self) -> None:
        self.pending = False
        if self._undo_until > time.monotonic():
            self._show_undo_row()
        else:
            self.hide()

    def show_done(self, title: str, thumb: Optional[QPixmap] = None) -> None:
        """A change went on stage: offer to take it back for a few seconds."""
        self._undo_until = time.monotonic() + self.UNDO_SECONDS
        self._done_title = title
        self._done_thumb = thumb
        if not self.pending:
            self._show_undo_row()

    def forget_undo(self) -> None:
        self._undo_until = 0.0
        if not self.pending:
            self._ticker.stop()
            self.hide()

    def undo_available(self) -> bool:
        return self._undo_until > time.monotonic()

    def _show_undo_row(self) -> None:
        self._set_tag("ON STAGE", self.theme["ok"])
        self._set_thumb(getattr(self, "_done_thumb", None))
        self.title.setText(getattr(self, "_done_title", ""))
        self.take_btn.hide()
        self.cancel_btn.hide()
        self.undo_btn.show()
        self._tick()
        self._ticker.start(250)
        self.show()

    def _tick(self) -> None:
        left = self._undo_until - time.monotonic()
        if left <= 0:
            self.forget_undo()
            return
        self.detail.setText(tr('undo for {0} more s').format(int(left + 0.99)))
        self.undo_btn.setText(tr('  Undo  ({0})').format(int(left + 0.99)))

    def _set_tag(self, text: str, colour: str) -> None:
        self.tag.setText(tr(text))
        self.tag.setStyleSheet(
            f"color: {colour}; font-size: 10px; font-weight: 800; letter-spacing: 1px;"
            f"border: 1px solid {colour}; border-radius: 7px; padding: 0px 7px;")

    def _set_thumb(self, pixmap: Optional[QPixmap]) -> None:
        if pixmap is None or pixmap.isNull():
            self.thumb.setPixmap(QPixmap())
            self.thumb.hide()
            return
        self.thumb.setPixmap(pixmap.scaled(self.thumb.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.thumb.show()


# --------------------------------------------------------------------------- #
# NOW / NEXT under every tab
# --------------------------------------------------------------------------- #

class ShowStrip(QFrame):
    """The running order, one line high, wherever the operator happens to be."""

    nextRequested = Signal()
    backRequested = Signal()
    openRequested = Signal()

    def __init__(self, icons, theme: dict) -> None:
        super().__init__()
        self.setObjectName("bar")
        self.theme = theme
        self.icons = icons
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 6, 8, 6)
        row.setSpacing(12)
        glyph = QLabel()
        glyph.setPixmap(icons.get("list", theme["muted"], 15).pixmap(15, 15))
        row.addWidget(glyph)
        self.now_caption = QLabel()
        self.now_caption.setObjectName("sectionTitle")
        row.addWidget(self.now_caption)
        self.now_title = QLabel()
        self.now_title.setStyleSheet("font-size: 14px; font-weight: 700;")
        self.now_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(self.now_title, 3)
        self.clock = QLabel()
        self.clock.setObjectName("timecode")
        row.addWidget(self.clock)
        arrow = QLabel("→")
        arrow.setObjectName("cardHint")
        row.addWidget(arrow)
        self.next_title = QLabel()
        self.next_title.setObjectName("cardHint")
        self.next_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(self.next_title, 3)
        self.auto = QLabel()
        self.auto.setStyleSheet(f"color: {theme['accent']}; font-weight: 600;")
        row.addWidget(self.auto)
        open_btn = QPushButton(tr('Running order'))
        open_btn.setObjectName("ghost")
        open_btn.setToolTip(tr('Open the Show tab'))
        open_btn.clicked.connect(self.openRequested.emit)
        row.addWidget(open_btn)
        back = QPushButton(tr('  Back'))
        back.setIcon(icons.get("prev", theme["text"], 14))
        back.setToolTip(tr('Previous step  (Page Up)'))
        back.clicked.connect(self.backRequested.emit)
        row.addWidget(back)
        self.next_btn = QPushButton(tr('  NEXT STEP'))
        self.next_btn.setObjectName("primary")
        self.next_btn.setIcon(icons.get("next", theme["ink"], 18))
        self.next_btn.setMinimumSize(160, 38)
        self.next_btn.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.next_btn.setToolTip(tr('Run the next step  (Page Down)'))
        self.next_btn.clicked.connect(self.nextRequested.emit)
        row.addWidget(self.next_btn)

    def set_emphasis(self, gold: bool) -> None:
        """Gold only where it is the one main action on screen."""
        name = "primary" if gold else ""
        if self.next_btn.objectName() != name:
            self.next_btn.setObjectName(name)
            self.next_btn.setIcon(self.icons.get("next", self.theme["ink"] if gold else self.theme["text"], 18))
            self.next_btn.style().unpolish(self.next_btn)
            self.next_btn.style().polish(self.next_btn)

    def set_state(self, caption: str, now: str, upcoming: str, clock: str, auto: str,
                  has_next: bool) -> None:
        self.now_caption.setText(caption)
        self.now_title.setText(now)
        self.next_title.setText(upcoming)
        self.clock.setText(clock)
        self.auto.setText(auto)
        self.next_btn.setEnabled(has_next)


# --------------------------------------------------------------------------- #
# Ready check
# --------------------------------------------------------------------------- #

class ReadyCheckDialog(QDialog):
    """
    Everything worth knowing before the doors open, on one page.

    `checks` returns rows of {"status": ok | warn | fail | info, "title",
    "detail", optional "action": (button text, key)}; a button calls
    `act(key)`. The page re-checks every second, so a clicker press or a
    screen being opened turns its row green while the dialog is up.
    """

    def __init__(self, checks: Callable[[], List[dict]], act: Callable[[str], None], theme: dict,
                 icons, parent=None) -> None:
        super().__init__(parent)
        self.checks = checks
        self.act = act
        self.theme = theme
        self.setWindowTitle(tr('Ready check'))
        self.setMinimumSize(640, 560)
        box = QVBoxLayout(self)
        box.setContentsMargins(22, 18, 22, 18)
        box.setSpacing(12)
        self.summary = QLabel()
        self.summary.setStyleSheet("font-size: 20px; font-weight: 700;")
        box.addWidget(self.summary)
        hint = QLabel(tr('Re-checked every second - press the clicker or open a screen and its row turns green.'))
        hint.setObjectName("cardHint")
        hint.setWordWrap(True)
        box.addWidget(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; } "
                             "QScrollArea > QWidget > QWidget { background: transparent; }")
        self.rows_host = QWidget()
        self.rows = QVBoxLayout(self.rows_host)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(6)
        scroll.setWidget(self.rows_host)
        box.addWidget(scroll, 1)
        buttons = QHBoxLayout()
        identify = QPushButton(tr('  Identify screens'))
        identify.setIcon(icons.get("monitor", theme["text"], 15))
        identify.setToolTip(tr('A big number on every monitor, for three seconds'))
        identify.clicked.connect(lambda: self.act("identify"))
        buttons.addWidget(identify)
        buttons.addStretch(1)
        close = QPushButton(tr('Close'))
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        box.addLayout(buttons)
        self._shown = None
        self.refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1000)

    def results(self) -> List[dict]:
        return list(self._shown or [])

    def refresh(self) -> None:
        rows = self.checks()
        signature = [(r["status"], r["title"], r.get("detail", ""), r.get("action")) for r in rows]
        if signature == self._shown_signature():
            return
        self._shown = rows
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for row in rows:
            self.rows.addWidget(self._row(row))
        self.rows.addStretch(1)
        fails = sum(1 for r in rows if r["status"] == "fail")
        warns = sum(1 for r in rows if r["status"] == "warn")
        if fails:
            text, colour = tr("{0} problem(s) to fix before the show").format(fails), self.theme["danger"]
        elif warns:
            text, colour = tr("Almost ready - {0} thing(s) to look at").format(warns), self.theme["warn"]
        else:
            text, colour = tr("Ready for the show  ✓"), self.theme["ok"]
        self.summary.setText(text)
        self.summary.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {colour};")

    def _shown_signature(self):
        if self._shown is None:
            return None
        return [(r["status"], r["title"], r.get("detail", ""), r.get("action")) for r in self._shown]

    def _row(self, data: dict) -> QWidget:
        colour = {"ok": self.theme["ok"], "warn": self.theme["warn"], "fail": self.theme["danger"],
                  "info": self.theme["muted"]}[data["status"]]
        frame = QFrame()
        frame.setObjectName("card")
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 9, 12, 9)
        row.setSpacing(12)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {colour}; font-size: 16px;")
        row.addWidget(dot, 0, Qt.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = QLabel(data["title"])
        title.setStyleSheet("font-size: 13px; font-weight: 600;")
        texts.addWidget(title)
        if data.get("detail"):
            detail = QLabel(data["detail"])
            detail.setObjectName("cardHint")
            detail.setWordWrap(True)
            texts.addWidget(detail)
        row.addLayout(texts, 1)
        action = data.get("action")
        if action:
            button = QPushButton(action[0])
            button.clicked.connect(lambda _c=False, key=action[1]: self._do(key))
            row.addWidget(button, 0, Qt.AlignVCenter)
        return frame

    def _do(self, key: str) -> None:
        self.act(key)
        self._shown = None
        self.refresh()


# --------------------------------------------------------------------------- #
# Presets as pictures
# --------------------------------------------------------------------------- #

class PresetTile(QWidget):
    """One preset: a picture of what it puts on the screens, and its name."""

    clicked = Signal(str)
    menuRequested = Signal(str, object)     # name, global position

    SIZE = QSize(116, 72)

    def __init__(self, name: str, picture: Optional[QPixmap], theme: dict) -> None:
        super().__init__()
        self.name = name
        self.picture = picture
        self.theme = theme
        self.state = ""                     # "" | "on" (on the screens) | "changed"
        self.selected = False
        self.setFixedSize(self.SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tr('{0} - click to put it on the screens; right-click for more').format(name))

    def set_state(self, state: str, selected: bool) -> None:
        self.state, self.selected = state, selected
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        theme = self.theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        frame = QRectF(1, 1, self.width() - 2, self.height() - 22)
        clip = QPainterPath()
        clip.addRoundedRect(frame, 7, 7)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#05070b"))
        p.drawPath(clip)
        if self.picture is not None and not self.picture.isNull():
            # cover the frame, cropping the middle out of the picture
            pw, ph = self.picture.width(), self.picture.height()
            scale = max(frame.width() / pw, frame.height() / ph)
            sw, sh = frame.width() / scale, frame.height() / scale
            source = QRectF((pw - sw) / 2, (ph - sh) / 2, sw, sh)
            p.save()
            p.setClipPath(clip)
            p.drawPixmap(frame, self.picture, source)
            p.restore()
        else:
            p.setPen(QColor(theme["muted"]))
            p.setFont(_font(10))
            p.drawText(frame, Qt.AlignCenter, tr("black"))
        colour = {"on": theme["ok"], "changed": theme["warn"]}.get(self.state)
        if colour:
            pen = QPen(QColor(colour), 2)
        elif self.selected:
            pen = QPen(QColor(theme["dim"]), 1.5)
        else:
            pen = QPen(QColor(theme["edge"]), 1)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(frame, 7, 7)
        if colour:
            tag = tr("ON SCREEN") if self.state == "on" else tr("CHANGED")
            p.setFont(_font(9, QFont.Bold))
            width = p.fontMetrics().horizontalAdvance(tag) + 12
            box = QRectF(frame.right() - width - 4, frame.top() + 4, width, 15)
            p.setPen(Qt.NoPen)
            fill = QColor(colour)
            fill.setAlpha(230)
            p.setBrush(fill)
            p.drawRoundedRect(box, 7, 7)
            p.setPen(QColor(theme["ink"]))
            p.drawText(box, Qt.AlignCenter, tag)
        p.setFont(_font(12, QFont.DemiBold))
        p.setPen(QColor(theme["text"]))
        name_rect = QRectF(2, self.height() - 20, self.width() - 4, 20)
        p.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self.name, Qt.ElideRight, int(name_rect.width())))
        p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.name)
        elif event.button() == Qt.RightButton:
            self.menuRequested.emit(self.name, event.globalPosition().toPoint())


class PresetStrip(QScrollArea):
    """Every preset as a picture, in a row; the one on the screens marked green."""

    presetClicked = Signal(str)
    menuRequested = Signal(str, object)

    def __init__(self, theme: dict) -> None:
        super().__init__()
        self.theme = theme
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFixedHeight(PresetTile.SIZE.height() + 10)
        self.setStyleSheet("QScrollArea { background: transparent; } "
                           "QScrollArea > QWidget > QWidget { background: transparent; }")
        host = QWidget()
        self.row = QHBoxLayout(host)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(10)
        self.row.addStretch(1)
        self.setWidget(host)
        self.tiles: Dict[str, PresetTile] = {}
        self.empty = QLabel(tr('No presets yet - set the screens up, then “Save as new…”'))
        self.empty.setObjectName("cardHint")
        self.row.insertWidget(0, self.empty)

    def set_presets(self, items: List[tuple]) -> None:
        """items: (name, picture) in order."""
        for tile in self.tiles.values():
            tile.setParent(None)
            tile.deleteLater()
        self.tiles = {}
        for position, (name, picture) in enumerate(items):
            tile = PresetTile(name, picture, self.theme)
            tile.clicked.connect(self.presetClicked.emit)
            tile.menuRequested.connect(self.menuRequested.emit)
            self.row.insertWidget(position, tile)
            self.tiles[name] = tile
        self.empty.setVisible(not items)

    def mark(self, loaded: Optional[str], changed: bool, selected: Optional[str]) -> None:
        for name, tile in self.tiles.items():
            state = ("changed" if changed else "on") if name == loaded else ""
            tile.set_state(state, name == selected)


# --------------------------------------------------------------------------- #
# Health, and the keys
# --------------------------------------------------------------------------- #

class HealthBar(QWidget):
    """
    The status bar's right side: a chip per thing that matters during a show,
    coloured by how it is. A click on any of them opens the ready check.
    """

    checkRequested = Signal()
    helpRequested = Signal()

    def __init__(self, theme: dict) -> None:
        super().__init__()
        self.theme = theme
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 4, 0)
        self.row.setSpacing(6)
        self.chips: List[QPushButton] = []
        self.help = QPushButton("?")
        self.help.setObjectName("healthChip")
        self.help.setToolTip(tr('Keyboard shortcuts'))
        self.help.setFixedWidth(30)
        self.help.clicked.connect(self.helpRequested.emit)
        self.row.addWidget(self.help)

    def set_items(self, items: List[tuple]) -> None:
        """items: (text, status, tooltip); status ok | warn | fail | info."""
        while len(self.chips) < len(items):
            chip = QPushButton()
            chip.setObjectName("healthChip")
            chip.clicked.connect(self.checkRequested.emit)
            self.row.insertWidget(len(self.chips), chip)
            self.chips.append(chip)
        for chip, (text, status, tip) in zip(self.chips, items):
            colour = {"ok": self.theme["ok"], "warn": self.theme["warn"], "fail": self.theme["danger"],
                      "info": self.theme["muted"]}[status]
            chip.setText(f"●  {text}")
            chip.setToolTip(tip + tr('\n\nClick for the ready check.'))
            chip.setStyleSheet(f"color: {colour};")
            chip.setProperty("status", status)
            chip.show()
        for chip in self.chips[len(items):]:
            chip.hide()


SHORTCUTS = (
    ("Running order", (("Page Down", "next step (the clicker's forward button)"),
                       ("Page Up", "step back"))),
    ("Screens", (("1  2  3", "choose Main / Sides / Top for the keys below"),
                 ("← →", "previous / next file in that screen's playlist"),
                 ("Space", "play / pause that screen's video"),
                 ("B", "BLACKOUT - every screen to black"),
                 ("Ctrl+O", "open the stage outputs"))),
    ("Preview → TAKE", (("Ctrl+Enter", "TAKE - put the waiting change on stage"),
                        ("Esc", "cancel it"),
                        ("Ctrl+Z", "undo the last change (for a few seconds)"))),
    ("Sound", (("F1 … F8", "play / pause a sound cue"),
               ("Shift+F1 … F8", "stop that cue"),
               ("Ctrl+Space", "stop all sound"))),
    ("Names on screen", (("Ctrl+→  Ctrl+←", "next / previous name"),
                         ("Ctrl+H", "hide the text"))),
    ("Slides (while on screen)", (("Page Down  →  Space", "next slide or animation"),
                                  ("Page Up  ←", "back"),
                                  ("B  /  .", "black the slides"),
                                  ("Esc", "end the presentation"))),
)


class ShortcutsDialog(QDialog):
    """Every key, in one place - instead of a line of small print under the window."""

    def __init__(self, theme: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr('Keyboard shortcuts'))
        self.setMinimumWidth(560)
        box = QVBoxLayout(self)
        box.setContentsMargins(22, 18, 22, 18)
        box.setSpacing(4)
        for section, keys in SHORTCUTS:
            title = QLabel(caps(tr(section)))
            title.setObjectName("sectionTitle")
            title.setContentsMargins(0, 10, 0, 2)
            box.addWidget(title)
            for key, meaning in keys:
                row = QHBoxLayout()
                label = QLabel(key)
                label.setFixedWidth(170)
                label.setStyleSheet(f"color: {theme['accent']}; font-weight: 600;")
                row.addWidget(label)
                text = QLabel(tr(meaning))
                text.setObjectName("cardHint")
                row.addWidget(text, 1)
                box.addLayout(row)
        close = QPushButton(tr('Close'))
        close.clicked.connect(self.accept)
        box.addSpacing(10)
        box.addWidget(close, 0, Qt.AlignRight)


# --------------------------------------------------------------------------- #
# Hold to confirm
# --------------------------------------------------------------------------- #

class HoldButton(QPushButton):
    """
    For what cannot be taken back: it acts only when held for a moment, a bar
    filling while it is held, so a stray tap - or a sleeve on the touch screen
    - does nothing. With `set_hold(False)` it is an ordinary button again.
    """

    HOLD_MS = 800

    def __init__(self, text: str, theme: dict, parent=None) -> None:
        super().__init__(text, parent)
        self.theme = theme
        self.hold = True
        self._progress = 0.0
        self._started = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_hold(self, on: bool) -> None:
        self.hold = on
        self._reset()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if not self.hold or event.button() != Qt.LeftButton or not self.isEnabled():
            super().mousePressEvent(event)
            return
        self._started = time.monotonic()
        self._progress = 0.0
        self._timer.start()
        self.setDown(True)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if not self.hold:
            super().mouseReleaseEvent(event)
            return
        early = self._timer.isActive()
        self._reset()
        if early:
            QToolTip.showText(self.mapToGlobal(QPointF(0, self.height()).toPoint()),
                              "Hold it down for a moment to confirm", self)
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self.hold and event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            event.ignore()               # no confirming by keyboard by accident
            return
        super().keyPressEvent(event)

    def _tick(self) -> None:
        self._progress = min(1.0, (time.monotonic() - self._started) * 1000.0 / self.HOLD_MS)
        self.update()
        if self._progress >= 1.0:
            self._reset()
            self.clicked.emit()

    def _reset(self) -> None:
        self._timer.stop()
        self._progress = 0.0
        self.setDown(False)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._progress <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 9, 9)
        p.setClipPath(clip)
        colour = QColor(self.theme["danger"])
        colour.setAlpha(110)
        p.fillRect(QRectF(0, 0, self.width() * self._progress, self.height()), colour)
        p.end()


# --------------------------------------------------------------------------- #
# After a crash
# --------------------------------------------------------------------------- #

class RecoveryDialog(QDialog):
    """
    The app stopped without being closed: offer to put the stage back as it was.
    Nobody at the desk (an unattended restart)? It puts it back by itself.
    """

    def __init__(self, when: str, lines: List[str], theme: dict, seconds: int = 20, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr('Put the stage back?'))
        self.setMinimumWidth(520)
        self.theme = theme
        self._left = seconds
        box = QVBoxLayout(self)
        box.setContentsMargins(22, 18, 22, 18)
        box.setSpacing(10)
        title = QLabel(tr('The app closed unexpectedly'))
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {theme['warn']};")
        box.addWidget(title)
        intro = QLabel(tr('It stopped at {0}. This was on the stage then:').format(when))
        intro.setObjectName("cardHint")
        intro.setWordWrap(True)
        box.addWidget(intro)
        for line in lines:
            label = QLabel("•  " + line)
            label.setWordWrap(True)
            box.addWidget(label)
        self.countdown = QLabel()
        self.countdown.setObjectName("cardHint")
        box.addWidget(self.countdown)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        fresh = QPushButton(tr('Start fresh'))
        fresh.clicked.connect(self.reject)
        buttons.addWidget(fresh)
        back = QPushButton(tr('  Put it back'))
        back.setObjectName("primary")
        back.setDefault(True)
        back.clicked.connect(self.accept)
        buttons.addWidget(back)
        box.addLayout(buttons)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    def _tick(self) -> None:
        if self._left <= 0:
            self._timer.stop()
            self.accept()
            return
        self.countdown.setText(tr('Putting it back by itself in {0} s…').format(self._left))
        self._left -= 1


# --------------------------------------------------------------------------- #
# Dark room
# --------------------------------------------------------------------------- #

class DimOverlay(QWidget):
    """
    A veil of black over the whole dashboard, for a dark hall. It is only
    paint: clicks, touches and keys go straight through to what is under it.
    """

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.amount = 0.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        window.installEventFilter(self)
        self.hide()

    def set_amount(self, amount: float) -> None:
        self.amount = amount
        self.setGeometry(self.parentWidget().rect())
        self.setVisible(amount > 0)
        self.raise_()
        self.update()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.parentWidget() and event.type() in (QEvent.Resize, QEvent.Show, QEvent.ChildAdded):
            self.setGeometry(watched.rect())
            if self.isVisible():
                self.raise_()
        return False

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, int(255 * self.amount)))
        painter.end()
