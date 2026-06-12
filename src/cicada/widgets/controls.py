"""Settings panel — live spectrogram parameters.

:class:`SettingsPanel` holds the live spectrogram-parameter editors (n_fft, hop,
window, colormap, dB levels, f_max). It emits a fresh
:class:`~cicada.spectrogram.SpectrogramParams` whenever a parameter changes, so
the spectrogram re-renders live while the panel (typically shown in the
*View → Settings…* dialog) is open. Playback and mode controls live elsewhere
(the top toolbar and the left panel respectively).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QSpinBox,
    QWidget,
)

from ..spectrogram import WINDOWS, SpectrogramParams

_NFFT_CHOICES = (256, 512, 1024, 2048, 4096)
_COLORMAPS = ("viridis", "magma", "inferno", "plasma", "gray")


class SettingsPanel(QWidget):
    """Spectrogram parameter editors.

    Signals::

        paramsChanged(object)        a fresh SpectrogramParams (n_fft/hop/...)
        colormapChanged(str)         the new colormap name
    """

    paramsChanged = Signal(object)
    colormapChanged = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._emitting = False  # guard against feedback while setting defaults

        form = QFormLayout(self)
        form.setContentsMargins(8, 8, 8, 8)

        self._nfft = QComboBox()
        for n in _NFFT_CHOICES:
            self._nfft.addItem(str(n), n)
        self._nfft.setCurrentText("1024")
        self._nfft.currentIndexChanged.connect(self._on_params)
        form.addRow("n_fft", self._nfft)

        self._hop = QSpinBox()
        self._hop.setRange(1, 8192)
        self._hop.setValue(256)
        self._hop.valueChanged.connect(self._on_params)
        form.addRow("hop", self._hop)

        self._window = QComboBox()
        self._window.addItems(list(WINDOWS))
        self._window.setCurrentText("hann")
        self._window.currentIndexChanged.connect(self._on_params)
        form.addRow("window", self._window)

        self._colormap = QComboBox()
        self._colormap.addItems(list(_COLORMAPS))
        self._colormap.setCurrentText("viridis")
        self._colormap.currentTextChanged.connect(self._on_colormap)
        form.addRow("colormap", self._colormap)

        self._db_floor = QDoubleSpinBox()
        self._db_floor.setRange(-200.0, 0.0)
        self._db_floor.setValue(-100.0)
        self._db_floor.valueChanged.connect(self._on_params)
        form.addRow("dB floor", self._db_floor)

        self._db_ceil = QDoubleSpinBox()
        self._db_ceil.setRange(-200.0, 60.0)
        self._db_ceil.setValue(0.0)
        self._db_ceil.valueChanged.connect(self._on_params)
        form.addRow("dB ceil", self._db_ceil)

        self._nyquist = QCheckBox("f_max = Nyquist")
        self._nyquist.setChecked(True)
        self._nyquist.toggled.connect(self._on_nyquist_toggled)
        form.addRow(self._nyquist)

        self._f_max = QDoubleSpinBox()
        self._f_max.setRange(1.0, 1_000_000.0)
        self._f_max.setValue(22050.0)
        self._f_max.setSuffix(" Hz")
        self._f_max.setEnabled(False)
        self._f_max.valueChanged.connect(self._on_params)
        form.addRow("f_max", self._f_max)

    # ------------------------------------------------------------------ #
    # Param assembly / signals
    # ------------------------------------------------------------------ #
    def current_params(self) -> SpectrogramParams:
        """Assemble a fresh :class:`SpectrogramParams` from the widgets."""
        f_max = None if self._nyquist.isChecked() else float(self._f_max.value())
        return SpectrogramParams(
            n_fft=int(self._nfft.currentData()),
            hop=int(self._hop.value()),
            window=self._window.currentText(),
            db_floor=float(self._db_floor.value()),
            db_ceil=float(self._db_ceil.value()),
            f_max=f_max,
        )

    def current_colormap(self) -> str:
        """Return the selected colormap name."""
        return self._colormap.currentText()

    def _on_params(self, *_args) -> None:
        if self._emitting:
            return
        self.paramsChanged.emit(self.current_params())

    def _on_colormap(self, name: str) -> None:
        if self._emitting:
            return
        self.colormapChanged.emit(name)

    def _on_nyquist_toggled(self, checked: bool) -> None:
        self._f_max.setEnabled(not checked)
        self._on_params()

    # ------------------------------------------------------------------ #
    # Programmatic defaults (from config)
    # ------------------------------------------------------------------ #
    def apply_params(self, params: SpectrogramParams, colormap: str) -> None:
        """Set the widgets from ``params``/``colormap`` without emitting."""
        self._emitting = True
        idx = self._nfft.findData(int(params.n_fft))
        if idx >= 0:
            self._nfft.setCurrentIndex(idx)
        self._hop.setValue(int(params.hop))
        if params.window in WINDOWS:
            self._window.setCurrentText(params.window)
        self._db_floor.setValue(float(params.db_floor))
        self._db_ceil.setValue(float(params.db_ceil))
        if params.f_max is None:
            self._nyquist.setChecked(True)
            self._f_max.setEnabled(False)
        else:
            self._nyquist.setChecked(False)
            self._f_max.setEnabled(True)
            self._f_max.setValue(float(params.f_max))
        if colormap in _COLORMAPS:
            self._colormap.setCurrentText(colormap)
        self._emitting = False
