# Cicada — Spectrogram Annotation Tool

Cicada is a lightweight, open-source tool for annotating audio spectrograms —
think **labelme, but for sound**. Open a folder of `.wav` files, draw labelled
boxes over regions of a spectrogram (calls, chorus, noise, …), and save each
file's annotations to a JSON sidecar next to the audio.

Built with **PySide6 + pyqtgraph**; spectrograms via **scipy**, audio I/O via
**soundfile**, playback via **sounddevice**.

## Setup

```shell
conda env create -f environment.yml
conda activate cicada
```

This installs the native libs (`portaudio`, `libsndfile`) the Python wheels bind
to, then `pip install -e .` for the package itself.

## Running

```shell
python -m cicada      # or simply:
cicada
```

## Usage

1. **Open Folder…** (File menu). Cicada looks for **variant subfolders** — each
   immediate subfolder that contains `.wav` files is treated as a *variant*
   (e.g. `mic/`, `out/`), and same-named files across them are grouped into one
   **recording**. The list shows one row per recording; a **Variant:** button bar
   lets you flip between e.g. mic vs enhanced. (If the folder has no such
   subfolders, it falls back to a flat list of every `.wav` found.) Recordings
   whose current variant is already annotated are marked with a `✓`.

   ```
   example/
     mic/  babble_15dB.wav      ┐  one recording "babble_15dB"
     out/  babble_15dB.wav      ┘  with variants [mic | out]
   ```

2. Select a recording: its spectrogram is computed. Use the **Spectrogram**
   controls (n_fft, hop, window, colormap, dB floor/ceil, f_max / Nyquist) to
   tune the view live — changing parameters re-renders the image without
   disturbing existing boxes (they live in time/frequency coordinates).
3. Tick **Annotate mode** and drag on the spectrogram to draw a box. **Double-click**
   a box to select it (a single click instead drops the play cursor); drag its
   body to move or its corner handles to resize; press **Delete**/**Backspace**
   to remove the selected box. Each variant has its **own** boxes, saved to its
   own sidecar.
4. In the **Labels** panel pick the active label (used for new boxes), **Add…** a
   new one, or **Apply to selected box** to relabel the current selection.
5. **Save** (`Ctrl+S`, or the button) writes `<audio>.json` beside that variant's
   wav. Annotations autosave when you switch recordings/variants by default.
6. **Switch variant** (click the bar or press `V`): the spectrogram view stays at
   the *same* time/frequency window, so mic and enhanced line up for comparison.
   **Lock view across files** extends that locking to different recordings too.
7. **Playback / cursor** (ocenaudio-style): **click** the spectrogram to drop the
   cyan play cursor, then **Space** to play/pause from it — the cursor animates
   along as it plays. **Play** plays from the cursor, **Play selection** plays the
   selected box's time span, **Stop** halts. If no audio device / PortAudio is
   available a status-bar message is shown instead of crashing.

### Keyboard

| Action               | Shortcut                |
|----------------------|-------------------------|
| Play / Pause         | `Space`                 |
| Cycle variant        | `V`                     |
| Save                 | `Ctrl+S`                |
| Next recording       | `Ctrl+Right` or `]`     |
| Previous recording   | `Ctrl+Left` or `[`      |
| Select box           | Double-click the box    |
| Delete box           | `Delete` / `Backspace`  |
| Set play cursor      | Single-click spectrogram|

Preferences (last folder, spectrogram defaults, colormap, labels file) persist
to `~/.cicada/config.json`; custom labels to `~/.cicada/labels.json`.

## JSON sidecar schema

Each audio file `foo.wav` gets a sibling `foo.json`:

```json
{
  "version": "1.0",
  "audio_file": "foo.wav",
  "audio_meta": {"sample_rate": 44100, "duration": 12.5, "n_channels": 1},
  "spectrogram": {"n_fft": 1024, "hop": 256, "window": "hann", "f_max": 22050.0},
  "boxes": [
    {"label": "call", "t_start": 1.0, "t_end": 2.0,
     "f_low": 100.0, "f_high": 200.0,
     "px": {"x": 10.0, "y": 20.0, "w": 30.0, "h": 40.0}},
    {"label": "noise", "t_start": 3.0, "t_end": 4.0,
     "f_low": 50.0, "f_high": 75.0, "px": null}
  ]
}
```

Box coordinates are authoritative in physical units (`t_start`/`t_end` in
seconds, `f_low`/`f_high` in Hz); `px` pixel coordinates are derived and stored
for reproducibility.

## Sample data

Generate known-content test clips (chirps, tone bursts) for manual checking:

```shell
python tools/make_sample.py /tmp/cicada_samples
```

## Note

The original Tkinter-based tool (CSV output) has been retired and is preserved
under `Archive/` for reference.
