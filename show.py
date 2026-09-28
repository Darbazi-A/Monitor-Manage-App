"""
The running order: an event built as steps, played with one NEXT button.

A step says what each screen, the sound, the text and the ceiling marquee
should do - or that they should be left as they are. Steps are saved as they
are edited (shows.json, next to presets.json). The dashboard does the actual
work; this module holds the data, the editor and the NOW / NEXT display.

Kept free of main.py imports on purpose: main imports this, and the icons and
colours are handed in.
"""
from __future__ import annotations

import copy
import json
import os
import uuid
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFrame,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

ROLES = ("main", "sides", "top")
ROLE_NAMES = {"main": "Main Stage", "sides": "Side Screens", "top": "Top Screen"}

SCREEN_MODES = (("keep", "Leave as it is"), ("file", "Show a file"), ("black", "Black"))
SOUND_MODES = (("keep", "Leave as it is"), ("play", "Play a sound"),
               ("fade", "Fade the music out"), ("silence", "Fade out all sound"))
TEXT_MODES = (("keep", "Leave as it is"), ("show", "Show text"), ("hide", "Hide the text"))
MARQUEE_MODES = (("keep", "Leave as it is"), ("start", "Scroll this text"), ("stop", "Stop scrolling"))
SLIDES_MODES = (("keep", "Leave as it is"), ("start", "Start this presentation"),
                ("end", "End the presentation"))
SLIDES_FILTER = "Presentations (*.pdf *.pptx *.ppt *.ppsx *.pps *.pptm *.odp)"
ADVANCE_MODES = (("manual", "Wait for NEXT"), ("after", "Go on by itself after"),
                 ("video", "Go on when the Main Stage video ends"),
                 ("sound", "Go on when the sound ends"))

MEDIA_FILTER = "Media (*.mp4 *.mov *.m4v *.mkv *.avi *.wmv *.mpg *.mpeg *.jpg *.jpeg *.png *.bmp *.gif *.webp)"
AUDIO_FILTER = "Sound (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.wma *.opus)"


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #

def new_step(title: str = "New step") -> dict:
    return {
        "id": uuid.uuid4().hex,
        "title": title,
        "notes": "",
        "screens": {role: {"mode": "keep", "path": "", "loop": True, "audio": False} for role in ROLES},
        "sound": {"mode": "keep", "path": "", "loop": False, "level": 90},
        "text": {"mode": "keep", "title": "", "subtitle": "", "target": "main"},
        "marquee": {"mode": "keep", "text": ""},
        "slides": {"mode": "keep", "path": "", "target": "main"},
        "advance": {"mode": "manual", "seconds": 10},
    }


def normalise_step(data: dict) -> dict:
    """Fill in anything a saved step (or an older file) lacks."""
    step = new_step()
    if not isinstance(data, dict):
        return step
    for key in ("id", "title", "notes"):
        if isinstance(data.get(key), str):
            step[key] = data[key]
    for role in ROLES:
        step["screens"][role].update((data.get("screens") or {}).get(role) or {})
    for part in ("sound", "text", "marquee", "slides", "advance"):
        step[part].update(data.get(part) or {})
    return step


def fold(steps: List[dict], index: int) -> dict:
    """
    What should be on stage once steps 0..index have run: for each element, the
    last step that did not leave it alone. Going back or jumping uses this, so
    a jump lands in the same state as walking there step by step.
    """
    state = {"screens": {role: None for role in ROLES}, "sound": None, "text": None, "marquee": None,
             "slides": None}
    for step in steps[: index + 1]:
        for role in ROLES:
            if step["screens"][role]["mode"] != "keep":
                state["screens"][role] = step["screens"][role]
                slides = state["slides"]
                if slides is not None and slides["mode"] == "start" and slides.get("target") == role:
                    state["slides"] = None      # the screen went to something else

        for part in ("sound", "text", "marquee", "slides"):
            if step[part]["mode"] != "keep":
                state[part] = step[part]
    return state


def summary(step: dict) -> str:
    """One line saying what a step does."""
    parts = []
    for role, short in (("main", "Main"), ("sides", "Sides"), ("top", "Top")):
        screen = step["screens"][role]
        if screen["mode"] == "file":
            parts.append(f"{short}: {os.path.basename(screen['path']) or '?'}")
        elif screen["mode"] == "black":
            parts.append(f"{short}: black")
    sound = step["sound"]
    if sound["mode"] == "play":
        parts.append("♪ " + (os.path.basename(sound["path"]) or "?"))
    elif sound["mode"] == "fade":
        parts.append("♪ fade out")
    elif sound["mode"] == "silence":
        parts.append("♪ all quiet")
    text = step["text"]
    if text["mode"] == "show":
        parts.append(f"T “{text['title']}”")
    elif text["mode"] == "hide":
        parts.append("T hidden")
    marquee = step["marquee"]
    if marquee["mode"] == "start":
        parts.append("⇢ " + marquee["text"][:24])
    elif marquee["mode"] == "stop":
        parts.append("⇢ stop")
    slides = step["slides"]
    if slides["mode"] == "start":
        parts.append("▣ " + (os.path.basename(slides["path"]) or "?"))
    elif slides["mode"] == "end":
        parts.append("▣ end")
    advance = step["advance"]
    if advance["mode"] == "after":
        parts.append(f"auto {advance['seconds']} s")
    elif advance["mode"] == "video":
        parts.append("auto at video end")
    elif advance["mode"] == "sound":
        parts.append("auto at sound end")
    return "   ·   ".join(parts) if parts else "changes nothing"


