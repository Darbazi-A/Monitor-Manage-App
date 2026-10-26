"""
Phone / tablet remote: a small web page served by the app on the local Wi-Fi.

Nothing to install on the phone - open the address in its browser, type the
PIN once, and the running order, BLACKOUT, the sound cues and the presets are
under a thumb. The server is plain QTcpServer on the GUI thread, so every
action runs exactly like a click on the dashboard.

Off until switched on. Every request but the page itself needs the PIN, and an
address that gets it wrong five times is locked out for a minute.

A guest link (/p/<token>, handed out as a QR code) opens the slides page with
nothing but NEXT / BACK: no PIN, no screens, no sound, no running order. A new
guest link retires the old one.
"""
from __future__ import annotations

from i18n import language, tr  # noqa: E402 - the interface's language
import phone_page  # noqa: E402 - the phone's whole-desk page
import remote_ka  # noqa: E402 - the slide clicker's pages in Georgian

import json
import random
import secrets
import time
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QNetworkInterface, QTcpServer, QTcpSocket
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QSpinBox,
                               QVBoxLayout)

from qr import qr_image

DEFAULT_PORT = 8765
MAX_REQUEST = 64 * 1024
GUEST_ACTIONS = ("slide_next", "slide_back", "slide_goto")


def new_pin() -> str:
    return f"{random.SystemRandom().randint(0, 9999):04d}"


def new_guest_token() -> str:
    return secrets.token_urlsafe(9)           # 72 random bits: not guessable


def qr_pixmap(text: str, pixels: int) -> QPixmap:
    return QPixmap.fromImage(qr_image(text, pixels))


def local_addresses() -> List[str]:
    """IPv4 addresses a phone on the same network can reach, likeliest first."""
    found = []
    for interface in QNetworkInterface.allInterfaces():
        flags = interface.flags()
        if not (flags & QNetworkInterface.IsUp) or flags & QNetworkInterface.IsLoopBack:
            continue
        for entry in interface.addressEntries():
            ip = entry.ip()
            if ip.protocol() != QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                continue
            text = ip.toString()
            if text.startswith("169.254."):
                continue                       # no DHCP answer - not reachable
            found.append(text)
    private = [a for a in found if a.startswith(("192.168.", "10.")) or
               (a.startswith("172.") and 16 <= int(a.split(".")[1]) <= 31)]
    return private + [a for a in found if a not in private]


