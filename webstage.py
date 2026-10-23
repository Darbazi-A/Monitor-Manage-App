"""
Web pages on the Main Stage: Canva presentations, Kahoot games - anything that
lives in a browser - without a browser window to wrestle onto the right screen.

A page is opened and got ready on the desk first, silent: log in, find the quiz,
press Canva's Present. **Show on the Main Stage** then moves that same page -
login, game and all - onto the Main Stage window, full screen, its sound going
to the hall. While it is there the desk shows a live picture of it that can be
clicked, scrolled and typed on, so Kahoot's Start / Next are pressed from the
desk. The clicker's forward / back reach the page as the arrow keys (Canva's
slides turn). Taking it off the stage brings it back to the desk, still logged
in, still where it was.

Logins are remembered: the pages use their own Chromium profile, kept under the
user's AppData, with cookies kept between runs. Passwords are typed by the
operator into the sites themselves; the app never stores them.

Kept free of main.py imports: the dashboard hands in the stage window.
"""
from __future__ import annotations

from i18n import tr  # noqa: E402 - the interface's language

import json
import os
import re
import subprocess
import time
from typing import List, Optional, Tuple

from PySide6.QtCore import QEvent, QKeyCombination, QObject, QPoint, QPointF, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFocusEvent, QKeyEvent, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from widgets import ElidedLabel

DEFAULT_LINKS: List[Tuple[str, str]] = [
    ("Canva", "https://www.canva.com/"),
    ("Kahoot", "https://create.kahoot.it/"),
]
PROFILE_NAME = "StageDisplayWeb"
MIRROR_MS = 180                 # the desk's live picture of the stage page, about five a second
BOUNCE_S = 0.4                  # a key handed back by the page this soon after we sent it is ours

# Keys a web page should get even though the dashboard has a shortcut for them -
# typing "b" into a login form must not black out the hall. The clicker's keys
# (Page Down / Up) and the sound cues (F1-F8) keep their shortcuts.
_KEEP_SHORTCUT = {Qt.Key_PageDown, Qt.Key_PageUp} | {getattr(Qt, f"Key_F{i}") for i in range(1, 13)}


def normalise_url(text: str) -> str:
    """What the operator typed - "canva.com/design/…", a full address - as an address to open."""
    text = (text or "").strip()
    if not text:
        return ""
    url = QUrl.fromUserInput(text)
    return url.toString() if url.isValid() else ""


def load_links(stored) -> List[Tuple[str, str]]:
    try:
        data = json.loads(stored) if isinstance(stored, str) and stored else None
    except ValueError:
        data = None
    if not isinstance(data, list):
        return list(DEFAULT_LINKS)
    links = []
    for entry in data:
        if isinstance(entry, (list, tuple)) and len(entry) == 2 and all(isinstance(x, str) for x in entry):
            links.append((entry[0], entry[1]))
    return links


def dump_links(links: List[Tuple[str, str]]) -> str:
    return json.dumps([list(entry) for entry in links], ensure_ascii=False)


def _wants_page(event) -> bool:
    """A ShortcutOverride the page should have instead of the dashboard's shortcut."""
    if event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
        return False
    return event.key() not in _KEEP_SHORTCUT


# --------------------------------------------------------------------------- #
# The page and where it is
# --------------------------------------------------------------------------- #

