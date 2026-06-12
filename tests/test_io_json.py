"""Tests for JSON sidecar persistence (save/load round-trip + schema)."""

from __future__ import annotations

import json
import os

from cicada import io_json
from cicada.io_json import has_annotation, load, save, sidecar_path
from cicada.models import (
    Annotation,
    AudioMeta,
    Box,
    PixelBox,
    SpectrogramMeta,
)


def _make_annotation() -> Annotation:
    return Annotation(
        audio_file="foo.wav",
        audio_meta=AudioMeta(sample_rate=44100, duration=12.5, n_channels=2),
        spectrogram=SpectrogramMeta(n_fft=1024, hop=256, window="hann", f_max=22050.0),
        boxes=[
            Box(
                label="call",
                t_start=1.0,
                t_end=2.0,
                f_low=100.0,
                f_high=200.0,
                px=PixelBox(x=10.0, y=20.0, w=30.0, h=40.0),
            ),
            Box(
                label="noise",
                t_start=3.0,
                t_end=4.0,
                f_low=50.0,
                f_high=75.0,
                px=None,
            ),
        ],
    )


def test_save_load_round_trip(tmp_path):
    ann = _make_annotation()
    audio_path = str(tmp_path / "foo.wav")

    written = save(ann, audio_path)
    assert written == sidecar_path(audio_path)
    assert os.path.exists(written)

    loaded = load(audio_path)
    assert loaded == ann  # dataclass deep equality across all nested fields


def test_on_disk_schema_keys(tmp_path):
    ann = _make_annotation()
    audio_path = str(tmp_path / "foo.wav")
    written = save(ann, audio_path)

    with open(written, encoding="utf-8") as f:
        data = json.load(f)

    assert set(data.keys()) == {
        "version",
        "audio_file",
        "audio_meta",
        "spectrogram",
        "boxes",
    }
    assert set(data["audio_meta"].keys()) == {"sample_rate", "duration", "n_channels"}
    assert set(data["spectrogram"].keys()) == {"n_fft", "hop", "window", "f_max"}

    for box in data["boxes"]:
        assert set(box.keys()) == {
            "label",
            "t_start",
            "t_end",
            "f_low",
            "f_high",
            "px",
        }

    box_with_px, box_without_px = data["boxes"]
    assert set(box_with_px["px"].keys()) == {"x", "y", "w", "h"}
    assert box_without_px["px"] is None


def test_to_from_dict_round_trip():
    ann = _make_annotation()
    assert io_json.from_dict(io_json.to_dict(ann)) == ann


def test_load_missing_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        load(str(tmp_path / "absent.wav"))


def test_load_tolerant_of_missing_version_and_extra_keys(tmp_path):
    from cicada.models import SCHEMA_VERSION

    audio_path = str(tmp_path / "bar.wav")
    payload = {
        # no "version" key
        "audio_file": "bar.wav",
        "audio_meta": {"sample_rate": 8000, "duration": 1.0, "n_channels": 1},
        "spectrogram": {"n_fft": 256, "hop": 64, "window": "hann", "f_max": 4000.0},
        "boxes": [
            {
                "label": "x",
                "t_start": 0.0,
                "t_end": 0.5,
                "f_low": 0.0,
                "f_high": 100.0,
                # no "px" key at all
                "unknown_extra": 123,
            }
        ],
        "junk_top_level": "ignored",
    }
    with open(sidecar_path(audio_path), "w", encoding="utf-8") as f:
        json.dump(payload, f)

    loaded = load(audio_path)
    assert loaded.version == SCHEMA_VERSION
    assert loaded.boxes[0].px is None


def test_sidecar_path_and_has_annotation(tmp_path):
    audio_path = str(tmp_path / "foo.wav")
    assert sidecar_path(audio_path) == str(tmp_path / "foo.json")

    assert not has_annotation(audio_path)
    save(_make_annotation(), audio_path)
    assert has_annotation(audio_path)
