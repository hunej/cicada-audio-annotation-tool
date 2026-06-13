"""JSON sidecar persistence — contract + implementation entry points.

Each audio file ``foo.wav`` gets a sibling ``foo.json`` (labelme-style). WP2
implements load/save plus dataclass<->dict conversion against the schema in
``models.py``.

``t_start``/``t_end`` are stored **in samples** (integer sample index) for
sample-accurate boundaries; they are converted to/from the in-memory seconds
representation at the I/O boundary using ``audio_meta.sample_rate``. ``f_low``/
``f_high`` remain in Hz.

The on-disk schema (one ``<audio>.json`` per audio file)::

    {
      "version": "1.0",
      "audio_file": "foo.wav",
      "audio_meta": {"sample_rate": 44100, "duration": 12.5, "n_channels": 1},
      "spectrogram": {"n_fft": 1024, "hop": 256, "window": "hann", "f_max": 22050.0},
      "boxes": [
        {"label": "call", "t_start": 44100, "t_end": 88200,
         "f_low": 100.0, "f_high": 200.0,
         "px": {"x": 10.0, "y": 20.0, "w": 30.0, "h": 40.0}},
        {"label": "noise", "t_start": 132300, "t_end": 176400,
         "f_low": 50.0, "f_high": 75.0, "px": null}
      ]
    }
"""

from __future__ import annotations

import json
import os

from .models import (
    SCHEMA_VERSION,
    Annotation,
    AudioMeta,
    Box,
    PixelBox,
    SpectrogramMeta,
)


def sidecar_path(audio_path: str) -> str:
    """Return the ``.json`` sidecar path for an audio file path."""
    base, _ = os.path.splitext(audio_path)
    return base + ".json"


def has_annotation(audio_path: str) -> bool:
    """True if a sidecar JSON already exists for this audio file."""
    return os.path.exists(sidecar_path(audio_path))


# --------------------------------------------------------------------------
# dataclass <-> dict
# --------------------------------------------------------------------------

def _sec_to_samples(t: float, sample_rate: int) -> int:
    """Seconds -> integer sample index (0 if the sample rate is unknown)."""
    return int(round(t * sample_rate)) if sample_rate > 0 else 0


def _samples_to_sec(s: float, sample_rate: int) -> float:
    """Sample index -> seconds (0.0 if the sample rate is unknown)."""
    return s / sample_rate if sample_rate > 0 else 0.0


def _box_to_dict(box: Box, sample_rate: int) -> dict:
    """Serialize one :class:`Box`; ``t_start``/``t_end`` go out as samples."""
    px = None
    if box.px is not None:
        px = {"x": box.px.x, "y": box.px.y, "w": box.px.w, "h": box.px.h}
    return {
        "label": box.label,
        "t_start": _sec_to_samples(box.t_start, sample_rate),
        "t_end": _sec_to_samples(box.t_end, sample_rate),
        "f_low": box.f_low,
        "f_high": box.f_high,
        "px": px,
    }


def _box_from_dict(d: dict, sample_rate: int) -> Box:
    """Reconstruct one :class:`Box`; ``t_start``/``t_end`` come in as samples."""
    px_d = d.get("px")
    px = None
    if px_d is not None:
        px = PixelBox(
            x=px_d["x"],
            y=px_d["y"],
            w=px_d["w"],
            h=px_d["h"],
        )
    return Box(
        label=d["label"],
        t_start=_samples_to_sec(d["t_start"], sample_rate),
        t_end=_samples_to_sec(d["t_end"], sample_rate),
        f_low=d["f_low"],
        f_high=d["f_high"],
        px=px,
    )


def to_dict(annotation: Annotation) -> dict:
    """Convert an :class:`Annotation` to a JSON-serializable dict."""
    am = annotation.audio_meta
    sp = annotation.spectrogram
    return {
        "version": annotation.version,
        "audio_file": annotation.audio_file,
        "audio_meta": {
            "sample_rate": am.sample_rate,
            "duration": am.duration,
            "n_channels": am.n_channels,
        },
        "spectrogram": {
            "n_fft": sp.n_fft,
            "hop": sp.hop,
            "window": sp.window,
            "f_max": sp.f_max,
        },
        "boxes": [_box_to_dict(b, am.sample_rate) for b in annotation.boxes],
    }


def from_dict(d: dict) -> Annotation:
    """Reconstruct an :class:`Annotation` from a dict.

    Tolerant of unknown extra keys; a missing ``version`` defaults to
    :data:`SCHEMA_VERSION` and a missing/null box ``px`` becomes ``None``.
    """
    am_d = d["audio_meta"]
    sp_d = d["spectrogram"]
    sample_rate = am_d["sample_rate"]
    return Annotation(
        audio_file=d["audio_file"],
        audio_meta=AudioMeta(
            sample_rate=sample_rate,
            duration=am_d["duration"],
            n_channels=am_d["n_channels"],
        ),
        spectrogram=SpectrogramMeta(
            n_fft=sp_d["n_fft"],
            hop=sp_d["hop"],
            window=sp_d["window"],
            f_max=sp_d["f_max"],
        ),
        boxes=[_box_from_dict(b, sample_rate) for b in d.get("boxes", [])],
        version=d.get("version", SCHEMA_VERSION),
    )


# --------------------------------------------------------------------------
# load / save
# --------------------------------------------------------------------------

def save(annotation: Annotation, audio_path: str) -> str:
    """Write the annotation sidecar next to ``audio_path``.

    Returns the path that was written.
    """
    path = sidecar_path(audio_path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(to_dict(annotation), f, indent=2)
    return path


def load(audio_path: str) -> Annotation:
    """Load the annotation sidecar for ``audio_path``.

    Raises :class:`FileNotFoundError` if the sidecar does not exist.
    """
    path = sidecar_path(audio_path)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8") as f:
        return from_dict(json.load(f))
