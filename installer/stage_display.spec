# PyInstaller recipe: the program as a folder with its own .exe (installer\build.ps1 runs it).
# -*- mode: python ; coding: utf-8 -*-
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "stage_display.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, "stage_icon.ico"), ".")],
    # imported by name inside functions, or only by the DJ decoder process
    hiddenimports=["dj_decoder", "selftest", "i18n_ka", "phone_ka", "remote_ka", "school_timer",
                   "PySide6.QtPdf", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
                   "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtNetwork",
                   "PySide6.QtWebSockets", "cloud", "cloud_control"],
    hookspath=[],
    runtime_hooks=[],
    # nothing here uses these; leaving them out keeps the program smaller
    excludes=["tkinter", "unittest", "pydoc_data", "PyInstaller",
              "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
              "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras", "PySide6.QtCharts", "PySide6.QtDataVisualization",
              "PySide6.QtGraphs", "PySide6.QtQuick3D", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
              "PySide6.QtHelp", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSensors", "PySide6.QtSerialPort",
              "PySide6.QtLocation", "PySide6.QtPositioning", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
              "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtSpatialAudio"],
    noarchive=False,
)


def wanted(entry) -> bool:
    """Leave out what the program never uses: Chromium's developer tools (83 MB), Chromium's
    words in a hundred languages but English and Georgian (44 MB), Qt's own translations."""
    name = entry[0].replace("\\", "/").lower()
    if "devtools_resources" in name:
        return False
    if "/qtwebengine_locales/" in name:
        return name.rsplit("/", 1)[-1] in ("en-us.pak", "en-gb.pak", "ka.pak")
    if "/translations/" in name and name.endswith(".qm"):
        return False
    return True


a.datas = [entry for entry in a.datas if wanted(entry)]
a.binaries = [entry for entry in a.binaries if wanted(entry)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Stage Display Controller",
    icon=os.path.join(ROOT, "stage_icon.ico"),
    version=os.path.join(SPECPATH, "version_info.txt"),
    console=False,                      # a desk program: no black console window behind it
    upx=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="Stage Display Controller",
)
