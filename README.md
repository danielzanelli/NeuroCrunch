# NeuroCrunch

A desktop application for neuroscience data analysis. Provides a file browser, multi-format viewer (images, video, CSV plots, PDFs), and a scriptable processing pipeline where analysis scripts can be configured, chained, and executed from the UI.

Built with **PySide6 + pyqtgraph**, distributed as a cross-platform PyInstaller bundle.

---

## Current Status

Phases 1–5 are complete. The full analysis pipeline is functional end-to-end.

What works today:

- **File browser** — folder selection, recursive tree view, right-click context menu, refresh
- **Multi-format viewer** — images, CSV/Excel plots (pyqtgraph, column selector, regex filter, clickable legend), video playback with controls, PDF (QPdfView + QWebEngineView fallback), plain text
- **Dark mode** — toggle with external QSS stylesheets (`assets/styles/`)
- **Plugin manager** — discovers `config.json`-based plugins from bundled `scripts/` and the user plugins directory; validates against JSON Schema; auto-derives `id` and `entry_point` from folder name; user scripts shadow official ones by id
- **Parameter dialogs** — auto-generated from `config.json` parameter definitions; all 8 widget types (`string`, `int`, `float`, `bool`, `file`, `directory`, `choice`, `text`); linked parameter auto-fill from pipeline context; required-field validation; "Configurado" status indicator
- **Script runner** — in-process execution via `QThread` + `exec()` (no external Python needed); `StdoutCapture` for live log streaming with in-place `\r` progress updates; `PROGRESS:N` protocol drives a progress indicator; cooperative cancellation via `ScriptContext`; pipeline halts on first error
- **Logging panel** — timestamped log with progress-update-in-place support
- **Official scripts** — `procesar_video` and `quitar_bleaching` fully implemented and migrated to the `run(params)` standard; 4 stubs pending
- **Script template** — `scripts/template/` with all 8 parameter types documented alongside logging, progress, cancellation, and matplotlib usage examples

What is **not yet implemented**:

- 4 of 6 official scripts are still stubs (`generar_graficos`, `matriz_pearson`, `seleccionar_activas`, `seleccionar_ROIs`)
- In-app updater (Phase 6)
- CI/CD pipeline (Phase 7)
- Multilanguage / i18n support (Phase 8)

---

## Final Objective

NeuroCrunch should work as follows end-to-end:

1. User opens a data folder in the browser
2. Scripts panel lists all available analysis scripts (official + user-installed community plugins)
3. User selects scripts, sets their execution order, and configures parameters via auto-generated dialogs
4. Scripts that depend on a previous script's output have those parameters auto-filled
5. User clicks **Ejecutar Seleccionados** → scripts run in worker threads in order; progress streams live to the log
6. On app startup, the updater silently checks GitHub Releases; if a new stable version exists, a banner prompts the user to download and apply it
7. Community users can share scripts by publishing a folder containing `<script_name>.py` + `config.json`; others drop it into their local plugins directory

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
│   ├── plugin_manager.py           # Script discovery and config parsing
│   ├── param_dialog.py             # Auto-generated parameter dialogs
│   ├── script_runner.py            # Threaded execution engine + pipeline ctx
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
│   │   ├── procesar_video.py       # Script file — named after the folder
│   │   └── config.json             # Script metadata and parameters
│   ├── quitar_bleaching/
│   ├── seleccionar_ROIs/
│   ├── seleccionar_activas/
│   ├── generar_graficos/
│   ├── matriz_pearson/
│   └── template/                   # Copy-paste starting point for new scripts
├── schemas/
│   └── plugin_config.schema.json   # JSON Schema for config.json validation
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
- ✅ `ParamDialog(plugin_info, current_values, pipeline_context, parent)` → `QDialog`
- ✅ Widget generation from `parameter.type` (see type→widget table below)
- ✅ Linked parameters pre-filled from `pipeline_context`, shown with "Fuente: {source_script}" label; still editable
- ✅ Validation on accept: all required params must be non-empty
- ✅ Scripts table "Configurado" cell turns green when all required params are saved
- ✅ Double-click a script row to open its parameter dialog
- ✅ Minimal in-memory `pipeline_context` dict (`{script_id: {output_key: value}}`) wired into `NeuroCrunch.py`
- ✅ Official script manifests updated with representative parameter definitions

