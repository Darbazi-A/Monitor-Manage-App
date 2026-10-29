"""
The desk lock: the control monitor locked behind a PIN while the show goes on.

Windows' own lock (Win+L) covers every monitor - the hall would see the lock
screen. This locks only the desk: a full-screen lock screen on the control
monitor, over everything, with the time, the hall and a PIN pad (the admin PIN).
While it is up:

- the keys that leave a window - Win, Alt+Tab, Alt+F4, Alt+Esc, Ctrl+Esc,
  Ctrl+Shift+Esc, the menu key - do nothing (a low-level keyboard hook);
  Ctrl+Alt+Del still works, as Windows wants;
- the mouse stays on the lock screen (it cannot wander onto the stage monitors);
- the program cannot be closed;
- the stage screens, the sound, the phone remote, Stage Cloud and the clicker all
  keep working - the clicker's keys reach the show through the lock screen.

It is unlocked with the PIN on the lock screen, or from the phone remote or
Stage Cloud. Kept free of main.py imports: the dashboard hands in what it needs.
"""
from __future__ import annotations

from i18n import tr  # noqa: E402 - the interface's language

import ctypes
import sys
import time
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget

PIN_MIN, PIN_MAX = 4, 8
CLICKER_KEYS = {Qt.Key_PageDown: "PgDown", Qt.Key_PageUp: "PgUp"}
KEEP_MS = 1000                    # the lock screen keeps itself in front, the mouse on it, this often

# -- Windows: the keys that leave a window, and the mouse ------------------------------------- #
WH_KEYBOARD_LL, HC_ACTION = 13, 0
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
LLKHF_ALTDOWN = 0x20
VK_TAB, VK_ESCAPE, VK_SPACE, VK_F4 = 0x09, 0x1B, 0x20, 0x73
VK_LWIN, VK_RWIN, VK_APPS = 0x5B, 0x5C, 0x5D
VK_CONTROL, VK_SHIFT = 0x11, 0x10


def blocked_key(vk: int, alt: bool, ctrl: bool, shift: bool) -> bool:
    """A key (with what is held) the lock screen swallows. Ctrl+Alt+Del is never seen here."""
    if vk in (VK_LWIN, VK_RWIN, VK_APPS):
        return True                                       # Start, Win+anything, the context menu
    if alt and vk in (VK_TAB, VK_ESCAPE, VK_F4, VK_SPACE):
        return True                                       # switching, closing, the window menu
    if ctrl and vk == VK_ESCAPE:
        return True                                       # Start (Ctrl+Esc) and Task Manager (Ctrl+Shift+Esc)
    return False


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", ctypes.c_uint32), ("scanCode", ctypes.c_uint32), ("flags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class KeyGuard:
    """While on, a low-level keyboard hook swallows blocked_key(); everything else passes."""

    def __init__(self) -> None:
        self.hook = None
        self._proc = None
        self.swallowed = 0

    def on(self) -> bool:
        if self.hook or sys.platform != "win32":
            return bool(self.hook)
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.GetAsyncKeyState.restype = ctypes.c_short

        def handler(code, wparam, lparam):
            if code == HC_ACTION and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                alt = bool(info.flags & LLKHF_ALTDOWN)
                ctrl = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
                shift = bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
                if blocked_key(info.vkCode, alt, ctrl, shift):
                    self.swallowed += 1
                    return 1
            return user32.CallNextHookEx(None, code, wparam, lparam)

        self._proc = proc_type(handler)                  # kept: Windows calls it for as long as it is set
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, proc_type, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        self.hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        return bool(self.hook)

    def off(self) -> None:
        if self.hook and sys.platform == "win32":
            ctypes.WinDLL("user32").UnhookWindowsHookEx(ctypes.c_void_p(self.hook))
        self.hook = None
        self._proc = None


def clip_cursor_to(hwnd: Optional[int]) -> None:
    """Keep the mouse on the monitor of this window (None: let it go). Windows drops the clip on
    Ctrl+Alt+Del and the like - the lock screen sets it again every second."""
    if sys.platform != "win32":
        return
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32")
    if hwnd is None:
        user32.ClipCursor(None)
        return

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    monitor = user32.MonitorFromWindow(wintypes.HWND(hwnd), 2)          # MONITOR_DEFAULTTONEAREST
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        user32.ClipCursor(ctypes.byref(info.rcMonitor))


