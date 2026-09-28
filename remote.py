"""
Phone / tablet remote: a small web page served by the app on the local Wi-Fi.

Nothing to install on the phone - open the address in its browser, type the
PIN once, and the running order, BLACKOUT, the sound cues and the presets are
under a thumb. The server is plain QTcpServer on the GUI thread, so every
action runs exactly like a click on the dashboard.

Off until switched on. Every request but the page itself needs the PIN, and an
address that gets it wrong five times is locked out for a minute.
"""
from __future__ import annotations

import json
import random
import time
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QNetworkInterface, QTcpServer, QTcpSocket
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout)

DEFAULT_PORT = 8765
MAX_REQUEST = 64 * 1024


def new_pin() -> str:
    return f"{random.SystemRandom().randint(0, 9999):04d}"


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
                 image: Optional[Callable[[str, int], Optional[bytes]]] = None) -> None:
        super().__init__(parent)
        self.state = state
        self.act = act
        self.image = image
        self.pin = new_pin()
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
        socket.deleteLater()

    def _close(self, socket: QTcpSocket) -> None:
        if socket in self._buffers:
            socket.abort()

    def _on_ready(self, socket: QTcpSocket) -> None:
        if socket not in self._buffers:
            return
        data = self._buffers[socket] + bytes(socket.readAll().data())
        self._buffers[socket] = data
        if len(data) > MAX_REQUEST:
            self._send(socket, 413, b"too large", "text/plain")
            return
        head, sep, body = data.partition(b"\r\n\r\n")
        if not sep:
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
        params = dict(part.partition("=")[::2] for part in query.split("&") if part)
        status, payload, kind = self._handle(method, path, headers, body[:length], ip, params)
        self._send(socket, status, payload, kind)

    def _send(self, socket: QTcpSocket, status: int, payload: bytes, kind: str) -> None:
        reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 404: "Not Found",
                  413: "Payload Too Large", 429: "Too Many Requests"}.get(status, "OK")
        head = (f"HTTP/1.1 {status} {reason}\r\nContent-Type: {kind}\r\n"
                f"Content-Length: {len(payload)}\r\nCache-Control: no-store\r\n"
                "X-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n").encode("latin-1")
        socket.write(head + payload)
        socket.flush()
        socket.disconnectFromHost()
        self._buffers.pop(socket, None)

    # -- routes -------------------------------------------------------------- #
    def _handle(self, method: str, path: str, headers: dict, body: bytes, ip: str,
                params: Optional[dict] = None):
        params = params or {}
        if path in ("/", "/index.html"):
            return 200, PAGE.encode("utf-8"), "text/html; charset=utf-8"
        if path == "/slides":
            return 200, SLIDES_PAGE.encode("utf-8"), "text/html; charset=utf-8"
        if path == "/manifest.json":
            return 200, MANIFEST.encode("utf-8"), "application/manifest+json"
        if not path.startswith("/api/"):
            return 404, b"not found", "text/plain"

        count, until = self._failures.get(ip, (0, 0.0))
        if until > time.monotonic():
            return 429, _json({"ok": False, "message": "Too many wrong PINs - wait a minute."}), "application/json"
        if headers.get("x-pin", "") != self.pin:
            count += 1
            self._failures[ip] = (0, time.monotonic() + 60) if count >= 5 else (count, 0.0)
            return 401, _json({"ok": False, "message": "Wrong PIN"}), "application/json"
        self._failures.pop(ip, None)
        self._seen[ip] = time.monotonic()

        if path == "/api/state" and method == "GET":
            return 200, _json(self.state()), "application/json"
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
            if action in ("next", "back", "slide_next", "slide_back"):
                # a double tap must not skip a step
                now = time.monotonic()
                gap = 0.35 if action.startswith("slide_") else 0.6   # slides are flicked through faster
                if now - self._last_step_action < gap:
                    return 200, _json({"ok": True, "message": "ignored double tap"}), "application/json"
                self._last_step_action = now
            ok, message = self.act(action, data)
            return 200, _json({"ok": ok, "message": message}), "application/json"
        return 404, _json({"ok": False, "message": "unknown"}), "application/json"


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

    def __init__(self, server: RemoteServer, theme: dict, parent=None) -> None:
        super().__init__(parent)
        self.server = server
        self.theme = theme
        self.setWindowTitle("Phone remote")
        self.setMinimumWidth(520)
        box = QVBoxLayout(self)
        box.setContentsMargins(22, 20, 22, 20)
        box.setSpacing(12)

        intro = QLabel("Run the show from a phone or tablet: NEXT, BACK, BLACKOUT, the sound cues "
                       "and the presets. The phone must be on the same Wi-Fi as this computer.")
        intro.setWordWrap(True)
        intro.setObjectName("cardHint")
        box.addWidget(intro)

        row = QHBoxLayout()
        self.switch = QPushButton()
        self.switch.setCheckable(True)
        self.switch.setMinimumHeight(44)
        self.switch.clicked.connect(lambda on: self.toggled.emit(on))
        row.addWidget(self.switch, 1)
        row.addWidget(QLabel("Port"))
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(server.port)
        self.port.valueChanged.connect(self.portChanged.emit)
        row.addWidget(self.port)
        box.addLayout(row)

        caption = QLabel("ON THE PHONE, OPEN")
        caption.setObjectName("sectionTitle")
        box.addWidget(caption)
        self.address = QLabel()
        self.address.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.address.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {theme['accent']};")
        box.addWidget(self.address)

        pin_row = QHBoxLayout()
        caption = QLabel("PIN")
        caption.setObjectName("sectionTitle")
        pin_row.addWidget(caption)
        self.pin = QLabel()
        self.pin.setStyleSheet("font-size: 30px; font-weight: 800; letter-spacing: 8px;")
        pin_row.addWidget(self.pin)
        pin_row.addStretch(1)
        renew = QPushButton("  New PIN")
        renew.setToolTip("Phones that know the old PIN will be asked again")
        renew.clicked.connect(self.pinRenewed.emit)
        pin_row.addWidget(renew)
        box.addLayout(pin_row)

        self.status = QLabel()
        self.status.setObjectName("cardHint")
        self.status.setWordWrap(True)
        box.addWidget(self.status)

        note = QLabel("The first time it is switched on, Windows may ask whether Python may use the "
                      "network: allow it on private networks.")
        note.setObjectName("keyHint")
        note.setWordWrap(True)
        box.addWidget(note)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        box.addWidget(close, 0, Qt.AlignRight)
        server.clientsChanged.connect(lambda _n: self.refresh())
        self.refresh()

    def refresh(self, error: str = "") -> None:
        on = self.server.running
        self.switch.setChecked(on)
        self.switch.setText("●  Remote is ON  —  tap to switch off" if on else "Switch the remote on")
        self.switch.setObjectName("primary" if not on else "")
        self.switch.style().unpolish(self.switch)
        self.switch.style().polish(self.switch)
        self.port.setEnabled(not on)
        addresses = self.server.addresses() if on else []
        if on and addresses:
            self.address.setText("\n".join(addresses[:2]))
        elif on:
            self.address.setText(f"http://<this computer>:{self.server.port}")
        else:
            self.address.setText("—")
        self.pin.setText(self.server.pin if on else "····")
        if error:
            self.status.setText(f"Could not start: {error}")
            self.status.setStyleSheet(f"color: {self.theme['danger']};")
        elif on:
            count = self.server.clients()
            self.status.setText(f"{count} phone(s) connected." if count else "Waiting for a phone…")
            self.status.setStyleSheet(f"color: {self.theme['ok']};" if count else "")
        else:
            self.status.setText("Off. Nobody can reach the app from the network.")
            self.status.setStyleSheet("")


