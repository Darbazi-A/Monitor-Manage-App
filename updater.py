"""
Updates: new versions of the program, from the project's GitHub Releases.

Now and then (a little after start, then every few hours) the installed program
asks GitHub for the newest release. When it is newer than this one, its
installer is downloaded in the background and checked against the SHA-256 that
GitHub keeps for it - then it waits. Nothing changes during a show: the new
version goes in only when the operator says so (Install now - the program
closes, installs and opens again), or by itself the next time the program is
closed.

The installer runs silently over the installation (the same AppId), so the
hall's presets, running orders, hall and settings all stay. Run from source,
the program only says that a new version is out - git brings it.

Kept free of main.py imports: the dashboard listens to the signals.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal

REPO = "Darbazi-A/Monitor-Manage-App"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
# the tests point this at a release of their own
LATEST_URL = os.environ.get("SDC_UPDATE_URL") or f"https://api.github.com/repos/{REPO}/releases/latest"
FIRST_CHECK_MS = 20_000                  # a little after start: the hall's monitors and the show come first
EVERY_MS = 6 * 3600 * 1000               # then every six hours, for a desk that runs for days
RETRY_MS = 30 * 60 * 1000                # no internet: try again in half an hour
TIMEOUT_S = 30
CHUNK = 1 << 20

# what the state means, for the Settings card
IDLE, CHECKING, LATEST, AVAILABLE, DOWNLOADING, READY, FAILED = (
    "idle", "checking", "latest", "available", "downloading", "ready", "failed")


def parse_version(text) -> Optional[tuple]:
    """'v1.2.0' / '1.2' -> (1, 2, 0); None for anything else ('nightly', '')."""
    found = re.match(r"\s*v?(\d+(?:\.\d+){0,3})\s*$", str(text or ""))
    if not found:
        return None
    numbers = [int(part) for part in found.group(1).split(".")]
    return tuple(numbers + [0] * (3 - len(numbers)))


def is_newer(candidate, current) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    return new is not None and old is not None and new > old


@dataclass
class Release:
    version: str                         # "1.2.0"
    name: str                            # the release's title
    notes: str                           # its description (Markdown)
    page: str                            # its page on GitHub
    asset_name: str                      # StageDisplayController-Setup-1.2.0.exe
    asset_url: str
    size: int
    sha256: str                          # "" when GitHub gave none


def release_from_json(data) -> Optional[Release]:
    """GitHub's answer -> a Release with a Windows installer, or None (a draft, a pre-release, no installer)."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    if parse_version(tag) is None:
        return None
    for asset in data.get("assets") or ():
        name = str(asset.get("name") or "")
        if not (name.lower().endswith(".exe") and "setup" in name.lower()):
            continue
        digest = str(asset.get("digest") or "")
        return Release(
            version=".".join(str(n) for n in parse_version(tag)),
            name=str(data.get("name") or tag),
            notes=str(data.get("body") or ""),
            page=str(data.get("html_url") or RELEASES_PAGE),
            asset_name=os.path.basename(name),
            asset_url=str(asset.get("browser_download_url") or ""),
            size=int(asset.get("size") or 0),
            sha256=digest.split(":", 1)[1].lower() if digest.lower().startswith("sha256:") else "",
        )
    return None


def download_dir() -> str:
    """Where the installer waits: the user's temp folder (not the roaming profile - it is 130 MB)."""
    return os.environ.get("SDC_UPDATE_DIR") or os.path.join(tempfile.gettempdir(), "StageDisplayController-update")


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": "StageDisplayController-updater",
                                                "Accept": "application/vnd.github+json"})


def file_matches(path: str, release: Release) -> bool:
    """The file is the release's installer: the right size, and (when GitHub gave one) the right SHA-256."""
    try:
        if os.path.getsize(path) != release.size:
            return False
        if not release.sha256:
            return True
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(CHUNK), b""):
                digest.update(block)
        return digest.hexdigest() == release.sha256
    except OSError:
        return False


