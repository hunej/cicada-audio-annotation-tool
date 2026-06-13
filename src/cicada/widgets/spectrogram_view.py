"""Interactive spectrogram + annotation widget (WP3 core).

:class:`SpectrogramView` displays a :class:`~cicada.spectrogram.SpectrogramResult`
as an image mapped into (time, frequency) data coordinates and lets the user
draw, move, resize, select, relabel and delete :class:`BoxROI` annotations.

The public API here is the contract WP4 builds on; see the method/signal list in
the class docstring.
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..models import Box
from ..spectrogram import SpectrogramResult
from .box_item import BoxROI


class _ResetAxis(pg.AxisItem):
    """AxisItem that resets *its own* axis to full extent on double-click.

    Double-clicking the time (bottom) axis auto-ranges time only; the frequency
    (left) axis auto-ranges frequency only. Single clicks / drags fall through to
    the default :class:`~pyqtgraph.AxisItem` behaviour (drag-to-zoom that axis).
    """

    def __init__(self, view: "SpectrogramView", which: str, orientation: str) -> None:
        super().__init__(orientation=orientation)
        self._view = view
        self._which = which  # "x" (time) or "y" (frequency)

    def mouseClickEvent(self, ev) -> None:  # noqa: N802 (pg API)
        if ev.button() == Qt.MouseButton.LeftButton and ev.double():
            self._view._reset_axis(self._which)
            ev.accept()
            return
        super().mouseClickEvent(ev)


class _AnnotateViewBox(pg.ViewBox):
    """ViewBox that draws rubber-band boxes on drag while in annotate mode.

    When ``annotate`` is True a left-button drag over the plot creates a new
    :class:`BoxROI` (via the owning view's callbacks) instead of panning. Other
    interactions (panning when not annotating, right-button zoom) fall back to
    the default :class:`~pyqtgraph.ViewBox` behaviour.

    Two audio-oriented tweaks override the defaults:

    * the mouse wheel over the plot area zooms the **time** axis only (the full
      band is usually wanted while scanning along time); wheeling *over* an axis
      still zooms just that axis, since the axis passes an explicit ``axis``;
    * a double-click on the empty plot resets **both** axes to the full view.
    """

    def __init__(self, view: "SpectrogramView", **kwargs) -> None:
        super().__init__(**kwargs)
        self._view = view
        self.annotate: bool = False

    def mouseDragEvent(self, ev, axis=None) -> None:  # noqa: N802 (pg API)
        if not self.annotate or ev.button() != Qt.MouseButton.LeftButton:
            super().mouseDragEvent(ev, axis=axis)
            return

        ev.accept()
        view_pos = self.mapSceneToView(ev.scenePos())
        if ev.isStart():
            start = self.mapSceneToView(ev.buttonDownScenePos())
            self._view._begin_new_box(start)
        self._view._drag_new_box(view_pos)
        if ev.isFinish():
            self._view._finish_new_box()

    def wheelEvent(self, ev, axis=None) -> None:  # noqa: N802 (pg API)
        # Over the plot area (axis is None) confine zoom to time (X); when an
        # AxisItem forwards the wheel it passes axis=0/1 and we honour it.
        if axis is None:
            axis = pg.ViewBox.XAxis
        super().wheelEvent(ev, axis=axis)

    def mouseClickEvent(self, ev) -> None:  # noqa: N802 (pg API)
        # Double-click on empty spectrogram area resets the whole view.
        if ev.button() == Qt.MouseButton.LeftButton and ev.double():
            self._view.reset_view()
            ev.accept()
            return
        # A plain left click on empty spectrogram area sets the play cursor.
        # (Clicks on a BoxROI are consumed by the ROI before reaching here.)
        if ev.button() == Qt.MouseButton.LeftButton:
            p = self.mapSceneToView(ev.scenePos())
            self._view._on_plot_clicked(p.x())
            ev.accept()
            return
        super().mouseClickEvent(ev)


class SpectrogramView(QWidget):
    """Spectrogram display + annotation surface.

    Public API (relied on by WP4)::

        set_spectrogram(result)        set_colormap(name)
        set_levels(db_floor, db_ceil)  set_annotate_mode(enabled)
        set_active_label(name, color)  set_boxes(boxes, color_for)
        get_boxes() -> list[Box]       clear_boxes()
        selected_box() -> Box | None   relabel_selected(name, color)
        get_view_range() -> (t0,t1,f0,f1)
        set_view_range(t0,t1,f0,f1)

    Signals::

        boxesChanged()                 (box added / edited / deleted)
        boxSelected(object)            the selected Box, or None
        viewRangeChanged(float, float, float, float)  (t0, t1, f0, f1)
    """

    boxesChanged = Signal()
    boxSelected = Signal(object)
    viewRangeChanged = Signal(float, float, float, float)
    positionClicked = Signal(float)  # user clicked to set play position (t, sec)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._result: Optional[SpectrogramResult] = None
        self._rois: list[BoxROI] = []
        self._selected: Optional[BoxROI] = None
        self._new_roi: Optional[BoxROI] = None

        self._active_label: str = "call"
        self._active_color: str = "#e6194b"

        self._db_floor: float = -100.0
        self._db_ceil: float = 0.0
        self._colormap_name: str = "viridis"
        self._view_pinned: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._glw = pg.GraphicsLayoutWidget()
        layout.addWidget(self._glw)

        self._vb = _AnnotateViewBox(self)
        self._plot = self._glw.addPlot(
            viewBox=self._vb,
            axisItems={
                "bottom": _ResetAxis(self, "x", "bottom"),
                "left": _ResetAxis(self, "y", "left"),
            },
        )
        self._plot.setLabel("bottom", "Time (s)")
        self._plot.setLabel("left", "Frequency (Hz)")
        # Low frequency at the bottom, increasing upward.
        self._vb.invertY(False)

        self._image = pg.ImageItem(axisOrder="row-major")
        self._plot.addItem(self._image)

        self._cmap = pg.colormap.get(self._colormap_name)
        self._image.setLookupTable(self._cmap.getLookupTable(nPts=256))

        # ColorBar gives a legend; also drives the LUT/levels uniformly.
        self._colorbar = pg.ColorBarItem(
            values=(self._db_floor, self._db_ceil),
            colorMap=self._cmap,
            label="dB",
        )
        self._colorbar.setImageItem(self._image, insert_in=self._plot)

        # Play cursor: a vertical line at the current playback time. Not movable
        # by drag (position is driven by clicks / playback), drawn above the image.
        self._playhead = pg.InfiniteLine(
            pos=0.0,
            angle=90,
            movable=False,
            pen=pg.mkPen("#00e5ff", width=2),
        )
        self._playhead.setZValue(20)
        self._plot.addItem(self._playhead, ignoreBounds=True)

        self._vb.sigRangeChanged.connect(self._on_range_changed)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ------------------------------------------------------------------ #
    # Spectrogram display
    # ------------------------------------------------------------------ #
    def set_spectrogram(self, result: SpectrogramResult) -> None:
        """Display ``result`` and map it into (t, f) data coordinates."""
        self._result = result
        self._image.setImage(result.image, autoLevels=False)
        self._image.setRect(
            pg.QtCore.QRectF(0.0, 0.0, float(result.duration), float(result.f_max))
        )
        self._apply_levels()
        if not self._view_pinned:
            self._plot.autoRange()

    def set_colormap(self, name: str) -> None:
        """Switch the colormap without recomputing the spectrogram."""
        self._colormap_name = name
        self._cmap = pg.colormap.get(name)
        self._image.setLookupTable(self._cmap.getLookupTable(nPts=256))
        self._colorbar.setColorMap(self._cmap)

    def set_levels(self, db_floor: float, db_ceil: float) -> None:
        """Set the dB display range without recomputing the spectrogram."""
        self._db_floor = float(db_floor)
        self._db_ceil = float(db_ceil)
        self._apply_levels()

    def _apply_levels(self) -> None:
        self._image.setLevels((self._db_floor, self._db_ceil))
        self._colorbar.setLevels((self._db_floor, self._db_ceil))

    # ------------------------------------------------------------------ #
    # Annotate mode / active label
    # ------------------------------------------------------------------ #
    def set_annotate_mode(self, enabled: bool) -> None:
        """Toggle box-drawing on drag (True) vs. panning (False)."""
        self._vb.annotate = bool(enabled)

    def set_active_label(self, name: str, color: str) -> None:
        """New boxes drawn from now on use this label name + color."""
        self._active_label = name
        self._active_color = color

    # ------------------------------------------------------------------ #
    # New-box drawing (driven by _AnnotateViewBox)
    # ------------------------------------------------------------------ #
    def _clamp_point(self, x: float, y: float) -> tuple[float, float]:
        if self._result is not None:
            x = float(np.clip(x, 0.0, self._result.duration))
            y = float(np.clip(y, 0.0, self._result.f_max))
        return x, y

    def _begin_new_box(self, start_pt) -> None:
        x0, y0 = self._clamp_point(start_pt.x(), start_pt.y())
        self._drag_origin = (x0, y0)
        roi = BoxROI(x0, y0, 0.0, 0.0, self._active_label, self._active_color)
        roi.add_to(self._vb)
        self._new_roi = roi

    def _drag_new_box(self, cur_pt) -> None:
        if self._new_roi is None:
            return
        x0, y0 = self._drag_origin
        x1, y1 = self._clamp_point(cur_pt.x(), cur_pt.y())
        left, right = sorted((x0, x1))
        bottom, top = sorted((y0, y1))
        self._new_roi.setPos([left, bottom], finish=False)
        self._new_roi.setSize([right - left, top - bottom], finish=False)

    def _finish_new_box(self) -> None:
        roi = self._new_roi
        self._new_roi = None
        if roi is None:
            return
        size = roi.size()
        # Discard degenerate (click without drag) boxes.
        if abs(size.x()) < 1e-9 or abs(size.y()) < 1e-9:
            roi.remove_from(self._vb)
            return
        self._wire_roi(roi)
        self._rois.append(roi)
        self._select_roi(roi)
        self.boxesChanged.emit()

    # ------------------------------------------------------------------ #
    # Box collection management
    # ------------------------------------------------------------------ #
    def _wire_roi(self, roi: BoxROI) -> None:
        roi.sigRegionChangeFinished.connect(self._on_roi_edited)
        roi.doubleClicked.connect(self._on_roi_clicked)  # double-click to select
        roi.sigRemoveRequested.connect(self._on_roi_remove_requested)

    def set_boxes(self, boxes: list[Box], color_for: Callable[[str], str]) -> None:
        """Replace all ROIs with one :class:`BoxROI` per ``Box``."""
        self.clear_boxes()
        for box in boxes:
            roi = BoxROI.from_box(box, color_for(box.label))
            roi.add_to(self._vb)
            self._wire_roi(roi)
            self._rois.append(roi)
        self._selected = None
        self.boxSelected.emit(None)

    def get_boxes(self) -> list[Box]:
        """Return all current ROIs as :class:`Box` objects."""
        if self._result is None:
            return []
        r = self._result
        n_rows, n_cols = r.image.shape
        return [
            roi.to_box(r.duration, r.f_max, n_cols, n_rows) for roi in self._rois
        ]

    def clear_boxes(self) -> None:
        """Remove every ROI from the view."""
        for roi in self._rois:
            roi.remove_from(self._vb)
        self._rois.clear()
        self._selected = None

    # ------------------------------------------------------------------ #
    # Selection / relabel / delete
    # ------------------------------------------------------------------ #
    def _select_roi(self, roi: Optional[BoxROI]) -> None:
        if self._selected is roi:
            if roi is not None:
                roi.set_selected(True)
            return
        if self._selected is not None:
            self._selected.set_selected(False)
        self._selected = roi
        if roi is not None:
            roi.set_selected(True)
        self.boxSelected.emit(self._selected_box())

    def _selected_box(self) -> Optional[Box]:
        if self._selected is None or self._result is None:
            return None
        r = self._result
        n_rows, n_cols = r.image.shape
        return self._selected.to_box(r.duration, r.f_max, n_cols, n_rows)

    def selected_box(self) -> Optional[Box]:
        """Return the selected ROI as a :class:`Box`, or ``None``."""
        return self._selected_box()

    def relabel_selected(self, name: str, color: str) -> None:
        """Change the selected ROI's label name + color."""
        if self._selected is None:
            return
        self._selected.set_label(name, color)
        self._selected.set_selected(True)
        self.boxesChanged.emit()
        self.boxSelected.emit(self._selected_box())

    def _delete_selected(self) -> None:
        if self._selected is None:
            return
        roi = self._selected
        roi.remove_from(self._vb)
        if roi in self._rois:
            self._rois.remove(roi)
        self._selected = None
        self.boxSelected.emit(None)
        self.boxesChanged.emit()

    # ------------------------------------------------------------------ #
    # ROI signal handlers
    # ------------------------------------------------------------------ #
    def _on_roi_clicked(self, roi) -> None:
        self._select_roi(roi)

    def _on_roi_edited(self, roi) -> None:
        if self._selected is not roi:
            self._select_roi(roi)
        else:
            self.boxSelected.emit(self._selected_box())
        self.boxesChanged.emit()

    def _on_roi_remove_requested(self, roi) -> None:
        roi.remove_from(self._vb)
        if roi in self._rois:
            self._rois.remove(roi)
        if self._selected is roi:
            self._selected = None
            self.boxSelected.emit(None)
        self.boxesChanged.emit()

    def keyPressEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        if ev.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._delete_selected()
            ev.accept()
            return
        super().keyPressEvent(ev)

    # ------------------------------------------------------------------ #
    # View range / lock
    # ------------------------------------------------------------------ #
    def get_view_range(self) -> tuple[float, float, float, float]:
        """Return the currently visible ``(t0, t1, f0, f1)`` range."""
        (t0, t1), (f0, f1) = self._vb.viewRange()
        return float(t0), float(t1), float(f0), float(f1)

    def set_view_range(self, t0: float, t1: float, f0: float, f1: float) -> None:
        """Pin the visible range to ``(t0, t1, f0, f1)``."""
        self._view_pinned = True
        self._vb.setXRange(t0, t1, padding=0)
        self._vb.setYRange(f0, f1, padding=0)

    def reset_view(self) -> None:
        """Unpin and auto-range to the full spectrogram extent (both axes)."""
        self._view_pinned = False
        self._plot.autoRange()

    def _reset_axis(self, which: str) -> None:
        """Auto-range a single axis to full extent (``"x"`` time / ``"y"`` freq)."""
        vb_axis = pg.ViewBox.XAxis if which == "x" else pg.ViewBox.YAxis
        self._vb.enableAutoRange(axis=vb_axis, enable=True)

    # ------------------------------------------------------------------ #
    # Play cursor (playhead)
    # ------------------------------------------------------------------ #
    def set_playhead(self, t: float) -> None:
        """Move the vertical play cursor to time ``t`` (seconds)."""
        self._playhead.setPos(float(t))

    def playhead(self) -> float:
        """Current play-cursor time in seconds."""
        return float(self._playhead.value())

    def _on_plot_clicked(self, x: float) -> None:
        """A click on the spectrogram sets the play cursor."""
        if self._result is not None:
            x = float(np.clip(x, 0.0, self._result.duration))
        self._playhead.setPos(x)
        self.positionClicked.emit(x)

    def _on_range_changed(self, *_args) -> None:
        # Any user navigation pins the view so later spectrograms don't reset it.
        self._view_pinned = True
        t0, t1, f0, f1 = self.get_view_range()
        self.viewRangeChanged.emit(t0, t1, f0, f1)
