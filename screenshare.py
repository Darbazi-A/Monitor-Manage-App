"""
Laptop screen share: any laptop on the hall's network shows its screen - and
its sound - on the Main Stage, from a web page. Nothing to install.

    laptop                         this app                          stage
    Chrome / Edge  --HTTPS-->  ShareServer (a thread)  --signal-->  the desk: "Nino wants to share"
      getDisplayMedia               offer / answer                    [Show on Main Stage]
      RTCPeerConnection <======== WebRTC, straight over the LAN ======> ShareReceiver
                                                                      (Chromium, inside the
                                                                       Main Stage window)

The laptop opens https://<this PC>:8443, types the share code shown at the desk
and presses Share: the browser asks which screen (and whether to send its
sound), and an offer waits at the desk. The operator puts it on stage - or the
desk accepts by itself, if told to - and the picture and sound arrive over
WebRTC: tens of milliseconds, full frame rate, the hall's sound system playing
the laptop's audio.

Browsers capture a screen only from HTTPS pages, so the server signs its own
certificate (selfcert.py); a laptop's browser warns about it the first time.
Plain http:// on the same port is answered with a redirect to https://.
"""
from __future__ import annotations

from i18n import language, tr  # noqa: E402 - the interface's language

import json
import os
import random
import re
import secrets
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional

from PySide6.QtCore import QEvent, QObject, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QSpinBox, QVBoxLayout, QWidget)

import selfcert
from remote import local_addresses, qr_pixmap

DEFAULT_SHARE_PORT = 8443
MAX_BODY = 256 * 1024
POLL_WAIT = 20.0            # a laptop's poll is held this long, waiting for news
GONE_AFTER = 30.0           # a laptop that has not polled for this long has left


def new_code() -> str:
    return f"{random.SystemRandom().randint(0, 9999):04d}"


class ShareRequest:
    """One laptop's offer to share, from the moment it asks until it ends."""

    def __init__(self, ident: str, name: str, ip: str, offer: str, audio: bool) -> None:
        self.id = ident
        self.name = name
        self.ip = ip
        self.offer = offer
        self.audio = audio
        self.state = "waiting"          # waiting -> live -> ended, or waiting -> declined
        self.answer = ""
        self.message = ""
        self.seen = time.monotonic()
        self.arrived = time.time()


# --------------------------------------------------------------------------- #
# The server: a thread of its own, so a held poll never stalls the desk
# --------------------------------------------------------------------------- #

class _Handler(BaseHTTPRequestHandler):
    server_version = "StageShare"
    protocol_version = "HTTP/1.0"

    def log_message(self, *_args) -> None:     # the desk has no console to fill
        pass

    def _send(self, status: int, payload: bytes, kind: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] in ("/", "/index.html"):
            self._send(200, share_page().encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > MAX_BODY:
            self._send(413, _json({"ok": False, "message": "too large"}))
            return
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except ValueError:
            self._send(400, _json({"ok": False, "message": "bad JSON"}))
            return
        status, answer = self.server.owner.handle(self.path, data, self.client_address[0])
        self._send(status, _json(answer))


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, context: ssl.SSLContext, owner: "ShareServer") -> None:
        self.context = context
        self.owner = owner
        super().__init__(address, _Handler)

    def finish_request(self, request, client_address) -> None:
        request.settimeout(POLL_WAIT + 15)
        try:
            first = request.recv(1, socket.MSG_PEEK)
        except OSError:
            return
        if first != b"\x16":                     # not a TLS hello: someone typed http://
            self._redirect(request)
            return
        try:
            tls = self.context.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            return                               # a browser refusing the certificate - normal the first time
        try:
            self.RequestHandlerClass(tls, client_address, self)
        finally:
            try:
                tls.close()
            except OSError:
                pass

    def _redirect(self, request) -> None:
        try:
            head = request.recv(4096).decode("latin-1", "replace")
            host = re.search(r"(?im)^host:\s*([^\s:]+)", head)
            target = f"https://{host.group(1) if host else local_addresses()[0]}:{self.server_address[1]}/"
            body = f'<a href="{target}">{target}</a>'.encode("utf-8")
            request.sendall((f"HTTP/1.0 301 Moved Permanently\r\nLocation: {target}\r\n"
                             f"Content-Type: text/html\r\nContent-Length: {len(body)}\r\n\r\n").encode("latin-1")
                            + body)
        except (OSError, IndexError):
            pass


