"""
Presentations straight from the app: PDF, PowerPoint, or a folder of pictures.

Slides are turned into full-screen pictures once, in the background, and kept
in a cache, so a deck opened a second time is ready at once. They go on stage
through the same output windows as everything else, with a quick dissolve.

A clicker, the keyboard, the phone and the dashboard all drive one Presenter.
PowerPoint files are converted by the PowerPoint installed on this PC (hidden
slides are skipped, speaker notes are kept); without PowerPoint, save the deck
as PDF.

Kept free of main.py imports: the dashboard hands in the stage, icons and colours.
"""
from __future__ import annotations

from i18n import tr  # noqa: E402 - the interface's language

import base64
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import (QBuffer, QByteArray, QIODevice, QObject, QProcess, QProcessEnvironment,
                            QRectF, QSize, QSizeF, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QImageReader, QPainter, QPen, QPixmap
from desk import HoldButton
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QFrame, QHBoxLayout, QLabel, QListView, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QSizePolicy,
                               QSpinBox, QVBoxLayout, QWidget)

try:
    from PySide6.QtPdf import QPdfDocument
except ImportError:  # pragma: no cover - QtPdf ships with PySide6-Addons
    QPdfDocument = None

PDF_EXTENSIONS = {".pdf"}
POWERPOINT_EXTENSIONS = {".pptx", ".ppt", ".ppsx", ".pps", ".pptm", ".odp"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
OPEN_FILTER = ("Presentations (*.pdf *.pptx *.ppt *.ppsx *.pps *.pptm *.odp "
               "*.png *.jpg *.jpeg);;PDF (*.pdf);;PowerPoint (*.pptx *.ppt *.ppsx *.pps *.pptm)")
TRANSITIONS = (("Quick dissolve", 250), ("Cut", 0), ("Slow dissolve", 700))

# What clickers send. Most send Page Down / Page Up; some send the arrows.
NEXT_KEYS = ("PgDown", "Right", "Down", "Space", "Return", "Enter", "N")
BACK_KEYS = ("PgUp", "Left", "Up", "Backspace", "P")
BLACK_KEYS = ("B", ".")


def cache_root() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "StageDisplayController", "slides")


def powerpoint_available() -> bool:
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "PowerPoint.Application"))
        return True
    except (ImportError, OSError):
        return False


