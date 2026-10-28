"""
The dashboard's side of Stage Cloud (cloud.py): what this hall tells the cloud, what it lets
the cloud do, and Settings → Cloud. Mixed into ControlPanel.

The cloud always sees how the hall is doing. It may run the safe commands - look for an
update, install a downloaded one, a message for the operator - and, while "Allow running this
hall from the dashboard" is on, everything the phone remote can do: the remote desk is the
phone page, its requests passed over the internet. Whatever the cloud does is said in the
status bar, with who did it.
"""
from __future__ import annotations

from i18n import language, tr  # noqa: E402 - the interface's language

import ctypes
import json
import os
import platform
import shutil
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QWidget)

import cloud as cloud_mod
import phone_page
from config import DATA_DIR, FROZEN, HALL, ROLE_LABELS, STAGE_ROLES, VERSION
from show import missing_files as show_missing_files
from theme import CLR_DIM, CLR_INK, CLR_MUTED, CLR_OK, CLR_WARN, Icons

UPLOAD_IDLE_S = 90                       # an upload from the cloud that stopped half way is thrown away


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _uptime_hours() -> float:
    try:
        return round(ctypes.windll.kernel32.GetTickCount64() / 3_600_000, 1)
    except (AttributeError, OSError):
        return 0.0


class CloudControl:
    """Stage Cloud, from the dashboard. Mixed into ControlPanel."""

    # -- set-up ------------------------------------------------------------------- #
    def _cloud_setup(self) -> None:
        self.cloud = cloud_mod.CloudLink(self.settings, self.cloud_status, self.cloud_rpc, self.cloud_command, self)
        self.cloud.stateChanged.connect(self._refresh_cloud)
        self.cloud.paired.connect(self._on_cloud_paired)
        self._cloud_uploads: dict = {}            # ticket -> when it last moved
        self._cloud_sweep = QTimer(self)
        self._cloud_sweep.timeout.connect(self._sweep_cloud_uploads)
        self._cloud_sweep.start(30_000)
        self._cloud_started = time.time()
        self._cloud_closing = False               # the cloud asked: close without the question
        self._cloud_messages: list = []
        self._cloud_section = 0                   # Settings → Cloud's row, once Settings is built
        self._cloud_recent: list = []             # the last things the cloud did, for the chip's tooltip
        self._cloud_chip_reset = QTimer(self)
        self._cloud_chip_reset.setSingleShot(True)
        self._cloud_chip_reset.timeout.connect(self._reset_cloud_chip)

    def _cloud_start(self) -> None:
        if not os.environ.get("SDC_NO_CLOUD"):
            self.cloud.start()

    def _cloud_event(self, text: str, level: str = "warn") -> None:
        self.cloud.send_event(text, level)

    # -- what the cloud is told ------------------------------------------------------- #
    def _cloud_problems(self) -> list:
        problems = [tr("{0} monitor gone").format(ROLE_LABELS[role]) for role in sorted(self._lost_screens)]
        gone = show_missing_files(self.show_tab.steps())
        if gone:
            problems.append(tr('{0} file(s) missing').format(len(gone)))
        if self.sound_master.value() == 0:
            problems.append(tr('Master volume is at 0'))
        hall_audio = str(self.settings.value("ready/hall_audio", "") or "")
        if hall_audio and self._audio_device_name() != hall_audio:
            problems.append(tr("Not the hall's device ({0})").format(hall_audio))
        return problems

    def cloud_status(self) -> dict:
        state = self.remote_state()
        show = state["show"]
        steps = show["steps"]
        index = show["index"]
        slides = state["slides"]
        updater = self.updater
        try:
            disk = round(shutil.disk_usage(DATA_DIR).free / 1024 ** 3, 1)
        except OSError:
            disk = None
        summary = {
            "version": VERSION,
            "hall": HALL.get("name") or "",
            "screens": [{"role": s["role"], "name": s["label"], "kind": s["kind"], "open": s["open"],
                         "what": s["file"], "state": s["state"]} for s in state["screens"]],
            "show": {"name": show["name"] or "", "step": index + 1, "steps": len(steps),
                     "title": steps[index]["title"] if 0 <= index < len(steps) else ""},
            "slides": {"name": slides["name"], "index": slides["index"] + 1, "count": slides["count"],
                       "live": bool(slides["live"])} if slides["loaded"] else None,
            "update": {"state": updater.state, "version": updater.release.version if updater.release else ""},
            "problems": self._cloud_problems()[:8],
            "control": self.cloud.control_allowed(),
            "computer": platform.node(),
            "language": language(),
        }
        detail = {
            "pc": {"os": platform.platform(terse=True), "uptime_h": _uptime_hours(), "disk_free_gb": disk,
                   "program_h": round((time.time() - self._cloud_started) / 3600, 1), "frozen": FROZEN},
            "sound": {"device": self._audio_device_name(), "master": self.sound_master.value()},
            "phone": {"on": self.remote.running, "phones": self.remote.clients() if self.remote.running else 0},
            "share": {"on": self.share.running, "laptops": len(self.share_receiver.links)},
            "preset": self.loaded_preset or "",
            "web": self.web.title() if self.web.is_open() else "",
            "timer": self.timer_state(),
        }
        return {"summary": summary, "detail": detail}

    # -- what the cloud may do --------------------------------------------------------- #
    def cloud_rpc(self, method: str, path: str, params: dict, body: bytes, user: str):
        """The remote desk's requests - the phone page's own API - while this hall allows it."""
        if not self.cloud.control_allowed():
            return 403, _json({"ok": False, "message": tr(
                "Running this hall from the dashboard is switched off here (Settings → Cloud).")}), "application/json"
        if path in ("/", "/index.html"):
            return 200, phone_page.render(language()), "text/html; charset=utf-8"
        if path == "/api/upload" and method == "POST":
            return self._cloud_upload(params, body, user)
        if method == "POST" and path == "/api/action":
            try:
                action = str(json.loads(body.decode("utf-8") or "{}").get("action", ""))
            except ValueError:
                action = ""
            if action:
                self._cloud_note(user, action)
        return self.remote.serve(method, path, params, body)

    def _cloud_note(self, user: str, what: str) -> None:
        """Whatever the cloud does is seen at the desk: the status bar for a moment, the cloud chip
        for a minute (who, and what), and the chip's tooltip keeps the last few."""
        text = tr("From the dashboard ({0}): {1}").format(user, what)
        self.statusBar().showMessage(text, 8000)
        self._cloud_recent = ([f"{time.strftime('%H:%M')}  {user}: {what}"] + self._cloud_recent)[:6]
        self.cloud_chip.setText(f" {user}: {what}"[:48])
        self.cloud_chip.setToolTip(tr("Connected to Stage Cloud") + "\n\n" + "\n".join(self._cloud_recent))
        self._cloud_chip_reset.start(60_000)

    def _reset_cloud_chip(self) -> None:
        self.cloud_chip.setText(tr(" Cloud"))

    def _cloud_upload(self, params: dict, body: bytes, user: str):
        """A file from the remote desk, in pieces: begin, write (one piece each), finish or cancel."""
        sink = self.remote.upload
        op = str(params.get("op", ""))
        ticket = str(params.get("ticket", ""))
        if op == "begin":
            try:
                length = int(params.get("length", -1))
            except (TypeError, ValueError):
                length = -1
            new, error = sink.begin(str(params.get("name", "")), length)
            if new is None:
                return 400, _json({"ok": False, "message": error}), "application/json"
            self._cloud_uploads[new] = time.monotonic()
            return 200, _json({"ok": True, "ticket": new}), "application/json"
        if ticket not in self._cloud_uploads:
            return 404, _json({"ok": False, "message": tr("The connection broke.")}), "application/json"
        if op == "write":
            error = sink.write(ticket, body)
            if error:
                self._cloud_uploads.pop(ticket, None)
                sink.cancel(ticket)
                return 500, _json({"ok": False, "message": error}), "application/json"
            self._cloud_uploads[ticket] = time.monotonic()
            return 200, _json({"ok": True}), "application/json"
        self._cloud_uploads.pop(ticket, None)
        if op == "finish":
            ok, message, name = sink.finish(ticket)
            if ok:
                self._cloud_note(user, name)
            return 200, _json({"ok": ok, "message": message, "name": name}), "application/json"
        sink.cancel(ticket)
        return 200, _json({"ok": True}), "application/json"

    def _sweep_cloud_uploads(self) -> None:
        now = time.monotonic()
        for ticket, when in list(self._cloud_uploads.items()):
            if now - when > UPLOAD_IDLE_S:
                self._cloud_uploads.pop(ticket, None)
                self.remote.upload.cancel(ticket)

    def cloud_command(self, cmd: str, args: dict, user: str):
        """The safe commands. Returns (ok, what the dashboard is told)."""
        updater = self.updater
        if cmd == "status":
            QTimer.singleShot(0, self.cloud.send_status)
            return True, ""
        if cmd == "message":
            text = str(args.get("text", "")).strip()[:500]
            if not text:
                return False, tr("An empty message.")
            QTimer.singleShot(0, lambda: self._show_cloud_message(user, text))
            return True, tr("Shown on the desk.")
        if cmd == "check_update":
            if not FROZEN:
                return False, tr("Run from source: new versions come with git.")
            if updater.waiting():
                return True, tr("Version {0} is downloaded and ready.").format(updater.release.version)
            updater.check()
            return True, tr("Looking for a new version…")
        if cmd == "install_update":
            if not updater.waiting():
                return False, tr("No update is downloaded yet.")
            if args.get("now"):
                QTimer.singleShot(1000, self._cloud_install_now)
                return True, tr("Installing version {0}: the program closes and opens again in about a minute.").format(
                    updater.release.version)
            return True, tr("Version {0} goes in when the program is closed.").format(updater.release.version)
        return False, tr("Unknown command.")

    def _cloud_install_now(self) -> None:
        self._update_requested = True
        self._cloud_closing = True
        if not self.close():
            self._update_requested = self._cloud_closing = False

    def _show_cloud_message(self, user: str, text: str) -> None:
        title = tr("Message from {0}").format(user)
        self.tray.notify(title, text)
        self.statusBar().showMessage(f"{title}: {text}", 30000)
        box = QMessageBox(QMessageBox.Information, title, text, QMessageBox.Ok, self)
        box.setWindowModality(Qt.NonModal)             # the desk keeps working; it waits to be read
        box.setAttribute(Qt.WA_DeleteOnClose)
        box.show()
        self._cloud_messages = [b for b in self._cloud_messages if b.isVisible()] + [box]

    # -- Settings → Cloud -------------------------------------------------------------- #
    def _build_cloud_card(self) -> QWidget:
        card, box = self._settings_card(tr('Stage Cloud'))
        self.cloud_status_label = QLabel()
        self.cloud_status_label.setWordWrap(True)
        self.cloud_status_label.setTextFormat(Qt.RichText)
        box.addWidget(self.cloud_status_label)

        self.cloud_pair_row = QWidget()
        row = QHBoxLayout(self.cloud_pair_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.cloud_address = QLineEdit(self.cloud.address())
        self.cloud_address.setPlaceholderText(tr("The dashboard's address, e.g. stage-cloud.school.workers.dev"))
        row.addWidget(self.cloud_address, 3)
        self.cloud_code = QLineEdit()
        self.cloud_code.setPlaceholderText(tr("Code, e.g. ABCD-2345"))
        self.cloud_code.setMaxLength(12)
        row.addWidget(self.cloud_code, 1)
        self.cloud_pair_btn = QPushButton(tr('  Pair'))
        self.cloud_pair_btn.setObjectName("primary")
        self.cloud_pair_btn.setIcon(Icons.get("globe", CLR_INK, 16))
        self.cloud_pair_btn.clicked.connect(self._pair_cloud)
        self.cloud_code.returnPressed.connect(self._pair_cloud)
        row.addWidget(self.cloud_pair_btn)
        box.addWidget(self.cloud_pair_row)

        buttons = QHBoxLayout()
        self.cloud_connect_btn = QPushButton(tr('  Connect now'))
        self.cloud_connect_btn.setIcon(Icons.get("refresh", CLR_DIM, 15))
        self.cloud_connect_btn.clicked.connect(self.cloud.connect_now)
        buttons.addWidget(self.cloud_connect_btn)
        self.cloud_forget_btn = QPushButton(tr('  Leave the cloud…'))
        self.cloud_forget_btn.setIcon(Icons.get("close", CLR_DIM, 15))
        self.cloud_forget_btn.clicked.connect(self._forget_cloud)
        buttons.addWidget(self.cloud_forget_btn)
        buttons.addStretch(1)
        box.addLayout(buttons)

        self.cloud_control_check = QCheckBox(tr(
            'Allow running this hall from the dashboard - the remote desk: screens, files, running order, slides, text, sound'))
        self.cloud_control_check.setChecked(self.cloud.control_allowed())
        self.cloud_control_check.toggled.connect(self.cloud.set_control_allowed)
        box.addWidget(self.cloud_control_check)
        note = QLabel(tr('The dashboard shows every paired hall: whether it is on, its version, its screens and what is on '
                         'them, the running order and problems. From there a hall can be told to look for an update, to '
                         'install it, or to show the operator a message - and, while the box above is ticked, run like '
                         'from the phone remote, from anywhere. What it does is said in the status bar, with who did it.'))
        note.setObjectName("cardHint")
        note.setWordWrap(True)
        box.addWidget(note)
        self._refresh_cloud()
        return card

    def _pair_cloud(self) -> None:
        self.cloud_pair_btn.setEnabled(False)
        self.cloud_status_label.setText(tr('Pairing…'))
        self.cloud.pair(self.cloud_address.text(), self.cloud_code.text())

    def _on_cloud_paired(self, ok: bool, message: str) -> None:
        self.cloud_pair_btn.setEnabled(True)
        if ok:
            self.cloud_code.clear()
            self.statusBar().showMessage(tr('Paired with Stage Cloud as “{0}”.').format(message), 8000)
        else:
            QMessageBox.warning(self, tr('Stage Cloud'), tr('Not paired: {0}').format(message))
        self._refresh_cloud()

    def _forget_cloud(self) -> None:
        answer = QMessageBox.question(
            self, tr('Stage Cloud'),
            tr('This computer leaves Stage Cloud: the dashboard no longer sees or runs this hall. It can be paired '
               'again with a new code. Leave?'))
        if answer == QMessageBox.Yes:
            self.cloud.forget()

    def _refresh_cloud(self) -> None:
        link = self.cloud
        state = link.state
        name = link.hall_name() or tr("this hall")
        address = link.address().replace("https://", "")
        if state == cloud_mod.ONLINE:
            text = tr("<b style='color:{0}'>Connected</b> as “{1}” to {2}.").format(CLR_OK, name, address)
        elif state == cloud_mod.CONNECTING:
            text = tr("Connecting to {0}…").format(address)
        elif state == cloud_mod.OFFLINE:
            text = tr("<b style='color:{0}'>Not connected</b> - it tries again by itself.").format(CLR_WARN)
            if link.detail:
                text += f"<br><span style='color:{CLR_MUTED}'>{link.detail[:160]}</span>"
        elif state == cloud_mod.UNPAIRED:
            text = tr("<b style='color:{0}'>Paired again elsewhere, or removed</b> - pair this hall again with a new code.").format(CLR_WARN)
        else:
            text = tr("Not paired. On the dashboard: Add a hall (or Pair again) gives a code - type it here.")
        if not hasattr(self, "cloud_status_label"):
            return
        self.cloud_status_label.setText(text)
        paired = link.is_paired() and state != cloud_mod.UNPAIRED
        self.cloud_pair_row.setVisible(not paired)
        self.cloud_connect_btn.setVisible(paired and state == cloud_mod.OFFLINE)
        self.cloud_forget_btn.setVisible(link.is_paired())
        if hasattr(self, "cloud_chip"):
            self.cloud_chip.setVisible(state == cloud_mod.ONLINE)