class ShareServer(QObject):
    """The laptops' side of the share: their page, their offers, and what the desk said."""

    requestArrived = Signal(str)        # a laptop asks to go on screen
    requestGone = Signal(str)           # a laptop stopped sharing, or stopped waiting
    _arrived = Signal(str)
    _gone = Signal(str)

    def __init__(self, cert_folder: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.cert_folder = cert_folder
        self.code = new_code()
        self.port = DEFAULT_SHARE_PORT
        self._server: Optional[_Server] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Condition()
        self._requests: Dict[str, ShareRequest] = {}
        self._failures: Dict[str, tuple] = {}
        self._arrived.connect(self.requestArrived.emit, Qt.QueuedConnection)
        self._gone.connect(self.requestGone.emit, Qt.QueuedConnection)
        self._sweeper = QTimer(self)
        self._sweeper.timeout.connect(self._sweep)
        self._sweeper.start(2000)

    # -- lifecycle ----------------------------------------------------------- #
    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self, port: int, loopback_only: bool = False) -> Optional[str]:
        """Listen; returns an error message, or None when it worked."""
        self.stop()
        try:
            cert, key = selfcert.ensure_certificate(self.cert_folder, local_addresses())
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            server = _Server(("127.0.0.1" if loopback_only else "0.0.0.0", port), context, self)
        except OSError as exc:
            return tr("Port {0} is not available.").format(port) if getattr(exc, "winerror", 0) in (10048, 10013) \
                else str(exc)
        except (ssl.SSLError, ValueError) as exc:
            return str(exc)
        self._server = server
        self.port = server.server_address[1]
        self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.3},
                                        name="screen-share", daemon=True)
        self._thread.start()
        return None

    def stop(self) -> None:
        # Tell the laptops first: their held polls answer "ended" before the server goes.
        with self._lock:
            for request in self._requests.values():
                if request.state in ("waiting", "live"):
                    request.state, request.message = "ended", tr("The stage desk switched the screen share off.")
            self._lock.notify_all()
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()

    def addresses(self) -> List[str]:
        return [f"https://{ip}:{self.port}" for ip in local_addresses()]

    def new_code(self) -> str:
        self.code = new_code()
        return self.code

    # -- what the desk sees and does ------------------------------------------ #
    def request(self, ident: str) -> Optional[ShareRequest]:
        with self._lock:
            return self._requests.get(ident)

    def waiting(self) -> List[ShareRequest]:
        with self._lock:
            return sorted((r for r in self._requests.values() if r.state == "waiting"), key=lambda r: r.arrived)

    def go_live(self, ident: str, answer: str) -> bool:
        with self._lock:
            request = self._requests.get(ident)
            if request is None or request.state != "waiting":
                return False
            request.state, request.answer = "live", answer
            self._lock.notify_all()
            return True

    def decline(self, ident: str, message: str = "") -> None:
        self._finish(ident, "declined", message or tr("The stage desk said no this time."))

    def end(self, ident: str, message: str = "") -> None:
        self._finish(ident, "ended", message or tr("The stage desk ended the share."))

    def _finish(self, ident: str, state: str, message: str) -> None:
        with self._lock:
            request = self._requests.get(ident)
            if request is not None and request.state in ("waiting", "live"):
                request.state, request.message = state, message
                self._lock.notify_all()

    def _sweep(self) -> None:
        """Laptops that stopped asking have left; old finished requests are forgotten."""
        now = time.monotonic()
        gone = []
        with self._lock:
            for ident, request in list(self._requests.items()):
                if request.state in ("waiting", "live") and now - request.seen > GONE_AFTER:
                    request.state, request.message = "ended", ""
                    gone.append(ident)
                elif request.state not in ("waiting", "live") and now - request.seen > 120:
                    del self._requests[ident]
        for ident in gone:
            self.requestGone.emit(ident)

    # -- the laptops' requests (server thread) ------------------------------- #
    def handle(self, path: str, data: dict, ip: str):
        if path == "/api/offer":
            count, until = self._failures.get(ip, (0, 0.0))
            if until > time.monotonic():
                return 429, {"ok": False, "message": tr("Too many wrong codes - wait a minute.")}
            if not secrets.compare_digest(str(data.get("code", "")), self.code):
                count += 1
                self._failures[ip] = (0, time.monotonic() + 60) if count >= 5 else (count, 0.0)
                return 401, {"ok": False, "message": tr("Wrong code - it is shown at the stage desk.")}
            self._failures.pop(ip, None)
            offer = str(data.get("sdp", ""))
            if "m=video" not in offer:
                return 400, {"ok": False, "message": "no video in the offer"}
            name = " ".join(str(data.get("name", "")).split())[:60] or tr("A laptop")
            request = ShareRequest(secrets.token_urlsafe(12), name, ip, offer, bool(data.get("audio")))
            with self._lock:
                self._requests[request.id] = request
            self._arrived.emit(request.id)
            return 200, {"ok": True, "id": request.id}
        request = self.request(str(data.get("id", "")))
        if request is None:
            return 404, {"ok": False, "state": "ended", "message": tr("The stage desk no longer knows this share.")}
        if path == "/api/poll":
            known = str(data.get("known", ""))
            deadline = time.monotonic() + POLL_WAIT
            with self._lock:
                request.seen = time.monotonic()
                while request.state == known and time.monotonic() < deadline and self._server is not None:
                    self._lock.wait(min(1.0, deadline - time.monotonic()))
                    request.seen = time.monotonic()
                answer = {"ok": True, "state": request.state, "message": request.message}
                if request.state == "live" and known != "live":
                    answer["sdp"] = request.answer
            return 200, answer
        if path == "/api/stop":
            with self._lock:
                was = request.state
                if was in ("waiting", "live"):
                    request.state, request.message = "ended", ""
                    self._lock.notify_all()
            if was in ("waiting", "live"):
                self._gone.emit(request.id)
            return 200, {"ok": True}
        return 404, {"ok": False, "message": "unknown"}


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


# --------------------------------------------------------------------------- #
# The receiver: Chromium inside the Main Stage window
# --------------------------------------------------------------------------- #

