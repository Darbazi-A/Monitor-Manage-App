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
sound), and an offer waits at the desk. The operator previews it - its picture
plays in the desk's bar, silent, so an open e-mail never reaches the hall - and
TAKEs it: alone on the Main Stage, beside the laptop already there, or small in
its corner. The picture and sound arrive over WebRTC: tens of milliseconds, full
frame rate, the hall's sound system playing the laptop's audio.

Each laptop has a Chromium page of its own; moving from the desk to the stage
moves that page's view, so the connection never restarts.

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

from PySide6.QtCore import QEvent, QObject, QRect, QSize, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPixmap
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
        self.where = ""                 # while live: "preview" (the desk only) or "stage"
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

    def go_live(self, ident: str, answer: str, where: str = "stage") -> bool:
        with self._lock:
            request = self._requests.get(ident)
            if request is None or request.state != "waiting":
                return False
            request.state, request.answer, request.where = "live", answer, where
            self._lock.notify_all()
            return True

    def move(self, ident: str, where: str) -> None:
        """The laptop's picture went from the desk's preview to the stage (or back): the laptop is told."""
        with self._lock:
            request = self._requests.get(ident)
            if request is not None and request.where != where:
                request.where = where
                self._lock.notify_all()

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
            known_where = str(data.get("where", ""))
            deadline = time.monotonic() + POLL_WAIT
            with self._lock:
                request.seen = time.monotonic()
                while request.state == known and request.where == known_where \
                        and time.monotonic() < deadline and self._server is not None:
                    self._lock.wait(min(1.0, deadline - time.monotonic()))
                    request.seen = time.monotonic()
                answer = {"ok": True, "state": request.state, "message": request.message, "where": request.where}
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
# The receiver: one Chromium page per laptop, on the desk or on the stage
# --------------------------------------------------------------------------- #

class ShareLink:
    """One laptop's connection: its own Chromium page, wherever its picture is shown."""

    def __init__(self, view, page) -> None:
        self.id = ""
        self.view = view
        self.page = page
        self.ready = False
        self.queued: List[str] = []
        self.where = ""                 # "preview" (in the desk's bar) or "stage"
        self.state = "connecting"
        self.stats: dict = {}
        self.silenced = False           # the operator muted this laptop
        self.lost_at = 0.0

    def run(self, script: str) -> None:
        if self.ready:
            self.page.runJavaScript(script)
        else:
            self.queued.append(script)


