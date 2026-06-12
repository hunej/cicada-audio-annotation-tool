"""Label panel — pick the active label, add labels, relabel the selection.

:class:`LabelPanel` shows the predefined labels (name + color swatch), lets the
user choose which one is *active* (used for new boxes), add a new label (with an
auto-assigned color), and apply the active label to the currently-selected box.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import label_config
from ..label_config import DEFAULT_LABELS, LabelDef

# Palette used to auto-assign colors to newly added labels.
_NEW_PALETTE = [
    "#911eb4",
    "#46f0f0",
    "#f032e6",
    "#bcf60c",
    "#fabebe",
    "#008080",
    "#9a6324",
    "#808000",
]


def _swatch(color: str) -> QIcon:
    """Return a small colored-square icon for ``color``."""
    pix = QPixmap(14, 14)
    pix.fill(QColor(color))
    return QIcon(pix)


class LabelPanel(QWidget):
    """Active-label selector + label editor.

    Signals::

        activeLabelChanged(object)   the newly active LabelDef
        applyToSelected(object)      apply this LabelDef to the selected box
        labelsChanged()              a label was added (caller persists)
    """

    activeLabelChanged = Signal(object)
    applyToSelected = Signal(object)
    labelsChanged = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._labels: list[LabelDef] = [LabelDef(l.name, l.color) for l in DEFAULT_LABELS]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        layout.addWidget(QLabel("Labels"))

        self._list = QListWidget()
        self._list.setIconSize(QSize(14, 14))
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        self._add_btn = QPushButton("Add…")
        self._add_btn.clicked.connect(self._on_add)
        btn_row.addWidget(self._add_btn)

        self._apply_btn = QPushButton("Apply to selected box")
        self._apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(self._apply_btn)
        layout.addLayout(btn_row)

        self._rebuild()

    # ------------------------------------------------------------------ #
    # Label list
    # ------------------------------------------------------------------ #
    def set_labels(self, labels: list[LabelDef]) -> None:
        """Replace the label set and refresh the list."""
        self._labels = [LabelDef(l.name, l.color) for l in labels]
        self._rebuild()

    def _rebuild(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for lbl in self._labels:
            item = QListWidgetItem(_swatch(lbl.color), lbl.name)
            item.setData(Qt.ItemDataRole.UserRole, lbl.name)
            self._list.addItem(item)
        if self._labels:
            self._list.setCurrentRow(0)
        self._list.blockSignals(False)
        if self._labels:
            self.activeLabelChanged.emit(self.active_label())

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    def active_label(self) -> LabelDef:
        """Return the currently selected (active) label.

        Falls back to the first label if nothing is selected.
        """
        row = self._list.currentRow()
        if 0 <= row < len(self._labels):
            return self._labels[row]
        return self._labels[0] if self._labels else LabelDef("call", "#e6194b")

    def labels(self) -> list[LabelDef]:
        """Return a copy of the full label set."""
        return [LabelDef(l.name, l.color) for l in self._labels]

    def color_for(self, name: str) -> str:
        """Return the hex color for ``name`` (deterministic for unknowns)."""
        return label_config.color_for(self._labels, name)

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._labels):
            self.activeLabelChanged.emit(self._labels[row])

    def _on_apply(self) -> None:
        self.applyToSelected.emit(self.active_label())

    def _on_add(self) -> None:
        name, ok = QInputDialog.getText(self, "Add label", "Label name:")
        name = name.strip()
        if not ok or not name:
            return
        if any(l.name == name for l in self._labels):
            # Already exists — just make it active.
            for i, l in enumerate(self._labels):
                if l.name == name:
                    self._list.setCurrentRow(i)
            return
        color = _NEW_PALETTE[len(self._labels) % len(_NEW_PALETTE)]
        self._labels.append(LabelDef(name, color))
        item = QListWidgetItem(_swatch(color), name)
        item.setData(Qt.ItemDataRole.UserRole, name)
        self._list.addItem(item)
        self._list.setCurrentRow(self._list.count() - 1)
        self.labelsChanged.emit()