class ShareReceiver(QObject):
    """
    Plays one laptop's stream across a stage window. The page lives in a
    QWebEngineView laid over the window's own picture, so ending the share
    simply uncovers what was there.
    """

    answered = Signal(str, str)         # request id, answer SDP
    failed = Signal(str, str)           # request id, why
    stateChanged = Signal(str)          # connecting / connected / disconnected / failed / closed
    statsChanged = Signal(dict)
    detached = Signal()                 # its stage window closed under a live share

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.view = None
        self.window: Optional[QWidget] = None
        self.current = ""               # the request on screen (or being connected)
        self.muted = False              # tests keep the hall quiet
        self.volume = 1.0
        self.stats: dict = {}
        self.state = "closed"
        self._ready = False
        self._queued: List[str] = []

    def available(self) -> bool:
        try:
            import PySide6.QtWebEngineWidgets  # noqa: F401
            return True
        except ImportError:
            return False

    def warm_up(self) -> None:
        """Start Chromium now, so the first share does not wait a second or two for it."""
        self._ensure_view()

    def _ensure_view(self):
        if self.view is not None:
            return self.view
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView

        receiver = self

        class Page(QWebEnginePage):
            def javaScriptConsoleMessage(self, _level, message, _line, _source):  # noqa: N802
                if message.startswith("SDS:"):
                    kind, _, payload = message[4:].partition(":")
                    try:
                        receiver._from_page(kind, json.loads(payload) if payload else None)
                    except ValueError:
                        pass

        view = QWebEngineView()
        view.setAttribute(Qt.WA_ShowWithoutActivating, True)
        view.setFocusPolicy(Qt.NoFocus)
        view.setContextMenuPolicy(Qt.NoContextMenu)
        page = Page(view)
        page.setBackgroundColor(QColor("black"))
        settings = page.settings()
        settings.setAttribute(QWebEngineSettings.PlaybackRequiresUserGesture, False)
        settings.setAttribute(QWebEngineSettings.ShowScrollBars, False)
        view.setPage(page)
        view.loadFinished.connect(self._on_loaded)
        page.setHtml(RECEIVER_PAGE, QUrl("http://localhost/stage-share"))
        view.hide()
        self.view = view
        return view

    @Slot(bool)
    def _on_loaded(self, ok: bool) -> None:
        self._ready = ok
        queued, self._queued = self._queued, []
        for script in queued:
            self.view.page().runJavaScript(script)

    def _run(self, script: str) -> None:
        if self._ready:
            self.view.page().runJavaScript(script)
        else:
            self._queued.append(script)

    def attach(self, window: Optional[QWidget]) -> None:
        """Lay the picture over this stage window (or take it off, with None)."""
        view = self._ensure_view()
        if self.window is not None:
            self.window.removeEventFilter(self)
        self.window = window
        if window is None:
            view.hide()
            view.setParent(None)
            return
        view.setParent(window)
        view.setGeometry(window.rect())
        window.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is not self.window or self.view is None:
            return False
        kind = event.type()
        if kind == QEvent.Resize:
            self.view.setGeometry(self.window.rect())
        elif kind == QEvent.DeferredDelete or (kind == QEvent.Close and getattr(watched, "_allow_close", True)):
            # The stage window is going: take the picture out first, or Chromium goes down with it.
            self.attach(None)
            if self.current:
                self.stop()
                self.detached.emit()
        return False

    def receive(self, ident: str, offer: str, window: QWidget) -> None:
        """Answer this laptop's offer and show its stream over `window`."""
        self.attach(window)
        self.current = ident
        self.stats = {}
        self.state = "connecting"
        self.view.show()
        self.view.raise_()
        self._run(f"receive({json.dumps(ident)}, {json.dumps(offer)}, "
                  f"{json.dumps({'volume': self.volume, 'muted': self.muted})})")

    def stop(self) -> None:
        self.current = ""
        self.stats = {}
        self.state = "closed"
        if self.view is not None:
            self._run("stop()")
            self.view.hide()

    def shutdown(self) -> None:
        """Before the app quits: the page goes before its view, both before Chromium's profile."""
        self.stop()
        view, self.view = self.view, None
        if view is None:
            return
        if self.window is not None:
            self.window.removeEventFilter(self)
            self.window = None
        from shiboken6 import Shiboken

        page = view.page()
        view.setParent(None)
        if page is not None and Shiboken.isValid(page):
            Shiboken.delete(page)
        if Shiboken.isValid(view):
            Shiboken.delete(view)
        self._ready = False

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))
        if self.view is not None:
            self._run(f"setVolume({self.volume}, {json.dumps(self.muted)})")

    def snapshot(self) -> QPixmap:
        if self.view is None or not self.view.isVisible():
            return QPixmap()
        return self.view.grab()

    def _from_page(self, kind: str, data) -> None:
        if kind == "answer" and isinstance(data, dict):
            if data.get("id") == self.current:
                self.answered.emit(self.current, str(data.get("sdp", "")))
        elif kind == "error" and isinstance(data, dict):
            if data.get("id") == self.current:
                self.failed.emit(self.current, str(data.get("message", "")))
        elif kind == "state" and isinstance(data, dict):
            if data.get("id") == self.current:
                self.state = str(data.get("state", ""))
                self.stateChanged.emit(self.state)
        elif kind == "stats" and isinstance(data, dict):
            if data.get("id") == self.current:
                self.stats = data
                self.statsChanged.emit(data)