class ShareReceiver(QObject):
    """
    The laptops' pictures. Each has its own page; a preview lives in a frame on
    the desk (silent), and TAKE moves the same view - connection and all - onto
    the Main Stage window, laid out alone, side by side, or one small in the
    other's corner. Ending a share simply uncovers what the stage had.
    """

    answered = Signal(str, str)         # request id, answer SDP
    failed = Signal(str, str)           # request id, why
    stateChanged = Signal(str, str)     # request id, connecting / connected / disconnected / failed / closed
    statsChanged = Signal(str, dict)
    detached = Signal(list)             # ids taken off the stage because its window closed

    MAX_LINKS = 3                       # two on the stage and one being previewed
    PIP_WIDTH = 0.30                    # the small picture, as a share of the stage's width

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.links: Dict[str, ShareLink] = {}
        self.stage: List[str] = []      # on the stage, in layout order (big / left first)
        self.layout = "single"          # single / side / pip
        self.window: Optional[QWidget] = None
        self.volume = 1.0
        self.muted = False              # tests keep the hall quiet
        self._spare: Optional[ShareLink] = None

    def available(self) -> bool:
        try:
            import PySide6.QtWebEngineWidgets  # noqa: F401
            return True
        except ImportError:
            return False

    def warm_up(self) -> None:
        """A page started ahead, so the next laptop does not wait a second or two for Chromium."""
        if self._spare is None and self.available():
            self._spare = self._make_link()

    def _make_link(self) -> ShareLink:
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView

        receiver = self
        view = QWebEngineView()
        view.setAttribute(Qt.WA_ShowWithoutActivating, True)
        view.setFocusPolicy(Qt.NoFocus)
        view.setContextMenuPolicy(Qt.NoContextMenu)
        link = ShareLink(view, None)

        class Page(QWebEnginePage):
            def javaScriptConsoleMessage(self, _level, message, _line, _source):  # noqa: N802
                if message.startswith("SDS:"):
                    kind, _, payload = message[4:].partition(":")
                    try:
                        receiver._from_page(link, kind, json.loads(payload) if payload else None)
                    except ValueError:
                        pass

        page = Page(view)
        link.page = page
        page.setBackgroundColor(QColor("black"))
        settings = page.settings()
        settings.setAttribute(QWebEngineSettings.PlaybackRequiresUserGesture, False)
        settings.setAttribute(QWebEngineSettings.ShowScrollBars, False)
        view.setPage(page)

        def loaded(ok: bool) -> None:
            link.ready = ok
            queued, link.queued = link.queued, []
            for script in queued:
                page.runJavaScript(script)

        view.loadFinished.connect(loaded)
        page.setHtml(RECEIVER_PAGE, QUrl("http://localhost/stage-share"))
        view.hide()
        return link

    # -- connecting ----------------------------------------------------------- #
    def can_connect(self) -> bool:
        return len(self.links) < self.MAX_LINKS

    def receive(self, ident: str, offer: str, host: Optional[QWidget] = None,
                window: Optional[QWidget] = None) -> List[str]:
        """
        Answer this laptop's offer. Its picture goes into `host` (a preview on the
        desk) or, with `window`, straight onto the stage, alone. Returns the ids
        that left the stage for it.
        """
        link = self._spare or self._make_link()
        self._spare = None
        link.id = ident
        link.state = "connecting"
        link.stats = {}
        self.links[ident] = link
        removed: List[str] = []
        if window is not None:
            removed = self._to_stage(link, window, "alone")
        else:
            self._to_host(link, host)
        sound = self._sound(link)
        link.run(f"receive({json.dumps(ident)}, {json.dumps(offer)}, {json.dumps(sound)})")
        QTimer.singleShot(800, self.warm_up)
        return removed

    def _to_host(self, link: ShareLink, host: Optional[QWidget]) -> None:
        link.where = "preview"
        if host is not None:
            link.view.setParent(host)
            link.view.setGeometry(host.rect())
            link.view.show()
        self._apply_sound(link)

    def take(self, ident: str, mode: str, window: QWidget) -> List[str]:
        """
        Put a previewed laptop on the stage: "alone", "side" (beside the one there)
        or "pip" (small, in its corner). Returns the ids that left the stage.
        """
        link = self.links.get(ident)
        if link is None:
            return []
        return self._to_stage(link, window, mode)

    def _to_stage(self, link: ShareLink, window: QWidget, mode: str) -> List[str]:
        self._attach_window(window)
        others = [i for i in self.stage if i != link.id]
        if mode == "alone" or not others:
            removed, self.stage, self.layout = others, [link.id], "single"
        else:
            removed = others[1:]
            self.stage = [others[0], link.id]
            self.layout = "pip" if mode == "pip" else "side"
        for ident in removed:
            if ident in self.links:
                self.links[ident].view.hide()
        link.where = "stage"
        link.view.setParent(window)
        self._apply_sound(link)
        self.relayout()
        return removed

    def drop(self, ident: str) -> None:
        """Close this laptop's connection and put its page away."""
        link = self.links.pop(ident, None)
        if ident in self.stage:
            self.stage.remove(ident)
            if len(self.stage) < 2:
                self.layout = "single"
        if link is not None:
            self._dispose(link, now=False)
        self.relayout()

    def drop_all(self) -> None:
        for ident in list(self.links):
            self.drop(ident)

    def _dispose(self, link: ShareLink, now: bool) -> None:
        from shiboken6 import Shiboken

        view, page = link.view, link.page
        if view is not None and Shiboken.isValid(view):
            view.hide()
            view.setParent(None)
        if now:
            if page is not None and Shiboken.isValid(page):
                Shiboken.delete(page)          # the page before its view
            if view is not None and Shiboken.isValid(view):
                Shiboken.delete(view)
        else:
            if page is not None and Shiboken.isValid(page):
                page.deleteLater()
            if view is not None and Shiboken.isValid(view):
                view.deleteLater()

    def shutdown(self) -> None:
        """Before the app quits: every page goes before its view, all before Chromium's profile."""
        links = list(self.links.values()) + ([self._spare] if self._spare is not None else [])
        self.links.clear()
        self.stage = []
        self._spare = None
        self._attach_window(None)
        for link in links:
            self._dispose(link, now=True)

    # -- the stage's layout ------------------------------------------------------ #
    def _attach_window(self, window: Optional[QWidget]) -> None:
        if self.window is window:
            return
        if self.window is not None:
            self.window.removeEventFilter(self)
        self.window = window
        if window is not None:
            window.installEventFilter(self)

    def set_layout(self, mode: str) -> None:
        if mode in ("side", "pip") and len(self.stage) >= 2:
            self.layout = mode
            self.relayout()

    def swap(self) -> None:
        if len(self.stage) >= 2:
            self.stage.reverse()
            self.relayout()

    def relayout(self) -> None:
        window = self.window
        if window is None:
            return
        width, height = window.width(), window.height()
        ids = [i for i in self.stage if i in self.links]
        places: Dict[str, QRect] = {}
        if len(ids) == 1 or (ids and self.layout == "single"):
            places[ids[0]] = QRect(0, 0, width, height)
        elif len(ids) >= 2 and self.layout == "side":
            half = width // 2
            places[ids[0]] = QRect(0, 0, half, height)
            places[ids[1]] = QRect(half, 0, width - half, height)
        elif len(ids) >= 2:
            places[ids[0]] = QRect(0, 0, width, height)
            small_w = int(width * self.PIP_WIDTH)
            small_h = int(small_w * 9 / 16)
            margin = int(min(width, height) * 0.04)
            places[ids[1]] = QRect(width - small_w - margin, height - small_h - margin, small_w, small_h)
        for ident in ids:
            view = self.links[ident].view
            if ident in places:
                view.setGeometry(places[ident])
                view.show()
            else:
                view.hide()
        for ident in ids:
            self.links[ident].view.raise_()   # the small one ends up on top

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is not self.window:
            return False
        kind = event.type()
        if kind == QEvent.Resize:
            self.relayout()
        elif kind == QEvent.DeferredDelete or (kind == QEvent.Close and getattr(watched, "_allow_close", True)):
            # The stage window is going: take the pictures out first, or Chromium goes down with it.
            gone = list(self.stage)
            for ident in gone:
                self.drop(ident)
            self._attach_window(None)
            if gone:
                self.detached.emit(gone)
        return False

    # -- sound ------------------------------------------------------------------ #
    def _sound(self, link: ShareLink) -> dict:
        """Only a laptop on the stage is heard - and not then if the operator muted it."""
        return {"volume": self.volume, "muted": self.muted or link.where != "stage" or link.silenced}

    def _apply_sound(self, link: ShareLink) -> None:
        sound = self._sound(link)
        link.run(f"setVolume({sound['volume']}, {json.dumps(sound['muted'])})")

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))
        for link in self.links.values():
            self._apply_sound(link)

    def set_silenced(self, ident: str, on: bool) -> None:
        link = self.links.get(ident)
        if link is not None:
            link.silenced = on
            self._apply_sound(link)

    # -- pictures ------------------------------------------------------------------ #
    def on_stage(self, window) -> bool:
        return bool(self.stage) and window is not None and self.window is window

    def snapshot(self) -> QPixmap:
        """The stage's laptops as the hall sees them."""
        window = self.window
        ids = [i for i in self.stage if i in self.links and self.links[i].view.isVisible()]
        if window is None or not ids:
            return QPixmap()
        canvas = QPixmap(window.size())
        canvas.fill(QColor("black"))
        painter = QPainter(canvas)
        for ident in ids:
            view = self.links[ident].view
            painter.drawPixmap(view.geometry().topLeft(), view.grab())
        painter.end()
        return canvas

    def _from_page(self, link: ShareLink, kind: str, data) -> None:
        if not isinstance(data, dict) or not link.id or data.get("id") != link.id:
            return
        if kind == "answer":
            self.answered.emit(link.id, str(data.get("sdp", "")))
        elif kind == "error":
            self.failed.emit(link.id, str(data.get("message", "")))
        elif kind == "state":
            link.state = str(data.get("state", ""))
            self.stateChanged.emit(link.id, link.state)
        elif kind == "stats":
            link.stats = data
            self.statsChanged.emit(link.id, data)