LEAVE_IN_FRONT = ("taskmgr.exe", "logonui.exe", "consent.exe")   # Ctrl+Alt+Del's Task Manager, Windows' own


def _foreground_program() -> str:
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)                 # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(520)
        buffer = ctypes.create_unicode_buffer(size.value)
        kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
        return buffer.value.rsplit("\\", 1)[-1].lower()
    finally:
        kernel32.CloseHandle(handle)


def take_foreground(hwnd: int) -> bool:
    """
    The lock screen in front, with the keyboard - even when someone was typing into another
    program (Windows does not let a program simply take the foreground). Not over Task Manager.
    """
    if sys.platform != "win32":
        return False
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    current = user32.GetForegroundWindow()
    if current == hwnd:
        return True
    if _foreground_program() in LEAVE_IN_FRONT:
        return False
    theirs = user32.GetWindowThreadProcessId(current, None)
    mine = kernel32.GetCurrentThreadId()
    attached = bool(theirs) and theirs != mine and user32.AttachThreadInput(theirs, mine, True)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(theirs, mine, False)
    return user32.GetForegroundWindow() == hwnd


def idle_seconds() -> float:
    """How long since anyone touched the keyboard or the mouse (anywhere on the PC)."""
    if sys.platform != "win32":
        return 0.0

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


# -- the lock screen --------------------------------------------------------------------- #
KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "⌫"]