# --------------------------------------------------------------------------- #
# The desk: the bar that asks and shows, and the dialog that switches it on
# --------------------------------------------------------------------------- #

class ShareBar(QFrame):
    """
    Across the top of every tab while a laptop waits or is on stage: who it is,
    and the one button that matters.
    """

    acceptRequested = Signal(str)
    declineRequested = Signal(str)
    stopRequested = Signal()
    volumeChanged = Signal(int)
    settingsRequested = Signal()

    def __init__(self, icons, theme: dict, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setObjectName("shareBar")
        self.setStyleSheet(
            f"QFrame#shareBar {{ background: {theme['card']}; border: 1px solid {theme['accent']};"
            " border-radius: 10px; }")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 8, 10, 8)
        row.setSpacing(10)
        self.icon = QLabel()
        self.icon.setPixmap(icons.get("monitor", theme["accent"], 20).pixmap(20, 20))
        row.addWidget(self.icon)
        self.tag = QLabel()
        row.addWidget(self.tag)
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 14px; font-weight: 700;")
        row.addWidget(self.title)
        self.detail = QLabel()
        self.detail.setObjectName("cardHint")
        row.addWidget(self.detail, 1)
        self.volume_label = QLabel(tr("Sound"))
        self.volume_label.setObjectName("cardHint")
        row.addWidget(self.volume_label)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(130)
        self.volume.setToolTip(tr("The laptop's sound in the hall"))
        self.volume.valueChanged.connect(self.volumeChanged.emit)
        row.addWidget(self.volume)
        self.accept_btn = QPushButton(tr("  Show on Main Stage"))
        self.accept_btn.setObjectName("primary")
        self.accept_btn.setIcon(icons.get("play", "#0b0e14", 15))
        self.accept_btn.clicked.connect(lambda: self.acceptRequested.emit(self._ident))
        row.addWidget(self.accept_btn)
        self.decline_btn = QPushButton(tr("Decline"))
        self.decline_btn.clicked.connect(lambda: self.declineRequested.emit(self._ident))
        row.addWidget(self.decline_btn)
        self.stop_btn = QPushButton(tr("  Stop sharing"))
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setIcon(icons.get("stop", theme["danger"], 15))
        self.stop_btn.clicked.connect(self.stopRequested.emit)
        row.addWidget(self.stop_btn)
        self._ident = ""
        self.hide()

    def show_waiting(self, request: ShareRequest, more: int, replacing: str = "") -> None:
        self._ident = request.id
        self.tag.setText(tr("LAPTOP"))
        self.tag.setStyleSheet(f"color: {self.theme['accent']}; font-weight: 800; letter-spacing: 1px;")
        self.title.setText(tr("{0} wants to share their screen").format(request.name))
        bits = [request.ip, tr("with sound") if request.audio else tr("no sound shared")]
        if replacing:
            bits.append(tr("instead of {0}").format(replacing))
        if more:
            bits.append(tr("{0} more waiting").format(more))
        self.detail.setText("  ·  ".join(bits))
        for widget in (self.accept_btn, self.decline_btn):
            widget.show()
        for widget in (self.volume_label, self.volume, self.stop_btn):
            widget.setVisible(bool(replacing))
        self.show()

    def show_live(self, request: ShareRequest, stats: dict, connected: bool) -> None:
        self._ident = request.id
        self.tag.setText(tr("ON MAIN STAGE") if connected else tr("CONNECTING"))
        self.tag.setStyleSheet(f"color: {self.theme['danger'] if connected else self.theme['warn']};"
                               " font-weight: 800; letter-spacing: 1px;")
        self.title.setText(request.name)
        bits = [request.ip]
        if stats.get("width"):
            bits.append(f"{stats['width']}×{stats['height']}  ·  {stats.get('fps', 0):.0f} fps")
        if connected:
            bits.append(tr("sound arriving") if stats.get("audio") else
                        (tr("no sound shared") if not request.audio else tr("sound: silent")))
        self.detail.setText("  ·  ".join(bits))
        for widget in (self.accept_btn, self.decline_btn):
            widget.hide()
        for widget in (self.volume_label, self.volume, self.stop_btn):
            widget.show()
        self.show()


