# NeuroCrunch

A desktop application for neuroscience data analysis. Provides a file browser, multi-format viewer (images, video, CSV plots, PDFs), and a scriptable processing pipeline where analysis scripts can be configured, chained, and executed from the UI.

Built with **PySide6 + pyqtgraph**, distributed as a cross-platform PyInstaller bundle.

---

## Current Status

The core application shell is functional. What works today:

- **File browser** — folder selection, recursive tree view, right-click context menu, refresh
- **Multi-format viewer** — images, CSV/Excel plots (pyqtgraph, column selector, regex filter, clickable legend), video playback with controls, PDF (QPdfView + QWebEngineView fallback), plain text
- **Dark mode** — toggle with external QSS stylesheets (`assets/styles/`)
- **Scripts table** — discovers `.py` files from `scripts/`, shows name/timestamp, checkbox to enable, execution order column; in-memory config dict per script
- **Logging panel** — timestamped log with progress-update-in-place support

What is **not yet implemented**:

- Script subfolders with manifests (scripts are flat stubs today)
- Parameter configuration dialog (no UI to set script args)
- Actual script execution (subprocess runner not wired up)
- Script output chaining between pipeline steps
- In-app updater
- CI/CD pipeline

---

## Final Objective

NeuroCrunch should work as follows end-to-end:

1. User opens a data folder in the browser
2. Scripts panel lists all available analysis scripts (official + user-installed community plugins)
3. User selects scripts, sets their execution order, and configures parameters via auto-generated dialogs
4. Scripts that depend on a previous script's output have those parameters auto-filled
5. User clicks **Ejecutar Seleccionados** → scripts run as subprocesses in order; progress streams to the log
6. On app startup, the updater silently checks GitHub Releases; if a new stable version exists, a banner prompts the user to download and apply it
7. Community users can share scripts by publishing a folder containing `main.py` + `manifest.json`; others drop it into their local plugins directory

---

## Repository Structure

```
NeuroCrunch/
├── .github/
│   └── workflows/
│       └── build.yml               # CI/CD: build on version tag, upload to GitHub Releases
├── src/
│   ├── NeuroCrunch.py              # Application entry point and main window logic
│   ├── mainwindow.py               # Auto-generated from mainwindow.ui — DO NOT EDIT
│   ├── dark_mode_manager.py        # Theme management
│   ├── plugin_manager.py           # Script discovery and manifest parsing       [PLANNED]
│   ├── param_dialog.py             # Auto-generated parameter dialogs             [PLANNED]
│   ├── script_runner.py            # Subprocess execution engine + pipeline ctx   [PLANNED]
│   └── updater.py                  # GitHub Releases version check + download     [PLANNED]
├── ui/
│   └── mainwindow.ui               # Qt Designer source
├── assets/
│   ├── icons/
│   └── styles/
│       ├── dark.qss
│       └── light.qss
├── scripts/                        # Official bundled analysis scripts
│   ├── procesar_video/             # One subfolder per script
│   │   ├── main.py
│   │   └── manifest.json
│   ├── seleccionar_ROIs/
│   ├── quitar_bleaching/
│   ├── seleccionar_activas/
│   ├── generar_graficos/
│   └── matriz_pearson/
├── schemas/
│   └── plugin_manifest.schema.json # JSON Schema for manifest validation          [PLANNED]
├── version.json                    # {"version": "x.y.z", "channel": "stable", "repo": "owner/NeuroCrunch"}
├── neurocruncher.spec              # PyInstaller build spec
└── requirements.txt
```

