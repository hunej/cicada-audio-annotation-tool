"""Spectrogram computation — contract + implementation entry points.

WP1 fills in :func:`compute`. The :class:`SpectrogramParams` dataclass and the
:class:`SpectrogramResult` return type are the stable contract that the GUI
(WP3/WP4) imports, so keep their fields stable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import get_window, stft

from .models import SpectrogramMeta

# Window names accepted by scipy.signal.get_window; surfaced in the UI dropdown.
WINDOWS = ("hann", "hamming", "blackman", "boxcar")


@dataclass
class SpectrogramParams:
    """User-tunable spectrogram parameters (live-editable in the UI)."""

    n_fft: int = 1024
    hop: int = 256  # samples between successive STFT columns
    window: str = "hann"
    db_floor: float = -100.0
    db_ceil: float = 0.0
    f_max: float | None = None  # None -> Nyquist (sample_rate / 2)

    def to_meta(self, f_max: float) -> SpectrogramMeta:
        return SpectrogramMeta(
            n_fft=self.n_fft, hop=self.hop, window=self.window, f_max=f_max
        )


@dataclass
class SpectrogramResult:
    """Output of :func:`compute`.

    ``image`` is a 2-D array of shape ``(n_rows, n_cols)`` in dB, with row 0 =
    lowest frequency (matches the pixel convention in ``models.py``).
    ``times``/``freqs`` are the bin centers. ``duration``/``f_max`` give the
    physical extent used to map the image onto (t, f) data coordinates.
    """

    image: np.ndarray
    times: np.ndarray
    freqs: np.ndarray
    duration: float
    f_max: float


def compute(
    samples: np.ndarray,
    sample_rate: int,
    params: SpectrogramParams,
) -> SpectrogramResult:
    """Compute a dB-scaled spectrogram via STFT.

    Returns a :class:`SpectrogramResult` whose ``image`` has shape
    ``(n_rows, n_cols)`` in dB with row 0 = lowest frequency.
    """
    samples = np.asarray(samples, dtype=np.float64).reshape(-1)

    n_fft = int(params.n_fft)
    # Clamp hop into [1, n_fft] so noverlap stays in scipy's valid range.
    hop = int(np.clip(params.hop, 1, n_fft))
    noverlap = n_fft - hop

    window = get_window(params.window, n_fft)

    freqs, times, Zxx = stft(
        samples,
        fs=sample_rate,
        window=window,
        nperseg=n_fft,
        noverlap=noverlap,
        boundary=None,
        padded=False,
    )

    # Magnitude -> dB. eps guards log10(0); freqs are already ascending (row 0
    # = lowest frequency), which matches the pixel convention, so do NOT flip.
    eps = np.finfo(np.float64).eps
    image = 20.0 * np.log10(np.abs(Zxx) + eps)
    image = np.clip(image, params.db_floor, params.db_ceil)

    nyquist = sample_rate / 2.0
    if params.f_max is not None and params.f_max < nyquist:
        keep = freqs <= params.f_max
        freqs = freqs[keep]
        image = image[keep, :]
        f_max = float(freqs[-1]) if freqs.size else float(params.f_max)
    else:
        f_max = float(freqs[-1]) if freqs.size else nyquist

    duration = len(samples) / sample_rate if sample_rate else 0.0

    return SpectrogramResult(
        image=image,
        times=times,
        freqs=freqs,
        duration=duration,
        f_max=f_max,
    )