class ShareDialog(QDialog):
    """Switch the screen share on, and read off what to type on the laptop."""

    toggled = Signal(bool)
    portChanged = Signal(int)
    codeRenewed = Signal()
    autoToggled = Signal(bool)

    def __init__(self, server: ShareServer, theme: dict, parent=None, auto: bool = False) -> None:
        super().__init__(parent)
        self.server = server
        self.theme = theme
        self.setWindowTitle(tr("Laptop screen share"))
        self.setMinimumWidth(600)
        box = QVBoxLayout(self)
        box.setContentsMargins(22, 20, 22, 20)
        box.setSpacing(12)

        intro = QLabel(tr("A laptop on the same network shows its screen - with its sound - on the Main Stage. Nothing to install: it opens a page in Chrome or Edge."))
        intro.setWordWrap(True)
        intro.setObjectName("cardHint")
        box.addWidget(intro)

        row = QHBoxLayout()
        self.switch = QPushButton()
        self.switch.setCheckable(True)
        self.switch.setMinimumHeight(44)
        self.switch.clicked.connect(lambda on: self.toggled.emit(on))
        row.addWidget(self.switch, 1)
        row.addWidget(QLabel(tr("Port")))
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(server.port)
        self.port.valueChanged.connect(self.portChanged.emit)
        row.addWidget(self.port)
        box.addLayout(row)

        middle = QHBoxLayout()
        middle.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(10)
        caption = QLabel(tr("ON THE LAPTOP, OPEN"))
        caption.setObjectName("sectionTitle")
        left.addWidget(caption)
        self.address = QLabel()
        self.address.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.address.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {theme['accent']};")
        left.addWidget(self.address)
        code_row = QHBoxLayout()
        caption = QLabel(tr("CODE"))
        caption.setObjectName("sectionTitle")
        code_row.addWidget(caption)
        self.code = QLabel()
        self.code.setStyleSheet("font-size: 30px; font-weight: 800; letter-spacing: 8px;")
        code_row.addWidget(self.code)
        code_row.addStretch(1)
        renew = QPushButton(tr("  New code"))
        renew.setToolTip(tr("Laptops that know the old code will be asked again"))
        renew.clicked.connect(self.codeRenewed.emit)
        code_row.addWidget(renew)
        left.addLayout(code_row)
        self.auto_check = QCheckBox(tr("Put a laptop on stage as soon as it asks (rehearsals)"))
        self.auto_check.setToolTip(tr("Off: the desk shows who is asking, and nothing reaches the stage until you press Show on Main Stage."))
        self.auto_check.setChecked(auto)
        self.auto_check.toggled.connect(self.autoToggled.emit)
        left.addWidget(self.auto_check)
        left.addStretch(1)
        middle.addLayout(left, 1)
        self.qr = QLabel()
        self.qr.setFixedSize(180, 180)
        self.qr.setAlignment(Qt.AlignCenter)
        self.qr.setObjectName("cardHint")
        middle.addWidget(self.qr, 0, Qt.AlignTop)
        box.addLayout(middle)

        steps = QLabel(tr("On the laptop:\n1.  Open the address in Chrome or Edge. The first time, the browser warns that the connection is not private: press Advanced, then Continue - the page comes from this computer.\n2.  Type the code and press Share my screen.\n3.  Choose Entire screen and switch on “Also share system audio” - or choose a tab and “Also share tab audio” - so the hall hears the sound."))
        steps.setWordWrap(True)
        steps.setObjectName("cardHint")
        box.addWidget(steps)

        self.status = QLabel()
        self.status.setObjectName("cardHint")
        self.status.setWordWrap(True)
        box.addWidget(self.status)

        note = QLabel(tr("Windows may ask whether Python may use the network: allow it on private networks. Firefox and Safari share the picture without sound."))
        note.setObjectName("keyHint")
        note.setWordWrap(True)
        box.addWidget(note)

        close = QPushButton(tr("Close"))
        close.clicked.connect(self.accept)
        box.addWidget(close, 0, Qt.AlignRight)
        self.refresh()

    def refresh(self, error: str = "") -> None:
        on = self.server.running
        self.switch.setChecked(on)
        self.switch.setText(tr("●  Screen share is ON  —  tap to switch off") if on else tr("Switch the screen share on"))
        self.switch.setObjectName("primary" if not on else "")
        self.switch.style().unpolish(self.switch)
        self.switch.style().polish(self.switch)
        self.port.setEnabled(not on)
        addresses = self.server.addresses() if on else []
        self.address.setText("\n".join(addresses[:2]) if addresses else ("https://<this computer>:%d" % self.server.port
                                                                           if on else "—"))
        self.code.setText(self.server.code if on else "····")
        if on and addresses:
            self.qr.setPixmap(qr_pixmap(addresses[0] + "/", 170))
            self.qr.setToolTip(addresses[0])
        else:
            self.qr.setPixmap(QPixmap())
            self.qr.setText(tr("QR code\nwhen the\nshare is on"))
        if error:
            self.status.setText(tr("Could not start: {0}").format(error))
            self.status.setStyleSheet(f"color: {self.theme['danger']};")
        elif on:
            self.status.setText(tr("Waiting for a laptop…"))
            self.status.setStyleSheet("")
        else:
            self.status.setText(tr("Off. No laptop can reach the stage."))
            self.status.setStyleSheet("")


# --------------------------------------------------------------------------- #
# The pages
# --------------------------------------------------------------------------- #

PAGE_WORDS = (
    "Share your screen",
    "Show this laptop on the stage screen - picture and sound.",
    "The 4-digit code shown at the stage desk",
    "Your name",
    "e.g. Nino - Grade 11 presentation",
    "What are you showing?",
    "Slides and documents (sharper text)",
    "Video (smoother movement)",
    "Share my screen",
    "In the window that opens, choose Entire screen and switch on “Also share system audio” - or choose a tab and “Also share tab audio” - so the hall hears the sound.",
    "Waiting for the stage desk to put you on screen…",
    "You are on the stage screen",
    "Connecting…",
    "Stop sharing",
    "Share again",
    "Sharing was cancelled.",
    "Connection lost.",
    "No sound is being shared. To send sound, stop and share again with “Also share system audio” (or a tab's audio) switched on.",
    "Sound is shared.",
    "This browser cannot share its screen here. Use Chrome or Edge on a laptop.",
    "The stage desk cannot be reached.",
)


