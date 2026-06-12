"""Predefined label management (labelme-style labels file).

A small set of named labels each carry a hex color used by the GUI. Labels are
read from / written to a JSON file shaped like::

    {"labels": [{"name": "call", "color": "#e6194b"}, ...]}

If no file exists yet, :func:`load_labels` returns a copy of
:data:`DEFAULT_LABELS`. :func:`color_for` always yields *some* color, falling
back to a deterministic palette pick for unknown names.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace


@dataclass
class LabelDef:
    """A predefined annotation label and its display color."""

    name: str
    color: str  # hex, e.g. "#ff0000"


DEFAULT_LABELS: list[LabelDef] = [
    LabelDef("call", "#e6194b"),
    LabelDef("chorus", "#3cb44b"),
    LabelDef("noise", "#4363d8"),
    LabelDef("unknown", "#f58231"),
]

# Deterministic fallback palette for unknown label names.
_FALLBACK_PALETTE: list[str] = [
    "#e6194b",
    "#3cb44b",
    "#4363d8",
    "#f58231",
    "#911eb4",
    "#46f0f0",
    "#f032e6",
    "#bcf60c",
    "#fabebe",
    "#008080",
    "#9a6324",
    "#808000",
]


def load_labels(path: str) -> list[LabelDef]:
    """Load labels from ``path``; return a copy of defaults if it is absent."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return [replace(label) for label in DEFAULT_LABELS]
    return [
        LabelDef(name=item["name"], color=item["color"])
        for item in data.get("labels", [])
    ]


def save_labels(labels: list[LabelDef], path: str) -> None:
    """Write ``labels`` to ``path`` as pretty JSON."""
    data = {"labels": [{"name": lbl.name, "color": lbl.color} for lbl in labels]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def color_for(labels: list[LabelDef], name: str) -> str:
    """Return the color for ``name``.

    Falls back to a deterministic palette pick (hash of ``name``) for labels
    not present in ``labels`` so the GUI always has a color to draw with.
    """
    for label in labels:
        if label.name == name:
            return label.color
    # Stable across processes (unlike the salted builtin ``hash``).
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()
    idx = int(digest, 16) % len(_FALLBACK_PALETTE)
    return _FALLBACK_PALETTE[idx]