class RemoteServer(QObject):
    """HTTP/1.0-style server: one request per connection, answered and closed."""

    clientsChanged = Signal(int)

    def __init__(self, state: Callable[[], dict], act: Callable[[str, dict], Tuple[bool, str]],
                 parent: Optional[QObject] = None,
                 image: Optional[Callable[[str, int], Optional[bytes]]] = None,
                 screen: Optional[Callable[[str], Optional[bytes]]] = None,
                 get: Optional[Callable[[str, dict], Optional[Tuple[int, bytes, str]]]] = None,
                 upload: Optional["UploadSink"] = None) -> None:
        super().__init__(parent)
        self.state = state
        self.act = act
        self.image = image
        self.screen = screen            # role -> JPEG of that stage screen, for the multiview
        self.get = get                  # other GET /api/... routes: files, thumbnails, the web page
        self.upload = upload            # where files sent from a phone go
        self._uploads: Dict[QTcpSocket, dict] = {}
        self.pin = new_pin()
        self.guest = ""                   # the guest link's token; "" = no guest link
        self.port = DEFAULT_PORT
        self.server: Optional[QTcpServer] = None
        self._buffers: Dict[QTcpSocket, bytes] = {}
        self._failures: Dict[str, Tuple[int, float]] = {}
        self._seen: Dict[str, float] = {}
        self._last_step_action = 0.0
        self._clients = 0
        self._ticker = QTimer(self)
        self._ticker.timeout.connect(self._count_clients)
        self._ticker.start(3000)

    # -- lifecycle ----------------------------------------------------------- #
    @property
    def running(self) -> bool:
        return self.server is not None and self.server.isListening()

    def start(self, port: int, loopback_only: bool = False) -> Optional[str]:
        """Listen; returns an error message, or None when it worked."""
        self.stop()
        server = QTcpServer(self)
        address = QHostAddress(QHostAddress.SpecialAddress.LocalHost if loopback_only
                               else QHostAddress.SpecialAddress.AnyIPv4)
        if not server.listen(address, port):
            message = server.errorString()
            server.deleteLater()
            return message or f"Port {port} is not available."
        server.newConnection.connect(self._on_connection)
        self.server = server
        self.port = port
        return None

    def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            self.server.deleteLater()
            self.server = None
        self._seen.clear()
        self._count_clients()

    def addresses(self) -> List[str]:
        return [f"http://{ip}:{self.port}" for ip in local_addresses()]

    def guest_url(self) -> str:
        addresses = self.addresses()
        base = addresses[0] if addresses else f"http://<this computer>:{self.port}"
        return f"{base}/p/{self.guest}" if self.guest else ""

    def clients(self) -> int:
        return self._clients

    def _count_clients(self) -> None:
        now = time.monotonic()
        self._seen = {ip: t for ip, t in self._seen.items() if now - t < 10}
        if len(self._seen) != self._clients:
            self._clients = len(self._seen)
            self.clientsChanged.emit(self._clients)

    # -- sockets ------------------------------------------------------------- #
    def _on_connection(self) -> None:
        while self.server is not None and self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self._buffers[socket] = b""
            socket.readyRead.connect(lambda s=socket: self._on_ready(s))
            socket.disconnected.connect(lambda s=socket: self._forget(s))
            QTimer.singleShot(10000, lambda s=socket: self._close(s))   # no slow-loris

    def _forget(self, socket: QTcpSocket) -> None:
        self._buffers.pop(socket, None)
        upload = self._uploads.pop(socket, None)
        if upload is not None:
            self._abandon(upload)               # the phone gave up half way
        socket.deleteLater()

    def _close(self, socket: QTcpSocket) -> None:
        if socket in self._buffers:
            socket.abort()

    def _on_ready(self, socket: QTcpSocket) -> None:
        if socket in self._uploads:
            self._on_upload_data(socket)
            return
        if socket not in self._buffers:
            return
        data = self._buffers[socket] + bytes(socket.readAll().data())
        self._buffers[socket] = data
        head, sep, body = data.partition(b"\r\n\r\n")
        if not sep:
            if len(data) > MAX_REQUEST:
                self._send(socket, 413, b"too large", "text/plain")
            return
        if head.startswith(b"POST /api/upload"):
            self._start_upload(socket, head, body)
            return
        if len(data) > MAX_REQUEST:
            self._send(socket, 413, b"too large", "text/plain")
            return
        lines = head.decode("latin-1").split("\r\n")
        try:
            method, target, _version = lines[0].split(" ", 2)
        except ValueError:
            self._send(socket, 400, b"bad request", "text/plain")
            return
        headers = {}
        for line in lines[1:]:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
        length = int(headers.get("content-length", "0") or 0)
        if len(body) < length:
            return                               # wait for the rest
        ip = socket.peerAddress().toString().replace("::ffff:", "")
        path, _, query = target.partition("?")
        from urllib.parse import parse_qsl
        params = dict(parse_qsl(query, keep_blank_values=True))
        status, payload, kind = self._handle(method, path, headers, body[:length], ip, params)
        self._send(socket, status, payload, kind)

    def _send(self, socket: QTcpSocket, status: int, payload: bytes, kind: str) -> None:
        reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
                  413: "Payload Too Large", 429: "Too Many Requests"}.get(status, "OK")
        head = (f"HTTP/1.1 {status} {reason}\r\nContent-Type: {kind}\r\n"
                f"Content-Length: {len(payload)}\r\nCache-Control: no-store\r\n"
                "X-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n").encode("latin-1")
        socket.write(head + payload)
        socket.flush()
        socket.disconnectFromHost()
        self._buffers.pop(socket, None)

    # -- files sent from a phone ---------------------------------------------- #
    # A video can be a gigabyte: it goes straight to disk as it arrives, never into
    # memory, and the connection may take minutes - it is only dropped when nothing
    # has come for half a minute.
    def _start_upload(self, socket: QTcpSocket, head: bytes, body: bytes) -> None:
        self._buffers.pop(socket, None)
        lines = head.decode("latin-1").split("\r\n")
        headers = {}
        for line in lines[1:]:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
        ip = socket.peerAddress().toString().replace("::ffff:", "")
        refused = self._authorise(headers, ip)
        if refused is not None or headers.get("x-guest"):
            status, payload = refused or (403, _json({"ok": False, "message": tr("A guest link only turns slides.")}))
            self._send(socket, status, payload, "application/json")
            return
        if self.upload is None:
            self._send(socket, 404, _json({"ok": False, "message": "no uploads"}), "application/json")
            return
        try:
            length = int(headers.get("content-length", "0") or 0)
        except ValueError:
            length = 0
        from urllib.parse import unquote
        name = unquote(headers.get("x-name", ""))
        ticket, error = self.upload.begin(name, length)
        if ticket is None:
            self._send(socket, 400, _json({"ok": False, "message": error}), "application/json")
            return
        upload = {"ticket": ticket, "left": length, "timer": QTimer(self)}
        upload["timer"].setSingleShot(True)
        upload["timer"].timeout.connect(lambda s=socket: self._upload_stalled(s))
        self._uploads[socket] = upload
        self._write_upload(socket, upload, body)

    def _on_upload_data(self, socket: QTcpSocket) -> None:
        upload = self._uploads.get(socket)
        if upload is not None:
            self._write_upload(socket, upload, bytes(socket.readAll().data()))

    def _write_upload(self, socket: QTcpSocket, upload: dict, chunk: bytes) -> None:
        chunk = chunk[: upload["left"]]
        if chunk:
            error = self.upload.write(upload["ticket"], chunk)
            if error:
                self._uploads.pop(socket, None)
                self._abandon(upload)
                self._send(socket, 500, _json({"ok": False, "message": error}), "application/json")
                return
            upload["left"] -= len(chunk)
        self._seen[socket.peerAddress().toString().replace("::ffff:", "")] = time.monotonic()
        if upload["left"] > 0:
            upload["timer"].start(30000)
            return
        upload["timer"].stop()
        self._uploads.pop(socket, None)
        ok, message, name = self.upload.finish(upload["ticket"])
        self._send(socket, 200, _json({"ok": ok, "message": message, "name": name}), "application/json")

    def _upload_stalled(self, socket: QTcpSocket) -> None:
        upload = self._uploads.pop(socket, None)
        if upload is not None:
            self._abandon(upload)
            socket.abort()

    def _abandon(self, upload: dict) -> None:
        upload["timer"].stop()
        if self.upload is not None:
            self.upload.cancel(upload["ticket"])

    # -- routes -------------------------------------------------------------- #
    def _authorise(self, headers: dict, ip: str):
        """None when the PIN (or a guest link) is right; else (status, payload) to answer with."""
        count, until = self._failures.get(ip, (0, 0.0))
        if until > time.monotonic():
            return 429, _json({"ok": False, "message": tr("Too many wrong PINs - wait a minute.")})
        offered = headers.get("x-guest", "")
        guest = bool(offered) and bool(self.guest) and secrets.compare_digest(offered, self.guest)
        if not guest and not secrets.compare_digest(headers.get("x-pin", ""), self.pin):
            count += 1
            self._failures[ip] = (0, time.monotonic() + 60) if count >= 5 else (count, 0.0)
            message = tr("This guest link has expired.") if offered else tr("Wrong PIN")
            return 401, _json({"ok": False, "message": message})
        self._failures.pop(ip, None)
        self._seen[ip] = time.monotonic()
        return None

    def _handle(self, method: str, path: str, headers: dict, body: bytes, ip: str,
                params: Optional[dict] = None):
        params = params or {}
        if path in ("/", "/index.html"):
            return 200, phone_page.render(language()), "text/html; charset=utf-8"
        if path == "/slides":
            return 200, _page(SLIDES_PAGE, remote_ka.SLIDES_KA), "text/html; charset=utf-8"
        if path == "/manifest.json":
            return 200, MANIFEST.encode("utf-8"), "application/manifest+json"
        if path.startswith("/p/"):
            # the page itself holds nothing; an old link says so instead of asking for a PIN
            if self.guest and path[3:] == self.guest:
                return 200, _page(SLIDES_PAGE, remote_ka.SLIDES_KA), "text/html; charset=utf-8"
            return 200, _page(EXPIRED_PAGE, remote_ka.EXPIRED_KA), "text/html; charset=utf-8"
        if not path.startswith("/api/"):
            return 404, b"not found", "text/plain"

        refused = self._authorise(headers, ip)
        if refused is not None:
            return refused[0], refused[1], "application/json"
        offered = headers.get("x-guest", "")
        guest = bool(offered) and bool(self.guest) and secrets.compare_digest(offered, self.guest)

        if path == "/api/state" and method == "GET":
            if guest:
                return 200, _json({"slides": self.state().get("slides", {}), "guest": True}), "application/json"
            return 200, _json(self.state()), "application/json"
        if path == "/api/screen" and method == "GET" and self.screen is not None:
            if guest:
                return 403, _json({"ok": False, "message": tr("A guest link only turns slides.")}), "application/json"
            data = self.screen(params.get("role", ""))
            if data is None:
                return 404, b"that screen is closed", "text/plain"
            return 200, data, "image/jpeg"
        if path == "/api/slide" and method == "GET" and self.image is not None:
            try:
                data = self.image(params.get("deck", ""), int(params.get("i", "-1")))
            except ValueError:
                data = None
            if data is None:
                return 404, b"no such slide", "text/plain"
            return 200, data, "image/jpeg"
        if path == "/api/action" and method == "POST":
            try:
                data = json.loads(body.decode("utf-8") or "{}")
            except ValueError:
                return 400, _json({"ok": False, "message": "bad JSON"}), "application/json"
            action = str(data.get("action", ""))
            if guest and action not in GUEST_ACTIONS:
                return 403, _json({"ok": False, "message": tr("A guest link only turns slides.")}), "application/json"
            if action in ("next", "back", "slide_next", "slide_back"):
                # a double tap must not skip a step
                now = time.monotonic()
                gap = 0.35 if action.startswith("slide_") else 0.6   # slides are flicked through faster
                if now - self._last_step_action < gap:
                    return 200, _json({"ok": True, "message": tr("ignored double tap")}), "application/json"
                self._last_step_action = now
            ok, message = self.act(action, data)
            return 200, _json({"ok": ok, "message": message}), "application/json"
        if method == "GET" and self.get is not None and not guest:
            answer = self.get(path, params)
            if answer is not None:
                return answer
        return 404, _json({"ok": False, "message": "unknown"}), "application/json"