def share_page() -> str:
    """The laptop's page, in the interface's language."""
    words = {english: tr(english) for english in PAGE_WORDS}
    return (SHARE_PAGE.replace("__WORDS__", json.dumps(words, ensure_ascii=False))
            .replace("__LANG__", "ka" if language() == "ka" else "en"))


SHARE_PAGE = r"""<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stage screen share</title>
<style>
:root { --bg:#0b0f1a; --panel:#131a2a; --edge:#26304a; --text:#e8ecf4; --dim:#93a0b8; --gold:#e8b84a;
        --ok:#57c98a; --danger:#e0605c; --warn:#e8a04a; }
* { box-sizing: border-box; }
body { margin:0; min-height:100vh; background:var(--bg); color:var(--text);
       font:16px/1.45 "Segoe UI", system-ui, sans-serif; display:flex; align-items:center; justify-content:center; }
main { width:min(520px, 100% - 32px); margin:32px 0; }
h1 { font-size:26px; margin:0 0 4px; }
.lead { color:var(--dim); margin:0 0 22px; }
.card { background:var(--panel); border:1px solid var(--edge); border-radius:14px; padding:20px; }
label { display:block; font-size:12px; letter-spacing:.5px; color:var(--dim); margin:0 0 6px; }
:lang(en) label { text-transform:uppercase; letter-spacing:1px; }
input, select { width:100%; background:#0b0f1a; color:var(--text); border:1px solid var(--edge); border-radius:9px;
                padding:11px 12px; font:inherit; margin-bottom:16px; }
input:focus, select:focus { outline:none; border-color:var(--gold); }
#code { font-size:28px; letter-spacing:12px; text-align:center; font-weight:700; }
button { width:100%; border:0; border-radius:10px; padding:15px; font:inherit; font-weight:700; font-size:18px; cursor:pointer; }
#share { background:var(--gold); color:#14110a; }
#stop { background:transparent; color:var(--danger); border:1px solid var(--danger); margin-top:14px; display:none; }
button:disabled { opacity:.5; cursor:default; }
.hint { color:var(--dim); font-size:13px; margin:14px 0 0; }
#status { margin:18px 0 0; font-weight:600; min-height:1.4em; }
#status.ok { color:var(--ok); } #status.bad { color:var(--danger); } #status.wait { color:var(--warn); }
#sound { color:var(--dim); font-size:14px; margin-top:6px; }
#sound.bad { color:var(--warn); }
.live { display:flex; align-items:center; gap:10px; }
.dot { width:12px; height:12px; border-radius:50%; background:var(--danger); box-shadow:0 0 12px var(--danger); }
</style>
</head>
<body>
<main>
<h1 data-t="Share your screen"></h1>
<p class="lead" data-t="Show this laptop on the stage screen - picture and sound."></p>
<div class="card">
  <div id="form">
    <label for="code" data-t="The 4-digit code shown at the stage desk"></label>
    <input id="code" inputmode="numeric" maxlength="4" autocomplete="off" placeholder="• • • •">
    <label for="name" data-t="Your name"></label>
    <input id="name" maxlength="60" data-p="e.g. Nino - Grade 11 presentation">
    <label for="kind" data-t="What are you showing?"></label>
    <select id="kind">
      <option value="detail" data-t="Slides and documents (sharper text)"></option>
      <option value="motion" data-t="Video (smoother movement)"></option>
    </select>
  </div>
  <button id="share" data-t="Share my screen"></button>
  <button id="stop" data-t="Stop sharing"></button>
  <div id="status"></div>
  <div id="sound"></div>
  <p class="hint" id="hint" data-t="In the window that opens, choose Entire screen and switch on “Also share system audio” - or choose a tab and “Also share tab audio” - so the hall hears the sound."></p>
</div>
</main>
<script>
const W = __WORDS__;
const t = k => W[k] || k;
const $ = id => document.getElementById(id);
document.querySelectorAll("[data-t]").forEach(e => e.textContent = t(e.dataset.t));
document.querySelectorAll("[data-p]").forEach(e => e.placeholder = t(e.dataset.p));
try { $("name").value = localStorage.getItem("share.name") || ""; $("kind").value = localStorage.getItem("share.kind") || "detail"; } catch (e) {}

let pc = null, stream = null, id = "", known = "", running = false;

function status(text, kind) { $("status").textContent = text || ""; $("status").className = kind || ""; }
function busy(on) {
  $("share").style.display = on ? "none" : "block";
  $("stop").style.display = on ? "block" : "none";
  $("form").style.display = on ? "none" : "block";
}
async function post(path, body) {
  const r = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  let data = {};
  try { data = await r.json(); } catch (e) {}
  data.status = r.status;
  return data;
}
function gathered(peer, ms) {
  return new Promise(done => {
    if (peer.iceGatheringState === "complete") return done();
    const timer = setTimeout(done, ms);
    peer.addEventListener("icegatheringstatechange", () => {
      if (peer.iceGatheringState === "complete") { clearTimeout(timer); done(); }
    });
  });
}

async function share() {
  if (running || pc) return;                 // one share per page
  const code = $("code").value.trim();
  try { localStorage.setItem("share.name", $("name").value); localStorage.setItem("share.kind", $("kind").value); } catch (e) {}
  if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) { status(t("This browser cannot share its screen here. Use Chrome or Edge on a laptop."), "bad"); return; }
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: {frameRate: {ideal: 30, max: 30}, width: {ideal: 1920, max: 1920}, height: {ideal: 1080, max: 1080}},
      audio: {echoCancellation: false, noiseSuppression: false, autoGainControl: false, suppressLocalAudioPlayback: false},
      systemAudio: "include", surfaceSwitching: "include", selfBrowserSurface: "exclude", monitorTypeSurfaces: "include"
    });
  } catch (e) { status(t("Sharing was cancelled."), "bad"); return; }
  const video = stream.getVideoTracks()[0];
  const kind = $("kind").value;
  video.contentHint = kind;
  const audio = stream.getAudioTracks().length > 0;
  $("sound").textContent = audio ? t("Sound is shared.") : t("No sound is being shared. To send sound, stop and share again with “Also share system audio” (or a tab's audio) switched on.");
  $("sound").className = audio ? "" : "bad";
  video.addEventListener("ended", () => stop(true));
  pc = new RTCPeerConnection({iceServers: []});
  // The picture is sent at full size from the first frame: a high bitrate allowed at
  // once, and - for slides and text - the resolution kept even if frames must drop.
  const transceiver = pc.addTransceiver(video, {direction: "sendonly", streams: [stream],
    sendEncodings: [{maxBitrate: kind === "detail" ? 12000000 : 10000000, maxFramerate: 30, scaleResolutionDownBy: 1}]});
  preferCodecs(transceiver, kind === "detail" ? ["video/VP9", "video/VP8"] : ["video/VP8", "video/VP9"]);
  stream.getAudioTracks().forEach(track => pc.addTransceiver(track, {direction: "sendonly", streams: [stream]}));
  pc.addEventListener("connectionstatechange", () => {
    if (pc && pc.connectionState === "connected") { status("● " + t("You are on the stage screen"), "ok"); tune(kind); }
    if (pc && pc.connectionState === "failed") { status(t("Connection lost."), "bad"); stop(true); }
  });
  await pc.setLocalDescription(await pc.createOffer());
  await gathered(pc, 2500);
  busy(true);
  status(t("Connecting…"), "wait");
  let reply;
  try { reply = await post("/api/offer", {code, name: $("name").value, sdp: pc.localDescription.sdp, audio}); }
  catch (e) { status(t("The stage desk cannot be reached."), "bad"); stop(false); return; }
  if (!reply.ok) { status(reply.message || "error", "bad"); stop(false); return; }
  id = reply.id; known = ""; running = true;
  poll();
}

function preferCodecs(transceiver, order) {
  if (!transceiver.setCodecPreferences || !window.RTCRtpSender || !RTCRtpSender.getCapabilities) return;
  const codecs = RTCRtpSender.getCapabilities("video").codecs;
  const rank = c => { const i = order.indexOf(c.mimeType); return i < 0 ? order.length : i; };
  try { transceiver.setCodecPreferences(codecs.slice().sort((a, b) => rank(a) - rank(b))); } catch (e) {}
}

async function tune(kind) {
  const sender = pc.getSenders().find(s => s.track && s.track.kind === "video");
  if (!sender) return;
  const p = sender.getParameters();
  if (!p.encodings || !p.encodings.length) p.encodings = [{}];
  p.encodings[0].maxBitrate = kind === "detail" ? 12000000 : 10000000;
  p.encodings[0].maxFramerate = 30;
  p.encodings[0].scaleResolutionDownBy = 1;
  p.degradationPreference = kind === "detail" ? "maintain-resolution" : "balanced";
  try { await sender.setParameters(p); } catch (e) {}
}

async function poll() {
  let misses = 0;
  while (running) {
    let reply;
    try { reply = await post("/api/poll", {id, known}); }
    catch (e) {
      if (++misses >= 3) status(t("The stage desk cannot be reached."), "bad");
      await new Promise(r => setTimeout(r, 2000));
      continue;
    }
    misses = 0;
    if (!running) return;
    known = reply.state;
    if (reply.state === "waiting") status(t("Waiting for the stage desk to put you on screen…"), "wait");
    else if (reply.state === "live" && reply.sdp) {
      status(t("Connecting…"), "wait");
      try { await pc.setRemoteDescription({type: "answer", sdp: reply.sdp}); }
      catch (e) { status(String(e), "bad"); stop(true); return; }
    } else if (reply.state === "declined" || reply.state === "ended") {
      status(reply.message || t("Connection lost."), reply.state === "ended" && !reply.message ? "" : "bad");
      stop(false);
      return;
    }
  }
}

function stop(tell) {
  if (tell && id) post("/api/stop", {id}).catch(() => {});
  running = false; id = "";
  if (stream) stream.getTracks().forEach(track => track.stop());
  if (pc) pc.close();
  stream = null; pc = null;
  busy(false);
  $("share").textContent = t("Share again");
}

$("share").onclick = share;
$("stop").onclick = () => { status(""); stop(true); };
window.addEventListener("pagehide", () => { if (id) navigator.sendBeacon("/api/stop", JSON.stringify({id})); });
</script>
</body>
</html>
"""

