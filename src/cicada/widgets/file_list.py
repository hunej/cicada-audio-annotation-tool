"""File-list panel — browse every recording/variant as its own list row.

:class:`FileListPanel` opens a *parent* folder, groups same-named ``.wav`` files
across variant subfolders (``mic``/``out``/…) into recordings, then lists one
row per *(recording, variant)* pair — e.g. ``babble_15dB(mic)`` and
``babble_15dB(out)`` as two separate rows. It emits the resolved wav path of the
current selection, plus whether the change stayed within the same recording (so
the window can keep the spectrogram view locked across variants).
"""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
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


def _entry_label(rec: Recording, variant: str) -> str:
    """Display name for a (recording, variant) row, e.g. ``babble_15dB(mic)``."""
    if variant == FLAT_VARIANT:
        return rec.key
    return f"{rec.key}({variant})"


class FileListPanel(QWidget):
    """Flat recording/variant list with annotation-status marks.

    Signals::

        selectionChanged(str, bool)
            (resolved wav path, same_recording) — same_recording is True when
            the new row belongs to the same recording as the previous one (only
            the variant changed).
    """

    selectionChanged = Signal(str, bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._library: Optional[Library] = None
        self._root: Optional[str] = None
        # One entry per visible row: (recording, variant).
        self._entries: list[tuple[Recording, str]] = []
        self._last_key: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        header = QHBoxLayout()
        self._title = QLabel("No folder open")
        self._title.setWordWrap(True)
        header.addWidget(self._title, 1)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setToolTip("Re-scan the folder for added/changed files")
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self._refresh_btn, 0)
        layout.addLayout(header)

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

    # ------------------------------------------------------------------ #
    # Folder loading
    # ------------------------------------------------------------------ #
    def set_folder(self, path: str) -> None:
        """Scan ``path`` into recordings/variants and populate the panel."""
        self._root = path
        self._refresh_btn.setEnabled(True)
        self._populate(restore=False)

    def refresh(self) -> None:
        """Re-scan the current folder, preserving the selected row if it survives.

        Useful when wav files are added/removed/edited outside the app. The
        selection is restored by (recording key, variant); if that pair is gone,
        falls back to the first row.
        """
        if self._root is None:
            return
        self._populate(restore=True)

    def _populate(self, restore: bool) -> None:
        """(Re)scan ``self._root`` and rebuild the list.

        When ``restore`` is True, keep the current (key, variant) selection if it
        still exists after the rescan; otherwise select the first row.
        """
        assert self._root is not None
        keep = self._current_entry()
        keep_pair = (keep[0].key, keep[1]) if keep is not None else None

        self._library = scan_library(self._root)
        self._entries = [
            (rec, variant)
            for rec in self._library.recordings
            for variant in self._library.variants
            if variant in rec.variants
        ]
        self._last_key = None

        n = len(self._library.recordings)
        self._title.setText(f"{os.path.basename(self._root) or self._root}  ({n} recordings)")

        self._list.blockSignals(True)
        self._list.clear()
        for rec, variant in self._entries:
            self._list.addItem(self._make_item(rec, variant))
        self._list.blockSignals(False)

        if not restore:
            if self._entries:
                self._list.setCurrentRow(0)
            return

        # Restore the prior selection and force a reload (the file on disk may
        # have changed), keeping the view if it's still the same recording.
        target = 0
        if keep_pair is not None:
            for row, (rec, variant) in enumerate(self._entries):
                if (rec.key, variant) == keep_pair:
                    target = row
                    break
        if not self._entries:
            return
        self._list.blockSignals(True)
        self._list.setCurrentRow(target)
        self._list.blockSignals(False)
        rec, variant = self._entries[target]
        same_recording = keep_pair is not None and rec.key == keep_pair[0]
        self._last_key = rec.key
        path = rec.path_for(variant)
        if path:
            self.selectionChanged.emit(path, same_recording)

    # ------------------------------------------------------------------ #
    # Resolution helpers
    # ------------------------------------------------------------------ #
    def _current_entry(self) -> Optional[tuple[Recording, str]]:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._entries):
            return None
        return self._entries[row]

    def current_path(self) -> Optional[str]:
        """Resolved wav path for the current row."""
        entry = self._current_entry()
        if entry is None:
            return None
        rec, variant = entry
        return rec.path_for(variant)

    def current_variant(self) -> str:
        entry = self._current_entry()
        return entry[1] if entry is not None else FLAT_VARIANT

    def sibling_variant_paths(self) -> list[str]:
        """Wav paths of the current recording's *other* variants (for box sync)."""
        entry = self._current_entry()
        if entry is None:
            return []
        rec, variant = entry
        return [p for v, p in rec.variants.items() if v != variant and p]

    # ------------------------------------------------------------------ #
    # List items / annotation marks
    # ------------------------------------------------------------------ #
    def _make_item(self, rec: Recording, variant: str) -> QListWidgetItem:
        path = rec.path_for(variant)
        annotated = bool(path) and io_json.has_annotation(path)
        prefix = "✓ " if annotated else "   "
        item = QListWidgetItem(prefix + _entry_label(rec, variant))
        item.setData(Qt.ItemDataRole.UserRole, rec.key)
        if annotated:
            item.setForeground(_ANNOTATED_COLOR)
        return item

    def refresh_annotated_marks(self) -> None:
        """Re-evaluate the ✓ mark for every row."""
        for row, (rec, variant) in enumerate(self._entries):
            path = rec.path_for(variant)
            annotated = bool(path) and io_json.has_annotation(path)
            item = self._list.item(row)
            item.setText(("✓ " if annotated else "   ") + _entry_label(rec, variant))
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
        """Next row (clamped)."""
        self.select_index(self._list.currentRow() + 1)

    def prev(self) -> None:
        """Previous row (clamped)."""
        self.select_index(self._list.currentRow() - 1)

    def cycle_variant(self) -> None:
        """Jump to the next row of the current recording (variant cycle)."""
        entry = self._current_entry()
        if entry is None:
            return
        key = entry[0].key
        rows = [r for r, (rec, _v) in enumerate(self._entries) if rec.key == key]
        if len(rows) < 2:
            return
        cur = self._list.currentRow()
        nxt = rows[(rows.index(cur) + 1) % len(rows)]
        self._list.setCurrentRow(nxt)

    def _on_row_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._entries):
            return
        rec, variant = self._entries[row]
        same_recording = rec.key == self._last_key
        self._last_key = rec.key
        path = rec.path_for(variant)
        if path:
            self.selectionChanged.emit(path, same_recording)
