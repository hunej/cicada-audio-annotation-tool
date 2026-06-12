"""Folder library model — group paired audio variants into recordings.

A *recording* is one logical capture (e.g. ``babble_15dB``) that may exist in
several processing *variants*, each living in its own immediate subfolder of the
opened parent folder::

    example/
      mic/  babble_15dB.wav      -> variant "mic"
      out/  babble_15dB.wav      -> variant "out"

Same-stem files across variant subfolders are grouped into one
:class:`Recording`. Each variant keeps its OWN annotation sidecar next to its
own ``.wav`` (see ``io_json.sidecar_path``), so variants are annotated
independently while the spectrogram view can stay locked across them.

If the opened folder contains no variant subfolders (just loose ``.wav`` files,
possibly nested), it falls back to a flat library: each file is its own
single-variant recording under the variant name :data:`FLAT_VARIANT`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

WAV_EXTS = (".wav",)
FLAT_VARIANT = ""  # variant name used in the flat (no-subfolder) fallback


def _is_wav(name: str) -> bool:
    return name.lower().endswith(WAV_EXTS)


def _stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


@dataclass
class Recording:
    """One logical recording and its available variants."""

    key: str  # basename without extension, e.g. "babble_15dB"
    variants: dict[str, str] = field(default_factory=dict)  # variant -> wav path

    def path_for(self, variant: str) -> str | None:
        return self.variants.get(variant)

    def available(self) -> list[str]:
        return list(self.variants.keys())


@dataclass
class Library:
    """A scanned parent folder: ordered variants + recordings."""

    root: str
    variants: list[str] = field(default_factory=list)  # all variant names, ordered
    recordings: list[Recording] = field(default_factory=list)  # ordered by key

    @property
    def is_flat(self) -> bool:
        return self.variants == [FLAT_VARIANT]


def _scan_variant_subfolders(root: str) -> dict[str, dict[str, str]]:
    """Return ``{variant_name: {stem: wav_path}}`` for immediate subfolders."""
    out: dict[str, dict[str, str]] = {}
    for entry in sorted(os.listdir(root)):
        sub = os.path.join(root, entry)
        if not os.path.isdir(sub):
            continue
        wavs = {
            _stem(f): os.path.join(sub, f)
            for f in sorted(os.listdir(sub))
            if _is_wav(f) and os.path.isfile(os.path.join(sub, f))
        }
        if wavs:
            out[entry] = wavs
    return out


def _scan_flat(root: str) -> list[Recording]:
    """Fallback: every ``.wav`` under ``root`` is its own recording."""
    recs: list[Recording] = []
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if _is_wav(name):
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, root)
                recs.append(Recording(key=rel, variants={FLAT_VARIANT: path}))
    recs.sort(key=lambda r: r.key)
    return recs


def scan_library(root: str) -> Library:
    """Scan ``root`` into a :class:`Library`.

    Prefers the variant-subfolder model; falls back to a flat scan when no
    immediate subfolder contains ``.wav`` files.
    """
    by_variant = _scan_variant_subfolders(root)

    if not by_variant:
        recs = _scan_flat(root)
        return Library(root=root, variants=[FLAT_VARIANT] if recs else [], recordings=recs)

    variants = sorted(by_variant.keys())
    # Union of stems across variants, ordered.
    keys: list[str] = sorted({stem for wavs in by_variant.values() for stem in wavs})
    recordings = [
        Recording(
            key=key,
            variants={v: by_variant[v][key] for v in variants if key in by_variant[v]},
        )
        for key in keys
    ]
    return Library(root=root, variants=variants, recordings=recordings)