RECEIVER_PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8">
<style>
html, body { margin:0; height:100%; background:#000; overflow:hidden; cursor:none; }
video { width:100%; height:100%; object-fit:contain; background:#000; }
</style></head>
<body><video id="v" autoplay playsinline></video>
<script>
const video = document.getElementById("v");
let pc = null, current = "", timer = null, last = {};
const say = (kind, data) => console.log("SDS:" + kind + ":" + JSON.stringify(data));

function tuneOpus(sdp) {
  const m = sdp.match(/a=rtpmap:(\d+) opus\/48000/i);
  if (!m) return sdp;
  const extra = "stereo=1;sprop-stereo=1;maxaveragebitrate=256000;useinbandfec=1";
  const line = new RegExp("a=fmtp:" + m[1] + " ([^\\r\\n]*)");
  if (line.test(sdp)) return sdp.replace(line, (all, params) => "a=fmtp:" + m[1] + " " + params + ";" + extra);
  return sdp.replace(new RegExp("(a=rtpmap:" + m[1] + " [^\\r\\n]*)"), "$1\r\na=fmtp:" + m[1] + " " + extra);
}
function tuneVideo(sdp) {
  const extra = "x-google-start-bitrate=6000;x-google-min-bitrate=2500;x-google-max-bitrate=12000";
  const types = [...sdp.matchAll(/a=rtpmap:(\d+) (VP8|VP9|AV1)\/90000/gi)].map(m => m[1]);
  for (const pt of types) {
    const line = new RegExp("a=fmtp:" + pt + " ([^\r\n]*)");
    if (line.test(sdp)) sdp = sdp.replace(line, (all, params) => "a=fmtp:" + pt + " " + params + ";" + extra);
    else sdp = sdp.replace(new RegExp("(a=rtpmap:" + pt + " [^\r\n]*)"), "$1\r\na=fmtp:" + pt + " " + extra);
  }
  return sdp;
}
function gathered(peer, ms) {
  return new Promise(done => {
    if (peer.iceGatheringState === "complete") return done();
    const t = setTimeout(done, ms);
    peer.addEventListener("icegatheringstatechange", () => {
      if (peer.iceGatheringState === "complete") { clearTimeout(t); done(); }
    });
  });
}
async function receive(id, sdp, opts) {
  stop();
  current = id;
  setVolume(opts.volume, opts.muted);
  try {
    pc = new RTCPeerConnection({iceServers: []});
    const peer = pc;
    const media = new MediaStream();
    video.srcObject = media;
    peer.ontrack = e => {
      media.addTrack(e.track);
      try { e.receiver.playoutDelayHint = 0.05; } catch (err) {}
      video.play().catch(err => say("error", {id, message: String(err)}));
    };
    peer.onconnectionstatechange = () => { if (peer === pc) say("state", {id, state: peer.connectionState}); };
    await peer.setRemoteDescription({type: "offer", sdp});
    const answer = await peer.createAnswer();
    answer.sdp = tuneVideo(tuneOpus(answer.sdp));
    await peer.setLocalDescription(answer);
    await gathered(peer, 2500);
    if (peer !== pc) return;
    say("answer", {id, sdp: peer.localDescription.sdp});
    last = {};
    timer = setInterval(stats, 1000);
  } catch (err) {
    say("error", {id, message: String(err)});
  }
}
async function stats() {
  if (!pc) return;
  const report = await pc.getStats();
  const out = {id: current, fps: 0, width: 0, height: 0, kbps: 0, audioKbps: 0, audio: false, level: 0};
  let bytes = 0, audioBytes = 0;
  report.forEach(s => {
    if (s.type !== "inbound-rtp") return;
    if (s.kind === "video") {
      out.fps = s.framesPerSecond || 0; out.width = s.frameWidth || 0; out.height = s.frameHeight || 0;
      bytes += s.bytesReceived || 0;
    } else if (s.kind === "audio") {
      audioBytes = s.bytesReceived || 0;
      out.level = s.audioLevel || 0;
      out.energy = s.totalAudioEnergy || 0;
    }
  });
  const now = performance.now();
  if (last.t) {
    out.kbps = Math.round((bytes - last.bytes) * 8 / (now - last.t));
    out.audioKbps = Math.round((audioBytes - last.audioBytes) * 8 / (now - last.t));
    // something audible: the level is only measured while the sound is played (not muted)
    out.audio = out.audioKbps > 0 && (out.energy || 0) - (last.energy || 0) > 1e-6;
  }
  last = {t: now, bytes, audioBytes, energy: out.energy || 0};
  say("stats", out);
}
function stop() {
  if (timer) clearInterval(timer);
  timer = null;
  if (pc) pc.close();
  pc = null; current = "";
  if (video.srcObject) video.srcObject.getTracks().forEach(t => t.stop());
  video.srcObject = null;
}
function setVolume(volume, muted) { video.volume = volume; video.muted = !!muted; }
</script></body></html>
"""
