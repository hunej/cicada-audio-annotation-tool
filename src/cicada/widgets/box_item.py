"""Interactive annotation rectangle for the spectrogram view.

A :class:`BoxROI` is a movable/resizable pyqtgraph ROI living in *data*
coordinates, where x = time (s) and y = frequency (Hz). Because the spectrogram
:class:`~pyqtgraph.ImageItem` is mapped into (t, f) data coords via ``setRect``,
the ROI's ``pos()``/``size()`` are already in physical units; converting to a
:class:`~cicada.models.Box` only requires normalizing and computing pixel coords
via :func:`~cicada.models.tf_to_px`.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor

from ..models import Box, tf_to_px


class BoxROI(pg.RectROI):
    """A labelled, resizable rectangle in (time, frequency) data coordinates.

    Selection is on **double-click** (``doubleClicked``); a single click is
    ignored so it falls through to the view and sets the play cursor instead.
    Dragging the body still moves the box; corner handles still resize it.
    """

    doubleClicked = Signal(object)

    def __init__(
        self,
        t0: float,
        f0: float,
        w_t: float,
        h_f: float,
        label: str,
        color: str,
    ) -> None:
        super().__init__(
            pos=[t0, f0],
            size=[w_t, h_f],
            movable=True,
            resizable=True,
            removable=True,
        )
        self.label: str = label
        self._color: str = color

        # A scale handle at each corner so the box resizes from any side.
        self.addScaleHandle([1, 1], [0, 0])
        self.addScaleHandle([0, 0], [1, 1])
        self.addScaleHandle([1, 0], [0, 1])
        self.addScaleHandle([0, 1], [1, 0])

        # Label text pinned to the top-left of the box (top = high freq).
        self._text = pg.TextItem(text=label, anchor=(0, 1))

        self._apply_color(color)
        self._update_label_pos()
        self.sigRegionChanged.connect(self._update_label_pos)

    # -- styling -----------------------------------------------------------
    def _apply_color(self, color: str) -> None:
        qcolor = QColor(color)
        self.setPen(pg.mkPen(qcolor, width=2))
        hover = QColor(qcolor)
        hover.setAlpha(255)
        self.hoverPen = pg.mkPen(hover, width=3)
        # Semi-transparent fill via hover brush is optional; keep hollow so the
        # spectrogram underneath stays visible. Tint the label to match.
        self._text.setColor(qcolor)

    def set_label(self, name: str, color: str) -> None:
        """Update the label name + color (text and pen)."""
        self.label = name
        self._color = color
        self._text.setText(name)
        self._apply_color(color)

    # -- mouse ------------------------------------------------------------
    def mouseClickEvent(self, ev) -> None:  # noqa: N802 (pg API)
        """Double-click selects; single left-click falls through to the view."""
        if ev.button() == Qt.MouseButton.LeftButton:
            if ev.double():
                self.doubleClicked.emit(self)
                ev.accept()
            else:
                # Ignore so the click reaches the ViewBox and sets the cursor.
                ev.ignore()
            return
        super().mouseClickEvent(ev)

    def set_selected(self, selected: bool) -> None:
        """Highlight (thicker/brighter pen) when selected."""
        qcolor = QColor(self._color)
        if selected:
            self.setPen(pg.mkPen(QColor("#ffffff"), width=3))
        else:
            self.setPen(pg.mkPen(qcolor, width=2))

    # -- label positioning -------------------------------------------------
    def _update_label_pos(self) -> None:
        pos = self.pos()
        size = self.size()
        x = pos.x()
        # Top-left corner = min x, max y (high frequency at top of the box).
        top_y = pos.y() + size.y() if size.y() >= 0 else pos.y()
        left_x = x if size.x() >= 0 else x + size.x()
        self._text.setPos(left_x, top_y)

    # -- view membership ---------------------------------------------------
    def add_to(self, viewbox: pg.ViewBox) -> None:
        """Add both the ROI and its label to ``viewbox``."""
        viewbox.addItem(self)
        viewbox.addItem(self._text)
        self._update_label_pos()

    def remove_from(self, viewbox: pg.ViewBox) -> None:
        """Remove both the ROI and its label from ``viewbox``."""
        viewbox.removeItem(self)
        viewbox.removeItem(self._text)

    # -- conversion --------------------------------------------------------
    def to_box(
        self,
        duration: float,
        f_max: float,
        n_cols: int,
        n_rows: int,
    ) -> Box:
        """Convert this ROI's (t, f) rect to a normalized :class:`Box`."""
        pos = self.pos()
        size = self.size()
        t_start = pos.x()
        t_end = pos.x() + size.x()
        f_low = pos.y()
        f_high = pos.y() + size.y()
        box = Box(
            label=self.label,
            t_start=t_start,
            t_end=t_end,
            f_low=f_low,
            f_high=f_high,
        ).normalized()
        box.px = tf_to_px(
            box.t_start,
            box.t_end,
            box.f_low,
            box.f_high,
            duration,
            f_max,
            n_cols,
            n_rows,
        )
        return box

    @classmethod
    def from_box(cls, box: Box, color: str) -> "BoxROI":
        """Build a :class:`BoxROI` covering ``box``'s (t, f) rectangle."""
        b = box.normalized()
        return cls(
            t0=b.t_start,
            f0=b.f_low,
            w_t=b.t_end - b.t_start,
            h_f=b.f_high - b.f_low,
            label=b.label,
            color=color,
        )

    def rect(self) -> QRectF:
        """Return the current (t, f) rectangle as a :class:`QRectF`."""
        pos = self.pos()
        size = self.size()
        return QRectF(pos.x(), pos.y(), size.x(), size.y())