def _natural(name: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


POWERSHELL_EXPORT = r"""
$ErrorActionPreference = 'Stop'
$src = $env:SDC_SRC; $dir = $env:SDC_DIR; $W = [int]$env:SDC_W; $H = [int]$env:SDC_H
New-Item -ItemType Directory -Force -Path $dir | Out-Null
# a private copy: PowerPoint hands out the same open presentation to everyone who
# opens a file, and closing it here must not end a slide show of the original
$copy = Join-Path $dir ("source" + [IO.Path]::GetExtension($src))
Copy-Item -LiteralPath $src -Destination $copy -Force
# PowerPoint may still be closing down after an earlier use (it takes seconds);
# an Open on that instance fails at once. Let it go, then start a fresh one.
$app = $null; $pres = $null
for ($try = 0; $pres -eq $null; $try++) {
  try {
    $app = New-Object -ComObject PowerPoint.Application
    $pres = $app.Presentations.Open($copy, -1, 0, 0)
  } catch {
    if ($try -ge 40) { throw }
    try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($app) } catch { }
    $app = $null
    Start-Sleep -Milliseconds 500
  }
}
try {
  $sw = $pres.PageSetup.SlideWidth; $sh = $pres.PageSetup.SlideHeight
  $scale = [Math]::Min($W / $sw, $H / $sh)
  $w = [int][Math]::Round($sw * $scale); $h = [int][Math]::Round($sh * $scale)
  $visible = @($pres.Slides | Where-Object { -not $_.SlideShowTransition.Hidden })
  "COUNT " + $visible.Count
  $notes = New-Object System.Collections.ArrayList
  $indexes = New-Object System.Collections.ArrayList
  $i = 0
  foreach ($slide in $visible) {
    $i++
    $slide.Export((Join-Path $dir ("page-{0:D4}.png" -f $i)), "PNG", $w, $h)
    $text = ""
    try { $text = [string]$slide.NotesPage.Shapes.Placeholders.Item(2).TextFrame.TextRange.Text } catch { }
    [void]$notes.Add($text)
    [void]$indexes.Add([int]$slide.SlideIndex)
    "PAGE " + $i
  }
  ConvertTo-Json -InputObject @($notes) | Out-File -Encoding utf8 (Join-Path $dir 'notes.json')
  ConvertTo-Json -InputObject @($indexes) | Out-File -Encoding utf8 (Join-Path $dir 'indexes.json')
  "DONE"
} finally {
  $pres.Close()
  # PowerPoint is left running, hidden: quitting takes seconds, and a slide show
  # starting meanwhile would attach to the instance that is going away.
  # The keeper (keep_powerpoint_ready) holds it; it goes when the app closes.
  Remove-Item -LiteralPath $copy -Force -ErrorAction SilentlyContinue
}
"""


# A real PowerPoint slideshow, driven line by line over stdin, so animations and
# transitions play exactly as they do in PowerPoint. Answers every command with
# "STATE <slide index> <view state> <show position>", or "ENDED".
POWERSHELL_SHOW = r"""
$ErrorActionPreference = 'Stop'
function Say($text) { [Console]::Out.WriteLine($text); [Console]::Out.Flush() }
# PowerPoint may still be closing down after an earlier use (it takes seconds);
# an Open on that instance fails at once. Let it go, then start a fresh one.
$app = $null; $pres = $null
for ($try = 0; $pres -eq $null; $try++) {
  try {
    $app = New-Object -ComObject PowerPoint.Application
    $pres = $app.Presentations.Open($env:SDC_SRC, -1, 0, 0)
  } catch {
    if ($try -ge 40) { throw }
    try { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($app) } catch { }
    $app = $null
    Start-Sleep -Milliseconds 500
  }
}
$show = $null
function State {
  try { $v = $show.View; Say ("STATE " + $v.Slide.SlideIndex + " " + $v.State + " " + $v.CurrentShowPosition) }
  catch { Say "ENDED" }
}
try {
  $settings = $pres.SlideShowSettings
  $settings.ShowType = 1
  $settings.ShowPresenterView = 0
  $settings.LoopUntilStopped = 0
  $show = $settings.Run()
  if ($env:SDC_PW) {
    # onto the stage screen the operator chose (points = logical pixels x 0.75)
    $show.Left = [double]$env:SDC_PX; $show.Top = [double]$env:SDC_PY
    $show.Width = [double]$env:SDC_PW; $show.Height = [double]$env:SDC_PH
  }
  # the last slide the audience sees; NEXT stops there instead of PowerPoint's
  # "End of slide show" screen
  $last = 1
  foreach ($slide in $pres.Slides) { if (-not $slide.SlideShowTransition.Hidden) { $last = $slide.SlideIndex } }
  Say "READY"
  $start = [int]$env:SDC_START
  if ($start -gt 1) { $show.View.GotoSlide($start) }
  State
  $done = $false
  while (-not $done) {
    $line = [Console]::In.ReadLine()
    if ($line -eq $null) { break }
    $cmd = $line.Trim()
    try {
      if ($cmd -eq 'next') {
        $v = $show.View
        $finished = $false
        try { $finished = $v.GetClickIndex() -ge $v.GetClickCount() } catch { }
        if ($v.State -eq 5 -or ($v.Slide.SlideIndex -ge $last -and $finished)) { Say "EDGE" } else { $v.Next() }
      }
      elseif ($cmd -eq 'prev') { $show.View.Previous() }
      elseif ($cmd -match '^goto (\d+)$') { $show.View.GotoSlide([int]$matches[1]) }
      elseif ($cmd -eq 'black') { $show.View.State = 3 }
      elseif ($cmd -eq 'unblack') { $show.View.State = 1 }
      elseif ($cmd -eq 'end') { $show.View.Exit(); $done = $true }
    } catch { }
    if ($done) { Say "ENDED" } else { State }
  }
} finally {
  try { if ($show -ne $null) { $show.View.Exit() } } catch { }
  try { $pres.Close() } catch { }
  # not $app.Quit(): see the export script
}
"""


class Deck(QObject):
    """One presentation, as a list of full-screen pictures on disk."""

    progress = Signal()          # the count is known, or more slides are ready
    failed = Signal(str)

    def __init__(self, path: str, size: QSize, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.path = os.path.normpath(path)
        self.name = os.path.splitext(os.path.basename(self.path.rstrip("\\/")))[0] or self.path
        self.size = size
        self.count = 0
        self.pages: List[Optional[str]] = []
        self.notes: List[str] = []
        self.done = False
        self.error = ""
        self._pdf = None
        self._process: Optional[QProcess] = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._render_next)
        self._thumbs: Dict[tuple, QPixmap] = {}
        self._jpegs: Dict[tuple, bytes] = {}
        ext = os.path.splitext(self.path)[1].lower()
        if os.path.isdir(self.path):
            self.kind = "images"
        elif ext in PDF_EXTENSIONS:
            self.kind = "pdf"
        elif ext in POWERPOINT_EXTENSIONS:
            self.kind = "powerpoint"
        elif ext in IMAGE_EXTENSIONS:
            self.kind = "images"
        else:
            self.kind = "unknown"
        try:
            info = os.stat(self.path)
            stamp = f"{info.st_mtime_ns}|{info.st_size}"
        except OSError:
            stamp = "missing"
        self.indexes: List[int] = []     # PowerPoint's own slide numbers of the visible slides
        key = f"{os.path.normcase(self.path)}|{stamp}|{size.width()}x{size.height()}|v2"
        self.token = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        self.dir = os.path.join(cache_root(), self.token)

    # -- loading ------------------------------------------------------------- #
    def start(self) -> Optional[str]:
        """Begin preparing the slides; returns an error message if it cannot."""
        if self.kind == "unknown":
            return tr('Open a PDF, a PowerPoint file, or a folder of pictures.')
        if not os.path.exists(self.path):
            return tr("{0} is missing.").format(os.path.basename(self.path))
        if self.kind == "images":
            folder = self.path if os.path.isdir(self.path) else None
            files = ([os.path.join(folder, f) for f in sorted(os.listdir(folder), key=_natural)
                      if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS] if folder else [self.path])
            if not files:
                return tr('That folder has no pictures in it.')
            self.pages = files
            self.count = len(files)
            self.notes = [""] * self.count
            self.done = True
            self.progress.emit()
            return None
        if self._load_cache():
            return None
        os.makedirs(self.dir, exist_ok=True)
        if self.kind == "pdf":
            if QPdfDocument is None:
                return tr('PDF support (QtPdf) is not installed.')
            self._pdf = QPdfDocument(self)
            status = self._pdf.load(self.path)
            if status != QPdfDocument.Error.None_ or self._pdf.pageCount() <= 0:
                return tr('This PDF could not be opened ({0}).').format(getattr(status, 'name', status))
            self.count = self._pdf.pageCount()
            self.pages = [None] * self.count
            self.notes = [""] * self.count
            self._timer.start(0)
            self.progress.emit()
            return None
        if not powerpoint_available():
            return (tr('PowerPoint is not installed on this PC. In PowerPoint on another computer use File → Save as → PDF, and open the PDF here.'))
        self._convert_powerpoint()
        return None

    def _load_cache(self) -> bool:
        marker = os.path.join(self.dir, "complete.json")
        try:
            with open(marker, encoding="utf-8") as handle:
                data = json.load(handle)
            pages = [os.path.join(self.dir, f"page-{i + 1:04d}.png") for i in range(int(data["count"]))]
            if not pages or not all(os.path.isfile(p) for p in pages):
                return False
            self.pages, self.count = pages, len(pages)
            notes = list(data.get("notes") or [])
            self.notes = (notes + [""] * self.count)[: self.count]
            self.indexes = [int(i) for i in (data.get("indexes") or [])]
            self.done = True
            QTimer.singleShot(0, self.progress.emit)
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def _finish(self) -> None:
        self.done = True
        try:
            with open(os.path.join(self.dir, "complete.json"), "w", encoding="utf-8") as handle:
                json.dump({"count": self.count, "notes": self.notes, "indexes": self.indexes,
                           "source": self.path}, handle, ensure_ascii=False)
        except OSError:
            pass
        self.progress.emit()

    # -- PDF ----------------------------------------------------------------- #
    def _render_pdf(self, index: int) -> Optional[str]:
        if self._pdf is None:
            return None
        page = self._pdf.pagePointSize(index)
        if page.isEmpty():
            page = QSizeF(16, 9)
        scale = min(self.size.width() / page.width(), self.size.height() / page.height())
        target = QSize(max(1, round(page.width() * scale)), max(1, round(page.height() * scale)))
        image = self._pdf.render(index, target)
        canvas = QImage(target, QImage.Format_RGB32)
        canvas.fill(QColor("white"))            # PDF pages are white paper, not transparent
        painter = QPainter(canvas)
        painter.drawImage(0, 0, image)
        painter.end()
        path = os.path.join(self.dir, f"page-{index + 1:04d}.png")
        canvas.save(path, "PNG")
        self.pages[index] = path
        return path

    def _render_next(self) -> None:
        missing = [i for i, p in enumerate(self.pages) if p is None]
        if not missing:
            self._timer.stop()
            self._finish()
            return
        self._render_pdf(missing[0])
        self.progress.emit()

    # -- PowerPoint ---------------------------------------------------------- #
    def _convert_powerpoint(self) -> None:
        process = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("SDC_SRC", self.path)
        env.insert("SDC_DIR", self.dir)
        env.insert("SDC_W", str(self.size.width()))
        env.insert("SDC_H", str(self.size.height()))
        process.setProcessEnvironment(env)
        process.readyReadStandardOutput.connect(self._on_output)
        process.finished.connect(self._on_converted)
        keep_powerpoint_ready()
        encoded = base64.b64encode(POWERSHELL_EXPORT.encode("utf-16-le")).decode("ascii")
        process.start("powershell.exe", ["-NoProfile", "-NonInteractive", "-EncodedCommand", encoded])
        self._process = process

    def _on_output(self) -> None:
        text = bytes(self._process.readAllStandardOutput().data()).decode("utf-8", "replace")
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("COUNT "):
                self.count = int(line.split()[1])
                self.pages = [None] * self.count
                self.notes = [""] * self.count
            elif line.startswith("PAGE "):
                index = int(line.split()[1]) - 1
                if 0 <= index < self.count:
                    self.pages[index] = os.path.join(self.dir, f"page-{index + 1:04d}.png")
            self.progress.emit()

    def _on_converted(self, code: int, _status) -> None:
        self._on_output()
        if code != 0 or not self.count or not all(self.pages):
            raw = bytes(self._process.readAllStandardError().data()).decode("utf-8", "replace")
            # PowerShell reports errors as CLIXML; keep just the sentence PowerPoint said
            lines = re.findall(r'<S S="Error">(.*?)</S>', raw) or raw.splitlines()
            message = " ".join(lines).replace("_x000D__x000A_", " ").strip()
            message = re.sub(r"\s+", " ", message.split(" At line:")[0])[:300]
            self.error = "PowerPoint could not convert this file." + (f" {message}" if message else "")
            self.failed.emit(self.error)
            return
        try:
            with open(os.path.join(self.dir, "notes.json"), encoding="utf-8-sig") as handle:
                notes = json.load(handle)
            notes = [notes] if isinstance(notes, str) else list(notes or [])
            self.notes = [str(n or "").replace("\r", "\n").strip() for n in notes][: self.count]
            self.notes += [""] * (self.count - len(self.notes))
        except (OSError, ValueError):
            pass
        try:
            with open(os.path.join(self.dir, "indexes.json"), encoding="utf-8-sig") as handle:
                indexes = json.load(handle)
            self.indexes = [int(i) for i in ([indexes] if isinstance(indexes, int) else indexes)]
        except (OSError, ValueError, TypeError):
            self.indexes = []
        self._finish()

    def position_of(self, slide_index: int) -> Optional[int]:
        """Our slide number (0-based) for PowerPoint's slide number, if it is a visible one."""
        if slide_index in self.indexes:
            return self.indexes.index(slide_index)
        return None if self.indexes else slide_index - 1

    def slide_index(self, position: int) -> int:
        """PowerPoint's slide number for our position."""
        return self.indexes[position] if 0 <= position < len(self.indexes) else position + 1

    def stop(self) -> None:
        self._timer.stop()
        if self._process is not None and self._process.state() != QProcess.NotRunning:
            self._process.kill()

    # -- access -------------------------------------------------------------- #
    def ready_count(self) -> int:
        return sum(1 for p in self.pages if p)

    def ensure(self, index: int) -> Optional[str]:
        """The slide's picture, rendering a PDF page right now if it is not ready."""
        if not 0 <= index < self.count:
            return None
        if self.pages[index] is None and self.kind == "pdf":
            self._render_pdf(index)
            self.progress.emit()
        return self.pages[index]

    def thumb(self, index: int, width: int) -> Optional[QPixmap]:
        key = (index, width)
        if key not in self._thumbs:
            path = self.pages[index] if 0 <= index < self.count else None
            if not path:
                return None
            reader = QImageReader(path)
            size = reader.size()
            if size.isValid() and size.width() > width:
                reader.setScaledSize(size.scaled(width, width * 4, Qt.KeepAspectRatio))
            image = reader.read()
            if image.isNull():
                return None
            self._thumbs[key] = QPixmap.fromImage(image)
        return self._thumbs[key]

    def jpeg(self, index: int, width: int = 960) -> Optional[bytes]:
        """A small JPEG of a slide, for the phone."""
        key = (index, width)
        if key not in self._jpegs:
            path = self.ensure(index)
            if not path:
                return None
            reader = QImageReader(path)
            size = reader.size()
            if size.isValid() and size.width() > width:
                reader.setScaledSize(size.scaled(width, width * 4, Qt.KeepAspectRatio))
            image = reader.read()
            if image.isNull():
                return None
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.WriteOnly)
            image.save(buffer, "JPG", 82)
            self._jpegs[key] = bytes(data.data())
        return self._jpegs[key]