**User plugins directory** (writable, outside the PyInstaller bundle):

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\NeuroCrunch\plugins\` |
| macOS | `~/Library/Application Support/NeuroCrunch/plugins/` |
| Linux | `~/.config/NeuroCrunch/plugins/` |

---

## Roadmap

Status markers: ✅ Done · 🔄 In progress · ⬜ Planned

### Phase 1 — Folder Restructure & Version Tracking
- ✅ Core app shell, file browser, viewers, dark mode
- ✅ Move each script stub into its own subfolder (`scripts/{name}/main.py`)
- ✅ Create `manifest.json` for each official script
- ✅ Create `version.json` at project root
- ✅ Update `neurocruncher.spec` to include `scripts/` and `version.json` in bundle
- ✅ Update `NeuroCrunch.py` to scan for script subfolders instead of flat `.py` files
- ✅ Resolve user plugins directory at startup and merge with bundled scripts

### Phase 2 — Plugin Manager (`src/plugin_manager.py`)
- ✅ `PluginInfo` dataclass: `id`, `name`, `description`, `version`, `author`, `category`, `entry_point` (abs path), `parameters`, `outputs`, `is_official`
- ✅ `PluginManager.discover_scripts(bundled_dir, user_dir)` — scans both dirs, parses manifests, skips invalid entries with a log warning
- ✅ Manifest validation against JSON Schema (`schemas/plugin_manifest.schema.json`)
- ✅ Wire into `NeuroCrunch.py`: replace current flat scan with `PluginManager`, populate scripts table with rich metadata

### Phase 3 — Parameter Dialog (`src/param_dialog.py`)
- ⬜ `ParamDialog(plugin_info, current_values, pipeline_context, parent)` → `QDialog`
- ⬜ Widget generation from `parameter.type` (see type→widget table below)
- ⬜ Linked parameters pre-filled from `PipelineContext`, shown with "From: {source_script}" label; still editable
- ⬜ Validation on accept: all required params must be non-empty
- ⬜ Scripts table "Configurado" cell turns green when all required params are saved

### Phase 4 — Script Runner (`src/script_runner.py`)
- ⬜ `PipelineContext` — stores `{script_id: {output_key: value}}`; persisted to `session_dir/pipeline_context.json`
- ⬜ `ScriptRunner(QThread)` — signals: `log_message(str)`, `script_started(str)`, `script_finished(str, bool)`, `pipeline_done(bool)`
- ⬜ Per-script execution: write `params.json`, call `python main.py --nc_params ... --nc_output ...`, stream stdout to log, read output JSON into context
- ⬜ Linked param resolution before each script run
- ⬜ Pipeline halt on script error; log message with script name and exit code
- ⬜ Stop/kill button in UI to cancel a running pipeline
- ⬜ Wire `btn_data_plot` ("Ejecutar Seleccionados") to `ScriptRunner`

### Phase 5 — Updater (`src/updater.py`)
- ⬜ `UpdateChecker(QThread)` — on startup, `GET https://api.github.com/repos/{repo}/releases/latest`; compare `tag_name` with `version.json`; emit `update_available(dict)` for newer stable releases
- ⬜ Status bar banner shown when update is available ("NeuroCrunch v1.x available — Download")
- ⬜ `UpdateDownloader(QThread)` — downloads platform asset to `user_data_dir/updates/`; progress shown in log; emits `download_complete(path)`
- ⬜ On `download_complete`: `QMessageBox` prompts "Restart to apply update"; on confirm, launch installer/archive and quit
- ⬜ Update launcher shim for Windows (required to replace running `.exe` — a small `.bat` or Python script that swaps the binary before re-launching)

### Phase 6 — CI/CD (`.github/workflows/build.yml`)
- ⬜ Trigger: push to tags matching `v*.*.*`
- ⬜ Matrix: `windows-latest`, `macos-latest`, `ubuntu-latest`
- ⬜ Steps: checkout → Python 3.11 → `pip install -r requirements.txt pyinstaller` → `pyinstaller neurocruncher.spec` → archive dist → upload to GitHub Release
- ⬜ Asset naming convention (must match updater download logic):
  - `NeuroCrunch-{version}-windows.exe`
  - `NeuroCrunch-{version}-macos.zip`
  - `NeuroCrunch-{version}-linux.tar.gz`
- ⬜ `version.json` must be updated before tagging a release (manual step or helper script)

### Phase 7 — Multilanguage Support (`translations/`)

The app currently hard-codes Spanish strings throughout the UI and manifests. This phase adds proper i18n using Qt's built-in translation system.

- ⬜ Wrap all hard-coded UI strings in `self.tr()` / `QCoreApplication.translate()` across `NeuroCrunch.py` and `src/` modules
- ⬜ Re-generate `src/mainwindow.py` from the `.ui` file after marking strings translatable in Qt Designer
- ⬜ Create `translations/` folder; add initial `.ts` source files for `es` (Spanish, base) and `en` (English)
- ⬜ Add `lupdate`/`lrelease` commands to dev workflow (extract strings → compile to `.qm`)
- ⬜ Load `.qm` file at startup via `QTranslator` based on stored language preference (falls back to system locale, then Spanish)
- ⬜ Language selector in app settings (stored in user config); takes effect on next launch
- ⬜ Bundle all `.qm` files in `assets/translations/` and include in PyInstaller spec
- ⬜ Manifest localized labels — plugin authors can supply per-language overrides (see manifest standard below); app picks the best match at load time
- ⬜ CI/CD: add `lrelease` step before PyInstaller build so compiled `.qm` files are always up to date in the bundle

---

## Plugin / Script Standard