def _page(page: str, georgian) -> bytes:
    """A phone page in the interface's language."""
    if language() == "ka":
        page = remote_ka.localized(page, georgian)
    return page.encode("utf-8")


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


# --------------------------------------------------------------------------- #
# The dialog on the dashboard
# --------------------------------------------------------------------------- #

class RemoteDialog(QDialog):
    """Switch the remote on, and read off what to type on the phone."""

    toggled = Signal(bool)
    portChanged = Signal(int)
    pinRenewed = Signal()
    qrPinToggled = Signal(bool)
    guestRequested = Signal()

    def __init__(self, server: RemoteServer, theme: dict, parent=None, qr_with_pin: bool = False) -> None:
        super().__init__(parent)
        self.server = server
        self.theme = theme
        self.qr_with_pin = qr_with_pin
        self.setWindowTitle(tr('Phone remote'))
        self.setMinimumWidth(520)
        box = QVBoxLayout(self)
        box.setContentsMargins(22, 20, 22, 20)
        box.setSpacing(12)

        intro = QLabel(tr('The whole stage from a phone or tablet - for a teacher running an event or a rehearsal: the screens, files sent from the phone, the running order (run and build it), presentations, text, sound, scenes, Canva and Kahoot, laptops, a rehearsal, BLACKOUT and Undo. The phone must be on the same Wi-Fi as this computer.'))
        intro.setWordWrap(True)
        intro.setObjectName("cardHint")
        box.addWidget(intro)

        row = QHBoxLayout()
        self.switch = QPushButton()
        self.switch.setCheckable(True)
        self.switch.setMinimumHeight(44)
        self.switch.clicked.connect(lambda on: self.toggled.emit(on))
        row.addWidget(self.switch, 1)
        row.addWidget(QLabel(tr('Port')))
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
        caption = QLabel(tr('ON THE PHONE, OPEN  ·  OR SCAN'))
        caption.setObjectName("sectionTitle")
        left.addWidget(caption)
        self.address = QLabel()
        self.address.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.address.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {theme['accent']};")
        left.addWidget(self.address)

        pin_row = QHBoxLayout()
        caption = QLabel(tr('PIN'))
        caption.setObjectName("sectionTitle")
        pin_row.addWidget(caption)
        self.pin = QLabel()
        self.pin.setStyleSheet("font-size: 30px; font-weight: 800; letter-spacing: 8px;")
        pin_row.addWidget(self.pin)
        pin_row.addStretch(1)
        renew = QPushButton(tr('  New PIN'))
        renew.setToolTip(tr('Phones that know the old PIN will be asked again'))
        renew.clicked.connect(self.pinRenewed.emit)
        pin_row.addWidget(renew)
        left.addLayout(pin_row)
        self.qr_pin_check = QCheckBox(tr('The QR code logs in by itself (no PIN to type)'))
        self.qr_pin_check.setToolTip(tr('Handy for the crew. Anyone with a photo of this QR code can run the show\nuntil you press New PIN - keep it off for codes that leave the desk.'))
        self.qr_pin_check.setChecked(qr_with_pin)
        self.qr_pin_check.toggled.connect(self._on_qr_pin)
        left.addWidget(self.qr_pin_check)
        guest = QPushButton(tr('  Guest slide clicker (QR, slides only)…'))
        guest.setToolTip(tr('A separate QR code for a visiting speaker: next / back slide, nothing else'))
        guest.clicked.connect(self.guestRequested.emit)
        left.addWidget(guest, 0, Qt.AlignLeft)
        left.addStretch(1)
        middle.addLayout(left, 1)
        self.qr = QLabel()
        self.qr.setFixedSize(212, 212)
        self.qr.setAlignment(Qt.AlignCenter)
        self.qr.setObjectName("cardHint")
        middle.addWidget(self.qr, 0, Qt.AlignTop)
        box.addLayout(middle)

        self.status = QLabel()
        self.status.setObjectName("cardHint")
        self.status.setWordWrap(True)
        box.addWidget(self.status)

        note = QLabel(tr('The first time it is switched on, Windows may ask whether Python may use the network: allow it on private networks.'))
        note.setObjectName("keyHint")
        note.setWordWrap(True)
        box.addWidget(note)
        if server.upload is not None:
            folder = server.upload.folder()
            uploads = QLabel(tr('Files sent from phones go to {0}. Only pictures, videos, sounds and presentations are accepted; the phone sees only that folder and the Library\'s folders. Keep the PIN to the people who run the hall.').format(folder))
            uploads.setObjectName("keyHint")
            uploads.setWordWrap(True)
            uploads.setTextInteractionFlags(Qt.TextSelectableByMouse)
            box.addWidget(uploads)

        close = QPushButton(tr('Close'))
        close.clicked.connect(self.accept)
        box.addWidget(close, 0, Qt.AlignRight)
        server.clientsChanged.connect(lambda _n: self.refresh())
        self.refresh()

    def _on_qr_pin(self, on: bool) -> None:
        self.qr_with_pin = on
        self.qrPinToggled.emit(on)
        self.refresh()

    def qr_text(self) -> str:
        """What the QR code holds. The PIN rides in the #fragment, which never leaves the phone."""
        addresses = self.server.addresses()
        if not (self.server.running and addresses):
            return ""
        return addresses[0] + "/" + (f"#pin={self.server.pin}" if self.qr_with_pin else "")

    def refresh(self, error: str = "") -> None:
        on = self.server.running
        self.switch.setChecked(on)
        self.switch.setText(tr('●  Remote is ON  —  tap to switch off') if on else tr('Switch the remote on'))
        self.switch.setObjectName("primary" if not on else "")
        self.switch.style().unpolish(self.switch)
        self.switch.style().polish(self.switch)
        self.port.setEnabled(not on)
        addresses = self.server.addresses() if on else []
        if on and addresses:
            self.address.setText("\n".join(addresses[:2]))
        elif on:
            self.address.setText(tr('http://<this computer>:{0}').format(self.server.port))
        else:
            self.address.setText("—")
        self.pin.setText(self.server.pin if on else "····")
        text = self.qr_text()
        if text:
            self.qr.setPixmap(qr_pixmap(text, 200))
            self.qr.setToolTip(text)
        else:
            self.qr.setPixmap(QPixmap())
            self.qr.setText(tr('QR code\nwhen the\nremote is on'))
        if error:
            self.status.setText(tr('Could not start: {0}').format(error))
            self.status.setStyleSheet(f"color: {self.theme['danger']};")
        elif on:
            count = self.server.clients()
            self.status.setText(tr('{0} phone(s) connected.').format(count) if count else tr('Waiting for a phone…'))
            self.status.setStyleSheet(f"color: {self.theme['ok']};" if count else "")
        else:
            self.status.setText(tr('Off. Nobody can reach the app from the network.'))
            self.status.setStyleSheet("")


