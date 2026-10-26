"""
The phone as a whole stage desk - for a teacher running an assembly or a
rehearsal without the operator: open the screens, put a file (or one sent from
the phone) on any of them, run and build the running order, presentations with
their videos, text, sound pads, scenes, Canva and Kahoot, laptops, a rehearsal
that leaves the hall untouched, and UNDO.

PhoneControl is mixed into the dashboard (ControlPanel): every phone action does
exactly what the matching control on the desk does. Anything that could open a
dialog on the desk (a file that will not play, say) runs a moment later, so the
phone's answer never waits for a click at an empty desk - and such problems come
back to the phone as a notice instead of a dialog.

The phone can reach only the folders the Library offers, the favourites and its
own uploads folder - never the rest of the disk. Wiring the screens, the PINs
and the admin settings stay on the desk.
"""
from __future__ import annotations

from i18n import language, tr  # noqa: E402 - the interface's language

import copy
import os
import re
import shutil
import time
import uuid
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, QStandardPaths, Qt, QTimer

from config import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, ROLE_LABELS, ROLE_MAIN, ROLE_TOP, STAGE_ROLES, VIDEO_EXTENSIONS
from media import MediaProblem
from presentation import PDF_EXTENSIONS, POWERPOINT_EXTENSIONS
from show import new_step

DECK_EXTENSIONS = PDF_EXTENSIONS | POWERPOINT_EXTENSIONS
UPLOAD_EXTENSIONS = set(IMAGE_EXTENSIONS) | set(VIDEO_EXTENSIONS) | set(AUDIO_EXTENSIONS) | DECK_EXTENSIONS
MAX_UPLOAD = 8 * 1024 ** 3                 # a long 4K video still fits; a mistake does not fill the disk
SPARE_DISK = 1024 ** 3                     # an upload never leaves less than this free


def uploads_folder() -> str:
    """Documents\\Stage Display\\Phone uploads - made when first needed."""
    documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) \
        or os.path.expanduser("~")
    return os.path.join(documents, "Stage Display", "Phone uploads")


def file_kind(path: str) -> str:
    extension = os.path.splitext(path)[1].lower()
    if extension in VIDEO_EXTENSIONS:
        return "video"
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    if extension in DECK_EXTENSIONS:
        return "deck"
    return ""


def _safe_name(name: str) -> str:
    name = os.path.basename((name or "").replace("\\", "/"))
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name[:180] or "upload"


class UploadSink:
    """Files sent from a phone: written straight to disk, checked, then named."""

    def __init__(self, folder: Callable[[], str] = uploads_folder,
                 arrived: Optional[Callable[[str], None]] = None) -> None:
        self.folder = folder
        self.arrived = arrived
        self._open: Dict[str, dict] = {}

    def begin(self, name: str, length: int) -> Tuple[Optional[str], str]:
        name = _safe_name(name)
        if os.path.splitext(name)[1].lower() not in UPLOAD_EXTENSIONS:
            return None, tr("Only pictures, videos, sounds and presentations can be sent.")
        if length <= 0:
            return None, tr("That file is empty.")
        if length > MAX_UPLOAD:
            return None, tr("That file is too big (over 8 GB).")
        folder = self.folder()
        try:
            os.makedirs(folder, exist_ok=True)
            if shutil.disk_usage(folder).free < length + SPARE_DISK:
                return None, tr("The stage computer's disk is too full for that file.")
            ticket = uuid.uuid4().hex
            part = os.path.join(folder, f".{ticket}.part")
            handle = open(part, "wb")
        except OSError as error:
            return None, str(error)
        self._open[ticket] = {"name": name, "part": part, "handle": handle, "folder": folder}
        return ticket, ""

    def write(self, ticket: str, chunk: bytes) -> Optional[str]:
        entry = self._open.get(ticket)
        if entry is None:
            return "gone"
        try:
            entry["handle"].write(chunk)
        except OSError as error:
            return str(error)
        return None

    def finish(self, ticket: str) -> Tuple[bool, str, str]:
        entry = self._open.pop(ticket, None)
        if entry is None:
            return False, "gone", ""
        entry["handle"].close()
        stem, extension = os.path.splitext(entry["name"])
        target = os.path.join(entry["folder"], entry["name"])
        number = 2
        while os.path.exists(target):
            target = os.path.join(entry["folder"], f"{stem} ({number}){extension}")
            number += 1
        try:
            os.replace(entry["part"], target)
        except OSError as error:
            return False, str(error), ""
        if self.arrived is not None:
            self.arrived(target)
        return True, tr("{0} is on the stage computer.").format(os.path.basename(target)), os.path.basename(target)

    def cancel(self, ticket: str) -> None:
        entry = self._open.pop(ticket, None)
        if entry is None:
            return
        try:
            entry["handle"].close()
            os.remove(entry["part"])
        except OSError:
            pass


