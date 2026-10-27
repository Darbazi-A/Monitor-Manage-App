"""
The built program checks itself:  "Stage Display Controller.exe" --selftest report.json

Everything a frozen build can lose is tried for real - the desk builds, Chromium
loads a page, a sound decodes, a PDF renders, the DJ desk's decoder process
starts and analyses a sound, the phone server answers - with settings and files
of its own (never the hall's), no stage window, and no sound. The report lists
each check; the exit code is 0 when all passed. installer\\build.ps1 runs it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback

WORK = tempfile.mkdtemp(prefix="sdc-selftest-")
os.environ["SDC_SETTINGS_APP"] = "StageDisplayControllerSELFTEST"
os.environ["SDC_DATA_DIR"] = os.path.join(WORK, "data")

results = []


def check(name: str, ok: bool, detail="") -> None:
    results.append({"check": name, "ok": bool(ok), "detail": str(detail)[:300]})


def pump(app, seconds: float, until=None) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.01)
    return bool(until and until())


def run(report: str) -> int:
    from PySide6.QtCore import QSettings, QUrl
    from PySide6.QtWidgets import QApplication

    import main
    from config import DATA_DIR, FROZEN, VERSION

    QSettings(main.SETTINGS_ORG, main.SETTINGS_APP).clear()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(main.STYLESHEET)
    check("version", True, VERSION)
    check("frozen build", FROZEN, sys.executable)
    check("the self-test's own files", DATA_DIR == os.environ["SDC_DATA_DIR"], DATA_DIR)

    try:
        panel = main.ControlPanel()
        check("the desk builds", True, f"{panel.tabs.count()} pages")
    except Exception:  # noqa: BLE001
        check("the desk builds", False, traceback.format_exc())
        return finish(report)
    check("no stage window opened", not panel._outputs())
    check("the icon is packed", os.path.isfile(main.ICON_FILE), main.ICON_FILE)

    # sound: a WAV decodes (muted)
    import school_timer
    from PySide6.QtMultimedia import QAudioOutput, QMediaFormat, QMediaPlayer
    wav = os.path.join(WORK, "beeps.wav")
    with open(wav, "wb") as handle:
        handle.write(school_timer.beeps_wav())
    player = QMediaPlayer()
    audio = QAudioOutput()
    audio.setMuted(True)
    player.setAudioOutput(audio)
    player.setSource(QUrl.fromLocalFile(wav))
    pump(app, 8, lambda: player.duration() > 0)
    check("sound decodes (FFmpeg)", player.duration() > 0, player.duration())
    codecs = QMediaFormat().supportedVideoCodecs(QMediaFormat.ConversionMode.Decode)
    check("video codecs available", len(codecs) >= 3, [c.name for c in codecs][:8])

    # PDF: one page written, then read and rendered
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QPainter, QPdfWriter
    from PySide6.QtPdf import QPdfDocument
    pdf_path = os.path.join(WORK, "page.pdf")
    writer = QPdfWriter(pdf_path)
    painter = QPainter(writer)
    painter.drawText(200, 200, "Stage Display self-test")
    painter.end()
    document = QPdfDocument()
    document.load(pdf_path)
    image = document.render(0, QSize(320, 180)) if document.pageCount() else None
    check("PDF slides render", image is not None and not image.isNull(), document.pageCount())

    # Chromium: a page loads and runs its script
    from PySide6.QtWebEngineWidgets import QWebEngineView
    view = QWebEngineView()
    view.setHtml("<title>start</title><script>document.title = 'ok-' + (6 * 7)</script>")
    pump(app, 30, lambda: view.title() == "ok-42")
    check("Chromium (Canva, Kahoot, laptops) loads a page", view.title() == "ok-42", view.title())

    # the DJ desk's decoder: the same .exe, as its own process
    command = [sys.executable, "--dj-decoder"] if FROZEN else [sys.executable, os.path.join(main.APP_DIR, "dj_decoder.py")]
    events = []
    try:
        decoder = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        def read() -> None:
            for raw in decoder.stdout:
                try:
                    events.append(json.loads(raw.decode("utf-8")))
                except ValueError:
                    pass
        threading.Thread(target=read, daemon=True).start()
        decoder.stdin.write((json.dumps({"cmd": "load", "id": 1, "path": wav, "sr": 44100}) + "\n").encode())
        decoder.stdin.flush()
        pump(app, 30, lambda: any(e.get("event") in ("done", "error") for e in events))
        done = [e for e in events if e.get("event") == "done"]
        check("the DJ decoder runs and analyses a sound", bool(done), [e.get("event") for e in events][-4:])
        names = [n for e in events for n in (e.get("refs") or []) if isinstance(n, str)]
        decoder.stdin.write((json.dumps({"cmd": "release", "names": names}) + "\n").encode())
        decoder.stdin.write(b'{"cmd": "quit"}\n')
        decoder.stdin.flush()
        decoder.wait(10)
    except Exception:  # noqa: BLE001
        check("the DJ decoder runs and analyses a sound", False, traceback.format_exc())

    # the phone server answers on this computer
    import urllib.request
    port = 18799
    error = panel.remote.start(port, loopback_only=True)
    answer = {}

    def fetch() -> None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as response:
                answer["page"] = response.read()
        except Exception as problem:  # noqa: BLE001
            answer["page"] = str(problem).encode()
    threading.Thread(target=fetch, daemon=True).start()
    pump(app, 12, lambda: "page" in answer)
    check("the phone server answers", error is None and b"Stage remote" in answer.get("page", b""), error or answer.get("page", b"")[:80])
    panel.remote.stop()

    # the presets go to the right place
    panel.presets.put("Self-test", panel._collect_preset())
    panel.presets.save()
    check("presets are saved with the program's files", os.path.isfile(os.path.join(DATA_DIR, "presets.json")))

    view.deleteLater()
    panel.web.shutdown()
    panel.share_receiver.shutdown()
    panel.tray.hide()
    QSettings(main.SETTINGS_ORG, main.SETTINGS_APP).clear()
    return finish(report)


def finish(report: str) -> int:
    ok = bool(results) and all(r["ok"] for r in results)
    with open(report, "w", encoding="utf-8") as handle:
        json.dump({"ok": ok, "checks": results}, handle, ensure_ascii=False, indent=1)
    os._exit(0 if ok else 1)          # at once: Chromium and the threads are torn down by Windows


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else os.path.join(WORK, "report.json"))
