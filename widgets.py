"""
Small widgets every part of the dashboard shares.

    ElidedLabel   one line of text - usually a file name - that never asks for
                  more width than it is given: too long, it ends in "…" (the
                  whole text on hover). A plain QLabel asks for its whole text,
                  so one long file name used to push a page past the window's
                  right edge.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QLabel, QSizePolicy


class ElidedLabel(QLabel):
    MIN_WIDTH = 40

    def __init__(self, text: str = "", parent=None, mode: Qt.TextElideMode = Qt.ElideMiddle) -> None:
        super().__init__(parent)
        self._full = ""
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text or ""
        self._refit()

    def text(self) -> str:
        return self._full

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), self.MIN_WIDTH), hint.height())

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        return QSize(self.fontMetrics().horizontalAdvance(self._full) + 6, hint.height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refit()

    def _refit(self) -> None:
        shown = self.fontMetrics().elidedText(self._full, self._mode, max(0, self.width() - 2))
        if QLabel.text(self) != shown:
            QLabel.setText(self, shown)
        self.setToolTip(self._full if shown != self._full else "")
