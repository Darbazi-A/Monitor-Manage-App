"""
Windows 11: how the app looks among other Windows apps, and how Windows treats it.

Looks
    Dark title bars in the app's own colours (Windows 11 lets an app colour its
    caption, caption text and border), Windows 11's rounded corners on dialogs,
    menus and drop-downs - and none at all, nor a border, on the stage windows:
    a projector or LED wall must get every pixel, square to the corner.

Behaviour
    Windows 11 slows down apps it thinks are in the background ("EcoQoS",
    efficiency mode) and ignores their timer requests while their window is
    minimised or covered. The desk is often exactly that - shrunk to the compact
    bar, or behind PowerPoint - while it is driving three stage screens, so the
    app opts out of both for itself. While any stage window is open it also asks
    Windows to keep the displays and the PC awake: a show can run for an hour
    without anyone touching the mouse, and the stock power plan turns the
    displays off after ten minutes.

Everything here only affects this app's own process and windows, needs no
administrator rights, and quietly does nothing on other systems.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Optional

IS_WINDOWS = sys.platform == "win32"
BUILD = sys.getwindowsversion().build if IS_WINDOWS else 0
IS_WIN11 = BUILD >= 22000

# DwmSetWindowAttribute
DWMWA_TRANSITIONS_FORCEDISABLED = 3
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWCP_DEFAULT, DWMWCP_DONOTROUND, DWMWCP_ROUND, DWMWCP_ROUNDSMALL = 0, 1, 2, 3
DWMWA_COLOR_NONE = 0xFFFFFFFE

# the process
PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION = 0x4
PROCESS_POWER_THROTTLING_INFORMATION = 4          # PROCESS_INFORMATION_CLASS.ProcessPowerThrottling
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


class _ThrottlingState(ctypes.Structure):
    _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]


def _colorref(colour: str) -> int:
    colour = colour.lstrip("#")
    red, green, blue = int(colour[0:2], 16), int(colour[2:4], 16), int(colour[4:6], 16)
    return red | (green << 8) | (blue << 16)


def _dwm(hwnd: int, attribute: int, value: int) -> bool:
    if not IS_WINDOWS or not hwnd:
        return False
    data = ctypes.c_uint(value)
    try:
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd), wintypes.DWORD(attribute), ctypes.byref(data), ctypes.sizeof(data))
    except (OSError, AttributeError):
        return False
    return result == 0


# --------------------------------------------------------------------------- #
# Windows
# --------------------------------------------------------------------------- #

def style_window(hwnd: int, caption: str, text: str, border: str, corners: int = DWMWCP_ROUND) -> bool:
    """An ordinary app window or dialog: a dark caption in the app's colours, rounded corners."""
    done = _dwm(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
    if IS_WIN11:
        done = all([_dwm(hwnd, DWMWA_CAPTION_COLOR, _colorref(caption)),
                    _dwm(hwnd, DWMWA_TEXT_COLOR, _colorref(text)),
                    _dwm(hwnd, DWMWA_BORDER_COLOR, _colorref(border)),
                    _dwm(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, corners)]) and done
    return done


def style_popup(hwnd: int, border: Optional[str] = None) -> None:
    """A menu, drop-down or tooltip: Windows 11's small rounded corners and a hairline."""
    if IS_WIN11:
        _dwm(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUNDSMALL)
        if border:
            _dwm(hwnd, DWMWA_BORDER_COLOR, _colorref(border))


def style_stage(hwnd: int) -> bool:
    """A stage window: square corners, no border, no fade - every pixel goes to the screen."""
    done = _dwm(hwnd, DWMWA_TRANSITIONS_FORCEDISABLED, 1)
    if IS_WIN11:
        done = all([_dwm(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_DONOTROUND),
                    _dwm(hwnd, DWMWA_BORDER_COLOR, DWMWA_COLOR_NONE)]) and done
    return done


def dwm_attribute(hwnd: int, attribute: int) -> Optional[int]:
    """What DWM has for one of this window's attributes (for the tests)."""
    if not IS_WINDOWS or not hwnd:
        return None
    data = ctypes.c_uint(0)
    try:
        result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd), wintypes.DWORD(attribute), ctypes.byref(data), ctypes.sizeof(data))
    except (OSError, AttributeError):
        return None
    return data.value if result == 0 else None


