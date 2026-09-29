"""
Automatic backups of presets.json and shows.json.

Before either file is written, the version on disk is copied into a
"backups" folder next to it - at most one copy every two minutes, however
often the running order is edited, and the newest ten of each are kept. A
preset overwritten by mistake, a running order deleted, a file damaged by a
power cut: one click on Screens & Setup brings the earlier version back.
"""
from __future__ import annotations

import datetime
import os
import shutil
import time
from typing import List, Optional, Tuple

KEEP = 10
EVERY_SECONDS = 120


def folder_for(path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(path)), "backups")


def _stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def list_backups(path: str) -> List[Tuple[str, datetime.datetime]]:
    """(backup file, when it was taken), newest first."""
    folder = folder_for(path)
    stem = _stem(path)
    found = []
    try:
        for name in os.listdir(folder):
            if name.startswith(stem + "-") and name.endswith(".json"):
                full = os.path.join(folder, name)
                found.append((full, datetime.datetime.fromtimestamp(os.path.getmtime(full))))
    except OSError:
        return []
    return sorted(found, key=lambda item: item[1], reverse=True)


def backup(path: str, force: bool = False) -> Optional[str]:
    """Copy `path` into the backups folder before it is overwritten. Returns the copy, or None."""
    if not os.path.isfile(path):
        return None
    existing = list_backups(path)
    if existing and not force and time.time() - existing[0][1].timestamp() < EVERY_SECONDS:
        return None
    folder = folder_for(path)
    try:
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        target = os.path.join(folder, f"{_stem(path)}-{stamp}.json")
        number = 2
        while os.path.exists(target):          # two copies within one second (a restore)
            target = os.path.join(folder, f"{_stem(path)}-{stamp}-{number}.json")
            number += 1
        shutil.copy2(path, target)
        os.utime(target)                       # "taken now", not the original's time
    except OSError:
        return None
    for old, _when in list_backups(path)[KEEP:]:
        try:
            os.remove(old)
        except OSError:
            pass
    return target


def restore(path: str, backup_file: str) -> Optional[str]:
    """Put a backup back in place of `path` (keeping the current one as a backup first)."""
    try:
        # read it first: keeping the current file as a copy may retire this one
        with open(backup_file, "rb") as handle:
            content = handle.read()
        backup(path, force=True)
        with open(path, "wb") as handle:
            handle.write(content)
        return None
    except OSError as exc:
        return str(exc)
