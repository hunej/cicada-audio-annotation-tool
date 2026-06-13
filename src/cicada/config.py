"""Application configuration — persisted user preferences.

A small :class:`AppConfig` dataclass holds the last-opened folder, the default
spectrogram parameters, the colormap and the labels-file path. It is persisted
as JSON to ``~/.cicada/config.json``. Loading tolerates a missing/corrupt file
by falling back to defaults, so the app always starts cleanly.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from .spectrogram import SpectrogramParams

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".cicada")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
DEFAULT_LABELS_FILE = os.path.join(CONFIG_DIR, "labels.json")


@dataclass
class AppConfig:
    """Persisted user preferences for the annotation app."""

    last_folder: str | None = None
    autosave_on_switch: bool = True
    spectrogram: SpectrogramParams = field(default_factory=SpectrogramParams)
    colormap: str = "viridis"
    labels_file: str = DEFAULT_LABELS_FILE
    # Per-folder variant whitelist: {folder_path: [variant names to show]}.
    # Absent folder -> show all variants.
    variant_filters: dict[str, list[str]] = field(default_factory=dict)


def _config_from_dict(d: dict) -> AppConfig:
    """Build an :class:`AppConfig` from a (possibly partial) dict."""
    sp_d = d.get("spectrogram", {}) or {}
    params = SpectrogramParams(
        n_fft=int(sp_d.get("n_fft", 1024)),
        hop=int(sp_d.get("hop", 256)),
        window=str(sp_d.get("window", "hann")),
        db_floor=float(sp_d.get("db_floor", -100.0)),
        db_ceil=float(sp_d.get("db_ceil", 0.0)),
        f_max=sp_d.get("f_max", None),
    )
    raw_filters = d.get("variant_filters", {}) or {}
    variant_filters = {
        str(k): [str(v) for v in (vals or [])] for k, vals in raw_filters.items()
    }
    return AppConfig(
        last_folder=d.get("last_folder"),
        autosave_on_switch=bool(d.get("autosave_on_switch", True)),
        spectrogram=params,
        colormap=str(d.get("colormap", "viridis")),
        labels_file=str(d.get("labels_file", DEFAULT_LABELS_FILE)),
        variant_filters=variant_filters,
    )


def load_config() -> AppConfig:
    """Load config from ``~/.cicada/config.json``; defaults if absent/invalid."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return AppConfig()
    try:
        return _config_from_dict(data)
    except (KeyError, TypeError, ValueError):
        return AppConfig()


def save_config(cfg: AppConfig) -> str:
    """Persist ``cfg`` to ``~/.cicada/config.json``; returns the path written."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2)
    return CONFIG_PATH