def corner_preference(hwnd: int) -> Optional[int]:
    return dwm_attribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE)


def priority_class() -> Optional[int]:
    if not IS_WINDOWS:
        return None
    try:
        kernel32 = _kernel32()
        kernel32.GetPriorityClass.argtypes = [wintypes.HANDLE]
        kernel32.GetPriorityClass.restype = wintypes.DWORD
        return int(kernel32.GetPriorityClass(kernel32.GetCurrentProcess()))
    except (OSError, AttributeError):
        return None


# --------------------------------------------------------------------------- #
# The process
# --------------------------------------------------------------------------- #

def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetProcessInformation.restype = wintypes.BOOL
    kernel32.GetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.GetProcessInformation.restype = wintypes.BOOL
    kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.SetPriorityClass.restype = wintypes.BOOL
    kernel32.SetThreadExecutionState.argtypes = [wintypes.DWORD]
    kernel32.SetThreadExecutionState.restype = wintypes.DWORD
    return kernel32


def opt_out_of_throttling() -> bool:
    """
    Full speed and real timer resolution even when Windows thinks the app is in
    the background (EcoQoS, and Windows 11 ignoring the timers of minimised or
    covered windows). Only this process.
    """
    if not IS_WINDOWS:
        return False
    state = _ThrottlingState(PROCESS_POWER_THROTTLING_CURRENT_VERSION,
                             PROCESS_POWER_THROTTLING_EXECUTION_SPEED | PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION,
                             0)          # controlled, and switched off
    try:
        kernel32 = _kernel32()
        return bool(kernel32.SetProcessInformation(kernel32.GetCurrentProcess(), PROCESS_POWER_THROTTLING_INFORMATION,
                                                   ctypes.byref(state), ctypes.sizeof(state)))
    except (OSError, AttributeError):
        return False


def throttling_state() -> Optional[tuple]:
    """(ControlMask, StateMask) as Windows has them for this process (for the tests)."""
    if not IS_WINDOWS:
        return None
    state = _ThrottlingState(PROCESS_POWER_THROTTLING_CURRENT_VERSION, 0, 0)
    try:
        kernel32 = _kernel32()
        if not kernel32.GetProcessInformation(kernel32.GetCurrentProcess(), PROCESS_POWER_THROTTLING_INFORMATION,
                                              ctypes.byref(state), ctypes.sizeof(state)):
            return None
    except (OSError, AttributeError):
        return None
    return state.ControlMask, state.StateMask


def raise_priority() -> bool:
    """Above normal: a busy PowerPoint or a laptop's browser does not starve the stage's video."""
    if not IS_WINDOWS:
        return False
    try:
        kernel32 = _kernel32()
        return bool(kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), ABOVE_NORMAL_PRIORITY_CLASS))
    except (OSError, AttributeError):
        return False


_awake = False


def keep_awake(on: bool) -> None:
    """While stage windows are open: no display sleep, no PC sleep. Off again when they close."""
    global _awake
    if not IS_WINDOWS or on == _awake:
        return
    try:
        kernel32 = _kernel32()
        flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED if on else ES_CONTINUOUS
        if kernel32.SetThreadExecutionState(flags):
            _awake = on
    except (OSError, AttributeError):
        pass


def keeping_awake() -> bool:
    return _awake


def tune_process() -> dict:
    """Everything the process asks of Windows at start-up; what worked, for the log and the tests."""
    return {"throttling": opt_out_of_throttling(), "priority": raise_priority()}