# One small process holds on to PowerPoint while the app runs. Without it,
# PowerPoint shuts itself down each time a slide show or an export lets go of
# it - which takes seconds, and a show started meanwhile attaches to the
# instance that is going away and never starts. When the app closes (or dies)
# its pipe closes, the keeper lets go, and PowerPoint - if nobody else is using
# it - closes by itself. A PowerPoint the operator opened is never closed.
POWERSHELL_KEEPER = r"""
$app = New-Object -ComObject PowerPoint.Application
[void][Console]::In.ReadLine()
"""
_keeper: Optional[subprocess.Popen] = None


def keep_powerpoint_ready() -> None:
    global _keeper
    if _keeper is not None and _keeper.poll() is None:
        return
    if not powerpoint_available():
        return
    encoded = base64.b64encode(POWERSHELL_KEEPER.encode("utf-16-le")).decode("ascii")
    try:
        _keeper = subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        _keeper = None


def release_powerpoint() -> None:
    """The app is closing: let PowerPoint go (it closes once nothing else holds it)."""
    global _keeper
    if _keeper is not None:
        try:
            _keeper.stdin.close()
        except (OSError, ValueError):
            pass
        _keeper = None


class PowerPointShow(QObject):
    """
    A real PowerPoint slideshow on a stage screen, driven over a PowerShell
    pipe: next / prev / goto / black go to PowerPoint itself, so animations and
    transitions play exactly as the author made them. PowerPoint's own state is
    read back several times a second, so keys pressed in PowerPoint (or slide
    timings) are followed too.

    A plain OS pipe (subprocess), not QProcess: PowerShell's [Console]::In never
    sees what QProcess writes on Windows.
    """

    started = Signal()
    state = Signal(int, int)      # PowerPoint's slide number, view state (3 = black, 5 = finished)
    ended = Signal()
    edge = Signal()               # NEXT on the last slide, all its animations played
    failed = Signal(str)
    _line = Signal(str)           # from the reader thread
    _eof = Signal(str)

    def __init__(self, path: str, points: Optional[QRectF], start_slide: int,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.running = False
        self._over = False
        self._queued: List[str] = []      # presses made while PowerPoint was still starting
        env = dict(os.environ, SDC_SRC=path, SDC_START=str(max(1, start_slide)))
        if points is not None:
            env.update(SDC_PX=f"{points.x():.2f}", SDC_PY=f"{points.y():.2f}",
                       SDC_PW=f"{points.width():.2f}", SDC_PH=f"{points.height():.2f}")
        self._line.connect(self._on_line)
        self._eof.connect(self._on_eof)
        self._poll = QTimer(self)
        self._poll.timeout.connect(lambda: self.send("state"))
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(self._too_slow)
        keep_powerpoint_ready()
        encoded = base64.b64encode(POWERSHELL_SHOW.encode("utf-16-le")).decode("ascii")
        try:
            self.process: Optional[subprocess.Popen] = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as error:
            self.process = None
            QTimer.singleShot(0, lambda: self._fail(tr("PowerShell could not start: {0}").format(error)))
            return
        threading.Thread(target=self._read, daemon=True).start()
        self._deadline.start(45000)

    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def send(self, command: str) -> None:
        if not self.running:
            if not self._over and command != "state":
                self._queued = (self._queued + [command])[-20:]
            return
        if self.alive():
            try:
                self.process.stdin.write((command + "\n").encode("ascii"))
                self.process.stdin.flush()
            except (OSError, ValueError):
                pass

    def stop(self) -> None:
        """End the slide show (quietly: no ended / failed from here on)."""
        self._over = True
        self._poll.stop()
        self._deadline.stop()
        if not self.alive():
            return
        if self.running:
            self.send("end")
            self._close_input()                   # the script tidies up and quits PowerPoint
            QTimer.singleShot(5000, self._kill)
        else:
            self._kill()                          # still opening: nothing to tidy
        self.running = False

    def _close_input(self) -> None:
        try:
            self.process.stdin.close()
        except (OSError, ValueError):
            pass

    def _kill(self) -> None:
        if self.alive():
            self.process.kill()

    def _read(self) -> None:
        """Reader thread: every line to the GUI thread, then whatever went wrong."""
        process = self.process
        for raw in process.stdout:
            self._line.emit(raw.decode("utf-8", "replace").strip())
        try:
            error = process.stderr.read().decode("utf-8", "replace")
        except (OSError, ValueError):
            error = ""
        self._eof.emit(error)

    def _on_line(self, line: str) -> None:
        if line == "READY":
            self.running = not self._over
            self._deadline.stop()
            if self.running:
                self._poll.start(400)
                self.started.emit()
                queued, self._queued = self._queued, []
                for command in queued:
                    self.send(command)
        elif line.startswith("STATE "):
            parts = line.split()
            try:
                self.state.emit(int(parts[1]), int(parts[2]))
            except (IndexError, ValueError):
                pass
        elif line == "EDGE":
            self.edge.emit()
        elif line == "ENDED":
            self._end()

    def _on_eof(self, error: str) -> None:
        if not self.running and not self._over:
            lines = re.findall(r'<S S="Error">(.*?)</S>', error) or \
                [l for l in error.splitlines() if l.strip() and not l.startswith("#< CLIXML")]
            message = re.sub(r"\s+", " ", " ".join(lines).replace("_x000D__x000A_", " ")).strip()
            self._fail("PowerPoint could not start the slide show." +
                       (f" {message.split(' At line:')[0][:200]}" if message else ""))
            return
        self._end()

    def _fail(self, message: str) -> None:
        if not self._over:
            self._over = True
            self.failed.emit(message)

    def _too_slow(self) -> None:
        if not self.running:
            self._kill()
            self._fail("PowerPoint did not start the slide show in time.")

    def _end(self) -> None:
        self._poll.stop()
        was_running, self.running = self.running, False
        if self.alive():
            self._close_input()                   # the show is over: let the script close the file
            QTimer.singleShot(5000, self._kill)
        if not self._over:
            self._over = True
            if was_running:
                self.ended.emit()


class Presenter(QObject):
    """
    Which slide, whether it is on stage, and whether the stage is blacked out.

    `stage` is the dashboard's side: present(role, path, fade_ms) -> error or
    None, clear(role, fade_ms), restore(role, fade_ms), label(role),
    size(role) -> QSize, points(role) -> QRectF of the screen in PowerPoint
    points, make_room(role) / give_back_room(role) for windows kept on top.

    PowerPoint files play in PowerPoint itself when `in_powerpoint` is set, so
    their animations survive; PDFs and pictures are shown as pictures.
    """

    changed = Signal()
    note = Signal(str)

    def __init__(self, stage, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.stage = stage
        self.deck: Optional[Deck] = None
        self.index = 0
        self.live = False
        self.black = False
        self.role = "main"
        self.fade_ms = 250
        self.started = 0.0
        self.in_powerpoint = True
        self.rehearsing = False             # rehearsal: pictures, PowerPoint would open on the stage first
        self.show: Optional[PowerPointShow] = None
        self.at_end = False
        self._seen = None
        self._waiting = False
        self._live_when_ready: Optional[str] = None

    # -- deck ---------------------------------------------------------------- #
    def open(self, path: str) -> Optional[str]:
        deck = Deck(path, self.stage.size(self.role), self)
        deck.progress.connect(self._on_progress)
        deck.failed.connect(self._on_failed)
        error = deck.start()
        if error:
            deck.deleteLater()
            return error
        was_live, role = self.live, self.role
        if self.live:
            self.end()
        if self.deck is not None:
            self.deck.stop()
            self.deck.deleteLater()
        self.deck = deck
        self.index = 0
        if was_live:
            self.go_live_when_ready(role)
        self.changed.emit()
        return None

    def count(self) -> int:
        return self.deck.count if self.deck else 0

    def notes(self, index: Optional[int] = None) -> str:
        index = self.index if index is None else index
        if self.deck and 0 <= index < len(self.deck.notes):
            return self.deck.notes[index]
        return ""

    def playing_in_powerpoint(self) -> bool:
        return self.show is not None

    def can_go_live(self) -> bool:
        return bool(self.count()) or self._wants_powerpoint()

    def _wants_powerpoint(self) -> bool:
        return bool(self.in_powerpoint and not self.rehearsing and self.deck is not None
                    and self.deck.kind == "powerpoint" and powerpoint_available())

    def _on_progress(self) -> None:
        if self._live_when_ready and (self.count() or self._wants_powerpoint()):
            role, self._live_when_ready = self._live_when_ready, None
            self.go_live(role)
            return
        if self._waiting and self.live and not self.black and self.deck and self.deck.pages[self.index]:
            self._show()
        self.changed.emit()

    def go_live_when_ready(self, role: str) -> None:
        """Go on screen now, or as soon as a converting deck knows its slides."""
        if self.count() or self._wants_powerpoint():
            self.go_live(role)
        else:
            self._live_when_ready = role

    def release(self) -> None:
        """Something else took over the screen: no longer live, and nothing to restore."""
        if self.live:
            self._stop_show()
            self.live = False
            self.black = False
            self._waiting = False
            self.changed.emit()

    def _on_failed(self, message: str) -> None:
        self.note.emit(message)
        self.changed.emit()

    # -- moving -------------------------------------------------------------- #
    def goto(self, index: int) -> None:
        if not self.count():
            return
        self.index = max(0, min(index, self.count() - 1))
        if self.show is not None:
            self.black = False
            self.show.send(f"goto {self.deck.slide_index(self.index)}")
        elif self.live:
            self.black = False
            self._show()
        self.changed.emit()

    def next(self) -> bool:
        if self.show is not None:
            # PowerPoint decides: the next animation, or the next slide
            self.show.send("unblack" if self.black else "next")
            return True
        if self.live and self.black:          # like PowerPoint: first press lifts the black
            self.black = False
            self._show()
            self.changed.emit()
            return True
        if self.index + 1 >= self.count():
            self.note.emit(tr('Last slide.'))
            return False
        self.goto(self.index + 1)
        return True

    def back(self) -> bool:
        if self.show is not None:
            self.show.send("unblack" if self.black else "prev")
            return True
        if self.live and self.black:
            self.black = False
            self._show()
            self.changed.emit()
            return True
        if self.index <= 0:
            return False
        self.goto(self.index - 1)
        return True

    def toggle_black(self) -> None:
        if not self.live:
            return
        self.black = not self.black
        if self.show is not None:
            self.show.send("black" if self.black else "unblack")
        elif self.black:
            self.stage.clear(self.role, 200)
        else:
            self._show()
        self.changed.emit()

    # -- on stage ------------------------------------------------------------ #
    def go_live(self, role: Optional[str] = None, restart: bool = False) -> None:
        if not self.can_go_live():
            self.note.emit(tr('Open a presentation first.'))
            return
        if self.live and ((role and role != self.role) or restart):
            self.end()
        if role:
            self.role = role
        if not self.live:
            self.started = time.monotonic()
        self.live = True
        self.black = False
        if self._wants_powerpoint():
            if self.show is None:
                self._start_show()
        else:
            self._show()
        self.changed.emit()

    def end(self) -> None:
        if not self.live:
            return
        in_powerpoint = self.show is not None
        self._stop_show()
        self.live = False
        self.black = False
        self._waiting = False
        if in_powerpoint:
            self.stage.give_back_room(self.role)     # the background never left its screen
        else:
            self.stage.restore(self.role, self.fade_ms)
        self.changed.emit()

    def _show(self) -> None:
        path = self.deck.ensure(self.index) if self.deck else None
        if not path:
            self._waiting = True              # PowerPoint still converting: shown when ready
            self.note.emit(tr('Preparing that slide…'))
            return
        self._waiting = False
        error = self.stage.present(self.role, path, self.fade_ms)
        if error:
            self.note.emit(error)

    # -- PowerPoint itself --------------------------------------------------- #
    def _start_show(self) -> None:
        self.stage.make_room(self.role)
        show = PowerPointShow(self.deck.path, self.stage.points(self.role),
                              self.deck.slide_index(self.index), self)
        show.state.connect(self._on_show_state)
        show.ended.connect(self._on_show_ended)
        show.edge.connect(lambda: self.note.emit(tr('Last slide.')))
        show.failed.connect(self._on_show_failed)
        show.started.connect(lambda: self.note.emit(tr('Playing in PowerPoint - animations included.')))
        show.started.connect(self.stage.refocus)
        self.show = show
        self.at_end = False
        self._seen = None
        self.note.emit(tr('Starting PowerPoint…'))

    def _stop_show(self) -> None:
        show, self.show = self.show, None
        if show is not None:
            show.stop()                           # quiet from here on: no ended / failed
            QTimer.singleShot(6000, show.deleteLater)

    def _on_show_state(self, slide_index: int, view_state: int) -> None:
        if self.deck is not None:
            position = self.deck.position_of(slide_index)
            if position is not None and position >= 0 and (not self.count() or position < self.count()):
                self.index = position
        self.at_end = view_state == 5             # past the last slide: PowerPoint's black end screen
        self.black = view_state == 3
        seen = (self.index, self.black, view_state)
        if seen != self._seen:
            self._seen = seen
            self.changed.emit()

    def _on_show_ended(self) -> None:
        """Someone pressed Esc in PowerPoint, or it was closed."""
        if self.show is not None:
            self.show = None
            if self.live:
                self.live = False
                self.black = False
                self.stage.give_back_room(self.role)
                self.note.emit(tr("PowerPoint's slide show was closed."))
                self.changed.emit()

    def _on_show_failed(self, message: str) -> None:
        self.show = None
        self.stage.give_back_room(self.role)
        if self.live and self.count():
            self.note.emit(message + tr(' Showing the slides as pictures instead (no animations).'))
            self._show()
        else:
            self.live = False
            self.note.emit(message)
        self.changed.emit()

    def elapsed(self) -> float:
        return time.monotonic() - self.started if self.live else 0.0


# --------------------------------------------------------------------------- #
# Widgets
# --------------------------------------------------------------------------- #

def _font(size: float, weight: int = QFont.Normal) -> QFont:
    font = QFont("Segoe UI")
    font.setPointSizeF(size)
    font.setWeight(QFont.Weight(weight))
    return font


class SlideView(QWidget):
    """A slide scaled to fit, with a badge in the corner."""

    clicked = Signal()

    def __init__(self, theme: dict, placeholder: str) -> None:
        super().__init__()
        self.theme = theme
        self.placeholder = placeholder
        self.pixmap: Optional[QPixmap] = None
        self.badge = ""
        self.badge_colour = theme["muted"]
        self.dimmed = False
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(160, 90)

    def show_slide(self, pixmap: Optional[QPixmap], badge: str = "", colour: Optional[str] = None,
                   dimmed: bool = False) -> None:
        self.pixmap, self.badge, self.dimmed = pixmap, badge, dimmed
        self.badge_colour = colour or self.theme["muted"]
        self.update()

    def mousePressEvent(self, _event) -> None:  # noqa: N802
        self.clicked.emit()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        area = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(self.theme["edge"]), 1))
        p.setBrush(QColor("#07090d"))
        p.drawRoundedRect(area, 10, 10)
        if self.pixmap is not None and not self.pixmap.isNull():
            size = self.pixmap.size().scaled(int(area.width()) - 12, int(area.height()) - 12, Qt.KeepAspectRatio)
            target = QRectF(area.center().x() - size.width() / 2, area.center().y() - size.height() / 2,
                            size.width(), size.height())
            p.drawPixmap(target.toRect(), self.pixmap)
            if self.dimmed:
                p.fillRect(target, QColor(0, 0, 0, 170))
        else:
            p.setPen(QColor(self.theme["muted"]))
            p.setFont(_font(10))
            p.drawText(area, Qt.AlignCenter, tr(self.placeholder))
        if self.badge:
            p.setFont(_font(8, QFont.Bold))
            width = p.fontMetrics().horizontalAdvance(self.badge) + 22
            tag = QRectF(area.left() + 10, area.top() + 10, width, 24)
            colour = QColor(self.badge_colour)
            fill = QColor(colour)
            fill.setAlpha(60)
            p.setPen(QPen(colour, 1))
            p.setBrush(fill)
            p.drawRoundedRect(tag, 12, 12)
            p.setPen(colour.lighter(130))
            p.drawText(tag, Qt.AlignCenter, self.badge)


