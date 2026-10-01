"""
Who is at the desk: the administrator, or someone using the simple desk.

The administrator sees everything - the screens' wiring, presets, the running
order's editor, the library, the DJ desk, the settings. Anyone else (a teacher
rehearsing in the hall, a visiting speaker's helper) gets the simple desk: the
scenes, a file or a presentation on a screen, the sound, a laptop, BLACKOUT -
and nothing that could undo the setup. Leaving the simple desk takes the admin
PIN.

The PIN is kept only as a salted PBKDF2-SHA256 hash in the app's settings;
five wrong tries lock the pad for half a minute.
"""
from __future__ import annotations

from i18n import tr  # noqa: E402 - the interface's language

import hashlib
import secrets
import time
from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

ITERATIONS = 120_000
PIN_MIN, PIN_MAX = 4, 8
MAX_TRIES = 5
LOCK_SECONDS = 30


def hash_pin(pin: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), bytes.fromhex(salt), ITERATIONS).hex()
    return f"pbkdf2-sha256${ITERATIONS}${salt}${digest}"


def check_pin(pin: str, stored: str) -> bool:
    try:
        _kind, rounds, salt, digest = stored.split("$")
        mine = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), bytes.fromhex(salt), int(rounds)).hex()
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(mine, digest)


class Access:
    """The admin PIN and the lock-out after wrong tries."""

    KEY = "security/admin_pin"

    def __init__(self, settings) -> None:
        self.settings = settings
        self._wrong = 0
        self._locked_until = 0.0

    def has_pin(self) -> bool:
        return bool(str(self.settings.value(self.KEY, "") or ""))

    def set_pin(self, pin: str) -> None:
        self.settings.setValue(self.KEY, hash_pin(pin))

    def clear_pin(self) -> None:
        self.settings.remove(self.KEY)

    def locked_for(self) -> int:
        return max(0, int(self._locked_until - time.monotonic() + 0.999))

    def verify(self, pin: str) -> bool:
        if self.locked_for():
            return False
        if check_pin(pin, str(self.settings.value(self.KEY, "") or "")):
            self._wrong = 0
            return True
        self._wrong += 1
        if self._wrong >= MAX_TRIES:
            self._wrong = 0
            self._locked_until = time.monotonic() + LOCK_SECONDS
        return False

    def start_simple(self) -> bool:
        """The app opens on the simple desk once there is a PIN to guard the rest (unless told otherwise)."""
        return self.has_pin() and str(self.settings.value("security/start_simple", "true")).lower() == "true"


class PinDialog(QDialog):
    """
    A PIN pad sized for a finger. "enter" checks the admin PIN; "set" asks for a
    new one twice. The keyboard's digits, Backspace and Enter work too.
    """

    def __init__(self, theme: dict, mode: str = "enter", access: Optional[Access] = None,
                 title: str = "", parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.mode = mode
        self.access = access
        self.pin = ""
        self._first = ""
        self.setWindowTitle(title or (tr("Admin PIN") if mode == "enter" else tr("Choose an admin PIN")))
        self.setModal(True)
        box = QVBoxLayout(self)
        box.setContentsMargins(28, 24, 28, 22)
        box.setSpacing(14)
        self.heading = QLabel()
        self.heading.setObjectName("pageTitle")
        self.heading.setAlignment(Qt.AlignHCenter)
        box.addWidget(self.heading)
        self.message = QLabel()
        self.message.setObjectName("cardHint")
        self.message.setAlignment(Qt.AlignHCenter)
        self.message.setWordWrap(True)
        self.message.setMinimumWidth(300)
        box.addWidget(self.message)
        self.dots = QLabel()
        self.dots.setAlignment(Qt.AlignHCenter)
        self.dots.setMinimumHeight(44)
        self.dots.setStyleSheet(f"font-size: 28px; letter-spacing: 10px; color: {theme['text']};")
        box.addWidget(self.dots)

        grid = QGridLayout()
        grid.setSpacing(10)
        keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "OK"]
        self.key_buttons = {}
        for i, key in enumerate(keys):
            button = QPushButton(tr("OK") if key == "OK" else key)
            button.setFixedSize(QSize(84, 58))
            button.setFocusPolicy(Qt.NoFocus)
            button.setStyleSheet("font-size: 20px; font-weight: 600;")
            if key == "OK":
                button.setObjectName("primary")
            button.clicked.connect(lambda _c=False, k=key: self._press(k))
            grid.addWidget(button, i // 3, i % 3)
            self.key_buttons[key] = button
        box.addLayout(grid)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(tr("Cancel"))
        cancel.setFocusPolicy(Qt.NoFocus)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        box.addLayout(row)
        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self._show)
        self._ticker.start(500)
        self._show()

    # -- input --------------------------------------------------------------- #
    def keyPressEvent(self, event) -> None:  # noqa: N802
        text = event.text()
        if text.isdigit():
            self._press(text)
        elif event.key() == Qt.Key_Backspace:
            self._press("⌫")
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._press("OK")
        elif event.key() == Qt.Key_Escape:
            self.reject()

    def _press(self, key: str) -> None:
        if key == "⌫":
            self.pin = self.pin[:-1]
        elif key == "OK":
            self._submit()
            return
        elif len(self.pin) < PIN_MAX:
            self.pin += key
        self._show()

    def _submit(self) -> None:
        if len(self.pin) < PIN_MIN:
            self._say(tr("At least {0} digits.").format(PIN_MIN), bad=True)
            return
        if self.mode == "enter":
            if self.access is not None and self.access.verify(self.pin):
                self.accept()
                return
            self.pin = ""
            self._say(tr("Wrong PIN."), bad=True)
            return
        if not self._first:
            self._first, self.pin = self.pin, ""
            self._say(tr("Type it once more."))
            return
        if self.pin != self._first:
            self._first, self.pin = "", ""
            self._say(tr("The two did not match - start again."), bad=True)
            return
        self.accept()

    # -- display ------------------------------------------------------------- #
    def _say(self, text: str, bad: bool = False) -> None:
        self._said = text
        self.message.setStyleSheet(f"color: {self.theme['danger']};" if bad else "")
        self._show()

    def _show(self) -> None:
        if self.mode == "enter":
            self.heading.setText(tr("Admin PIN"))
            locked = self.access.locked_for() if self.access is not None else 0
            if locked:
                self.message.setText(tr("Too many wrong tries - wait {0} s.").format(locked))
                self.message.setStyleSheet(f"color: {self.theme['danger']};")
            elif not getattr(self, "_said", ""):
                self.message.setText(tr("Everything beyond the simple desk needs the administrator's PIN."))
            else:
                self.message.setText(self._said)
            for button in self.key_buttons.values():
                button.setEnabled(not locked)
        else:
            self.heading.setText(tr("Choose an admin PIN") if not self._first else tr("Confirm the PIN"))
            if not getattr(self, "_said", ""):
                self.message.setText(tr("{0} to {1} digits. Keep it to the people who set the hall up.").format(PIN_MIN, PIN_MAX))
            else:
                self.message.setText(self._said)
        self.dots.setText("●" * len(self.pin) + "○" * max(0, PIN_MIN - len(self.pin)))


def ask_pin(theme: dict, access: Access, parent=None) -> bool:
    """True when the admin PIN was typed."""
    return PinDialog(theme, "enter", access, parent=parent).exec() == QDialog.Accepted


def choose_pin(theme: dict, parent=None, title: str = "") -> Optional[str]:
    """A new PIN, typed twice - or None."""
    dialog = PinDialog(theme, "set", title=title, parent=parent)
    return dialog.pin if dialog.exec() == QDialog.Accepted else None
