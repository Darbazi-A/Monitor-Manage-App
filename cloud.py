"""
Stage Cloud: this hall on the dashboard that shows every hall - and, when the hall allows
it, run from there, from anywhere.

Paired once (Settings → Cloud: the cloud's address and a code from its dashboard), the
program keeps a WebSocket open to the cloud. Every 30 seconds it says how the hall is doing
(cloud_control.py writes it: the version, the screens and what is on them, the running
order, problems, the computer), and it answers the dashboard: the safe commands - look for
an update, install it, a message for the operator - and, if Settings → Cloud allows it, the
phone page's own requests: the remote desk is the phone remote, over the internet.

The connection comes back by itself (after 3 s, then longer, at most a minute); a hall that
was paired again elsewhere stops trying and says so.

Kept free of main.py imports: the dashboard gives it what to send and what to do.
"""
from __future__ import annotations

import base64
import json
import platform
import threading
import urllib.error
import urllib.request
from typing import Callable

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket, QNetworkRequest
from PySide6.QtWebSockets import QWebSocket

STATUS_MS = 30_000                   # how often the hall says how it is
PING_MS = 25_000                     # keeps proxies from closing a quiet connection
RETRY_MS = (3_000, 6_000, 15_000, 30_000, 60_000)
TIMEOUT_S = 20
TEXT_TYPES = ("application/json", "text/")

OFF, CONNECTING, ONLINE, OFFLINE, UNPAIRED = "off", "connecting", "online", "offline", "unpaired"


def clean_address(text: str) -> str:
    """'stage-cloud.x.workers.dev' -> 'https://stage-cloud.x.workers.dev' (no path, no slash at the end)."""
    text = str(text or "").strip().rstrip("/")
    if text and "://" not in text:
        text = ("http://" if text.startswith(("127.0.0.1", "localhost")) else "https://") + text
    return text


def socket_address(address: str) -> str:
    return address.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/hall/connect"