class LearnDialog(QDialog):
    """Press the clicker's buttons once; whatever keys it sends are remembered."""

    def __init__(self, theme: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr('Learn the clicker'))
        self.setMinimumWidth(460)
        self.steps = [("next", "NEXT (forward)"), ("back", "BACK"), ("black", "BLACK screen (optional)")]
        self.learned: Dict[str, dict] = {}
        self._at = 0
        box = QVBoxLayout(self)
        box.setContentsMargins(22, 20, 22, 20)
        box.setSpacing(12)
        self.prompt = QLabel()
        self.prompt.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {theme['accent']};")
        self.prompt.setWordWrap(True)
        box.addWidget(self.prompt)
        self.heard = QLabel("")
        self.heard.setObjectName("cardHint")
        self.heard.setWordWrap(True)
        box.addWidget(self.heard)
        row = QHBoxLayout()
        skip = QPushButton(tr('Skip'))
        skip.setFocusPolicy(Qt.NoFocus)
        skip.clicked.connect(self._advance)
        row.addWidget(skip)
        row.addStretch(1)
        cancel = QPushButton(tr('Cancel'))
        cancel.setFocusPolicy(Qt.NoFocus)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        box.addLayout(row)
        self._show_prompt()

    def _show_prompt(self) -> None:
        if self._at >= len(self.steps):
            self.accept()
            return
        self.prompt.setText(tr("Press the clicker's {0} button").format(self.steps[self._at][1]))

    def _advance(self) -> None:
        self._at += 1
        self._show_prompt()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta) or event.isAutoRepeat():
            return
        from PySide6.QtGui import QKeySequence
        name = QKeySequence(key).toString() or f"key {key}"
        action = self.steps[self._at][0]
        self.learned[action] = {"key": int(key), "vk": int(event.nativeVirtualKey()), "name": name}
        self.heard.setText(self.heard.text() + f"{self.steps[self._at][1]}: {name}\n")
        self._advance()


