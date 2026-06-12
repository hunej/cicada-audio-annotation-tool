"""Main application window — wires the WP1-3 layers into a usable GUI.

:class:`MainWindow` lays out a playback toolbar (top, ocenaudio-style), the file
list + mode/label panels (left, stacked) and the interactive spectrogram
(center), and connects every panel signal to the audio / spectrogram /
annotation back-end. The less-frequently-touched spectrogram parameters live in
the *View → Settings…* dialog. :func:`main` is the ``cicada`` console-script
entry point.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QMainWindow,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from . import audio, io_json, label_config, spectrogram
from .config import AppConfig, load_config, save_config
from .models import Annotation
from .widgets.controls import SettingsPanel
from .widgets.file_list import FileListPanel
from .widgets.label_panel import LabelPanel
from .widgets.spectrogram_view import SpectrogramView

WINDOW_TITLE = "Cicada — Spectrogram Annotation"


class MainWindow(QMainWindow):
    """Top-level window tying the panels and back-end together."""

    def __init__(self, config: Optional[AppConfig] = None) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1280, 800)

        self._config = config if config is not None else AppConfig()

        # Per-file runtime state.
        self._current_path: Optional[str] = None
        self._current_audio: Optional[audio.AudioData] = None
        self._current_result: Optional[spectrogram.SpectrogramResult] = None
        self._dirty: bool = False

        # Last view range, re-applied when switching variant of a recording.
        self._saved_range: Optional[tuple[float, float, float, float]] = None

        # Playback / playhead state.
        self._cursor: float = 0.0          # play position (seconds)
        self._playing: bool = False
        self._play_pos0: float = 0.0       # cursor when playback started
        self._play_t0: float = 0.0         # monotonic clock when playback started
        self._play_end: float = 0.0        # stop position (seconds)
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(30)   # ~33 fps playhead animation
        self._play_timer.timeout.connect(self._advance_playhead)

        self._build_ui()
        self._build_toolbar()
        self._build_menu()
        self._wire()
        self._apply_config()

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        self._file_list = FileListPanel()
        self._view = SpectrogramView()
        self._labels = LabelPanel()

        # Spectrogram params live in the View → Settings… dialog (built lazily).
        self._settings = SettingsPanel()
        self._settings_dialog: Optional[QDialog] = None

        # Mode group (annotate toggle) shown above the labels on the left.
        mode_box = QGroupBox("Mode")
        mode_layout = QVBoxLayout(mode_box)
        self._annotate = QCheckBox("Annotate mode (drag to draw)")
        mode_layout.addWidget(self._annotate)

        # Left column (top→bottom): file list, then mode + labels, splittable.
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addWidget(mode_box)
        bottom_layout.addWidget(self._labels, 1)

        left = QSplitter(Qt.Orientation.Vertical)
        left.addWidget(self._file_list)
        left.addWidget(bottom)
        left.setStretchFactor(0, 3)
        left.setStretchFactor(1, 2)
        left.setSizes([460, 340])

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self._view)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([280, 1000])

        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Open a folder to begin.")

    def _build_toolbar(self) -> None:
        """Top transport bar (ocenaudio-style): playback + save."""
        bar = QToolBar("Playback")
        bar.setMovable(False)
        self.addToolBar(bar)

        play_btn = QAction("▶ Play", self)
        play_btn.triggered.connect(self._on_play)
        bar.addAction(play_btn)

        play_sel_btn = QAction("▶ Selection", self)
        play_sel_btn.triggered.connect(self._on_play_selection)
        bar.addAction(play_sel_btn)

        stop_btn = QAction("■ Stop", self)
        stop_btn.triggered.connect(self._on_stop)
        bar.addAction(stop_btn)

        bar.addSeparator()

        save_btn = QAction("Save", self)
        save_btn.triggered.connect(self._on_save)
        bar.addAction(save_btn)

    def _open_settings(self) -> None:
        """Show the (non-modal) spectrogram settings dialog."""
        if self._settings_dialog is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("Settings")
            layout = QVBoxLayout(dlg)
            layout.addWidget(self._settings)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(dlg.hide)
            layout.addWidget(buttons)
            self._settings_dialog = dlg
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        open_act = QAction("Open Folder…", self)
        open_act.triggered.connect(self._on_open_folder)
        file_menu.addAction(open_act)

        save_act = QAction("Save", self)
        save_act.setShortcut(QKeySequence.StandardKey.Save)  # Ctrl+S
        save_act.triggered.connect(self._on_save)
        file_menu.addAction(save_act)

        file_menu.addSeparator()

        next_act = QAction("Next", self)
        next_act.setShortcuts([QKeySequence("Ctrl+Right"), QKeySequence("]")])
        next_act.triggered.connect(self._file_list.next)
        file_menu.addAction(next_act)

        prev_act = QAction("Previous", self)
        prev_act.setShortcuts([QKeySequence("Ctrl+Left"), QKeySequence("[")])
        prev_act.triggered.connect(self._file_list.prev)
        file_menu.addAction(prev_act)

        view_menu = self.menuBar().addMenu("&View")
        settings_act = QAction("Settings…", self)
        settings_act.triggered.connect(self._open_settings)
        view_menu.addAction(settings_act)

        # Window-level shortcuts (work regardless of focused widget).
        play_act = QAction("Play / Pause", self)
        play_act.setShortcut(QKeySequence(Qt.Key.Key_Space))
        play_act.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        play_act.triggered.connect(self._toggle_play)
        self.addAction(play_act)

        variant_act = QAction("Cycle Variant", self)
        variant_act.setShortcut(QKeySequence("V"))
        variant_act.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        variant_act.triggered.connect(self._file_list.cycle_variant)
        self.addAction(variant_act)

    # ------------------------------------------------------------------ #
    # Signal wiring
    # ------------------------------------------------------------------ #
    def _wire(self) -> None:
        self._file_list.selectionChanged.connect(self._on_file_selected)

        self._settings.paramsChanged.connect(self._on_params_changed)
        self._settings.colormapChanged.connect(self._on_colormap_changed)
        self._annotate.toggled.connect(self._view.set_annotate_mode)

        self._labels.activeLabelChanged.connect(self._on_active_label_changed)
        self._labels.applyToSelected.connect(self._on_apply_to_selected)
        self._labels.labelsChanged.connect(self._on_labels_changed)

        self._view.boxesChanged.connect(self._on_boxes_changed)
        self._view.viewRangeChanged.connect(self._on_view_range_changed)
        self._view.positionClicked.connect(self._on_position_clicked)

    def _apply_config(self) -> None:
        """Apply persisted config to the controls/labels and reopen folder."""
        self._settings.apply_params(self._config.spectrogram, self._config.colormap)
        labels = label_config.load_labels(self._config.labels_file)
        self._labels.set_labels(labels)
        self._view.set_colormap(self._config.colormap)
        if self._config.last_folder and os.path.isdir(self._config.last_folder):
            self._file_list.set_folder(self._config.last_folder)

    # ------------------------------------------------------------------ #
    # File handling
    # ------------------------------------------------------------------ #
    def _on_open_folder(self) -> None:
        start = self._config.last_folder or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "Open Folder", start)
        if not path:
            return
        self._config.last_folder = path
        self._persist_config()
        self._file_list.set_folder(path)

    def _on_file_selected(self, path: str, same_recording: bool = False) -> None:
        """Autosave the previous file (if dirty), then load ``path``.

        ``same_recording`` is True when only the variant changed (e.g. mic→out):
        in that case the spectrogram view and play cursor are preserved so the
        two versions line up at the same time/frequency window.
        """
        if (
            self._config.autosave_on_switch
            and self._dirty
            and self._current_path is not None
            and self._current_audio is not None
        ):
            self._save_annotation(self._current_path, quiet=True)

        self._stop_playback(at_end=False)

        try:
            data = audio.load(path)
        except Exception as exc:  # noqa: BLE001 — surface any load failure
            self.statusBar().showMessage(f"Failed to load {os.path.basename(path)}: {exc}")
            return

        self._current_path = path
        self._current_audio = data
        # Keep the view on a variant switch (same recording); reset for new ones.
        self._compute_and_show(keep_view=same_recording)

        # Reset the play cursor on a new recording; keep it across variants.
        if not same_recording:
            self._cursor = 0.0
        self._cursor = min(self._cursor, data.meta.duration)
        self._view.set_playhead(self._cursor)

        # Load this variant's own annotation boxes, or clear.
        if io_json.has_annotation(path):
            try:
                ann = io_json.load(path)
                self._view.set_boxes(ann.boxes, self._labels.color_for)
            except Exception as exc:  # noqa: BLE001
                self.statusBar().showMessage(f"Failed to read annotation: {exc}")
                self._view.clear_boxes()
        else:
            self._view.clear_boxes()

        self._dirty = False
        variant = self._file_list.current_variant()
        tag = f"{os.path.basename(path)}" + (f"  [{variant}]" if variant else "")
        self.setWindowTitle(f"{WINDOW_TITLE} — {tag}")
        self.statusBar().showMessage(tag)

    def _compute_and_show(self, keep_view: bool) -> None:
        """Compute the spectrogram for the current audio and display it.

        Boxes are *not* touched: they live in (t, f) coordinates and survive a
        re-render. ``keep_view`` re-applies the saved range (variant switch,
        view-lock, or live param edit); otherwise the view auto-ranges fresh.
        """
        if self._current_audio is None:
            return
        params = self._settings.current_params()
        result = spectrogram.compute(
            self._current_audio.samples, self._current_audio.sample_rate, params
        )
        self._current_result = result
        self._view.set_spectrogram(result)
        self._view.set_colormap(self._settings.current_colormap())
        self._view.set_levels(params.db_floor, params.db_ceil)
        if keep_view and self._saved_range is not None:
            self._view.set_view_range(*self._saved_range)
        elif not keep_view:
            self._view.reset_view()

    # ------------------------------------------------------------------ #
    # Controls
    # ------------------------------------------------------------------ #
    def _on_params_changed(self, _params) -> None:
        """Recompute the spectrogram for the current audio, preserving boxes."""
        if self._current_audio is None:
            return
        self._compute_and_show(keep_view=True)

    def _on_colormap_changed(self, name: str) -> None:
        self._view.set_colormap(name)
        self._config.colormap = name

    def _on_view_range_changed(self, t0: float, t1: float, f0: float, f1: float) -> None:
        self._saved_range = (t0, t1, f0, f1)

    # ------------------------------------------------------------------ #
    # Labels
    # ------------------------------------------------------------------ #
    def _on_active_label_changed(self, label) -> None:
        self._view.set_active_label(label.name, label.color)

    def _on_apply_to_selected(self, label) -> None:
        self._view.relabel_selected(label.name, label.color)

    def _on_labels_changed(self) -> None:
        """Persist the full label set when a label is added."""
        try:
            os.makedirs(os.path.dirname(self._config.labels_file), exist_ok=True)
            label_config.save_labels(
                self._labels.labels(), self._config.labels_file
            )
        except OSError as exc:
            self.statusBar().showMessage(f"Could not save labels: {exc}")

    # ------------------------------------------------------------------ #
    # Playback + playhead
    # ------------------------------------------------------------------ #
    def _on_position_clicked(self, t: float) -> None:
        """User clicked the spectrogram to move the play cursor."""
        self._cursor = float(t)
        if self._playing:
            self._play_from(self._cursor)  # restart from the new spot

    def _toggle_play(self) -> None:
        """Spacebar: play from the cursor, or pause (cursor stays put)."""
        if self._current_audio is None:
            return
        if self._playing:
            self._stop_playback(at_end=False)  # pause
        else:
            self._play_from(self._cursor)

    def _play_from(self, t: float, t_end: Optional[float] = None) -> None:
        """Start playback at ``t`` seconds, animating the playhead."""
        if self._current_audio is None:
            return
        dur = self._current_audio.meta.duration
        if t >= dur - 1e-3:  # at/after the end -> restart from the top
            t = 0.0
        self._cursor = t
        self._play_end = dur if t_end is None else min(float(t_end), dur)
        try:
            audio.play(self._current_audio, t, t_end)
        except RuntimeError as exc:
            self.statusBar().showMessage(str(exc))
            return
        self._playing = True
        self._play_pos0 = t
        self._play_t0 = time.monotonic()
        self._view.set_playhead(t)
        self._play_timer.start()

    def _advance_playhead(self) -> None:
        if not self._playing or self._current_audio is None:
            return
        pos = self._play_pos0 + (time.monotonic() - self._play_t0)
        if pos >= self._play_end:
            self._stop_playback(at_end=True)
            return
        self._cursor = pos
        self._view.set_playhead(pos)

    def _stop_playback(self, at_end: bool) -> None:
        """Stop playback. On natural end, park the cursor at the stop point."""
        was_playing = self._playing
        self._playing = False
        self._play_timer.stop()
        if was_playing:
            try:
                audio.stop()
            except RuntimeError:
                pass
        if at_end:
            self._cursor = self._play_end
            self._view.set_playhead(self._cursor)

    def _on_play(self) -> None:
        """Play button: play from the current cursor."""
        self._play_from(self._cursor)

    def _on_play_selection(self) -> None:
        if self._current_audio is None:
            return
        box = self._view.selected_box()
        if box is None:
            self.statusBar().showMessage("No box selected.")
            return
        self._play_from(box.t_start, box.t_end)

    def _on_stop(self) -> None:
        self._stop_playback(at_end=False)

    # ------------------------------------------------------------------ #
    # Saving
    # ------------------------------------------------------------------ #
    def _on_boxes_changed(self) -> None:
        self._dirty = True

    def _on_save(self) -> None:
        if self._current_path is None or self._current_audio is None:
            self.statusBar().showMessage("Nothing to save.")
            return
        self._save_annotation(self._current_path, quiet=False)

    def _save_annotation(self, path: str, quiet: bool) -> None:
        """Build and write the annotation sidecar for ``path``."""
        if self._current_audio is None or self._current_result is None:
            return
        params = self._settings.current_params()
        boxes = self._view.get_boxes()
        annotation = Annotation(
            audio_file=os.path.basename(path),
            audio_meta=self._current_audio.meta,
            spectrogram=params.to_meta(self._current_result.f_max),
            boxes=boxes,
        )
        try:
            io_json.save(annotation, path)
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Save failed: {exc}")
            return
        self._dirty = False
        self._file_list.refresh_annotated_marks()
        if not quiet:
            self.statusBar().showMessage(f"Saved {len(boxes)} boxes")

    # ------------------------------------------------------------------ #
    # Config persistence
    # ------------------------------------------------------------------ #
    def _persist_config(self) -> None:
        self._config.spectrogram = self._settings.current_params()
        self._config.colormap = self._settings.current_colormap()
        try:
            save_config(self._config)
        except OSError:
            pass

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self._stop_playback(at_end=False)
        if (
            self._config.autosave_on_switch
            and self._dirty
            and self._current_path is not None
        ):
            self._save_annotation(self._current_path, quiet=True)
        self._persist_config()
        super().closeEvent(event)


def main() -> int:
    """Console-script entry point: launch the GUI."""
    app = QApplication(sys.argv)
    config = load_config()
    window = MainWindow(config)
    window.show()
    return sys.exit(app.exec())


if __name__ == "__main__":
    main()