class GuestDialog(QDialog):
    """A QR code for a visiting speaker's phone: next / back slide, nothing else."""

    enabledToggled = Signal(bool)
    renewRequested = Signal()

    def __init__(self, server: RemoteServer, theme: dict, parent=None) -> None:
        super().__init__(parent)
        self.server = server
        self.theme = theme
        self.setWindowTitle(tr('Guest slide clicker'))
        self.setMinimumWidth(460)
        box = QVBoxLayout(self)
        box.setContentsMargins(22, 20, 22, 20)
        box.setSpacing(12)

        intro = QLabel(tr('For a guest speaker: they scan this with the phone camera and get NEXT and BACK for the slides - no PIN, and nothing else: no screens, no sound, no running order. The phone must be on the same Wi-Fi as this computer.'))
        intro.setWordWrap(True)
        intro.setObjectName("cardHint")
        box.addWidget(intro)

        self.qr = QLabel()
        self.qr.setFixedSize(340, 340)
        self.qr.setAlignment(Qt.AlignCenter)
        self.qr.setObjectName("cardHint")
        box.addWidget(self.qr, 0, Qt.AlignHCenter)
        self.url = QLabel()
        self.url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.url.setAlignment(Qt.AlignCenter)
        self.url.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {theme['accent']};")
        box.addWidget(self.url)
        self.status = QLabel()
        self.status.setObjectName("cardHint")
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignCenter)
        box.addWidget(self.status)

        row = QHBoxLayout()
        self.switch = QPushButton()
        self.switch.setCheckable(True)
        self.switch.setMinimumHeight(40)
        self.switch.clicked.connect(lambda on: self.enabledToggled.emit(on))
        row.addWidget(self.switch, 1)
        self.renew = QPushButton(tr('  New link'))
        self.renew.setMinimumHeight(40)
        self.renew.setToolTip(tr('A fresh QR code; phones holding the old one are shut out at once'))
        self.renew.clicked.connect(self.renewRequested.emit)
        row.addWidget(self.renew)
        box.addLayout(row)

        close = QPushButton(tr('Close'))
        close.clicked.connect(self.accept)
        box.addWidget(close, 0, Qt.AlignRight)
        server.clientsChanged.connect(lambda _n: self.refresh())
        self.refresh()

    def refresh(self, error: str = "") -> None:
        server = self.server
        on = bool(server.guest)
        self.switch.setChecked(on)
        self.switch.setText(tr('●  Guest link is ON  —  tap to switch off') if on else tr('Make a guest link'))
        self.switch.setObjectName("" if on else "primary")
        self.switch.style().unpolish(self.switch)
        self.switch.style().polish(self.switch)
        self.renew.setEnabled(on)
        url = server.guest_url() if on and server.running else ""
        if url and server.addresses():
            self.qr.setPixmap(qr_pixmap(url, 330))
            self.url.setText(url)
        else:
            self.qr.setPixmap(QPixmap())
            self.qr.setText("—")
            self.url.setText("")
        if error:
            self.status.setText(tr('Could not start the phone remote: {0}').format(error))
            self.status.setStyleSheet(f"color: {self.theme['danger']};")
        elif not on:
            self.status.setText(tr('No guest link: nobody can turn the slides from a phone without the PIN.'))
            self.status.setStyleSheet("")
        elif not server.running:
            self.status.setText(tr('The phone remote is off, so the link does not work yet.'))
            self.status.setStyleSheet(f"color: {self.theme['warn']};")
        elif not server.addresses():
            self.status.setText(tr('This computer is not on a network the phone can reach.'))
            self.status.setStyleSheet(f"color: {self.theme['warn']};")
        else:
            self.status.setText(tr('Slides only. Switch it off or make a new link after the talk.'))
            self.status.setStyleSheet(f"color: {self.theme['ok']};")


