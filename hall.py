"""
Setting a hall up: which stage screens it has, what each is called, which is
the LED strip with the running text, and which monitor each one is on.

The hall lives in hall.json beside the hall's files (config.hall_file) and is
read once, at start (config.HALL): saving here asks to restart the program.
"Find the screens" proposes a hall from the monitors Windows reports - every
monitor but the desk's, the biggest as the Main Stage, a very wide one as the
strip - and "Show numbers" puts a big number on each monitor to tell them apart.
A hall can be saved to a file and opened on another computer, with its scenes
and running orders.
"""
from __future__ import annotations

from i18n import tr  # noqa: E402 - the interface's language

import json
import os
import re
from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

import config

KINDS = (("screen", "Screen"), ("strip", "LED strip - running text"))
FILE_KIND = "stage-display-hall"


def save_hall(hall: dict) -> Optional[str]:
    """Write the hall; an error message, or None."""
    path = config.hall_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(config.clean_hall(hall), handle, ensure_ascii=False, indent=1)
    except OSError as error:
        return str(error)
    return None


def monitor_caption(screen) -> str:
    geo = screen.geometry()
    model = (screen.model() or screen.manufacturer() or "").strip()
    primary = tr("  (the desk)") if screen is QGuiApplication.primaryScreen() else ""
    return f"{model or screen.name()}  —  {geo.width()}×{geo.height()}{primary}"


def propose_hall() -> dict:
    """A hall from the monitors: every one but the desk's, the biggest first, a very wide one as the strip."""
    desk = QGuiApplication.primaryScreen()
    monitors = [s for s in QGuiApplication.screens() if s is not desk]
    monitors.sort(key=lambda s: s.geometry().x())

    def aspect(screen) -> float:
        geo = screen.geometry()
        return geo.width() / max(1, geo.height())

    strip = max((s for s in monitors if aspect(s) >= 2.5), key=aspect, default=None)
    plain = [s for s in monitors if s is not strip]
    plain.sort(key=lambda s: -s.geometry().width() * s.geometry().height())
    screens = []
    for index, monitor in enumerate(plain[: config.MAX_SCREENS - (1 if strip else 0)]):
        screens.append({"id": "main" if index == 0 else f"screen{index + 1}",
                        "name": "Main Stage" if index == 0 else tr("Screen {0}").format(index + 1),
                        "kind": "screen", "monitor": monitor.name()})
    if not screens:
        screens.append({"id": "main", "name": "Main Stage", "kind": "screen"})
    if strip is not None:
        geo = strip.geometry()
        screens.append({"id": "top", "name": "Top Screen", "kind": "strip", "monitor": strip.name(),
                        "width": geo.width(), "height": geo.height()})
    return {"name": "", "screens": screens}


class ScreenRow(QFrame):
    """One screen of the hall: its name, its kind, its monitor."""

    def __init__(self, dialog: "HallDialog", screen: dict) -> None:
        super().__init__()
        self.dialog = dialog
        self.sid = screen.get("id", "")
        self.extra = {k: v for k, v in screen.items() if k in ("width", "height", "note")}
        self.setObjectName("card")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)
        self.number = QLabel()
        self.number.setFixedWidth(26)
        self.number.setStyleSheet("font-size: 18px; font-weight: 800;")
        row.addWidget(self.number)
        self.name_edit = QLineEdit(screen.get("name", ""))
        self.name_edit.setPlaceholderText(tr("Name - e.g. Main Stage, Left screen, Foyer"))
        self.name_edit.setMaxLength(40)
        row.addWidget(self.name_edit, 3)
        self.kind_combo = QComboBox()
        for value, label in KINDS:
            self.kind_combo.addItem(tr(label), value)
        self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(screen.get("kind", "screen"))))
        self.kind_combo.currentIndexChanged.connect(lambda _i: dialog.kind_changed(self))
        row.addWidget(self.kind_combo, 2)
        self.monitor_combo = QComboBox()
        self.monitor_combo.addItem(tr("monitor: choose later"), "")
        for monitor in QGuiApplication.screens():
            self.monitor_combo.addItem(monitor_caption(monitor), monitor.name())
        wanted = screen.get("monitor", "")
        self.monitor_missing = bool(wanted) and self.monitor_combo.findData(wanted) < 0
        if self.monitor_missing:
            self.monitor_combo.addItem(tr("{0}  (not connected)").format(wanted), wanted)
        self.monitor_combo.setCurrentIndex(max(0, self.monitor_combo.findData(wanted)))
        row.addWidget(self.monitor_combo, 3)
        self.up_btn = QPushButton("▲")
        self.up_btn.setToolTip(tr("Earlier in the list"))
        self.up_btn.clicked.connect(lambda: dialog.move(self, -1))
        row.addWidget(self.up_btn)
        self.down_btn = QPushButton("▼")
        self.down_btn.setToolTip(tr("Later in the list"))
        self.down_btn.clicked.connect(lambda: dialog.move(self, 1))
        row.addWidget(self.down_btn)
        self.remove_btn = QPushButton("✕")
        self.remove_btn.setToolTip(tr("Take this screen out of the hall"))
        self.remove_btn.clicked.connect(lambda: dialog.remove(self))
        row.addWidget(self.remove_btn)

    def kind(self) -> str:
        return self.kind_combo.currentData()

    def screen(self) -> dict:
        data = dict(self.extra, id=self.sid, name=self.name_edit.text().strip(), kind=self.kind())
        if self.monitor_combo.currentData():
            data["monitor"] = self.monitor_combo.currentData()
        return data