class PresentationTab(QWidget):
    """Current and next slide, notes, timer, thumbnails, and the clicker."""

    learnRequested = Signal()
    guestRequested = Signal()
    globalToggled = Signal(bool)
    powerpointToggled = Signal(bool)
    limitChanged = Signal(int)              # minutes, 0 = no limit
    countdownTargetChanged = Signal(str)    # a screen, or "" for none
    countdown = Signal(str, str, str)       # screen, text ("" = take it away), colour

    def __init__(self, presenter: Presenter, icons, theme: dict, role_labels: Dict[str, str],
                 touch: bool = False) -> None:
        super().__init__()
        self.presenter = presenter
        self.icons = icons
        self.theme = theme
        self.role_labels = role_labels
        self._thumb_width = 156
        self._last_key = ("", "", 0.0)
        self._deck_shown = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 10, 0, 0)
        outer.setSpacing(10)
        outer.addWidget(self._build_bar())

        body = QHBoxLayout()
        body.setSpacing(10)
        self.current = SlideView(theme, "Open a PDF or PowerPoint file")
        self.current.clicked.connect(self.presenter.next)
        body.addWidget(self.current, 3)

        side = QFrame()
        side.setObjectName("card")
        column = QVBoxLayout(side)
        column.setContentsMargins(16, 14, 16, 14)
        column.setSpacing(8)
        top = QHBoxLayout()
        self.counter = QLabel("– / –")
        self.counter.setStyleSheet("font-size: 26px; font-weight: 800;")
        top.addWidget(self.counter)
        top.addStretch(1)
        self.clock = QLabel("")
        self.clock.setObjectName("timecode")
        self.clock.setStyleSheet("font-size: 15px;")
        column.addLayout(top)
        limit_row = top                      # one row: counter, limit, countdown, clock
        limit_row.setSpacing(6)
        caption = QLabel(tr('Limit'))
        caption.setObjectName("cardHint")
        limit_row.addWidget(caption)
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 240)
        self.limit_spin.setSuffix(tr(' min'))
        self.limit_spin.setSpecialValueText(tr('none'))
        self.limit_spin.setToolTip(tr('How long the speaker has. The clock above counts down, amber in the last\ntwo minutes, red once over.'))
        self.limit_spin.valueChanged.connect(self._on_limit)
        limit_row.addWidget(self.limit_spin)
        self.countdown_combo = QComboBox()
        self.countdown_combo.addItem(tr('countdown: desk only'), "")
        for role, label in role_labels.items():
            self.countdown_combo.addItem(tr('countdown on {0}').format(label), role)
        self.countdown_combo.setToolTip(tr('Also show the time left, small in the corner of a stage screen\nthe speaker can see (not the one a PowerPoint show covers)'))
        self.countdown_combo.currentIndexChanged.connect(self._on_countdown_target)
        limit_row.addWidget(self.countdown_combo)
        limit_row.addSpacing(10)
        limit_row.addWidget(self.clock)
        self.limit_minutes = 0
        self.countdown_role = ""
        self._countdown_shown = ("", "", "")
        caption = QLabel(tr('NEXT SLIDE'))
        caption.setObjectName("sectionTitle")
        column.addWidget(caption)
        self.upcoming = SlideView(theme, "—")
        self.upcoming.setMinimumHeight(110)
        self.upcoming.setMaximumHeight(230)
        column.addWidget(self.upcoming, 2)
        caption = QLabel(tr('NOTES'))
        caption.setObjectName("sectionTitle")
        column.addWidget(caption)
        self.notes = QLabel("")
        self.notes.setWordWrap(True)
        self.notes.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.notes.setStyleSheet("font-size: 14px;")
        notes_scroll = QScrollArea()
        notes_scroll.setWidgetResizable(True)
        notes_scroll.setFrameShape(QFrame.NoFrame)
        notes_scroll.setWidget(self.notes)
        notes_scroll.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }")
        column.addWidget(notes_scroll, 1)
        nav = QHBoxLayout()
        nav.setSpacing(8)
        back = QPushButton(tr('  Back'))
        back.setIcon(icons.get("prev", theme["text"], 16))
        back.setMinimumHeight(52)
        back.setToolTip(tr('Previous slide  (clicker back, Page Up, ←)'))
        back.clicked.connect(self.presenter.back)
        nav.addWidget(back, 2)
        self.next_btn = QPushButton(tr('  NEXT'))
        self.next_btn.setObjectName("primary")
        self.next_btn.setIcon(icons.get("next", "#0b0e13", 20))
        self.next_btn.setIconSize(QSize(20, 20))
        self.next_btn.setMinimumHeight(52)
        self.next_btn.setStyleSheet("font-size: 17px; font-weight: 700;")
        self.next_btn.setToolTip(tr('Next slide  (clicker forward, Page Down, →, Space)'))
        self.next_btn.clicked.connect(self.presenter.next)
        nav.addWidget(self.next_btn, 3)
        column.addLayout(nav)
        stage_row = QHBoxLayout()
        stage_row.setSpacing(8)
        self.live_btn = HoldButton("", theme)       # ending a talk by accident: hold to end
        self.live_btn.setMinimumHeight(46)
        self.live_btn.clicked.connect(self._toggle_live)
        stage_row.addWidget(self.live_btn, 3)
        self.black_btn = QPushButton(tr('  Black'))
        self.black_btn.setCheckable(True)
        self.black_btn.setMinimumHeight(46)
        self.black_btn.setToolTip(tr('Black out the presentation screen  (clicker black, B)'))
        self.black_btn.clicked.connect(lambda: self.presenter.toggle_black())
        stage_row.addWidget(self.black_btn, 2)
        column.addLayout(stage_row)
        body.addWidget(side, 2)
        outer.addLayout(body, 1)

        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListView.IconMode)
        self.thumbs.setFlow(QListView.LeftToRight)
        self.thumbs.setWrapping(False)
        self.thumbs.setMovement(QListView.Static)
        self.thumbs.setIconSize(QSize(self._thumb_width, self._thumb_width * 9 // 16))
        self.thumbs.setFixedHeight(self._thumb_width * 9 // 16 + 62)
        self.thumbs.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.thumbs.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.thumbs.setSpacing(4)
        self.thumbs.itemClicked.connect(lambda item: self.presenter.goto(self.thumbs.row(item)))
        outer.addWidget(self.thumbs)
        outer.addWidget(self._build_clicker_bar())

        self.presenter.changed.connect(self.refresh)
        ticker = QTimer(self)
        ticker.timeout.connect(self._tick)
        ticker.start(1000)
        self.refresh()

    # -- building ------------------------------------------------------------ #
    def _build_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("bar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(8)
        open_file = QPushButton(tr('  Open…'))
        open_file.setIcon(self.icons.get("folder", self.theme["text"], 15))
        open_file.setToolTip(tr('A PDF or PowerPoint file'))
        open_file.clicked.connect(self._open_file)
        row.addWidget(open_file)
        open_folder = QPushButton(tr('  Folder of pictures…'))
        open_folder.setIcon(self.icons.get("image", self.theme["text"], 15))
        open_folder.clicked.connect(self._open_folder)
        row.addWidget(open_folder)
        self.recent = QComboBox()
        self.recent.setMinimumWidth(240)
        self.recent.setToolTip(tr('Recently opened'))
        self.recent.activated.connect(self._open_recent)
        row.addWidget(self.recent)
        row.addSpacing(10)
        row.addWidget(QLabel(tr('Screen')))
        self.target = QComboBox()
        for role, label in self.role_labels.items():
            self.target.addItem(label, role)
        self.target.setToolTip(tr('Which screen the slides appear on'))
        self.target.currentIndexChanged.connect(self._on_target)
        row.addWidget(self.target)
        row.addWidget(QLabel(tr('Change')))
        self.transition = QComboBox()
        for caption, ms in TRANSITIONS:
            self.transition.addItem(tr(caption), ms)
        self.transition.currentIndexChanged.connect(
            lambda: setattr(self.presenter, "fade_ms", int(self.transition.currentData())))
        row.addWidget(self.transition)
        self.powerpoint_check = QCheckBox(tr('PowerPoint animations'))
        self.powerpoint_check.setToolTip(
            tr('On: PowerPoint files play in PowerPoint itself on the stage screen, so animations,\nvideos and slide transitions work. NEXT, the clicker and the phone drive it.\nOff: they are shown as still pictures (PDFs always are).'))
        self.powerpoint_check.setChecked(self.presenter.in_powerpoint)
        self.powerpoint_check.setEnabled(powerpoint_available())
        self.powerpoint_check.toggled.connect(self._on_powerpoint)
        row.addWidget(self.powerpoint_check)
        row.addStretch(1)
        self.status = QLabel("")
        self.status.setObjectName("cardHint")
        row.addWidget(self.status)
        return bar

    def _build_clicker_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("bar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(10)
        caption = QLabel(tr('Clicker'))
        caption.setObjectName("sectionTitle")
        row.addWidget(caption)
        self.key_label = QLabel(tr('press a clicker button to test it'))
        self.key_label.setObjectName("cardHint")
        self.key_label.setMinimumWidth(260)
        row.addWidget(self.key_label)
        hint = QLabel(tr('Page Down / Up · arrows · Space · B = black · F5 start · Esc end'))
        hint.setObjectName("keyHint")
        row.addWidget(hint, 1)
        learn = QPushButton(tr('  Learn my clicker…'))
        learn.setIcon(self.icons.get("target", self.theme["text"], 15))
        learn.setToolTip(tr('For a clicker that sends unusual keys: press its buttons once'))
        learn.clicked.connect(self.learnRequested.emit)
        row.addWidget(learn)
        guest = QPushButton(tr('  Guest phone clicker…'))
        guest.setIcon(self.icons.get("phone", self.theme["text"], 15))
        guest.setToolTip(tr("A QR code for a guest speaker's phone: next / back slide, nothing else"))
        guest.clicked.connect(self.guestRequested.emit)
        row.addWidget(guest)
        self.global_check = QCheckBox(tr('Works even when another program is in front'))
        self.global_check.setToolTip(
            tr("While slides are on screen, the clicker's Page Down / Page Up (and any learned keys)\nreach this app even if PowerPoint, a browser or anything else has focus."))
        self.global_check.toggled.connect(self.globalToggled.emit)
        row.addWidget(self.global_check)
        return bar

    # -- actions ------------------------------------------------------------- #
    def set_recent(self, paths: List[str]) -> None:
        self.recent.blockSignals(True)
        self.recent.clear()
        self.recent.addItem(tr('Recent…'), "")
        for path in paths:
            self.recent.addItem(os.path.basename(path.rstrip("\\/")) or path, path)
            self.recent.setItemData(self.recent.count() - 1, path, Qt.ToolTipRole)
        self.recent.blockSignals(False)

    def _open_file(self) -> None:
        start = os.path.dirname(self.presenter.deck.path) if self.presenter.deck else os.path.expanduser("~/Desktop")
        path, _ = QFileDialog.getOpenFileName(self, tr('Open a presentation'), start, OPEN_FILTER)
        if path:
            self.open_path(path)

    def _open_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr('A folder of slide pictures'), os.path.expanduser("~/Desktop"))
        if path:
            self.open_path(path)

    def _open_recent(self) -> None:
        path = self.recent.currentData()
        self.recent.setCurrentIndex(0)
        if path:
            self.open_path(path)

    openedPath = Signal(str)

    def open_path(self, path: str) -> None:
        error = self.presenter.open(path)
        if error:
            self.show_status(error, self.theme["danger"])
        else:
            self.openedPath.emit(os.path.normpath(path))

    def _on_target(self) -> None:
        role = self.target.currentData()
        if self.presenter.live:
            self.presenter.go_live(role)
        else:
            self.presenter.role = role
        self.refresh()

    def _on_powerpoint(self, on: bool) -> None:
        self.presenter.in_powerpoint = on
        self.powerpointToggled.emit(on)
        if self.presenter.live and self.presenter.deck is not None and self.presenter.deck.kind == "powerpoint":
            self.presenter.go_live(self.presenter.role, restart=True)
        self.refresh()

    def _toggle_live(self) -> None:
        if self.presenter.live:
            self.presenter.end()
        else:
            self.presenter.go_live(self.target.currentData())

    def show_status(self, text: str, colour: str = "") -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {colour};" if colour else "")

    def show_key(self, name: str, action: str, source: str = "") -> None:
        self._last_key = (name, action, time.monotonic(), source)
        self._tick()

    # -- display ------------------------------------------------------------- #
    def refresh(self) -> None:
        presenter = self.presenter
        deck = presenter.deck
        count = presenter.count()
        role_label = self.role_labels.get(presenter.role, presenter.role)
        if self.target.currentData() != presenter.role:
            self.target.blockSignals(True)
            self.target.setCurrentIndex(max(0, self.target.findData(presenter.role)))
            self.target.blockSignals(False)
        if deck is None:
            self.counter.setText("– / –")
            self.current.show_slide(None)
            self.upcoming.show_slide(None)
            self.notes.setText("")
        else:
            self.counter.setText(f"{presenter.index + 1} / {count}" if count else "…")
            pixmap = deck.thumb(presenter.index, 1280) if count else None
            where = tr("in PowerPoint  ·  {0}").format(role_label) if presenter.playing_in_powerpoint() else role_label
            if presenter.live and presenter.black:
                badge, colour = tr("BLACK  ·  {0}").format(where), self.theme["warn"]
            elif presenter.live:
                badge, colour = tr("LIVE  ·  {0}").format(where), self.theme["danger"]
            else:
                badge, colour = tr("PREVIEW  ·  not on screen"), self.theme["muted"]
            self.current.show_slide(pixmap, badge, colour, dimmed=presenter.live and presenter.black)
            if presenter.index + 1 < count:
                self.upcoming.show_slide(deck.thumb(presenter.index + 1, 640), "")
            else:
                self.upcoming.show_slide(None, "")
                self.upcoming.placeholder = tr("last slide") if count else "—"
            notes = presenter.notes()
            self.notes.setText(notes or ("" if deck.kind != "powerpoint" else tr("no notes on this slide")))
            self._sync_thumbs()
            if deck.error:
                self.show_status(deck.error.splitlines()[0], self.theme["danger"])
            elif not deck.done:
                self.show_status(tr('Preparing slides  {0} / {1}').format(deck.ready_count(), count or '…'))
            elif presenter.playing_in_powerpoint():
                state = "starting…" if not presenter.show.running else (
                    "end of the show - NEXT does nothing more" if presenter.at_end else "animations on")
                self.show_status(tr('{0}  ·  {1} slides  ·  PowerPoint {2}').format(deck.name, count, state), self.theme["accent"])
            else:
                self.show_status(tr('{0}  ·  {1} slides').format(deck.name, count), "")
        self.live_btn.set_hold(presenter.live)
        if presenter.live:
            self.live_btn.setText(tr('  End  ·  back to the {0} background   (hold)').format(role_label))
            self.live_btn.setIcon(self.icons.get("stop", self.theme["danger"], 16))
            self.live_btn.setObjectName("danger")
        else:
            self.live_btn.setText(tr('  Show on {0}').format(role_label))
            self.live_btn.setIcon(self.icons.get("monitor", self.theme["text"], 16))
            self.live_btn.setObjectName("")
        self.live_btn.style().unpolish(self.live_btn)
        self.live_btn.style().polish(self.live_btn)
        self.live_btn.setEnabled(presenter.can_go_live())
        self.black_btn.setEnabled(presenter.live)
        self.black_btn.setChecked(presenter.live and presenter.black)
        # in PowerPoint the last slide may still have animations to play
        self.next_btn.setEnabled(bool(count) and (presenter.index + 1 < count or presenter.black
                                                   or presenter.playing_in_powerpoint()))
        self._tick()

    def _sync_thumbs(self) -> None:
        deck = self.presenter.deck
        if deck is None:
            self.thumbs.clear()
            self._deck_shown = None
            return
        if self._deck_shown != (deck.token, deck.count):
            self._deck_shown = (deck.token, deck.count)
            self.thumbs.clear()
            for i in range(deck.count):
                item = QListWidgetItem(str(i + 1))
                item.setData(Qt.UserRole, False)
                self.thumbs.addItem(item)
        for i in range(min(deck.count, self.thumbs.count())):
            item = self.thumbs.item(i)
            if not item.data(Qt.UserRole) and deck.pages[i]:
                pixmap = deck.thumb(i, self._thumb_width)
                if pixmap is not None:
                    item.setIcon(QIcon(pixmap))
                    item.setData(Qt.UserRole, True)
        if 0 <= self.presenter.index < self.thumbs.count():
            self.thumbs.setCurrentRow(self.presenter.index)
            self.thumbs.scrollToItem(self.thumbs.item(self.presenter.index), QAbstractItemView.PositionAtCenter)

    def _on_limit(self, minutes: int) -> None:
        self.limit_minutes = minutes
        self.limitChanged.emit(minutes)
        self._tick()

    def _on_countdown_target(self) -> None:
        old = self.countdown_role
        self.countdown_role = self.countdown_combo.currentData() or ""
        if old and old != self.countdown_role:
            self.countdown.emit(old, "", "")
            self._countdown_shown = ("", "", "")
        self.countdownTargetChanged.emit(self.countdown_role)
        self._tick()

    def time_text(self, elapsed: float):
        """The desk clock: time on screen, or time left of the limit - and its colour."""
        clock = lambda seconds: f"{int(seconds // 60)}:{int(seconds % 60):02d}"  # noqa: E731
        if not self.limit_minutes:
            return tr("on screen {0}").format(clock(elapsed)), ""
        left = self.limit_minutes * 60 - elapsed
        if left < 0:
            return tr("{0} OVER the {1} min").format(clock(-left), self.limit_minutes), self.theme["danger"]
        return tr("{0} left of {1} min").format(clock(left), self.limit_minutes), self.theme["warn"] if left <= 120 else ""

    def _tick(self) -> None:
        elapsed = self.presenter.elapsed()
        text, colour = self.time_text(elapsed)
        self.clock.setText(text if self.presenter.live else "")
        self.clock.setStyleSheet(f"font-size: 15px; color: {colour}; font-weight: 700;" if colour and self.presenter.live
                                 else "font-size: 15px;")
        stage = ("", "", "")
        if self.presenter.live and self.limit_minutes and self.countdown_role:
            left = self.limit_minutes * 60 - elapsed
            shown = abs(left)
            stage = (self.countdown_role,
                     ("+" if left < 0 else "") + f"{int(shown // 60)}:{int(shown % 60):02d}",
                     self.theme["danger"] if left < 0 else self.theme["warn"] if left <= 120 else "#ffffff")
        if stage != self._countdown_shown:
            if not stage[0] and self._countdown_shown[0]:
                self.countdown.emit(self._countdown_shown[0], "", "")
            elif stage[0]:
                self.countdown.emit(*stage)
            self._countdown_shown = stage
        if len(self._last_key) == 4 and self._last_key[0]:
            name, action, when, source = self._last_key
            ago = int(time.monotonic() - when)
            self.key_label.setText(tr("last press: {0} → {1}").format(name, action) + (tr(" ({0})").format(source) if source else "")
                                   + (tr("  ·  {0} s ago").format(ago) if ago else "  ·  just now"))
            self.key_label.setStyleSheet(f"color: {self.theme['ok']};" if ago < 3 else "")
