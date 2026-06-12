"""File-list panel — browse recordings and switch between audio variants.

:class:`FileListPanel` opens a *parent* folder, groups same-named ``.wav`` files
across variant subfolders (``mic``/``out``/…) into one row per recording, and
adds a variant switcher so the user can flip between e.g. mic and enhanced
versions of the same capture. It emits the resolved wav path of the current
(recording, variant) selection, plus whether the change stayed within the same
recording (so the window can keep the spectrogram view locked across variants).
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import io_json
from ..library import FLAT_VARIANT, Library, Recording, scan_library

_ANNOTATED_COLOR = QColor("#2e7d32")  # green for already-annotated files


class FileListPanel(QWidget):
    """Recording list + variant switcher with annotation-status marks.

    Signals::

        selectionChanged(str, bool)
            (resolved wav path, same_recording) — same_recording is True when
            only the variant changed within the current recording.
    """

    selectionChanged = Signal(str, bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._library: Optional[Library] = None
        self._preferred_variant: str = FLAT_VARIANT

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._title = QLabel("No folder open")
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        # Variant switcher (one checkable button per variant).
        self._variant_bar = QWidget()
        self._variant_layout = QHBoxLayout(self._variant_bar)
        self._variant_layout.setContentsMargins(0, 0, 0, 0)
        self._variant_layout.setSpacing(2)
        self._variant_group = QButtonGroup(self)
        self._variant_group.setExclusive(True)
        self._variant_buttons: dict[str, QPushButton] = {}
        layout.addWidget(self._variant_bar)

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

    # ------------------------------------------------------------------ #
    # Folder loading
    # ------------------------------------------------------------------ #
    def set_folder(self, path: str) -> None:
        """Scan ``path`` into recordings/variants and populate the panel."""
        self._library = scan_library(path)
        variants = self._library.variants
        if self._preferred_variant not in variants:
            self._preferred_variant = variants[0] if variants else FLAT_VARIANT

        self._build_variant_bar(variants)

        n = len(self._library.recordings)
        self._title.setText(f"{os.path.basename(path) or path}  ({n} recordings)")

        self._list.blockSignals(True)
        self._list.clear()
        for rec in self._library.recordings:
            self._list.addItem(self._make_item(rec))
        self._list.blockSignals(False)

        if n:
            self._list.setCurrentRow(0)

    def _build_variant_bar(self, variants: list[str]) -> None:
        """Rebuild the variant button row. Hidden in the flat fallback."""
        for btn in self._variant_buttons.values():
            self._variant_group.removeButton(btn)
            btn.deleteLater()
        self._variant_buttons.clear()
        while self._variant_layout.count():
            item = self._variant_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        flat = variants == [FLAT_VARIANT] or not variants
        self._variant_bar.setVisible(not flat)
        if flat:
            return

        self._variant_layout.addWidget(QLabel("Variant:"))
        for name in variants:
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setChecked(name == self._preferred_variant)
            btn.clicked.connect(lambda _checked, v=name: self.set_variant(v))
            self._variant_group.addButton(btn)
            self._variant_layout.addWidget(btn)
            self._variant_buttons[name] = btn
        self._variant_layout.addStretch(1)

    # ------------------------------------------------------------------ #
    # Resolution helpers
    # ------------------------------------------------------------------ #
    def _current_recording(self) -> Optional[Recording]:
        if self._library is None:
            return None
        row = self._list.currentRow()
        if row < 0 or row >= len(self._library.recordings):
            return None
        return self._library.recordings[row]

    def _resolved_variant(self, rec: Recording) -> str:
        """Preferred variant if the recording has it, else its first available."""
        if self._preferred_variant in rec.variants:
            return self._preferred_variant
        avail = rec.available()
        return avail[0] if avail else FLAT_VARIANT

    def current_path(self) -> Optional[str]:
        """Resolved wav path for the current recording + variant."""
        rec = self._current_recording()
        if rec is None:
            return None
        return rec.path_for(self._resolved_variant(rec))

    def current_variant(self) -> str:
        rec = self._current_recording()
        return self._resolved_variant(rec) if rec is not None else FLAT_VARIANT

    # ------------------------------------------------------------------ #
    # List items / annotation marks
    # ------------------------------------------------------------------ #
    def _make_item(self, rec: Recording) -> QListWidgetItem:
        path = rec.path_for(self._resolved_variant(rec))
        annotated = bool(path) and io_json.has_annotation(path)
        prefix = "✓ " if annotated else "   "
        item = QListWidgetItem(prefix + rec.key)
        item.setData(Qt.ItemDataRole.UserRole, rec.key)
        if annotated:
            item.setForeground(_ANNOTATED_COLOR)
        return item

    def refresh_annotated_marks(self) -> None:
        """Re-evaluate the ✓ mark for every row against the current variant."""
        if self._library is None:
            return
        for row in range(self._list.count()):
            rec = self._library.recordings[row]
            path = rec.path_for(self._resolved_variant(rec))
            annotated = bool(path) and io_json.has_annotation(path)
            item = self._list.item(row)
            item.setText(("✓ " if annotated else "   ") + rec.key)
            item.setForeground(
                _ANNOTATED_COLOR if annotated else QColor(Qt.GlobalColor.black)
            )

    # ------------------------------------------------------------------ #
    # Navigation
    # ------------------------------------------------------------------ #
    def select_index(self, i: int) -> None:
        n = self._list.count()
        if n:
            self._list.setCurrentRow(max(0, min(i, n - 1)))

    def next(self) -> None:
        """Next recording (clamped)."""
        self.select_index(self._list.currentRow() + 1)

    def prev(self) -> None:
        """Previous recording (clamped)."""
        self.select_index(self._list.currentRow() - 1)

    def set_variant(self, name: str) -> None:
        """Switch the active variant (stays on the current recording)."""
        self._preferred_variant = name
        rec = self._current_recording()
        if rec is None:
            return
        self._sync_variant_buttons(rec)
        path = rec.path_for(self._resolved_variant(rec))
        if path:
            self.selectionChanged.emit(path, True)  # same recording

    def cycle_variant(self) -> None:
        """Cycle to the next available variant of the current recording."""
        rec = self._current_recording()
        if rec is None:
            return
        avail = rec.available()
        if len(avail) < 2:
            return
        cur = self._resolved_variant(rec)
        nxt = avail[(avail.index(cur) + 1) % len(avail)]
        self.set_variant(nxt)

    def _sync_variant_buttons(self, rec: Recording) -> None:
        """Reflect availability + the resolved variant in the button row."""
        resolved = self._resolved_variant(rec)
        for name, btn in self._variant_buttons.items():
            btn.setEnabled(name in rec.variants)
            btn.blockSignals(True)
            btn.setChecked(name == resolved)
            btn.blockSignals(False)

    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            return
        rec = self._current_recording()
        if rec is None:
            return
        self._sync_variant_buttons(rec)
        path = rec.path_for(self._resolved_variant(rec))
        if path:
            self.selectionChanged.emit(path, False)  # new recording
