"""
The dashboard's side of the school timer (school_timer.py): which screen it is
on, keeping every screen that shows it up to date a few times a second, the
signal when the time is up, and remembering the time and the look.

TimerControl is mixed into ControlPanel. A rehearsal shows the timer in its
window as well, while the hall keeps the one it had; BLACKOUT takes it away.
"""
from __future__ import annotations

from i18n import tr  # noqa: E402 - the interface's language

import json
import os
from typing import List, Optional, Tuple

from PySide6.QtCore import QSize, QTimer, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFileDialog

from config import ROLE_LABELS, STAGE_ROLES
import school_timer as timer_mod

TICK_MS = 125                     # eight times a second: the line moves smoothly, the seconds on time


class TimerControl:
    """The timer's place in the dashboard. Mixed into ControlPanel."""

    def _timer_setup(self) -> None:
        self.timer_clock = timer_mod.TimerClock(self)
        try:
            self.timer_clock.load(json.loads(self.settings.value("timer/clock", "") or "{}"))
        except (TypeError, ValueError):
            pass
        try:
            self._timer_look = timer_mod.clean_look(json.loads(self.settings.value("timer/look", "") or "{}"))
        except (TypeError, ValueError):
            self._timer_look = dict(timer_mod.DEFAULT_LOOK)
        self._timer_role = ""
        self._timer_windows: List = []
        self._timer_logo = self._timer_load_logo()
        self._timer_player = None
        self._timer_ticks = 0
        self.timer_clock.changed.connect(self._timer_remember)
        self.timer_clock.reachedZero.connect(self._timer_at_zero)
        self._timer_ticker = QTimer(self)
        self._timer_ticker.timeout.connect(self._timer_tick)
        self._timer_ticker.start(TICK_MS)

    def _timer_load_logo(self) -> Optional[QPixmap]:
        path = str(self.settings.value("timer/logo", "") or "") or timer_mod.default_logo()
        if path and os.path.isfile(path):
            picture = QPixmap(path)
            if not picture.isNull():
                # big enough for a 4K screen's corner, small enough to draw eight times a second
                return picture.scaledToHeight(min(picture.height(), 360)) if picture.height() > 360 else picture
        return None

    def _timer_remember(self) -> None:
        self.settings.setValue("timer/clock", json.dumps(self.timer_clock.to_dict(), ensure_ascii=False))

    # -- the page ------------------------------------------------------------------ #
    def _build_timer_page(self):
        page = timer_mod.TimerPage(self.timer_clock, self._timer_icons(), self._timer_theme(),
                                   [(role, ROLE_LABELS[role]) for role in STAGE_ROLES])
        page.set_logo(self._timer_logo)
        page.set_look(self._timer_look)
        page.showRequested.connect(lambda role: self._timer_report(self.timer_show(role)))
        page.hideRequested.connect(lambda: self._timer_report(self.timer_hide()))
        page.lookChanged.connect(self.timer_set_look)
        page.logoRequested.connect(self._timer_choose_logo)
        self.timer_page = page
        return page

    def _timer_report(self, answer: Tuple[bool, str]) -> None:
        ok, message = answer
        if message:
            self.statusBar().showMessage(message, 6000)

    def _timer_choose_logo(self) -> None:
        start = os.path.dirname(str(self.settings.value("timer/logo", "") or "")) or os.path.expanduser("~/Desktop")
        path, _ = QFileDialog.getOpenFileName(self, tr("A logo for the timer"), start,
                                              tr("Pictures") + " (*.png *.jpg *.jpeg *.bmp *.webp *.svg)")
        if path:
            self.timer_set_logo(path)

    def timer_set_logo(self, path: str) -> Tuple[bool, str]:
        picture = QPixmap(path) if path and os.path.isfile(path) else QPixmap()
        if picture.isNull():
            return False, tr("That picture could not be opened.")
        self.settings.setValue("timer/logo", path)
        self._timer_logo = self._timer_load_logo()
        self.timer_page.set_logo(self._timer_logo)
        return True, tr("The timer's logo: {0}").format(os.path.basename(path))

    # -- on a screen ------------------------------------------------------------------- #
    def timer_show(self, role: str) -> Tuple[bool, str]:
        if role not in STAGE_ROLES:
            return False, tr("No such screen.")
        window = self._show_output(role)
        if window is None:
            return False, tr("{0} is closed - open the screens first.").format(ROLE_LABELS[role])
        if self._timer_role and self._timer_role != role:
            self.timer_hide()
        self._timer_role = role
        if window not in self._timer_windows:
            self._timer_windows.append(window)
        self._timer_tick()
        self.timer_page.set_on_screen(role)
        return True, tr("The timer is on {0}.").format(ROLE_LABELS[role])

    def timer_hide(self) -> Tuple[bool, str]:
        from shiboken6 import Shiboken

        for window in self._timer_windows:
            if Shiboken.isValid(window):
                window.set_timer(None)
        self._timer_windows = []
        was, self._timer_role = self._timer_role, ""
        self.timer_page.set_on_screen("")
        return True, (tr("The timer came off {0}.").format(ROLE_LABELS[was]) if was else "")

    def timer_set_look(self, look: dict) -> None:
        self._timer_look = timer_mod.clean_look(dict(self._timer_look, **(look or {})))
        self.settings.setValue("timer/look", json.dumps(self._timer_look))
        if self.timer_page.look != self._timer_look:
            self.timer_page.set_look(self._timer_look)
        self._timer_tick()

    def _timer_tick(self) -> None:
        from shiboken6 import Shiboken

        clock = self.timer_clock
        clock.poll()
        look = self._timer_look
        frame = clock.frame(look)
        role = self._timer_role
        if role:
            current = self._show_output(role)
            if current is not None and current not in self._timer_windows:
                self._timer_windows.append(current)      # opened again, or a rehearsal began
            alive = []
            for window in self._timer_windows:
                if Shiboken.isValid(window):
                    window.set_timer(look, frame, self._timer_logo)
                    alive.append(window)
            self._timer_windows = alive
        self._timer_ticks += 1
        page = getattr(self, "timer_page", None)
        if page is not None and page.isVisible() and self._timer_ticks % 2 == 0:
            shown = page.on_screen or page.chosen_screen() or STAGE_ROLES[0]
            size = self._stage_size(shown)
            aspect = size.width() / max(1, size.height())
            picture = None
            window = self._show_output(role) if role else None
            if window is not None:
                width = 640 if aspect > 3 else 480
                picture = window.preview(QSize(width, max(12, int(width / aspect))))
            page.show_frame(frame, picture, aspect)

    # -- the end ------------------------------------------------------------------------- #
    def _timer_at_zero(self) -> None:
        self.statusBar().showMessage(tr("The timer is at 0:00."), 8000)
        if self._timer_look.get("sound") != "beeps" or not self._timer_role or self._rehearsal is not None:
            return                       # only a timer the hall can see beeps in the hall
        from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer

        path = os.path.join(os.path.dirname(timer_mod.default_logo()), "timer_beeps.wav")
        if not os.path.isfile(path):
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as handle:
                    handle.write(timer_mod.beeps_wav())
            except OSError:
                return
        if self._timer_player is None:
            self._timer_player = QMediaPlayer(self)
            self._timer_player.setAudioOutput(QAudioOutput(self._timer_player))
        wanted = self.audio_device_combo.currentData()
        device = next((d for d in QMediaDevices.audioOutputs() if d.description() == wanted), None) \
            if wanted else None
        output = self._timer_player.audioOutput()
        output.setDevice(device or QMediaDevices.defaultAudioOutput())
        output.setVolume(max(0.0, min(1.0, self.sound_master.value() / 100.0)))
        self._timer_player.setSource(QUrl.fromLocalFile(path))
        self._timer_player.setPosition(0)
        self._timer_player.play()

    # -- for the phone ------------------------------------------------------------------- #
    def timer_state(self) -> dict:
        clock = self.timer_clock
        return {"frame": clock.frame(self._timer_look), "look": dict(self._timer_look), "on": self._timer_role,
                "mode": clock.mode, "title": clock.title, "duration": clock.duration_ms,
                "until": clock.until.toString("HH:mm"), "running": clock.running}

    def _timer_icons(self):
        from theme import Icons
        return Icons

    def _timer_theme(self) -> dict:
        from theme import THEME
        return THEME