class LockScreen(QWidget):
    """
    The control monitor's lock screen, drawn by hand: a calm dark picture, the time, what the
    stage is doing, and a PIN pad (a mouse, a finger or the keyboard's digits).
    """

    unlockRequested = Signal(str)                 # the PIN typed
    clickerKey = Signal(str)                      # PgDown / PgUp: the show goes on

    def __init__(self, title: str, status: Callable[[], str], theme: dict) -> None:
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setWindowTitle(tr("The desk is locked"))
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.title = title
        self.status = status
        self.theme = theme
        self.pin = ""
        self.message = ""
        self.message_bad = False
        self.shake = 0.0
        self.pressed = ""
        self.allow_close = False
        self._keys: dict = {}
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start(500)
        self._shaker = QTimer(self)
        self._shaker.timeout.connect(self._on_shake)

    # -- what is said -------------------------------------------------------------- #
    def say(self, text: str, bad: bool = False) -> None:
        self.message, self.message_bad = text, bad
        if bad:
            self.pin = ""
            self.shake = 1.0
            self._shaker.start(16)
        self.update()

    def _on_tick(self) -> None:
        self.update()

    def _on_shake(self) -> None:
        self.shake = max(0.0, self.shake - 0.06)
        if self.shake <= 0:
            self._shaker.stop()
        self.update()

    # -- input --------------------------------------------------------------------- #
    def press(self, key: str) -> None:
        if key == "⌫":
            self.pin = self.pin[:-1]
        elif key.isdigit() and len(self.pin) < PIN_MAX:
            self.pin += key
        self.message = ""
        self.update()

    def submit(self) -> None:
        if len(self.pin) < PIN_MIN:
            self.say(tr("At least {0} digits.").format(PIN_MIN), bad=True)
            return
        pin, self.pin = self.pin, ""
        self.unlockRequested.emit(pin)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if Qt.Key_0 <= key <= Qt.Key_9:
            self.press(chr(key))
        elif key == Qt.Key_Backspace:
            self.press("⌫")
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self.submit()
        elif key == Qt.Key_Escape:
            self.pin = ""
            self.update()
        elif not event.isAutoRepeat():
            # anything else may be the clicker: the dashboard decides (PgDown / PgUp, a learned key)
            self.clickerKey.emit(CLICKER_KEYS.get(key) or QKeySequence(key).toString())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        for key, rect in self._keys.items():
            if rect.contains(event.position()):
                self.pressed = key
                self.update()
                return

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        key, self.pressed = self.pressed, ""
        if key and self._keys.get(key, QRectF()).contains(event.position()):
            if key == "ok":
                self.submit()
            else:
                self.press(key)
        self.update()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self.allow_close:
            event.ignore()                         # Alt+F4 and friends never get here, but just in case

    def event(self, event) -> bool:  # noqa: A003
        if event.type() == QEvent.ShortcutOverride:
            event.accept()                         # the dashboard's shortcuts stay quiet behind the lock
            return True
        return super().event(event)

    # -- the picture ------------------------------------------------------------------ #
    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        scale = max(0.6, min(1.4, h / 1080))
        background = QLinearGradient(0, 0, w, h)
        background.setColorAt(0, QColor("#0b1020"))
        background.setColorAt(1, QColor("#05070c"))
        p.fillRect(self.rect(), background)
        for cx, cy, r, colour in ((0.18, 0.15, 0.55, QColor(91, 140, 255, 60)), (0.85, 0.9, 0.5, QColor(139, 108, 255, 45))):
            glow = QRadialGradient(QPointF(w * cx, h * cy), max(w, h) * r)
            glow.setColorAt(0, colour)
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(self.rect(), glow)

        family = self.font().family()

        def text(rect: QRectF, value: str, size: float, weight=QFont.Normal, colour="#e9edf5", align=Qt.AlignCenter):
            font = QFont(family)
            font.setPixelSize(max(9, int(size * scale)))
            font.setWeight(weight)
            p.setFont(font)
            p.setPen(QColor(colour))
            p.drawText(rect, align, value)

        # the left: the time and the hall
        left = QRectF(0, 0, w * 0.56, h)
        cx = left.center().x()
        y = h * 0.30
        now = time.localtime()
        text(QRectF(0, y - 120 * scale, left.width(), 150 * scale), time.strftime("%H:%M", now), 132, QFont.Light)
        text(QRectF(0, y + 30 * scale, left.width(), 40 * scale), time.strftime("%d.%m.%Y", now), 22, QFont.Normal, "#a9b3c6")
        badge = QRectF(cx - 150 * scale, y + 100 * scale, 300 * scale, 44 * scale)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(badge, badge.height() / 2, badge.height() / 2)
        self._lock_icon(p, QPointF(badge.left() + 28 * scale, badge.center().y()), 9 * scale, QColor("#cfdcff"))
        text(badge.adjusted(44 * scale, 0, -12 * scale, 0), tr("The desk is locked"), 16, QFont.DemiBold, "#cfdcff")
        text(QRectF(0, y + 170 * scale, left.width(), 40 * scale), self.title, 24, QFont.DemiBold)
        text(QRectF(w * 0.06, y + 215 * scale, left.width() - w * 0.12, 90 * scale), self.status(), 16, QFont.Normal, "#8a96ab",
             Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap)
        text(QRectF(0, h - 70 * scale, left.width(), 30 * scale),
             tr("The stage, the phone remote and the clicker keep working."), 14, QFont.Normal, "#5f6b80")

        # the right: a card with the PIN pad
        card = QRectF(w * 0.6, h * 0.5 - 330 * scale, min(420 * scale, w * 0.34), 660 * scale)
        offset = self.shake * 14 * scale * (1 if int(self.shake * 40) % 2 else -1)
        card.translate(offset, 0)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.setBrush(QColor(19, 24, 35, 225))
        p.drawRoundedRect(card, 28 * scale, 28 * scale)
        text(QRectF(card.left(), card.top() + 30 * scale, card.width(), 30 * scale), tr("Admin PIN"), 20, QFont.DemiBold)
        # the dots
        count = max(PIN_MIN, len(self.pin))
        gap = 26 * scale
        start = card.center().x() - (count - 1) * gap / 2
        for i in range(count):
            filled = i < len(self.pin)
            p.setPen(QPen(QColor("#5b8cff") if filled else QColor(255, 255, 255, 70), 2))
            p.setBrush(QColor("#5b8cff") if filled else Qt.NoBrush)
            p.drawEllipse(QPointF(start + i * gap, card.top() + 98 * scale), 7 * scale, 7 * scale)
        colour = "#f87171" if self.message_bad else "#a9b3c6"
        text(QRectF(card.left() + 10, card.top() + 118 * scale, card.width() - 20, 28 * scale), self.message, 14, QFont.Normal, colour)
        # the keys
        self._keys = {}
        size = 78 * scale
        spacing = 18 * scale
        grid_w = size * 3 + spacing * 2
        gx = card.center().x() - grid_w / 2
        gy = card.top() + 160 * scale
        for index, key in enumerate(KEYS):
            if not key:
                continue
            row, col = divmod(index, 3)
            rect = QRectF(gx + col * (size + spacing), gy + row * (size + spacing * 0.7), size, size)
            self._keys[key] = rect
            down = self.pressed == key
            p.setPen(QPen(QColor(255, 255, 255, 30), 1))
            p.setBrush(QColor(91, 140, 255, 90) if down else QColor(255, 255, 255, 14))
            p.drawEllipse(rect)
            text(rect, key, 28 if key != "⌫" else 22, QFont.Normal)
        button = QRectF(card.left() + 32 * scale, card.bottom() - 84 * scale, card.width() - 64 * scale, 56 * scale)
        self._keys["ok"] = button
        gradient = QLinearGradient(button.topLeft(), button.bottomRight())
        gradient.setColorAt(0, QColor("#5b8cff"))
        gradient.setColorAt(1, QColor("#8b6cff"))
        p.setPen(Qt.NoPen)
        p.setBrush(gradient if len(self.pin) >= PIN_MIN else QColor(255, 255, 255, 16))
        p.drawRoundedRect(button, 16 * scale, 16 * scale)
        text(button, tr("Unlock"), 18, QFont.DemiBold, "#ffffff" if len(self.pin) >= PIN_MIN else "#6d788d")
        p.end()

    @staticmethod
    def _lock_icon(p: QPainter, centre: QPointF, r: float, colour: QColor) -> None:
        p.save()
        p.setPen(QPen(colour, max(1.5, r * 0.28), Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        shackle = QPainterPath()
        shackle.moveTo(centre.x() - r * 0.6, centre.y() - r * 0.1)
        shackle.lineTo(centre.x() - r * 0.6, centre.y() - r * 0.6)
        shackle.arcTo(QRectF(centre.x() - r * 0.6, centre.y() - r * 1.3, r * 1.2, r * 1.4), 180, -180)
        shackle.lineTo(centre.x() + r * 0.6, centre.y() - r * 0.1)
        p.drawPath(shackle)
        p.setPen(Qt.NoPen)
        p.setBrush(colour)
        p.drawRoundedRect(QRectF(centre.x() - r, centre.y() - r * 0.15, r * 2, r * 1.4), r * 0.3, r * 0.3)
        p.restore()


class DeskLock:
    """The lock as the dashboard uses it: on, off, kept in front, the keys and the mouse held."""

    def __init__(self, title: Callable[[], str], status: Callable[[], str], screen: Callable[[], object],
                 theme: dict, on_unlock_pin: Callable[[str], None], on_clicker: Callable[[str], None]) -> None:
        self._title, self._status, self._screen, self.theme = title, status, screen, theme
        self._on_unlock_pin, self._on_clicker = on_unlock_pin, on_clicker
        self.window: Optional[LockScreen] = None
        self.guard = KeyGuard()
        self._keep = QTimer()
        self._keep.timeout.connect(self._keep_in_front)

    def locked(self) -> bool:
        return self.window is not None

    def lock(self) -> None:
        if self.window is not None:
            return
        window = LockScreen(self._title(), self._status, self.theme)
        window.unlockRequested.connect(self._on_unlock_pin)
        window.clickerKey.connect(self._on_clicker)
        screen = self._screen() or QApplication.primaryScreen()
        window.setGeometry(screen.geometry())
        window.show()
        window.windowHandle().setScreen(screen)
        window.showFullScreen()
        window.raise_()
        window.activateWindow()
        take_foreground(int(window.winId()))
        window.setFocus()
        self.window = window
        self.guard.on()
        clip_cursor_to(int(window.winId()))
        self._keep.start(KEEP_MS)

    def unlock(self) -> None:
        self._keep.stop()
        self.guard.off()
        clip_cursor_to(None)
        window, self.window = self.window, None
        if window is not None:
            window.allow_close = True
            window.close()
            window.deleteLater()

    def say(self, text: str, bad: bool = False) -> None:
        if self.window is not None:
            self.window.say(text, bad)

    def _keep_in_front(self) -> None:
        window = self.window
        if window is None:
            return
        screen = self._screen()
        if screen is not None and window.screen() is not screen:
            window.windowHandle().setScreen(screen)
            window.setGeometry(screen.geometry())
            window.showFullScreen()
        if not window.isActiveWindow():
            window.raise_()
            window.activateWindow()
            if take_foreground(int(window.winId())):
                window.setFocus()
        if not self.guard.hook:
            self.guard.on()
        clip_cursor_to(int(window.winId()))        # again: Ctrl+Alt+Del and UAC let it go
