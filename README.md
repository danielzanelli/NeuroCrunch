# NeuroCrunch

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/danielzanelli/NeuroCrunch)](https://github.com/danielzanelli/NeuroCrunch/releases/latest)

NeuroCrunch is a desktop app for neuroscience data analysis: browse and preview your recordings, then chain no-code analysis scripts into a visual pipeline — from raw calcium-imaging video to correlation plots — without touching a terminal or writing code.

---

## Overview

NeuroCrunch combines two core capabilities:

1. **A universal file browser and multi-format viewer** — open recordings, spreadsheets, PDFs, or text files in a live preview pane; overlays regions of interest (ROIs) directly onto videos.
2. **A visual, no-code pipeline builder** — chain analysis scripts together using an interactive table, set their parameters in auto-generated forms, and run them with a click. Scripts link automatically: one script's output becomes the next script's input.

The app ships with a complete **calcium-imaging pipeline** (video processing → ROI extraction → fluorescence analysis → correlation analysis → visualization), extensible via community-authored plugins. Built with **PySide6 + pyqtgraph**, distributed as a cross-platform PyInstaller bundle (Windows installer, macOS `.dmg`, Linux AppImage).

---

## Download & Install

Get the latest release for your operating system:

| Platform | Installer |
|---|---|
| **Windows** | [NeuroCrunch-{version}-windows-setup.exe](https://github.com/danielzanelli/NeuroCrunch/releases/latest) |
| **macOS** | [NeuroCrunch-{version}-macos.dmg](https://github.com/danielzanelli/NeuroCrunch/releases/latest) |
| **Linux** | [NeuroCrunch-{version}-linux.AppImage](https://github.com/danielzanelli/NeuroCrunch/releases/latest) |

**First launch note:** Releases are currently **unsigned**. If your OS shows a security warning (SmartScreen on Windows, Gatekeeper on macOS), see [Installing an unsigned build](#installing-an-unsigned-build) below for how to proceed.

---

## Features

### File Browser & Multi-Format Viewer

Open a folder and browse its contents in a tree view. Double-click any file to preview it:

- **Images** (.png, .jpg, .jpeg, .bmp, .gif) — displayed at native resolution; auto-scales to fit the window.
- **Videos** (.mp4, .avi, .mov, .mkv, .wmv, .flv, .mpeg, .mpg, .webm, .tif, .tiff) — play/pause with a seek slider. **ROI overlay**: if you have a `.zip` file of regions of interest (e.g., from ImageJ/FIJI or NeuroCrunch's ROI-selection step), double-click it *while a video is open* to draw green ROI outlines on every frame.
- **Spreadsheets** (.csv, .xls, .xlsx) — loaded into an interactive plot viewer. Filter columns by substring, select a column range, and click "Plot" to graph up to 100 traces. Click legend entries to toggle visibility of individual traces.
- **PDFs** (.pdf) — rendered with built-in PDF support (or a web-based fallback).
- **Text** (any other file) — displayed as plain UTF-8 text.

Right-click a file for options: **Open** (preview) or **Show in folder** (show in file explorer).

### Dark Mode

Toggle between light and dark themes with the theme icon button in the **Script pipeline** panel header. The app starts in dark mode by default. All viewer elements (graphs, text, video controls) adapt automatically.

### Visual, No-Code Pipeline

Build analysis workflows by selecting scripts and configuring them, no code required:

1. **Select scripts** — in the **Script pipeline** table, check the boxes next to the scripts you want to run.
2. **Configure each script** — double-click a script row to open its parameter dialog. Fill in required fields (marked with `*`). Many fields are auto-filled from previous script outputs; hover over the value to see which script supplied it.
3. **Set execution order** — use the **Order** dropdown to number the scripts in the order you want them to run. Conflicting orders are resolved automatically.
4. **Run the pipeline** — click **Run**. Watch the live log as each script runs, with real-time progress updates. Press **Stop** to cancel.
5. **Save & reuse** — click **Save** to export your pipeline configuration (including the working folder) to a `.config` file; click **Load** to restore it later.

### Built-in Calcium-Imaging Pipeline

Six analysis scripts are bundled. Run them in sequence, or pick and mix:

1. **Generate ROIs** (preprocessing) — *not yet implemented* — will let you interactively draw regions of interest (circular, rectangular, or polygonal) over a calcium-imaging video and export them as a `.zip` file (ImageJ/FIJI-compatible format). For now, define ROIs using ImageJ/FIJI and import them.
2. **Generate Signals** (preprocessing) — extracts fluorescence signal from each ROI. Measures max, mean, standard deviation, and integral of pixel intensity per ROI per frame; optional Z-score normalization. Output: CSV of raw traces.
3. **Signal Processing** (processing) — removes photobleaching (signal decay over time) using an Asymmetric Least Squares (ALS) algorithm with customizable parameters. Output: corrected and smoothed CSV.
4. **Select Active** (processing) — keeps only cells with activity above a noise threshold sustained for a minimum number of frames. Output: CSV of active cells only.
5. **Pearson Matrix** (analysis) — computes pairwise Pearson correlations between active cells. Output: correlation matrix CSV + heatmap image (PNG).
6. **Connectivity Graph** (visualization) — produces summary plots from processed signals (overlay, raster, and mean±σ). Choose output format (PNG, SVG, PDF) and add a custom title.

**Typical workflow**: Generate Signals → Signal Processing → Select Active → Pearson Matrix → Connectivity Graph. (Generate ROIs will be inserted at the very start once it's implemented.)

### Extensibility & Community Scripts

Write your own analysis scripts in Python and drop them into the user plugins folder:

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\NeuroCrunch\plugins\` |
| macOS | `~/Library/Application Support/NeuroCrunch/plugins/` |
| Linux | `~/.config/NeuroCrunch/plugins/` |

Each script is a folder containing a `config.json` (metadata and parameters) and a `.py` file named after the folder. Community scripts shadow official ones if they share the same id, so you can override or extend bundled scripts. See [Writing Your Own Scripts](#writing-your-own-scripts) below for the full contract and examples.

Click the **Scripts** button to open your plugins folder directly.

### Auto-Updater

On startup, NeuroCrunch silently checks GitHub for a newer release. If one is available, a prompt appears in the status bar: "NeuroCrunch *X.Y.Z* available". Click to download and apply the update automatically. The app restarts with the new version.

### Internationalization

The codebase is written in **English** (base language), with **Spanish** provided through the translation layer. Switch languages from the **Preferences** dialog — click the gear icon in the **Script pipeline** panel header, pick a language, and the UI updates immediately. Your choice is saved and restored on the next launch. The app starts in English by default and falls back to English for any string a translation doesn't cover.

---

## How to Use

### Step-by-step walkthrough

1. **Open a data folder** — click **Select folder** to browse for the folder containing your recordings, CSVs, ROI files, etc. The folder tree on the left will populate with all files.
2. **Preview files** — double-click any file in the tree to open it in the center viewer.
3. **Build a pipeline** — look at the **Script pipeline** panel on the right:
   - Double-click a script to configure it (a dialog will open with fields for each parameter).
   - Check the checkbox next to scripts you want to run.
   - Use the **Order** dropdown to set the order (1, 2, 3, …).
4. **Run the pipeline** — click **Run**. Watch the **Log** panel at the bottom for real-time output and progress. If you need to stop early, click **Stop**.
5. **Save your pipeline** — once configured, click **Save** to save the pipeline config and working folder path. Next time you open NeuroCrunch, you can click **Load** to restore it.
6. **Extend with plugins** — click **Scripts** to open the user plugins folder. Add new scripts by creating subfolders with `config.json` + script files. Click the refresh icon (**Refresh folder and scripts**) to reload the scripts list without restarting the app.

### Example: Process a calcium-imaging video end-to-end

Assume you have a video file `imaging.tif` and ROI definitions in `rois.zip` (e.g., from ImageJ).

1. **Select folder** → navigate to the folder containing `imaging.tif` and `rois.zip`.
2. **Configure Generate Signals**:
   - Double-click "Generate Signals" in the scripts table.
   - Input video: browse to `imaging.tif`.
   - ROI file: browse to `rois.zip`.
   - Frames per second: enter `10` (or your video's frame rate).
   - Output folder: choose an output folder.
   - Click **Accept**.
3. **Configure Signal Processing**:
   - Double-click it. Input CSV will auto-fill from Generate Signals' output.
   - Adjust ALS parameters if needed (defaults are reasonable).
   - Click **Accept**.
4. **Configure Select Active**:
   - Double-click it. Input CSV will auto-fill. Adjust thresholds if needed.
   - Click **Accept**.
5. **Configure Pearson Matrix**:
   - Double-click it. Input CSV will auto-fill. Set correlation threshold (default 0.5).
   - Click **Accept**.
6. **Configure Connectivity Graph**:
   - Double-click it. Input CSV will auto-fill. Choose format (PNG). Add a title if desired.
   - Click **Accept**.
7. **Check the checkboxes** next to all 5 scripts; set their **Order** to 1, 2, 3, 4, 5 respectively.
8. **Click Run** — the pipeline runs in sequence. Watch the log for progress and any errors.
9. **Review outputs** — when done, open your output folder and preview the CSV files and images in NeuroCrunch's viewer.

---

## Writing Your Own Scripts

Every script — official or community — lives in its own folder and consists of a `config.json` metadata file and a single `.py` file named after the folder.

### Structure

```
my_analysis/
├── config.json           # Metadata, parameters, outputs
└── my_analysis.py        # Script code
```

### `config.json`

```json
{
  "name": "My Analysis",
  "description": "Does something useful with fluorescence data.",
  "version": "1.0.0",
  "author": "Your Name",
  "category": "analysis",
  "parameters": [
    {
      "name": "input_csv",
      "type": "file",
      "label": "Input CSV",
      "description": "CSV with fluorescence traces",
      "required": true,
      "extensions": [".csv"],
      "link": "previous_script.output_csv"
    },
    {
      "name": "threshold",
      "type": "float",
      "label": "Threshold",
      "default": 0.5,
      "min": 0.0,
      "max": 1.0,
      "decimals": 2
    }
  ],
  "outputs": {
    "result_csv": "Path to the output CSV"
  }
}
```

`id` (script folder name) and `entry_point` (script filename) are auto-derived and don't need to be in the JSON.

#### Parameter Types

| `type` | Widget | Extra fields |
|---|---|---|
| `string` | Text field | — |
| `int` | Number input | `min`, `max` |
| `float` | Decimal input | `min`, `max`, `decimals` |
| `bool` | Checkbox | — |
| `file` | File picker | `extensions` (list, e.g., `[".csv", ".xlsx"]`) |
| `directory` | Folder picker | — |
| `choice` | Dropdown | `options` (list of strings) |
| `text` | Multi-line text | — |

#### Linked Parameters

Link a parameter to a previous script's output by adding a `"link"` field:

```json
{
  "name": "input_csv",
  "type": "file",
  "label": "Input CSV",
  "link": "generate_signals.output_csv"
}
```

When a user runs `generate_signals` first, NeuroCrunch auto-fills this parameter with the output path. The field is still editable.

The manifest `link` is only a default: in the parameter dialog, every file/folder parameter has a link button (🔗) where users can pick any other script's declared output — or switch back to a manually chosen file. Output paths produced by a run are remembered (and stored in saved `.config` files), so a linked parameter also resolves when the source script ran in an earlier session.

#### Localized Labels

Multi-language parameter labels:

```json
{
  "name": "threshold",
  "type": "float",
  "label": {"en": "Threshold", "es": "Umbral"},
  "description": {"en": "Minimum value", "es": "Valor mínimo"}
}
```

### `my_analysis.py`

Define a `run(params)` function. The app calls it directly in a worker thread:

```python
def run(params):
    """
    params: dict of parameter values (keys match config.json "name" fields).
    Returns: dict whose keys match the "outputs" declared in config.json.
    Use print() to send messages to the app log.
    Raise an exception to report an error.
    """
    input_csv = params["input_csv"]
    threshold = params["threshold"]
    output_dir = params.get("output_dir", ".")

    print("Loading data...")
    import pandas as pd
    df = pd.read_csv(input_csv)

    print("Processing...")
    result = df[df.mean(axis=1) > threshold]

    output_path = f"{output_dir}/result.csv"
    result.to_csv(output_path, index=False)
    print(f"Saved to {output_path}")

    return {"result_csv": output_path}
```

For progress reporting and cancellation, accept an optional `ctx` parameter:

```python
def run(params, ctx):
    items = [...]
    for i, item in enumerate(items):
        if ctx.is_cancelled():
            return {}  # User clicked Stop
        ctx.progress(100 * i / len(items))
        # ... process item ...
    return {...}
```

Or report progress with `print("PROGRESS:50")` (sets the progress bar to 50%).

#### Rules

- Never call `sys.exit()` — raise an exception instead.
- Never call `os._exit()` — it terminates the app.
- `if __name__ == "__main__":` blocks are safe and won't be executed by the app.

#### Bundled Libraries

These libraries are pre-installed and available in all scripts; no `pip install` needed:

`numpy`, `pandas`, `opencv-python-headless`, `matplotlib`, `tifffile`, `read_roi`, `jsonschema`

To use a new library, add it to `requirements.txt` **and** the `collect_all` list in `neurocruncher.spec`, then rebuild the app.

---

## Repository Structure

```
NeuroCrunch/
├── .github/
│   └── workflows/
│       └── build.yml               # CI/CD: build on version tag, upload to GitHub Releases
├── src/
│   ├── NeuroCrunch.py              # Application entry point and main window logic
│   ├── mainwindow.py               # Auto-generated from mainwindow.ui — do not edit
│   ├── icon_loader.py              # Icon loading utilities
│   ├── dark_mode_manager.py        # Theme management
│   ├── plugin_manager.py           # Script discovery and config parsing
│   ├── param_dialog.py             # Auto-generated parameter dialogs
│   ├── script_runner.py            # Threaded execution engine + pipeline context
│   └── updater.py                  # GitHub Releases version check and download
├── ui/
│   └── mainwindow.ui               # Qt Designer source
├── assets/
│   ├── icons/
│   └── styles/
│       ├── dark.qss
│       └── light.qss
├── scripts/                        # Official bundled analysis scripts
│   ├── generate_signals/
│   ├── signal_processing/
│   ├── select_active/
│   ├── generate_rois/
│   ├── pearson_matrix/
│   ├── connectivity_graph/
│   └── template/                   # Copy-paste starting point for new scripts
├── schemas/
│   └── plugin_config.schema.json   # JSON Schema for config.json validation
├── assets/translations/            # i18n: .ts source files and compiled .qm/.qm.json
├── version.json                    # {"version": "x.y.z", "channel": "stable", "repo": "owner/NeuroCrunch"}
├── neurocruncher.spec              # PyInstaller build spec
└── requirements.txt
```

---

## Development Setup

### Run from source

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python src/NeuroCrunch.py
```

### Build a frozen release

```bash
# Install PyInstaller
pip install pyinstaller

# Build
pyinstaller neurocruncher.spec

# Output is in dist/NeuroCrunch/
```

The spec file optimizes the bundle size (~1.6 GB dependencies → ~750 MB frozen):
- Drops unused packages (scipy, dev tools).
- Keeps only Spanish/English Qt translations.
- Excludes QtWebEngine (~290 MB). PDFs use QtPdf instead; if rendering fails, you can re-add it.

**Requirements:** Python 3.13+ (tested on 3.13).

### Regenerate the main window from Qt Designer

The file `src/mainwindow.py` is auto-generated from `ui/mainwindow.ui` and should not be edited by hand. If you modify the `.ui` file in Qt Designer, regenerate:

```bash
pyside6-uic ui/mainwindow.ui -o src/mainwindow.py
```

---

## Installing an Unsigned Build

Releases are currently **unsigned**, so your OS will warn on first launch. This is expected.

- **Windows** — SmartScreen shows "Windows protected your PC". Click **More info → Run anyway**.
- **macOS** — Gatekeeper says the app is damaged or can't be opened. Right-click the `.app` → **Open**, or run: `xattr -dr com.apple.quarantine /Applications/NeuroCrunch.app`.
- **Linux (AppImage)** — no gatekeeper. Make it executable and run: `chmod +x NeuroCrunch-*-linux.AppImage && ./NeuroCrunch-*-linux.AppImage`.

Signing (Windows code-signing certificate + Apple notarization) can be added later to remove these warnings.

---

## Future Work

- **Algorithmic ROI detection** — implement `generate_rois` as an automatic (not interactive) script for detecting regions of interest in a representative video frame or projection.
- **Network graph visualization** — add a `generate_graph` script to build weighted connectivity networks from correlation matrices, plus an interactive graph viewer with hub-metric coloring and click-to-highlight neighbors.
- **Expand the preferences dialog** — the Preferences dialog currently exposes a language selector; grow it with more user settings (default working folder, UI options, update channel).
- **Community translations** — expand language support beyond English and Spanish; accept translations via pull request.
- **Script timeout policy** — define and enforce a maximum runtime per script.
- **Automated macOS packaging** — implement `.dmg` building in the CI/CD pipeline.

---

## License

NeuroCrunch is licensed under the [Apache License 2.0](LICENSE) — a permissive license standard in scientific software. You are free to use, modify, and redistribute it (including commercially), provided you preserve the [LICENSE](LICENSE) and [NOTICE](NOTICE) files.

Bundled third-party components (Qt/PySide6 under LGPL-3.0, plus the permissively licensed scientific stack) are documented in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
