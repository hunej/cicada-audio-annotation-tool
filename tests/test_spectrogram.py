"""Tests for cicada.spectrogram.compute (numpy/scipy only; no GUI, no audio)."""

from __future__ import annotations

import numpy as np
import pytest

from cicada.models import PixelBox, px_to_tf, tf_to_px
from cicada.spectrogram import SpectrogramParams, compute

SAMPLE_RATE = 16000
DURATION = 1.0


def _tone(freq: float, sample_rate: int = SAMPLE_RATE, duration: float = DURATION) -> np.ndarray:
    t = np.arange(int(duration * sample_rate)) / sample_rate
    return np.sin(2.0 * np.pi * freq * t).astype(np.float64)


def test_shape_orientation_and_peak_frequency():
    freq = 2000.0
    samples = _tone(freq)
    params = SpectrogramParams(n_fft=1024, hop=256)
    res = compute(samples, SAMPLE_RATE, params)

    # image shape == (len(freqs), len(times)).
    assert res.image.shape == (len(res.freqs), len(res.times))

    # row 0 = lowest frequency (ascending order, not flipped).
    assert res.freqs[0] < res.freqs[-1]
    assert res.freqs[0] == pytest.approx(0.0, abs=1e-9)

    # peak-energy row corresponds to the tone frequency within one bin.
    row_energy = res.image.sum(axis=1)
    peak_row = int(np.argmax(row_energy))
    bin_width = res.freqs[1] - res.freqs[0]
    assert abs(res.freqs[peak_row] - freq) <= bin_width


def test_db_clipping_respects_floor_and_ceil():
    samples = _tone(1500.0)
    params = SpectrogramParams(n_fft=512, hop=128, db_floor=-60.0, db_ceil=-10.0)
    res = compute(samples, SAMPLE_RATE, params)

    assert res.image.min() >= -60.0 - 1e-9
    assert res.image.max() <= -10.0 + 1e-9


def test_f_max_cropping_reduces_rows():
    samples = _tone(1000.0)
    full = compute(samples, SAMPLE_RATE, SpectrogramParams(n_fft=1024, hop=256))
    cropped = compute(
        samples, SAMPLE_RATE, SpectrogramParams(n_fft=1024, hop=256, f_max=3000.0)
    )

    assert cropped.image.shape[0] < full.image.shape[0]
    assert cropped.freqs[-1] <= 3000.0
    assert cropped.f_max <= 3000.0
    # full clip's f_max is the Nyquist top bin.
    assert full.f_max == pytest.approx(SAMPLE_RATE / 2.0)


def test_f_max_none_uses_nyquist():
    res = compute(_tone(1000.0), SAMPLE_RATE, SpectrogramParams())
    assert res.f_max == pytest.approx(SAMPLE_RATE / 2.0)
    assert res.duration == pytest.approx(DURATION)


def test_tf_px_roundtrip_for_known_box():
    duration, f_max = 3.0, 8000.0
    n_cols, n_rows = 300, 400
    t_start, t_end, f_low, f_high = 0.5, 1.0, 2000.0, 5000.0

    px = tf_to_px(t_start, t_end, f_low, f_high, duration, f_max, n_cols, n_rows)
    assert isinstance(px, PixelBox)

    back = px_to_tf(px, duration, f_max, n_cols, n_rows)
    assert back == pytest.approx((t_start, t_end, f_low, f_high))
