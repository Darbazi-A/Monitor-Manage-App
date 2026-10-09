"""
The simple desk: for whoever uses the hall without setting it up - a rehearsal,
a guest's helper. Big, plain and safe: what each screen shows (and a file or
black for it), the scenes the administrator saved, a presentation, the sound
cues, a laptop. Nothing here can change the wiring, presets or running order.

Kept free of main.py imports, like desk.py: the dashboard feeds it and listens.
"""
from __future__ import annotations

from i18n import tr  # noqa: E402 - the interface's language

from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider,
                               QVBoxLayout, QWidget)

from widgets import ElidedLabel


def _card() -> Tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    box = QVBoxLayout(frame)
    box.setContentsMargins(16, 14, 16, 14)
    box.setSpacing(10)
    return frame, box


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("cardTitle")
    return label


class ScreenPanel(QFrame):
    """One stage screen: its picture, what is on it, and what you may do with it."""

    fileRequested = Signal(str)
    blackRequested = Signal(str)

    PICTURE = QSize(330, 150)

    def __init__(self, role: str, label: str, icons, theme: dict) -> None:
        super().__init__()
        self.role = role
        self.theme = theme
        self.setObjectName("card")
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 12, 14, 14)
        box.setSpacing(9)
        head = QHBoxLayout()
        title = _heading(label)
        head.addWidget(title)
        head.addStretch(1)
        self.tag = QLabel()
        head.addWidget(self.tag)
        box.addLayout(head)
        self.picture = QLabel()
        self.picture.setFixedHeight(self.PICTURE.height())
        self.picture.setMinimumWidth(200)
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.setStyleSheet("background: #05070b; border-radius: 8px;")
        box.addWidget(self.picture)
        self.caption = ElidedLabel()
        self.caption.setObjectName("cardHint")
        box.addWidget(self.caption)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.file_btn = QPushButton(tr("  Show a file…"))
        self.file_btn.setIcon(icons.get("image", theme["text"], 16))
        self.file_btn.setObjectName("big")
        self.file_btn.clicked.connect(lambda: self.fileRequested.emit(self.role))
        row.addWidget(self.file_btn, 1)
        self.black_btn = QPushButton(tr("Black"))
        self.black_btn.setObjectName("big")
        self.black_btn.setToolTip(tr("Clear this screen to black"))
        self.black_btn.clicked.connect(lambda: self.blackRequested.emit(self.role))
        row.addWidget(self.black_btn)
        box.addLayout(row)
        self._key = None

    def show_state(self, pixmap: Optional[QPixmap], caption: str, state: str) -> None:
        key = (pixmap.cacheKey() if pixmap is not None and not pixmap.isNull() else 0, caption, state,
               self.picture.width())
        if key == self._key:
            return
        self._key = key
        if pixmap is not None and not pixmap.isNull():
            self.picture.setPixmap(pixmap.scaled(self.picture.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.picture.setPixmap(QPixmap())
            self.picture.setText(tr("closed") if state == "closed" else "")
        self.caption.setText(caption)
        colour = {"live": self.theme["danger"], "rehearsal": self.theme.get("rehearse", "#7d97e0")}.get(
            state, self.theme["muted"])
        word = {"live": tr("ON AIR"), "rehearsal": tr("REHEARSAL"), "black": tr("BLACK"),
                "closed": tr("CLOSED")}.get(state, "")
        self.tag.setText(word)
        self.tag.setStyleSheet(f"color: {colour}; font-size: 11px; font-weight: 700; letter-spacing: 0.5px;")
        enabled = state != "closed"
        self.file_btn.setEnabled(enabled)
        self.black_btn.setEnabled(enabled)


class SimplePage(QWidget):
    """The whole simple desk, one page."""

    fileRequested = Signal(str)
    blackRequested = Signal(str)
    presetChosen = Signal(str)
    slidesOpenRequested = Signal()
    slideNext = Signal()
    slideBack = Signal()
    slidesEnd = Signal()
    slidesLive = Signal()
    videoRequested = Signal()           # a video in the middle of the talk
    cueClicked = Signal(int)
    stopSoundRequested = Signal()
    masterChanged = Signal(int)
    laptopRequested = Signal()
    openScreensRequested = Signal()

    def __init__(self, roles: Sequence[Tuple[str, str]], icons, theme: dict, preset_strip: QWidget) -> None:
        super().__init__()
        self.icons = icons
        self.theme = theme
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(14)

        title_row = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel(tr("The stage"))
        title.setObjectName("pageTitle")
        titles.addWidget(title)
        lead = QLabel(tr("Pick a scene, or show a file or a presentation - everything here goes straight to the hall's screens."))
        lead.setObjectName("pageLead")
        titles.addWidget(lead)
        title_row.addLayout(titles, 1)
        self.open_btn = QPushButton(tr("  Open the stage screens"))
        self.open_btn.setObjectName("primary")
        self.open_btn.setIcon(icons.get("monitor", theme["ink"], 16))
        self.open_btn.setMinimumHeight(42)
        self.open_btn.clicked.connect(self.openScreensRequested.emit)
        title_row.addWidget(self.open_btn, 0, Qt.AlignBottom)
        outer.addLayout(title_row)

        # the screens
        screens = QHBoxLayout()
        screens.setSpacing(12)
        self.panels: Dict[str, ScreenPanel] = {}
        for role, label in roles:
            panel = ScreenPanel(role, label, icons, theme)
            panel.fileRequested.connect(self.fileRequested.emit)
            panel.blackRequested.connect(self.blackRequested.emit)
            self.panels[role] = panel
            screens.addWidget(panel, 1)
        outer.addLayout(screens)

        # the scenes
        scenes, scenes_box = _card()
        head = QHBoxLayout()
        head.addWidget(_heading(tr("Scenes")))
        hint = QLabel(tr("One tap puts a whole scene on every screen."))
        hint.setObjectName("cardHint")
        head.addSpacing(10)
        head.addWidget(hint, 1)
        scenes_box.addLayout(head)
        self.preset_strip = preset_strip
        preset_strip.presetClicked.connect(self.presetChosen.emit)
        scenes_box.addWidget(preset_strip)
        self.no_scenes = QLabel(tr("No scenes saved yet - the administrator saves them as presets."))
        self.no_scenes.setObjectName("cardHint")
        scenes_box.addWidget(self.no_scenes)
        outer.addWidget(scenes)

        # presentation | sound | laptop
        lower = QHBoxLayout()
        lower.setSpacing(12)

        slides, box = _card()
        box.addWidget(_heading(tr("Presentation")))
        self.slides_state = QLabel(tr("Nothing open."))
        self.slides_state.setObjectName("cardHint")
        self.slides_state.setWordWrap(True)
        box.addWidget(self.slides_state)
        open_btn = QPushButton(tr("  Open a presentation…"))
        open_btn.setObjectName("big")
        open_btn.setIcon(icons.get("open", theme["text"], 16))
        open_btn.clicked.connect(self.slidesOpenRequested.emit)
        box.addWidget(open_btn)
        steps = QHBoxLayout()
        steps.setSpacing(8)
        self.back_btn = QPushButton()
        self.back_btn.setIcon(icons.get("prev", theme["text"], 18))
        self.back_btn.setObjectName("big")
        self.back_btn.setToolTip(tr("Previous slide"))
        self.back_btn.clicked.connect(self.slideBack.emit)
        steps.addWidget(self.back_btn)
        self.next_btn = QPushButton(tr("  Next slide"))
        self.next_btn.setIcon(icons.get("next", theme["ink"], 18))
        self.next_btn.setObjectName("primary")
        self.next_btn.setMinimumHeight(46)
        self.next_btn.clicked.connect(self.slideNext.emit)
        steps.addWidget(self.next_btn, 1)
        box.addLayout(steps)
        ends = QHBoxLayout()
        self.live_btn = QPushButton(tr("Show on the Main Stage"))
        self.live_btn.clicked.connect(self.slidesLive.emit)
        ends.addWidget(self.live_btn, 1)
        self.video_btn = QPushButton(tr("  Video…"))
        self.video_btn.setIcon(icons.get("video", theme["text"], 15))
        self.video_btn.setToolTip(tr("Play a video: the slides wait, and come back where they were when it ends"))
        self.video_btn.clicked.connect(self.videoRequested.emit)
        ends.addWidget(self.video_btn)
        self.end_btn = QPushButton(tr("End"))
        self.end_btn.clicked.connect(self.slidesEnd.emit)
        ends.addWidget(self.end_btn)
        box.addLayout(ends)
        box.addStretch(1)
        lower.addWidget(slides, 3)

        sound, box = _card()
        head = QHBoxLayout()
        head.addWidget(_heading(tr("Sound")))
        head.addStretch(1)
        stop = QPushButton(tr("  Stop all sound"))
        stop.setObjectName("danger")
        stop.setIcon(icons.get("stop", theme["danger"], 14))
        stop.clicked.connect(self.stopSoundRequested.emit)
        head.addWidget(stop)
        box.addLayout(head)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.cue_buttons: List[QPushButton] = []
        for i in range(8):
            button = QPushButton(f"F{i + 1}")
            button.setMinimumHeight(44)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(lambda _c=False, n=i: self.cueClicked.emit(n))
            grid.addWidget(button, i // 4, i % 4)
            self.cue_buttons.append(button)
        box.addLayout(grid)
        master = QHBoxLayout()
        master_label = QLabel(tr("Volume"))
        master_label.setObjectName("cardHint")
        master.addWidget(master_label)
        self.master = QSlider(Qt.Horizontal)
        self.master.setRange(0, 100)
        self.master.valueChanged.connect(self.masterChanged.emit)
        master.addWidget(self.master, 1)
        box.addLayout(master)
        box.addStretch(1)
        lower.addWidget(sound, 4)

        laptop, box = _card()
        box.addWidget(_heading(tr("Laptop")))
        self.laptop_state = QLabel()
        self.laptop_state.setObjectName("cardHint")
        self.laptop_state.setWordWrap(True)
        box.addWidget(self.laptop_state)
        connect = QPushButton(tr("  How to connect a laptop…"))
        connect.setIcon(icons.get("monitor", theme["text"], 16))
        connect.clicked.connect(self.laptopRequested.emit)
        box.addWidget(connect)
        box.addStretch(1)
        lower.addWidget(laptop, 3)
        outer.addLayout(lower)
        outer.addStretch(1)

    # -- fed by the dashboard ------------------------------------------------- #
    def set_screen(self, role: str, pixmap: Optional[QPixmap], caption: str, state: str) -> None:
        if role in self.panels:
            self.panels[role].show_state(pixmap, caption, state)

    def set_screens_closed(self, closed: Sequence[str]) -> None:
        self.open_btn.setVisible(bool(closed))
        self.open_btn.setToolTip(tr("Closed: {0}").format(", ".join(closed)) if closed else "")

    def set_has_scenes(self, any_scenes: bool) -> None:
        self.preset_strip.setVisible(any_scenes)
        self.no_scenes.setVisible(not any_scenes)

    def set_slides(self, text: str, opened: bool, live: bool, paused: bool = False) -> None:
        self.next_btn.setText(tr("  Back to slides") if paused else tr("  Next slide"))
        self.slides_state.setText(text)
        self.next_btn.setEnabled(opened)
        self.back_btn.setEnabled(opened)
        self.live_btn.setEnabled(opened and not live)
        self.end_btn.setEnabled(live)

    def set_cues(self, cues: Sequence[Tuple[str, bool, bool]]) -> None:
        """(name, playing, paused) per cue."""
        for i, button in enumerate(self.cue_buttons):
            name, playing, paused = cues[i] if i < len(cues) else ("", False, False)
            text = f"F{i + 1}   {name}" if name else f"F{i + 1}"
            if button.text() != text:
                button.setText(text)
                button.setToolTip(name)
            button.setEnabled(bool(name))
            style = (f"background: rgba(76, 187, 131, 0.14); border-color: {self.theme['ok']}; color: {self.theme['ok']};"
                     if playing else f"border-color: {self.theme['accent']};" if paused else "")
            if button.styleSheet() != style:
                button.setStyleSheet(style)

    def set_master(self, value: int) -> None:
        self.master.blockSignals(True)
        self.master.setValue(value)
        self.master.blockSignals(False)

    def set_laptop(self, text: str) -> None:
        self.laptop_state.setText(text)
