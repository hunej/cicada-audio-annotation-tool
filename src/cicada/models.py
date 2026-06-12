"""Core data model — the shared contract used across the whole app.

A :class:`Box` is one annotated rectangle on the spectrogram. Its primary,
authoritative coordinates are physical: ``t_start``/``t_end`` in seconds and
``f_low``/``f_high`` in Hz. Pixel coordinates (:class:`PixelBox`) are stored
*in addition* for reproducibility/visualization but are derived from the
physical coordinates plus the spectrogram image shape, so they can always be
recomputed (see :func:`tf_to_px` / :func:`px_to_tf`).

The pixel coordinate convention matches the spectrogram image as displayed:
``x`` increases with time (column index), ``y`` increases with frequency
(row index, i.e. row 0 = lowest frequency). ``w``/``h`` are width/height in
pixels. This is independent of any GUI framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

SCHEMA_VERSION = "1.0"


@dataclass
class PixelBox:
    """Axis-aligned rectangle in spectrogram-image pixel space."""

    x: float
    y: float
    w: float
    h: float


@dataclass
class Box:
    """One annotated region on the spectrogram.

    Physical coordinates are authoritative. ``px`` is optional and derived.
    """

    label: str
    t_start: float
    t_end: float
    f_low: float
    f_high: float
    px: Optional[PixelBox] = None

    def normalized(self) -> "Box":
        """Return a copy with ``t_start <= t_end`` and ``f_low <= f_high``."""
        t0, t1 = sorted((self.t_start, self.t_end))
        f0, f1 = sorted((self.f_low, self.f_high))
        return Box(self.label, t0, t1, f0, f1, self.px)


@dataclass
class AudioMeta:
    """Metadata about the source audio file."""

    sample_rate: int
    duration: float
    n_channels: int


@dataclass
class SpectrogramMeta:
    """Parameters that produced the spectrogram the boxes were drawn on.

    Mirrors the runtime ``SpectrogramParams`` (see ``spectrogram.py``) but as a
    plain serializable record. ``f_max`` is the highest frequency displayed
    (typically ``sample_rate / 2``).
    """

    n_fft: int
    hop: int
    window: str
    f_max: float


@dataclass
class Annotation:
    """Everything stored in one ``<audio>.json`` sidecar file."""

    audio_file: str
    audio_meta: AudioMeta
    spectrogram: SpectrogramMeta
    boxes: list[Box] = field(default_factory=list)
    version: str = SCHEMA_VERSION


# --------------------------------------------------------------------------
# t/f <-> pixel conversions
#
# The spectrogram image has ``n_cols`` time bins spanning [0, duration] seconds
# and ``n_rows`` frequency bins spanning [0, f_max] Hz, with row 0 = lowest
# frequency. These are pure, GUI-independent helpers.
# --------------------------------------------------------------------------

def tf_to_px(
    t_start: float,
    t_end: float,
    f_low: float,
    f_high: float,
    duration: float,
    f_max: float,
    n_cols: int,
    n_rows: int,
) -> PixelBox:
    """Convert a time/frequency rectangle to a pixel rectangle."""
    if duration <= 0 or f_max <= 0:
        raise ValueError("duration and f_max must be positive")
    sx = n_cols / duration
    sy = n_rows / f_max
    x0 = t_start * sx
    x1 = t_end * sx
    y0 = f_low * sy
    y1 = f_high * sy
    return PixelBox(x=min(x0, x1), y=min(y0, y1), w=abs(x1 - x0), h=abs(y1 - y0))


def px_to_tf(
    px: PixelBox,
    duration: float,
    f_max: float,
    n_cols: int,
    n_rows: int,
) -> tuple[float, float, float, float]:
    """Convert a pixel rectangle back to ``(t_start, t_end, f_low, f_high)``."""
    if n_cols <= 0 or n_rows <= 0:
        raise ValueError("n_cols and n_rows must be positive")
    sx = duration / n_cols
    sy = f_max / n_rows
    t_start = px.x * sx
    t_end = (px.x + px.w) * sx
    f_low = px.y * sy
    f_high = (px.y + px.h) * sy
    return t_start, t_end, f_low, f_high