# --------------------------------------------------------------------------- #
# The desk: the bar that asks, previews and shows, and the dialog that switches it on
# --------------------------------------------------------------------------- #

def describe_stats(request: ShareRequest, link: Optional[ShareLink]) -> str:
    stats = link.stats if link is not None else {}
    bits = []
    if stats.get("width"):
        bits.append(f"{stats['width']}×{stats['height']}  ·  {stats.get('fps', 0):.0f} fps")
    elif link is not None:
        bits.append(tr("connecting…"))
    if not request.audio:
        bits.append(tr("no sound shared"))
    elif link is not None and link.where == "stage" and link.state == "connected":
        bits.append(tr("sound arriving") if stats.get("audio") else tr("sound: silent"))
    elif link is not None:
        bits.append(tr("sound waits for TAKE"))
    else:
        bits.append(tr("with sound"))
    return "  ·  ".join(bits)


class ShareChip(QFrame):
    """One laptop in the bar: asking, being previewed, or on the stage."""

    PREVIEW = QSize(224, 126)

    def __init__(self, ident: str, theme: dict) -> None:
        super().__init__()
        self.ident = ident
        self.theme = theme
        self.setObjectName("shareChip")
        self.setStyleSheet(
            f"QFrame#shareChip {{ background: {theme['raised']}; border: 1px solid {theme['edge']}; border-radius: 10px; }}")
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(6)
        self.host = QFrame()
        self.host.setFixedSize(self.PREVIEW)
        self.host.setStyleSheet("background: #000000; border-radius: 6px;")
        box.addWidget(self.host, 0, Qt.AlignHCenter)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.tag = QLabel()
        head.addWidget(self.tag)
        self.name = QLabel()
        self.name.setStyleSheet("font-size: 13px; font-weight: 700;")
        head.addWidget(self.name, 1)
        box.addLayout(head)
        self.detail = QLabel()
        self.detail.setObjectName("cardHint")
        box.addWidget(self.detail)
        self.row = QHBoxLayout()
        self.row.setSpacing(6)
        box.addLayout(self.row)
        self._buttons_key = None
        self.buttons: Dict[str, QPushButton] = {}

    def show_state(self, tag: str, colour: str, name: str, detail: str, preview: bool,
                   buttons: List[tuple]) -> None:
        """buttons: (key, text, objectName, callback, tooltip)"""
        self.tag.setText(tag)
        self.tag.setStyleSheet(f"color: {colour}; font-size: 10px; font-weight: 800; letter-spacing: 0.6px;")
        self.name.setText(name)
        width = (self.PREVIEW.width() if preview else 300) - 4
        self.detail.setText(self.detail.fontMetrics().elidedText(detail, Qt.ElideRight, width))
        self.detail.setToolTip(detail)
        self.host.setVisible(preview)
        key = tuple((b[0], b[1]) for b in buttons)
        if key == self._buttons_key:
            return
        self._buttons_key = key
        while self.row.count():
            item = self.row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()               # off the chip at once, not when the deferred delete runs
                widget.setParent(None)
                widget.deleteLater()
        self.buttons = {}
        for key_name, text, object_name, callback, tooltip in buttons:
            button = QPushButton(text)
            if object_name:
                button.setObjectName(object_name)
            button.setToolTip(tooltip)
            button.clicked.connect(callback)
            self.row.addWidget(button)
            self.buttons[key_name] = button