class CloudLink(QObject):
    stateChanged = Signal()
    paired = Signal(bool, str)                  # ok, message: the answer to pair()
    _answer = Signal(str, object)               # from a worker thread: what, result

    def __init__(self, settings, status: Callable[[], dict], rpc: Callable, command: Callable,
                 parent: QObject = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.status = status                    # () -> dict
        self.rpc = rpc                          # (method, path, params, body: bytes, user) -> (code, bytes, type)
        self.command = command                  # (cmd, args, user) -> (ok, message)
        self.state = OFF
        self.detail = ""
        self._tries = 0
        self.socket = QWebSocket()
        self.socket.connected.connect(self._on_connected)
        self.socket.disconnected.connect(self._on_disconnected)
        self.socket.textMessageReceived.connect(self._on_message)
        self.socket.errorOccurred.connect(self._on_error)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self.send_status)
        self._ping_timer = QTimer(self)
        self._ping_timer.timeout.connect(lambda: self._send({"t": "ping"}))
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self.connect_now)
        self._answer.connect(self._on_answer)

    # -- what is remembered (the registry, like every other setting) ------------------------- #
    def value(self, key: str, default: str = "") -> str:
        return str(self.settings.value("cloud/" + key, default) or default)

    def address(self) -> str:
        return self.value("address")

    def hall_name(self) -> str:
        return self.value("hall")

    def is_paired(self) -> bool:
        return bool(self.value("token"))

    def control_allowed(self) -> bool:
        return self.value("control", "true") == "true"

    def set_control_allowed(self, on: bool) -> None:
        self.settings.setValue("cloud/control", "true" if on else "false")
        self.send_status()

    # -- pairing ------------------------------------------------------------------------------- #
    def pair(self, address: str, code: str) -> None:
        """Pair with a code from the dashboard (in the background); paired(ok, message) answers."""
        address = clean_address(address)
        if not address or not code.strip():
            self.paired.emit(False, "address and code")
            return

        def work() -> None:
            request = urllib.request.Request(
                address + "/hall/pair", method="POST",
                data=json.dumps({"code": code, "computer": platform.node()}).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-SDC-Client": "hall",
                         "User-Agent": "StageDisplayController-cloud"})
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT_S) as answer:
                    result = json.loads(answer.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                try:
                    result = json.loads(error.read().decode("utf-8"))
                except ValueError:
                    result = {"ok": False, "message": f"HTTP {error.code}"}
            except Exception as error:  # noqa: BLE001 - no internet, a wrong address
                result = {"ok": False, "message": str(error) or error.__class__.__name__}
            self._answer.emit("pair", {"address": address, **result})
        threading.Thread(target=work, name="cloud-pair", daemon=True).start()

    def forget(self) -> None:
        """This computer leaves the cloud (the dashboard keeps the hall, ready to pair again)."""
        for key in ("token", "id", "hall"):
            self.settings.remove("cloud/" + key)
        self._stop()
        self._set(OFF)

    # -- the connection ---------------------------------------------------------------------- #
    def start(self) -> None:
        if self.is_paired():
            self.connect_now()

    def connect_now(self) -> None:
        if not self.is_paired():
            return
        self._retry.stop()
        if self.socket.state() != QAbstractSocket.UnconnectedState:
            self.socket.abort()
        request = QNetworkRequest(QUrl(socket_address(self.address())))
        request.setRawHeader(b"Authorization", ("Bearer " + self.value("token")).encode("ascii"))
        request.setRawHeader(b"User-Agent", b"StageDisplayController-cloud")
        self._set(CONNECTING)
        self.socket.open(request)

    def stop(self) -> None:
        self._stop()
        self._set(OFF if not self.is_paired() else OFFLINE, "closed")

    def _stop(self) -> None:
        self._retry.stop()
        self._status_timer.stop()
        self._ping_timer.stop()
        if self.socket.state() != QAbstractSocket.UnconnectedState:
            self.socket.close()

    def _on_connected(self) -> None:
        self._tries = 0
        self._set(ONLINE)
        self.send_status()
        self._status_timer.start(STATUS_MS)
        self._ping_timer.start(PING_MS)

    def _on_disconnected(self) -> None:
        self._status_timer.stop()
        self._ping_timer.stop()
        if not self.is_paired() or self.state in (OFF, UNPAIRED, CONNECTING):
            return                                    # never connected: _on_error looks into it
        if self.socket.closeCode() == 4000:          # another connection with this token took over
            self._set(OFFLINE, "another program connected as this hall")
        self._again()

    def _on_error(self, _error) -> None:
        if self.state == CONNECTING:
            self._check_token()                       # refused: still paired, or paired again elsewhere?

    def _again(self) -> None:
        delay = RETRY_MS[min(self._tries, len(RETRY_MS) - 1)]
        self._tries += 1
        if self.state != OFFLINE:
            self._set(OFFLINE, self.socket.errorString() if self.socket.error() != QAbstractSocket.UnknownSocketError else "")
        self._retry.start(delay)

    def _check_token(self) -> None:
        address, token = self.address(), self.value("token")

        def work() -> None:
            request = urllib.request.Request(address + "/hall/connect",
                                             headers={"Authorization": "Bearer " + token,
                                                      "User-Agent": "StageDisplayController-cloud"})
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT_S):
                    pass
                result = "paired"
            except urllib.error.HTTPError as error:
                result = "unpaired" if error.code == 401 else f"HTTP {error.code}"
            except Exception as error:  # noqa: BLE001
                result = str(error) or error.__class__.__name__
            self._answer.emit("token", result)
        threading.Thread(target=work, name="cloud-check", daemon=True).start()

    def _on_answer(self, what: str, result) -> None:
        if what == "pair":
            if result.get("ok"):
                self.settings.setValue("cloud/address", result["address"])
                self.settings.setValue("cloud/token", result["token"])
                self.settings.setValue("cloud/id", result.get("id", ""))
                self.settings.setValue("cloud/hall", result.get("name", ""))
                self._tries = 0
                self.connect_now()
            self.paired.emit(bool(result.get("ok")), str(result.get("message") or result.get("name") or ""))
        elif what == "token":
            if result == "unpaired":
                self._stop()
                self._set(UNPAIRED, "this hall was paired again on another computer, or removed")
            else:
                self._set(OFFLINE, "" if result == "paired" else result)
                self._again()

    def _set(self, state: str, detail: str = "") -> None:
        if (state, detail) != (self.state, self.detail):
            self.state, self.detail = state, detail
            self.stateChanged.emit()

    # -- talking ------------------------------------------------------------------------------ #
    def _send(self, message: dict) -> bool:
        if self.state != ONLINE:
            return False
        self.socket.sendTextMessage(json.dumps(message, ensure_ascii=False))
        return True

    def send_status(self) -> None:
        if self.state == ONLINE:
            try:
                status = self.status()
            except Exception as error:  # noqa: BLE001 - a status is never worth a crash
                status = {"summary": {"error": str(error)}}
            self._send({"t": "status", "status": status})

    def send_event(self, text: str, level: str = "info") -> None:
        self._send({"t": "event", "level": level, "text": text})

    def _on_message(self, text: str) -> None:
        try:
            message = json.loads(text)
        except ValueError:
            return
        kind = message.get("t")
        if kind == "rpc":
            self._answer_rpc(message)
        elif kind == "cmd":
            try:
                ok, said = self.command(str(message.get("cmd", "")), message.get("args") or {}, str(message.get("user", "")))
            except Exception as error:  # noqa: BLE001
                ok, said = False, str(error)
            self._send({"t": "reply", "id": message.get("id"), "ok": bool(ok), "message": said})

    def _answer_rpc(self, message: dict) -> None:
        body = message.get("body")
        if isinstance(body, dict) and body.get("b64") is not None:
            raw = base64.b64decode(body["b64"])
        else:
            raw = (body or "").encode("utf-8") if isinstance(body, str) else b""
        try:
            code, data, kind = self.rpc(str(message.get("method", "GET")), str(message.get("path", "")),
                                        message.get("params") or {}, raw, str(message.get("user", "")))
        except Exception as error:  # noqa: BLE001
            code, data, kind = 500, json.dumps({"ok": False, "message": str(error)}).encode("utf-8"), "application/json"
        reply = {"t": "reply", "id": message.get("id"), "status": code, "type": kind}
        if kind.startswith(TEXT_TYPES):
            reply["body"] = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
        else:
            reply["b64"] = base64.b64encode(data).decode("ascii")
        self._send(reply)
