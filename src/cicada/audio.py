"""Audio loading and playback — contract + implementation entry points.

WP1 implements these. Loading uses ``soundfile`` (libsndfile); playback uses
``sounddevice`` (PortAudio). Multi-channel audio is reduced to mono for the
spectrogram (channel 0, see ``mono=True``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import soundfile as sf

from .models import AudioMeta


def describe(path: str) -> dict:
    """Read just the header of ``path`` and return basic audio info.

    Cheap (no sample data is decoded) — used for the file-list "Audio info"
    popup. Keys: ``samplerate``, ``channels``, ``frames``, ``duration`` (s),
    ``format`` (``"WAV/PCM_16"``-style).
    """
    inf = sf.info(path)
    return {
        "samplerate": int(inf.samplerate),
        "channels": int(inf.channels),
        "frames": int(inf.frames),
        "duration": float(inf.duration),
        "format": f"{inf.format}/{inf.subtype}",
    }


def _import_sounddevice():
    """Lazily import sounddevice, raising a clear error if unavailable.

    sounddevice depends on PortAudio, which may be missing on headless or
    server systems. Importing it lazily keeps ``import cicada.audio`` safe.
    """
    try:
        import sounddevice as sd
    except Exception as exc:  # OSError, ImportError, ...
        raise RuntimeError(
            "Audio playback is unavailable: could not import 'sounddevice' "
            f"(is PortAudio installed?). Original error: {exc}"
        ) from exc
    return sd


@dataclass
class AudioData:
    """Loaded audio: mono float samples plus metadata."""

    samples: np.ndarray  # 1-D float32/float64, mono
    sample_rate: int
    meta: AudioMeta


def load(path: str, mono: bool = True) -> AudioData:
    """Load a wav (or any libsndfile-supported) file as float32 samples."""
    data, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    n_frames, n_channels = data.shape
    meta = AudioMeta(
        sample_rate=int(sample_rate),
        duration=n_frames / sample_rate if sample_rate else 0.0,
        n_channels=int(n_channels),
    )
    if mono and n_channels > 1:
        samples = data[:, 0]
    else:
        samples = data[:, 0] if n_channels == 1 else data
    samples = np.ascontiguousarray(samples)
    return AudioData(samples=samples, sample_rate=int(sample_rate), meta=meta)


def play(audio: AudioData, t_start: float | None = None, t_end: float | None = None) -> None:
    """Play the whole file, or the ``[t_start, t_end]`` slice (seconds).

    Playback is non-blocking. Any prior playback is stopped first.
    """
    sd = _import_sounddevice()
    sr = audio.sample_rate
    samples = audio.samples

    i0 = 0 if t_start is None else max(0, int(round(t_start * sr)))
    i1 = len(samples) if t_end is None else min(len(samples), int(round(t_end * sr)))
    clip = samples[i0:i1]

    sd.stop()
    sd.play(clip, sr)


def stop() -> None:
    """Stop any current playback."""
    sd = _import_sounddevice()
    sd.stop()