# --------------------------------------------------------------------------- #
# The page
# --------------------------------------------------------------------------- #

MANIFEST = json.dumps({
    "name": "Stage remote", "short_name": "Stage", "display": "standalone",
    "background_color": "#0c1018", "theme_color": "#0c1018", "start_url": "/",
})

PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<meta name="theme-color" content="#0c1018">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="manifest" href="/manifest.json">
<title>Stage remote</title>
<style>
:root { --bg:#0c1018; --card:#141a26; --raised:#1a2130; --well:#0f141e; --edge:#222b3c; --edge-hi:#2c3750;
  --text:#e9edf5; --dim:#9aa6bb; --muted:#6c7891; --gold:#e3b23c; --ok:#57c98a; --warn:#d9853f; --red:#e0605c; }
* { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
html,body { margin:0; background:var(--bg); color:var(--text); font:15px/1.35 "Segoe UI",system-ui,-apple-system,Roboto,sans-serif; }
body { padding:env(safe-area-inset-top) 0 calc(72px + env(safe-area-inset-bottom)); min-height:100vh; }
button { font:inherit; color:inherit; border:1px solid var(--edge); background:linear-gradient(#212a3a,#182030);
  border-radius:14px; padding:14px 10px; touch-action:manipulation; cursor:pointer; }
button:active { transform:scale(.98); background:var(--well); }
header { display:flex; align-items:center; gap:10px; padding:14px 16px 6px; }
header .dot { width:10px; height:10px; border-radius:50%; background:var(--muted); flex:none; }
header .dot.on { background:var(--ok); box-shadow:0 0 10px var(--ok); }
header h1 { font-size:16px; margin:0; letter-spacing:.3px; flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
header .clock { color:var(--dim); font-variant-numeric:tabular-nums; }
main { padding:6px 14px 14px; display:none; }
main.active { display:block; }
.card { background:linear-gradient(var(--raised),var(--card) 55%); border:1px solid var(--edge); border-top-color:#313d55;
  border-radius:18px; padding:14px 16px; margin-bottom:12px; }
.cap { color:var(--muted); font-size:11px; font-weight:700; letter-spacing:1.2px; text-transform:uppercase; }
.now h2 { font-size:26px; margin:4px 0 2px; line-height:1.15; }
.notes { color:var(--dim); white-space:pre-wrap; margin-top:4px; }
.timer { color:var(--muted); font-variant-numeric:tabular-nums; margin-top:6px; font-size:13px; }
.next h3 { font-size:18px; margin:4px 0 0; }
.auto { color:var(--gold); font-weight:600; margin-top:4px; font-size:13px; }
.go { display:block; width:100%; min-height:24vh; font-size:34px; font-weight:800; letter-spacing:2px;
  color:#12161f; background:linear-gradient(#f2c556,var(--gold)); border-color:#c9992f; border-radius:22px; margin:4px 0 10px; }
.go:disabled { background:var(--well); color:var(--muted); border-color:var(--edge); }
.row { display:flex; gap:10px; }
.row > * { flex:1; }
.steps { list-style:none; margin:0; padding:0; }
.steps li { display:flex; align-items:center; gap:10px; padding:11px 10px; border-radius:12px; border:1px solid transparent; }
.steps li + li { margin-top:4px; }
.steps li .n { width:28px; height:28px; flex:none; border-radius:50%; background:#232c3d; color:var(--dim);
  display:grid; place-items:center; font-size:13px; font-weight:700; }
.steps li .t { flex:1; min-width:0; }
.steps li .t b { display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.steps li .t small { display:block; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.steps li.now { background:#1d2533; border-color:rgba(227,178,60,.45); }
.steps li.now .n { background:var(--gold); color:#12161f; }
.steps li.sel { border-color:var(--gold); }
.steps li .jump { display:none; padding:8px 14px; border-radius:10px; background:var(--gold); color:#12161f; border-color:#c9992f; font-weight:700; }
.steps li.sel .jump { display:block; }
.blackout { width:100%; font-size:22px; font-weight:800; letter-spacing:2px; color:var(--red);
  background:transparent; border:1.5px solid rgba(224,96,92,.55); min-height:74px; border-radius:18px; margin-bottom:12px; }
.screens { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; }
.screen { background:var(--well); border:1px solid var(--edge); border-radius:12px; padding:9px; min-width:0; }
.screen b { font-size:12px; display:block; }
.screen span { color:var(--dim); font-size:12px; display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.screen.off b { color:var(--muted); }
.cues { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; }
.cue { padding:10px 6px; min-height:64px; text-align:left; }
.cue small { display:block; color:var(--muted); font-size:11px; font-weight:700; }
.cue span { display:block; font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.cue.playing { border-color:var(--ok); background:rgba(87,201,138,.14); }
.cue.playing small { color:var(--ok); }
.cue.paused { border-color:var(--gold); }
.cue:disabled { opacity:.35; }
.presets button { width:100%; text-align:left; margin-top:6px; display:flex; justify-content:space-between; }
.presets button.cur { border-color:rgba(227,178,60,.5); }
.vol { display:flex; align-items:center; gap:10px; }
.vol b { min-width:54px; text-align:center; font-size:18px; }
nav { position:fixed; left:0; right:0; bottom:0; display:flex; gap:8px; padding:8px 12px calc(8px + env(safe-area-inset-bottom));
  background:rgba(12,16,24,.94); border-top:1px solid var(--edge); backdrop-filter:blur(8px); }
nav button { flex:1; background:transparent; border-color:transparent; color:var(--muted); font-weight:700; letter-spacing:1px; }
nav button.on { color:var(--gold); border-color:rgba(227,178,60,.35); background:rgba(227,178,60,.08); }
#login { position:fixed; inset:0; background:var(--bg); display:none; flex-direction:column; align-items:center; justify-content:center; gap:18px; z-index:9; }
#login.show { display:flex; }
#pin { font-size:40px; letter-spacing:18px; min-height:52px; font-weight:800; }
.pad { display:grid; grid-template-columns:repeat(3,84px); gap:12px; }
.pad button { height:72px; font-size:26px; font-weight:700; border-radius:50%; }
#msg { color:var(--red); min-height:20px; }
#toast { position:fixed; left:50%; bottom:90px; transform:translateX(-50%); background:var(--raised); border:1px solid var(--edge-hi);
  padding:10px 16px; border-radius:12px; opacity:0; transition:opacity .25s; pointer-events:none; max-width:90vw; text-align:center; }
#toast.show { opacity:1; }
.empty { color:var(--muted); text-align:center; padding:20px 6px; }
</style></head>
<body>
<header><div class="dot" id="dot"></div><h1 id="head">Stage remote</h1><div class="clock" id="clock"></div></header>

<main id="v-show" class="active">
  <div class="card now"><div class="cap" id="nowcap">Ready</div><h2 id="nowtitle">—</h2>
    <div class="notes" id="notes"></div><div class="timer" id="timer"></div></div>
  <button class="go" id="go">NEXT ▶</button>
  <div class="card next"><div class="cap">Next</div><h3 id="nexttitle">—</h3><div class="auto" id="auto"></div></div>
  <div class="row" style="margin-bottom:12px"><button id="back">◀ Back</button><button id="restart">↺ Start over</button></div>
  <div class="card"><div class="cap" style="margin-bottom:6px">Running order · tap a step, then GO</div><ul class="steps" id="steps"></ul></div>
</main>

<main id="v-stage">
  <button class="blackout" id="blackout">BLACKOUT</button>
  <div class="card"><div class="cap" style="margin-bottom:8px">Screens</div><div class="screens" id="screens"></div></div>
  <div class="card"><div class="cap" style="margin-bottom:8px">Sound</div><div class="cues" id="cues"></div>
    <div class="row" style="margin-top:10px"><button id="silence">Silence</button>
      <div class="vol"><button id="vdown">−</button><b id="vol">–</b><button id="vup">+</button></div></div></div>
  <div class="card presets"><div class="cap">Presets</div><div id="presets"></div></div>
</main>

<nav><button class="on" data-v="show">SHOW</button><button data-v="stage">STAGE</button><button data-href="/slides">SLIDES</button></nav>

<div id="login"><div class="cap">Enter the PIN shown on the dashboard</div><div id="pin"></div>
  <div class="pad" id="pad"></div><div id="msg"></div></div>
<div id="toast"></div>

<script>
const $ = id => document.getElementById(id);
let pin = localStorage.getItem("stagePin") || "";
let typed = "", state = null, selected = -1, lastGo = 0, failures = 0;

function toast(text) { const t = $("toast"); t.textContent = text; t.classList.add("show");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 1800); }
function buzz() { if (navigator.vibrate) navigator.vibrate(18); }
function esc(s) { return String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function mmss(s) { s = Math.max(0, Math.floor(s)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); }

async function api(path, body) {
  const options = { headers: { "X-Pin": pin } };
  if (body) { options.method = "POST"; options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
  const r = await fetch(path, options);
  // forget a refused PIN, so polling stops instead of locking this phone out
  if (r.status === 401) { pin = ""; localStorage.removeItem("stagePin"); askPin("Wrong PIN"); throw new Error("pin"); }
  if (r.status === 429) { askPin("Too many tries - wait a minute"); throw new Error("locked"); }
  return r.json();
}
async function act(action, extra) {
  buzz();
  try { const res = await api("/api/action", Object.assign({ action }, extra || {}));
        if (!res.ok && res.message) toast(res.message); else if (res.message) toast(res.message); }
  catch (e) {}
  refresh();
}

function askPin(message) { $("login").classList.add("show"); $("msg").textContent = message || ""; typed = ""; drawPin(); }
function drawPin() { $("pin").textContent = typed.padEnd(4, "·").split("").map((c, i) => i < typed.length ? "●" : "·").join(""); }
(function buildPad() {
  const keys = ["1","2","3","4","5","6","7","8","9","","0","⌫"];
  for (const k of keys) { const b = document.createElement("button"); b.textContent = k; if (!k) b.style.visibility = "hidden";
    b.onclick = () => { buzz(); if (k === "⌫") typed = typed.slice(0, -1); else if (typed.length < 4) typed += k;
      drawPin(); if (typed.length === 4) { pin = typed; localStorage.setItem("stagePin", pin); $("login").classList.remove("show"); refresh(); } };
    $("pad").appendChild(b); }
})();

function render() {
  const s = state; if (!s) return;
  const show = s.show;
  $("head").textContent = show.name || "Stage remote";
  const now = show.index >= 0 ? show.steps[show.index] : null;
  const next = show.steps[show.index + 1];
  $("nowcap").textContent = now ? `Now · step ${show.index + 1} of ${show.steps.length}` : (show.steps.length ? "Ready" : "No steps yet");
  $("nowtitle").textContent = now ? now.title : (show.steps.length ? "Press NEXT to start" : "Build the running order on the dashboard");
  $("notes").textContent = now ? now.notes : "";
  $("timer").textContent = now ? "running " + mmss(show.elapsed) : "";
  $("nexttitle").textContent = next ? next.title : (now ? "— end of the show —" : "—");
  $("auto").textContent = show.auto != null ? `goes on by itself in ${Math.ceil(show.auto)} s` : "";
  $("go").disabled = !next;
  const list = $("steps");
  if (!show.steps.length) list.innerHTML = '<li class="empty">No steps in this running order.</li>';
  else list.innerHTML = show.steps.map((st, i) =>
    `<li data-i="${i}" class="${i === show.index ? "now" : ""} ${i === selected ? "sel" : ""}"><div class="n">${i + 1}</div>
     <div class="t"><b>${esc(st.title)}</b><small>${esc(st.summary)}</small></div><button class="jump" data-go="${i}">GO</button></li>`).join("");
  $("screens").innerHTML = s.screens.map(sc =>
    `<div class="screen ${sc.open ? "" : "off"}"><b>${esc(sc.label)}</b><span>${sc.open ? esc(sc.file || "empty") : "closed"}</span></div>`).join("");
  $("cues").innerHTML = s.cues.map(c =>
    `<button class="cue ${c.playing ? "playing" : ""} ${c.paused ? "paused" : ""}" data-cue="${c.index}" ${c.filled ? "" : "disabled"}>
     <small>F${c.index + 1}${c.playing ? " ▶" : c.paused ? " ❚❚" : ""}</small><span>${esc(c.label || "empty")}</span></button>`).join("");
  $("vol").textContent = s.master + "%";
  $("presets").innerHTML = s.presets.length ? s.presets.map(p =>
    `<button data-preset="${esc(p)}" class="${p === s.preset ? "cur" : ""}"><span>${esc(p)}</span><span>${p === s.preset ? "on screens" : "load"}</span></button>`).join("")
    : '<div class="empty">No presets saved.</div>';
}

async function refresh() {
  if (!pin) { askPin(); return; }
  try { state = await api("/api/state"); $("dot").classList.add("on"); failures = 0; render(); }
  catch (e) { if (e.message !== "pin" && e.message !== "locked") { if (++failures > 2) $("dot").classList.remove("on"); } }
}

$("go").onclick = () => { const t = Date.now(); if (t - lastGo < 700) return; lastGo = t; selected = -1; act("next"); };
$("back").onclick = () => act("back");
$("restart").onclick = () => { if (confirm("Back to before step 1? Nothing on stage changes until NEXT.")) act("restart"); };
$("steps").onclick = e => {
  const go = e.target.closest("[data-go]");
  if (go) { selected = -1; act("goto", { index: +go.dataset.go }); return; }
  const li = e.target.closest("li[data-i]"); if (!li) return;
  selected = (+li.dataset.i === selected) ? -1 : +li.dataset.i; render(); };
$("blackout").onclick = () => act("blackout");
$("silence").onclick = () => act("silence");
$("vdown").onclick = () => act("master", { value: Math.max(0, (state ? state.master : 90) - 5) });
$("vup").onclick = () => act("master", { value: Math.min(100, (state ? state.master : 90) + 5) });
$("cues").onclick = e => { const b = e.target.closest("[data-cue]"); if (b) act("cue", { index: +b.dataset.cue }); };
$("presets").onclick = e => { const b = e.target.closest("[data-preset]");
  if (b && confirm(`Put “${b.dataset.preset}” on the screens?`)) act("preset", { name: b.dataset.preset }); };
document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  if (b.dataset.href) { location.href = b.dataset.href; return; }
  document.querySelectorAll("nav button").forEach(x => x.classList.toggle("on", x === b));
  document.querySelectorAll("main").forEach(m => m.classList.toggle("active", m.id === "v-" + b.dataset.v)); });
setInterval(() => { $("clock").textContent = new Date().toTimeString().slice(0, 5); }, 1000);
setInterval(() => { if (!document.hidden) refresh(); }, 800);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
refresh();
</script></body></html>
"""


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
let pin = localStorage.getItem("stagePin") || "", typed = "", state = null, lastTap = 0;
const images = {};            // "deck:index" -> object URL, fetched with the PIN header
function toast(t) { const e = $("toast"); e.textContent = t; e.classList.add("show"); clearTimeout(e._h); e._h = setTimeout(() => e.classList.remove("show"), 1500); }
function buzz() { if (navigator.vibrate) navigator.vibrate(20); }
function mmss(s) { s = Math.max(0, Math.floor(s)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); }
async function api(path, body) {
  const o = { headers: { "X-Pin": pin } };
  if (body) { o.method = "POST"; o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(body); }
  const r = await fetch(path, o);
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
  $("next").disabled = !s.loaded || (s.index + 1 >= s.count && !s.black);
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
  if (!pin) { askPin(); return; }
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
  else if (e.key === "b" || e.key === "B" || e.key === ".") act("slide_black");
});
setInterval(() => { if (!document.hidden) refresh(); }, 700);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
refresh();
</script></body></html>
"""