class ShareBar(QFrame):
    """
    Over every tab while a laptop asks, is previewed or is on the stage: a card
    for each, with the one or two buttons that matter, and - with two on the
    stage - how they share it.
    """

    previewRequested = Signal(str)
    declineRequested = Signal(str)
    takeRequested = Signal(str, str)        # request id, "alone" / "side" / "pip"
    dropRequested = Signal(str)             # end a preview, or take one laptop off the stage
    silenceToggled = Signal(str, bool)
    layoutRequested = Signal(str)
    swapRequested = Signal()
    volumeChanged = Signal(int)

    def __init__(self, icons, theme: dict, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setObjectName("shareBar")
        self.setStyleSheet(
            f"QFrame#shareBar {{ background: {theme['card']}; border: 1px solid {theme['edge']}; border-radius: 12px; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 12, 10)
        row.setSpacing(10)
        caption = QVBoxLayout()
        caption.setSpacing(4)
        icon = QLabel()
        icon.setPixmap(icons.get("monitor", theme["accent"], 20).pixmap(20, 20))
        caption.addWidget(icon)
        title = QLabel(tr("LAPTOPS"))
        title.setObjectName("sectionTitle")
        caption.addWidget(title)
        caption.addStretch(1)
        row.addLayout(caption)
        self.chips_row = QHBoxLayout()
        self.chips_row.setSpacing(10)
        row.addLayout(self.chips_row)
        row.addStretch(1)

        right = QVBoxLayout()
        right.setSpacing(8)
        self.layout_box = QWidget()
        layout_row = QHBoxLayout(self.layout_box)
        layout_row.setContentsMargins(0, 0, 0, 0)
        layout_row.setSpacing(6)
        self.side_btn = QPushButton(tr("Side by side"))
        self.side_btn.setCheckable(True)
        self.side_btn.clicked.connect(lambda: self.layoutRequested.emit("side"))
        layout_row.addWidget(self.side_btn)
        self.pip_btn = QPushButton(tr("Picture in picture"))
        self.pip_btn.setCheckable(True)
        self.pip_btn.clicked.connect(lambda: self.layoutRequested.emit("pip"))
        layout_row.addWidget(self.pip_btn)
        self.swap_btn = QPushButton(tr("  Swap"))
        self.swap_btn.setIcon(icons.get("refresh", theme["text"], 14))
        self.swap_btn.setToolTip(tr("Swap the two laptops' places"))
        self.swap_btn.clicked.connect(self.swapRequested.emit)
        layout_row.addWidget(self.swap_btn)
        right.addWidget(self.layout_box)
        volume_row = QHBoxLayout()
        self.volume_label = QLabel(tr("Sound"))
        self.volume_label.setObjectName("cardHint")
        volume_row.addWidget(self.volume_label)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(160)
        self.volume.setToolTip(tr("The laptops' sound in the hall"))
        self.volume.valueChanged.connect(self.volumeChanged.emit)
        volume_row.addWidget(self.volume)
        right.addLayout(volume_row)
        right.addStretch(1)
        row.addLayout(right)
        self.chips: Dict[str, ShareChip] = {}
        self.preview_first = True
        self.hide()

    def host_for(self, ident: str) -> QFrame:
        return self._chip(ident).host

    def _chip(self, ident: str) -> ShareChip:
        chip = self.chips.get(ident)
        if chip is None:
            chip = ShareChip(ident, self.theme)
            self.chips[ident] = chip
            self.chips_row.addWidget(chip, 0, Qt.AlignTop)
        return chip

    def update_state(self, waiting: List[ShareRequest], links: List[tuple], stage: List[str], layout: str,
                     can_connect: bool) -> None:
        """links: (request, link) for every connected laptop."""
        theme = self.theme
        order: List[str] = []
        on_stage = [(r, l) for r, l in links if l.where == "stage"]
        on_stage.sort(key=lambda pair: stage.index(pair[0].id) if pair[0].id in stage else 99)
        previews = [(r, l) for r, l in links if l.where != "stage"]
        stage_count = len(on_stage)

        for request, link in on_stage:
            order.append(request.id)
            ident = request.id
            silenced = link.silenced
            self._chip(ident).show_state(
                tr("ON STAGE"), theme["danger"], request.name, describe_stats(request, link), False, [
                    ("mute", tr("Unmute") if silenced else tr("Mute"), "",
                     lambda _c=False, i=ident, s=silenced: self.silenceToggled.emit(i, not s),
                     tr("Hear this laptop in the hall, or not")),
                    ("stop", tr("Stop"), "danger", lambda _c=False, i=ident: self.dropRequested.emit(i),
                     tr("Take this laptop off the stage")),
                ])
        for request, link in previews:
            order.append(request.id)
            ident = request.id
            if stage_count == 0:
                buttons = [("alone", tr("TAKE"), "primary",
                            lambda _c=False, i=ident: self.takeRequested.emit(i, "alone"),
                            tr("Put this laptop on the Main Stage"))]
            else:
                buttons = [("alone", tr("TAKE"), "primary",
                            lambda _c=False, i=ident: self.takeRequested.emit(i, "alone"),
                            tr("On the Main Stage instead of what is there")),
                           ("side", tr("Beside"), "", lambda _c=False, i=ident: self.takeRequested.emit(i, "side"),
                            tr("Side by side with the laptop on the stage")),
                           ("pip", tr("Small"), "", lambda _c=False, i=ident: self.takeRequested.emit(i, "pip"),
                            tr("Small, in the corner of the laptop on the stage"))]
            buttons.append(("drop", "✕", "ghost", lambda _c=False, i=ident: self.dropRequested.emit(i),
                            tr("End this preview")))
            self._chip(ident).show_state(tr("PREVIEW"), theme["warn"], request.name,
                                         describe_stats(request, link), True, buttons)
        for request in waiting:
            order.append(request.id)
            ident = request.id
            first = tr("Preview") if self.preview_first else tr("Show on Main Stage")
            hint = tr("See it here first - nothing reaches the stage until TAKE") if self.preview_first \
                else tr("Put it on the Main Stage")
            self._chip(ident).show_state(
                tr("ASKS"), theme["accent"], request.name, f"{request.ip}  ·  " + describe_stats(request, None),
                False, [("preview", first, "primary", lambda _c=False, i=ident: self.previewRequested.emit(i), hint),
                        ("decline", tr("Decline"), "", lambda _c=False, i=ident: self.declineRequested.emit(i),
                         tr("Say no to this laptop"))])
            button = self.chips[ident].buttons.get("preview")
            if button is not None:
                button.setEnabled(can_connect)
                if not can_connect:
                    button.setToolTip(tr("Three laptops are connected - end one first"))

        for ident in [i for i in self.chips if i not in order]:
            chip = self.chips.pop(ident)
            self.chips_row.removeWidget(chip)
            chip.hide()
            chip.deleteLater()
        for index, ident in enumerate(order):
            if self.chips_row.indexOf(self.chips[ident]) != index:
                self.chips_row.removeWidget(self.chips[ident])
                self.chips_row.insertWidget(index, self.chips[ident], 0, Qt.AlignTop)
        self.layout_box.setVisible(stage_count >= 2)
        self.side_btn.setChecked(layout == "side")
        self.pip_btn.setChecked(layout == "pip")
        for widget in (self.volume_label, self.volume):
            widget.setVisible(stage_count >= 1)
        self.setVisible(bool(order))


class ShareDialog(QDialog):
    """Switch the screen share on, and read off what to type on the laptop."""

    toggled = Signal(bool)
    portChanged = Signal(int)
    codeRenewed = Signal()
    autoToggled = Signal(bool)
    previewToggled = Signal(bool)

    def __init__(self, server: ShareServer, theme: dict, parent=None, auto: bool = False,
                 preview: bool = True) -> None:
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
        self.preview_check = QCheckBox(tr("Laptops wait in a preview on the desk until TAKE"))
        self.preview_check.setToolTip(tr("The laptop's picture plays silently in the desk's bar first, so nothing unexpected - an open e-mail, a notification - reaches the hall."))
        self.preview_check.setChecked(preview)
        self.preview_check.toggled.connect(self.previewToggled.emit)
        left.addWidget(self.preview_check)
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
    "The stage desk is looking at your screen - not on the big screen yet.",
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

let pc = null, stream = null, id = "", known = "", where = "", running = false;
function connectedText() {
  if (where === "stage") status("● " + t("You are on the stage screen"), "ok");
  else status(t("The stage desk is looking at your screen - not on the big screen yet."), "wait");
}

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
    if (pc && pc.connectionState === "connected") { connectedText(); tune(kind); }
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
  id = reply.id; known = ""; where = ""; running = true;
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
    try { reply = await post("/api/poll", {id, known, where}); }
    catch (e) {
      if (++misses >= 3) status(t("The stage desk cannot be reached."), "bad");
      await new Promise(r => setTimeout(r, 2000));
      continue;
    }
    misses = 0;
    if (!running) return;
    known = reply.state;
    where = reply.where || "";
    if (reply.state === "waiting") status(t("Waiting for the stage desk to put you on screen…"), "wait");
    else if (reply.state === "live" && reply.sdp) {
      status(t("Connecting…"), "wait");
      try { await pc.setRemoteDescription({type: "answer", sdp: reply.sdp}); }
      catch (e) { status(String(e), "bad"); stop(true); return; }
    } else if (reply.state === "live" && pc && pc.connectionState === "connected") {
      connectedText();
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