### Phase 4 — Script Runner (`src/script_runner.py`)
- ✅ `PipelineContext` — stores `{script_id: {output_key: value}}`; persisted to `session_dir/pipeline_context.json`
- ✅ `ScriptRunner(QThread)` — signals: `log_message(str)`, `script_started(str)`, `script_finished(str, bool)`, `pipeline_done(bool)`
- ✅ Per-script execution: write `params.json`, call `python main.py --nc_params ... --nc_output ...`, stream stdout to log, read output JSON into context
- ✅ Linked param resolution before each script run
- ✅ Pipeline halt on script error; log message with script name and exit code
- ✅ Stop/kill button in UI to cancel a running pipeline
- ✅ Wire `btn_execute_scripts` ("Ejecutar Seleccionados") to `ScriptRunner`

### Phase 5 — Script System Refactor

*Replaces the Phase 4 subprocess model with in-process threading and a simpler script convention. No external Python interpreter required after this phase.*

- ✅ Rename `manifest.json` → `config.json` and `main.py` → `<script_name>.py` across all script folders
- ✅ `src/plugin_manager.py`: search for `config.json`; auto-derive `id` from folder name and `entry_point` as `<folder_name>.py` — both removed from required config fields; `template/` and `_`-prefixed folders skipped during discovery
- ✅ `schemas/plugin_config.schema.json`: renamed; `id`, `entry_point`, `version`, `author` made optional
- ✅ All 6 `config.json` files: `entry_point` field removed (auto-derived)
- ✅ `src/script_runner.py`: replaced `subprocess.Popen` with `QThread` + `exec()` in a fresh namespace
- ✅ `StdoutCapture` — redirects `sys.stdout` per run; emits `log_message` signal line by line; handles `\r` in-place; detects `PROGRESS:N` lines to drive a progress indicator
- ✅ `ScriptContext` — optional second parameter `run(params, ctx)`; wraps `threading.Event` for cooperative cancellation via `ctx.is_cancelled()`; exposes `ctx.progress(n)` and `ctx.log(msg)`
- ✅ `procesar_video` and `quitar_bleaching`: `run = main` alias added; `sys.exit()` inside `run()` caught by runner; `if __name__ == "__main__":` preserved for CLI use
- ✅ Add `scripts/template/` — copy-paste starting point with all 8 parameter types, logging, progress, cancellation, and matplotlib usage documented inline
- ✅ `tests/test_script_runner.py`: rewritten for threading model (58 tests passing)

### Phase 6 — Updater (`src/updater.py`)
- ⬜ `UpdateChecker(QThread)` — on startup, `GET https://api.github.com/repos/{repo}/releases/latest`; compare `tag_name` with `version.json`; emit `update_available(dict)` for newer stable releases
- ⬜ Status bar banner shown when update is available ("NeuroCrunch v1.x available — Download")
- ⬜ `UpdateDownloader(QThread)` — downloads platform asset to `user_data_dir/updates/`; progress shown in log; emits `download_complete(path)`
- ⬜ On `download_complete`: `QMessageBox` prompts "Restart to apply update"; on confirm, launch installer/archive and quit
- ⬜ Update launcher shim for Windows (required to replace running `.exe` — a small `.bat` or Python script that swaps the binary before re-launching)

### Phase 7 — CI/CD (`.github/workflows/build.yml`)
- ⬜ Trigger: push to tags matching `v*.*.*`
- ⬜ Matrix: `windows-latest`, `macos-latest`, `ubuntu-latest`
- ⬜ Steps: checkout → Python 3.11 → `pip install -r requirements.txt pyinstaller` → `pyinstaller neurocruncher.spec` → archive dist → upload to GitHub Release
- ⬜ Asset naming convention (must match updater download logic):
  - `NeuroCrunch-{version}-windows.exe`
  - `NeuroCrunch-{version}-macos.zip`
  - `NeuroCrunch-{version}-linux.tar.gz`