class HallDialog(QDialog):
    """Settings -> Hall: the hall's screens, found, numbered, named; saved, opened, sent to a file."""

    def __init__(self, hall: dict, parent=None, identify: Callable[[], None] = lambda: None,
                 extras: Callable[[], dict] = lambda: {}, take_extras: Callable[[dict], str] = lambda _d: "") -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("The hall"))
        self.setMinimumSize(980, 620)
        self.identify = identify
        self.extras = extras
        self.take_extras = take_extras
        self.rows: List[ScreenRow] = []
        box = QVBoxLayout(self)
        box.setContentsMargins(22, 18, 22, 18)
        box.setSpacing(10)
        title = QLabel(tr("The hall's screens"))
        title.setObjectName("pageTitle")
        box.addWidget(title)
        lead = QLabel(tr("Every stage screen this hall has - up to eight. The first is the Main Stage: presentations, "
                         "Canva and laptops go there. One screen may be a wide LED strip with the running text. "
                         "Find the screens fills the list from the monitors connected now; Show numbers puts a "
                         "big number on each monitor so you can tell which is which."))
        lead.setObjectName("pageLead")
        lead.setWordWrap(True)
        box.addWidget(lead)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(tr("The hall's name")))
        self.hall_name = QLineEdit(hall.get("name", ""))
        self.hall_name.setPlaceholderText(tr("optional - e.g. Assembly hall"))
        self.hall_name.setMaxLength(60)
        name_row.addWidget(self.hall_name, 1)
        box.addLayout(name_row)

        tools = QHBoxLayout()
        find = QPushButton(tr("  Find the screens"))
        find.setObjectName("primary")
        find.clicked.connect(self.find_screens)
        tools.addWidget(find)
        numbers = QPushButton(tr("  Show numbers on the monitors"))
        numbers.clicked.connect(self.identify)
        tools.addWidget(numbers)
        self.add_btn = QPushButton(tr("  + Add a screen"))
        self.add_btn.clicked.connect(lambda: self.add({"name": "", "kind": "screen"}))
        tools.addWidget(self.add_btn)
        tools.addStretch(1)
        box.addLayout(tools)

        holder = QWidget()
        self.list_box = QVBoxLayout(holder)
        self.list_box.setContentsMargins(0, 0, 0, 0)
        self.list_box.setSpacing(6)
        self.list_box.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(holder)
        box.addWidget(scroll, 1)

        self.note = QLabel("")
        self.note.setObjectName("cardHint")
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        bottom = QHBoxLayout()
        export = QPushButton(tr("  Save to a file…"))
        export.setToolTip(tr("The hall, its scenes and running orders in one file - for another computer"))
        export.clicked.connect(self.export_file)
        bottom.addWidget(export)
        load = QPushButton(tr("  Open a file…"))
        load.setToolTip(tr("A hall saved on another computer"))
        load.clicked.connect(self.import_file)
        bottom.addWidget(load)
        bottom.addStretch(1)
        cancel = QPushButton(tr("Cancel"))
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        save = QPushButton(tr("  Save - the program restarts"))
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        bottom.addWidget(save)
        box.addLayout(bottom)
        self.set_hall(hall)

    # -- the list ------------------------------------------------------------------ #
    def set_hall(self, hall: dict) -> None:
        for row in self.rows:
            row.setParent(None)
            row.deleteLater()
        self.rows = []
        for screen in config.clean_hall(hall)["screens"]:
            self.add(screen, renumber=False)
        self.renumber()

    def add(self, screen: dict, renumber: bool = True) -> None:
        if len(self.rows) >= config.MAX_SCREENS:
            return
        row = ScreenRow(self, screen)
        self.rows.append(row)
        self.list_box.insertWidget(len(self.rows) - 1, row)
        if row.kind() == "strip":
            self.kind_changed(row)          # a new strip: the hall's old one becomes a plain screen
        if renumber:
            self.renumber()
            row.name_edit.setFocus()

    def remove(self, row: ScreenRow) -> None:
        if row in self.rows and self.rows.index(row) > 0:
            self.rows.remove(row)
            row.setParent(None)
            row.deleteLater()
            self.renumber()

    def move(self, row: ScreenRow, delta: int) -> None:
        index = self.rows.index(row)
        target = index + delta
        if index == 0 or not 1 <= target < len(self.rows):
            return                              # the Main Stage stays first
        self.rows[index], self.rows[target] = self.rows[target], self.rows[index]
        self.list_box.removeWidget(row)
        self.list_box.insertWidget(target, row)
        self.renumber()

    def kind_changed(self, row: ScreenRow) -> None:
        if row.kind() == "strip":
            for other in self.rows:
                if other is not row and other.kind() == "strip":
                    other.kind_combo.setCurrentIndex(0)          # one strip only
        self.renumber()

    def renumber(self) -> None:
        for index, row in enumerate(self.rows):
            row.number.setText(str(index + 1))
            main = index == 0
            row.up_btn.setEnabled(index > 1)
            row.down_btn.setEnabled(0 < index < len(self.rows) - 1)
            row.remove_btn.setEnabled(not main)
            if main and row.kind() == "strip":
                row.kind_combo.setCurrentIndex(0)                # the Main Stage is never a strip
            row.kind_combo.setEnabled(not main)
        self.add_btn.setEnabled(len(self.rows) < config.MAX_SCREENS)
        strips = sum(1 for row in self.rows if row.kind() == "strip")
        self.note.setText(tr("{0} screen(s); the first is the Main Stage{1}.").format(
            len(self.rows), tr(", one is the LED strip") if strips else ""))

    def hall(self) -> dict:
        """The hall as typed, with ids: kept where a screen had one, new ones made up."""
        used = set()
        screens = []
        for index, row in enumerate(self.rows):
            screen = row.screen()
            if index == 0:
                screen["id"] = "main"
            elif not screen["id"] or screen["id"] in used:
                base = "top" if screen["kind"] == "strip" else "screen"
                number = index + 1
                sid = base if base == "top" and "top" not in used else f"{base}{number}"
                while sid in used:
                    number += 1
                    sid = f"{base}{number}"
                screen["id"] = sid
            used.add(screen["id"])
            screens.append(screen)
        return {"name": self.hall_name.text().strip(), "screens": screens}

    # -- buttons ------------------------------------------------------------------------ #
    def find_screens(self) -> None:
        if len(self.rows) > 1 and QMessageBox.question(
                self, tr("Find the screens"), tr("Replace the list with the monitors connected now?")) != QMessageBox.Yes:
            return
        proposal = propose_hall()
        proposal["name"] = self.hall_name.text().strip()
        self.set_hall(proposal)
        self.note.setText(tr("Found {0} screen(s) besides the desk. Name them, check the numbers on the "
                             "monitors, then save.").format(len(proposal["screens"]) if proposal["screens"][0].get("monitor") else 0))

    def save(self) -> None:
        hall = self.hall()
        if any(not screen["name"] for screen in hall["screens"]):
            QMessageBox.information(self, tr("The hall"), tr("Every screen needs a name."))
            return
        names = [screen["name"].lower() for screen in hall["screens"]]
        if len(set(names)) != len(names):
            QMessageBox.information(self, tr("The hall"), tr("Two screens have the same name."))
            return
        error = save_hall(hall)
        if error:
            QMessageBox.critical(self, tr("The hall"), error)
            return
        self.accept()

    def export_file(self) -> None:
        hall = self.hall()
        name = re.sub(r'[<>:"/\\|?*]', "_", hall["name"] or tr("Hall"))
        path, _ = QFileDialog.getSaveFileName(self, tr("Save the hall to a file"),
                                              os.path.join(os.path.expanduser("~/Desktop"), f"{name}.stagehall"),
                                              tr("Hall") + " (*.stagehall)")
        if not path:
            return
        data = {"kind": FILE_KIND, "version": 1, "hall": config.clean_hall(hall)}
        data.update(self.extras())
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=1)
        except OSError as error:
            QMessageBox.critical(self, tr("The hall"), str(error))
            return
        self.note.setText(tr("Saved to {0}.").format(path))

    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Open a hall"), os.path.expanduser("~/Desktop"),
                                              tr("Hall") + " (*.stagehall *.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, tr("The hall"), str(error))
            return
        if not isinstance(data, dict) or data.get("kind") != FILE_KIND or not isinstance(data.get("hall"), dict):
            QMessageBox.information(self, tr("The hall"), tr("That is not a hall saved by this program."))
            return
        self.set_hall(data["hall"])
        self.hall_name.setText(data["hall"].get("name", ""))
        # the monitors there are not the monitors here: choose them again (or Find the screens)
        for row in self.rows:
            if row.monitor_missing:
                row.monitor_combo.setCurrentIndex(0)
        message = self.take_extras(data)
        self.note.setText(tr("Opened {0}. Check the monitors, then save.").format(os.path.basename(path))
                          + (" " + message if message else ""))