def missing_files(steps: List[dict]) -> List[str]:
    paths = []
    for step in steps:
        for role in ROLES:
            screen = step["screens"][role]
            if screen["mode"] == "file" and screen["path"]:
                paths.append(screen["path"])
        if step["sound"]["mode"] == "play" and step["sound"]["path"]:
            paths.append(step["sound"]["path"])
        if step["slides"]["mode"] == "start" and step["slides"]["path"]:
            paths.append(step["slides"]["path"])
    return sorted({p for p in paths if not os.path.isfile(p)})


class ShowStore:
    """Named shows in one JSON file."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.shows: Dict[str, dict] = {}
        self.current = ""
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            for name, show in (payload.get("shows") or {}).items():
                self.shows[name] = {"steps": [normalise_step(s) for s in show.get("steps", [])]}
            self.current = payload.get("current", "")
        except (OSError, ValueError, AttributeError):
            pass
        if not self.shows:
            self.shows["My event"] = {"steps": []}
        if self.current not in self.shows:
            self.current = self.names()[0]

    def names(self) -> List[str]:
        return sorted(self.shows, key=str.lower)

    def steps(self, name: Optional[str] = None) -> List[dict]:
        return self.shows[name or self.current]["steps"]

    def save(self) -> Optional[str]:
        try:
            with open(self.path, "w", encoding="utf-8") as handle:
                json.dump({"current": self.current, "shows": self.shows}, handle, indent=1,
                          ensure_ascii=False)
            return None
        except OSError as exc:
            return str(exc)


# --------------------------------------------------------------------------- #
# The step list
# --------------------------------------------------------------------------- #

class StepDelegate(QStyledItemDelegate):
    """Number, title and what the step does; NOW and NEXT marked."""

    def __init__(self, tab: "ShowTab") -> None:
        super().__init__(tab)
        self.tab = tab

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(200, self.tab.row_height)

    def paint(self, painter: QPainter, option, index) -> None:
        theme = self.tab.theme
        row = index.row()
        step = self.tab.step_at(row)
        if step is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(option.rect).adjusted(2, 2, -2, -2)
        now = row == self.tab.running_index
        upcoming = row == self.tab.running_index + 1
        selected = bool(option.state & QStyle.State_Selected)
        painter.setPen(QPen(QColor(theme["accent"] if selected else theme["edge"]), 1.2 if selected else 1))
        painter.setBrush(QColor("#1d2533" if now else theme["raised"] if selected else theme["card"]))
        painter.drawRoundedRect(rect, 9, 9)
        if now:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme["accent"]))
            painter.drawRoundedRect(QRectF(rect.left(), rect.top() + 6, 4, rect.height() - 12), 2, 2)
        # number
        badge = QRectF(rect.left() + 12, rect.center().y() - 14, 28, 28)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme["accent"] if now else "#232c3d"))
        painter.drawEllipse(badge)
        painter.setPen(QColor(theme["ink"] if now else theme["dim"]))
        painter.setFont(_font(9, QFont.Bold))
        painter.drawText(badge, Qt.AlignCenter, str(row + 1))
        # text
        left = badge.right() + 12
        tag_w = 58 if (now or upcoming) else 0
        text_rect = QRectF(left, rect.top() + 7, rect.right() - left - tag_w - 10, rect.height() / 2 - 4)
        painter.setPen(QColor(theme["text"]))
        painter.setFont(_font(10.5, QFont.DemiBold))
        metrics = painter.fontMetrics()
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter,
                         metrics.elidedText(step["title"] or "Untitled", Qt.ElideRight, int(text_rect.width())))
        sub_rect = QRectF(left, rect.center().y() + 1, text_rect.width(), rect.height() / 2 - 8)
        painter.setPen(QColor(theme["muted"]))
        painter.setFont(_font(8.5))
        metrics = painter.fontMetrics()
        painter.drawText(sub_rect, Qt.AlignLeft | Qt.AlignVCenter,
                         metrics.elidedText(summary(step), Qt.ElideRight, int(sub_rect.width())))
        if now or upcoming:
            tag = QRectF(rect.right() - tag_w - 6, rect.center().y() - 11, tag_w, 22)
            colour = QColor(theme["accent"] if now else theme["ok"])
            painter.setPen(QPen(colour, 1))
            fill = QColor(colour)
            fill.setAlpha(40)
            painter.setBrush(fill)
            painter.drawRoundedRect(tag, 11, 11)
            painter.setPen(colour)
            painter.setFont(_font(7.5, QFont.Bold))
            painter.drawText(tag, Qt.AlignCenter, "NOW" if now else "NEXT")
        painter.restore()


def _font(size: float, weight: int = QFont.Normal) -> QFont:
    font = QFont("Segoe UI")
    font.setPointSizeF(size)
    font.setWeight(QFont.Weight(weight))
    return font


# --------------------------------------------------------------------------- #
# Editor rows
# --------------------------------------------------------------------------- #

class FileField(QWidget):
    """A file name with a browse button; files can be dropped on it."""

    changed = Signal(str)

    def __init__(self, filter_text: str, icons, theme: dict, start_dir: Callable[[], str]) -> None:
        super().__init__()
        self.filter_text = filter_text
        self.start_dir = start_dir
        self._path = ""
        self.setAcceptDrops(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.label = QLineEdit()
        self.label.setReadOnly(True)
        self.label.setPlaceholderText("drop a file here or press …")
        self.label.setMinimumWidth(120)
        layout.addWidget(self.label, 1)
        browse = QPushButton()
        browse.setIcon(icons.get("folder", theme["text"], 15))
        browse.setToolTip("Choose a file")
        browse.clicked.connect(self._browse)
        layout.addWidget(browse)

    def path(self) -> str:
        return self._path

    def set_path(self, path: str) -> None:
        self._path = path or ""
        self.label.setText(os.path.basename(self._path))
        self.label.setToolTip(self._path)
        missing = bool(self._path) and not os.path.isfile(self._path)
        self.label.setStyleSheet("color: #e0605c;" if missing else "")
        if missing:
            self.label.setToolTip(self._path + "\n\nThis file is missing.")

    def _browse(self) -> None:
        start = os.path.dirname(self._path) if self._path else self.start_dir()
        path, _ = QFileDialog.getOpenFileName(self, "Choose a file", start, self.filter_text + ";;All files (*)")
        if path:
            self.set_path(os.path.normpath(path))
            self.changed.emit(self._path)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls:
            self.set_path(os.path.normpath(urls[0].toLocalFile()))
            self.changed.emit(self._path)


def _combo(options) -> QComboBox:
    combo = QComboBox()
    for value, caption in options:
        combo.addItem(caption, value)
    return combo


def _set_combo(combo: QComboBox, value: str) -> None:
    combo.blockSignals(True)
    combo.setCurrentIndex(max(0, combo.findData(value)))
    combo.blockSignals(False)


def _caption(text: str, width: int = 96) -> QLabel:
    label = QLabel(text)
    label.setObjectName("cardHint")
    label.setFixedWidth(width)
    return label


# --------------------------------------------------------------------------- #
# The tab
# --------------------------------------------------------------------------- #

class ShowTab(QWidget):
    """Running order: NOW / NEXT with the big button above, the steps and their editor below."""

    goRequested = Signal(int)
    nextRequested = Signal()
    backRequested = Signal()
    restartRequested = Signal()
    captureRequested = Signal()
    remoteRequested = Signal()
    showSwitched = Signal()
    edited = Signal()

    def __init__(self, store: ShowStore, icons, theme: dict, touch: bool = False) -> None:
        super().__init__()
        self.store = store
        self.icons = icons
        self.theme = theme
        self.running_index = -1
        self.row_height = 62 if touch else 54
        self._loading = False
        self._last_dir = os.path.expanduser("~")
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.store.save)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 10, 0, 0)
        outer.setSpacing(10)
        outer.addWidget(self._build_run_card())
        outer.addWidget(self._build_toolbar())

        body = QHBoxLayout()
        body.setSpacing(10)
        body.addWidget(self._build_list_card(), 5)
        body.addWidget(self._build_editor_card(), 6)
        outer.addLayout(body, 1)

        self._fill_show_combo()
        self._reload_list()

    # -- building ------------------------------------------------------------ #
    def _build_run_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        row = QHBoxLayout(card)
        row.setContentsMargins(18, 14, 18, 14)
        row.setSpacing(18)

        now = QVBoxLayout()
        now.setSpacing(2)
        self.now_caption = QLabel("READY")
        self.now_caption.setObjectName("sectionTitle")
        now.addWidget(self.now_caption)
        self.now_title = QLabel("Press NEXT to start")
        self.now_title.setStyleSheet("font-size: 22px; font-weight: 700;")
        self.now_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        now.addWidget(self.now_title)
        self.now_notes = QLabel("")
        self.now_notes.setObjectName("cardHint")
        self.now_notes.setWordWrap(True)
        self.now_notes.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.now_notes.setMaximumHeight(40)
        now.addWidget(self.now_notes)
        self.now_clock = QLabel("")
        self.now_clock.setObjectName("timecode")
        now.addWidget(self.now_clock)
        now.addStretch(1)
        row.addLayout(now, 5)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background: {self.theme['edge']};")
        row.addWidget(divider)

        upcoming = QVBoxLayout()
        upcoming.setSpacing(2)
        caption = QLabel("NEXT")
        caption.setObjectName("sectionTitle")
        upcoming.addWidget(caption)
        self.next_title = QLabel("—")
        self.next_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.next_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        upcoming.addWidget(self.next_title)
        self.next_summary = QLabel("")
        self.next_summary.setObjectName("cardHint")
        self.next_summary.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        upcoming.addWidget(self.next_summary)
        self.next_auto = QLabel("")
        self.next_auto.setStyleSheet(f"color: {self.theme['accent']}; font-weight: 600;")
        upcoming.addWidget(self.next_auto)
        upcoming.addStretch(1)
        row.addLayout(upcoming, 4)

        buttons = QVBoxLayout()
        buttons.setSpacing(8)
        self.next_btn = QPushButton("  NEXT")
        self.next_btn.setObjectName("primary")
        self.next_btn.setIcon(self.icons.get("next", "#0b0e13", 22))
        self.next_btn.setIconSize(QSize(22, 22))
        self.next_btn.setMinimumSize(210, 64)
        self.next_btn.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.next_btn.setToolTip("Run the next step  (Page Down - a presenter clicker works too)")
        self.next_btn.clicked.connect(self.nextRequested.emit)
        buttons.addWidget(self.next_btn)
        small = QHBoxLayout()
        small.setSpacing(6)
        back = QPushButton("  Back")
        back.setIcon(self.icons.get("prev", self.theme["text"], 15))
        back.setToolTip("Go back one step  (Page Up)")
        back.clicked.connect(self.backRequested.emit)
        small.addWidget(back, 1)
        restart = QPushButton("  Start over")
        restart.setIcon(self.icons.get("refresh", self.theme["text"], 15))
        restart.setToolTip("Back to before step 1. Nothing on stage changes until NEXT.")
        restart.clicked.connect(self.restartRequested.emit)
        small.addWidget(restart, 1)
        buttons.addLayout(small)
        row.addLayout(buttons)
        return card

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("bar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(8)
        glyph = QLabel()
        glyph.setPixmap(self.icons.get("list", self.theme["muted"], 16).pixmap(16, 16))
        row.addWidget(glyph)
        caption = QLabel("Running order")
        caption.setObjectName("sectionTitle")
        row.addWidget(caption)
        self.show_combo = QComboBox()
        self.show_combo.setMinimumWidth(220)
        self.show_combo.currentIndexChanged.connect(self._on_show_chosen)
        row.addWidget(self.show_combo)
        for text, icon, tip, handler in (
                ("  New", "plus", "Start a new running order", self._new_show),
                ("  Rename", "text", "Rename this running order", self._rename_show),
                ("  Copy", "save", "Make a copy to change for another event", self._copy_show),
                ("  Delete", "trash", "Delete this running order", self._delete_show)):
            button = QPushButton(text)
            button.setIcon(self.icons.get(icon, self.theme["text"], 15))
            button.setToolTip(tip)
            button.clicked.connect(handler)
            row.addWidget(button)
        self.missing_label = QLabel("")
        self.missing_label.setStyleSheet(f"color: {self.theme['warn']}; font-weight: 600;")
        row.addWidget(self.missing_label)
        row.addStretch(1)
        saved = QLabel("saved as you edit")
        saved.setObjectName("keyHint")
        row.addWidget(saved)
        self.remote_btn = QPushButton("  Phone remote")
        self.remote_btn.setIcon(self.icons.get("monitor", self.theme["text"], 15))
        self.remote_btn.setToolTip("Run the show from a phone or tablet on the same Wi-Fi")
        self.remote_btn.clicked.connect(self.remoteRequested.emit)
        row.addWidget(self.remote_btn)
        return bar

    def _build_list_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        box = QVBoxLayout(card)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(8)
        self.list = QListWidget()
        self.list.setObjectName("stepList")
        self.list.setItemDelegate(StepDelegate(self))
        self.list.setUniformItemSizes(True)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.setStyleSheet("QListWidget#stepList { background: transparent; border: none; padding: 0px; }"
                                "QListWidget#stepList::item { padding: 0px; border: none; }"
                                "QListWidget#stepList::item:selected { background: transparent; }")
        self.list.currentRowChanged.connect(self._on_row_chosen)
        self.list.itemDoubleClicked.connect(lambda item: self.goRequested.emit(self.list.row(item)))
        self.list.model().rowsMoved.connect(self._on_rows_moved)
        box.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        for text, icon, tip, handler in (
                ("  Step", "plus", "Add a step after the selected one", self._add_step),
                ("  From stage", "target", "Add a step that recreates what is on the screens right now",
                 self.captureRequested.emit),
                ("", "save", "Duplicate the selected step", self._duplicate_step),
                ("", "trash", "Delete the selected step", self._delete_step)):
            button = QPushButton(text)
            button.setIcon(self.icons.get(icon, self.theme["text"], 15))
            button.setToolTip(tip)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        buttons.addStretch(1)
        up = QPushButton("▲")
        up.setToolTip("Move the step up")
        up.clicked.connect(lambda: self._move_step(-1))
        down = QPushButton("▼")
        down.setToolTip("Move the step down")
        down.clicked.connect(lambda: self._move_step(1))
        buttons.addWidget(up)
        buttons.addWidget(down)
        box.addLayout(buttons)
        return card

    def _build_editor_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(4, 4, 4, 4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; } "
                             "QScrollArea > QWidget > QWidget { background: transparent; }")
        outer.addWidget(scroll)
        page = QWidget()
        scroll.setWidget(page)
        self.editor = page
        form = QVBoxLayout(page)
        form.setContentsMargins(12, 10, 12, 10)
        form.setSpacing(8)

        head = QHBoxLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Step name - e.g. Anthem, Welcome speech, Awards")
        self.title_edit.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.title_edit.textEdited.connect(lambda text: self._edit(lambda s: s.__setitem__("title", text)))
        head.addWidget(self.title_edit, 1)
        self.go_btn = QPushButton("  Go to this step")
        self.go_btn.setIcon(self.icons.get("play", self.theme["text"], 14))
        self.go_btn.setToolTip("Put this step on stage now (double-click a step does the same)")
        self.go_btn.clicked.connect(lambda: self.goRequested.emit(self.list.currentRow()))
        head.addWidget(self.go_btn)
        form.addLayout(head)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("Notes for whoever runs the show: who speaks, what to wait for…")
        self.notes_edit.setFixedHeight(54)
        self.notes_edit.textChanged.connect(self._on_notes)
        form.addWidget(self.notes_edit)

        form.addWidget(self._section("Screens"))
        self.screen_rows: Dict[str, dict] = {}
        for role in ROLES:
            form.addLayout(self._screen_row(role))

        form.addWidget(self._section("Sound"))
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(_caption("Sound"))
        self.sound_mode = _combo(SOUND_MODES)
        self.sound_mode.currentIndexChanged.connect(self._on_sound)
        row.addWidget(self.sound_mode)
        self.sound_file = FileField(AUDIO_FILTER, self.icons, self.theme, lambda: self._last_dir)
        self.sound_file.changed.connect(lambda path: self._on_file_chosen(path, self._on_sound))
        row.addWidget(self.sound_file, 1)
        self.sound_loop = QCheckBox("Repeat")
        self.sound_loop.setToolTip("Loop it - for background music under a scene")
        self.sound_loop.toggled.connect(self._on_sound)
        row.addWidget(self.sound_loop)
        form.addLayout(row)

        form.addWidget(self._section("Words on screen"))
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(_caption("Text"))
        self.text_mode = _combo(TEXT_MODES)
        self.text_mode.currentIndexChanged.connect(self._on_text)
        row.addWidget(self.text_mode)
        self.text_title = QLineEdit()
        self.text_title.setPlaceholderText("Name")
        self.text_title.textEdited.connect(self._on_text)
        row.addWidget(self.text_title, 2)
        self.text_sub = QLineEdit()
        self.text_sub.setPlaceholderText("Second line (optional)")
        self.text_sub.textEdited.connect(self._on_text)
        row.addWidget(self.text_sub, 2)
        self.text_target = QComboBox()
        for role in ROLES:
            self.text_target.addItem(ROLE_NAMES[role], role)
        self.text_target.setToolTip("Which screen the text appears on (styled on the Text tab)")
        self.text_target.currentIndexChanged.connect(self._on_text)
        row.addWidget(self.text_target)
        form.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(_caption("Top strip"))
        self.marquee_mode = _combo(MARQUEE_MODES)
        self.marquee_mode.currentIndexChanged.connect(self._on_marquee)
        row.addWidget(self.marquee_mode)
        self.marquee_text = QLineEdit()
        self.marquee_text.setPlaceholderText("Text to scroll across the ceiling strip")
        self.marquee_text.textEdited.connect(self._on_marquee)
        row.addWidget(self.marquee_text, 1)
        form.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(_caption("Presentation"))
        self.slides_mode = _combo(SLIDES_MODES)
        self.slides_mode.currentIndexChanged.connect(self._on_slides)
        row.addWidget(self.slides_mode)
        self.slides_file = FileField(SLIDES_FILTER, self.icons, self.theme, lambda: self._last_dir)
        self.slides_file.changed.connect(lambda path: self._on_slides_file(path))
        row.addWidget(self.slides_file, 1)
        self.slides_target = QComboBox()
        for role in ROLES:
            self.slides_target.addItem(ROLE_NAMES[role], role)
        self.slides_target.setToolTip("Which screen the slides appear on")
        self.slides_target.currentIndexChanged.connect(self._on_slides)
        row.addWidget(self.slides_target)
        form.addLayout(row)

        form.addWidget(self._section("Then"))
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(_caption("Next step"))
        self.advance_mode = _combo(ADVANCE_MODES)
        self.advance_mode.currentIndexChanged.connect(self._on_advance)
        row.addWidget(self.advance_mode, 1)
        self.advance_seconds = QSpinBox()
        self.advance_seconds.setRange(1, 3600)
        self.advance_seconds.setSuffix(" s")
        self.advance_seconds.valueChanged.connect(self._on_advance)
        row.addWidget(self.advance_seconds)
        form.addLayout(row)
        form.addStretch(1)
        self.empty_note = QLabel("Add a step with “+ Step”, or set the screens up on the Live tab and "
                                 "press “From stage”.")
        self.empty_note.setObjectName("cardHint")
        self.empty_note.setWordWrap(True)
        form.addWidget(self.empty_note)
        return card

    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        label.setContentsMargins(0, 6, 0, 0)
        return label

    def _screen_row(self, role: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(_caption(ROLE_NAMES[role]))
        mode = _combo(SCREEN_MODES)
        mode.currentIndexChanged.connect(lambda _i, r=role: self._on_screen(r))
        row.addWidget(mode)
        field = FileField(MEDIA_FILTER, self.icons, self.theme, lambda: self._last_dir)
        field.changed.connect(lambda path, r=role: self._on_file_chosen(path, lambda: self._on_screen(r), r))
        row.addWidget(field, 1)
        loop = QCheckBox("Repeat")
        loop.setToolTip("Loop the video - off to play a clip once (and to use “when the video ends”)")
        loop.toggled.connect(lambda _on, r=role: self._on_screen(r))
        row.addWidget(loop)
        audio = QCheckBox("Sound")
        audio.setToolTip("Play the video's own sound")
        audio.toggled.connect(lambda _on, r=role: self._on_screen(r))
        row.addWidget(audio)
        self.screen_rows[role] = {"mode": mode, "file": field, "loop": loop, "audio": audio}
        return row

    # -- shows --------------------------------------------------------------- #
    def _fill_show_combo(self) -> None:
        self.show_combo.blockSignals(True)
        self.show_combo.clear()
        self.show_combo.addItems(self.store.names())
        self.show_combo.setCurrentText(self.store.current)
        self.show_combo.blockSignals(False)

    def _on_show_chosen(self) -> None:
        name = self.show_combo.currentText()
        if name and name in self.store.shows and name != self.store.current:
            self.store.current = name
            self._save_soon()
            self._reload_list()
            self.showSwitched.emit()

    def _ask_name(self, title: str, default: str) -> Optional[str]:
        name, ok = QInputDialog.getText(self, title, "Name:", text=default)
        name = name.strip()
        if not ok or not name:
            return None
        if name in self.store.shows and name != self.store.current:
            QMessageBox.information(self, title, f"There is already a running order called “{name}”.")
            return None
        return name

    def _new_show(self) -> None:
        name = self._ask_name("New running order", "")
        if name:
            self.store.shows[name] = {"steps": []}
            self._switch_to(name)

    def _rename_show(self) -> None:
        old = self.store.current
        name = self._ask_name("Rename", old)
        if name and name != old:
            self.store.shows[name] = self.store.shows.pop(old)
            self._switch_to(name)

    def _copy_show(self) -> None:
        name = self._ask_name("Copy running order", self.store.current + " (copy)")
        if name:
            steps = copy.deepcopy(self.store.steps())
            for step in steps:
                step["id"] = uuid.uuid4().hex
            self.store.shows[name] = {"steps": steps}
            self._switch_to(name)

    def _delete_show(self) -> None:
        name = self.store.current
        if QMessageBox.question(self, "Delete", f"Delete the running order “{name}”?") != QMessageBox.Yes:
            return
        del self.store.shows[name]
        if not self.store.shows:
            self.store.shows["My event"] = {"steps": []}
        self._switch_to(self.store.names()[0])

    def _switch_to(self, name: str) -> None:
        self.store.current = name
        self._fill_show_combo()
        self._save_soon()
        self._reload_list()
        self.showSwitched.emit()

    # -- steps --------------------------------------------------------------- #
    def steps(self) -> List[dict]:
        return self.store.steps()

    def step_at(self, row: int) -> Optional[dict]:
        steps = self.steps()
        return steps[row] if 0 <= row < len(steps) else None

    def _reload_list(self, select: Optional[int] = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for step in self.steps():
            item = QListWidgetItem(step["title"])
            item.setData(Qt.UserRole, step["id"])
            self.list.addItem(item)
        self.list.blockSignals(False)
        if self.steps():
            self.list.setCurrentRow(min(max(0, select if select is not None else 0), len(self.steps()) - 1))
        self._load_editor()
        self._refresh_missing()

    def _on_rows_moved(self, *_args) -> None:
        order = [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]
        by_id = {step["id"]: step for step in self.steps()}
        self.store.shows[self.store.current]["steps"] = [by_id[i] for i in order if i in by_id]
        self._changed()

    def _move_step(self, delta: int) -> None:
        row = self.list.currentRow()
        steps = self.steps()
        target = row + delta
        if row < 0 or not 0 <= target < len(steps):
            return
        steps[row], steps[target] = steps[target], steps[row]
        self._reload_list(target)
        self._changed()

    def add_step(self, step: dict, after: Optional[int] = None) -> None:
        steps = self.steps()
        row = self.list.currentRow() if after is None else after
        at = row + 1 if 0 <= row < len(steps) else len(steps)
        steps.insert(at, normalise_step(step))
        self._reload_list(at)
        self._changed()
        self.title_edit.setFocus()
        self.title_edit.selectAll()

    def _add_step(self) -> None:
        self.add_step(new_step(f"Step {len(self.steps()) + 1}"))

    def _duplicate_step(self) -> None:
        step = self.step_at(self.list.currentRow())
        if step is not None:
            clone = copy.deepcopy(step)
            clone["id"] = uuid.uuid4().hex
            clone["title"] = step["title"] + " (copy)"
            self.add_step(clone)

    def _delete_step(self) -> None:
        row = self.list.currentRow()
        step = self.step_at(row)
        if step is None:
            return
        if QMessageBox.question(self, "Delete step", f"Delete “{step['title']}”?") != QMessageBox.Yes:
            return
        del self.steps()[row]
        self._reload_list(max(0, row - 1))
        self._changed()

    def _on_row_chosen(self, _row: int) -> None:
        self._load_editor()

    # -- editor -------------------------------------------------------------- #
    def _current(self) -> Optional[dict]:
        return self.step_at(self.list.currentRow())

    def _load_editor(self) -> None:
        step = self._current()
        self._loading = True
        enabled = step is not None
        for widget in self.editor.findChildren(QWidget):
            if widget is not self.empty_note:
                widget.setEnabled(enabled)
        self.empty_note.setVisible(not enabled)
        if step is not None:
            self.title_edit.setText(step["title"])
            self.notes_edit.setPlainText(step["notes"])
            for role in ROLES:
                data, row = step["screens"][role], self.screen_rows[role]
                _set_combo(row["mode"], data["mode"])
                row["file"].set_path(data["path"])
                for key in ("loop", "audio"):
                    row[key].blockSignals(True)
                    row[key].setChecked(bool(data[key]))
                    row[key].blockSignals(False)
            sound = step["sound"]
            _set_combo(self.sound_mode, sound["mode"])
            self.sound_file.set_path(sound["path"])
            self.sound_loop.blockSignals(True)
            self.sound_loop.setChecked(bool(sound["loop"]))
            self.sound_loop.blockSignals(False)
            text = step["text"]
            _set_combo(self.text_mode, text["mode"])
            self.text_title.setText(text["title"])
            self.text_sub.setText(text["subtitle"])
            _set_combo(self.text_target, text["target"])
            _set_combo(self.marquee_mode, step["marquee"]["mode"])
            self.marquee_text.setText(step["marquee"]["text"])
            _set_combo(self.slides_mode, step["slides"]["mode"])
            self.slides_file.set_path(step["slides"]["path"])
            _set_combo(self.slides_target, step["slides"]["target"])
            _set_combo(self.advance_mode, step["advance"]["mode"])
            self.advance_seconds.blockSignals(True)
            self.advance_seconds.setValue(int(step["advance"]["seconds"]))
            self.advance_seconds.blockSignals(False)
        self._loading = False
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        """Only the controls that mean something for the chosen action are live."""
        if self._current() is None:
            return
        for row in self.screen_rows.values():
            showing = row["mode"].currentData() == "file"
            for key in ("file", "loop", "audio"):
                row[key].setEnabled(showing)
        playing = self.sound_mode.currentData() == "play"
        self.sound_file.setEnabled(playing)
        self.sound_loop.setEnabled(playing)
        text = self.text_mode.currentData() == "show"
        for widget in (self.text_title, self.text_sub, self.text_target):
            widget.setEnabled(text)
        self.marquee_text.setEnabled(self.marquee_mode.currentData() == "start")
        starting = self.slides_mode.currentData() == "start"
        self.slides_file.setEnabled(starting)
        self.slides_target.setEnabled(starting)
        self.advance_seconds.setVisible(self.advance_mode.currentData() == "after")

    def _edit(self, change: Callable[[dict], None]) -> None:
        if self._loading:
            return
        step = self._current()
        if step is None:
            return
        change(step)
        self._changed()

    def _changed(self) -> None:
        self._sync_enabled()
        self.list.viewport().update()
        self._refresh_missing()
        self._save_soon()
        self.edited.emit()

    def _save_soon(self) -> None:
        self._save_timer.start(500)

    def _on_notes(self) -> None:
        self._edit(lambda s: s.__setitem__("notes", self.notes_edit.toPlainText()))

    def _on_file_chosen(self, path: str, then: Callable[[], None], role: Optional[str] = None) -> None:
        self._last_dir = os.path.dirname(path)
        # choosing a file means "show it": switch the action over for the operator
        if role is not None:
            _set_combo(self.screen_rows[role]["mode"], "file")
        else:
            _set_combo(self.sound_mode, "play")
        then()

    def _on_screen(self, role: str) -> None:
        row = self.screen_rows[role]
        self._edit(lambda s: s["screens"][role].update(
            mode=row["mode"].currentData(), path=row["file"].path(),
            loop=row["loop"].isChecked(), audio=row["audio"].isChecked()))

    def _on_sound(self, *_args) -> None:
        self._edit(lambda s: s["sound"].update(
            mode=self.sound_mode.currentData(), path=self.sound_file.path(),
            loop=self.sound_loop.isChecked()))

    def _on_text(self, *_args) -> None:
        self._edit(lambda s: s["text"].update(
            mode=self.text_mode.currentData(), title=self.text_title.text(),
            subtitle=self.text_sub.text(), target=self.text_target.currentData()))

    def _on_marquee(self, *_args) -> None:
        self._edit(lambda s: s["marquee"].update(
            mode=self.marquee_mode.currentData(), text=self.marquee_text.text()))

    def _on_slides(self, *_args) -> None:
        self._edit(lambda s: s["slides"].update(
            mode=self.slides_mode.currentData(), path=self.slides_file.path(),
            target=self.slides_target.currentData()))

    def _on_slides_file(self, path: str) -> None:
        self._last_dir = os.path.dirname(path)
        _set_combo(self.slides_mode, "start")
        self._on_slides()

    def _on_advance(self, *_args) -> None:
        self._edit(lambda s: s["advance"].update(
            mode=self.advance_mode.currentData(), seconds=self.advance_seconds.value()))

    def _refresh_missing(self) -> None:
        gone = missing_files(self.steps())
        self.missing_label.setText(f"⚠ {len(gone)} file(s) missing" if gone else "")
        self.missing_label.setToolTip("\n".join(gone))

    # -- running ------------------------------------------------------------- #
    def set_running(self, index: int) -> None:
        self.running_index = index
        steps = self.steps()
        now = self.step_at(index)
        upcoming = self.step_at(index + 1)
        if now is None:
            self.now_caption.setText("READY" if steps else "NO STEPS YET")
            self.now_title.setText("Press NEXT to start" if steps else "Build the running order below")
            self.now_notes.setText("")
            self.now_clock.setText("")
        else:
            self.now_caption.setText(f"NOW  ·  STEP {index + 1} OF {len(steps)}")
            self.now_title.setText(now["title"] or "Untitled")
            self.now_notes.setText(now["notes"])
        if upcoming is not None:
            self.next_title.setText(upcoming["title"] or "Untitled")
            self.next_summary.setText(summary(upcoming))
        else:
            self.next_title.setText("— end of the show —" if now is not None else "—")
            self.next_summary.setText("")
        self.next_btn.setEnabled(upcoming is not None)
        self.list.viewport().update()
        if 0 <= index < self.list.count():
            self.list.scrollToItem(self.list.item(index), QAbstractItemView.PositionAtCenter)

    def set_clock(self, elapsed: Optional[float], auto_remaining: Optional[float], auto_text: str = "") -> None:
        if elapsed is None:
            self.now_clock.setText("")
        else:
            self.now_clock.setText(f"running {int(elapsed // 60)}:{int(elapsed % 60):02d}")
        if auto_remaining is not None:
            self.next_auto.setText(f"goes on by itself in {int(auto_remaining + 0.99)} s")
        else:
            self.next_auto.setText(auto_text)
