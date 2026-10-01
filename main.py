"""
Stage Display Controller
========================

A multi-screen playback controller for a school assembly hall stage (PySide6 / Qt 6).

Physical setup
--------------
* Operator PC -> the Control Panel lives on the operator's monitor.
* Stage outputs (3 logical outputs):
    1. "Main Stage"   - the large central screen.
    2. "Side Screens" - left + right screens, mirrored by the hardware, so the
                        app produces ONE window that feeds both.
    3. "Top Screen"   - the wide LED strip near the ceiling. Supports an
                        image/video/solid-colour background plus scrolling text.

LED walls and Windows
---------------------
An LED processor (Nova Studio, LVP, ...) often reports a desktop resolution that
does not match the canvas the wall actually maps. The Top strip here reports
2816x256 to Windows while the real canvas is 2818x132. Every output therefore
supports a CUSTOM geometry: an exact width/height/offset used instead of
fullscreen. See RoutingRow and BaseOutputWindow.show_with_geometry().

Running a show
--------------
Each output has a PLAYLIST: the backgrounds prepared in advance for an event.
Click an entry (or the prev/next arrows) to put it on that screen instantly.
Playlists, routing, marquee and volumes all travel inside a named preset.

Architecture
------------
    Icons                - line icons drawn with QPainter (no image assets).
    MediaEngine          - QMediaPlayer wrapper: looping, safe source swapping.
    FadeOverlay          - crossfades or dips one output between pictures.
    BaseOutputWindow     - frameless, un-closable, taskbar-less stage window.
    SceneOutputWindow    - any stage output, drawn through a QGraphicsScene.
    StandardOutputWindow / TopOutputWindow - Main+Sides / the ceiling strip.
    DropZone             - drag & drop target with a thumbnail preview.
    Playlist             - the prepared-media list for one output.
    OutputCard / TopCard - one output's live controls.
    RoutingRow           - one row of the Screens tab: monitor + geometry.
    PresetStore          - named presets saved as JSON next to this file.
    ControlPanel         - the main window (Live tab + Screens tab).

Requirements:  Python 3.9+   and   pip install PySide6
Run with:      python main.py
"""

from __future__ import annotations

from i18n import LANGUAGES, language as current_language, set_language, tr  # noqa: E402

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
    QBuffer,
    QByteArray,
    QIODevice,
    QEasingCurve,
    QEvent,
    QMimeData,
    QObject,
    QProcess,
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
from config import *  # noqa: F401,F403,E402
from theme import *  # noqa: F401,F403,E402
from media import *  # noqa: F401,F403,E402
from outputs import *  # noqa: F401,F403,E402
from sound import *  # noqa: F401,F403,E402
from cards import *  # noqa: F401,F403,E402
from library import *  # noqa: F401,F403,E402
from textslides import *  # noqa: F401,F403,E402
from routing import *  # noqa: F401,F403,E402
from minibar import *  # noqa: F401,F403,E402
import backups  # noqa: E402 - copies of presets.json and shows.json before each change
import desk as desk_mod  # noqa: E402 - multiview, SETUP / SHOW, TAKE, ready check
import presentation as pres_mod  # noqa: E402 - PDF / PowerPoint slides
import remote as remote_mod  # noqa: E402 - the phone remote (QtNetwork)
import screenshare as share_mod  # noqa: E402 - laptops on the Main Stage (WebRTC)
from show import (ShowStore, ShowTab, fold as show_fold, missing_files as show_missing_files,  # noqa: E402
                  new_step, summary as step_summary)
PRESET_FILE = os.path.join(APP_DIR, "presets.json")
SHOW_FILE = os.path.join(APP_DIR, "shows.json")

# Per-user "run at login" entry. HKCU needs no administrator rights, and it
# starts nothing until the operator ticks the box in Screens & Setup.
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "StageDisplayController"

# LED processors and video walls often finish enumerating well after the
# desktop appears, so an autostart waits before applying the routing.
DEFAULT_STARTUP_DELAY = 20

# QSettings scope. Tests override these so a test run cannot rewrite the
# operator's real preferences.
SETTINGS_ORG = "StageDisplayController"
SETTINGS_APP = "StageDisplayController"


# --------------------------------------------------------------------------- #
# Presets
# --------------------------------------------------------------------------- #

class Autostart:
    """
    "Open this preset when the PC starts", via the per-user Run registry key.

    HKCU\\...\\Run needs no administrator rights and affects only this account.
    The command launches pythonw.exe so no console window appears behind the
    stage output, and passes the preset name plus a delay - see
    DEFAULT_STARTUP_DELAY for why the delay matters.
    """

    @staticmethod
    def available() -> bool:
        return winreg is not None and sys.platform == "win32"

    @staticmethod
    def _launcher() -> str:
        """pythonw.exe if we can find it, so the app starts without a console."""
        if getattr(sys, "frozen", False):  # packaged with PyInstaller etc.
            return sys.executable
        executable = sys.executable
        if os.path.basename(executable).lower() == "python.exe":
            quiet = os.path.join(os.path.dirname(executable), "pythonw.exe")
            if os.path.exists(quiet):
                return quiet
        return executable

    @classmethod
    def command(cls, preset: str, delay: int) -> str:
        if getattr(sys, "frozen", False):
            return f'"{cls._launcher()}" --preset "{preset}" --delay {delay}'
        script = os.path.join(APP_DIR, os.path.basename(__file__))
        return f'"{cls._launcher()}" "{script}" --preset "{preset}" --delay {delay}'

    @classmethod
    def read(cls) -> Optional[str]:
        """The currently registered command line, or None when disabled."""
        if not cls.available():
            return None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, _kind = winreg.QueryValueEx(key, RUN_VALUE)
                return value
        except OSError:
            return None

    @classmethod
    def enable(cls, preset: str, delay: int) -> Optional[str]:
        """Returns an error message, or None on success."""
        if not cls.available():
            return tr('Autostart is only supported on Windows.')
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                    winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, cls.command(preset, delay))
            return None
        except OSError as exc:
            return str(exc)

    @classmethod
    def disable(cls) -> Optional[str]:
        if not cls.available():
            return None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, RUN_VALUE)
        except FileNotFoundError:
            return None
        except OSError as exc:
            return str(exc)
        return None

    @staticmethod
    def parse(command: Optional[str]) -> tuple:
        """Pull (preset, delay) back out of a registered command line."""
        if not command:
            return None, DEFAULT_STARTUP_DELAY
        preset, delay = None, DEFAULT_STARTUP_DELAY
        if "--preset" in command:
            rest = command.split("--preset", 1)[1].strip()
            if rest.startswith('"'):
                preset = rest[1:].split('"', 1)[0]
            else:
                preset = rest.split(" ", 1)[0]
        if "--delay" in command:
            tail = command.split("--delay", 1)[1].strip().split(" ", 1)[0]
            if tail.isdigit():
                delay = int(tail)
        return preset, delay


class PresetStore:
    """Named presets persisted as JSON next to this script."""

    def __init__(self, path: Optional[str] = None) -> None:
        # Resolved at call time, not import time, so PRESET_FILE stays overridable.
        self.path = path or PRESET_FILE
        self.data: Dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.data = payload.get("presets", {}) if isinstance(payload, dict) else {}
        except (OSError, ValueError):
            self.data = {}

    def save(self) -> Optional[str]:
        """Write to disk; returns an error message on failure, None on success."""
        backups.backup(self.path)       # the version on disk, before it is replaced
        try:
            with open(self.path, "w", encoding="utf-8") as handle:
                json.dump({"presets": self.data}, handle, indent=2, ensure_ascii=False)
            return None
        except OSError as exc:
            return str(exc)

    def names(self) -> List[str]:
        return sorted(self.data.keys())

    def put(self, name: str, payload: dict) -> None:
        self.data[name] = payload

    def get(self, name: str) -> Optional[dict]:
        return self.data.get(name)

    def remove(self, name: str) -> None:
        self.data.pop(name, None)


class SlideStage:
    """
    What the presenter may do to the stage: put a slide on a screen, black it,
    and give the screen back to whatever its card holds when the talk ends.
    The card is never changed, so the background is exactly where it was.
    """

    def __init__(self, panel: "ControlPanel") -> None:
        self.panel = panel

    def label(self, role: str) -> str:
        return ROLE_LABELS.get(role, role)

    def size(self, role: str) -> QSize:
        window = self.panel._show_output(role)
        if window is not None and window.width() >= 640 and window.height() >= 360:
            return QSize(window.width(), window.height())
        return QSize(1920, 1080)

    def present(self, role: str, path: str, fade_ms: int) -> Optional[str]:
        panel = self.panel
        window = panel._show_output(role)
        if window is None and panel.routing_rows[role].screen_combo.currentData():
            panel._apply_routing()
            window = panel._show_output(role)
        if window is None:
            return tr('{0} has no monitor - pick one on Screens & Setup.').format(self.label(role))
        window.set_scale_mode(ScaleMode.FIT)
        try:
            window.present(path, fade_ms, TRANSITION_CROSSFADE)
        except MediaProblem as problem:
            return f"{problem.title}: {os.path.basename(path)}"
        return None

    def clear(self, role: str, fade_ms: int) -> None:
        window = self.panel._show_output(role)
        if window is not None:
            window.fade_clear(fade_ms)

    # -- PowerPoint's own slide show on a stage screen ------------------------ #
    def _rect(self, role: str) -> Optional[QRect]:
        window = self.panel._show_output(role)
        if window is not None and window.isVisible():
            return QRect(window.mapToGlobal(QPoint(0, 0)), window.size())
        name = self.panel.routing_rows[role].screen_combo.currentData()
        screen = next((s for s in QGuiApplication.screens() if s.name() == name), None)
        return screen.geometry() if screen is not None else None

    def points(self, role: str) -> Optional[QRectF]:
        """Where PowerPoint should put its slide show, in points (logical pixels x 0.75)."""
        rect = self._rect(role)
        if rect is None:
            return None
        return QRectF(rect.x() * 0.75, rect.y() * 0.75, rect.width() * 0.75, rect.height() * 0.75)

    def make_room(self, role: str) -> None:
        """Stage windows kept on top would hide PowerPoint: let them sit under it for now."""
        rect = self._rect(role)
        self._lowered = []
        if rect is None or sys.platform != "win32":
            return
        for other in STAGE_ROLES:
            window = self.panel._show_output(other)
            if (window is not None and window.isVisible() and window.geometry().intersects(rect)
                    and window.windowFlags() & Qt.WindowStaysOnTopHint):
                set_topmost(window, False)
                self._lowered.append(window)

    def give_back_room(self, role: str) -> None:
        for window in getattr(self, "_lowered", []):
            try:
                if window.isVisible() and window.windowFlags() & Qt.WindowStaysOnTopHint:
                    set_topmost(window, True)
            except RuntimeError:
                pass              # the window was rebuilt meanwhile
        self._lowered = []

    def refocus(self) -> None:
        """PowerPoint takes the focus when its show starts; the desk keeps it."""
        QTimer.singleShot(250, self.panel.activateWindow)

    def restore(self, role: str, fade_ms: int) -> None:
        panel = self.panel
        window = panel._show_output(role)
        if window is None:
            return
        card = panel.cards[role]
        window.set_scale_mode(card.current_scale_mode())
        path = card.current_path()
        if path and os.path.isfile(path):
            try:
                window.engine.set_loop(card.is_repeating())
                window.present(path, fade_ms, TRANSITION_CROSSFADE)
                return
            except MediaProblem:
                pass
        window.fade_clear(fade_ms)


# Windows hotkey plumbing, for a clicker that must work whichever window has focus.
WM_HOTKEY = 0x0312
VK_BY_NAME = {"PgDown": 0x22, "PgUp": 0x21}


