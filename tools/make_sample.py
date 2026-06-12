#!/usr/bin/env python
"""Synthesize sample WAVs with KNOWN content for manual verification.

Usage::

    python tools/make_sample.py [outdir]   # default ./sample_data

Each file's ground-truth (time, frequency) events are printed so a human can
check that annotation box coordinates land where expected.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import soundfile as sf

SAMPLE_RATE = 22050
DURATION = 3.0
AMPLITUDE = 0.6
SEED = 1234


def _t(sample_rate: int = SAMPLE_RATE, duration: float = DURATION) -> np.ndarray:
    """Time vector for one clip."""
    n = int(round(duration * sample_rate))
    return np.arange(n, dtype=np.float64) / sample_rate


def _to_int16(sig: np.ndarray) -> np.ndarray:
    """Clip to [-1, 1] and convert to 16-bit PCM range."""
    sig = np.clip(sig, -1.0, 1.0)
    return (sig * 32767.0).astype(np.int16)


def make_chirp() -> tuple[np.ndarray, list[str]]:
    """Linear chirp sweeping f0 -> f1 over the whole clip."""
    f0, f1 = 500.0, 8000.0
    t = _t()
    k = (f1 - f0) / DURATION  # Hz per second
    phase = 2.0 * np.pi * (f0 * t + 0.5 * k * t * t)
    sig = AMPLITUDE * np.sin(phase)
    notes = [
        f"linear chirp: {f0:.0f} Hz at t=0.0s -> {f1:.0f} Hz at t={DURATION:.1f}s",
        f"  (at t=1.5s the instantaneous freq is ~{f0 + k * 1.5:.0f} Hz)",
    ]
    return _to_int16(sig), notes


def make_tone_bursts() -> tuple[np.ndarray, list[str]]:
    """Two tone bursts at known (t, f) locations, plus low-level noise."""
    rng = np.random.default_rng(SEED)
    t = _t()
    sig = np.zeros_like(t)

    bursts = [
        (2000.0, 0.5, 1.0),  # 2 kHz, 0.5-1.0 s
        (5000.0, 1.8, 2.3),  # 5 kHz, 1.8-2.3 s
    ]
    notes = []
    for freq, ts, te in bursts:
        mask = (t >= ts) & (t < te)
        sig[mask] += AMPLITUDE * np.sin(2.0 * np.pi * freq * t[mask])
        notes.append(f"tone burst: {freq:.0f} Hz from t={ts:.1f}s to t={te:.1f}s")

    sig += 0.01 * rng.standard_normal(t.shape)  # faint, seeded background noise
    return _to_int16(sig), notes


def make_dual_chirp() -> tuple[np.ndarray, list[str]]:
    """Two simultaneous linear chirps that cross at a known time."""
    t = _t()
    a0, a1 = 1000.0, 6000.0  # rising
    b0, b1 = 6000.0, 1000.0  # falling
    ka = (a1 - a0) / DURATION
    kb = (b1 - b0) / DURATION
    up = np.sin(2.0 * np.pi * (a0 * t + 0.5 * ka * t * t))
    down = np.sin(2.0 * np.pi * (b0 * t + 0.5 * kb * t * t))
    sig = 0.5 * AMPLITUDE * (up + down)
    cross_t = DURATION / 2.0
    cross_f = a0 + ka * cross_t
    notes = [
        f"rising chirp: {a0:.0f} Hz -> {a1:.0f} Hz over {DURATION:.1f}s",
        f"falling chirp: {b0:.0f} Hz -> {b1:.0f} Hz over {DURATION:.1f}s",
        f"  they cross at t={cross_t:.2f}s, f~{cross_f:.0f} Hz",
    ]
    return _to_int16(sig), notes


GENERATORS = {
    "chirp.wav": make_chirp,
    "tone_bursts.wav": make_tone_bursts,
    "dual_chirp.wav": make_dual_chirp,
}


def main(argv: list[str]) -> int:
    outdir = argv[1] if len(argv) > 1 else "./sample_data"
    os.makedirs(outdir, exist_ok=True)

    print(f"Writing sample WAVs to: {os.path.abspath(outdir)}")
    print(f"sample_rate={SAMPLE_RATE} Hz, duration={DURATION:.1f}s, mono, 16-bit PCM\n")

    for name, gen in GENERATORS.items():
        sig, notes = gen()
        path = os.path.join(outdir, name)
        sf.write(path, sig, SAMPLE_RATE, subtype="PCM_16")
        print(f"{name}:")
        for line in notes:
            print(f"  {line}")
        print()

    print("Ground-truth events above; verify box (t, f) coordinates against them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