# --------------------------------------------------------------------------- #
# The page
# --------------------------------------------------------------------------- #

MANIFEST = json.dumps({
    "name": "Stage remote", "short_name": "Stage", "display": "standalone",
    "background_color": "#0c1018", "theme_color": "#0c1018", "start_url": "/",
})

# The slides-only remote: what a presenter holds when the clicker fails.
SLIDES_PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<meta name="theme-color" content="#0c1018">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<link rel="manifest" href="/manifest.json">
<title>Slides remote</title>
<style>
:root { --bg:#0c1018; --card:#141a26; --well:#0f141e; --edge:#222b3c; --text:#e9edf5; --dim:#9aa6bb;
  --muted:#6c7891; --gold:#e3b23c; --ok:#57c98a; --warn:#d9853f; --red:#e0605c; }
* { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
html,body { margin:0; height:100%; background:var(--bg); color:var(--text);
  font:15px/1.3 "Segoe UI",system-ui,-apple-system,Roboto,sans-serif; overscroll-behavior:none; }
body { display:flex; flex-direction:column; padding:env(safe-area-inset-top) 12px calc(12px + env(safe-area-inset-bottom)); gap:10px; }
button { font:inherit; color:inherit; border:1px solid var(--edge); background:linear-gradient(#212a3a,#182030);
  border-radius:16px; touch-action:manipulation; cursor:pointer; }
button:active { transform:scale(.98); filter:brightness(.85); }
button:disabled { opacity:.35; }
header { display:flex; align-items:center; gap:10px; padding-top:10px; }
header a { color:var(--muted); text-decoration:none; font-size:13px; }
.guest header a, .guest .row { display:none; }
.guest .pad { min-height:220px; }
header h1 { flex:1; font-size:15px; margin:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.pill { font-size:11px; font-weight:800; letter-spacing:1px; padding:4px 10px; border-radius:20px; border:1px solid var(--edge); color:var(--muted); }
.pill.live { color:#ff8c88; border-color:rgba(224,96,92,.6); background:rgba(224,96,92,.15); }
.pill.black { color:var(--warn); border-color:rgba(217,133,63,.6); background:rgba(217,133,63,.15); }
.info { display:flex; align-items:baseline; gap:10px; }
.count { font-size:34px; font-weight:800; font-variant-numeric:tabular-nums; }
.timer { color:var(--dim); font-variant-numeric:tabular-nums; margin-left:auto; }
.slide { position:relative; background:#000; border:1px solid var(--edge); border-radius:14px; overflow:hidden;
  aspect-ratio:16/9; display:grid; place-items:center; color:var(--muted); }
.slide img { width:100%; height:100%; object-fit:contain; display:block; }
.slide.dim img { opacity:.25; }
.nextrow { display:flex; gap:12px; align-items:flex-start; }
.nextrow .nextcol { width:42%; flex:none; }
.nextrow .cap { margin-bottom:4px; }
.nextrow .cap { color:var(--muted); font-size:11px; font-weight:700; letter-spacing:1.2px; }
.notes { color:var(--dim); white-space:pre-wrap; font-size:14px; max-height:4.5em; overflow:auto; }
.pad { flex:1; display:flex; gap:10px; min-height:150px; }
.pad button { font-size:30px; font-weight:800; letter-spacing:2px; }
#back { flex:1; }
#next { flex:2; color:#12161f; background:linear-gradient(#f2c556,var(--gold)); border-color:#c9992f; }
.row { display:flex; gap:10px; }
.row button { flex:1; padding:16px 8px; font-weight:700; }
#black.on { color:var(--warn); border-color:rgba(217,133,63,.6); }
#live.on { color:#ff8c88; border-color:rgba(224,96,92,.55); }
#login { position:fixed; inset:0; background:var(--bg); display:none; flex-direction:column; align-items:center; justify-content:center; gap:18px; z-index:9; }
#login.show { display:flex; }
#pin { font-size:40px; letter-spacing:18px; font-weight:800; min-height:52px; }
.keys { display:grid; grid-template-columns:repeat(3,84px); gap:12px; }
.keys button { height:72px; font-size:26px; font-weight:700; border-radius:50%; }
#msg { color:var(--red); min-height:20px; }
#toast { position:fixed; left:50%; bottom:24px; transform:translateX(-50%); background:#1a2130; border:1px solid #2c3750;
  padding:10px 16px; border-radius:12px; opacity:0; transition:opacity .25s; pointer-events:none; }
#toast.show { opacity:1; }
.empty { text-align:center; color:var(--muted); padding:40px 10px; }
</style></head>
<body>
<header><a href="/">◀ Show</a><h1 id="name">Slides</h1><span class="pill" id="state">—</span></header>
<div class="info"><span class="count" id="count">– / –</span><span class="timer" id="timer"></span></div>
<div class="slide" id="cur">no presentation open</div>
<div class="nextrow"><div class="nextcol"><div class="cap">NEXT</div><div class="slide" id="nxt"></div></div>
  <div style="min-width:0"><div class="cap">NOTES</div><div class="notes" id="notes"></div></div></div>
<div class="pad"><button id="back">◀</button><button id="next">NEXT ▶</button></div>
<div class="row"><button id="black">Black</button><button id="live">Show on screen</button></div>
<div id="login"><div style="color:var(--muted);font-size:12px;font-weight:700;letter-spacing:1.2px">ENTER THE PIN SHOWN ON THE DASHBOARD</div>
  <div id="pin"></div><div class="keys" id="keys"></div><div id="msg"></div></div>
<div id="toast"></div>
<script>
const $ = id => document.getElementById(id);
let pin = localStorage.getItem("stagePin") || "", typed = "", state = null, lastTap = 0, dead = false;
// a guest link (/p/<token>): slides only, no PIN
const GUEST = location.pathname.startsWith("/p/") ? location.pathname.slice(3) : "";
if (GUEST) { document.body.classList.add("guest"); document.title = "Slide clicker";
  const m = document.querySelector('link[rel="manifest"]'); if (m) m.remove(); }
if (/^#pin=\d{4}$/.test(location.hash)) { pin = location.hash.slice(5); localStorage.setItem("stagePin", pin); }
if (location.hash) history.replaceState(null, "", location.pathname);
const images = {};            // "deck:index" -> object URL, fetched with the PIN header
function toast(t) { const e = $("toast"); e.textContent = t; e.classList.add("show"); clearTimeout(e._h); e._h = setTimeout(() => e.classList.remove("show"), 1500); }
function buzz() { if (navigator.vibrate) navigator.vibrate(20); }
function mmss(s) { s = Math.max(0, Math.floor(s)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); }
async function api(path, body) {
  const o = { headers: GUEST ? { "X-Guest": GUEST } : { "X-Pin": pin } };
  if (body) { o.method = "POST"; o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(body); }
  const r = await fetch(path, o);
  if (r.status === 401 && GUEST) { expired(); throw new Error("pin"); }
  if (r.status === 401) { pin = ""; localStorage.removeItem("stagePin"); askPin("Wrong PIN"); throw new Error("pin"); }
  if (r.status === 429) { askPin("Too many tries - wait a minute"); throw new Error("locked"); }
  return r;
}
async function act(action, extra) {
  buzz();
  try { const r = await api("/api/action", Object.assign({ action }, extra || {})); const j = await r.json(); if (j.message) toast(j.message); } catch (e) {}
  refresh();
}
async function image(deck, i) {
  const key = deck + ":" + i;
  if (images[key]) return images[key];
  const r = await api(`/api/slide?deck=${deck}&i=${i}`);
  if (!r.ok) return null;
  images[key] = URL.createObjectURL(await r.blob());
  return images[key];
}
async function put(el, deck, i, dim) {
  if (i < 0 || !state || i >= state.slides.count) { el.innerHTML = i >= 0 ? "<span>end</span>" : ""; return; }
  const want = deck + ":" + i;
  el.classList.toggle("dim", !!dim);
  if (el.dataset.key === want) return;
  el.dataset.key = want;
  const url = await image(deck, i).catch(() => null);
  if (el.dataset.key !== want) return;
  el.innerHTML = url ? `<img src="${url}" alt="">` : "<span>preparing…</span>";
  if (!url) el.dataset.key = "";
}
function askPin(m) { $("login").classList.add("show"); $("msg").textContent = m || ""; typed = ""; drawPin(); }
function expired() {                                   // the desk made a new guest link
  dead = true; $("login").classList.add("show"); $("keys").style.display = "none"; $("pin").textContent = "";
  $("login").firstElementChild.textContent = "THIS CLICKER LINK HAS EXPIRED";
  $("msg").textContent = "Ask the stage desk for the new QR code."; }
function drawPin() { $("pin").textContent = [0, 1, 2, 3].map(i => i < typed.length ? "●" : "·").join(""); }
(function keys() {
  for (const k of ["1","2","3","4","5","6","7","8","9","","0","⌫"]) {
    const b = document.createElement("button"); b.textContent = k; if (!k) b.style.visibility = "hidden";
    b.onclick = () => { buzz(); if (k === "⌫") typed = typed.slice(0, -1); else if (typed.length < 4) typed += k; drawPin();
      if (typed.length === 4) { pin = typed; localStorage.setItem("stagePin", pin); $("login").classList.remove("show"); refresh(); } };
    $("keys").appendChild(b); }
})();
function render() {
  const s = state.slides;
  $("name").textContent = s.loaded ? s.name : "Slides";
  $("count").textContent = s.loaded ? `${s.index + 1} / ${s.count}` : "– / –";
  $("timer").textContent = s.live ? "on screen " + mmss(s.elapsed) : "";
  const pill = $("state");
  pill.textContent = !s.loaded ? "NOTHING OPEN" : s.black ? "BLACK" : s.live ? "LIVE · " + s.target : "NOT ON SCREEN";
  pill.className = "pill " + (s.black ? "black" : s.live ? "live" : "");
  $("notes").textContent = s.notes || "";
  // in PowerPoint the last slide may still have animations to play
  $("next").disabled = !s.loaded || (s.index + 1 >= s.count && !s.black && !s.powerpoint);
  $("back").disabled = !s.loaded || (s.index <= 0 && !s.black);
  $("black").disabled = !s.live;
  $("black").classList.toggle("on", s.black);
  $("black").textContent = s.black ? "Lift black" : "Black";
  $("live").disabled = !s.loaded;
  $("live").classList.toggle("on", s.live);
  $("live").textContent = s.live ? "End presentation" : "Show on screen";
  if (s.loaded) { put($("cur"), s.deck, s.index, s.black); put($("nxt"), s.deck, s.index + 1, false); }
  else { $("cur").textContent = "no presentation open"; $("cur").dataset.key = ""; $("nxt").innerHTML = ""; $("nxt").dataset.key = ""; }
}
async function refresh() {
  if (dead) return;
  if (!pin && !GUEST) { askPin(); return; }
  try { const r = await api("/api/state"); state = await r.json(); render(); } catch (e) {}
}
function guard() { const t = Date.now(); if (t - lastTap < 450) return false; lastTap = t; return true; }
$("next").onclick = () => { if (guard()) act("slide_next"); };
$("back").onclick = () => { if (guard()) act("slide_back"); };
$("black").onclick = () => act("slide_black");
$("live").onclick = () => { if (!state) return;
  if (state.slides.live) { if (confirm("End the presentation and put the background back?")) act("slide_live", { on: false }); }
  else act("slide_live", { on: true }); };
document.addEventListener("keydown", e => {           // a Bluetooth clicker paired to the phone works too
  if (["PageDown","ArrowRight","ArrowDown"," ","Enter"].includes(e.key)) { e.preventDefault(); if (guard()) act("slide_next"); }
  else if (["PageUp","ArrowLeft","ArrowUp","Backspace"].includes(e.key)) { e.preventDefault(); if (guard()) act("slide_back"); }
  else if (!GUEST && (e.key === "b" || e.key === "B" || e.key === ".")) act("slide_black");
});
setInterval(() => { if (!document.hidden) refresh(); }, 700);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
refresh();
</script></body></html>
"""


# What an old guest link shows: no PIN pad, no way in.
EXPIRED_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0c1018"><title>Link expired</title>
<style>
html,body { margin:0; height:100%; background:#0c1018; color:#e9edf5; font:16px/1.4 "Segoe UI",system-ui,-apple-system,Roboto,sans-serif; }
body { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:12px; padding:24px; text-align:center; }
b { color:#e3b23c; font-size:12px; letter-spacing:1.4px; }
p { color:#9aa6bb; margin:0; max-width:320px; }
</style></head>
<body><b>THIS CLICKER LINK HAS EXPIRED</b><p>Ask the stage desk for the new QR code.</p></body></html>
"""
