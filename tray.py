"""
The app's icon by the clock (the notification area): minimising the dashboard
hides it there instead of leaving a button on the taskbar, and the show goes
on - the stage screens, the sound, the clicker, the phone remote and the laptop
share all keep working while the desk is out of sight.

A click on the icon brings the desk back; its menu also offers the small bar,
BLACKOUT, stopping all sound, and quitting.

Kept free of main.py imports: the dashboard listens to the signals.
"""
from __future__ import annotations

from i18n import tr  # noqa: E402 - the interface's language

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

APP_NAME = "Stage Display Controller"


class StageTray(QObject):
    openRequested = Signal()
    barRequested = Signal()
    blackoutRequested = Signal()
    stopSoundRequested = Signal()
    quitRequested = Signal()

    def __init__(self, icon: QIcon, parent: QObject = None) -> None:
        super().__init__(parent)
        self.icon: QSystemTrayIcon = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.icon = QSystemTrayIcon(icon, self)
        self.icon.setToolTip(APP_NAME)
        menu = QMenu()
        self.status = QAction(APP_NAME, menu)
        self.status.setEnabled(False)
        menu.addAction(self.status)
        menu.addSeparator()
        show = QAction(tr("Open the stage desk"), menu)
        bold = QFont(show.font())
        bold.setBold(True)
        show.setFont(bold)                       # what a click on the icon does
        show.triggered.connect(self.openRequested.emit)
        menu.addAction(show)
        bar = QAction(tr("Small bar on top"), menu)
        bar.triggered.connect(self.barRequested.emit)
        menu.addAction(bar)
        menu.addSeparator()
        blackout = QAction(tr("BLACKOUT - every screen to black"), menu)
        blackout.triggered.connect(self.blackoutRequested.emit)
        menu.addAction(blackout)
        stop = QAction(tr("Stop all sound"), menu)
        stop.triggered.connect(self.stopSoundRequested.emit)
        menu.addAction(stop)
        menu.addSeparator()
        leave = QAction(tr("Quit…"), menu)
        leave.triggered.connect(self.quitRequested.emit)
        menu.addAction(leave)
        self.menu = menu                         # the icon does not own its menu
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._on_activated)
        self.icon.show()

    def available(self) -> bool:
        return self.icon is not None

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.openRequested.emit()

    def set_status(self, text: str) -> None:
        """One line on what the stage is doing: the tooltip and the menu's first line."""
        if self.icon is None:
            return
        tip = f"{APP_NAME}\n{text}" if text else APP_NAME
        if self.icon.toolTip() != tip:
            self.icon.setToolTip(tip)
            self.status.setText(text or APP_NAME)

    def notify(self, title: str, message: str) -> None:
        if self.icon is not None:
            self.icon.showMessage(title, message, QSystemTrayIcon.Information, 6000)

    def hide(self) -> None:
        if self.icon is not None:
            self.icon.hide()