class ControlPanel(QMainWindow):
    """Operator-facing window: a Live tab for the show, a Screens tab for setup."""

    WIDE_ASPECT_THRESHOLD = 2.5
    OUTPUT_ATTRS = {ROLE_MAIN: "main_output", ROLE_SIDES: "sides_output", ROLE_TOP: "top_output"}

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(tr('Stage Display Controller'))
        if os.path.exists(ICON_FILE):
            self.setWindowIcon(QIcon(ICON_FILE))

        available = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(min(1380, available.width() - 60), min(940, available.height() - 60))

        self.main_output: Optional[StandardOutputWindow] = None
        self.sides_output: Optional[StandardOutputWindow] = None
        self.top_output: Optional[TopOutputWindow] = None

        self.routing_rows: Dict[str, RoutingRow] = {}
        self.presets = PresetStore()
        self.active_role = ROLE_MAIN
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        # The look - touch-sized or not - goes on once, before a single widget
        # exists: re-styling the finished window cost over half a second of start-up.
        app = QApplication.instance()
        sheet = STYLESHEET + language_stylesheet() + (touch_stylesheet() if self.touch_enabled() else "")
        if app is not None and app.styleSheet() != sheet:
            app.setStyleSheet(sheet)
        self._freshly_opened: set = set()
        self.mini: Optional[MiniBar] = None
        self._mini_ticker = QTimer(self)
        self._mini_ticker.timeout.connect(self._refresh_mini)
        self.sound = SoundDeck(self)
        self.sound.failed.connect(self._on_cue_failed)
        self.loaded_preset: Optional[str] = None
        self._preset_dirty = False

        # Running order: where we are, and its own pair of players so one
        # step's music can fade out while the next one's fades in.
        self.show_index = -1
        self._show_started = 0.0
        self._show_auto: Optional[float] = None
        self._show_sound_started = False
        self._show_text_shown: Optional[tuple] = None
        self._show_players = [SoundCue(-1, self), SoundCue(-2, self)]
        self._show_active = 0
        self._show_timer = QTimer(self)
        self._show_timer.timeout.connect(self._show_tick)
        self.remote = remote_mod.RemoteServer(self.remote_state, self.remote_action, self,
                                              image=self._remote_slide_image,
                                              screen=self._remote_screen_image)
        self._remote_dialog = None
        self._guest_dialog = None
        # Laptop screen share: laptops ask over HTTPS, the picture comes over WebRTC.
        self.share = share_mod.ShareServer(os.path.join(APP_DIR, "share_cert"), self)
        self.share_receiver = share_mod.ShareReceiver(self)
        self._share_live = ""               # the laptop on the Main Stage (its request id)
        self._share_dialog = None
        self._share_lost_at = 0.0

        # Presentations: one presenter, driven by the dashboard, the clicker,
        # the keyboard, the phone and the running order alike.
        self.presenter = pres_mod.Presenter(SlideStage(self), self)
        self.presenter.in_powerpoint = str(self.settings.value("slides/powerpoint", "true")).lower() == "true"
        self.presenter.note.connect(self._on_presenter_note)
        self.presenter.changed.connect(self._on_presenter_changed)
        self._hotkeys: Dict[int, tuple] = {}
        self._slide_shortcuts: List[QShortcut] = []
        self._learned_shortcuts: List[QShortcut] = []
        self._was_live = False

        # The desk: SETUP / SHOW, and preview-then-TAKE with the change waiting.
        self.ui_mode = "setup"
        self.preview_first = str(self.settings.value("ui/preview_first", "false")).lower() == "true"
        self._pending_change: Optional[dict] = None
        self._direct_depth = 0          # >0 while a TAKE, a step or an undo is changing the stage
        self._ready_dialog = None
        self._undo_snapshot: Optional[dict] = None
        self._rehearsal: Optional[RehearsalMonitor] = None
        self._thumb_cache: Dict[tuple, QPixmap] = {}
        self._lost_screens: set = set()      # stage screens whose monitor has gone away
        self._session_written = ""

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 8)
        root.setSpacing(9)
        root.addWidget(self._build_header())
        # A laptop asking to share, or on stage, shows here whatever tab is open.
        self.share_bar = share_mod.ShareBar(Icons, THEME)
        self.share_bar.acceptRequested.connect(self._accept_share)
        self.share_bar.declineRequested.connect(self._decline_share)
        self.share_bar.stopRequested.connect(lambda: self._end_share(tr("The stage desk ended the share.")))
        self.share_bar.volumeChanged.connect(self._on_share_volume)
        root.addWidget(self.share_bar)
        self.preset_bar = self._build_preset_bar()
        root.addWidget(self.preset_bar)

        self.tabs = desk_mod.PageTabs()
        self.tabs.addTab(self._build_live_tab(), tr('  Live  '))
        self.tabs.addTab(self._build_show_tab(), tr('  Show  '))
        self.tabs.addTab(self._build_presentation_tab(), tr('  Slides  '))
        self.tabs.addTab(self._build_library_tab(), tr('  Library  '))
        self.tabs.addTab(self._build_text_tab(), tr('  Text  '))
        # The DJ desk is built the first time its tab opens: it starts an audio
        # engine, and a show that never uses it should not pay for one.
        self.dj_panel = None
        self.dj_page = QWidget()
        dj_layout = QVBoxLayout(self.dj_page)
        dj_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs.addTab(self.dj_page, tr('  DJ  '), scroll=False)   # the DJ desk sizes itself
        # "&&" because a single & would be swallowed as a keyboard mnemonic.
        self.screens_page = self._build_screens_tab()
        self.tabs.addTab(self.screens_page, tr('  Screens && Setup  '))
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)
        # NOW / NEXT follows the operator onto every tab.
        self.show_strip = desk_mod.ShowStrip(Icons, THEME)
        self.show_strip.nextRequested.connect(self.show_next)
        self.show_strip.backRequested.connect(self.show_back)
        self.show_strip.openRequested.connect(lambda: self.tabs.setCurrentWidget(self.show_tab))
        root.addWidget(self.show_strip)
        self.setCentralWidget(central)

        app = QGuiApplication.instance()
        app.screenAdded.connect(lambda _s: self._on_screens_changed())
        app.screenRemoved.connect(lambda _s: self._on_screens_changed())
        # A monitor can also come back without Windows saying so in time; look every two seconds.
        self._screen_watch = QTimer(self)
        self._screen_watch.timeout.connect(self._check_stage_screens)
        self._screen_watch.start(2000)

        self._refresh_screen_combos(initial=True)
        self._refresh_preset_combo()
        self._load_fade_setting()
        self._refresh_audio_devices()
        self._restore_library_places()
        self.sound_master.setValue(int(self.settings.value('sound/master', 90)))
        self._load_autostart_state()
        self._describe_preset_state()
        self._update_output_status()
        self._install_shortcuts()
        self.set_active_role(ROLE_MAIN)
        self._apply_touch_mode()
        self._restore_window_geometry()
        self._restore_remote()
        self._restore_share()
        self._multiview_timer = QTimer(self)
        self._multiview_timer.timeout.connect(self._refresh_multiview)
        self._multiview_timer.start(500)
        self.dim_overlay = desk_mod.DimOverlay(self)
        try:
            self._set_dark_room(int(self.settings.value("ui/darkroom", 0) or 0))
        except (TypeError, ValueError):
            self._set_dark_room(0)
        self._set_mode(str(self.settings.value("ui/mode", "setup")), check=False)
        self._refresh_show_strip()
        # What is on stage is written down every few seconds; after a crash it is offered back.
        self._session_timer = QTimer(self)
        self._session_timer.timeout.connect(self._save_session)
        QTimer.singleShot(0, self._offer_recovery)

        self.health = desk_mod.HealthBar(THEME)
        self.health.checkRequested.connect(self._open_ready_check)
        self.health.helpRequested.connect(self._show_shortcuts)
        self.statusBar().addPermanentWidget(self.health)
        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._refresh_health)
        self._health_timer.start(2000)
        self._refresh_health()
        self.statusBar().showMessage(
            tr('Screens & Setup → assign monitors → OPEN OUTPUTS.   Then drop media onto a card, or build a playlist.')
        )

    # ------------------------------------------------------------------ UI -- #

    def _build_header(self) -> QWidget:
        """
        Name and time; a live picture of every stage screen; and the controls
        that matter whatever tab is open - SETUP / SHOW, PREVIEW -> TAKE, the
        ready check, and BLACKOUT.
        """
        bar = QFrame()
        bar.setObjectName("bar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 6, 12, 6)
        layout.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(3)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(8)
        mark = QLabel()
        mark.setPixmap(Icons.get("monitor", CLR_ACCENT, 19).pixmap(19, 19))
        brand_row.addWidget(mark)
        title = QLabel(tr('Stage Display'))
        title.setObjectName("brand")
        brand_row.addWidget(title)
        brand_row.addStretch(1)
        left.addLayout(brand_row)
        # A wall clock the operator can glance at without leaving the app.
        self.clock = QLabel()
        self.clock.setObjectName("clock")
        self.clock.setToolTip(tr('Current time'))
        left.addWidget(self.clock)
        self.mode_note = QLabel()
        self.mode_note.setObjectName("keyHint")
        left.addWidget(self.mode_note)
        left.addStretch(1)
        layout.addLayout(left)
        self._tick_clock()
        clock_timer = QTimer(self)
        clock_timer.timeout.connect(self._tick_clock)
        clock_timer.start(1000)

        # What the audience sees, on every screen, all the time.
        aspects = {ROLE_MAIN: 16 / 9, ROLE_SIDES: 16 / 9,
                   ROLE_TOP: DEFAULT_TOP_WIDTH / DEFAULT_TOP_HEIGHT}
        self.multiview = desk_mod.MultiView({role: ROLE_LABELS[role] for role in STAGE_ROLES},
                                            aspects, THEME)
        for tile in self.multiview.tiles.values():
            tile.clicked.connect(self._on_tile_clicked)
            tile.filesDropped.connect(self._on_tile_files)
        layout.addWidget(self.multiview)

        # PREVIEW -> TAKE and Undo live in the header's free middle, so nothing
        # below moves when they come and go (the sound pads used to be pushed
        # off the bottom for ten seconds after every change)
        layout.addStretch(1)
        self.take_bar = desk_mod.TakeBar(Icons, THEME)
        self.take_bar.takeRequested.connect(self._take)
        self.take_bar.cancelRequested.connect(self._cancel_take)
        self.take_bar.undoRequested.connect(self._undo)
        self.take_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.take_bar, 30)
        layout.addStretch(1)

        # --- global actions ------------------------------------------------ #
        right = QVBoxLayout()
        right.setSpacing(8)
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        top_row.addStretch(1)
        self.mode_switch = desk_mod.ModeSwitch(THEME)
        self.mode_switch.modeChanged.connect(self._set_mode)
        top_row.addWidget(self.mode_switch)
        self.preview_btn = QPushButton(tr('  PREVIEW → TAKE'))
        self.preview_btn.setCheckable(True)
        self.preview_btn.setIcon(Icons.get("target", CLR_TEXT, 15))
        self.preview_btn.setToolTip(
            tr('On: a file, preset or name chosen by hand waits in PREVIEW until you press TAKE,\nso nothing reaches the stage by accident. NEXT in the running order goes straight on.'))
        self.preview_btn.setChecked(self.preview_first)
        self.preview_btn.toggled.connect(self._set_preview_first)
        top_row.addWidget(self.preview_btn)
        self.rehearse_btn = QPushButton(tr('  Rehearse'))
        self.rehearse_btn.setCheckable(True)
        self.rehearse_btn.setIcon(Icons.get("play", CLR_TEXT, 15))
        self.rehearse_btn.setToolTip(tr('Try the show out in a window on this desk: presets, running order, names and\nslides go there instead of the stage, and the hall keeps what it has.'))
        self.rehearse_btn.clicked.connect(self._toggle_rehearsal)
        top_row.addWidget(self.rehearse_btn)
        ready = QPushButton(tr('  Ready check'))
        ready.setIcon(Icons.get("list", CLR_TEXT, 15))
        ready.setToolTip(tr('Screens, sound, clicker, files - everything worth knowing before the doors open'))
        ready.clicked.connect(self._open_ready_check)
        top_row.addWidget(ready)
        right.addLayout(top_row)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        bottom_row.addStretch(1)
        self.open_btn = QPushButton(tr('  Open outputs'))
        self.open_btn.setIcon(Icons.get("monitor", CLR_TEXT, 16))
        self.open_btn.setToolTip(tr('Apply the Screens tab settings and open every stage window  (Ctrl+O)'))
        self.open_btn.clicked.connect(self._apply_routing)
        bottom_row.addWidget(self.open_btn)

        blackout = QPushButton(tr('  BLACKOUT'))
        blackout.setObjectName("danger")
        blackout.setIcon(Icons.get("power", CLR_DANGER, 16))
        blackout.setMinimumWidth(150)
        blackout.setToolTip(tr('Instantly clear every stage screen to black  (B)'))
        blackout.clicked.connect(self._blackout_all)
        bottom_row.addWidget(blackout)

        self.dark_btn = icon_button("moon", tr('Dark room: dim this screen so its light does not spill into the hall'),
                                    CLR_DIM, 16)
        self.dark_btn.setObjectName("ghost")
        self.dark_btn.setCheckable(True)
        self.dark_btn.clicked.connect(self._cycle_dark_room)
        bottom_row.addWidget(self.dark_btn)
        shrink = icon_button("compress", tr('Shrink to a small bar that stays on top'),
                             CLR_DIM, 16)
        shrink.setObjectName("ghost")
        shrink.clicked.connect(self.shrink_to_bar)
        bottom_row.addWidget(shrink)
        right.addLayout(bottom_row)
        layout.addLayout(right)
        # "Close outputs" deliberately lives on the Screens tab: an X in the
        # header corner reads like "quit the app" during a show.
        return bar

    # ------------------------------------------------------------ the desk -- #

    def _refresh_multiview(self) -> None:
        """What each stage screen shows right now, a couple of times a second."""
        if not self.isVisible() or self.isMinimized():
            return
        presenter = self.presenter
        rehearsing = getattr(self, "_rehearsal", None) is not None
        for role, tile in self.multiview.tiles.items():
            window = self._show_output(role)
            if window is None:
                tile.set_state(desk_mod.STATE_CLOSED, None, tr("closed - click to open"))
                continue
            if role in self._lost_screens:
                tile.set_state(desk_mod.STATE_CLOSED, None, tr("monitor gone - waiting for it"))
                continue
            card = self.cards.get(role) if hasattr(self, "cards") else None
            if role == ROLE_MAIN and self._share_on(window):
                pixmap = self.share_receiver.snapshot()
                pixmap = pixmap.scaled(tile.preview_size(), Qt.KeepAspectRatio, Qt.SmoothTransformation) \
                    if not pixmap.isNull() else None
                request = self.share.request(self._share_live)
                caption = tr("laptop  ·  {0}").format(request.name if request else "")
                live = True
            elif presenter.live and presenter.role == role and presenter.playing_in_powerpoint():
                pixmap = None
                if presenter.deck is not None and presenter.count() and not presenter.black:
                    pixmap = presenter.deck.thumb(presenter.index, 256)
                caption = (f"PowerPoint  ·  {presenter.index + 1} / {presenter.count() or '…'}"
                           + ("  ·  " + tr("black") if presenter.black else ""))
                live = not presenter.black
            else:
                drawn = getattr(tile, "_drawn", None)
                key = (id(window), window.picture_version, tile.preview_size().width())
                if drawn == key and not window.is_moving() and tile.pixmap is not None:
                    pixmap = tile.pixmap            # nothing moved: keep the last picture
                else:
                    pixmap = window.preview(tile.preview_size())
                    tile._drawn = key
                live = window.has_picture()
                parts = []
                if presenter.live and presenter.role == role and presenter.deck is not None:
                    parts.append(tr("slides {0}/{1}").format(presenter.index + 1, presenter.count()))
                elif card is not None and card.current_path():
                    parts.append(os.path.basename(card.current_path()))
                if window.slide_visible():
                    parts.append(tr("text"))
                if role == ROLE_TOP and window.is_marquee_running():
                    parts.append(tr("marquee"))
                caption = "  +  ".join(parts) if parts else (tr("colour") if live else tr("black"))
            state = desk_mod.STATE_REHEARSAL if rehearsing else (
                desk_mod.STATE_LIVE if live else desk_mod.STATE_BLACK)
            tile.set_state(state, pixmap, caption)

    @Slot(str)
    def _on_tile_clicked(self, role: str) -> None:
        self.set_active_role(role)
        if self._show_output(role) is not None:
            return
        if self.routing_rows[role].screen_combo.currentData():
            self._apply_routing()
        else:
            self.statusBar().showMessage(
                tr('{0} has no monitor - pick one on Screens & Setup.').format(ROLE_LABELS[role]), 6000)

    @Slot(str, list)
    def _on_tile_files(self, role: str, paths: List[str]) -> None:
        """Files dropped on a screen in the header go on that screen."""
        media = [os.path.normpath(p) for p in paths
                 if os.path.isfile(p) and os.path.splitext(p)[1].lower() in (IMAGE_EXTENSIONS | VIDEO_EXTENSIONS)]
        if not media:
            self.statusBar().showMessage(tr('Only pictures and videos can go on a screen.'), 6000)
            return
        card = self.cards[role]
        card.playlist.add_paths(media, announce=False)
        self.set_active_role(role)
        card.loadRequested.emit(media[0])

    # -- SETUP / SHOW ---------------------------------------------------------- #

    @Slot(str)
    def _set_mode(self, mode: str, check: bool = True) -> None:
        """
        SETUP: everything can be prepared and edited. SHOW: the event is on -
        the library and the screen setup step away, and nothing can be deleted,
        renamed or rebuilt by a stray tap.
        """
        mode = "show" if mode == "show" else "setup"
        if mode == "show" and self._rehearsal is not None:
            self.end_rehearsal()
        self.ui_mode = mode
        self.settings.setValue("ui/mode", mode)
        show = mode == "show"
        self.mode_switch.set_mode(mode)
        setup_pages = (self.library, self.screens_page)
        if show and self.tabs.currentWidget() in setup_pages:
            self.tabs.setCurrentIndex(0)      # before hiding: Qt would pick a neighbour
        for page in setup_pages:
            index = self.tabs.indexOf(page)
            if index >= 0:
                self.tabs.setTabVisible(index, not show)
        self.open_btn.setVisible(not show)
        self.rehearse_btn.setVisible(not show)
        for widget in getattr(self, "_preset_edit_widgets", []):
            widget.setVisible(not show)
        self.show_tab.set_locked(show)
        if show:
            self.mode_note.setText(tr('SHOW  ·  editing locked'))
            self.mode_note.setStyleSheet(f"color: {CLR_DANGER}; font-weight: 700;")
        else:
            self.mode_note.setText(tr('SETUP  ·  preparing'))
            self.mode_note.setStyleSheet("")
        if show and check and any(row["status"] == "fail" for row in self._ready_checks()):
            self._open_ready_check()

    # -- dark room ------------------------------------------------------------ #

    DARK_LEVELS = ((0.0, "off"), (0.38, "dim"), (0.6, "darker"))

    @Slot()
    def _cycle_dark_room(self) -> None:
        self._set_dark_room((self.dark_level + 1) % len(self.DARK_LEVELS))

    def _set_dark_room(self, level: int) -> None:
        """
        During the event the desk sits in a dark hall; a bright dashboard lights
        up the operator's face and the front rows. Two steps darker, clicks still
        pass straight through, and the stage itself is never touched.
        """
        level = max(0, min(level, len(self.DARK_LEVELS) - 1))
        self.dark_level = level
        self.settings.setValue("ui/darkroom", level)
        amount, name = self.DARK_LEVELS[level]
        name = tr(name)
        self.dim_overlay.set_amount(amount)
        self.dark_btn.setChecked(level > 0)
        following = tr(self.DARK_LEVELS[(level + 1) % len(self.DARK_LEVELS)][1])
        self.dark_btn.setToolTip(tr('Dark room: {0} - click for {1}. Dims this screen so its light does not spill into the hall.').format(name, following))

    # -- PREVIEW -> TAKE ------------------------------------------------------- #

    @Slot(bool)
    def _set_preview_first(self, on: bool) -> None:
        self.preview_first = on
        self.settings.setValue("ui/preview_first", "true" if on else "false")
        if not on and self._pending_change is not None:
            self._cancel_take()
        self.statusBar().showMessage(
            tr('PREVIEW → TAKE on: choices wait for TAKE.') if on else
            tr('PREVIEW → TAKE off: choices go straight on stage.'), 6000)

    @contextmanager
    def _direct(self):
        """Stage changes made inside this go straight on: a TAKE, a running-order step, an undo."""
        self._direct_depth += 1
        try:
            yield
        finally:
            self._direct_depth -= 1

    def _change_stage(self, title: str, apply: Callable[[], None], thumb: Optional[QPixmap] = None,
                      detail: str = "") -> None:
        """
        Every change made by hand comes through here: straight on stage, or -
        with PREVIEW -> TAKE on - into the bar under the header until TAKE.
        """
        if self._direct_depth > 0:
            apply()                     # part of a TAKE, a step or an undo already under way
            return
        if self.preview_first and self.isVisible():
            self._pending_change = {"title": title, "apply": apply, "thumb": thumb}
            self.take_bar.show_pending(title, detail, thumb)
            self._sync_take_keys()
            return
        self._record_change(title, apply, thumb)

    def _record_change(self, title: str, apply: Callable[[], None], thumb: Optional[QPixmap] = None) -> None:
        """Change the stage, keeping what was there so Undo can put it back for a few seconds."""
        if self._direct_depth > 0:
            apply()
            return
        before = self._stage_snapshot()
        with self._direct():
            apply()
        self._undo_snapshot = before
        self.take_bar.show_done(title, thumb)

    def _stage_snapshot(self) -> dict:
        screens = {}
        for role in STAGE_ROLES:
            card = self.cards[role]
            window = self._show_output(role)
            screens[role] = {
                "path": card.current_path(), "loop": card.is_repeating(), "muted": card.mute_btn.isChecked(),
                "scale": card.current_scale_mode(),
                "slide": window.slide_state() if window is not None else None,
                "colour": window._bg_color.name() if window is not None else None,
            }
        top = self.top_output
        return {"screens": screens,
                "marquee": {"running": bool(top and top.is_marquee_running()),
                            "text": self.top_card.text_edit.text()},
                "preset": (self.loaded_preset, self._preset_dirty)}

    @Slot()
    def _undo(self) -> None:
        """Put the stage back to how it was before the last change made by hand."""
        snapshot = self._undo_snapshot
        if snapshot is None or not self.take_bar.undo_available():
            self.statusBar().showMessage(tr('Nothing to undo.'), 3000)
            return
        self._undo_snapshot = None
        self.take_bar.forget_undo()
        fade = self.fade_ms()
        with self._direct():
            for role, want in snapshot["screens"].items():
                card = self.cards[role]
                window = self._show_output(role)
                if window is None:
                    continue
                if want["colour"] and want["colour"] != window._bg_color.name():
                    window.set_background_color(QColor(want["colour"]))
                if want["path"] != card.current_path():
                    card.set_scale_mode(want["scale"])
                    self._set_checked(card.repeat_btn, want["loop"])
                    self._set_checked(card.mute_btn, want["muted"])
                    if want["path"] and os.path.isfile(want["path"]):
                        card.loadRequested.emit(want["path"])
                    else:
                        window.fade_clear(fade)
                        card.reset_file()
                if want["slide"] != window.slide_state():
                    if want["slide"]:
                        window.set_slide_style(self.text_slides.style_dict())
                        window.show_slide(want["slide"][0], want["slide"][1], max(120, fade // 2))
                    else:
                        window.hide_slide(max(120, fade // 2))
            marquee = snapshot["marquee"]
            top = self.top_output
            if top is not None and marquee["running"] != top.is_marquee_running():
                if marquee["running"]:
                    self.top_card.text_edit.setText(marquee["text"])
                    self._start_marquee()
                else:
                    self._stop_marquee()
        self.loaded_preset, self._preset_dirty = snapshot["preset"]
        self._describe_preset_state()
        self.statusBar().showMessage(tr('Undone - the stage is back to how it was.'), 5000)

    # -- after a crash ------------------------------------------------------------ #

    def _session_state(self) -> dict:
        snapshot = self._stage_snapshot()
        presenter = self.presenter
        return {
            "routing": {role: row.config().to_dict() for role, row in self.routing_rows.items()},
            "open": [role for role in STAGE_ROLES if self._show_output(role) is not None],
            "screens": {role: {"path": data["path"], "loop": data["loop"], "muted": data["muted"],
                               "scale": data["scale"].name, "slide": data["slide"], "colour": data["colour"]}
                        for role, data in snapshot["screens"].items()},
            "marquee": snapshot["marquee"],
            "preset": list(snapshot["preset"]),
            "show": {"name": self.show_store.current, "index": self.show_index},
            "slides": {"path": presenter.deck.path if presenter.deck is not None else "",
                       "index": presenter.index, "live": presenter.live, "role": presenter.role},
        }

    def _save_session(self) -> None:
        """Write down what is on stage, when it changed. Not while rehearsing: that is not the stage."""
        if self._rehearsal is not None:
            return
        text = json.dumps(self._session_state(), sort_keys=True)
        if text != self._session_written:
            self._session_written = text
            self.settings.setValue("session/state", text)
            self.settings.setValue("session/time", QTime.currentTime().toString("HH:mm"))

    def _offer_recovery(self) -> None:
        raw = str(self.settings.value("session/state", "") or "")
        clean = str(self.settings.value("session/clean", "true")).lower() == "true"
        self.settings.setValue("session/clean", "false")     # until this run closes properly
        self._session_timer.start(3000)
        if clean or not raw:
            return
        try:
            state = json.loads(raw)
        except ValueError:
            return
        lines = []
        for role in STAGE_ROLES:
            data = state.get("screens", {}).get(role, {})
            if data.get("path"):
                lines.append(f"{ROLE_LABELS[role]}: {os.path.basename(data['path'])}")
            if data.get("slide"):
                lines.append(tr("{0}: the name “{1}”").format(ROLE_LABELS[role], data['slide'][0]))
        if state.get("marquee", {}).get("running"):
            lines.append(tr("Top Screen: scrolling “{0}”").format(state['marquee']['text'][:40]))
        slides = state.get("slides", {})
        if slides.get("live") and slides.get("path"):
            lines.append(tr("Slides: {0}, slide {1}").format(os.path.basename(slides['path']), slides.get('index', 0) + 1))
        show = state.get("show", {})
        if show.get("index", -1) >= 0:
            lines.append(tr("Running order “{0}”, step {1}").format(show.get('name'), show['index'] + 1))
        if not lines:
            return
        dialog = desk_mod.RecoveryDialog(str(self.settings.value("session/time", "") or "earlier"), lines, THEME,
                                         20, self)
        if dialog.exec() == QDialog.Accepted:
            self._restore_session(state)

    def _restore_session(self, state: dict) -> None:
        """Put back what was on stage: the screens, their files and names, the marquee, slides, the step."""
        names = self._screen_names()
        for role, data in state.get("routing", {}).items():
            if role in self.routing_rows and data:
                self.routing_rows[role].apply_config(RouteConfig.from_dict(data, role != ROLE_MAIN), names)
        with self._direct():
            if state.get("open"):
                self._apply_routing()
            for role in STAGE_ROLES:
                data = state.get("screens", {}).get(role, {})
                card = self.cards[role]
                try:
                    card.set_scale_mode(ScaleMode[data.get("scale", "FIT")])
                except KeyError:
                    pass
                self._set_checked(card.repeat_btn, bool(data.get("loop", True)))
                self._set_checked(card.mute_btn, bool(data.get("muted", False)))
                window = self._show_output(role)
                if window is None:
                    continue
                if data.get("colour") and data["colour"] != "#000000":
                    window.set_background_color(QColor(data["colour"]))
                path = data.get("path", "")
                if path and os.path.isfile(path):
                    card.playlist.add_paths([path], announce=False)
                    card.loadRequested.emit(path)
                if data.get("slide"):
                    window.set_slide_style(self.text_slides.style_dict())
                    window.show_slide(data["slide"][0], data["slide"][1], 0)
            marquee = state.get("marquee", {})
            if marquee.get("text"):
                self.top_card.text_edit.setText(marquee["text"])
            if marquee.get("running") and self.top_output is not None:
                self._start_marquee()
        preset = state.get("preset") or [None, False]
        self.loaded_preset, self._preset_dirty = preset[0], bool(preset[1])
        self._describe_preset_state()
        show = state.get("show", {})
        if show.get("name") in self.show_store.shows and show.get("name") != self.show_store.current:
            self.show_tab._switch_to(show["name"])
        steps = self.show_tab.steps()
        index = show.get("index", -1)
        if 0 <= index < len(steps):
            self.show_index = index
            self._show_step_id = steps[index]["id"]
            self._show_started = time.monotonic()
            self.show_tab.set_running(index)
            self._show_timer.start(250)
        slides = state.get("slides", {})
        if slides.get("path") and os.path.exists(slides["path"]):
            if self.presenter.open(slides["path"]) is None:
                self.presenter.index = max(0, int(slides.get("index", 0)))
                if slides.get("live"):
                    self.presenter.go_live_when_ready(slides.get("role") or ROLE_MAIN)
        self._refresh_mini()
        self.statusBar().showMessage(tr('The stage is back as it was before the app closed.'), 10000)

    # -- backups -------------------------------------------------------------------- #

    def _add_language_picker(self, box: QHBoxLayout) -> None:
        heading = QLabel("Language / ენა")        # readable whichever language is on
        heading.setObjectName("sectionTitle")
        box.addWidget(heading)
        self.language_combo = QComboBox()
        for code, name in LANGUAGES:
            self.language_combo.addItem(name, code)
        self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(current_language())))
        self.language_combo.setToolTip(tr("The interface's language. Names, files and steps stay as you typed them."))
        self.language_combo.activated.connect(self._on_language_chosen)
        box.addWidget(self.language_combo)

    @Slot(int)
    def _on_language_chosen(self, index: int) -> None:
        code = self.language_combo.itemData(index)
        if code == current_language():
            return
        self.settings.setValue("ui/language", code)
        answer = QMessageBox.question(
            self, "Language / ენა",
            "The new language is used from the next start. Restart the app now?\n\n"
            "ახალი ენა შემდეგი ჩართვიდან გამოიყენება. გადავტვირთო პროგრამა ახლავე?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            self.restart_app()

    def restart_app(self) -> None:
        """Close properly (it asks first if screens are live), then start again - without the autostart."""
        if self.close():
            QProcess.startDetached(sys.executable, [os.path.abspath(__file__)])

    def _build_backups_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        box = QHBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(10)
        heading = QLabel(tr('Backups'))
        heading.setObjectName("sectionTitle")
        box.addWidget(heading)
        self.backup_combo = QComboBox()
        self.backup_combo.setMinimumWidth(320)
        self.backup_combo.setToolTip(tr('Copies taken by themselves before the presets or the running orders change'))
        box.addWidget(self.backup_combo)
        restore = desk_mod.HoldButton(tr('  Restore'), THEME)
        restore.setIcon(Icons.get("refresh", CLR_TEXT, 15))
        restore.setToolTip(tr('Put this copy back (what is there now is kept as a copy too) - hold to confirm'))
        restore.clicked.connect(self._restore_backup)
        box.addWidget(restore)
        note = QLabel(tr('Taken before presets.json or shows.json change - at most one every two minutes, the newest ten of each.'))
        note.setObjectName("cardHint")
        note.setWordWrap(True)
        box.addWidget(note, 1)
        return card

    def _refresh_backups(self) -> None:
        if not hasattr(self, "backup_combo"):
            return
        self.backup_combo.clear()
        entries = [("presets", tr("Presets"), path, when) for path, when in backups.list_backups(PRESET_FILE)]
        entries += [("shows", tr("Running orders"), path, when) for path, when in backups.list_backups(SHOW_FILE)]
        entries.sort(key=lambda e: e[3], reverse=True)
        for kind, caption, path, when in entries:
            self.backup_combo.addItem(f"{caption}  ·  {when.strftime('%d.%m  %H:%M:%S')}", f"{kind}|{path}")
        if not entries:
            self.backup_combo.addItem(tr('no copies yet - they appear once something is saved'), None)
        self.backup_combo.setEnabled(bool(entries))

    @Slot()
    def _restore_backup(self) -> None:
        chosen = self.backup_combo.currentData()
        if not chosen:
            return
        kind, path = str(chosen).split("|", 1)
        if kind == "presets":
            error = backups.restore(PRESET_FILE, path)
            if error is None:
                self.presets.load()
                self._refresh_preset_combo(self.loaded_preset)
        else:
            self.show_tab._save_timer.stop()
            error = backups.restore(SHOW_FILE, path)
            if error is None:
                restored = ShowStore(SHOW_FILE)
                self.show_store.shows = restored.shows
                self.show_store.current = restored.current
                self.show_tab._fill_show_combo()
                self.show_tab._reload_list()
                self.show_restart()
        if error:
            QMessageBox.critical(self, tr('Could not restore'), error)
            return
        self._refresh_backups()
        self.statusBar().showMessage(tr('Restored the copy from {0}.').format(self.backup_combo.currentText().split('·')[-1].strip()),
                                     8000)

    # -- rehearsal --------------------------------------------------------------- #

    def _stage_size(self, role: str) -> QSize:
        config = self.routing_rows[role].config()
        if config.custom and config.width > 0 and config.height > 0:
            return QSize(config.width, config.height)
        screen = self._screen_by_name(config.screen_name)
        if screen is not None:
            return screen.geometry().size()
        return QSize(DEFAULT_TOP_WIDTH, DEFAULT_TOP_HEIGHT) if role == ROLE_TOP else QSize(1920, 1080)

    @Slot()
    def _toggle_rehearsal(self) -> None:
        if self._rehearsal is None:
            self.start_rehearsal()
        else:
            self.end_rehearsal()

    def start_rehearsal(self) -> None:
        """
        Swap the stage windows for three in a desk window. Everything that drives
        a screen goes through the same attributes, so the whole dashboard follows
        without knowing; the real windows keep playing what they had.
        """
        if self._rehearsal is not None:
            return
        if self.presenter.live:
            self.rehearse_btn.setChecked(False)
            QMessageBox.information(self, tr('Rehearsal'), tr('A presentation is on the stage. End it first, then rehearse - the rehearsal must not take it off the screen.'))
            return
        if self._pending_change is not None:
            self._cancel_take()
        self._rehearsal_before = {
            "snapshot": self._stage_snapshot(),
            "outputs": {role: self._show_output(role) for role in STAGE_ROLES},
            "show": (self.show_index, getattr(self, "_show_step_id", None), self._show_started),
            "players": (self._show_players, self._show_active),
        }
        monitor = RehearsalMonitor({role: self._stage_size(role) for role in STAGE_ROLES})
        monitor.endRequested.connect(self.end_rehearsal)
        monitor.soundChosen.connect(self._set_rehearsal_sound)
        for role, window in monitor.outputs.items():
            card = self.cards[role]
            player = window.engine.player
            player.positionChanged.connect(card.set_position)
            player.durationChanged.connect(card.set_duration)
            card.seekRequested.connect(player.setPosition)
            window.engine.errorOccurred.connect(lambda message, bound=role: self._on_engine_error(bound, message))
            window.engine.set_loop(card.is_repeating())
            window.engine.set_volume(card.volume_slider.value())
            window.engine.set_muted(card.mute_btn.isChecked())
            window.set_scale_mode(card.current_scale_mode())
            setattr(self, self.OUTPUT_ATTRS[role], window)
        self._rehearsal = monitor
        # the running order gets its own music players, so the hall's keep playing
        self._show_players = [SoundCue(-3, self), SoundCue(-4, self)]
        self._show_active = 0
        for player in self._show_players:
            player.set_master(self.sound_master.value())
        self.presenter.rehearsing = True
        self._set_rehearsal_sound("")
        self._push_top_settings()
        self._freshly_opened = set(STAGE_ROLES)
        self._restore_media_to_outputs()        # start from what the stage shows now
        self._freshly_opened = set()
        monitor.show()
        self.rehearse_btn.setChecked(True)
        self.rehearse_btn.setText(tr('  End rehearsal'))
        self._update_output_status()
        self.statusBar().showMessage(tr('REHEARSAL - everything goes to the rehearsal window; the stage is untouched.'),
                                     10000)

    def _set_rehearsal_sound(self, device_name: str) -> None:
        from PySide6.QtMultimedia import QMediaDevices

        device = next((d for d in QMediaDevices.audioOutputs() if d.description() == device_name), None) \
            if device_name else None
        mode = device if device is not None else "silent"
        for cue in list(self.sound.cues) + list(self._show_players):
            cue.rehearsal = mode
        for role in STAGE_ROLES:
            window = self._show_output(role)
            if window is None:
                continue
            window.engine.set_silenced(device is None)
            if device is not None:
                window.engine.set_device(device)

    def end_rehearsal(self) -> None:
        """Give the dashboard back the stage windows - which never stopped showing what they had."""
        monitor = self._rehearsal
        if monitor is None:
            return
        if self._share_live and self.share_receiver.window is self.main_output:
            self._end_share(tr("The rehearsal ended."))     # it was on the rehearsal window
        before = self._rehearsal_before
        if self.presenter.live:
            self.presenter.end()
        from PySide6.QtMultimedia import QMediaDevices

        wanted = self.audio_device_combo.currentData()
        device = next((d for d in QMediaDevices.audioOutputs() if d.description() == wanted), None) \
            if wanted else QMediaDevices.defaultAudioOutput()
        for cue in self.sound.cues:
            cue.end_rehearsal(device)
        for player in self._show_players:
            player.stop(0)
            player.deleteLater()
        self._show_players, self._show_active = before["players"]
        for role in STAGE_ROLES:
            window = self._show_output(role)
            if window is not None:
                window.engine.clear()
            setattr(self, self.OUTPUT_ATTRS[role], before["outputs"][role])
        self._rehearsal = None
        self.presenter.rehearsing = False
        monitor.hide()
        monitor.deleteLater()

        # the cards go back to describing the stage - without touching it
        snapshot = before["snapshot"]
        for role, want in snapshot["screens"].items():
            card = self.cards[role]
            card.blockSignals(True)
            card.set_scale_mode(want["scale"])
            card.blockSignals(False)
            for button, value in ((card.repeat_btn, want["loop"]), (card.mute_btn, want["muted"])):
                button.blockSignals(True)
                button.setChecked(value)
                button.blockSignals(False)
            if want["path"]:
                card.show_loaded(want["path"])
            else:
                card.reset_file()
            window = self._show_output(role)
            if window is not None:
                card.set_duration(window.engine.player.duration())
        self.top_card.text_edit.blockSignals(True)
        self.top_card.text_edit.setText(snapshot["marquee"]["text"])
        self.top_card.text_edit.blockSignals(False)
        self.loaded_preset, self._preset_dirty = snapshot["preset"]
        self._describe_preset_state()
        index, step_id, started = before["show"]
        self.show_index, self._show_step_id, self._show_started = index, step_id, started
        self._show_auto = None
        self.show_tab.set_running(index)
        if index < 0:
            self._show_timer.stop()
            self.show_tab.set_clock(None, None)
        self._undo_snapshot = None
        self.take_bar.forget_undo()
        self.rehearse_btn.setChecked(False)
        self.rehearse_btn.setText(tr('  Rehearse'))
        self._update_output_status()
        self._refresh_mini()
        self.statusBar().showMessage(tr('Rehearsal over - the dashboard drives the stage again, as it was.'), 8000)

    @Slot()
    def _take(self) -> None:
        change, self._pending_change = self._pending_change, None
        self.take_bar.clear_pending()
        self._sync_take_keys()
        if change is not None:
            self._record_change(change["title"], change["apply"], change["thumb"])

    @Slot()
    def _cancel_take(self) -> None:
        self._pending_change = None
        self.take_bar.clear_pending()
        self._sync_take_keys()
        self.statusBar().showMessage(tr('Preview cancelled - the stage was not changed.'), 4000)

    def _sync_take_keys(self) -> None:
        pending = self._pending_change is not None
        self._take_shortcut.setEnabled(pending)
        # Esc cancels, unless slides are on screen: then it is the clicker's "end"
        self._cancel_shortcut.setEnabled(pending and not self.presenter.live)

    def _thumb_for_path(self, path: str) -> Optional[QPixmap]:
        return small_picture(path, QSize(160, 90))

    def _text_thumb(self, title: str, subtitle: str) -> QPixmap:
        pixmap = QPixmap(160, 90)
        pixmap.fill(QColor("#05070b"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.TextAntialiasing)
        font = QFont("Segoe UI")
        font.setPixelSize(15)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(QRectF(4, 20, 152, 30), Qt.AlignCenter,
                         painter.fontMetrics().elidedText(title, Qt.ElideRight, 150))
        if subtitle:
            font.setPixelSize(10)
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(QColor("#cfd8e6"))
            painter.drawText(QRectF(4, 50, 152, 20), Qt.AlignCenter,
                             painter.fontMetrics().elidedText(subtitle, Qt.ElideRight, 150))
        painter.end()
        return pixmap

    # -- NEXT everywhere ------------------------------------------------------- #

    def _refresh_show_strip(self) -> None:
        steps = self.show_tab.steps()
        visible = bool(steps) and self.tabs.currentWidget() is not self.show_tab
        self.show_strip.setVisible(visible)
        if not visible:
            return
        index = self.show_index
        now = steps[index] if 0 <= index < len(steps) else None
        upcoming = steps[index + 1] if index + 1 < len(steps) else None
        caption = tr("NOW  ·  {0} / {1}").format(index + 1, len(steps)) if now else tr("READY")
        now_text = (now["title"] or tr("Untitled")) if now else tr("Press NEXT to start")
        next_text = (upcoming["title"] or tr("Untitled")) if upcoming else tr("— end of the show —")
        clock = ""
        if now is not None:
            elapsed = time.monotonic() - self._show_started
            clock = f"{int(elapsed // 60)}:{int(elapsed % 60):02d}"
        auto = tr("auto in {0} s").format(int(self._show_auto + 0.99)) if self._show_auto is not None else ""
        self.show_strip.set_state(caption, now_text, next_text, clock, auto, upcoming is not None)
        # Slides, Text and Screens have a gold button of their own; there, the step NEXT steps back
        self.show_strip.set_emphasis(self.tabs.currentWidget() in (self.tabs.widget(0), self.library, self.dj_page))

    # -- ready check ----------------------------------------------------------- #

    @Slot()
    def _open_ready_check(self) -> None:
        if self._ready_dialog is None:
            self._ready_dialog = desk_mod.ReadyCheckDialog(self._ready_checks, self._ready_action,
                                                           THEME, Icons, self)
        self._ready_dialog.refresh()
        self._ready_dialog.show()
        self._ready_dialog.raise_()
        self._ready_dialog.activateWindow()

    def _ready_check_open(self) -> bool:
        return self._ready_dialog is not None and self._ready_dialog.isVisible()

    def _audio_device_name(self) -> str:
        from PySide6.QtMultimedia import QMediaDevices

        chosen = self.audio_device_combo.currentData()
        if chosen:
            return str(chosen)
        return QMediaDevices.defaultAudioOutput().description()

    def _ready_checks(self) -> List[dict]:
        rows: List[dict] = []

        def add(status, title, detail="", action=None):
            rows.append({"status": status, "title": title, "detail": detail, "action": action})

        # -- screens -- #
        for role in STAGE_ROLES:
            label = ROLE_LABELS[role]
            name = self.routing_rows[role].screen_combo.currentData()
            window = self._show_output(role)
            if not name:
                add("fail", tr('{0}: no monitor chosen').format(label), tr('Pick its monitor on Screens & Setup.'),
                    (tr('Screens & Setup'), "screens"))
            elif self._screen_by_name(name) is None:
                add("fail", tr('{0}: its monitor is not connected').format(label),
                    tr('Windows does not report “{0}” - check the cable or the LED processor.').format(name))
            elif window is None:
                add("warn", tr('{0}: closed').format(label), tr('The monitor is there; its window is not open.'),
                    (tr('Open outputs'), "open"))
            else:
                card = self.cards[role]
                what = os.path.basename(card.current_path()) if card.current_path() else "black"
                add("ok", tr('{0}: open').format(label), tr('on screen: {0}').format(what))
        # -- sound -- #
        device = self._audio_device_name()
        hall = str(self.settings.value("ready/hall_audio", "") or "")
        if not device:
            add("fail", tr('No sound output device'), tr('Windows reports no speakers or mixer.'))
        elif hall and device != hall:
            add("warn", tr('Sound goes to {0}').format(device), tr("The hall's device is {0}.").format(hall),
                (tr("This is the hall's device"), "hall_audio"))
        elif hall:
            add("ok", tr('Sound: {0}').format(device), tr("the hall's device"))
        else:
            add("info", tr('Sound: {0}').format(device), tr("Is this the hall's mixer? Remember it, and the check will warn if the sound ever goes somewhere else."), (tr("Yes, this is the hall's"), "hall_audio"))
        if self.sound_master.value() == 0:
            add("warn", tr('Master volume is at 0'), tr('Sound cues and running-order music will be silent.'))
        # -- files -- #
        steps = self.show_tab.steps()
        gone = show_missing_files(steps)
        if not steps:
            add("info", tr('The running order is empty'), tr('Fine if this event is run by hand.'))
        elif gone:
            add("fail", tr('Running order: {0} file(s) missing').format(len(gone)),
                ", ".join(os.path.basename(p) for p in gone[:5]) + ("…" if len(gone) > 5 else ""))
        else:
            add("ok", tr('Running order “{0}”: {1} step(s)').format(self.show_store.current, len(steps)), tr('every file is there'))
        lost = sorted({os.path.basename(p) for card in self.cards.values()
                       for p in card.playlist.paths() + [card.current_path()] if p and not os.path.isfile(p)}
                      | {os.path.basename(cue.path) for cue in self.sound.cues
                         if cue.path and not os.path.isfile(cue.path)})
        if lost:
            add("warn", tr('{0} file(s) on the Live tab are missing').format(len(lost)), ", ".join(lost[:5]))
        # -- presentation -- #
        deck = self.presenter.deck
        if deck is not None:
            if deck.error:
                add("fail", tr('Presentation “{0}” did not open').format(deck.name), deck.error.splitlines()[0])
            elif deck.kind == "powerpoint" and self.presenter.in_powerpoint and not pres_mod.powerpoint_available():
                add("warn", tr('Presentation “{0}”').format(deck.name), tr('PowerPoint is not installed: it will show as pictures.'))
            else:
                add("ok", tr('Presentation “{0}”').format(deck.name), tr('{0} slides ready').format(deck.count or '…'))
        # -- clicker -- #
        last = self.presentation_tab._last_key
        ago = time.monotonic() - last[2] if last[2] else None
        if ago is not None and ago < 1800:
            minutes = int(ago // 60)
            add("ok", tr('Clicker works'), tr('last press: {0} → {1}, ').format(last[0], last[1])
                + (tr("{0} min ago").format(minutes) if minutes else tr("{0} s ago").format(int(ago))))
        else:
            add("warn", tr('Clicker not tested'), tr('Press any clicker button now - this row turns green. (Presses here are only a test: nothing moves.)'))
        # -- phone remote -- #
        if self.remote.running:
            guest = tr("  ·  guest link on") if self.remote.guest else ""
            add("ok", tr('Phone remote is on'), tr('{0} phone(s) connected{1}').format(self.remote.clients(), guest))
        else:
            add("info", tr('Phone remote is off'), tr('Only needed if someone runs the show from a phone.'),
                (tr('Phone remote…'), "remote"))
        if self.preview_first:
            add("info", tr('PREVIEW → TAKE is on'), tr('Files, presets and names chosen by hand wait for TAKE.'))
        return rows

    def _refresh_health(self) -> None:
        """The status bar's chips: screens, sound, clicker, phones, files."""
        if not self.isVisible():
            return
        items = []
        open_count = sum(1 for role in STAGE_ROLES if self._show_output(role) is not None)
        routed = sum(1 for role in STAGE_ROLES if self.routing_rows[role].screen_combo.currentData())
        items.append((tr('Screens {0}/{1}').format(open_count, len(STAGE_ROLES)),
                      "ok" if open_count == len(STAGE_ROLES) else ("warn" if open_count < routed else "info"),
                      tr('Stage windows open')))
        device = self._audio_device_name()
        hall = str(self.settings.value("ready/hall_audio", "") or "")
        short = device if len(device) <= 30 else device[:28] + "…"
        if self.sound_master.value() == 0:
            items.append((tr('Sound muted  ·  {0}').format(short), "warn", tr('Master volume is at 0')))
        elif hall and device != hall:
            items.append((tr('Sound: {0}').format(short), "warn", tr("Not the hall's device ({0})").format(hall)))
        else:
            items.append((tr('Sound: {0}').format(short), "ok" if hall else "info", device))
        last = self.presentation_tab._last_key
        ago = time.monotonic() - last[2] if last[2] else None
        if ago is not None and ago < 1800:
            items.append((tr("Clicker {0} min").format(int(ago // 60)) if ago >= 60 else "Clicker ✓", "ok",
                          tr('Last press: {0}').format(last[0])))
        else:
            items.append((tr('Clicker untested'), "info", tr('No clicker press seen yet')))
        if self.remote.running:
            items.append((tr('Phones {0}').format(self.remote.clients()), "ok", tr('The phone remote is on')))
        gone = show_missing_files(self.show_tab.steps())
        if gone:
            items.append((tr('{0} file(s) missing').format(len(gone)), "fail", "\n".join(gone[:8])))
        for role in sorted(self._lost_screens):
            items.insert(0, (tr("{0} monitor gone").format(ROLE_LABELS[role]), "fail",
                             "Windows lost this monitor. The picture comes back by itself when it returns."))
        self.health.set_items(items)

    @Slot()
    def _show_shortcuts(self) -> None:
        desk_mod.ShortcutsDialog(THEME, self).exec()

    def _ready_action(self, key: str) -> None:
        if key == "identify":
            self._identify_screens()
        elif key == "open":
            self._apply_routing()
        elif key == "screens":
            self._set_mode("setup", check=False)
            self.tabs.setCurrentWidget(self.screens_page)
        elif key == "hall_audio":
            self.settings.setValue("ready/hall_audio", self._audio_device_name())
        elif key == "remote":
            self._open_remote_dialog()

    def _build_preset_bar(self) -> QWidget:
        """
        Presets as pictures: what each one puts on the screens, the one that is
        on the screens now marked green (amber once it has been changed). One
        tap loads; saving, renaming and deleting are SETUP work, at the end of
        the row and on a right-click.
        """
        bar = QFrame()
        bar.setObjectName("bar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 6, 14, 6)
        layout.setSpacing(12)

        caption_box = QVBoxLayout()
        caption_box.setSpacing(4)
        caption_row = QHBoxLayout()
        caption_row.setSpacing(6)
        glyph = QLabel()
        glyph.setPixmap(Icons.get("list", CLR_MUTED, 16).pixmap(16, 16))
        caption_row.addWidget(glyph)
        caption = QLabel(tr('PRESETS'))
        caption.setObjectName("sectionTitle")
        caption.setToolTip(tr('Saved in {0}').format(PRESET_FILE))
        caption_row.addWidget(caption)
        caption_row.addStretch(1)
        caption_box.addLayout(caption_row)
        self.preset_state = QLabel()
        self.preset_state.setObjectName("cardHint")
        self.preset_state.setWordWrap(True)
        self.preset_state.setFixedWidth(150)
        caption_box.addWidget(self.preset_state)
        caption_box.addStretch(1)
        layout.addLayout(caption_box)

        # The chosen preset lives in a combo nobody sees: saving, deleting and
        # the autostart all read it, as they always have.
        self.preset_combo = QComboBox()
        self.preset_combo.hide()
        layout.addWidget(self.preset_combo)

        self.preset_strip = desk_mod.PresetStrip(THEME)
        self.preset_strip.presetClicked.connect(self._on_preset_tile)
        self.preset_strip.menuRequested.connect(self._preset_menu)
        layout.addWidget(self.preset_strip, 1)

        edit = QGridLayout()
        edit.setHorizontalSpacing(6)
        edit.setVerticalSpacing(6)
        new_btn = QPushButton(tr('  Save as new…'))
        new_btn.setIcon(Icons.get("plus", CLR_TEXT, 15))
        new_btn.setToolTip(tr('Store what is set up now under a new name'))
        new_btn.clicked.connect(self._save_preset_as)
        save_btn = QPushButton(tr('  Save'))
        save_btn.setIcon(Icons.get("save", CLR_TEXT, 15))
        save_btn.setToolTip(tr('Overwrite the chosen preset with what is set up now'))
        save_btn.clicked.connect(self._save_preset)
        new_preset_btn = desk_mod.HoldButton(tr('  Blank'), THEME)
        new_preset_btn.setIcon(Icons.get("refresh", CLR_TEXT, 15))
        new_preset_btn.setToolTip(tr('Clear everything and start a fresh show from blank - hold to confirm'))
        new_preset_btn.clicked.connect(self._new_preset)
        delete_btn = desk_mod.HoldButton(tr('  Delete'), THEME)
        delete_btn.setIcon(Icons.get("trash", CLR_TEXT, 15))
        delete_btn.setToolTip(tr('Remove the chosen preset - hold to confirm'))
        delete_btn.clicked.connect(self._delete_preset)
        edit.addWidget(new_btn, 0, 0)
        edit.addWidget(save_btn, 0, 1)
        edit.addWidget(new_preset_btn, 1, 0)
        edit.addWidget(delete_btn, 1, 1)
        layout.addLayout(edit)
        # hidden in SHOW mode
        self._preset_edit_widgets = [new_preset_btn, save_btn, new_btn, delete_btn]

        # video frames for the pictures arrive later; rebuild once they have
        self._preset_pictures_timer = QTimer(self)
        self._preset_pictures_timer.setSingleShot(True)
        self._preset_pictures_timer.timeout.connect(self._rebuild_preset_strip)
        thumbnailer().ready.connect(lambda *_a: self._preset_pictures_timer.start(400))
        return bar

    def _preset_picture(self, payload: dict) -> QPixmap:
        """A preset at a glance: the Main Stage, the side screens inset, the ceiling strip on top."""
        canvas = QPixmap(176, 99)
        canvas.fill(QColor("#05070b"))
        outputs = payload.get("outputs", {})
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        def cover(path: str, rect: QRect) -> bool:
            picture = small_picture(path, QSize(320, 180)) if path else None
            if picture is None or picture.isNull():
                return False
            scale = max(rect.width() / picture.width(), rect.height() / picture.height())
            sw, sh = rect.width() / scale, rect.height() / scale
            painter.drawPixmap(QRectF(rect), picture,
                               QRectF((picture.width() - sw) / 2, (picture.height() - sh) / 2, sw, sh))
            return True

        cover(outputs.get(ROLE_MAIN, {}).get("file", ""), QRect(0, 0, 176, 99))
        top_rect = QRect(0, 0, 176, 9)
        if not cover(outputs.get(ROLE_TOP, {}).get("file", ""), top_rect):
            painter.fillRect(top_rect, QColor(payload.get("top", {}).get("background", "#101828")))
        sides = outputs.get(ROLE_SIDES, {}).get("file", "")
        if sides:
            inset = QRect(6, 99 - 6 - 27, 48, 27)
            painter.fillRect(inset.adjusted(-1, -1, 1, 1), QColor(CLR_BG))
            if not cover(sides, inset):
                painter.fillRect(inset, QColor("#05070b"))
        painter.end()
        return canvas

    def _rebuild_preset_strip(self) -> None:
        items = [(name, self._preset_picture(self.presets.get(name) or {})) for name in self.presets.names()]
        self.preset_strip.set_presets(items)
        self._mark_preset_strip()

    def _mark_preset_strip(self) -> None:
        if hasattr(self, "preset_strip"):
            chosen = self.preset_combo.currentText() if self.preset_combo.isEnabled() else None
            self.preset_strip.mark(self.loaded_preset, self._preset_dirty, chosen)

    @Slot(str)
    def _on_preset_tile(self, name: str) -> None:
        self.preset_combo.setCurrentText(name)
        self._mark_preset_strip()
        self._load_preset()

    def _preset_menu(self, name: str, position) -> None:
        self.preset_combo.setCurrentText(name)
        self._mark_preset_strip()
        menu = QMenu(self)
        menu.addAction(tr('Put “{0}” on the screens').format(name), self._load_preset)
        if self.ui_mode == "setup":
            menu.addSeparator()
            menu.addAction(tr('Save what is set up now into “{0}”').format(name), self._save_preset)
            menu.addAction(tr('Delete “{0}”…').format(name), self._delete_preset)
        menu.exec(position)

    def _mark_preset_dirty(self) -> None:
        if not self._preset_dirty:
            self._preset_dirty = True
            self._describe_preset_state()

    def _describe_preset_state(self) -> None:
        self._mark_preset_strip()
        if self.loaded_preset is None:
            self.preset_state.setText(tr('nothing loaded'))
            self.preset_state.setStyleSheet(f"color: {CLR_MUTED};")
            return
        if self._preset_dirty:
            self.preset_state.setText(tr('●  {0} — changed, not saved').format(self.loaded_preset))
            self.preset_state.setStyleSheet(f"color: {CLR_WARN}; font-weight: 600;")
        else:
            self.preset_state.setText(tr('●  {0} is on the screens').format(self.loaded_preset))
            self.preset_state.setStyleSheet(f"color: {CLR_OK}; font-weight: 600;")

    def _build_live_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 10, 0, 0)
        outer.setSpacing(11)

        screens = QWidget()
        layout = QHBoxLayout(screens)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(11)

        self.main_card = OutputCard("Main Stage", "large central screen", ScaleMode.FIT)
        self._wire_card(self.main_card, ROLE_MAIN)
        layout.addWidget(self.main_card, 1)

        self.sides_card = OutputCard("Side Screens", "left + right, mirrored", ScaleMode.CROP)
        self._wire_card(self.sides_card, ROLE_SIDES)
        layout.addWidget(self.sides_card, 1)

        self.top_card = TopCard()
        self._wire_card(self.top_card, ROLE_TOP)
        self.top_card.colorRequested.connect(self._on_top_colour)
        self.top_card.marqueeTextChanged.connect(
            lambda text: self.top_output and self.top_output.set_marquee_text(text)
        )
        self.top_card.marqueeFontSizeChanged.connect(
            lambda size: self.top_output and self.top_output.set_marquee_font_size(size)
        )
        self.top_card.marqueeFamilyChanged.connect(
            lambda family: self.top_output and self.top_output.set_marquee_family(family)
        )
        self.top_card.marqueeColorChanged.connect(
            lambda colour: self.top_output and self.top_output.set_marquee_color(colour)
        )
        self.top_card.marqueeSpeedChanged.connect(
            lambda speed: self.top_output and self.top_output.set_marquee_speed(speed)
        )
        self.top_card.marqueeStart.connect(self._start_marquee)
        self.top_card.marqueeStop.connect(self._stop_marquee)
        for changed in (self.top_card.marqueeTextChanged, self.top_card.marqueeColorChanged,
                        self.top_card.marqueeSpeedChanged, self.top_card.colorRequested):
            changed.connect(lambda *_a: self._mark_preset_dirty())
        layout.addWidget(self.top_card, 1)

        self.cards: Dict[str, OutputCard] = {
            ROLE_MAIN: self.main_card,
            ROLE_SIDES: self.sides_card,
            ROLE_TOP: self.top_card,
        }
        for role, card in self.cards.items():
            card.activated.connect(lambda bound=role: self.set_active_role(bound))

        outer.addWidget(screens, 1)
        outer.addWidget(self._build_sound_bar())
        return page

    # -------------------------------------------------------- mini bar ----- #

    def shrink_to_bar(self) -> None:
        """Hide the dashboard and leave a strip floating over everything else."""
        if self.mini is None:
            self.mini = MiniBar()
            self.mini.expandRequested.connect(self.restore_from_bar)
            self.mini.presetRequested.connect(self._mini_load_preset)
            self.mini.blackoutRequested.connect(self._blackout_all)
            self.mini.stopSoundRequested.connect(self._stop_all_sound)
            self.mini.stepRequested.connect(
                lambda delta: self._active_card().playlist.step(delta))
            self.mini.cueRequested.connect(self._fire_cue)
            self.mini.playPauseRequested.connect(self._toggle_active_playback)
            self.mini.screenChosen.connect(self.set_active_role)
            self.mini.showNextRequested.connect(self.show_next)
            self.mini.showBackRequested.connect(self.show_back)

        self.mini.set_presets(self.presets.names(), self.loaded_preset)
        self._refresh_mini_now()
        self.mini.adjustSize()

        stored = self.settings.value("window/mini_pos")
        if stored is not None:
            self.mini.move(stored)
        else:
            available = QGuiApplication.primaryScreen().availableGeometry()
            self.mini.move(available.center().x() - self.mini.width() // 2,
                           available.bottom() - self.mini.height() - 60)
        self.mini.show()
        self.mini.raise_()
        self.hide()
        self._mini_ticker.start(400)

    def _refresh_mini_now(self) -> None:
        """Fill the bar before it is shown, so it never appears blank."""
        was_visible = self.mini.isVisible()
        self.mini.setVisible(True)
        self._refresh_mini()
        self.mini.setVisible(was_visible)

    def restore_from_bar(self) -> None:
        if self.mini is not None:
            self.settings.setValue("window/mini_pos", self.mini.pos())
            self.mini.hide()
        self._mini_ticker.stop()
        self.show()
        self.raise_()
        self.activateWindow()

    def _refresh_mini(self) -> None:
        self._refresh_show_strip()
        if self.mini is None or not self.mini.isVisible():
            return
        role = self.active_role
        card = self.cards[role]
        window = getattr(self, self.OUTPUT_ATTRS[role], None)
        playing = False
        if window is not None:
            states = getattr(QMediaPlayer, "PlaybackState", None)
            playing = window.engine.player.playbackState() == getattr(
                states, "PlayingState", None)
        name = os.path.basename(card.current_path()) if card.current_path() else ""
        self.mini.show_screen(role, name, window is not None, playing)
        self.mini.show_cues(self.sound.cues)
        steps = self.show_tab.steps()
        now = steps[self.show_index] if 0 <= self.show_index < len(steps) else None
        upcoming = steps[self.show_index + 1] if self.show_index + 1 < len(steps) else None
        if now is None:
            text = tr("Running order ready · next: {0}").format(upcoming['title']) if upcoming else ""
        else:
            text = f"{self.show_index + 1}/{len(steps)}  {now['title']}" + (
                f"   →   {upcoming['title']}" if upcoming else "   ·   last step")
        self.mini.show_running(text, upcoming is not None, bool(steps))

    @Slot(str)
    def _mini_load_preset(self, name: str) -> None:
        payload = self.presets.get(name)
        if not payload:
            return
        self._apply_preset(payload)
        self.loaded_preset = name
        self._preset_dirty = False
        self._describe_preset_state()
        self._refresh_preset_combo(name)

    # ---------------------------------------------------- running order ---- #

    def _build_show_tab(self) -> QWidget:
        self.show_store = ShowStore(SHOW_FILE)
        self.show_tab = ShowTab(self.show_store, Icons, THEME, touch=self.touch_enabled(),
                                thumbs=lambda path: self._cached_thumb(path))
        thumbnailer().ready.connect(lambda *_a: self.show_tab.list.viewport().update())
        self.show_tab.nextRequested.connect(self.show_next)
        self.show_tab.backRequested.connect(self.show_back)
        self.show_tab.restartRequested.connect(self.show_restart)
        self.show_tab.goRequested.connect(self.show_go)
        self.show_tab.captureRequested.connect(self._capture_show_step)
        self.show_tab.remoteRequested.connect(self._open_remote_dialog)
        self.show_tab.showSwitched.connect(self.show_restart)
        self.show_tab.edited.connect(self._on_show_edited)
        self.show_tab.set_running(-1)
        return self.show_tab

    def _show_output(self, role: str):
        return getattr(self, self.OUTPUT_ATTRS[role], None)

    def _cached_thumb(self, path: str, width: int = 112, height: int = 64) -> Optional[QPixmap]:
        """Small pictures for lists that repaint often: made once, kept."""
        key = (path, width, height)
        picture = self._thumb_cache.get(key)
        if picture is None:
            picture = small_picture(path, QSize(width, height))
            if picture is not None:
                if len(self._thumb_cache) > 400:
                    self._thumb_cache.clear()
                self._thumb_cache[key] = picture
        return picture

    def _on_show_edited(self) -> None:
        """Steps added, moved or deleted mid-show: NOW stays on the step that is running."""
        ids = [s["id"] for s in self.show_tab.steps()]
        running = getattr(self, "_show_step_id", None)
        if self.show_index >= 0:
            self.show_index = ids.index(running) if running in ids else -1
            if self.show_index < 0:
                self.show_restart()
                return
        self.show_tab.set_running(self.show_index)
        self._refresh_mini()

    @Slot()
    def show_next(self) -> None:
        steps = self.show_tab.steps()
        if self.show_index + 1 < len(steps):
            self.show_go(self.show_index + 1)
        elif steps:
            self.statusBar().showMessage(tr('That was the last step of the running order.'), 5000)

    @Slot()
    def show_back(self) -> None:
        if self.show_index > 0:
            self.show_go(self.show_index - 1)

    @Slot()
    def show_restart(self) -> None:
        """Back to before step 1. The stage is left as it is until NEXT."""
        self.show_index = -1
        self._show_auto = None
        self._show_timer.stop()
        self.show_tab.set_running(-1)
        self.show_tab.set_clock(None, None)
        self._refresh_mini()

    @Slot(int)
    def show_go(self, index: int) -> None:
        """
        Put step `index` on stage. Everything the step sets is done; everything
        it leaves alone is brought to where the earlier steps put it, so a jump
        or a step back lands exactly where walking there would have.
        """
        steps = self.show_tab.steps()
        if not 0 <= index < len(steps):
            return
        target = show_fold(steps, index)
        step = steps[index]
        # One step forward does just what that step says, so anything the
        # operator changed by hand stays changed. Back and jumps replay the
        # earlier steps to land where walking there would have.
        only_explicit = index == self.show_index + 1
        self._open_outputs_for(target)
        with self._direct():
            problems = self._apply_show_state(target, step, only_explicit)
        self.show_index = index
        self._show_step_id = step["id"]
        self._show_started = time.monotonic()
        if index + 1 < len(steps):
            upcoming = steps[index + 1]
            for role in STAGE_ROLES:
                if upcoming["screens"][role]["mode"] == "file":
                    warm_file(upcoming["screens"][role]["path"])
            if upcoming["sound"]["mode"] == "play":
                warm_file(upcoming["sound"]["path"])
        self._show_sound_started = step["sound"]["mode"] == "play" and not problems
        self.show_tab.set_running(index)
        self._show_tick()
        self._show_timer.start(250)
        self._refresh_mini()
        message = tr("Step {0} of {1}: {2}").format(index + 1, len(steps), step['title'])
        if problems:
            message += "   —   " + "; ".join(problems)
        self.statusBar().showMessage(message, 12000)

    def _open_outputs_for(self, target: dict) -> None:
        """A step that needs a screen that is closed opens the outputs, like OPEN OUTPUTS."""
        needed = [role for role in STAGE_ROLES if target["screens"][role] is not None]
        if target["text"] is not None and target["text"]["mode"] == "show":
            needed.append(target["text"].get("target") or ROLE_MAIN)
        if target["marquee"] is not None and target["marquee"]["mode"] == "start":
            needed.append(ROLE_TOP)
        closed = [role for role in needed if self._show_output(role) is None
                  and self.routing_rows[role].screen_combo.currentData()]
        if closed:
            self._apply_routing()

    @staticmethod
    def _set_checked(button: QPushButton, checked: bool) -> None:
        if button.isChecked() != checked:
            button.setChecked(checked)          # emits, so the output follows

    def _apply_show_state(self, target: dict, step: dict, only_explicit: bool = False) -> List[str]:
        problems: List[str] = []
        fade = self.fade_ms()
        if only_explicit:
            target = dict(target)
            target["screens"] = {role: (target["screens"][role] if step["screens"][role]["mode"] != "keep"
                                        else None) for role in STAGE_ROLES}
            for part in ("sound", "text", "marquee", "slides"):
                if step.get(part, {}).get("mode", "keep") == "keep":
                    target[part] = None

        # -- screens -- #
        for role in STAGE_ROLES:
            entry = target["screens"][role]
            if entry is None:
                continue
            explicit = step["screens"][role]["mode"] != "keep"
            card = self.cards[role]
            window = self._show_output(role)
            if window is None:
                problems.append(tr("{0} is not open").format(ROLE_LABELS[role]))
                continue
            if explicit and self.presenter.live and self.presenter.role == role:
                self.presenter.release()     # this step puts something else on that screen
            if entry["mode"] == "black":
                if card.current_path() or explicit:
                    window.fade_clear(fade)
                    card.reset_file()
                continue
            path = entry["path"]
            if not path or not os.path.isfile(path):
                problems.append(tr("missing file {0}").format(os.path.basename(path) or tr('(none chosen)')))
                continue
            current = card.current_path()
            same = bool(current) and os.path.normcase(os.path.abspath(current)) == \
                os.path.normcase(os.path.abspath(path))
            self._set_checked(card.repeat_btn, bool(entry["loop"]))
            self._set_checked(card.mute_btn, not entry["audio"])
            if same and (entry["loop"] or not explicit):
                continue                    # already there: do not restart it
            card.show_loaded(path)
            card.loadRequested.emit(path)

        # -- sound -- #
        entry = target["sound"]
        if entry is not None:
            explicit = step["sound"]["mode"] != "keep"
            active = self._show_players[self._show_active]
            if entry["mode"] == "play":
                playing_same = active.is_playing() and os.path.normcase(active.path) == \
                    os.path.normcase(entry["path"] or "")
                # a one-off fanfare from an earlier step is not replayed on a jump
                wanted = (explicit and not (playing_same and entry["loop"])) or \
                         (not explicit and entry["loop"] and not playing_same)
                if wanted:
                    problem = self._show_play(entry)
                    if problem:
                        problems.append(problem)
            elif entry["mode"] in ("fade", "silence"):
                for player in self._show_players:
                    player.stop(1500)
                if entry["mode"] == "silence":
                    self.sound.stop_all(1500)

        # -- words on screen -- #
        entry = target["text"]
        if entry is not None:
            explicit = step["text"]["mode"] != "keep"
            if entry["mode"] == "show":
                role = entry.get("target") or ROLE_MAIN
                key = (role, entry["title"], entry["subtitle"])
                for other in STAGE_ROLES:
                    window = self._show_output(other)
                    if other != role and window is not None and window.slide_visible():
                        window.hide_slide(max(120, fade // 2))
                window = self._show_output(role)
                if window is None:
                    problems.append(tr("{0} is not open for the text").format(ROLE_LABELS[role]))
                elif explicit or self._show_text_shown != key or not window.slide_visible():
                    window.set_slide_style(self.text_slides.style_dict())
                    window.show_slide(entry["title"], entry["subtitle"], max(120, fade // 2))
                    self._show_text_shown = key
            else:
                for window in self._outputs():
                    if window.slide_visible():
                        window.hide_slide(max(120, fade // 2))
                self._show_text_shown = None

        # -- ceiling marquee -- #
        entry = target["marquee"]
        if entry is not None:
            explicit = step["marquee"]["mode"] != "keep"
            top = self.top_output
            if entry["mode"] == "start" and entry["text"].strip():
                if self.top_card.text_edit.text() != entry["text"]:
                    self.top_card.text_edit.setText(entry["text"])
                if top is None:
                    problems.append("Top Screen is not open for the marquee")
                elif explicit or not top.is_marquee_running():
                    self._start_marquee()
            elif entry["mode"] == "stop" and top is not None and top.is_marquee_running():
                self._stop_marquee()

        # -- presentation -- #
        entry = target.get("slides")
        presenter = self.presenter
        if entry is not None:
            explicit = step.get("slides", {}).get("mode", "keep") != "keep"
            if entry["mode"] == "start":
                path = entry["path"]
                role = entry.get("target") or ROLE_MAIN
                if not path or not os.path.exists(path):
                    problems.append(tr("missing presentation {0}").format(os.path.basename(path) or tr('(none chosen)')))
                else:
                    same = presenter.deck is not None and \
                        os.path.normcase(presenter.deck.path) == os.path.normcase(os.path.normpath(path))
                    error = None if same else presenter.open(path)
                    if error:
                        problems.append(error)
                    else:
                        if same and explicit:
                            presenter.goto(0)
                        if explicit or not presenter.live or presenter.role != role:
                            presenter.go_live_when_ready(role)
            elif entry["mode"] == "end" and presenter.live:
                presenter.end()
        return problems

    def _show_play(self, entry: dict) -> Optional[str]:
        """Fade the running order's music over to `entry`, on the other player."""
        path = entry["path"]
        if not path or not os.path.isfile(path):
            return tr('missing sound {0}').format(os.path.basename(path) or tr('(none chosen)'))
        old = self._show_players[self._show_active]
        new = self._show_players[1 - self._show_active]
        try:
            new.assign(path)
        except MediaProblem as problem:
            return f"{os.path.basename(path)}: {problem.title}"
        new.set_master(self.sound_master.value())
        new.set_level(int(entry.get("level", 90)))
        new.set_loop(bool(entry["loop"]))
        if old.is_playing() or old.is_paused():
            old.stop(1200)
        new.play()
        self._show_active = 1 - self._show_active
        return None

    def _show_tick(self) -> None:
        steps = self.show_tab.steps()
        if not 0 <= self.show_index < len(steps):
            self._show_timer.stop()
            self.show_tab.set_clock(None, None)
            self._show_auto = None
            return
        step = steps[self.show_index]
        elapsed = time.monotonic() - self._show_started
        has_next = self.show_index + 1 < len(steps)
        advance = step["advance"]
        remaining, note, go_on = None, "", False
        if has_next and advance["mode"] == "after":
            remaining = max(0.0, float(advance["seconds"]) - elapsed)
            go_on = remaining <= 0
        elif has_next and advance["mode"] == "video":
            note = "goes on when the video ends"
            window = self.main_output
            status = getattr(QMediaPlayer, "MediaStatus", None)
            end = getattr(status, "EndOfMedia", None)
            go_on = window is not None and elapsed > 1.0 and \
                window.engine.player.mediaStatus() == end
        elif has_next and advance["mode"] == "sound":
            note = "goes on when the sound ends"
            player = self._show_players[self._show_active]
            go_on = self._show_sound_started and elapsed > 1.0 and \
                not player.is_playing() and not player.is_paused()
        self._show_auto = remaining
        self.show_tab.set_clock(elapsed, remaining, note)
        self._refresh_show_strip()
        if go_on:
            self.show_next()

    @Slot()
    def _capture_show_step(self) -> None:
        """A new step that recreates what is on stage right now."""
        step = new_step(tr("Step {0}").format(len(self.show_tab.steps()) + 1))
        for role in STAGE_ROLES:
            card = self.cards[role]
            path = card.current_path()
            if path:
                step["screens"][role] = {"mode": "file", "path": path, "loop": card.is_repeating(),
                                         "audio": not card.mute_btn.isChecked()}
            elif self._show_output(role) is not None:
                step["screens"][role]["mode"] = "black"
        player = self._show_players[self._show_active]
        if player.is_playing() and player.path:
            step["sound"] = {"mode": "play", "path": player.path, "loop": player.loop, "level": player.level}
        if self.top_output is not None and self.top_output.is_marquee_running():
            step["marquee"] = {"mode": "start", "text": self.top_card.text_edit.text()}
        if self.presenter.live and self.presenter.deck is not None:
            step["slides"] = {"mode": "start", "path": self.presenter.deck.path, "target": self.presenter.role}
        self.show_tab.add_step(step)
        self.statusBar().showMessage(tr('Step added from what is on stage now - give it a name.'), 6000)

    # ------------------------------------------------------ phone remote --- #

    def _restore_remote(self) -> None:
        pin = str(self.settings.value("remote/pin", "") or "")
        if len(pin) != 4 or not pin.isdigit():
            pin = remote_mod.new_pin()
            self.settings.setValue("remote/pin", pin)
        self.remote.pin = pin
        self.remote.guest = str(self.settings.value("remote/guest", "") or "")
        try:
            self.remote.port = int(self.settings.value("remote/port", remote_mod.DEFAULT_PORT))
        except (TypeError, ValueError):
            self.remote.port = remote_mod.DEFAULT_PORT
        self.remote.clientsChanged.connect(lambda _n: self._describe_remote())
        if str(self.settings.value("remote/enabled", "false")).lower() == "true":
            self.remote.start(self.remote.port)
        self._describe_remote()

    # -- laptop screen share ---------------------------------------------------- #

    def _restore_share(self) -> None:
        code = str(self.settings.value("share/code", "") or "")
        if len(code) != 4 or not code.isdigit():
            code = share_mod.new_code()
            self.settings.setValue("share/code", code)
        self.share.code = code
        try:
            self.share.port = int(self.settings.value("share/port", share_mod.DEFAULT_SHARE_PORT))
        except (TypeError, ValueError):
            self.share.port = share_mod.DEFAULT_SHARE_PORT
        try:
            volume = int(self.settings.value("share/volume", 100))
        except (TypeError, ValueError):
            volume = 100
        self.share_bar.volume.blockSignals(True)
        self.share_bar.volume.setValue(volume)
        self.share_bar.volume.blockSignals(False)
        self.share_receiver.volume = volume / 100.0
        self.share.requestArrived.connect(self._on_share_request)
        self.share.requestGone.connect(self._on_share_gone)
        self.share_receiver.answered.connect(self._on_share_answered)
        self.share_receiver.failed.connect(self._on_share_failed)
        self.share_receiver.stateChanged.connect(self._on_share_state)
        self.share_receiver.statsChanged.connect(lambda _stats: self._refresh_share_bar())
        self.share_receiver.detached.connect(
            lambda: self._end_share(tr("The Main Stage screen was closed.")))
        if str(self.settings.value("share/enabled", "false")).lower() == "true":
            self._toggle_share(True)
        self._describe_share()

    def _share_on(self, window) -> bool:
        """Whether a laptop's picture covers this stage window right now."""
        receiver = self.share_receiver
        return bool(self._share_live) and window is not None and receiver.window is window \
            and receiver.view is not None and receiver.view.isVisible()

    def _toggle_share(self, on: bool) -> str:
        error = ""
        if on:
            if not self.share_receiver.available():
                error = tr("This installation of PySide6 has no QtWebEngine.")
            else:
                error = self.share.start(self.share.port) or ""
                self.settings.setValue("share/port", self.share.port)
                if not error:
                    # Chromium starts now, so the first laptop is on screen at once
                    QTimer.singleShot(1500, self.share_receiver.warm_up)
        else:
            self._end_share(tr("The stage desk switched the screen share off."))
            self.share.stop()
        self.settings.setValue("share/enabled", "true" if self.share.running else "false")
        if self._share_dialog is not None:
            self._share_dialog.refresh(error)
        self._refresh_share_bar()
        self._describe_share()
        return error

    @Slot()
    def _open_share_dialog(self) -> None:
        if self._share_dialog is None:
            auto = str(self.settings.value("share/auto", "false")).lower() == "true"
            dialog = share_mod.ShareDialog(self.share, THEME, self, auto=auto)
            dialog.toggled.connect(self._toggle_share)
            dialog.portChanged.connect(lambda port: setattr(self.share, "port", port))
            dialog.codeRenewed.connect(self._renew_share_code)
            dialog.autoToggled.connect(lambda on: self.settings.setValue("share/auto", "true" if on else "false"))
            self._share_dialog = dialog
        self._share_dialog.refresh()
        self._share_dialog.show()
        self._share_dialog.raise_()

    def _renew_share_code(self) -> None:
        self.settings.setValue("share/code", self.share.new_code())
        if self._share_dialog is not None:
            self._share_dialog.refresh()

    def _describe_share(self) -> None:
        tab = getattr(self, "presentation_tab", None)
        if tab is None:
            return
        if self.share.running:
            tab.laptop_btn.setText(tr("  Laptop screen share · ON"))
            tab.laptop_btn.setStyleSheet(f"color: {CLR_OK}; font-weight: 600;")
        else:
            tab.laptop_btn.setText(tr("  Laptop screen share…"))
            tab.laptop_btn.setStyleSheet("")

    @Slot(str)
    def _on_share_request(self, ident: str) -> None:
        request = self.share.request(ident)
        if request is None:
            return
        if not self._share_live and str(self.settings.value("share/auto", "false")).lower() == "true":
            self._accept_share(ident)
            return
        self._refresh_share_bar()
        self.statusBar().showMessage(
            tr("{0} wants to share their screen - Show on Main Stage puts it there.").format(request.name), 10000)
        QApplication.alert(self)

    @Slot(str)
    def _accept_share(self, ident: str) -> None:
        request = self.share.request(ident)
        if request is None or request.state != "waiting":
            self._refresh_share_bar()
            return
        window = self.main_output
        if window is None:
            self.statusBar().showMessage(
                tr("Open the Main Stage screen first - the laptop's picture goes there."), 8000)
            return
        if self._share_live and self._share_live != ident:
            self.share.end(self._share_live, tr("The stage desk switched to another laptop."))
        self._share_live = ident
        self._share_lost_at = 0.0
        self.share_receiver.receive(ident, request.offer, window)
        self._watch_share_window(window)
        self._refresh_share_bar()
        self.statusBar().showMessage(tr("{0}: connecting to the Main Stage…").format(request.name), 6000)

    @Slot(str, str)
    def _on_share_answered(self, ident: str, sdp: str) -> None:
        if not self.share.go_live(ident, sdp) and ident == self._share_live:
            self._end_share("")             # the laptop gave up while the desk was answering

    @Slot(str, str)
    def _on_share_failed(self, ident: str, why: str) -> None:
        if ident == self._share_live:
            self._end_share(tr("The stage could not show this screen."))
            self.statusBar().showMessage(tr("Screen share failed: {0}").format(why), 10000)

    @Slot(str)
    def _decline_share(self, ident: str) -> None:
        self.share.decline(ident)
        self._refresh_share_bar()

    def _end_share(self, message: str = "") -> None:
        ident, self._share_live = self._share_live, ""
        self._watch_share_window(None)
        self.share_receiver.stop()
        if ident:
            self.share.end(ident, message)
        self._refresh_share_bar()

    def _watch_share_window(self, window) -> None:
        """A new picture sent to the Main Stage - a step, a preset, a file - takes the laptop off it."""
        old = getattr(self, "_share_watched", None)
        if old is not None:
            try:
                old.pictureReplaced.disconnect(self._on_share_covered)
            except (RuntimeError, TypeError):
                pass                        # the window has gone already
        self._share_watched = window
        if window is not None:
            window.pictureReplaced.connect(self._on_share_covered)

    @Slot()
    def _on_share_covered(self) -> None:
        if self._share_live:
            self._end_share(tr("The stage desk put something else on the Main Stage."))
            self.statusBar().showMessage(tr("The laptop came off the Main Stage for the new picture."), 6000)

    @Slot(str)
    def _on_share_gone(self, ident: str) -> None:
        if ident == self._share_live:
            request = self.share.request(ident)
            self._end_share("")
            self.statusBar().showMessage(
                tr("{0} stopped sharing - the Main Stage shows what it had before.").format(
                    request.name if request else tr("The laptop")), 8000)
        self._refresh_share_bar()

    @Slot(str)
    def _on_share_state(self, state: str) -> None:
        if state == "connected":
            self._share_lost_at = 0.0
            request = self.share.request(self._share_live)
            if request is not None:
                self.statusBar().showMessage(tr("{0} is on the Main Stage.").format(request.name), 6000)
        elif state == "failed":
            self._end_share(tr("The connection was lost."))
            self.statusBar().showMessage(tr("The laptop's connection was lost."), 8000)
        elif state == "disconnected":
            # Wi-Fi hiccups reconnect by themselves; give it a few seconds before giving up
            self._share_lost_at = time.monotonic()
            QTimer.singleShot(8000, self._check_share_lost)
        self._refresh_share_bar()

    def _check_share_lost(self) -> None:
        if self._share_live and self._share_lost_at and time.monotonic() - self._share_lost_at >= 7.5 \
                and self.share_receiver.state == "disconnected":
            self._end_share(tr("The connection was lost."))
            self.statusBar().showMessage(tr("The laptop's connection was lost."), 8000)

    @Slot(int)
    def _on_share_volume(self, value: int) -> None:
        self.share_receiver.set_volume(value / 100.0)
        self.settings.setValue("share/volume", value)

    def _refresh_share_bar(self) -> None:
        bar = getattr(self, "share_bar", None)
        if bar is None:
            return
        live = self.share.request(self._share_live) if self._share_live else None
        waiting = self.share.waiting() if self.share.running else []
        if waiting:
            bar.show_waiting(waiting[0], len(waiting) - 1, replacing=live.name if live else "")
        elif live is not None:
            bar.show_live(live, self.share_receiver.stats, self.share_receiver.state == "connected")
        else:
            bar.hide()

    def _describe_remote(self) -> None:
        if self.remote.running:
            count = self.remote.clients()
            self.show_tab.remote_btn.setText(tr('  Phone remote · ON').format() + (f" ({count})" if count else ""))
            self.show_tab.remote_btn.setStyleSheet(f"color: {CLR_OK}; font-weight: 600;")
        else:
            self.show_tab.remote_btn.setText(tr('  Phone remote'))
            self.show_tab.remote_btn.setStyleSheet("")

    @Slot()
    def _open_remote_dialog(self) -> None:
        if self._remote_dialog is None:
            qr_pin = str(self.settings.value("remote/qr_pin", "false")).lower() == "true"
            dialog = remote_mod.RemoteDialog(self.remote, THEME, self, qr_with_pin=qr_pin)
            dialog.toggled.connect(self._toggle_remote)
            dialog.portChanged.connect(lambda port: setattr(self.remote, "port", port))
            dialog.pinRenewed.connect(self._renew_remote_pin)
            dialog.qrPinToggled.connect(
                lambda on: self.settings.setValue("remote/qr_pin", "true" if on else "false"))
            dialog.guestRequested.connect(self._open_guest_dialog)
            self._remote_dialog = dialog
        self._remote_dialog.refresh()
        self._remote_dialog.show()
        self._remote_dialog.raise_()

    def _toggle_remote(self, on: bool) -> None:
        error = ""
        if on:
            error = self.remote.start(self.remote.port) or ""
            self.settings.setValue("remote/port", self.remote.port)
        else:
            self.remote.stop()
        self.settings.setValue("remote/enabled", "true" if self.remote.running else "false")
        if self._remote_dialog is not None:
            self._remote_dialog.refresh(error)
        if self._guest_dialog is not None:
            self._guest_dialog.refresh(error)
        self._describe_remote()
        return error

    @Slot()
    def _open_guest_dialog(self) -> None:
        """The guest slide clicker: its own QR code, slides only. Switches the remote on if needed."""
        if not self.remote.guest:
            self._set_guest_link(True)
        error = "" if self.remote.running else self._toggle_remote(True)
        if self._guest_dialog is None:
            dialog = remote_mod.GuestDialog(self.remote, THEME, self)
            dialog.enabledToggled.connect(self._set_guest_link)
            dialog.renewRequested.connect(lambda: self._set_guest_link(True, renew=True))
            self._guest_dialog = dialog
        self._guest_dialog.refresh(error)
        self._guest_dialog.show()
        self._guest_dialog.raise_()
        self._guest_dialog.activateWindow()

    def _set_guest_link(self, on: bool, renew: bool = False) -> None:
        if on and (renew or not self.remote.guest):
            self.remote.guest = remote_mod.new_guest_token()
        elif not on:
            self.remote.guest = ""
        self.settings.setValue("remote/guest", self.remote.guest)
        if self._guest_dialog is not None:
            self._guest_dialog.refresh()

    def _renew_remote_pin(self) -> None:
        self.remote.pin = remote_mod.new_pin()
        self.settings.setValue("remote/pin", self.remote.pin)
        if self._remote_dialog is not None:
            self._remote_dialog.refresh()

    def remote_state(self) -> dict:
        """Everything the phone page draws, in one small JSON object."""
        steps = self.show_tab.steps()
        index = self.show_index if self.show_index < len(steps) else -1
        screens = []
        for role in STAGE_ROLES:
            path = self.cards[role].current_path()
            state, moving, version = self._screen_state(role)
            screens.append({"role": role, "label": ROLE_LABELS[role],
                            "open": self._show_output(role) is not None,
                            "file": os.path.basename(path) if path else "",
                            "state": state, "moving": moving, "version": version})
        cues = [{"index": cue.index, "label": cue.label(), "filled": bool(cue.path),
                 "playing": cue.is_playing(), "paused": cue.is_paused()} for cue in self.sound.cues]
        return {
            "show": {"name": self.show_store.current, "index": index,
                     "steps": [{"title": s["title"] or "Untitled", "notes": s["notes"],
                                "summary": step_summary(s)} for s in steps],
                     "elapsed": time.monotonic() - self._show_started if index >= 0 else 0,
                     "auto": self._show_auto if index >= 0 else None},
            "screens": screens,
            "cues": cues,
            "presets": self.presets.names(),
            "preset": self.loaded_preset or "",
            "master": self.sound_master.value(),
            "slides": self._slides_state(),
        }

    def _slides_state(self) -> dict:
        presenter = self.presenter
        deck = presenter.deck
        return {"loaded": bool(deck and presenter.count()), "name": deck.name if deck else "",
                "count": presenter.count(), "index": presenter.index, "live": presenter.live,
                "black": presenter.black, "elapsed": presenter.elapsed(),
                "deck": deck.token if deck else "", "notes": presenter.notes(),
                "target": ROLE_LABELS.get(presenter.role, presenter.role),
                "powerpoint": presenter.playing_in_powerpoint()}

    def remote_action(self, action: str, data: dict):
        """One tap on the phone. Returns (ok, message for the phone)."""
        steps = self.show_tab.steps()
        if action == "next":
            if self.show_index + 1 >= len(steps):
                return False, tr('That was the last step.')
            self.show_next()
            return True, f"{self.show_index + 1}. {steps[self.show_index]['title']}"
        if action == "back":
            if self.show_index <= 0:
                return False, tr('Already at the first step.')
            self.show_back()
            return True, f"{self.show_index + 1}. {steps[self.show_index]['title']}"
        if action == "goto":
            try:
                index = int(data.get("index", -1))
            except (TypeError, ValueError):
                index = -1
            if not 0 <= index < len(steps):
                return False, tr('No such step.')
            self.show_go(index)
            return True, f"{index + 1}. {steps[index]['title']}"
        if action == "restart":
            self.show_restart()
            return True, tr('Ready - NEXT starts step 1.')
        if action == "blackout":
            self._blackout_all()
            return True, tr('Blackout.')
        if action == "cue":
            try:
                index = int(data.get("index", -1))
            except (TypeError, ValueError):
                index = -1
            if not 0 <= index < len(self.sound.cues) or not self.sound.cues[index].path:
                return False, tr('That sound pad is empty.')
            self._fire_cue(index)
            return True, ""
        if action == "silence":
            self._stop_all_sound()
            return True, tr('Fading out all sound.')
        if action == "master":
            try:
                self.sound_master.setValue(max(0, min(100, int(data.get("value", 90)))))
            except (TypeError, ValueError):
                return False, tr('Bad volume.')
            return True, ""
        if action.startswith("slide_"):
            return self._remote_slide_action(action, data)
        if action == "preset":
            name = str(data.get("name", ""))
            if name not in self.presets.names():
                return False, tr('No such preset.')
            # later, so a dialog about a missing file cannot hold the phone's answer
            QTimer.singleShot(0, lambda: self._mini_load_preset(name))
            return True, tr('Loading {0}.').format(name)
        return False, tr('Unknown action.')

    # ------------------------------------------------------ text slides ---- #

    def _build_text_tab(self) -> QWidget:
        self.text_slides = TextSlides()
        self.text_slides.showRequested.connect(self._show_slide)
        self.text_slides.hideRequested.connect(self._hide_slide)
        self.text_slides.styleChanged.connect(self._on_slide_style_changed)
        self.text_slides.targetChanged.connect(self._on_slide_target_changed)
        self.text_slides.stage_size = self._stage_size
        self.text_slides.preview_source = (
            lambda role, size: self._show_output(role).preview(size) if self._show_output(role) else None)
        try:
            self.text_slides.set_custom_looks(json.loads(self.settings.value("text/looks", "") or "{}"))
        except (ValueError, TypeError):
            pass
        self.text_slides.looksChanged.connect(
            lambda: self.settings.setValue("text/looks", json.dumps(self.text_slides.custom_looks)))
        return self.text_slides

    def _slide_output(self):
        role = self.text_slides.target.currentData() or ROLE_MAIN
        return role, getattr(self, self.OUTPUT_ATTRS[role], None)

    @Slot(str, str)
    def _show_slide(self, title: str, subtitle: str) -> None:
        role, window = self._slide_output()
        if window is None:
            QMessageBox.warning(
                self, tr('Output not open'),
                tr('“{0}” has no output window yet.\n\nOpen the “Screens & Setup” tab, pick a monitor for it, then press “OPEN OUTPUTS”.').format(ROLE_LABELS[role]))
            return

        def apply() -> None:
            role_now, target = self._slide_output()
            if target is None:
                return
            target.set_slide_style(self.text_slides.style_dict())
            target.show_slide(title, subtitle, max(120, self.fade_ms() // 2))
            self.statusBar().showMessage(
                f"{ROLE_LABELS[role_now]}: {title}" + (f" — {subtitle}" if subtitle else ""), 8000)

        self._change_stage(f"{ROLE_LABELS[role]}  ←  “{title}”", apply,
                           self._text_thumb(title, subtitle), subtitle)

    @Slot()
    def _hide_slide(self) -> None:
        role, window = self._slide_output()
        if window is None:
            return
        window.hide_slide(max(120, self.fade_ms() // 2))
        self.statusBar().showMessage(tr('{0}: text hidden.').format(ROLE_LABELS[role]), 5000)

    @Slot()
    def _on_slide_style_changed(self) -> None:
        self._mark_preset_dirty()
        _role, window = self._slide_output()
        if window is not None and window.slide_visible():
            window.set_slide_style(self.text_slides.style_dict())

    @Slot(str)
    def _on_slide_target_changed(self, _role: str) -> None:
        """Moving the text to another screen must not leave it on the old one."""
        for window in self._outputs():
            window.hide_slide(200)
        self._mark_preset_dirty()

    # --------------------------------------------------------- library ----- #

    @Slot()
    def build_show_from_folder(self) -> None:
        """
        Turn one event folder into a whole show.

        Everything for an assembly usually lives in a single folder already -
        the backgrounds, the clips, the fanfares. Reading the shape of each file
        is enough to sort it: the ceiling clips are 2816x128, the side clips are
        portrait, the rest is 16:9, and the sound is whatever is audio.
        """
        folder = QFileDialog.getExistingDirectory(
            self, tr('Choose the folder for this event'), self.library.current_folder() or "")
        if not folder:
            return
        folder = os.path.normpath(folder)

        files = scan_event_folder(folder)
        if not files:
            QMessageBox.information(
                self, tr('Nothing to import'),
                tr('No images, videos or sounds were found in\n{0}').format(folder))
            return

        progress = QProgressDialog(tr('Looking at the files…'), tr('Cancel'), 0, len(files), self)
        progress.setWindowTitle(tr('Building a show'))
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        rows = []
        for index, path in enumerate(files):
            if progress.wasCanceled():
                return
            progress.setValue(index)
            progress.setLabelText(os.path.basename(path))
            QApplication.processEvents()
            size = probe_media_size(path)
            rows.append((path, size, classify_media(path, size, folder)))
        progress.setValue(len(files))

        dialog = EventFolderDialog(folder, rows, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._apply_event_folder(folder, dialog.assignments(),
                                 dialog.replace_check.isChecked(),
                                 dialog.go_live_check.isChecked())

    def _apply_event_folder(self, folder: str, assignments: Dict[str, List[str]],
                            replace: bool, go_live: bool) -> None:
        if replace:
            for card in self.cards.values():
                card.playlist.clear_all()
                card.reset_file()
            for cue in self.sound.cues:
                cue.clear()

        placed = []
        for role in STAGE_ROLES:
            paths = assignments.get(role, [])
            if not paths:
                continue
            self.cards[role].playlist.add_paths(paths, announce=False)
            placed.append(f"{len(paths)} on {ROLE_LABELS[role]}")

        sounds = assignments.get("sound", [])
        skipped_sounds = max(0, len(sounds) - SOUND_SLOTS)
        for slot, path in enumerate(sounds[:SOUND_SLOTS]):
            try:
                self.sound.cues[slot].assign(path)
            except MediaProblem:
                pass
        if sounds:
            placed.append(tr("{0} sound cue(s)").format(min(len(sounds), SOUND_SLOTS)))
        self._refresh_cue_pads()

        live_note = ""
        if go_live:
            # Only screens that actually have a window; otherwise this would
            # fire one "output not open" dialog per screen, in a row.
            open_roles = [r for r in STAGE_ROLES
                          if getattr(self, self.OUTPUT_ATTRS[r], None) is not None]
            with self._direct():
                for role in open_roles:
                    card = self.cards[role]
                    if card.playlist.count():
                        card.playlist.setCurrentRow(0)
                        card.loadRequested.emit(card.playlist.item(0).data(Qt.UserRole))
            if not open_roles:
                live_note = "  — nothing is on yet: press OPEN OUTPUTS first"


        self._mark_preset_dirty()
        self.library.set_folder(folder)
        self.tabs.setCurrentIndex(0)
        message = "Built from " + os.path.basename(folder) + ": " + ", ".join(placed)
        if skipped_sounds:
            message += tr("  ({0} extra sound file(s) left out - only {1} cues)").format(skipped_sounds, SOUND_SLOTS)
        message += live_note
        self.statusBar().showMessage(message, 15000)

    def _build_library_tab(self) -> QWidget:
        self.library = MediaLibrary()
        self.library.showRequested.connect(self._library_show)
        self.library.queueRequested.connect(self._library_queue)
        self.library.cueRequested.connect(self._assign_cue)
        self.library.buildRequested.connect(self.build_show_from_folder)
        self.library.favouritesChanged.connect(
            lambda: self.settings.setValue("library/favourites", self.library.favourites()))
        return self.library

    def _restore_library_places(self) -> None:
        stored = self.settings.value("library/folders", [])
        if isinstance(stored, str):
            stored = [stored] if stored else []
        self.library.set_pinned([str(f) for f in (stored or [])])
        favourites = self.settings.value("library/favourites", [])
        if isinstance(favourites, str):
            favourites = [favourites] if favourites else []
        self.library.set_favourites([str(f) for f in (favourites or [])])
        last = self.settings.value("library/last", "")
        folders = self.library.pinned()
        self.library.set_folder(last if last and os.path.isdir(last)
                                else (folders[0] if folders else ""), defer_files=True)

    def _remember_library_places(self) -> None:
        self.settings.setValue("library/folders", self.library.pinned())
        self.settings.setValue("library/last", self.library.current_folder())

    @Slot(str, str)
    def _library_show(self, role: str, path: str) -> None:
        card = self.cards[role]
        card.playlist.add_paths([path], announce=False)   # keeps the playlist in step
        self.set_active_role(role)
        card.loadRequested.emit(path)

    @Slot(str, list)
    def _library_queue(self, role: str, paths: List[str]) -> None:
        target = role or self.active_role
        card = self.cards[target]
        added = card.playlist.add_paths(list(paths), announce=False)
        self._mark_preset_dirty()
        self.statusBar().showMessage(
            tr('{0}: {1} item(s) added to the playlist').format(ROLE_LABELS[target], len(added))
            if added else tr('Already in that playlist.'), 6000)

    # ----------------------------------------------------------- sound ----- #

    def _build_sound_bar(self) -> QWidget:
        """
        The sound desk, kept on the Live tab rather than a tab of its own.

        During a ceremony the operator is switching backgrounds and firing
        fanfares in the same minute; putting sound behind a tab would mean
        looking away from the screens at exactly the wrong moment.
        """
        bar = QFrame()
        bar.setObjectName("card")
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(14, 8, 14, 10)
        layout.setSpacing(7)

        header = QHBoxLayout()
        header.setSpacing(8)
        glyph = QLabel()
        glyph.setPixmap(Icons.get("volume", CLR_ACCENT, 16).pixmap(16, 16))
        header.addWidget(glyph)
        title = QLabel(tr('Sound cues'))
        title.setObjectName("sectionTitle")
        header.addWidget(title)

        hint = QLabel(tr('drop sound files onto a pad · F1–F8 play and pause · Shift+F… stops'))
        hint.setObjectName("keyHint")
        header.addWidget(hint)
        header.addStretch(1)
        self.now_playing = QLabel("")
        self.now_playing.setToolTip(tr('The sound that ends soonest, and how long it has left'))
        header.addWidget(self.now_playing)
        header.addSpacing(10)

        header.addWidget(QLabel(tr('Output')))
        self.audio_device_combo = QComboBox()
        self.audio_device_combo.setMinimumWidth(190)
        self.audio_device_combo.setToolTip(tr('Which sound device every cue and video plays out of'))
        self.audio_device_combo.currentIndexChanged.connect(self._on_audio_device_changed)
        header.addWidget(self.audio_device_combo)

        header.addSpacing(8)
        header.addWidget(QLabel(tr('Master')))
        self.sound_master = QSlider(Qt.Horizontal)
        self.sound_master.setRange(0, 100)
        self.sound_master.setValue(self.sound.master)
        self.sound_master.setMaximumWidth(130)
        self.sound_master.valueChanged.connect(self._on_master_volume)
        header.addWidget(self.sound_master)

        fade_all = QPushButton(tr('  Fade out'))
        fade_all.setIcon(Icons.get("volume", CLR_TEXT, 15))
        fade_all.setToolTip(tr('Fade every sound out gently, over three seconds'))
        fade_all.clicked.connect(self._fade_all_sound)
        header.addWidget(fade_all)
        stop_all = QPushButton(tr('  STOP SOUND'))
        stop_all.setObjectName("danger")
        stop_all.setIcon(Icons.get("stop", CLR_DANGER, 15))
        stop_all.setToolTip(tr('Fade out and rewind every cue (Ctrl+Space)'))
        stop_all.clicked.connect(self._stop_all_sound)
        header.addWidget(stop_all)
        layout.addLayout(header)

        pads = QHBoxLayout()
        pads.setSpacing(7)
        self.cue_pads: List[CuePad] = []
        for index in range(SOUND_SLOTS):
            pad = CuePad(index)
            pad.assignRequested.connect(lambda path, i=index: self._assign_cue(i, path))
            pad.playPauseRequested.connect(lambda i=index: self._fire_cue(i))
            pad.stopRequested.connect(lambda i=index: self._stop_cue(i))
            pad.seekRequested.connect(lambda ms, i=index: self.sound.cues[i].seek(ms))
            pad.cleared.connect(lambda i=index: self._clear_cue(i))
            pad.loopToggled.connect(lambda on, i=index: self.sound.cues[i].set_loop(on))
            pads.addWidget(pad, 1)
            self.cue_pads.append(pad)
        layout.addLayout(pads)

        # One timer keeps the countdowns honest without a signal per cue.
        ticker = QTimer(self)
        ticker.timeout.connect(self._refresh_cue_pads)
        ticker.start(250)
        return bar

    def _refresh_audio_devices(self) -> None:
        from PySide6.QtMultimedia import QMediaDevices

        wanted = self.settings.value("sound/device", "")
        devices = QMediaDevices.audioOutputs()
        self.audio_device_combo.blockSignals(True)
        self.audio_device_combo.clear()
        self.audio_device_combo.addItem(tr('System default'), None)
        for device in devices:
            self.audio_device_combo.addItem(device.description(), device.description())
        index = self.audio_device_combo.findData(wanted) if wanted else -1
        self.audio_device_combo.setCurrentIndex(max(0, index))
        self.audio_device_combo.blockSignals(False)
        self._apply_audio_device()

    def _apply_audio_device(self) -> None:
        from PySide6.QtMultimedia import QMediaDevices

        wanted = self.audio_device_combo.currentData()
        device = None
        if wanted:
            device = next((d for d in QMediaDevices.audioOutputs()
                           if d.description() == wanted), None)
        if device is None:
            device = QMediaDevices.defaultAudioOutput()
        self.sound.set_device(device)
        for player in self._show_players:
            player.set_device(device)
        for window in self._outputs():
            window.engine.set_device(device)

    @Slot()
    def _on_audio_device_changed(self) -> None:
        self.settings.setValue("sound/device", self.audio_device_combo.currentData() or "")
        self._apply_audio_device()
        self.statusBar().showMessage(
            tr('Sound output: {0}').format(self.audio_device_combo.currentText()), 5000)

    @Slot(int)
    def _on_master_volume(self, value: int) -> None:
        self.sound.set_master(value)
        for player in self._show_players:
            player.set_master(value)
        self.settings.setValue("sound/master", value)

    def _refresh_cue_pads(self) -> None:
        for pad, cue in zip(self.cue_pads, self.sound.cues):
            pad.show_cue(cue)
        self._refresh_now_playing()

    def _refresh_now_playing(self) -> None:
        """Big and plain: what is playing, and how long until it stops."""
        playing = [cue for cue in list(self.sound.cues) + list(self._show_players) if cue.is_playing()]
        if not playing:
            if self.now_playing.text():
                self.now_playing.setText("")
            return

        def left(cue) -> float:
            if cue.loop or cue.duration() <= 0:
                return float("inf")
            return max(0, cue.duration() - cue.position())

        cue = min(playing, key=left)
        remaining = left(cue)
        name = cue.label() + ("  (running order)" if cue in self._show_players else "")
        more = f"   +{len(playing) - 1}" if len(playing) > 1 else ""
        if remaining == float("inf"):
            text, colour = tr("♪  {0}  ·  looping{1}").format(name, more), CLR_OK
        else:
            text = tr("♪  {0}  ·  {1} left{2}").format(name, format_time(int(remaining)), more)
            colour = CLR_WARN if remaining < 10000 else CLR_OK
        self.now_playing.setText(text)
        self.now_playing.setStyleSheet(f"color: {colour}; font-size: 15px; font-weight: 700;")

    @Slot()
    def _fade_all_sound(self) -> None:
        self.sound.stop_all(3000)
        for player in self._show_players:
            player.stop(3000)
        self.statusBar().showMessage(tr('Fading every sound out…'), 4000)

    def _assign_cue(self, index: int, path: str) -> None:
        try:
            self.sound.cues[index].assign(path)
        except MediaProblem as problem:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle(problem.title)
            box.setText(tr('<b>{0}</b><br>Cue F{1} was not changed.').format(problem.title, index + 1))
            box.setInformativeText(problem.message())
            box.setDetailedText(f"File:\n{path}")
            box.exec()
            return
        self._mark_preset_dirty()
        self._refresh_cue_pads()
        self.statusBar().showMessage(
            f"F{index + 1}: {os.path.basename(path)}", 5000)

    def _fire_cue(self, index: int) -> None:
        """Play, or pause if it is already running."""
        cue = self.sound.cues[index]
        if not cue.path:
            self.statusBar().showMessage(
                tr('F{0} is empty — drop a sound file on it first.').format(index + 1), 5000)
            return
        cue.toggle()
        self._refresh_cue_pads()
        self.statusBar().showMessage(
            f"F{index + 1} {'playing' if cue.is_playing() else 'paused'}: {cue.label()}", 4000)

    def _stop_cue(self, index: int) -> None:
        cue = self.sound.cues[index]
        if not cue.path:
            return
        cue.stop()
        self._refresh_cue_pads()
        self.statusBar().showMessage(tr('F{0} stopped: {1}').format(index + 1, cue.label()), 4000)

    def _clear_cue(self, index: int) -> None:
        self.sound.cues[index].clear()
        self._mark_preset_dirty()
        self._refresh_cue_pads()

    @Slot()
    def _stop_all_sound(self) -> None:
        self.sound.stop_all()
        for player in self._show_players:
            player.stop()
        self.statusBar().showMessage(tr('All sound cues fading out.'), 4000)

    def _on_cue_failed(self, index: int, message: str) -> None:
        cue = self.sound.cues[index]
        name = cue.label() or tr("cue F{0}").format(index + 1)
        cue.clear()
        self._refresh_cue_pads()
        QMessageBox.warning(
            self, tr('Sound will not play'),
            tr('<b>{0}</b> could not be played.<br><br>The audio backend said: {1}<br><br>Convert it to MP3 or WAV and assign it again.').format(name, message),
        )

    # ------------------------------------------------------- keyboard ------ #

    def _tick_clock(self) -> None:
        self.clock.setText(QTime.currentTime().toString("HH:mm:ss"))

    # ------------------------------------------------------- transitions --- #

    def fade_ms(self) -> int:
        """Current transition length; 0 means hard cut."""
        value = self.fade_combo.currentData()
        return int(value) if value is not None else 0

    def fade_style(self) -> str:
        return self.style_combo.currentData() or TRANSITION_CROSSFADE

    def _load_fade_setting(self) -> None:
        stored = self.settings.value("playback/fade_ms", DEFAULT_FADE_MS)
        try:
            stored = int(stored)
        except (TypeError, ValueError):
            stored = DEFAULT_FADE_MS
        index = self.fade_combo.findData(stored)
        self.fade_combo.blockSignals(True)
        self.fade_combo.setCurrentIndex(index if index >= 0 else
                                        self.fade_combo.findData(DEFAULT_FADE_MS))
        self.fade_combo.blockSignals(False)

        style = self.settings.value("playback/fade_style", TRANSITION_CROSSFADE)
        index = self.style_combo.findData(style)
        self.style_combo.blockSignals(True)
        self.style_combo.setCurrentIndex(max(0, index))
        self.style_combo.blockSignals(False)

    @Slot()
    def _on_fade_changed(self) -> None:
        milliseconds = self.fade_ms()
        self.settings.setValue("playback/fade_ms", milliseconds)
        self.settings.setValue("playback/fade_style", self.fade_style())
        if milliseconds == 0:
            self.statusBar().showMessage(tr('Transitions off — pictures change instantly.'), 5000)
        else:
            name = "crossfade" if self.fade_style() == TRANSITION_CROSSFADE else "fade through black"
            self.statusBar().showMessage(tr('Transition: {0} over {1} ms.').format(name, milliseconds), 5000)

    def set_active_role(self, role: str) -> None:
        """Choose which card the keyboard shortcuts drive."""
        self.active_role = role
        for name, card in self.cards.items():
            card.set_active(name == role)

    def _active_card(self) -> OutputCard:
        return self.cards[self.active_role]

    def _install_shortcuts(self) -> None:
        """
        Live-operation keys. During a show the mouse is slow and the operator is
        often looking at the stage, not the screen.
        """
        def clicker_or(name: str, fallback=None):
            # While slides are on screen these keys turn slides, the way a
            # clicker expects; otherwise they keep their stage meaning.
            return lambda: self._clicker_key(name, fallback)

        bindings = (
            ("1", lambda: self.set_active_role(ROLE_MAIN)),
            ("2", lambda: self.set_active_role(ROLE_SIDES)),
            ("3", lambda: self.set_active_role(ROLE_TOP)),
            ("Space", clicker_or("Space", self._toggle_active_playback)),
            ("Right", clicker_or("Right", lambda: self._active_card().playlist.step(1))),
            ("Left", clicker_or("Left", lambda: self._active_card().playlist.step(-1))),
            ("B", clicker_or("B", self._blackout_all)),
            ("Ctrl+O", self._apply_routing),
            ("Ctrl+Space", self._stop_all_sound),
            ("Ctrl+Right", lambda: self.text_slides.step(1)),
            ("Ctrl+Left", lambda: self.text_slides.step(-1)),
            ("Ctrl+H", self._hide_slide),
            # What a wireless presenter clicker sends: slides when a
            # presentation is on screen, the running order otherwise.
            ("PgDown", clicker_or("PgDown")),
            ("PgUp", clicker_or("PgUp")),
        )
        bindings += tuple(
            (f"F{slot + 1}", clicker_or(f"F{slot + 1}", lambda i=slot: self._fire_cue(i)))
            for slot in range(SOUND_SLOTS)
        )
        bindings += tuple(
            (f"Shift+F{slot + 1}", clicker_or(f"Shift+F{slot + 1}", lambda i=slot: self._stop_cue(i)))
            for slot in range(SOUND_SLOTS)
        )

        # Keys that drive the stage screens step aside on the DJ tab, where Space
        # and the arrows would otherwise pause a background mid-mix.
        self._stage_shortcuts: List[QShortcut] = []
        for key, handler in bindings:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(handler)
            if key in ("1", "2", "3", "Space", "Left", "Right"):
                self._stage_shortcuts.append(shortcut)

        # Other keys clickers send, live only while slides are on screen.
        for name in ("Down", "Up", "Return", "Enter", "Backspace", "N", "P", ".", "Esc"):
            shortcut = QShortcut(QKeySequence(name), self)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(lambda n=name: self._clicker_key(n))
            shortcut.setEnabled(False)
            self._slide_shortcuts.append(shortcut)
        self._install_learned_keys()
        BaseOutputWindow.key_router = self._route_output_key
        # PREVIEW -> TAKE
        self._take_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        self._take_shortcut.setContext(Qt.ApplicationShortcut)
        self._take_shortcut.activated.connect(self._take)
        self._cancel_shortcut = QShortcut(QKeySequence("Esc"), self)
        self._cancel_shortcut.setContext(Qt.ApplicationShortcut)
        self._cancel_shortcut.activated.connect(self._cancel_take)
        self._take_shortcut.setEnabled(False)
        self._cancel_shortcut.setEnabled(False)
        undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        undo.setContext(Qt.ApplicationShortcut)
        undo.activated.connect(self._undo)

    # ----------------------------------------------------------- clicker --- #

    def _learned(self) -> Dict[str, dict]:
        try:
            data = json.loads(self.settings.value("clicker/learned", "") or "{}")
            return {k: v for k, v in data.items() if isinstance(v, dict) and v.get("name")}
        except (ValueError, TypeError, AttributeError):
            return {}

    def _slide_action_for(self, name: str) -> Optional[str]:
        for action, info in self._learned().items():
            if info.get("name") == name:
                return action
        if name in pres_mod.NEXT_KEYS:
            return "next"
        if name in pres_mod.BACK_KEYS:
            return "back"
        if name in pres_mod.BLACK_KEYS:
            return "black"
        if name in ("F5", "Shift+F5"):
            return "start"              # the clicker's "start slideshow" button
        if name == "Esc":
            return "end"
        return None

    def _clicker_key(self, name: str, fallback=None, source: str = "") -> bool:
        """
        One key from the keyboard or a clicker. Slides get it while they are on
        screen; otherwise the clicker's forward / back walk the running order,
        and every other key does what it always did.
        """
        action = self._slide_action_for(name)
        if self._ready_check_open():
            # the operator is testing the clicker: note it, move nothing
            self.presentation_tab.show_key(name, tr('test ✓'), source)
            return True
        if self.presenter.live and action:
            self._do_slide(action, name, source)
            return True
        learned = any(info.get("name") == name for info in self._learned().values())
        if action in ("next", "back") and (name in ("PgDown", "PgUp") or learned):
            self.presentation_tab.show_key(name, tr('running order {0}').format(action), source)
            (self.show_next if action == "next" else self.show_back)()
            return True
        if fallback is not None:
            fallback()
            return True
        return False

    def _do_slide(self, action: str, name: str, source: str) -> None:
        presenter = self.presenter
        if action == "next":
            presenter.next()
        elif action == "back":
            presenter.back()
        elif action == "black":
            presenter.toggle_black()
        elif action == "start":
            if presenter.black:
                presenter.toggle_black()
        elif action == "end":
            presenter.end()
        labels = {"next": "next slide", "back": "previous slide", "black": "black",
                  "start": "show", "end": "end presentation"}
        self.presentation_tab.show_key(name, labels.get(action, action), source)

    def _route_output_key(self, event) -> bool:
        """Keys pressed while a stage window has focus (see BaseOutputWindow.key_router)."""
        name = QKeySequence(event.key()).toString()
        if event.modifiers() & Qt.ShiftModifier and name.startswith("F"):
            name = "Shift+" + name
        return self._clicker_key(name, None, "stage screen had focus")

    def _install_learned_keys(self) -> None:
        for shortcut in self._learned_shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._learned_shortcuts = []
        taken = {QKeySequence(s.key()).toString() for s in self.findChildren(QShortcut)
                 if s.isEnabled() or s in self._slide_shortcuts}
        for info in self._learned().values():
            name = info["name"]
            if name in taken or not info.get("key"):
                continue                   # an ordinary key: already routed above
            shortcut = QShortcut(QKeySequence(int(info["key"])), self)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(lambda n=name: self._clicker_key(n))
            self._learned_shortcuts.append(shortcut)

    def _clicker_global(self) -> bool:
        return str(self.settings.value("clicker/global", "true")).lower() == "true"

    def _on_clicker_global(self, on: bool) -> None:
        self.settings.setValue("clicker/global", "true" if on else "false")
        self._update_hotkeys()

    def _update_hotkeys(self) -> None:
        want = self.presenter.live and self._clicker_global()
        if want and not self._hotkeys:
            self._register_hotkeys()
        elif not want and self._hotkeys:
            self._unregister_hotkeys()

    def _register_hotkeys(self) -> None:
        """
        While slides are on screen, the clicker's keys reach this app even when
        another program has focus (Windows RegisterHotKey). Released the moment
        the presentation ends.
        """
        if sys.platform != "win32":
            return
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.RegisterHotKey.restype = wintypes.BOOL
        keys = dict(VK_BY_NAME)
        for info in self._learned().values():
            if info.get("vk"):
                keys.setdefault(info["name"], int(info["vk"]))
        hwnd = int(self.winId())
        refused = []
        for number, (name, vk) in enumerate(keys.items()):
            hotkey_id = 0xB100 + number
            if user32.RegisterHotKey(hwnd, hotkey_id, 0x4000, vk):      # MOD_NOREPEAT
                self._hotkeys[hotkey_id] = name
            else:
                refused.append(name)
        if refused:
            self.presentation_tab.show_status(
                "Another program already uses " + ", ".join(refused)
                + tr(' - the clicker works while this window is in front.'), CLR_WARN)

    def _unregister_hotkeys(self) -> None:
        if sys.platform == "win32":
            user32 = ctypes.WinDLL("user32")
            hwnd = int(self.winId())
            for hotkey_id in list(self._hotkeys):
                user32.UnregisterHotKey(ctypes.c_void_p(hwnd), hotkey_id)
        self._hotkeys = {}

    def nativeEvent(self, event_type, message):  # noqa: N802
        if self._hotkeys:
            try:
                if bytes(event_type) == b"windows_generic_MSG":
                    from ctypes import wintypes
                    msg = wintypes.MSG.from_address(int(message))
                    name = self._hotkeys.get(int(msg.wParam)) if msg.message == WM_HOTKEY else None
                    if name:
                        QTimer.singleShot(0, lambda n=name: self._clicker_key(n, None, "from any program"))
                        return True, 0
            except (TypeError, ValueError, OSError):
                pass
        return super().nativeEvent(event_type, message)

    @Slot()
    def _learn_clicker(self) -> None:
        # The clicker's keys must reach the dialog, not the shortcuts they would trigger.
        shortcuts = [s for s in self.findChildren(QShortcut) if s.isEnabled()]
        for shortcut in shortcuts:
            shortcut.setEnabled(False)
        had_hotkeys = bool(self._hotkeys)
        self._unregister_hotkeys()
        dialog = pres_mod.LearnDialog(THEME, self)
        accepted = dialog.exec() == QDialog.Accepted
        for shortcut in shortcuts:
            shortcut.setEnabled(True)
        if accepted and dialog.learned:
            self.settings.setValue("clicker/learned", json.dumps(dialog.learned))
            self._install_learned_keys()
            names = ", ".join(f"{k}: {v['name']}" for k, v in dialog.learned.items())
            self.presentation_tab.show_status(tr('Clicker learned - {0}').format(names), CLR_OK)
        if had_hotkeys:
            self._update_hotkeys()

    # ----------------------------------------------------- presentations --- #

    def _build_presentation_tab(self) -> QWidget:
        tab = pres_mod.PresentationTab(self.presenter, Icons, THEME,
                                       {role: ROLE_LABELS[role] for role in STAGE_ROLES},
                                       touch=self.touch_enabled())
        self.presentation_tab = tab
        tab.set_recent(self._recent_decks())
        tab.openedPath.connect(self._remember_deck)
        tab.learnRequested.connect(self._learn_clicker)
        tab.guestRequested.connect(self._open_guest_dialog)
        tab.laptopRequested.connect(self._open_share_dialog)
        tab.global_check.setChecked(self._clicker_global())
        tab.globalToggled.connect(self._on_clicker_global)
        tab.powerpointToggled.connect(
            lambda on: self.settings.setValue("slides/powerpoint", "true" if on else "false"))
        tab.limit_spin.setValue(int(self.settings.value("slides/limit", 0) or 0))
        tab.countdown_combo.setCurrentIndex(max(0, tab.countdown_combo.findData(
            str(self.settings.value("slides/countdown", "") or ""))))
        tab.limitChanged.connect(lambda minutes: self.settings.setValue("slides/limit", minutes))
        tab.countdownTargetChanged.connect(lambda role: self.settings.setValue("slides/countdown", role))
        tab.countdown.connect(self._on_countdown)
        return tab

    @Slot(str, str, str)
    def _on_countdown(self, role: str, text: str, colour: str) -> None:
        window = self._show_output(role) if role in STAGE_ROLES else None
        if window is not None:
            window.set_corner_text(text, colour)

    def _recent_decks(self) -> List[str]:
        stored = self.settings.value("slides/recent", [])
        if isinstance(stored, str):
            stored = [stored] if stored else []
        return [p for p in (stored or []) if os.path.exists(p)]

    def _remember_deck(self, path: str) -> None:
        recent = [path] + [p for p in self._recent_decks() if os.path.normcase(p) != os.path.normcase(path)]
        self.settings.setValue("slides/recent", recent[:8])
        self.presentation_tab.set_recent(recent[:8])

    @Slot(str)
    def _on_presenter_note(self, text: str) -> None:
        self.statusBar().showMessage(text, 6000)
        self.presentation_tab.show_status(text, CLR_WARN)

    @Slot()
    def _on_presenter_changed(self) -> None:
        if hasattr(self, "_cancel_shortcut"):
            self._sync_take_keys()
        live = self.presenter.live
        for shortcut in self._slide_shortcuts:
            shortcut.setEnabled(live)
        self._update_hotkeys()
        if live != self._was_live:
            self._was_live = live
            deck = self.presenter.deck
            self.statusBar().showMessage(
                (tr('Slides on {0}: {1}').format(ROLE_LABELS.get(self.presenter.role), deck.name) if live and deck
                 else tr('Presentation ended - background back on screen.')), 6000)

    def _remote_slide_action(self, action: str, data: dict):
        presenter = self.presenter
        count = presenter.count()
        if not count:
            return False, tr('No presentation is open.')
        if action in ("slide_next", "slide_back") and presenter.playing_in_powerpoint():
            # PowerPoint plays the next animation or slide; the phone sees the result on its next poll
            (presenter.next if action == "slide_next" else presenter.back)()
            self.presentation_tab.show_key("phone", tr('next') if action == "slide_next" else tr('back'))
            return True, "Next." if action == "slide_next" else "Back."
        if action == "slide_next":
            moved = presenter.next()
            self.presentation_tab.show_key("phone", tr('next slide'))
            return (True, f"{presenter.index + 1} / {count}") if moved else (False, "Last slide.")
        if action == "slide_back":
            moved = presenter.back()
            self.presentation_tab.show_key("phone", tr('previous slide'))
            return (True, f"{presenter.index + 1} / {count}") if moved else (False, tr("First slide."))
        if action == "slide_goto":
            try:
                presenter.goto(int(data.get("index", 0)))
            except (TypeError, ValueError):
                return False, tr('No such slide.')
            return True, f"{presenter.index + 1} / {count}"
        if action == "slide_black":
            if not presenter.live:
                return False, tr('The slides are not on screen.')
            presenter.toggle_black()
            return True, "Black." if presenter.black else "Back on screen."
        if action == "slide_live":
            if data.get("on", True):
                presenter.go_live()
                return True, tr('Slides on {0}.').format(ROLE_LABELS.get(presenter.role))
            presenter.end()
            return True, tr('Presentation ended.')
        return False, tr('Unknown action.')

    def _screen_state(self, role: str):
        """(closed | black | live | rehearsal, whether it moves by itself, a number that changes with it)."""
        window = self._show_output(role)
        if window is None:
            return "closed", False, "closed"
        presenter = self.presenter
        if role == ROLE_MAIN and self._share_on(window):
            live, moving, version = True, True, "laptop"
        elif presenter.live and presenter.role == role and presenter.playing_in_powerpoint():
            live, moving, version = not presenter.black, False, f"ppt-{presenter.index}-{presenter.black}"
        else:
            live, moving, version = window.has_picture(), window.is_moving(), str(window.picture_version)
        if self._rehearsal is not None:
            return "rehearsal", moving, version
        return ("live" if live else "black"), moving, version

    def _remote_screen_image(self, role: str) -> Optional[bytes]:
        """A small JPEG of what a stage screen shows, for the phone's multiview."""
        if role not in STAGE_ROLES:
            return None
        window = self._show_output(role)
        if window is None:
            return None
        state, moving, version = self._screen_state(role)
        cache = self.__dict__.setdefault("_screen_jpegs", {})
        if not moving and cache.get(role, (None, None))[0] == version:
            return cache[role][1]
        presenter = self.presenter
        if version == "laptop":
            buffer_data = QByteArray()
            buffer = QBuffer(buffer_data)
            buffer.open(QIODevice.WriteOnly)
            self.share_receiver.snapshot().scaledToWidth(480, Qt.SmoothTransformation).save(buffer, "JPG", 72)
            data = bytes(buffer_data.data())
        elif version.startswith("ppt-") and presenter.deck is not None and not presenter.black:
            data = presenter.deck.jpeg(presenter.index, 480)
        else:
            stage = self._stage_size(role)
            width = 640 if stage.width() > stage.height() * 3 else 480
            height = max(12, int(width * stage.height() / max(1, stage.width())))
            buffer_data = QByteArray()
            buffer = QBuffer(buffer_data)
            buffer.open(QIODevice.WriteOnly)
            window.preview(QSize(width, height)).save(buffer, "JPG", 72)
            data = bytes(buffer_data.data())
        cache[role] = (version, data)
        return data

    def _remote_slide_image(self, token: str, index: int) -> Optional[bytes]:
        deck = self.presenter.deck
        if deck is None or deck.token != token:
            return None
        return deck.jpeg(index)

    @Slot(int)
    def _on_tab_changed(self, index: int) -> None:
        on_dj = self.tabs.widget(index) is self.dj_page
        for shortcut in self._stage_shortcuts:
            shortcut.setEnabled(not on_dj)
        # Presets describe the stage screens; the DJ desk wants the height.
        # The header, with BLACKOUT, stays.
        self.preset_bar.setVisible(self.tabs.widget(index) in (self.tabs.widget(0), self.library))
        if self.tabs.widget(index) is self.screens_page:
            self._refresh_backups()
        if on_dj and self.dj_panel is None:
            self._build_dj_panel()
        self._refresh_show_strip()

    def _build_dj_panel(self) -> None:
        try:
            import dj
        except ImportError as exc:
            note = QLabel(
                tr('The DJ desk needs numpy, which is not installed.\n\nInstall it with:   python -m pip install numpy\n\n({0})').format(exc)
            )
            note.setAlignment(Qt.AlignCenter)
            note.setObjectName("cardHint")
            self.dj_page.layout().addWidget(note)
            self.dj_panel = False
            return
        self.dj_panel = dj.DJPanel(self.settings, self.settings.value("sound/device", "") or None,
                                   touch=self.touch_enabled())
        self.dj_page.layout().addWidget(self.dj_panel)

    @Slot()
    def _toggle_active_playback(self) -> None:
        window = getattr(self, self.OUTPUT_ATTRS[self.active_role], None)
        if window is None:
            return
        player = window.engine.player
        playing = getattr(QMediaPlayer, "PlaybackState", None)
        state_playing = getattr(playing, "PlayingState", None) if playing else None
        if player.playbackState() == state_playing:
            window.engine.pause()
        else:
            window.engine.play()

    def _build_screens_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(11)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 16)
        card_layout.setSpacing(10)

        heading = QLabel(tr('Display routing'))
        heading.setObjectName("sectionTitle")
        card_layout.addWidget(heading)

        note = QLabel(
            tr("Assign each role to a monitor. Use “Custom size” when an LED processor's mapped canvas differs from the resolution Windows reports — the ceiling strip is driven at {0}×{1}.").format(DEFAULT_TOP_WIDTH, DEFAULT_TOP_HEIGHT)
        )
        note.setObjectName("cardHint")
        note.setWordWrap(True)
        card_layout.addWidget(note)

        for role in (ROLE_CONTROL, ROLE_MAIN, ROLE_SIDES, ROLE_TOP):
            row = RoutingRow(role, allow_custom=(role != ROLE_CONTROL))
            row.onTopChanged.connect(self._on_output_on_top_changed)
            self.routing_rows[role] = row
            card_layout.addWidget(row)
        # The Main Stage is the screen a presentation or browser gets shown on,
        # so it must not float above everything else.
        self.routing_rows[ROLE_MAIN].on_top_check.setChecked(False)

        buttons = QHBoxLayout()
        buttons.setSpacing(7)
        apply_btn = QPushButton(tr('  Apply routing / Open outputs'))
        apply_btn.setObjectName("primary")
        apply_btn.setIcon(Icons.get("monitor", "#0b0e13", 16))
        apply_btn.clicked.connect(self._apply_routing)
        buttons.addWidget(apply_btn)

        identify = QPushButton(tr('  Identify monitors'))
        identify.setIcon(Icons.get("target", CLR_TEXT, 16))
        identify.setToolTip(tr('Flash a big number on every monitor for 3 seconds'))
        identify.clicked.connect(self._identify_screens)
        buttons.addWidget(identify)

        redetect = QPushButton(tr('  Re-detect'))
        redetect.setIcon(Icons.get("refresh", CLR_TEXT, 16))
        redetect.clicked.connect(lambda: self._refresh_screen_combos())
        buttons.addWidget(redetect)

        use_reported = QPushButton(tr('  Copy reported size'))
        use_reported.setIcon(Icons.get("open", CLR_TEXT, 16))
        use_reported.setToolTip(tr('Fill the W/H boxes with what Windows reports for each monitor'))
        use_reported.clicked.connect(self._copy_reported_sizes)
        buttons.addWidget(use_reported)

        close_outputs = desk_mod.HoldButton(tr('  Close outputs'), THEME)
        close_outputs.setIcon(Icons.get("close", CLR_TEXT, 16))
        close_outputs.setToolTip(tr('Close every stage output window (the app keeps running) - hold to confirm'))
        close_outputs.clicked.connect(self._close_all_outputs)
        buttons.addWidget(close_outputs)

        buttons.addSpacing(14)
        fade_label = QLabel(tr('Transition'))
        fade_label.setObjectName("cardHint")
        buttons.addWidget(fade_label)
        self.fade_combo = QComboBox()
        for caption, milliseconds in FADE_PRESETS:
            self.fade_combo.addItem(tr(caption), milliseconds)
        self.fade_combo.setToolTip(
            tr('How long a change of picture takes.\nApplies to every screen, to playlist steps and to blackouts.')
        )
        self.fade_combo.currentIndexChanged.connect(self._on_fade_changed)
        buttons.addWidget(self.fade_combo)

        self.style_combo = QComboBox()
        for caption, value in TRANSITION_STYLES:
            self.style_combo.addItem(tr(caption), value)
        self.style_combo.setToolTip(
            tr('Crossfade dissolves the old picture into the new one - the hall never goes dark.\nThrough black fades out, swaps, then fades in.')
        )
        self.style_combo.currentIndexChanged.connect(self._on_fade_changed)
        buttons.addWidget(self.style_combo)

        buttons.addStretch(1)
        card_layout.addLayout(buttons)
        layout.addWidget(card)
        layout.addWidget(self._build_autostart_card())
        layout.addWidget(self._build_touch_card())
        layout.addWidget(self._build_backups_card())

        tips = QFrame()
        tips.setObjectName("card")
        tips_layout = QVBoxLayout(tips)
        tips_layout.setContentsMargins(16, 14, 16, 16)
        tips_layout.setSpacing(8)
        tip_title = QLabel(tr('Running a show'))
        tip_title.setObjectName("sectionTitle")
        tips_layout.addWidget(tip_title)
        tip_text = QLabel(
            tr("Prepare the event by dropping several backgrounds onto a card — they land in that screen's playlist.\nDuring the show, click a playlist entry, or use the ‹ › arrows, to switch instantly.\nRepeat is on by default, so videos loop; switch it off per screen to play once.\n“On top” is off for the Main Stage, so a PowerPoint deck or a browser can be shown over its background — the side and ceiling screens stay above everything.\nSave everything as a preset, and the next assembly is one click away.\nStage windows stay out of the taskbar, so only this dashboard appears there.")
        )
        lines = tip_text.text().split("\n")
        tip_text.setText("\n".join(lines[:len(lines) // 2]))
        tip_text.setObjectName("cardHint")
        tip_text.setWordWrap(True)
        tip_more = QLabel("\n".join(lines[len(lines) // 2:]))
        tip_more.setObjectName("cardHint")
        tip_more.setWordWrap(True)
        columns = QHBoxLayout()
        columns.setSpacing(28)
        columns.addWidget(tip_text, 1, Qt.AlignTop)
        columns.addWidget(tip_more, 1, Qt.AlignTop)
        tips_layout.addLayout(columns)
        layout.addWidget(tips)

        layout.addStretch(1)
        return page

    def _build_touch_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        box = QHBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(10)
        heading = QLabel(tr('Touch screen'))
        heading.setObjectName("sectionTitle")
        box.addWidget(heading)
        self.touch_combo = QComboBox()
        for caption, value in TOUCH_MODES:
            self.touch_combo.addItem(tr(caption), value)
        wanted = self.settings.value("ui/touch", "auto")
        self.touch_combo.setCurrentIndex(max(0, self.touch_combo.findData(wanted)))
        self.touch_combo.setToolTip(
            tr('Larger buttons, sliders and lists for fingers, and lists that scroll with a flick.\nAutomatic switches them on when Windows reports a touch screen.'))
        self.touch_combo.currentIndexChanged.connect(self._on_touch_changed)
        box.addWidget(self.touch_combo)
        self.touch_note = QLabel()
        self.touch_note.setObjectName("cardHint")
        box.addWidget(self.touch_note, 1)
        self._add_language_picker(box)
        return card

    def touch_enabled(self) -> bool:
        mode = self.settings.value("ui/touch", "auto")
        if mode == "on":
            return True
        if mode == "off":
            return False
        return touch_screen_present()

    def _apply_touch_mode(self) -> None:
        touch = self.touch_enabled()
        app = QApplication.instance()
        sheet = STYLESHEET + language_stylesheet() + (touch_stylesheet() if touch else "")
        if app.styleSheet() != sheet:
            app.setStyleSheet(sheet)
        # A finger flicks a list rather than rubber-banding a selection; the
        # mouse still drags items as before. Only item lists: a scroller over
        # a panel of sliders would steal every drag from the sliders.
        for area in self.findChildren(QAbstractItemView):
            if touch:
                QScroller.grabGesture(area.viewport(), QScroller.TouchGesture)
            else:
                QScroller.ungrabGesture(area.viewport())
        detected = tr("a touch screen is connected") if touch_screen_present() else tr("no touch screen found")
        self.touch_note.setText(
            (tr("On — {0}.") if touch else tr("Off — {0}.")).format(detected)
            + (tr("  The DJ tab picks up the change the next time the app starts.")
               if self.dj_panel else ""))

    @Slot()
    def _on_touch_changed(self) -> None:
        self.settings.setValue("ui/touch", self.touch_combo.currentData())
        self._apply_touch_mode()

    def _build_autostart_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 14, 16, 16)
        box.setSpacing(9)

        heading = QLabel(tr('Start with Windows'))
        heading.setObjectName("sectionTitle")
        box.addWidget(heading)

        note = QLabel(
            tr('Open the app and put a preset on the screens automatically when this PC starts. The delay gives LED processors and video walls time to come up first — without it the outputs can land on the wrong monitors.')
        )
        note.setObjectName("cardHint")
        note.setWordWrap(True)
        box.addWidget(note)

        row = QHBoxLayout()
        row.setSpacing(9)

        self.autostart_check = QCheckBox(tr('Start automatically'))
        self.autostart_check.toggled.connect(self._on_autostart_toggled)
        row.addWidget(self.autostart_check)

        row.addWidget(QLabel(tr('Preset')))
        self.autostart_preset = QComboBox()
        self.autostart_preset.setMinimumWidth(200)
        self.autostart_preset.currentIndexChanged.connect(self._refresh_autostart_entry)
        row.addWidget(self.autostart_preset)

        row.addWidget(QLabel(tr('Wait')))
        self.autostart_delay = QSpinBox()
        self.autostart_delay.setRange(0, 600)
        self.autostart_delay.setValue(DEFAULT_STARTUP_DELAY)
        self.autostart_delay.setSuffix(" s")
        self.autostart_delay.setToolTip(tr('Seconds to wait for the monitors before applying the preset'))
        self.autostart_delay.valueChanged.connect(self._refresh_autostart_entry)
        row.addWidget(self.autostart_delay)

        self.autostart_status = QLabel()
        self.autostart_status.setObjectName("cardHint")
        self.autostart_status.setWordWrap(True)
        row.addSpacing(12)
        row.addWidget(self.autostart_status, 1)
        box.addLayout(row)

        if not Autostart.available():
            self.autostart_check.setEnabled(False)
            self.autostart_preset.setEnabled(False)
            self.autostart_delay.setEnabled(False)
        return card

    def _load_autostart_state(self) -> None:
        """Reflect whatever is registered in the Run key, without changing it."""
        preset, delay = Autostart.parse(Autostart.read())
        self.autostart_delay.blockSignals(True)
        self.autostart_delay.setValue(delay)
        self.autostart_delay.blockSignals(False)

        if preset:
            index = self.autostart_preset.findText(preset)
            if index >= 0:
                self.autostart_preset.blockSignals(True)
                self.autostart_preset.setCurrentIndex(index)
                self.autostart_preset.blockSignals(False)

        self.autostart_check.blockSignals(True)
        self.autostart_check.setChecked(preset is not None)
        self.autostart_check.blockSignals(False)
        self._describe_autostart()

    def _describe_autostart(self) -> None:
        if not Autostart.available():
            self.autostart_status.setText(tr('Autostart is only available on Windows.'))
            return
        if not self.autostart_check.isChecked():
            self.autostart_status.setText(tr('Currently off — nothing runs at login.'))
            return
        preset = self.autostart_preset.currentText()
        delay = self.autostart_delay.value()
        self.autostart_status.setText(
            tr('On: at login the app opens and applies “{0}” after {1} seconds.').format(preset, delay)
        )
        self.autostart_status.setStyleSheet(f"color: {CLR_OK};")

    @Slot(bool)
    def _on_autostart_toggled(self, enabled: bool) -> None:
        if enabled and not self.autostart_preset.isEnabled():
            # No presets saved yet, so there would be nothing to apply.
            QMessageBox.information(
                self, tr('No preset'),
                tr('Save a preset first — autostart needs to know what to put on the screens.'),
            )
            self.autostart_check.setChecked(False)
            return
        error = self._refresh_autostart_entry()
        if error:
            QMessageBox.critical(self, tr('Could not change autostart'), error)
            self.autostart_check.blockSignals(True)
            self.autostart_check.setChecked(not enabled)
            self.autostart_check.blockSignals(False)
        self._describe_autostart()

    @Slot()
    def _refresh_autostart_entry(self) -> Optional[str]:
        """Write (or remove) the Run entry so it matches the controls."""
        if not Autostart.available():
            return None
        if self.autostart_check.isChecked():
            preset = self.autostart_preset.currentText()
            if not preset or not self.autostart_preset.isEnabled():
                return None
            error = Autostart.enable(preset, self.autostart_delay.value())
        else:
            error = Autostart.disable()
        if not error:
            self._describe_autostart()
        return error

    # -- autostart run ------------------------------------------------------ #

    def run_autostart(self, preset: str, delay: int) -> None:
        """
        Apply `preset` once the monitors have had `delay` seconds to appear.

        Called only when the app was launched with --preset, i.e. by the Run
        registry entry at login.
        """
        remaining = {"seconds": max(0, delay)}
        ticker = QTimer(self)

        def tick() -> None:
            if remaining["seconds"] <= 0:
                ticker.stop()
                self._fire_autostart(preset)
                return
            self.statusBar().showMessage(
                tr('Autostart: applying “{0}” in {1}s (waiting for the monitors)…').format(preset, remaining['seconds'])
            )
            remaining["seconds"] -= 1

        ticker.timeout.connect(tick)
        ticker.start(1000)
        tick()

    def _fire_autostart(self, preset: str) -> None:
        self._refresh_screen_combos()  # pick up monitors that appeared while waiting
        payload = self.presets.get(preset)
        if not payload:
            self.statusBar().showMessage(
                tr('Autostart: preset “{0}” not found — nothing applied.').format(preset), 0
            )
            return
        self._apply_preset(payload)
        self.statusBar().showMessage(tr('Autostart: “{0}” applied.').format(preset), 10000)

    def _wire_card(self, card: OutputCard, role: str) -> None:
        """Connect a card's signals to whichever output window that role owns."""

        def output():
            return getattr(self, self.OUTPUT_ATTRS[role], None)

        def on_load(path: str) -> None:
            if output() is None:
                put_on(path)          # says why it cannot, at once
                return
            self._change_stage(f"{ROLE_LABELS[role]}  ←  {os.path.basename(path)}",
                               lambda: put_on(path), self._thumb_for_path(path))

        def put_on(path: str) -> None:
            window = output()
            if window is None:
                QMessageBox.warning(
                    self,
                    tr('Output not open'),
                    tr('“{0}” has no output window yet.\n\nOpen the “Screens & Setup” tab, pick a monitor for it, then press “OPEN OUTPUTS” and try again.').format(ROLE_LABELS[role]),
                )
                return
            try:
                window.set_scale_mode(card.current_scale_mode())
                window.engine.set_loop(card.is_repeating())
                window.present(path, self.fade_ms(), self.fade_style())
            except MediaProblem as problem:
                self._report_media_problem(role, path, problem)
                return
            except Exception as exc:  # never let one bad file take the app down
                self._report_media_problem(
                    role, path,
                    MediaProblem(tr('Could not show this file'),
                                 f"{os.path.basename(path)}\n\n{type(exc).__name__}: {exc}"),
                )
                return
            card.show_loaded(path)
            self._mark_preset_dirty()
            self.statusBar().showMessage(f"{ROLE_LABELS[role]}: {os.path.basename(path)}", 6000)
            queued = card.playlist.paths()
            if path in queued and queued.index(path) + 1 < len(queued):
                warm_file(queued[queued.index(path) + 1])     # the next one is ready too

        card.loadRequested.connect(on_load)
        card.queueRequested.connect(
            lambda paths: self.statusBar().showMessage(
                tr('{0}: {1} item(s) added to the playlist').format(ROLE_LABELS[role], len(paths)), 5000
            )
        )
        card.scaleModeChanged.connect(lambda mode: output() and output().set_scale_mode(mode))
        for changed in (card.scaleModeChanged, card.repeatChanged, card.muteChanged,
                        card.queueRequested, card.volumeChanged):
            changed.connect(lambda *_a: self._mark_preset_dirty())
        card.playRequested.connect(lambda: output() and output().engine.play())
        card.pauseRequested.connect(lambda: output() and output().engine.pause())
        card.stopRequested.connect(lambda: output() and output().engine.stop())
        card.clearRequested.connect(lambda: self._record_change(
            tr('{0}  →  black').format(ROLE_LABELS[role]), lambda: output() and output().fade_clear(self.fade_ms())))
        card.volumeChanged.connect(lambda value: output() and output().engine.set_volume(value))
        card.muteChanged.connect(lambda muted: output() and output().engine.set_muted(muted))
        card.repeatChanged.connect(lambda on: output() and output().engine.set_loop(on))

    # -------------------------------------------------- problem reporting -- #

    def _report_media_problem(self, role: str, path: str, problem: MediaProblem) -> None:
        """One clear dialog instead of a frozen or blank screen."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(problem.title)
        box.setText(tr('<b>{0}</b><br>{1} was not changed.').format(problem.title, ROLE_LABELS[role]))
        box.setInformativeText(problem.message())
        box.setDetailedText(f"File:\n{path}")
        box.setStandardButtons(QMessageBox.Ok)
        box.exec()
        self.statusBar().showMessage(
            tr('{0}: {1} refused — {2}').format(ROLE_LABELS[role], os.path.basename(path), problem.title), 12000
        )

    def _on_engine_error(self, role: str, message: str) -> None:
        """
        Playback errors used to vanish silently: the signal was never connected,
        so an unplayable codec looked like the app hanging for no reason.
        """
        card = self.cards.get(role)
        name = os.path.basename(card.current_path()) if card and card.current_path() else "the clip"
        window = getattr(self, self.OUTPUT_ATTRS[role], None)
        if window is not None:
            window.clear_output()      # do not leave a frozen half-frame on stage
        if card is not None:
            card.reset_file()
        self._report_media_problem(
            role,
            card.current_path() if card else "",
            MediaProblem(
                tr('This video will not play on this PC'),
                tr('{0}\n\nThe video backend reported:\n{1}\n\nThe container opened, so this is almost certainly the codec inside it - H.265/HEVC, VP9 and AV1 are not supported here.').format(name, message),
                CONVERT_ADVICE,
            ),
        )

    # -------------------------------------------------------------- routing -- #

    @staticmethod
    def _screen_caption(index: int, screen: QScreen) -> str:
        geo = screen.geometry()
        primary = "  [primary]" if screen is QGuiApplication.primaryScreen() else ""
        return (f"#{index + 1}  {screen.name()}  —  {geo.width()}×{geo.height()} "
                f"@ ({geo.x()},{geo.y()}){primary}")

    @staticmethod
    def _screen_by_name(name: Optional[str]) -> Optional[QScreen]:
        """
        Resolve a stored screen name to a live QScreen.

        Combos store names rather than QScreen objects on purpose: if a monitor
        is unplugged, a stored object would become a dangling reference, whereas
        an unknown name simply resolves to None.
        """
        if not name:
            return None
        for screen in QGuiApplication.screens():
            if screen.name() == name:
                return screen
        return None

    def _screen_names(self) -> List[str]:
        return [screen.name() for screen in QGuiApplication.screens()]

    def _on_screens_changed(self) -> None:
        self._refresh_screen_combos()
        QTimer.singleShot(300, self._check_stage_screens)

    def _check_stage_screens(self) -> None:
        """
        An LED processor that restarts, or a cable that slips, takes its monitor
        away from Windows - and Windows pushes the stage window onto another
        screen, the desk's included. The window is hidden the moment its monitor
        goes (it keeps playing, unseen) and put back exactly where it belongs
        the moment the monitor returns. Nobody has to press anything.
        """
        if self._rehearsal is not None:
            return
        names = self._screen_names()
        for role in STAGE_ROLES:
            window = self._show_output(role)
            routed = self.routing_rows[role].screen_combo.currentData()
            if window is None or not routed:
                self._lost_screens.discard(role)
                continue
            if routed not in names:
                if role not in self._lost_screens:
                    self._lost_screens.add(role)
                    window.hide()
                    self.statusBar().showMessage(
                        tr('{0}: its monitor went away - the picture waits, and comes back with it.').format(ROLE_LABELS[role]),
                        20000)
                continue
            screen = self._screen_by_name(routed)
            if screen is None:
                continue
            if role in self._lost_screens:
                self._lost_screens.discard(role)
                window.show_with_geometry(screen, self._rect_for(role, screen))
                self.statusBar().showMessage(tr('{0} is back.').format(ROLE_LABELS[role]), 8000)
            elif window.isVisible() and not screen.geometry().contains(window.geometry().center()):
                window.show_with_geometry(screen, self._rect_for(role, screen))   # Windows moved it: back

    def _refresh_screen_combos(self, initial: bool = False) -> None:
        screens = QGuiApplication.screens()
        names = [screen.name() for screen in screens]
        previous = {role: row.screen_combo.currentData() for role, row in self.routing_rows.items()}

        for row in self.routing_rows.values():
            combo = row.screen_combo
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(tr('— None (disabled) —'), None)
            for index, screen in enumerate(screens):
                combo.addItem(self._screen_caption(index, screen), screen.name())
            combo.blockSignals(False)

        if initial:
            self._apply_default_assignment(screens)
        else:
            for role, row in self.routing_rows.items():
                wanted = previous.get(role)
                if wanted in names:
                    row.screen_combo.setCurrentIndex(names.index(wanted) + 1)
                elif wanted:
                    combo = row.screen_combo
                    combo.blockSignals(True)
                    combo.addItem(tr('— {0}  (not connected) —').format(wanted), wanted)
                    combo.setCurrentIndex(combo.count() - 1)
                    combo.blockSignals(False)

        self.statusBar().showMessage(tr('{0} monitor(s) detected.').format(len(screens)), 4000)

    def _apply_default_assignment(self, screens) -> None:
        """
        Sensible first guess - the operator can override every choice:

        * Control Panel -> the primary monitor (the operator's desk).
        * Top Screen    -> the most extremely wide monitor, pre-filled with the
          real LED canvas size rather than the resolution Windows reports.
        * Main Stage    -> the largest of the remaining monitors.
        * Side Screens  -> whatever is left.
        """
        primary = QGuiApplication.primaryScreen()
        names = [screen.name() for screen in screens]
        candidates = [screen for screen in screens if screen is not primary]

        def aspect(screen: QScreen) -> float:
            geo = screen.geometry()
            return geo.width() / geo.height() if geo.height() else 0.0

        def area(screen: QScreen) -> int:
            geo = screen.geometry()
            return geo.width() * geo.height()

        top_screen = None
        wide = [screen for screen in candidates if aspect(screen) >= self.WIDE_ASPECT_THRESHOLD]
        if wide:
            top_screen = max(wide, key=aspect)
            candidates.remove(top_screen)

        candidates.sort(key=area, reverse=True)
        chosen = {
            ROLE_CONTROL: primary,
            ROLE_MAIN: candidates[0] if len(candidates) > 0 else None,
            ROLE_SIDES: candidates[1] if len(candidates) > 1 else None,
            ROLE_TOP: top_screen,
        }

        for role, screen in chosen.items():
            row = self.routing_rows[role]
            name = screen.name() if screen is not None else None
            row.screen_combo.setCurrentIndex(names.index(name) + 1 if name in names else 0)
            if screen is not None and role != ROLE_CONTROL:
                geo = screen.geometry()
                row.set_size(geo.width(), geo.height())

        # The ceiling strip's mapped canvas, not what Windows reports.
        top_row = self.routing_rows[ROLE_TOP]
        top_row.set_size(DEFAULT_TOP_WIDTH, DEFAULT_TOP_HEIGHT)
        top_row.mode_combo.setCurrentIndex(1 if top_screen is not None else 0)
        self.top_card.size_spin.setValue(max(24, int(DEFAULT_TOP_HEIGHT * 0.72)))

    @Slot()
    def _copy_reported_sizes(self) -> None:
        for role in STAGE_ROLES:
            row = self.routing_rows[role]
            screen = self._screen_by_name(row.screen_combo.currentData())
            if screen is not None:
                geo = screen.geometry()
                row.set_size(geo.width(), geo.height())
        self.statusBar().showMessage(tr("Custom sizes filled from the monitors' reported resolutions."), 5000)

    def _rect_for(self, role: str, screen: QScreen) -> Optional[QRect]:
        """Absolute rectangle for an output, or None for plain fullscreen."""
        config = self.routing_rows[role].config()
        if not config.custom:
            return None
        origin = screen.geometry()
        return QRect(
            origin.x() + config.offset_x,
            origin.y() + config.offset_y,
            max(1, config.width),
            max(1, config.height),
        )

    @Slot()
    def _apply_routing(self) -> None:
        if self._rehearsal is not None:
            # the rehearsal screens follow; the stage windows are not touched
            self._push_top_settings()
            self._restore_media_to_outputs()
            self._update_output_status()
            return
        assignments = {
            role: self._screen_by_name(row.screen_combo.currentData())
            for role, row in self.routing_rows.items()
        }

        used = [screen for role, screen in assignments.items()
                if screen is not None and role != ROLE_CONTROL]
        if len(used) != len(set(used)):
            QMessageBox.information(
                self,
                tr('Duplicate monitors'),
                tr('Two or more outputs are assigned to the same monitor.\nThey will overlap — fine for testing, but check this before the show.'),
            )

        control_screen = assignments[ROLE_CONTROL]
        if control_screen is not None:
            self._move_self_to(control_screen)

        self._freshly_opened = set()   # filled by _ensure_output below

        specs = (
            (ROLE_MAIN, StandardOutputWindow, "Main Stage Output", self.main_card),
            (ROLE_SIDES, StandardOutputWindow, "Side Screens Output", self.sides_card),
            (ROLE_TOP, TopOutputWindow, "Top Screen Output", self.top_card),
        )
        for role, cls, title, card in specs:
            attr = self.OUTPUT_ATTRS[role]
            window = self._ensure_output(role, getattr(self, attr), assignments[role], cls, title, card)
            setattr(self, attr, window)

        if self.top_output is not None:
            self._push_top_settings()

        self._restore_media_to_outputs()
        self._update_output_status()

        self.raise_()
        self.activateWindow()

        active = [ROLE_LABELS[role] for role in STAGE_ROLES if assignments[role] is not None]
        self.statusBar().showMessage(
            tr('Outputs open: ') + (", ".join(active) if active else "none"), 8000
        )

    def _ensure_output(self, role: str, window, screen: Optional[QScreen], cls, title: str,
                       card: OutputCard):
        """Create, move or close one output window so it matches its assigned screen."""
        if screen is None:
            if window is not None:
                window.clear_output()
                window.force_close()
                window.deleteLater()
            return None

        if window is None:
            self._freshly_opened.add(role)   # nothing on it yet, so do not fade in
            window = cls(title)
            window.set_scale_mode(card.current_scale_mode())
            window.closedByUser.connect(
                lambda bound_role=role, name=title: self._on_output_closed(bound_role, name)
            )
            # Feed the card's position bar; these die with the window.
            player = window.engine.player
            player.positionChanged.connect(card.set_position)
            player.durationChanged.connect(card.set_duration)
            card.seekRequested.connect(player.setPosition)
            window.engine.errorOccurred.connect(
                lambda message, bound=role: self._on_engine_error(bound, message)
            )

        window.engine.set_loop(card.is_repeating())
        window.engine.set_volume(card.volume_slider.value())
        window.engine.set_muted(card.mute_btn.isChecked())
        window.set_always_on_top(self.routing_rows[role].on_top_check.isChecked())
        window.show_with_geometry(screen, self._rect_for(role, screen))
        return window

    def _restore_media_to_outputs(self) -> None:
        """
        Re-send whatever each card has loaded - after reopening a window, or
        when a preset changes every screen at once.

        A screen that was already showing something transitions into the new
        picture; one whose window has only just been created cuts straight in,
        because there is nothing to dissolve away from.
        """
        for role, card in self.cards.items():
            window = getattr(self, self.OUTPUT_ATTRS[role], None)
            path = card.current_path()
            if window is None or not path or not os.path.isfile(path):
                continue
            window.set_scale_mode(card.current_scale_mode())
            fade = 0 if role in self._freshly_opened else self.fade_ms()
            try:
                window.present(path, fade, self.fade_style())
            except MediaProblem as problem:
                self._report_media_problem(role, path, problem)
                card.reset_file()

    def _on_output_closed(self, role: str, title: str) -> None:
        """
        Forget a window the operator dismissed with Escape.

        Without this the panel would keep sending media to a hidden window -
        which looks exactly like a screen that has gone black.
        """
        window = getattr(self, self.OUTPUT_ATTRS[role], None)
        if window is not None:
            window.deleteLater()
        setattr(self, self.OUTPUT_ATTRS[role], None)
        self._update_output_status()
        self.statusBar().showMessage(
            tr('{0} closed with Escape — press OPEN OUTPUTS to bring it back.').format(title), 8000
        )

    def _move_self_to(self, screen: QScreen) -> None:
        """
        Put the dashboard on the operator's monitor - but only if it is not
        already there.

        Applying a preset used to drag the window to a fixed offset every time,
        un-maximising it and shoving it off to one side, which then had to be
        dragged back by hand before every show.
        """
        handle = self.windowHandle()
        if handle is not None and handle.screen() is screen:
            return
        was_maximised = self.isMaximized()
        if was_maximised:
            self.showNormal()
        geometry = screen.geometry()
        if handle is not None:
            handle.setScreen(screen)
        self.move(geometry.x() + 50, geometry.y() + 40)
        if was_maximised:
            self.showMaximized()

    @Slot(str, bool)
    def _on_output_on_top_changed(self, role: str, on_top: bool) -> None:
        """Apply a stacking change live, without reopening the whole routing."""
        window = getattr(self, self.OUTPUT_ATTRS.get(role, ""), None)
        if window is None:
            return
        window.set_always_on_top(on_top)
        self.raise_()
        self.activateWindow()
        self.statusBar().showMessage(
            tr('{0}: always-on-top {1}').format(ROLE_LABELS[role], 'ON' if on_top else 'OFF')
            + ("" if on_top else " — other windows can now cover this screen."),
            6000,
        )

    @Slot()
    def _close_all_outputs(self) -> None:
        if self._rehearsal is not None:
            self.statusBar().showMessage(tr('End the rehearsal first.'), 5000)
            return
        for window in self._outputs():
            window.clear_output()
            window.force_close()
            window.deleteLater()
        self.main_output = self.sides_output = self.top_output = None
        self._update_output_status()
        self.statusBar().showMessage(tr('All stage outputs closed.'), 5000)

    @Slot()
    def _blackout_all(self) -> None:
        if self._share_live:
            self._end_share(tr("The stage went to black."))
        def black() -> None:
            fade = self.fade_ms()
            for window in self._outputs():
                window.fade_clear(fade)
            if self.top_output is not None:
                self.top_output.stop_marquee()
            for card in self.cards.values():
                card.reset_file()
        self._record_change(tr('BLACKOUT  -  every screen to black'), black)
        self.statusBar().showMessage(tr('BLACKOUT — every stage screen cleared.  (Ctrl+Z puts it back)'), 6000)

    def _outputs(self):
        return [w for w in (self.main_output, self.sides_output, self.top_output) if w is not None]

    def _update_output_status(self) -> None:
        for role in STAGE_ROLES:
            is_open = getattr(self, self.OUTPUT_ATTRS[role], None) is not None
            if role in getattr(self, "cards", {}):
                self.cards[role].set_output_open(is_open)
        if hasattr(self, "cards"):
            self._refresh_multiview()

    @Slot()
    def _identify_screens(self) -> None:
        """Flash a large number on every monitor for ~3 seconds."""
        overlays = []
        for index, screen in enumerate(QGuiApplication.screens()):
            label = QLabel(f"{index + 1}\n{screen.name()}")
            label.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(
                "background-color: rgba(0,0,0,225); color: #5aa9f0;"
                "font-size: 120px; font-weight: bold;"
            )
            label.setGeometry(screen.geometry())
            label.show()
            handle = label.windowHandle()
            if handle is not None:
                handle.setScreen(screen)
            label.setGeometry(screen.geometry())
            overlays.append(label)

        def dismiss() -> None:
            for overlay in overlays:
                overlay.close()
                overlay.deleteLater()

        QTimer.singleShot(3000, dismiss)

    # ---------------------------------------------------------- top screen -- #

    @Slot(QColor)
    def _on_top_colour(self, colour: QColor) -> None:
        if self.top_output is None:
            QMessageBox.warning(self, tr('Output not open'), tr('The Top Screen output window is not open yet.'))
            return
        fade = self.fade_ms()
        self.top_output.transition(
            lambda: self.top_output.set_background_color(colour), fade, self.fade_style()
        )
        self.statusBar().showMessage(tr('Top Screen: solid background {0}').format(colour.name()), 5000)

    def _push_top_settings(self) -> None:
        """Send every marquee/background setting to a (possibly new) Top window."""
        top = self.top_output
        if top is None:
            return
        state = self.top_card.marquee_state()
        top.set_background_color(self.top_card.background_colour())
        top.set_marquee_family(state["family"])
        top.set_marquee_font_size(state["size"])
        top.set_marquee_color(QColor(state["colour"]))
        top.set_marquee_speed(state["speed"])
        top.set_marquee_text(state["text"])

    @Slot()
    def _start_marquee(self) -> None:
        if self.top_output is None:
            QMessageBox.warning(self, tr('Output not open'), tr('The Top Screen output window is not open yet.'))
            return
        if not self.top_card.text_edit.text().strip():
            QMessageBox.information(self, tr('No text'), tr('Type the marquee text first.'))
            return
        state = self.top_card.marquee_state()
        self.top_output.set_marquee_family(state["family"])
        self.top_output.set_marquee_font_size(state["size"])
        self.top_output.set_marquee_color(QColor(state["colour"]))
        self.top_output.set_marquee_speed(state["speed"])
        self.top_output.set_marquee_text(state["text"])
        self.top_output.start_marquee()
        self.statusBar().showMessage(tr('Marquee scrolling.'), 4000)

    @Slot()
    def _stop_marquee(self) -> None:
        if self.top_output is not None:
            self.top_output.stop_marquee()
            self.statusBar().showMessage(tr('Marquee stopped.'), 4000)

    # ------------------------------------------------------------- presets -- #

    def _refresh_preset_combo(self, select: Optional[str] = None) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        names = self.presets.names()
        if names:
            self.preset_combo.addItems(names)
            self.preset_combo.setEnabled(True)
        else:
            self.preset_combo.addItem(tr('no presets yet'))
            self.preset_combo.setEnabled(False)
        if select:
            index = self.preset_combo.findText(select)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)
        self.preset_combo.blockSignals(False)

        self._rebuild_preset_strip()

        # The autostart picker offers the same list.
        wanted = self.autostart_preset.currentText()
        self.autostart_preset.blockSignals(True)
        self.autostart_preset.clear()
        if names:
            self.autostart_preset.addItems(names)
            self.autostart_preset.setEnabled(Autostart.available())
            target = select or wanted
            index = self.autostart_preset.findText(target) if target else -1
            self.autostart_preset.setCurrentIndex(max(0, index))
        else:
            self.autostart_preset.addItem(tr('no presets yet'))
            self.autostart_preset.setEnabled(False)
        self.autostart_preset.blockSignals(False)
        # Keep the registered command in step with a renamed or deleted preset.
        if self.autostart_check.isChecked():
            self._refresh_autostart_entry()

    def _collect_preset(self) -> dict:
        payload = {
            "routing": {role: row.config().to_dict() for role, row in self.routing_rows.items()},
            "outputs": {},
            "sound": {"master": self.sound.master, "cues": self.sound.to_list()},
            "slides": self.text_slides.to_dict(),
            "top": {
                "background": self.top_card.background_colour().name(),
                "marquee": self.top_card.marquee_state(),
                # Remembered so an unattended autostart brings the text back too.
                "marquee_running": (self.top_output.is_marquee_running()
                                    if self.top_output is not None else False),
            },
        }
        for role, card in self.cards.items():
            payload["outputs"][role] = {
                "file": card.current_path(),
                "playlist": card.playlist.paths(),
                "scale": card.current_scale_mode().name,
                "volume": card.volume_slider.value(),
                "muted": card.mute_btn.isChecked(),
                "repeat": card.is_repeating(),
            }
        return payload

    def _apply_preset(self, payload: dict) -> None:
        names = [screen.name() for screen in QGuiApplication.screens()]
        missing: List[str] = []

        # Presets written before per-output stacking existed only carry a single
        # "always_on_top"; fall back to it, but never float the Main Stage.
        legacy_on_top = bool(payload.get("always_on_top", True))
        for role, row in self.routing_rows.items():
            data = payload.get("routing", {}).get(role)
            if data:
                default_on_top = False if role == ROLE_MAIN else legacy_on_top
                row.apply_config(RouteConfig.from_dict(data, default_on_top), names)

        self.text_slides.from_dict(payload.get("slides", {}))

        sound_data = payload.get("sound", {})
        if sound_data:
            self.sound_master.setValue(int(sound_data.get("master", self.sound.master)))
            missing += self.sound.from_list(sound_data.get("cues", []))
            self._refresh_cue_pads()

        top_data = payload.get("top", {})
        self.top_card.set_background_colour_value(QColor(top_data.get("background", "#101828")))
        self.top_card.apply_marquee_state(top_data.get("marquee", {}))

        for role, card in self.cards.items():
            data = payload.get("outputs", {}).get(role, {})
            try:
                card.set_scale_mode(ScaleMode[data.get("scale", "FIT")])
            except KeyError:
                pass
            card.volume_slider.setValue(int(data.get("volume", 80)))
            card.mute_btn.setChecked(bool(data.get("muted", False)))
            card.repeat_btn.setChecked(bool(data.get("repeat", True)))

            card.playlist.clear_all()
            queued = [p for p in data.get("playlist", []) if os.path.isfile(p)]
            missing += [os.path.basename(p) for p in data.get("playlist", []) if not os.path.isfile(p)]
            card.playlist.add_paths(queued, announce=False)

            path = data.get("file", "")
            if path and os.path.isfile(path):
                card.show_loaded(path)
            else:
                card.reset_file()

        # Open the windows, then push the remembered media into them.
        self._apply_routing()

        if (top_data.get("marquee_running")
                and self.top_output is not None
                and self.top_card.text_edit.text().strip()):
            self.top_output.start_marquee()

        if missing:
            QMessageBox.warning(
                self,
                tr('Missing files'),
                tr('These files from the preset were not found and were skipped:\n\n')
                + "\n".join(sorted(set(missing))),
            )

    @Slot()
    def _new_preset(self) -> None:
        """
        Blank slate for building a fresh show.

        Monitor routing is deliberately kept: that describes the hall's wiring,
        not the event, and re-picking three screens every time would be a chore.
        """
        if self._preset_dirty and self.loaded_preset:
            answer = QMessageBox.question(
                self,
                tr('Unsaved changes'),
                tr('“{0}” has changes that are not saved.\n\nSave them before starting a new show?').format(self.loaded_preset),
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if answer == QMessageBox.Cancel:
                return
            if answer == QMessageBox.Save:
                self._save_preset()

        for role, card in self.cards.items():
            card.reset_file()
            card.playlist.clear_all()
            card.set_scale_mode(ScaleMode.FIT if role == ROLE_MAIN else ScaleMode.CROP)
            card.volume_slider.setValue(80)
            card.mute_btn.setChecked(False)
            card.repeat_btn.setChecked(True)

        self.top_card.text_edit.clear()
        self.top_card.size_spin.setValue(max(24, int(DEFAULT_TOP_HEIGHT * 0.72)))
        self.top_card.speed_slider.setValue(180)
        self.top_card.set_background_colour_value(QColor("#101828"))

        self.text_slides.set_text("")
        self._hide_slide()

        for cue in self.sound.cues:
            cue.clear()
        self.sound_master.setValue(90)
        self._refresh_cue_pads()

        for window in self._outputs():
            window.clear_output()
        if self.top_output is not None:
            self.top_output.stop_marquee()

        self.loaded_preset = None
        self._preset_dirty = False
        self._describe_preset_state()
        self.preset_state.setText(tr('blank — build the show, then “Save as new…”'))
        self.preset_state.setStyleSheet(f"color: {CLR_ACCENT}; font-weight: 600;")
        self.statusBar().showMessage(
            tr('Cleared. Screens are black, cues are empty, monitor routing kept.'), 8000)

    @Slot()
    def _load_preset(self) -> None:
        name = self.preset_combo.currentText()
        payload = self.presets.get(name) if self.preset_combo.isEnabled() else None
        if not payload:
            QMessageBox.information(self, tr('No preset'), tr('Save a preset first, then it can be loaded.'))
            return

        def apply() -> None:
            self._apply_preset(payload)
            self.loaded_preset = name
            self._preset_dirty = False
            self._describe_preset_state()
            self.statusBar().showMessage(tr('Preset loaded: {0}').format(name), 6000)

        main_file = payload.get("outputs", {}).get(ROLE_MAIN, {}).get("file", "")
        self._change_stage(tr('Preset  “{0}”').format(name), apply,
                           self._thumb_for_path(main_file) if main_file else None,
                           tr('every screen, the sound cues and the marquee'))

    @Slot()
    def _save_preset(self) -> None:
        name = self.preset_combo.currentText()
        if not self.preset_combo.isEnabled() or not name:
            self._save_preset_as()  # nothing to overwrite yet - ask for a name
            return
        self.presets.put(name, self._collect_preset())
        self._write_presets(name)

    @Slot()
    def _save_preset_as(self) -> None:
        name, accepted = QInputDialog.getText(self, tr('Save preset'), tr('Preset name:'))
        name = name.strip()
        if not accepted or not name:
            return
        if name in self.presets.names():
            answer = QMessageBox.question(
                self, tr('Overwrite?'), tr('A preset called “{0}” already exists. Replace it?').format(name)
            )
            if answer != QMessageBox.Yes:
                return
        self.presets.put(name, self._collect_preset())
        self._write_presets(name)

    @Slot()
    def _delete_preset(self) -> None:
        name = self.preset_combo.currentText()
        if not self.preset_combo.isEnabled() or not name:
            return
        if self.sender() is not None and not isinstance(self.sender(), desk_mod.HoldButton):
            # from the right-click menu: no hold there, so ask
            answer = QMessageBox.question(self, tr('Delete preset'), tr('Delete “{0}”?').format(name))
            if answer != QMessageBox.Yes:
                return
        self.presets.remove(name)
        self._write_presets()

    def _write_presets(self, select: Optional[str] = None) -> None:
        error = self.presets.save()
        if error:
            QMessageBox.critical(self, tr('Could not save presets'), error)
            return
        if select:
            self.loaded_preset = select
            self._preset_dirty = False
        self._refresh_preset_combo(select)
        self._describe_preset_state()
        self.statusBar().showMessage(tr('Presets saved to {0}').format(PRESET_FILE), 6000)

    # ------------------------------------------------------------ shutdown -- #

    def _restore_window_geometry(self) -> None:
        """
        Come back the size it was left, and fill the screen the first time.

        The key is versioned: the old one held a small hand-sized window from
        before this defaulted to maximised, and that would have kept winning.
        """
        saved = self.settings.value("window/geometry2")
        restored = bool(saved is not None and self.restoreGeometry(saved))

        # A saved geometry is only worth keeping if it still lands on a screen
        # that exists. The LED processors come and go, and a rectangle recorded
        # against yesterday's monitor arrangement leaves the window stranded at
        # an odd size or half off the desktop.
        if restored and not self.isMaximized():
            frame = self.frameGeometry()
            on_screen = any(s.availableGeometry().intersects(frame)
                            for s in QGuiApplication.screens())
            too_small = frame.width() < 900 or frame.height() < 600
            if not on_screen or too_small:
                restored = False

        if not restored:
            # Windows ignores "maximised" for a window whose starting size is
            # below its minimum, which finger-sized controls can push past the
            # default 1380x940 - and the minimum is not known until the
            # stylesheet is applied at show time. Start at the work area's size.
            area = QGuiApplication.primaryScreen().availableGeometry()
            self.resize(area.width() - 16, area.height() - 40)
            self.setWindowState(self.windowState() | Qt.WindowMaximized)

    def closeEvent(self, event) -> None:  # noqa: N802
        """Closing the control panel tears down every stage window, then quits."""
        live = self._outputs()
        if live:
            # Quitting mid-show blacks out the hall; make it a deliberate act.
            answer = QMessageBox.question(
                self,
                tr('Stage outputs are live'),
                tr('{0} stage screen(s) are still showing content.\n\nQuitting closes them and blacks out the stage. Quit anyway?').format(len(live)),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return

        self.sound.stop_all(0)
        for player in self._show_players:
            player.stop(0)
        self._unregister_hotkeys()
        self._session_timer.stop()
        self.settings.setValue("session/clean", "true")    # closed on purpose: nothing to offer back
        self.presenter.release()             # a PowerPoint slide show closes with the app
        if self.presenter.deck is not None:
            self.presenter.deck.stop()
        pres_mod.release_powerpoint()        # and the hidden PowerPoint behind it, once idle
        self.remote.stop()
        self._end_share(tr("The stage desk closed."))
        self.share.stop()
        self.share_receiver.shutdown()
        self.show_store.save()
        if self.dj_panel:
            self.dj_panel.shutdown()
        if self.mini is not None:
            self.settings.setValue("window/mini_pos", self.mini.pos())
            self.mini.close()
        self._remember_library_places()
        self.settings.setValue("window/geometry2", self.saveGeometry())
        for window in live:
            window.clear_output()
            window.force_close()
            window.deleteLater()
        self.main_output = self.sides_output = self.top_output = None
        event.accept()
        QApplication.quit()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Multi-screen playback controller for an assembly hall stage."
    )
    parser.add_argument(
        "--preset",
        help="Apply this saved preset on startup (used by the Start-with-Windows entry).",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=DEFAULT_STARTUP_DELAY,
        help="Seconds to wait for the monitors before applying --preset.",
    )
    # parse_known_args so Qt's own switches (-platform, -style, ...) pass through.
    options, _unknown = parser.parse_known_args(argv)
    return options


def main() -> int:
    options = parse_args(sys.argv[1:])
    app = QApplication(sys.argv)
    app.setApplicationName("Stage Display Controller")
    # the interface's language, before a single window is built
    set_language(str(QSettings(SETTINGS_ORG, SETTINGS_APP).value("ui/language", "en") or "en"))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET + language_stylesheet())
    if os.path.exists(ICON_FILE):
        app.setWindowIcon(QIcon(ICON_FILE))
    # Output windows must never keep the app alive on their own;
    # ControlPanel.closeEvent() calls QApplication.quit() explicitly.
    app.setQuitOnLastWindowClosed(False)

    panel = ControlPanel()
    panel.show()
    if options.preset:
        panel.run_autostart(options.preset, options.delay)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