class PhoneControl:
    """The phone's side of the dashboard. Mixed into ControlPanel."""

    # -- set-up ------------------------------------------------------------------ #
    def _phone_setup(self) -> None:
        self._phone_quiet = 0
        self._phone_notice = {"id": 0, "text": ""}
        self._phone_sent: Dict[str, float] = {}     # screen -> when a phone last put a file on it

    def phone_owns_problem(self, role: str) -> bool:
        """A problem now is the phone's to hear: it is acting, or put a file on that screen just now
        (a video that will not play says so a moment after it was sent)."""
        return bool(self._phone_quiet) or time.monotonic() - self._phone_sent.get(role, -100.0) < 15.0

    def _phone_problem(self, text: str) -> None:
        """Something a phone asked for went wrong after it had its answer: it shows on the phone."""
        self._phone_notice = {"id": self._phone_notice["id"] + 1, "text": text}

    def _phone_later(self, action: Callable[[], None]) -> None:
        """Run a stage change after the phone has its answer; problems become notices, not dialogs."""
        def run() -> None:
            self._phone_quiet += 1
            try:
                action()
            finally:
                self._phone_quiet -= 1
        QTimer.singleShot(0, run)

    # -- where the phone may look ---------------------------------------------------- #
    def _phone_places(self) -> List[dict]:
        places = [{"key": "up", "name": tr("Sent from phones"), "path": uploads_folder()}]
        for index, folder in enumerate(self.library.pinned()):
            places.append({"key": f"p{index}", "name": os.path.basename(folder.rstrip("\\/")) or folder,
                           "path": folder})
        places.append({"key": "fav", "name": tr("★ Favourites"), "path": ""})
        return places

    def _phone_path(self, ident: str) -> Optional[str]:
        """A file the phone named ("place|relative path"), if it is one the phone may use."""
        key, _, rel = str(ident or "").partition("|")
        if key == "fav":
            favourites = self.library.favourites()
            try:
                path = favourites[int(rel)]
            except (ValueError, IndexError):
                return None
            return path if os.path.isfile(path) else None
        place = next((p for p in self._phone_places() if p["key"] == key), None)
        if place is None or not place["path"]:
            return None
        base = os.path.normpath(place["path"])
        path = os.path.normpath(os.path.join(base, rel))
        try:
            if os.path.commonpath([os.path.normcase(base), os.path.normcase(path)]) != os.path.normcase(base):
                return None                     # ".." out of the place
        except ValueError:
            return None
        return path

    def _phone_files(self, params: dict) -> dict:
        places = self._phone_places()
        key = params.get("place") or "up"
        place = next((p for p in places if p["key"] == key), places[0])
        listing = {"places": [{"key": p["key"], "name": p["name"]} for p in places],
                   "place": place["key"], "dir": "", "folders": [], "files": []}
        if place["key"] == "fav":
            for index, path in enumerate(self.library.favourites()):
                kind = file_kind(path)
                if kind and os.path.isfile(path):
                    listing["files"].append(self._phone_file_entry(f"fav|{index}", path, kind))
            return listing
        base = os.path.normpath(place["path"])
        if place["key"] == "up":
            os.makedirs(base, exist_ok=True)
        folder = self._phone_path(f"{place['key']}|{params.get('dir', '')}") or base
        if not os.path.isdir(folder):
            folder = base
        rel = os.path.relpath(folder, base)
        listing["dir"] = "" if rel == "." else rel.replace("\\", "/")
        try:
            names = os.listdir(folder)
        except OSError:
            names = []
        files = []
        for name in names:
            if name.startswith("."):
                continue
            full = os.path.join(folder, name)
            sub = (listing["dir"] + "/" + name) if listing["dir"] else name
            if os.path.isdir(full):
                listing["folders"].append({"name": name, "dir": sub})
            else:
                kind = file_kind(name)
                if kind:
                    files.append(self._phone_file_entry(f"{place['key']}|{sub}", full, kind))
        listing["folders"].sort(key=lambda f: f["name"].lower())
        if place["key"] == "up":
            files.sort(key=lambda f: -f["time"])            # just sent: on top
        else:
            files.sort(key=lambda f: f["name"].lower())
        listing["files"] = files[:400]
        return listing

    @staticmethod
    def _phone_file_entry(ident: str, path: str, kind: str) -> dict:
        try:
            info = os.stat(path)
            size, when = info.st_size, info.st_mtime
        except OSError:
            size, when = 0, 0
        return {"id": ident, "name": os.path.basename(path), "kind": kind, "size": size, "time": when}

    # -- pictures for the phone -------------------------------------------------------- #
    @staticmethod
    def _jpeg(pixmap, quality: int = 72) -> Optional[bytes]:
        if pixmap is None or pixmap.isNull():
            return None
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        pixmap.save(buffer, "JPG", quality)
        return bytes(data.data())

    def phone_get(self, path: str, params: dict):
        """The phone's other GET routes: (status, body, content type), or None."""
        import json
        if path == "/api/files":
            return 200, json.dumps(self._phone_files(params), ensure_ascii=False).encode("utf-8"), "application/json"
        if path == "/api/thumb":
            file_path = self._phone_path(params.get("id", ""))
            if file_path and file_kind(file_path) in ("image", "video") and os.path.isfile(file_path):
                data = self._jpeg(self._cached_thumb(file_path, 192, 108))
                if data:
                    return 200, data, "image/jpeg"
            return 404, b"no picture yet", "text/plain"
        if path == "/api/web":
            web = self.web
            if web.view is None or not web.is_open():
                return 404, b"no page", "text/plain"
            picture = web.snapshot() if web.on_stage() else web.view.grab()
            if not picture.isNull() and picture.width() > 960:
                picture = picture.scaledToWidth(960, Qt.SmoothTransformation)
            data = self._jpeg(picture, 70)
            return (200, data, "image/jpeg") if data else (404, b"no picture", "text/plain")
        return None

    # -- what the phone draws ------------------------------------------------------------ #
    def phone_state(self) -> dict:
        state = self.remote_state()
        for screen in state["screens"]:
            role = screen["role"]
            card = self.cards[role]
            window = self._show_output(role)
            path = card.current_path()
            entry = {"video": file_kind(path) == "video", "loop": card.is_repeating(),
                     "muted": card.mute_btn.isChecked(), "volume": card.volume_slider.value(),
                     "playing": False, "position": 0, "duration": 0, "text": None}
            if window is not None:
                player = window.engine.player
                entry["playing"] = player.playbackState() == player.PlaybackState.PlayingState
                entry["position"], entry["duration"] = player.position(), player.duration()
                slide = window.slide_state()
                entry["text"] = list(slide) if slide else None
            screen.update(entry)
        steps = self.show_tab.steps()
        state["show"]["shows"] = self.show_store.names()
        state["show"]["ids"] = [s["id"] for s in steps]
        state["outputs"] = {"open": len(self._outputs()),
                            "can_open": any(self.routing_rows[r].screen_combo.currentData() for r in STAGE_ROLES)}
        state["roles"] = [{"role": r, "label": ROLE_LABELS[r]} for r in STAGE_ROLES]
        state["undo"] = bool(self._undo_snapshot is not None and self.take_bar.undo_available())
        monitor = self._rehearsal
        from PySide6.QtMultimedia import QMediaDevices
        state["rehearsal"] = {"on": monitor is not None,
                              "sound": (monitor.sound_combo.currentData() or "") if monitor is not None else "",
                              "devices": [d.description() for d in QMediaDevices.audioOutputs()]}
        presenter, tab = self.presenter, self.presentation_tab
        slides = state["slides"]
        brk = self._break
        player = None
        if brk:
            window = self._show_output(brk["role"])
            player = window.engine.player if window is not None else None
        slides.update({
            "open": presenter.deck is not None, "kind": presenter.deck.kind if presenter.deck else "",
            "paused": presenter.paused, "role": presenter.role,
            "breaks": [os.path.basename(p) for p in tab.breaks.files()],
            "break": {"name": os.path.basename(brk["path"]),
                      "playing": bool(player and player.playbackState() == player.PlaybackState.PlayingState),
                      "position": player.position() if player else 0,
                      "duration": player.duration() if player else 0} if brk else None,
        })
        top = self.top_output
        state["text"] = {"target": self.text_slides.target.currentData() or ROLE_MAIN,
                         "marquee": {"running": bool(top and top.is_marquee_running()),
                                     "text": self.top_card.text_edit.text()}}
        web = self.web
        state["web"] = {"available": web.available(), "where": web.where if web.is_open() else "",
                        "title": web.title() if web.is_open() else "", "loading": web.loading,
                        "links": [{"name": n, "url": u} for n, u in self.web_tab._links]}
        share, receiver = self.share, self.share_receiver
        links = []
        for ident, link in receiver.links.items():
            request = share.request(ident)
            if request is not None:
                links.append({"id": ident, "name": request.name, "where": link.where, "state": link.state,
                              "silenced": link.silenced})
        state["share"] = {"running": share.running, "code": share.code,
                          "address": share.addresses()[0] if share.addresses() else "",
                          "waiting": [{"id": r.id, "name": r.name} for r in share.waiting() if r.id not in receiver.links]
                          if share.running else [],
                          "links": links, "stage": list(receiver.stage), "layout": receiver.layout}
        state["notice"] = dict(self._phone_notice)
        state["lang"] = language()
        return state

    # -- what the phone does ---------------------------------------------------------------- #
    PHONE_ACTIONS = frozenset((
        "screens_open", "screen_file", "screen_black", "screen_play", "screen_seek", "screen_loop",
        "screen_mute", "screen_volume", "undo", "rehearsal", "rehearsal_sound",
        "show_select", "show_new", "step_capture", "step_recapture", "step_edit", "step_delete", "step_move",
        "preset_save", "deck_open", "deck_show", "deck_end", "deck_close",
        "break_add", "break_play", "break_back", "break_toggle", "break_seek",
        "text_show", "text_hide", "marquee", "cue_assign", "cue_stop", "cue_clear",
        "web_open", "web_stage", "web_off", "web_close", "web_key", "web_click", "web_type", "web_scroll",
        "share_on", "share_preview", "share_take", "share_decline", "share_end", "share_silence",
    ))

    def phone_action(self, action: str, data: dict):
        if action not in self.PHONE_ACTIONS:
            return self.remote_action(action, data)         # the running order, BLACKOUT, pads, slides
        handler = getattr(self, "_phone_" + action)
        try:
            return handler(data)
        except (TypeError, ValueError, KeyError) as error:
            return False, tr("That did not work: {0}").format(error)

    def _phone_role(self, data: dict) -> str:
        role = str(data.get("role", ""))
        if role not in STAGE_ROLES:
            raise ValueError("no such screen")
        return role

    def _phone_file(self, data: dict, *kinds: str) -> str:
        path = self._phone_path(data.get("id", ""))
        if not path or not os.path.isfile(path):
            raise ValueError(tr("that file is not there any more"))
        if kinds and file_kind(path) not in kinds:
            raise ValueError(tr("not the right kind of file"))
        return path

    # screens
    def _phone_screens_open(self, _data: dict):
        if not any(self.routing_rows[r].screen_combo.currentData() for r in STAGE_ROLES):
            return False, tr("The screens are not set up yet - the administrator picks the monitors in Settings.")
        self._phone_later(self._apply_routing)
        return True, tr("Opening the stage screens.")

    def _phone_screen_file(self, data: dict):
        role = self._phone_role(data)
        path = self._phone_path(data.get("id", ""))
        if not path or not os.path.isfile(path):
            return False, tr("That file is not there any more.")
        kind = file_kind(path)
        if kind == "deck":
            return False, tr("That is a presentation - open it under Presentation.")
        if kind == "audio":
            return False, tr("That is a sound - put it on a sound pad.")
        if self._show_output(role) is None:
            if not self.routing_rows[role].screen_combo.currentData():
                return False, tr("{0} has no monitor set up.").format(ROLE_LABELS[role])
            self._phone_later(self._apply_routing)          # open it, then the file goes on
        card = self.cards[role]
        name = os.path.basename(path)
        self._phone_sent[role] = time.monotonic()
        self._phone_later(lambda: self._record_change(f"{ROLE_LABELS[role]}  ←  {name}",
                                                      lambda: card.loadRequested.emit(path),
                                                      self._thumb_for_path(path)))
        return True, tr("{0} → {1}").format(name, ROLE_LABELS[role])

    def _phone_screen_black(self, data: dict):
        role = self._phone_role(data)
        if self._show_output(role) is None:
            return False, tr("{0} is closed.").format(ROLE_LABELS[role])
        self._phone_later(self.cards[role]._on_clear)
        return True, tr("{0} → black").format(ROLE_LABELS[role])

    def _phone_screen_play(self, data: dict):
        role = self._phone_role(data)
        card = self.cards[role]
        (card.playRequested if data.get("on", True) else card.pauseRequested).emit()
        return True, ""

    def _phone_screen_seek(self, data: dict):
        window = self._show_output(self._phone_role(data))
        if window is None:
            return False, tr("That screen is closed.")
        player = window.engine.player
        target = max(0, min(int(data.get("ms", 0)), max(0, player.duration() - 250)))
        player.setPosition(target)
        return True, ""

    def _phone_screen_loop(self, data: dict):
        card = self.cards[self._phone_role(data)]
        self._set_checked(card.repeat_btn, bool(data.get("on")))
        return True, tr("Repeat on.") if data.get("on") else tr("Repeat off.")

    def _phone_screen_mute(self, data: dict):
        card = self.cards[self._phone_role(data)]
        self._set_checked(card.mute_btn, bool(data.get("on")))
        return True, tr("Sound off.") if data.get("on") else tr("Sound on.")

    def _phone_screen_volume(self, data: dict):
        card = self.cards[self._phone_role(data)]
        card.volume_slider.setValue(max(0, min(100, int(data.get("value", 80)))))
        return True, ""

    def _phone_undo(self, _data: dict):
        if self._undo_snapshot is None or not self.take_bar.undo_available():
            return False, tr("Nothing to undo.")
        self._phone_later(self._undo)
        return True, tr("Undone - the stage is back to how it was.")

    # rehearsal
    def _phone_rehearsal(self, data: dict):
        if data.get("on"):
            if self._rehearsal is not None:
                return True, ""
            if self.presenter.live:
                return False, tr("A presentation is on the stage. End it first, then rehearse.")
            self._phone_later(self.start_rehearsal)
            return True, tr("Rehearsal: the hall keeps what it has; the phone shows the rehearsal screens.")
        if self._rehearsal is None:
            return True, ""
        self._phone_later(self.end_rehearsal)
        return True, tr("Rehearsal ended - back to the real stage.")

    def _phone_rehearsal_sound(self, data: dict):
        monitor = self._rehearsal
        if monitor is None:
            return False, tr("No rehearsal is running.")
        index = monitor.sound_combo.findData(str(data.get("device", "")))
        monitor.sound_combo.setCurrentIndex(max(0, index))
        return True, tr("Rehearsal sound: {0}").format(monitor.sound_combo.currentText())

    # running order
    def _phone_show_select(self, data: dict):
        name = str(data.get("name", ""))
        if name not in self.show_store.shows:
            return False, tr("No such running order.")
        if name != self.show_store.current:
            self.show_tab._switch_to(name)
        return True, name

    def _phone_show_new(self, data: dict):
        name = str(data.get("name", "")).strip()[:80]
        if not name:
            return False, tr("Give it a name.")
        if name in self.show_store.shows:
            return False, tr("There is already a running order called “{0}”.").format(name)
        self.show_store.shows[name] = {"steps": []}
        self.show_tab._switch_to(name)
        return True, tr("New running order: {0}").format(name)

    def _phone_step_from_stage(self) -> dict:
        step = new_step()
        for role in STAGE_ROLES:
            card = self.cards[role]
            path = card.current_path()
            if path:
                step["screens"][role] = {"mode": "file", "path": path, "loop": card.is_repeating(),
                                         "audio": not card.mute_btn.isChecked()}
            elif self._show_output(role) is not None:
                step["screens"][role]["mode"] = "black"
        player = self._show_players[self._show_active]
        if player.is_playing() and player.path:
            step["sound"] = {"mode": "play", "path": player.path, "loop": player.loop, "level": player.level}
        if self.top_output is not None and self.top_output.is_marquee_running():
            step["marquee"] = {"mode": "start", "text": self.top_card.text_edit.text()}
        role, window = self._slide_output()
        if window is not None and window.slide_state():
            title, subtitle = window.slide_state()[:2]
            step["text"] = {"mode": "show", "title": title, "subtitle": subtitle, "target": role}
        if self.presenter.live and self.presenter.deck is not None:
            step["slides"] = {"mode": "start", "path": self.presenter.deck.path, "target": self.presenter.role}
        return step

    def _phone_step_capture(self, data: dict):
        steps = self.show_tab.steps()
        step = self._phone_step_from_stage()
        step["title"] = str(data.get("title", "")).strip()[:120] or tr("Step {0}").format(len(steps) + 1)
        step["notes"] = str(data.get("notes", ""))[:2000]
        self.show_tab.add_step(step, after=len(steps) - 1)
        return True, tr("Step added: {0}").format(step["title"])

    def _phone_step_index(self, data: dict) -> int:
        steps = self.show_tab.steps()
        index = int(data.get("index", -1))
        if not 0 <= index < len(steps) or (data.get("sid") and steps[index]["id"] != data["sid"]):
            raise ValueError(tr("the running order changed - try again"))
        return index

    def _phone_step_recapture(self, data: dict):
        index = self._phone_step_index(data)
        step = self.show_tab.steps()[index]
        fresh = self._phone_step_from_stage()
        for part in ("screens", "sound", "text", "marquee", "slides"):
            step[part] = fresh[part]
        self.show_tab._reload_list(index)
        self.show_tab._changed()
        return True, tr("“{0}” now puts up what is on the screens.").format(step["title"])

    def _phone_step_edit(self, data: dict):
        index = self._phone_step_index(data)
        step = self.show_tab.steps()[index]
        if "title" in data:
            step["title"] = str(data["title"]).strip()[:120] or step["title"]
        if "notes" in data:
            step["notes"] = str(data["notes"])[:2000]
        if "auto" in data:
            seconds = int(data.get("auto") or 0)
            step["advance"] = {"mode": "after", "seconds": seconds} if seconds > 0 else \
                {"mode": "manual", "seconds": step["advance"].get("seconds", 10)}
        self.show_tab._reload_list(index)
        self.show_tab._changed()
        return True, tr("Saved.")

    def _phone_step_delete(self, data: dict):
        index = self._phone_step_index(data)
        title = self.show_tab.steps()[index]["title"]
        del self.show_tab.steps()[index]
        self.show_tab._reload_list(max(0, index - 1))
        self.show_tab._changed()
        return True, tr("Deleted: {0}").format(title)

    def _phone_step_move(self, data: dict):
        index = self._phone_step_index(data)
        steps = self.show_tab.steps()
        target = index + (1 if int(data.get("delta", 1)) > 0 else -1)
        if not 0 <= target < len(steps):
            return False, ""
        steps[index], steps[target] = steps[target], steps[index]
        self.show_tab._reload_list(target)
        self.show_tab._changed()
        return True, ""

    # scenes
    def _phone_preset_save(self, data: dict):
        name = str(data.get("name", "")).strip()[:80]
        if not name:
            return False, tr("Give it a name.")
        if name in self.presets.names() and not data.get("replace"):
            return False, tr("A scene called “{0}” already exists.").format(name)
        self.presets.put(name, self._collect_preset())
        self._write_presets(name)
        return True, tr("Scene saved: {0}").format(name)

    # presentations
    def _phone_deck_open(self, data: dict):
        path = self._phone_file(data, "deck", "image")
        if self.presenter.live and not data.get("replace"):
            return False, tr("A presentation is on the screen - end it first.")
        self.presentation_tab.open_path(path)
        if self.presenter.deck is None:
            return False, tr("That presentation could not be opened.")
        return True, tr("Opened: {0}").format(os.path.basename(path))

    def _phone_deck_show(self, data: dict):
        if self.presenter.deck is None:
            return False, tr("Open a presentation first.")
        role = self._phone_role(data) if data.get("role") else self.presenter.role
        if self._show_output(role) is None:
            return False, tr("{0} is closed - open the screens first.").format(ROLE_LABELS[role])
        if self.web.on_stage() and role == ROLE_MAIN:
            self._web_off_stage()
        self._phone_later(lambda: self.presenter.go_live_when_ready(role))
        return True, tr("Slides on {0}.").format(ROLE_LABELS[role])

    def _phone_deck_end(self, _data: dict):
        if not self.presenter.live:
            return True, ""
        self._phone_later(self.presenter.end)
        return True, tr("Presentation ended.")

    def _phone_deck_close(self, _data: dict):
        if self.presenter.live:
            return False, tr("It is on a screen - end it first, then close it.")
        return (True, tr("Closed.")) if self.presentation_tab.close_deck() else (False, tr("Nothing to close."))

    def _phone_break_add(self, data: dict):
        path = self._phone_file(data, "video")
        self.presentation_tab.breaks.add_paths([path])
        return True, tr("Added to the talk's videos.")

    def _phone_break_play(self, data: dict):
        if "id" in data:
            path = self._phone_file(data, "video", "image")
        else:
            files = self.presentation_tab.breaks.files()
            path = files[int(data.get("index", 0))]
        self._phone_later(lambda: self.play_break(path))
        return True, tr("{0} is playing.").format(os.path.basename(path))

    def _phone_break_back(self, _data: dict):
        if not self._break and not self.presenter.paused:
            return True, ""
        self._phone_later(self.end_break)
        return True, tr("Back to the slides.") if self.presenter.live else tr("Video stopped.")

    def _phone_break_player(self):
        brk = self._break
        window = self._show_output(brk["role"]) if brk else None
        if window is None:
            raise ValueError(tr("no video is playing"))
        return window.engine.player

    def _phone_break_toggle(self, _data: dict):
        player = self._phone_break_player()
        if player.playbackState() == player.PlaybackState.PlayingState:
            player.pause()
            return True, tr("Paused.")
        player.play()
        return True, ""

    def _phone_break_seek(self, data: dict):
        player = self._phone_break_player()
        if "delta" in data:
            target = player.position() + int(data["delta"])
        else:
            target = int(data.get("ms", 0))
        player.setPosition(max(0, min(target, max(0, player.duration() - 250))))
        return True, ""

    # text
    def _phone_text_show(self, data: dict):
        role = self._phone_role(data)
        title = str(data.get("title", "")).strip()[:200]
        subtitle = str(data.get("subtitle", "")).strip()[:300]
        if not title and not subtitle:
            return False, tr("Type the text first.")
        if self._show_output(role) is None:
            return False, tr("{0} is closed - open the screens first.").format(ROLE_LABELS[role])
        combo = self.text_slides.target
        if combo.currentData() != role:
            combo.setCurrentIndex(max(0, combo.findData(role)))
        self._phone_later(lambda: self._record_change(f"{ROLE_LABELS[role]}  ←  “{title}”",
                                                      lambda: self._show_slide(title, subtitle)))
        return True, tr("Text on {0}.").format(ROLE_LABELS[role])

    def _phone_text_hide(self, data: dict):
        role = self._phone_role(data) if data.get("role") else None
        for each in ([role] if role else STAGE_ROLES):
            window = self._show_output(each)
            if window is not None and window.slide_visible():
                window.hide_slide(max(120, self.fade_ms() // 2))
        return True, tr("Text hidden.")

    def _phone_marquee(self, data: dict):
        if self.top_output is None:
            return False, tr("{0} is closed - open the screens first.").format(ROLE_LABELS[ROLE_TOP])
        if data.get("on"):
            text = str(data.get("text", "")).strip()[:500]
            if not text:
                return False, tr("Type the text first.")
            self.top_card.text_edit.setText(text)
            self._phone_later(self._start_marquee)
            return True, tr("The text runs along the Top Screen.")
        self._phone_later(self._stop_marquee)
        return True, tr("Running text stopped.")

    # sound pads
    def _phone_cue_assign(self, data: dict):
        index = int(data.get("index", -1))
        if not 0 <= index < len(self.sound.cues):
            return False, tr("No such sound pad.")
        path = self._phone_file(data, "audio", "video")
        try:
            self.sound.cues[index].assign(path)
        except MediaProblem as problem:
            return False, problem.title
        self._mark_preset_dirty()
        self._refresh_cue_pads()
        return True, f"F{index + 1}: {os.path.basename(path)}"

    def _phone_cue_stop(self, data: dict):
        index = int(data.get("index", -1))
        if 0 <= index < len(self.sound.cues):
            self._stop_cue(index)
        return True, ""

    def _phone_cue_clear(self, data: dict):
        index = int(data.get("index", -1))
        if 0 <= index < len(self.sound.cues):
            self._clear_cue(index)
        return True, tr("Sound pad emptied.")

    # Canva, Kahoot, the web
    def _phone_web_open(self, data: dict):
        if "index" in data:
            url = self.web_tab._links[int(data["index"])][1]
        else:
            url = str(data.get("url", ""))
        if not self.web.available():
            return False, tr("This installation of PySide6 has no QtWebEngine.")
        if not self.web.open(url, self.web_tab.host):
            return False, tr("That is not an address that can be opened.")
        return True, tr("Opening it on the desk - silent until you put it on the stage.")

    def _phone_web_stage(self, _data: dict):
        if not self.web.is_open():
            return False, tr("Open a page first.")
        if self.main_output is None:
            return False, tr("Open the Main Stage screen first - the page goes there.")
        if self.presenter.live and self.presenter.role == ROLE_MAIN:
            return False, tr("A presentation is on the Main Stage - end it first.")
        self._phone_later(self._web_to_stage)
        return True, tr("On the Main Stage.")

    def _phone_web_off(self, _data: dict):
        self._web_off_stage(tr("The web page came off the Main Stage."))
        return True, tr("Off the stage - the background is back.")

    def _phone_web_close(self, _data: dict):
        if self.web.on_stage():
            self._web_off_stage()
        self.web.close()
        return True, tr("Closed.")

    WEB_KEYS = {"next": Qt.Key_Right, "back": Qt.Key_Left, "up": Qt.Key_Up, "down": Qt.Key_Down,
                "enter": Qt.Key_Return, "space": Qt.Key_Space, "escape": Qt.Key_Escape, "tab": Qt.Key_Tab,
                "backspace": Qt.Key_Backspace}

    def _phone_web_key(self, data: dict):
        key = self.WEB_KEYS.get(str(data.get("key", "")))
        if key is None or not self.web.is_open():
            return False, ""
        text = {"enter": "\r", "space": " ", "tab": "\t", "backspace": "\b"}.get(str(data.get("key")), "")
        self.web.send_key(key, Qt.NoModifier, text)
        return True, ""

    def _phone_web_click(self, data: dict):
        if not self.web.is_open():
            return False, ""
        self.web.click_at(float(data.get("x", 0.5)), float(data.get("y", 0.5)))
        return True, ""

    def _phone_web_type(self, data: dict):
        if not self.web.is_open():
            return False, ""
        self.web.type_text(str(data.get("text", ""))[:500])
        return True, ""

    def _phone_web_scroll(self, data: dict):
        if not self.web.is_open():
            return False, ""
        self.web.scroll(float(data.get("amount", 0.6)))
        return True, ""

    # laptops
    def _phone_share_on(self, data: dict):
        error = self._toggle_share(bool(data.get("on")))
        if error:
            return False, error
        return True, tr("Laptop share on.") if self.share.running else tr("Laptop share off.")

    def _phone_share_preview(self, data: dict):
        self._preview_share(str(data.get("id", "")))
        return True, ""

    def _phone_share_take(self, data: dict):
        ident = str(data.get("id", ""))
        if ident not in self.share_receiver.links:
            self._preview_share(ident)          # straight from the queue: connect it first
        mode = str(data.get("mode", "alone"))
        self._phone_later(lambda: self._take_share(ident, mode if mode in ("alone", "side", "pip") else "alone"))
        return True, tr("On the Main Stage.")

    def _phone_share_decline(self, data: dict):
        self._decline_share(str(data.get("id", "")))
        return True, ""

    def _phone_share_end(self, data: dict):
        self._drop_share(str(data.get("id", "")))
        return True, tr("Ended.")

    def _phone_share_silence(self, data: dict):
        self._silence_share(str(data.get("id", "")), bool(data.get("on")))
        return True, ""
