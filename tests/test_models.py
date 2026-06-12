"""Tests for the pure t/f<->pixel helpers and Box.normalized in models.py."""

from __future__ import annotations

import pytest

from cicada.models import Box, PixelBox, px_to_tf, tf_to_px


def test_tf_px_round_trip():
    duration, f_max, n_cols, n_rows = 10.0, 20000.0, 500, 256
    t_start, t_end, f_low, f_high = 2.0, 7.5, 1000.0, 8000.0

    px = tf_to_px(t_start, t_end, f_low, f_high, duration, f_max, n_cols, n_rows)
    rt = px_to_tf(px, duration, f_max, n_cols, n_rows)

    assert rt == pytest.approx((t_start, t_end, f_low, f_high), abs=1e-9)


def test_tf_to_px_values():
    # 100 cols over 10s -> 10 px/s; 200 rows over 1000Hz -> 0.2 px/Hz
    px = tf_to_px(1.0, 3.0, 100.0, 500.0, 10.0, 1000.0, 100, 200)
    assert px == PixelBox(x=10.0, y=20.0, w=20.0, h=80.0)


def test_normalized_sorts_reversed_coords():
    box = Box(label="x", t_start=2.0, t_end=1.0, f_low=300.0, f_high=100.0)
    norm = box.normalized()
    assert (norm.t_start, norm.t_end) == (1.0, 2.0)
    assert (norm.f_low, norm.f_high) == (100.0, 300.0)
    assert norm.label == "x"


def test_normalized_preserves_already_sorted():
    px = PixelBox(x=1.0, y=2.0, w=3.0, h=4.0)
    box = Box(label="y", t_start=1.0, t_end=2.0, f_low=10.0, f_high=20.0, px=px)
    norm = box.normalized()
    assert norm == box


def test_tf_to_px_raises_on_nonpositive_duration():
    with pytest.raises(ValueError):
        tf_to_px(0.0, 1.0, 0.0, 1.0, duration=0.0, f_max=1000.0, n_cols=10, n_rows=10)
    with pytest.raises(ValueError):
        tf_to_px(0.0, 1.0, 0.0, 1.0, duration=-5.0, f_max=1000.0, n_cols=10, n_rows=10)


def test_tf_to_px_raises_on_nonpositive_fmax():
    with pytest.raises(ValueError):
        tf_to_px(0.0, 1.0, 0.0, 1.0, duration=10.0, f_max=0.0, n_cols=10, n_rows=10)
