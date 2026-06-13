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
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import audio, io_json
from ..library import FLAT_VARIANT, Library, Recording, _is_wav, scan_library

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
        variantsChanged(list)
            the enabled variant names, emitted when the user toggles the
            "Variants" filter (caller persists per folder).

    Extra ``.wav`` files can be dragged onto the panel; they appear as flat
    rows (no variant) appended after the scanned recordings. Right-clicking a
    row offers "Audio info" and "Remove from list" (the latter is a transient,
    session-only hide for scanned files — Refresh brings them back).
    """

    selectionChanged = Signal(str, bool)
    variantsChanged = Signal(list)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._library: Optional[Library] = None
        self._root: Optional[str] = None
        # One entry per visible row: (recording, variant).
        self._entries: list[tuple[Recording, str]] = []
        self._last_key: Optional[str] = None
        # Enabled variant names; None means "show all".
        self._enabled_variants: Optional[set[str]] = None
        self._variant_actions: dict[str, QAction] = {}
        # Ad-hoc dropped .wav files (flat recordings) and session-removed rows.
        self._extra_recordings: list[Recording] = []
        self._removed: set[tuple[str, str]] = set()

        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        header = QHBoxLayout()
        self._title = QLabel("No folder open")
        self._title.setWordWrap(True)
        header.addWidget(self._title, 1)

        # Variant filter: a popup checklist of subfolders to show as rows.
        self._variant_btn = QToolButton()
        self._variant_btn.setText("Variants ▾")
        self._variant_btn.setToolTip("Choose which variant subfolders to list")
        self._variant_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._variant_menu = QMenu(self._variant_btn)
        self._variant_btn.setMenu(self._variant_menu)
        self._variant_btn.setVisible(False)
        header.addWidget(self._variant_btn, 0)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setToolTip("Re-scan the folder for added/changed files")
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self._refresh_btn, 0)
        layout.addLayout(header)

        self._list = QListWidget()
        self._list.setAcceptDrops(False)  # let drops fall through to the panel
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._list)

    # ------------------------------------------------------------------ #
    # Folder loading
    # ------------------------------------------------------------------ #
    def set_folder(self, path: str, enabled_variants: Optional[list[str]] = None) -> None:
        """Scan ``path`` and populate the panel.

        ``enabled_variants`` is the remembered variant whitelist for this folder
        (``None`` -> show all). Names no longer present are ignored; if none
        match, falls back to showing all.
        """
        self._root = path
        self._refresh_btn.setEnabled(True)
        self._library = scan_library(path)
        self._extra_recordings.clear()
        self._removed.clear()

        variants = self._library.variants
        if enabled_variants is None:
            self._enabled_variants = None
        else:
            keep = {v for v in variants if v in enabled_variants}
            self._enabled_variants = keep if keep else None

        self._rebuild_variant_menu()
        self._set_title()
        self._rebuild_entries(restore=False, force_reload=False)

    def refresh(self) -> None:
        """Re-scan the current folder, preserving the selected row if it survives.

        Useful when wav files are added/removed/edited outside the app. The
        selection is restored by (recording key, variant); if that pair is gone,
        falls back to the first row. The variant filter is kept.
        """
        if self._root is None:
            return
        self._library = scan_library(self._root)
        self._removed.clear()  # session-removed scanned rows come back on refresh
        self._rebuild_variant_menu()
        self._set_title()
        self._rebuild_entries(restore=True, force_reload=True)

    def _set_title(self) -> None:
        n = (len(self._library.recordings) if self._library else 0) + len(
            self._extra_recordings
        )
        if self._root:
            base = os.path.basename(self._root) or self._root
        elif self._extra_recordings:
            base = "Dropped files"
        else:
            base = "No folder open"
        suffix = f"  ({n} recordings)" if (self._root or self._extra_recordings) else ""
        self._title.setText(base + suffix)

    # ------------------------------------------------------------------ #
    # Variant filter
    # ------------------------------------------------------------------ #
    def _rebuild_variant_menu(self) -> None:
        """Rebuild the Variants checklist from the scanned variant names."""
        self._variant_menu.clear()
        self._variant_actions.clear()
        variants = self._library.variants if self._library else []
        flat = (not variants) or variants == [FLAT_VARIANT]
        self._variant_btn.setVisible(not flat)
        if flat:
            return
        for v in variants:
            act = self._variant_menu.addAction(v)
            act.setCheckable(True)
            act.setChecked(self._enabled_variants is None or v in self._enabled_variants)
            act.toggled.connect(self._on_variant_toggled)
            self._variant_actions[v] = act

    def _on_variant_toggled(self, _checked: bool = False) -> None:
        self._enabled_variants = {
            v for v, act in self._variant_actions.items() if act.isChecked()
        }
        self._rebuild_entries(restore=True, force_reload=False)
        self.variantsChanged.emit(sorted(self._enabled_variants))

    def _variant_enabled(self, variant: str) -> bool:
        return self._enabled_variants is None or variant in self._enabled_variants

    # ------------------------------------------------------------------ #
    # Drag-and-drop (add files) + row context menu
    # ------------------------------------------------------------------ #
    def _wav_urls(self, mime) -> list[str]:
        if not mime.hasUrls():
            return []
        out = []
        for url in mime.urls():
            p = url.toLocalFile()
            if p and _is_wav(p) and os.path.isfile(p):
                out.append(p)
        return out

    def dragEnterEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        if self._wav_urls(ev.mimeData()):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        if self._wav_urls(ev.mimeData()):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dropEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        paths = self._wav_urls(ev.mimeData())
        if paths:
            self.add_files(paths)
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def add_files(self, paths: list[str]) -> None:
        """Append ``.wav`` files as flat (no-variant) rows; skip duplicates."""
        known = {r.variants.get(FLAT_VARIANT) for r in self._extra_recordings}
        added = False
        for p in paths:
            if not (_is_wav(p) and os.path.isfile(p)):
                continue
            ap = os.path.abspath(p)
            if ap in known:
                continue
            self._extra_recordings.append(
                Recording(key=os.path.basename(ap), variants={FLAT_VARIANT: ap})
            )
            known.add(ap)
            added = True
        if added:
            self._set_title()
            self._rebuild_entries(restore=True, force_reload=False)

    def _on_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        row = self._list.row(item)
        menu = QMenu(self)
        info_act = menu.addAction("Audio info…")
        remove_act = menu.addAction("Remove from list")
        chosen = menu.exec(self._list.viewport().mapToGlobal(pos))
        if chosen == info_act:
            self._show_audio_info(row)
        elif chosen == remove_act:
            self._remove_row(row)

    def _remove_row(self, row: int) -> None:
        """Take a row out of the list (session-only for scanned files)."""
        if not (0 <= row < len(self._entries)):
            return
        rec, variant = self._entries[row]
        if variant == FLAT_VARIANT and rec in self._extra_recordings:
            self._extra_recordings.remove(rec)
        else:
            self._removed.add((rec.key, variant))
        self._set_title()
        self._rebuild_entries(restore=True, force_reload=False)

    def _show_audio_info(self, row: int) -> None:
        if not (0 <= row < len(self._entries)):
            return
        rec, variant = self._entries[row]
        path = rec.path_for(variant)
        if not path:
            return
        try:
            d = audio.describe(path)
        except Exception as exc:  # noqa: BLE001 — surface any read failure
            QMessageBox.warning(
                self, "Audio info", f"Could not read {os.path.basename(path)}:\n{exc}"
            )
            return
        dur = d["duration"]
        mm, ss = divmod(dur, 60.0)
        text = (
            f"File:\t{os.path.basename(path)}\n"
            f"Sample rate:\t{d['samplerate']} Hz\n"
            f"Channels:\t{d['channels']}\n"
            f"Duration:\t{dur:.3f} s  ({int(mm)}:{ss:05.2f})\n"
            f"Frames:\t{d['frames']}\n"
            f"Format:\t{d['format']}\n\n"
            f"{path}"
        )
        QMessageBox.information(self, "Audio info", text)

    # ------------------------------------------------------------------ #
    # List building
    # ------------------------------------------------------------------ #
    def _rebuild_entries(self, restore: bool, force_reload: bool) -> None:
        """Rebuild the visible rows from the current library + variant filter.

        ``restore`` keeps the prior (key, variant) selection if it survives.
        ``force_reload`` re-emits selectionChanged even when the selection is
        unchanged (used after a rescan, since the file on disk may have changed).
        """
        keep = self._current_entry()
        keep_pair = (keep[0].key, keep[1]) if keep is not None else None

        recs = self._library.recordings if self._library else []
        variants = self._library.variants if self._library else []
        scanned = [
            (rec, variant)
            for rec in recs
            for variant in variants
            if variant in rec.variants
            and self._variant_enabled(variant)
            and (rec.key, variant) not in self._removed
        ]
        # Dropped files always show (not subject to the variant filter).
        extras = [(rec, FLAT_VARIANT) for rec in self._extra_recordings]
        self._entries = scanned + extras
        self._last_key = None

        self._list.blockSignals(True)
        self._list.clear()
        for rec, variant in self._entries:
            self._list.addItem(self._make_item(rec, variant))
        self._list.blockSignals(False)

        if not self._entries:
            return
        if not restore:
            self._list.setCurrentRow(0)  # emits via _on_row_changed
            return

        target = 0
        if keep_pair is not None:
            for row, (rec, variant) in enumerate(self._entries):
                if (rec.key, variant) == keep_pair:
                    target = row
                    break
        self._list.blockSignals(True)
        self._list.setCurrentRow(target)
        self._list.blockSignals(False)
        rec, variant = self._entries[target]
        self._last_key = rec.key
        if force_reload or (rec.key, variant) != keep_pair:
            path = rec.path_for(variant)
            if path:
                same_recording = keep_pair is not None and rec.key == keep_pair[0]
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
