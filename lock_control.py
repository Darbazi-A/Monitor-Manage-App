"""
The dashboard's side of the desk lock (desklock.py): locking and unlocking - from the desk,
the phone remote, Stage Cloud, or by itself after a while with nobody at the desk - the PIN,
the clicker through the lock, and its card in Settings → Admin & simple desk.
Mixed into ControlPanel.

A locked desk stays locked: the program cannot be closed, and if it is started again
(after Ctrl+Alt+Del → Task Manager, a crash) it locks itself again at once.
"""
from __future__ import annotations

from i18n import tr  # noqa: E402 - the interface's language

import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

import access as access_mod
import desklock as lock_mod
from config import HALL, ROLE_LABELS, STAGE_ROLES
from theme import CLR_TEXT, THEME, Icons

AUTOLOCK_CHOICES = (0, 5, 10, 15, 30, 60)            # minutes; 0 = never
IDLE_CHECK_MS = 15_000


class LockControl:
    """The desk lock, from the dashboard. Mixed into ControlPanel."""

    def _lock_setup(self) -> None:
        self.desk_lock = lock_mod.DeskLock(
            title=lambda: HALL.get("name") or "Stage Display Controller", status=self._lock_status,
            screen=lambda: self.screen(), theme=THEME,
            on_unlock_pin=self._unlock_with_pin, on_clicker=self._lock_clicker)
        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._check_autolock)
        self._idle_timer.start(IDLE_CHECK_MS)
        if str(self.settings.value("desk/locked", "false")).lower() == "true" and not os.environ.get("SDC_NO_RELOCK"):
            QTimer.singleShot(1500, lambda: self.lock_desk("restart"))     # it was locked when it went down

    def desk_locked(self) -> bool:
        return self.desk_lock.locked()

    # -- on and off ------------------------------------------------------------------ #
    def lock_desk(self, source: str = "desk"):
        """Returns (ok, message). From the desk, a PIN is chosen first if there is none."""
        if self.desk_locked():
            return True, tr("The desk is locked.")
        if not self.access.has_pin():
            if source != "desk":
                return False, tr("Set an admin PIN first (Settings → Admin & simple desk).")
            pin = access_mod.choose_pin(THEME, self, tr("Choose an admin PIN - it unlocks the desk"))
            if not pin:
                return False, ""
            self.access.set_pin(pin)
            self._describe_security()
        if self.mini is not None and self.mini.isVisible():
            self.restore_from_bar()
        self.desk_lock.lock()
        self.settings.setValue("desk/locked", "true")
        self._lock_changed()
        return True, tr("The desk is locked.")

    def unlock_desk(self, by: str = ""):
        if not self.desk_locked():
            return True, tr("The desk is not locked.")
        self.desk_lock.unlock()
        self.settings.setValue("desk/locked", "false")
        self._lock_changed()
        if by:
            self.statusBar().showMessage(tr("Unlocked by {0}.").format(by), 10000)
        return True, tr("The desk is unlocked.")

    def _lock_changed(self) -> None:
        locked = self.desk_locked()
        if hasattr(self, "lock_chip"):
            self.lock_chip.setVisible(not locked)
        if hasattr(self, "lock_now_btn"):
            self.lock_now_btn.setEnabled(not locked)
        self._refresh_tray()
        if hasattr(self, "cloud"):
            QTimer.singleShot(0, self.cloud.send_status)

    def _unlock_with_pin(self, pin: str) -> None:
        wait = self.access.locked_for()
        if wait > 0:
            self.desk_lock.say(tr("Too many wrong PINs - wait {0} s.").format(wait), bad=True)
        elif self.access.verify(pin):
            self.unlock_desk()
        else:
            wait = self.access.locked_for()
            self.desk_lock.say(tr("Too many wrong PINs - wait {0} s.").format(wait) if wait else tr("Wrong PIN."), bad=True)

    def _lock_clicker(self, name: str) -> None:
        """A key on the lock screen: the clicker's (Page Down / Up, or one it was taught) works the show."""
        learned = {info.get("name") for info in self._learned().values()}
        if name in ("PgDown", "PgUp") or name in learned:
            self._clicker_key(name, None, "desk locked")

    def _lock_status(self) -> str:
        """One line under the hall's name: what is on the stage."""
        parts = []
        for role in STAGE_ROLES:
            if self._show_output(role) is not None:
                path = self.cards[role].current_path()
                if path:
                    parts.append(f"{ROLE_LABELS[role]}: {os.path.basename(path)}")
        steps = self.show_tab.steps()
        if 0 <= self.show_index < len(steps):
            parts.append(tr("Running order: {0}, step {1} of {2}").format(
                self.show_store.current, self.show_index + 1, len(steps)))
        if self.presenter.live:
            parts.append(tr("Slides on screen"))
        return "  ·  ".join(parts) or tr("Nothing on the stage just now.")

    def _check_autolock(self) -> None:
        minutes = int(self.settings.value("desk/autolock", 0) or 0)
        if minutes <= 0 or self.desk_locked() or not self.access.has_pin():
            return
        if lock_mod.idle_seconds() >= minutes * 60:
            self.lock_desk("auto")

    # -- Settings → Admin & simple desk ---------------------------------------------------- #
    def _build_lock_card(self) -> QWidget:
        card, box = self._settings_card(tr('Desk lock'))
        text = QLabel(tr('Locks the control monitor behind the admin PIN while the show goes on: the stage screens, '
                         'the sound, the phone remote, Stage Cloud and the clicker keep working. On the locked desk '
                         'Win, Alt+Tab, Alt+F4 and the like do nothing, the mouse stays on the lock screen and the '
                         'program cannot be closed; Ctrl+Alt+Del still works. The phone remote and Stage Cloud can '
                         'lock and unlock it too.'))
        text.setObjectName("cardHint")
        text.setWordWrap(True)
        box.addWidget(text)
        row = QHBoxLayout()
        self.lock_now_btn = QPushButton(tr('  Lock the desk now'))
        self.lock_now_btn.setObjectName("primary")
        self.lock_now_btn.setIcon(Icons.get("lock", "#ffffff", 16))
        self.lock_now_btn.clicked.connect(lambda: self.lock_desk("desk"))
        row.addWidget(self.lock_now_btn)
        row.addSpacing(16)
        row.addWidget(QLabel(tr('Lock by itself after')))
        self.autolock_combo = QComboBox()
        for minutes in AUTOLOCK_CHOICES:
            self.autolock_combo.addItem(tr('never') if minutes == 0 else tr('{0} min with nobody at the desk').format(minutes), minutes)
        current = int(self.settings.value("desk/autolock", 0) or 0)
        self.autolock_combo.setCurrentIndex(max(0, self.autolock_combo.findData(current)))
        self.autolock_combo.currentIndexChanged.connect(
            lambda _i: self.settings.setValue("desk/autolock", self.autolock_combo.currentData()))
        row.addWidget(self.autolock_combo)
        row.addStretch(1)
        box.addLayout(row)
        return card

    def _make_lock_chip(self) -> QPushButton:
        chip = QPushButton(tr(" Lock"))
        chip.setIcon(Icons.get("lock", CLR_TEXT, 15))
        chip.setFlat(True)
        chip.setToolTip(tr("Lock the desk: the show goes on, the desk needs the admin PIN"))
        chip.clicked.connect(lambda: self.lock_desk("desk"))
        return chip