- ⬜ `version.json` must be updated before tagging a release (manual step or helper script)

### Phase 8 — Multilanguage Support (`translations/`)

The app currently hard-codes Spanish strings throughout the UI and manifests. This phase adds proper i18n using Qt's built-in translation system.

- ⬜ Wrap all hard-coded UI strings in `self.tr()` / `QCoreApplication.translate()` across `NeuroCrunch.py` and `src/` modules
- ⬜ Re-generate `src/mainwindow.py` from the `.ui` file after marking strings translatable in Qt Designer
- ⬜ Create `translations/` folder; add initial `.ts` source files for `es` (Spanish, base) and `en` (English)
- ⬜ Add `lupdate`/`lrelease` commands to dev workflow (extract strings → compile to `.qm`)
- ⬜ Load `.qm` file at startup via `QTranslator` based on stored language preference (falls back to system locale, then Spanish)
- ⬜ Language selector in app settings (stored in user config); takes effect on next launch
- ⬜ Bundle all `.qm` files in `assets/translations/` and include in PyInstaller spec
- ⬜ Config localized labels — plugin authors can supply per-language overrides (see config standard below); app picks the best match at load time
- ⬜ CI/CD: add `lrelease` step before PyInstaller build so compiled `.qm` files are always up to date in the bundle

---

## Plugin / Script Standard

Every script — official or community — lives in its own subfolder and contains exactly two files: a `config.json` and a Python file named after the folder.

### `config.json`

```json
{
  "name": "Procesar Video",
  "description": "Extracts fluorescence traces from a calcium imaging video.",
  "version": "1.0.0",
  "author": "NeuroCrunch Team",
  "category": "preprocessing",
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

`id` is auto-derived from the folder name. `entry_point` is auto-derived as `<folder_name>.py`. Both are accepted in `config.json` but not required. `version` and `author` are optional.

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

### `<script_name>.py` — execution contract

Scripts define a single `run(params)` function. The app calls it directly in a worker thread — no subprocess, no JSON files to read or write.

```python
def run(params):
    """
    params: dict of all configured parameter values.
    Returns: dict whose keys match the 'outputs' declared in config.json.
    Use print() to send messages to the app log.
    Raise an exception to report an error — never call sys.exit().
    """
    input_csv  = params["input_csv"]
    output_dir = params["output_dir"]

    print("Loading data...")
    # ... use any bundled library freely ...

    return {"output_csv": f"{output_dir}/result.csv"}
```

For cooperative cancellation and progress reporting, accept an optional `ctx` argument — the runner detects it via `inspect.signature` and passes it automatically:

```python
def run(params, ctx):
    for i, item in enumerate(items):
        if ctx.is_cancelled():
            return {}
        ctx.progress(i / len(items) * 100)
        # ...
```

Or report progress with a plain `print`:

```python
print("PROGRESS:50")   # sets the progress bar to 50 %
```

**Rules**
- Never call `sys.exit()` — raise an exception instead
- Never call `os._exit()` — it terminates the entire application
- `if __name__ == "__main__":` blocks are ignored by the runner and can be kept for standalone CLI use

**Bundled libraries** (available to all scripts, no installation required):
`numpy`, `pandas`, `scipy`, `opencv-python`, `matplotlib`, `tifffile`, `scikit-image`, `read_roi`

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
- [x] ~~Script dependencies~~ — Scripts run in-process using the app's bundled Python; required libraries are bundled with the app and documented in the Plugin/Script Standard. New library requests go through a new app release.
- [ ] Confirm base/default language (currently Spanish — all existing strings are `es`)
- [ ] Which languages to ship in v1.0? Suggested: `es` (base) + `en`; others added by community via PR
- [ ] Language preference: per-user config file, or respect OS locale by default?