class Updater(QObject):
    stateChanged = Signal()              # anything the Settings card shows
    ready = Signal(object)               # a Release whose installer is downloaded and checked
    _finished = Signal(str, object, str)  # from the worker thread: state, release, detail
    _progress = Signal(float)

    def __init__(self, current: str, can_install: bool, parent: QObject = None) -> None:
        super().__init__(parent)
        self.current = current
        self.can_install = can_install   # the installed program; from source, only "a new version is out"
        self.state = IDLE
        self.detail = ""                 # an error's words
        self.release: Optional[Release] = None
        self.installer = ""              # the downloaded, checked installer
        self.progress = 0.0
        self.last_check = 0.0
        self._busy = False
        self._finished.connect(self._on_finished)
        self._progress.connect(self._on_progress)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.check)

    # -- when -------------------------------------------------------------------- #

    def start_schedule(self, first_ms: int = FIRST_CHECK_MS) -> None:
        self._timer.start(first_ms)

    def stop_schedule(self) -> None:
        self._timer.stop()

    def scheduled(self) -> bool:
        return self._timer.isActive()

    # -- asking GitHub ------------------------------------------------------------- #

    def busy(self) -> bool:
        return self._busy

    def check(self) -> None:
        """Ask for the newest release (in the background). A downloaded update simply waits to go in."""
        if self._busy or self.waiting():
            return
        self._busy = True
        self.state, self.detail, self.progress = CHECKING, "", 0.0
        self.stateChanged.emit()
        threading.Thread(target=self._work, name="update-check", daemon=True).start()

    def _work(self) -> None:
        try:
            with urllib.request.urlopen(_request(LATEST_URL), timeout=TIMEOUT_S) as answer:
                release = release_from_json(json.loads(answer.read().decode("utf-8")))
            if release is None or not is_newer(release.version, self.current):
                self._finished.emit(LATEST, release, "")
            elif not self.can_install:
                self._finished.emit(AVAILABLE, release, "")
            else:
                self._finished.emit(DOWNLOADING, release, "")
                self._finished.emit(READY, release, self._download(release))
        except Exception as error:  # noqa: BLE001 - no internet, GitHub busy, a broken file: try later
            self._finished.emit(FAILED, None, str(error) or error.__class__.__name__)

    def _download(self, release: Release) -> str:
        folder = download_dir()
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, release.asset_name)
        for name in os.listdir(folder):  # an older version's installer, a broken download
            if name != release.asset_name:
                try:
                    os.remove(os.path.join(folder, name))
                except OSError:
                    pass
        if os.path.isfile(path) and file_matches(path, release):
            return path                   # downloaded before: the program was closed before installing
        if not release.asset_url.lower().startswith("https://") and not os.environ.get("SDC_UPDATE_URL"):
            raise ValueError("the installer's address is not https")
        partial = path + ".part"
        digest = hashlib.sha256()
        done = 0
        with urllib.request.urlopen(_request(release.asset_url), timeout=TIMEOUT_S) as answer, \
                open(partial, "wb") as handle:
            for block in iter(lambda: answer.read(CHUNK), b""):
                handle.write(block)
                digest.update(block)
                done += len(block)
                if release.size:
                    self._progress.emit(min(1.0, done / release.size))
        if done != release.size:
            os.remove(partial)
            raise ValueError(f"the download is {done} bytes, not {release.size}")
        if release.sha256 and digest.hexdigest() != release.sha256:
            os.remove(partial)
            raise ValueError("the download does not match GitHub's SHA-256 - it was not kept")
        os.replace(partial, path)
        return path

    def _on_progress(self, fraction: float) -> None:
        self.progress = fraction
        self.stateChanged.emit()

    def _on_finished(self, state: str, release, detail: str) -> None:
        if state == DOWNLOADING:
            self.state, self.release, self.progress = state, release, 0.0
            self.stateChanged.emit()
            return
        self._busy = False
        self.last_check = time.time()
        if state == FAILED:
            self.state, self.detail = FAILED, detail
        else:
            self.state, self.detail, self.release = state, "", release
            self.installer = detail if state == READY else ""
        self.stateChanged.emit()
        if self.state == READY:
            self.ready.emit(self.release)
        self._timer.start(RETRY_MS if state == FAILED else EVERY_MS)

    # -- installing ------------------------------------------------------------- #

    def waiting(self) -> bool:
        """An update is downloaded and can go in."""
        return self.state == READY and bool(self.installer) and self.can_install

    def install(self, relaunch: bool, visible: bool) -> bool:
        """
        Start the installer and leave it to it: the program must close next (the
        installer also closes what is left of it). relaunch: it opens the program
        again when done. visible: a small progress window instead of nothing.
        """
        if not self.waiting() or not file_matches(self.installer, self.release):
            return False
        arguments = [self.installer, "/SILENT" if visible else "/VERYSILENT", "/SUPPRESSMSGBOXES",
                     "/NORESTART", "/CLOSEAPPLICATIONS",
                     "/LOG=" + os.path.join(os.path.dirname(self.installer), "install.log")]
        if relaunch:
            arguments.append("/RELAUNCH")  # StageDisplay.iss: open the program again afterwards
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            subprocess.Popen(arguments, creationflags=flags, close_fds=True)
        except OSError as error:
            self.state, self.detail = FAILED, str(error)
            self.installer = ""
            self.stateChanged.emit()
            return False
        return True