Every script — official or community — lives in its own subfolder and must contain exactly two files.

### `manifest.json`

```json
{
  "id": "procesar_video",
  "name": "Procesar Video",
  "description": "Extracts fluorescence traces from a calcium imaging video.",
  "version": "1.0.0",
  "author": "NeuroCrunch Team",
  "category": "preprocessing",
  "entry_point": "main.py",
  "parameters": [
    {
      "name": "input_video",
      "type": "file",
      "label": "Video de entrada",
      "required": true,
      "extensions": [".tif", ".tiff", ".avi", ".mp4"],
      "description": "Calcium imaging video file"
    },
    {
      "name": "fps",
      "type": "int",
      "label": "Frames por segundo",
      "default": 10,
      "min": 1,
      "max": 1000
    },
    {
      "name": "output_dir",
      "type": "directory",
      "label": "Carpeta de salida",
      "required": true
    }
  ],
  "outputs": {
    "output_csv": "Path to the extracted signals CSV file"
  }
}
```

#### Parameter types

| `type` | Widget | Extra fields |
|---|---|---|
| `string` | `QLineEdit` | — |
| `int` | `QSpinBox` | `min`, `max` |
| `float` | `QDoubleSpinBox` | `min`, `max`, `decimals` |
| `bool` | `QCheckBox` | — |
| `file` | `QLineEdit` + Browse | `extensions` (list) |
| `directory` | `QLineEdit` + Browse | — |
| `choice` | `QComboBox` | `options` (list of strings) |
| `text` | `QTextEdit` | — |

#### Localized labels

Manifest `label` and `description` fields can optionally be replaced by a locale map. The app picks the best match for the active language and falls back to the bare string value if no match is found.

```json
{
  "name": "fps",
  "type": "int",
  "label": {"es": "Frames por segundo", "en": "Frames per second"},
  "description": {"es": "Velocidad de muestreo del video", "en": "Video sampling rate"},
  "default": 10
}
```

A bare string (`"label": "Frames por segundo"`) is always valid and treated as the fallback for all locales.

#### Linking a parameter to a previous script's output

Add a `"link"` field referencing `"{script_id}.{output_key}"`. The app will auto-fill the value from the pipeline context if that script has already run. The field remains editable.

```json
{
  "name": "input_csv",
  "type": "file",
  "label": "CSV de entrada",
  "link": "procesar_video.output_csv"
}
```

### `main.py` — execution contract

Scripts are run as subprocesses. The app calls:

```
python main.py --nc_params /tmp/.../procesar_video_params.json --nc_output /tmp/.../procesar_video_output.json
```

**`params.json`** contains all configured parameter values plus a `_context` key:

```json
{
  "input_video": "/path/to/video.tif",
  "fps": 10,
  "output_dir": "/path/to/session/",
  "_context": {
    "session_dir": "/path/to/session/",
    "pipeline_outputs": {
      "procesar_video": {"output_csv": "/path/to/signals.csv"}
    }
  }
}
```

Scripts read this file, do their work, then write **`output.json`** with their declared output keys:

```json
{
  "output_csv": "/path/to/session/procesar_video/signals.csv"
}
```

Anything written to **stdout** is captured line-by-line and appended to the UI log. A non-zero exit code halts the pipeline.

---

## Development Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Run from source
python src/NeuroCrunch.py

# Build with PyInstaller
pyinstaller neurocruncher.spec
```

**Dependencies**: `PySide6==6.9.2`, `pyqtgraph==0.14.4`, `pandas==2.2.3`, `numpy==2.1.3`

`src/mainwindow.py` is auto-generated from `ui/mainwindow.ui` by Qt's `uic` tool. Do not edit it by hand.

To regenerate after editing the `.ui` file:

```bash
pyside6-uic ui/mainwindow.ui -o src/mainwindow.py
```

---

## Open Questions / Decisions Needed

- [ ] Confirm GitHub repo URL (needed for `version.json` → `"repo"` field and updater)
- [ ] Decide on Windows installer format: bare `.exe` from PyInstaller, or an NSIS/Inno Setup installer (required for clean update replacement of a running binary)
- [ ] Script timeout policy: maximum allowed runtime per script before the runner kills it?
- [ ] Should community plugins be allowed to declare additional Python dependencies (`"requires"` in manifest), and if so, should the app attempt to `pip install` them automatically?
- [ ] Confirm base/default language (currently Spanish — all existing strings are `es`)
- [ ] Which languages to ship in v1.0? Suggested: `es` (base) + `en`; others added by community via PR
- [ ] Language preference: per-user config file, or respect OS locale by default?