class WebStage(QObject):
    """
    One web page, in one of three places: nowhere (""), the desk ("desk": a
    silent preview the operator works in) or the stage ("stage": filling the
    Main Stage window, heard in the hall, mirrored on the desk).
    """

    changed = Signal()              # place, address, title or loading changed
    detached = Signal()             # the stage window closed under the page: it is back on the desk

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.profile = None
        self.view = None
        self.page = None
        self.where = ""
        self.window: Optional[QWidget] = None
        self.host: Optional["WebHost"] = None
        self.mirror: Optional["WebMirror"] = None
        self.loading = False
        self.progress = 0
        self._filtered: set = set()
        self._delivering = False
        self._sent: dict = {}                       # key -> when it was last handed to the page
        self._stepped_aside: set = set()            # dashboard shortcuts off for a moment (_deliver_key)
        self._restore_shortcuts = QTimer(self)
        self._restore_shortcuts.setSingleShot(True)
        self._restore_shortcuts.timeout.connect(self._shortcuts_back)
        self.shortcut_owner: Optional[QWidget] = None    # the dashboard, whose shortcuts step aside for keys
        self._mirror_timer = QTimer(self)
        self._mirror_timer.timeout.connect(self._refresh_mirror)

    def available(self) -> bool:
        try:
            import PySide6.QtWebEngineWidgets  # noqa: F401
            return True
        except ImportError:
            return False

    # -- building -------------------------------------------------------------- #
    def _ensure(self) -> None:
        if self.view is not None:
            return
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView
        # A profile of its own, kept on disk: Canva and Kahoot stay logged in.
        profile = QWebEngineProfile(PROFILE_NAME, self)
        profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
        # Some sites turn away browsers they do not know; this one is Chromium.
        profile.setHttpUserAgent(re.sub(r"\s*QtWebEngine/\S+", "", profile.httpUserAgent()))
        self.profile = profile

        view = QWebEngineView()
        view.setContextMenuPolicy(Qt.NoContextMenu)
        view.setAttribute(Qt.WA_ShowWithoutActivating, True)

        class Page(QWebEnginePage):
            def createWindow(self, _kind):  # noqa: N802
                # A link that wants a new tab ("Present", "Start") opens here instead.
                spare = QWebEnginePage(self.profile(), self)

                def follow(url: QUrl) -> None:
                    if url.isValid() and not url.isEmpty() and url.scheme() != "about":
                        self.setUrl(url)
                        spare.deleteLater()

                spare.urlChanged.connect(follow)
                return spare

            def javaScriptConsoleMessage(self, *_args):  # noqa: N802
                pass                            # sites are chatty; none of it is ours

        page = Page(profile, view)
        settings = page.settings()
        settings.setAttribute(QWebEngineSettings.PlaybackRequiresUserGesture, False)
        settings.setAttribute(QWebEngineSettings.FullScreenSupportEnabled, True)
        settings.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, True)
        settings.setAttribute(QWebEngineSettings.FocusOnNavigationEnabled, False)
        # Canva's Present asks for full screen: the page already fills its screen
        page.fullScreenRequested.connect(lambda request: request.accept())
        page.setAudioMuted(True)
        page.titleChanged.connect(lambda _title: self.changed.emit())
        page.urlChanged.connect(lambda _url: self.changed.emit())
        page.loadStarted.connect(self._on_load_started)
        page.loadProgress.connect(self._on_load_progress)
        page.loadFinished.connect(self._on_load_finished)
        view.setPage(page)
        self.view, self.page = view, page

    def _on_load_started(self) -> None:
        self.loading, self.progress = True, 0
        self.changed.emit()

    def _on_load_progress(self, value: int) -> None:
        self.progress = value

    def _on_load_finished(self, _ok: bool) -> None:
        self.loading = False
        self._watch_keys()
        self.changed.emit()

    # -- what it shows -------------------------------------------------------------- #
    def is_open(self) -> bool:
        return self.page is not None and self.where != ""

    def on_stage(self, window=None) -> bool:
        return self.where == "stage" and (window is None or self.window is window)

    def title(self) -> str:
        if self.page is None:
            return ""
        title = self.page.title().strip()
        url = self.page.url()
        return title if title and title != url.toString() else url.host()

    def url(self) -> str:
        return self.page.url().toString() if self.page is not None else ""

    def open(self, url: str, host: "WebHost") -> bool:
        """Load an address - into the desk's preview, or where the page already is."""
        url = normalise_url(url)
        if not url or not self.available():
            return False
        self._ensure()
        self.host = host
        if self.where != "stage":
            self._to_desk()
        self.page.load(QUrl(url))
        self.changed.emit()
        return True

    def back(self) -> None:
        if self.page is not None:
            from PySide6.QtWebEngineCore import QWebEnginePage
            self.page.triggerAction(QWebEnginePage.Back)

    def reload(self) -> None:
        if self.page is not None:
            from PySide6.QtWebEngineCore import QWebEnginePage
            self.page.triggerAction(QWebEnginePage.Reload)

    def close(self) -> None:
        """Put the page away (off the stage first). Logins stay."""
        if self.where == "stage":
            self.off_stage()
        if self.page is not None:
            self.page.load(QUrl("about:blank"))
        if self.view is not None:
            self.view.hide()
        self.where = ""
        if self.host is not None:
            self.host.update()
        self.changed.emit()

    # -- the desk --------------------------------------------------------------------- #
    def _to_desk(self) -> None:
        self.where = "desk"
        self._attach_window(None)
        self._mirror_timer.stop()
        if self.mirror is not None:
            self.mirror.hide()
        if self.host is not None:
            self.view.setParent(self.host)
            self._place_on_desk()
            self.view.show()
        else:
            self.view.hide()
            self.view.setParent(None)           # never left behind on a stage window
        self.page.setAudioMuted(True)           # the desk never makes a sound in the hall
        self._watch_keys()

    def _place_on_desk(self) -> None:
        if self.host is None or self.view is None:
            return
        rect = self.host.content_rect()
        self.view.setGeometry(rect)
        # laid out as the stage will see it, only smaller: what is ready here is ready there
        width = max(1, self.stage_size().width())
        self.view.setZoomFactor(max(0.25, min(5.0, rect.width() / width)))
        if self.mirror is not None:
            self.mirror.setGeometry(rect)

    def stage_size(self) -> QSize:
        window = self.window or getattr(self.host, "stage_window", lambda: None)()
        if window is not None and window.width() >= 320 and window.height() >= 180:
            return window.size()
        return QSize(1920, 1080)

    # -- the stage ------------------------------------------------------------------- #
    def to_stage(self, window: QWidget) -> bool:
        if self.page is None or window is None or self.where == "":
            return False
        self._attach_window(window)
        self.where = "stage"
        self.view.setParent(window)
        self.view.setZoomFactor(1.0)
        self.view.setGeometry(QRect(QPoint(0, 0), window.size()))
        self.view.show()
        self.view.raise_()
        self.page.setAudioMuted(False)
        if self.host is not None:
            if self.mirror is None:
                self.mirror = WebMirror(self, self.host)
            self.mirror.setGeometry(self.host.content_rect())
            self.mirror.show()
            self.mirror.raise_()
            self._mirror_timer.start(MIRROR_MS)
        self._watch_keys()
        self.changed.emit()
        return True

    def off_stage(self) -> None:
        """Off the stage, back to the desk - silent, still logged in, still where it was."""
        if self.where != "stage":
            return
        self._to_desk()
        self.changed.emit()

    def snapshot(self) -> QPixmap:
        """The page as the hall sees it."""
        if self.where != "stage" or self.view is None or not self.view.isVisible():
            return QPixmap()
        if self.mirror is not None and self.mirror.isVisible() and not self.mirror.picture.isNull():
            return self.mirror.picture          # taken a moment ago for the desk's mirror
        return self.view.grab()

    def _refresh_mirror(self) -> None:
        if self.mirror is None or not self.mirror.isVisible() or self.where != "stage":
            return
        self.mirror.set_picture(self.view.grab())

    # -- input from the desk to the stage page ----------------------------------------- #
    def _target(self) -> Optional[QWidget]:
        if self.view is None:
            return None
        return self.view.focusProxy() or self.view

    def map_from_mirror(self, point: QPointF) -> QPointF:
        if self.mirror is None or self.view is None or self.mirror.width() <= 0:
            return point
        return QPointF(point.x() * self.view.width() / self.mirror.width(),
                       point.y() * self.view.height() / max(1, self.mirror.height()))

    def send_mouse(self, kind, point: QPointF, button, buttons, modifiers) -> None:
        target = self._target()
        if target is None or self.where != "stage":
            return
        local = self.map_from_mirror(point)
        if kind == QEvent.MouseButtonPress and not target.hasFocus():
            # as for keys: a page that believes itself focused puts the caret where it is clicked
            QApplication.sendEvent(target, QFocusEvent(QEvent.FocusIn, Qt.MouseFocusReason))
        event = QMouseEvent(kind, local, QPointF(target.mapToGlobal(local.toPoint())), button, buttons, modifiers)
        QApplication.sendEvent(target, event)

    def send_wheel(self, event) -> None:
        target = self._target()
        if target is None or self.where != "stage":
            return
        local = self.map_from_mirror(event.position())
        wheel = QWheelEvent(local, QPointF(target.mapToGlobal(local.toPoint())), event.pixelDelta(),
                            event.angleDelta(), event.buttons(), event.modifiers(), event.phase(),
                            event.inverted())
        QApplication.sendEvent(target, wheel)

    def send_key(self, key: int, modifiers=Qt.NoModifier, text: str = "") -> None:
        """A key for the stage page; the desk keeps the keyboard."""
        self._with_focus(lambda: self._deliver_key(key, modifiers, text))

    def press(self, direction: str) -> None:
        """The clicker: "next" / "back" as the arrow keys (Canva turns its slides with them)."""
        self.send_key(Qt.Key_Right if direction == "next" else Qt.Key_Left)

    def _deliver_key(self, key: int, modifiers, text: str) -> None:
        target = self._target()
        if target is None or self._delivering:
            return
        self._delivering = True             # a key the page leaves would climb to the stage window's
        try:                                # clicker routing - and come straight back here
            if not target.hasFocus():
                # Chromium reads keys only in a page it believes focused; the desk keeps the
                # real focus, so the page is told it has it (nothing changes on the stage)
                QApplication.sendEvent(target, QFocusEvent(QEvent.FocusIn, Qt.OtherFocusReason))
            # A made-up key is tried as a shortcut first - and → ← Space B are the
            # dashboard's own. Those step aside while the page has the key, and a moment
            # longer: a key the page does not use comes back up from Chromium, and must
            # not then black out the hall or send the key round again.
            for shortcut in self._shortcuts_for(key, modifiers):
                shortcut.setEnabled(False)
                self._stepped_aside.add(shortcut)
            self._sent[int(key)] = time.monotonic()
            self._restore_shortcuts.start(int(BOUNCE_S * 1000))
            for kind in (QEvent.KeyPress, QEvent.KeyRelease):
                QApplication.sendEvent(target, QKeyEvent(kind, key, modifiers, text))
        finally:
            self._delivering = False

    def _shortcuts_back(self) -> None:
        stepped, self._stepped_aside = self._stepped_aside, set()
        for shortcut in stepped:
            try:
                shortcut.setEnabled(True)
            except RuntimeError:
                pass                            # gone meanwhile

    def _shortcuts_for(self, key: int, modifiers) -> list:
        """The dashboard's enabled shortcuts that this key would fire."""
        if self.shortcut_owner is None:
            return []
        from PySide6.QtGui import QKeySequence, QShortcut
        wanted = QKeySequence(QKeyCombination(Qt.KeyboardModifiers(modifiers), Qt.Key(key)))
        return [s for s in self.shortcut_owner.findChildren(QShortcut)
                if s.isEnabled() and s.key().matches(wanted) == QKeySequence.ExactMatch]

    def _with_focus(self, action) -> None:
        if self._target() is None or self.window is None or self.where != "stage":
            return
        action()

    # -- keys typed into the page itself, on the desk ------------------------------------ #
    def _watch_keys(self) -> None:
        target = self._target()
        if target is not None and id(target) not in self._filtered:
            self._filtered.add(id(target))
            target.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        kind = event.type()
        if kind == QEvent.ShortcutOverride and watched is self._target():
            if _wants_page(event):
                event.accept()                  # typing goes to the page, not to a dashboard shortcut
            return False
        if self.window is not None and watched is self.window:
            if kind in (QEvent.KeyPress, QEvent.KeyRelease) and \
                    time.monotonic() - self._sent.get(int(event.key()), -10.0) < BOUNCE_S:
                # a key the page did not use, handed back up by Chromium: had it reached the
                # stage window's clicker routing it would be sent to the page again, for ever
                return True
            if kind == QEvent.Resize and self.where == "stage" and self.view is not None:
                self.view.setGeometry(QRect(QPoint(0, 0), self.window.size()))
            elif kind == QEvent.DeferredDelete or (kind == QEvent.Close and getattr(watched, "_allow_close", True)):
                # the stage window is going: take the page out first, or Chromium goes down with it
                self._to_desk()
                self.detached.emit()
                self.changed.emit()
            return False
        if self.host is not None and watched is self.host and kind == QEvent.Resize:
            if self.where == "desk":
                self._place_on_desk()
            elif self.mirror is not None:
                self.mirror.setGeometry(self.host.content_rect())
        return False

    def set_host(self, host: "WebHost") -> None:
        self.host = host
        host.installEventFilter(self)

    def _attach_window(self, window: Optional[QWidget]) -> None:
        if self.window is window:
            return
        if self.window is not None:
            try:
                self.window.removeEventFilter(self)
            except RuntimeError:
                pass
        self.window = window
        if window is not None:
            window.installEventFilter(self)

    # -- Edge, for a site that will not work in here ------------------------------------- #
    @staticmethod
    def open_in_edge(url: str, screen_rect: Optional[QRect]) -> Optional[str]:
        """
        Edge as an app window (no address bar), full screen on the Main Stage's
        monitor. Returns an error message, or None. An Edge that is already open
        may put the window where it likes - then drag it across with Win+Shift+→.
        """
        url = normalise_url(url)
        if not url:
            return tr("Type an address first.")
        candidates = [os.path.join(os.environ.get(var, ""), r"Microsoft\Edge\Application\msedge.exe")
                      for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        edge = next((path for path in candidates if os.path.isfile(path)), None)
        if edge is None:
            return tr("Microsoft Edge was not found on this PC.")
        args = [edge, "--new-window", f"--app={url}", "--start-fullscreen"]
        if screen_rect is not None:
            args += [f"--window-position={screen_rect.x()},{screen_rect.y()}",
                     f"--window-size={screen_rect.width()},{screen_rect.height()}"]
        try:
            subprocess.Popen(args, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        except OSError as error:
            return str(error)
        return None

    # -- quitting ------------------------------------------------------------------------ #
    def shutdown(self) -> None:
        """Before the app quits: the page before its view, both before the profile."""
        from shiboken6 import Shiboken

        self._mirror_timer.stop()
        self._attach_window(None)
        page, view = self.page, self.view
        self.page = self.view = None
        self.where = ""
        if view is not None and Shiboken.isValid(view):
            view.hide()
            view.setParent(None)
        if page is not None and Shiboken.isValid(page):
            Shiboken.delete(page)
        if view is not None and Shiboken.isValid(view):
            Shiboken.delete(view)


# --------------------------------------------------------------------------- #
# The desk side
# --------------------------------------------------------------------------- #

class WebHost(QFrame):
    """Where the page lives on the desk - or its live picture, while it is on the stage."""

    def __init__(self, theme: dict, stage_window=lambda: None) -> None:
        super().__init__()
        self.theme = theme
        self.stage_window = stage_window
        self.setObjectName("webHost")
        self.setStyleSheet("QFrame#webHost { background: #05070b; border-radius: 8px; }")
        self.setMinimumSize(480, 270)
        self.placeholder = tr("Open a saved link on the left, or type an address above.")

    def content_rect(self) -> QRect:
        """The biggest rectangle of the stage's shape that fits, centred."""
        window = self.stage_window()
        aspect = (window.width() / window.height()) if window is not None and window.height() > 0 else 16 / 9
        width, height = self.width(), self.height()
        if width / max(1, height) > aspect:
            w = int(height * aspect)
            return QRect((width - w) // 2, 0, w, height)
        h = int(width / aspect)
        return QRect(0, (height - h) // 2, width, h)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if any(child.isVisible() for child in self.children() if isinstance(child, QWidget)):
            return
        p = QPainter(self)
        p.setPen(QColor(self.theme["muted"]))
        p.drawText(self.rect().adjusted(20, 20, -20, -20), Qt.AlignCenter | Qt.TextWordWrap, self.placeholder)


class WebMirror(QWidget):
    """
    The stage page's live picture on the desk. Clicks, the wheel and typing on
    it go to the page on the stage, at the same spot.
    """

    def __init__(self, stage: WebStage, parent: QWidget) -> None:
        super().__init__(parent)
        self.stage = stage
        self.picture = QPixmap()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setCursor(Qt.PointingHandCursor)

    def set_picture(self, pixmap: QPixmap) -> None:
        if not pixmap.isNull():
            self.picture = pixmap
            self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("black"))
        if not self.picture.isNull():
            p.drawPixmap(self.rect(), self.picture)
        p.setPen(QPen(QColor(self.stage_colour()), 3))
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))

    def stage_colour(self) -> str:
        return "#e5484d"

    def event(self, event) -> bool:  # noqa: A003
        if event.type() == QEvent.ShortcutOverride and _wants_page(event):
            event.accept()                      # typed here: for the page on the stage
            return True
        return super().event(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.setFocus(Qt.MouseFocusReason)
        self.stage.send_mouse(QEvent.MouseButtonPress, event.position(), event.button(), event.buttons(),
                              event.modifiers())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.stage.send_mouse(QEvent.MouseButtonRelease, event.position(), event.button(), event.buttons(),
                              event.modifiers())

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.stage.send_mouse(QEvent.MouseButtonDblClick, event.position(), event.button(), event.buttons(),
                              event.modifiers())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self.stage.send_mouse(QEvent.MouseMove, event.position(), Qt.NoButton, event.buttons(), event.modifiers())

    def wheelEvent(self, event) -> None:  # noqa: N802
        self.stage.send_wheel(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        self.stage.send_key(event.key(), event.modifiers(), event.text())


class WebTab(QWidget):
    """The Web page of the desk: saved links, the address, the page, and the stage buttons."""

    stageRequested = Signal()
    offStageRequested = Signal()
    edgeRequested = Signal(str)
    linksChanged = Signal(list)

    def __init__(self, stage: WebStage, icons, theme: dict, links: List[Tuple[str, str]],
                 stage_window=lambda: None) -> None:
        super().__init__()
        self.stage = stage
        self.icons = icons
        self.theme = theme
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(10)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel(tr("Canva, Kahoot and the web"))
        title.setObjectName("pageTitle")
        titles.addWidget(title)
        lead = QLabel(tr("Get it ready here - log in, open the quiz or the presentation; the hall sees and hears "
                         "nothing yet. Then Show on the Main Stage."))
        lead.setObjectName("pageLead")
        lead.setWordWrap(True)
        titles.addWidget(lead)
        outer.addLayout(titles)

        body = QHBoxLayout()
        body.setSpacing(12)

        # saved links
        side = QFrame()
        side.setObjectName("card")
        side.setFixedWidth(280)
        column = QVBoxLayout(side)
        column.setContentsMargins(14, 12, 14, 14)
        column.setSpacing(8)
        head = QHBoxLayout()
        caption = QLabel(tr("SAVED LINKS"))
        caption.setObjectName("sectionTitle")
        head.addWidget(caption)
        head.addStretch(1)
        add = QPushButton()
        add.setObjectName("ghost")
        add.setIcon(icons.get("plus", theme["muted"], 15))
        add.setToolTip(tr("Save a link - the page open now, or an address you type"))
        add.clicked.connect(self._add_link)
        head.addWidget(add)
        remove = QPushButton()
        remove.setObjectName("ghost")
        remove.setIcon(icons.get("minus", theme["muted"], 15))
        remove.setToolTip(tr("Remove the chosen link from the list"))
        remove.clicked.connect(self._remove_link)
        head.addWidget(remove)
        column.addLayout(head)
        self.links = QListWidget()
        self.links.setTextElideMode(Qt.ElideRight)
        self.links.itemActivated.connect(self._open_item)
        self.links.itemClicked.connect(self._open_item)
        column.addWidget(self.links, 1)
        hint = QLabel(tr("A click opens it here, on the desk."))
        hint.setObjectName("cardHint")
        hint.setWordWrap(True)
        column.addWidget(hint)
        body.addWidget(side)

        # the page
        main = QVBoxLayout()
        main.setSpacing(8)
        nav = QHBoxLayout()
        nav.setSpacing(6)
        self.back_btn = QPushButton()
        self.back_btn.setIcon(icons.get("prev", theme["text"], 15))
        self.back_btn.setToolTip(tr("Back to the previous page"))
        self.back_btn.clicked.connect(self.stage.back)
        nav.addWidget(self.back_btn)
        self.reload_btn = QPushButton()
        self.reload_btn.setIcon(icons.get("refresh", theme["text"], 15))
        self.reload_btn.setToolTip(tr("Load the page again"))
        self.reload_btn.clicked.connect(self.stage.reload)
        nav.addWidget(self.reload_btn)
        self.address = QLineEdit()
        self.address.setPlaceholderText(tr("An address - a Canva or Kahoot link, or any web page"))
        self.address.returnPressed.connect(self._open_address)
        nav.addWidget(self.address, 1)
        go = QPushButton(tr("  Open"))
        go.setIcon(icons.get("open", theme["text"], 15))
        go.clicked.connect(self._open_address)
        nav.addWidget(go)
        self.close_btn = QPushButton(tr("  Close"))
        self.close_btn.setIcon(icons.get("close", theme["text"], 15))
        self.close_btn.setToolTip(tr("Put the page away (off the stage first). Logins are kept."))
        self.close_btn.clicked.connect(self._close_page)
        nav.addWidget(self.close_btn)
        main.addLayout(nav)

        self.host = WebHost(theme, stage_window)
        stage.set_host(self.host)
        main.addWidget(self.host, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.state = ElidedLabel("")
        self.state.setObjectName("cardHint")
        actions.addWidget(self.state, 1)
        self.edge_btn = QPushButton(tr("  Open in Edge"))
        self.edge_btn.setIcon(icons.get("monitor", theme["text"], 15))
        self.edge_btn.setToolTip(tr("For a site that does not work in here: Edge, full screen on the Main Stage"))
        self.edge_btn.clicked.connect(lambda: self.edgeRequested.emit(self.address.text() or self.stage.url()))
        actions.addWidget(self.edge_btn)
        self.stage_btn = QPushButton(tr("  Show on the Main Stage"))
        self.stage_btn.setObjectName("primary")
        self.stage_btn.setIcon(icons.get("monitor", theme["ink"], 16))
        self.stage_btn.setMinimumHeight(44)
        self.stage_btn.clicked.connect(self.stageRequested.emit)
        actions.addWidget(self.stage_btn)
        self.off_btn = QPushButton(tr("  Take it off the stage"))
        self.off_btn.setObjectName("danger")
        self.off_btn.setIcon(icons.get("stop", theme["danger"], 16))
        self.off_btn.setMinimumHeight(44)
        self.off_btn.setToolTip(tr("The Main Stage shows its background again; the page comes back here"))
        self.off_btn.clicked.connect(self.offStageRequested.emit)
        actions.addWidget(self.off_btn)
        main.addLayout(actions)
        self.tip = QLabel(tr("On the stage: click, scroll and type on the picture above - it happens on the stage. "
                             "The clicker's forward / back turn Canva's slides."))
        self.tip.setObjectName("cardHint")
        self.tip.setWordWrap(True)
        main.addWidget(self.tip)
        body.addLayout(main, 1)
        outer.addLayout(body, 1)

        self._links: List[Tuple[str, str]] = []
        self.set_links(links)
        stage.changed.connect(self.refresh)
        self.refresh()

    # -- links ------------------------------------------------------------------------ #
    def set_links(self, links: List[Tuple[str, str]]) -> None:
        self._links = list(links)
        self.links.clear()
        for name, url in self._links:
            item = QListWidgetItem(self.icons.get("globe", self.theme["dim"], 15), name)
            item.setData(Qt.UserRole, url)
            item.setToolTip(url)
            self.links.addItem(item)

    def _open_item(self, item: QListWidgetItem) -> None:
        url = item.data(Qt.UserRole)
        if url:
            self.address.setText(url)
            self.open_url(url)

    def _add_link(self) -> None:
        current = self.stage.url() if self.stage.is_open() else ""
        url, ok = QInputDialog.getText(self, tr("Save a link"), tr("Address:"), QLineEdit.Normal,
                                       current or self.address.text())
        url = normalise_url(url) if ok else ""
        if not url:
            return
        name, ok = QInputDialog.getText(self, tr("Save a link"), tr("Name in the list:"), QLineEdit.Normal,
                                        (self.stage.title() if current else "") or QUrl(url).host())
        if not ok:
            return
        self._links.append((name.strip() or QUrl(url).host(), url))
        self.set_links(self._links)
        self.linksChanged.emit(self._links)

    def _remove_link(self) -> None:
        row = self.links.currentRow()
        if 0 <= row < len(self._links):
            del self._links[row]
            self.set_links(self._links)
            self.linksChanged.emit(self._links)

    # -- the page ---------------------------------------------------------------------- #
    def _open_address(self) -> None:
        self.open_url(self.address.text())

    def open_url(self, url: str) -> None:
        if not self.stage.available():
            self.state.setText(tr("This installation of PySide6 has no QtWebEngine."))
            return
        if not self.stage.open(url, self.host):
            self.state.setText(tr("That is not an address that can be opened."))

    def _close_page(self) -> None:
        if self.stage.on_stage():
            self.offStageRequested.emit()
        self.stage.close()

    def refresh(self) -> None:
        stage = self.stage
        open_ = stage.is_open()
        on_stage = stage.where == "stage"
        if open_ and not self.address.hasFocus():
            self.address.setText(stage.url())
        self.back_btn.setEnabled(open_)
        self.reload_btn.setEnabled(open_)
        self.close_btn.setEnabled(open_)
        self.stage_btn.setVisible(not on_stage)
        self.stage_btn.setEnabled(open_)
        self.off_btn.setVisible(on_stage)
        title = stage.title()
        if on_stage:
            self.state.setText(tr("ON THE MAIN STAGE  ·  {0}").format(title))
            self.state.setStyleSheet(f"color: {self.theme['danger']}; font-weight: 700;")
        elif open_:
            loading = tr("  ·  loading…") if stage.loading else ""
            self.state.setText(tr("On the desk only - silent, not on a screen  ·  {0}").format(title) + loading)
            self.state.setStyleSheet("")
        else:
            self.state.setText(tr("Nothing open."))
            self.state.setStyleSheet("")
        self.host.update()
