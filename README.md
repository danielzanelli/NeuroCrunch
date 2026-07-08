# NeuroCrunch

A desktop application for neuroscience data analysis. Provides a file browser, multi-format viewer (images, video, CSV plots, PDFs), and a scriptable processing pipeline where analysis scripts can be configured, chained, and executed from the UI.

Built with **PySide6 + pyqtgraph**, distributed as a cross-platform PyInstaller bundle.

---

## Current Status

Phases 1–8 are complete or substantially in progress. The full analysis pipeline is functional end-to-end with internationalization infrastructure in place.

### What works today:

- **File browser** — folder selection, recursive tree view, right-click context menu, refresh
- **Multi-format viewer** — images, CSV/Excel plots (pyqtgraph, column selector, regex filter, clickable legend), video playback with controls, PDF (QPdfView + QWebEngineView fallback), plain text
- **Dark mode** — toggle with external QSS stylesheets (`assets/styles/`)
- **Plugin manager** — discovers `config.json`-based plugins from bundled `scripts/` and the user plugins directory; validates against JSON Schema; auto-derives `id` and `entry_point` from folder name; user scripts shadow official ones by id
- **Parameter dialogs** — auto-generated from `config.json` parameter definitions; all 8 widget types (`string`, `int`, `float`, `bool`, `file`, `directory`, `choice`, `text`); linked parameter auto-fill from pipeline context; required-field validation; "Configurado" status indicator; translatable labels
- **Script runner** — in-process execution via `QThread` + `exec()` (no external Python needed); `StdoutCapture` for live log streaming with in-place `\r` progress updates; `PROGRESS:N` protocol drives a progress indicator; cooperative cancellation via `ScriptContext`; pipeline halts on first error
- **Logging panel** — timestamped log with progress-update-in-place support
- **Official scripts** — `procesar_video`, `quitar_bleaching`, `seleccionar_activas`, `matriz_pearson`, `generar_graficos` implemented on the `run(params)` standard; only `seleccionar_ROIs` (interactive) pending
- **Script template** — `scripts/template/` with all 8 parameter types documented alongside logging, progress, cancellation, and matplotlib usage examples
- **User scripts** — "Abrir Carpeta de Scripts" button opens the writable per-user plugins directory; drop a script folder in, then **Refrescar** re-scans and lists it (no restart)
- **Frozen build** — PyInstaller bundle collects all script dependencies and resolves bundled scripts via `sys._MEIPASS`
- **In-app updater** (Phase 6) — checks GitHub Releases; downloads and applies updates; silently skips on offline/rate-limit
- **CI/CD release pipeline** (Phase 7) — automatic builds on version tags; supports Windows (Inno Setup), macOS (.dmg), Linux (AppImage)
- **Internationalization** (Phase 8) — translation infrastructure with `.ts` source files (Spanish/English); build tool for `.qm`/`.qm.json` compilation; `QTranslator` loader; app-wide translatable strings; plugin manifest support for localized labels

### What is **not yet implemented**:

- 1 of 6 official scripts still a stub: `seleccionar_ROIs` — now scoped as an **algorithmic** batch
  script (automatic ROI detection with pre-configured parameters), not interactive drawing (Phase 9)
- Weighted network graph support: a `generar_grafo` producer script + an interactive graph viewer
  (Phase 10)
- Language selector UI dialog (deferred from Phase 8 — translation infrastructure complete, selector awaits preferences dialog)
- Qt Linguist GUI tool integration (deferred — Python build tool works; Linguist UI optional for larger projects)

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

> **Sequencing note.** Distribution infrastructure is being built before the remaining
> scripts. Phase 7 (CI/CD) is implemented **before** Phase 6 (Updater): the updater
> downloads what CI publishes, so real release assets must exist before it can be tested.
> The 4 stub scripts are tracked as **Phase 9**.

### Phase 0 — Build foundation (prerequisite for distribution)
- ✅ `requirements.txt`: added `tifffile`, `matplotlib`; pins reconciled to tested versions
- ✅ `neurocruncher.spec`: `collect_all` bundles the libraries the `exec()`-loaded scripts
  import (PyInstaller can't see them otherwise); QtWebEngine/QtPdf hidden imports; excludes
  competing Qt bindings (PyQt5/PyQt6/PySide2); tolerant of a missing icon
- ✅ Frozen build resolves bundled `scripts/` via `sys._MEIPASS` (fixes empty scripts table in the `.exe`)

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

*Implemented; the check/compare/asset-selection logic is unit-tested (`tests/test_updater.py`, 11 tests). The download + apply steps need a real GitHub Release to exercise end-to-end.*

- ✅ `UpdateChecker(QThread)` — on startup, `GET https://api.github.com/repos/{repo}/releases/latest`; compares `tag_name` with `version.json` (numeric, not lexical); emits `update_available(dict)` for newer releases, else `up_to_date`; failures are logged, not popped up
- ✅ Status-bar message + `QMessageBox` prompt when an update is available
- ✅ `UpdateDownloader(QThread)` — downloads the platform asset (`select_asset` matches the Phase 7 naming) to the per-user updates dir; progress reported via signal
- ✅ On download complete: `QMessageBox` prompts to restart; on confirm, `apply_update()` launches the asset and the app quits
- ✅ Per-OS apply: Windows runs the Inno installer silently (`/SILENT /CLOSEAPPLICATIONS`) — no separate launcher shim needed; Linux re-launches the AppImage; macOS opens the `.dmg`

### Phase 7 — CI/CD (`.github/workflows/build.yml`)

*Authored; pending a first tag-push to validate on GitHub's runners (can't be exercised locally).*

- ✅ Trigger: push to tags matching `v*.*.*`, plus `workflow_dispatch` for manual test builds
- ✅ Matrix: `windows-latest`, `macos-latest`, `ubuntu-latest`
- ✅ Steps: checkout → Python 3.13 → `pip install -r requirements.txt pyinstaller` → `pyinstaller neurocruncher.spec` → per-OS packaging → upload artifact → attach to GitHub Release (tag builds only)
- ✅ Per-OS packaging — PyInstaller freezes once; each OS wraps it natively:

  | OS | Packager | Asset |
  |---|---|---|
  | Windows | Inno Setup (`packaging/windows/NeuroCrunch.iss`) | `NeuroCrunch-{version}-windows-setup.exe` |
  | macOS | `.dmg` via `hdiutil` from the `.app` bundle | `NeuroCrunch-{version}-macos.dmg` |
  | Linux | AppImage (`packaging/linux/build_appimage.sh`) | `NeuroCrunch-{version}-linux.AppImage` |

- ✅ Version derived from the git tag (`vX.Y.Z` → `X.Y.Z`); update `version.json` before tagging
- Releases ship **unsigned** for now — see [Installing an unsigned build](#installing-an-unsigned-build)

### Phase 8 — Multilanguage Support (`translations/`)

The app now supports proper i18n using Qt's translation system. All hardcoded UI strings have been wrapped for translation.

- ✅ Wrap all hard-coded UI strings in `self.tr()` / `QCoreApplication.translate()` across `NeuroCrunch.py`
- ✅ Create `assets/translations/` folder with initial `.ts` source files for `es` (Spanish, base) and `en` (English)
- ✅ Add `build_translations.py` command to compile `.ts` → `.qm` (with fallback JSON format for development)
- ✅ Load `.qm` (or `.qm.json` fallback) at startup via `QTranslator` based on stored language preference
- ✅ Bundle all translation files in `assets/translations/` and include in PyInstaller spec
- ✅ Config localized labels support (already partial in `param_dialog.py`); plugin authors can supply per-language overrides
- ✅ CI/CD: add translation build step before PyInstaller
- 🔄 Language selector in app settings (UI hook ready; full implementation pending preferences dialog)
- ⬜ Re-generate `src/mainwindow.py` from `.ui` file with translatable strings (optional: improves UI designer workflow)

### Phase 9 — Complete the official scripts

The batch scripts follow the `run(params)` standard and preserve the trace-CSV format
(metadata columns `frame`/`tiempo_s` + per-cell signal columns like `123_mean`) so the
pipeline links resolve end-to-end.

- ✅ `seleccionar_activas` — keeps traces with an event ≥ `min_duracion` frames above a
  **robust** threshold (median + k·σ_MAD, so events don't inflate the baseline) → `active_csv`
- ✅ `matriz_pearson` — Pearson correlation matrix of the active traces + heatmap; reports
  pairs above `umbral_correlacion` → `matrix_csv`, `heatmap_png`
- ✅ `generar_graficos` — overlay, raster (cells × time), and mean±σ summary figures in the
  chosen format → `figures_dir`
- ⬜ `seleccionar_ROIs` — **algorithmic** ROI detection (no interactive drawing). Runs as a normal
  `run(params)` batch step: reads a representative frame (or a projection over the video), segments
  regions with pre-configured parameters (e.g. threshold / min-max area / blur), and exports an
  ImageJ-compatible `roi_zip` consumable by `procesar_video`. Detection quality and parameter
  polishing come later; the goal for this phase is a working end-to-end producer that fits the
  existing pipeline and links.
  > **Design decision.** All interactivity lives in the app viewer, never in scripts. Scripts stay
  > pure producers (`run(params)` → files); the user inspects and manipulates results by opening the
  > output files in the viewer (CSV, video/ROI, graph). This keeps every Qt/main-thread concern in
  > one place and lets community scripts stay headless. There is intentionally **no** "interactive
  > plugin" kind.

### Phase 10 — Weighted network graphs (producer script + interactive viewer)

Turn the correlation results into weighted connectivity networks the user can explore in the app.
Following the Phase 9 design decision, this splits cleanly into a headless **producer script** and an
interactive **viewer** that opens the file it emits — exactly the CSV / video-ROI pattern.

**Graph file format**
- ⬜ Adopt **JSON Graph Format (JGF)** for weighted networks: JSON, human-readable, has a published
  schema, and validates through the same `jsonschema` path as `config.json`. Written by hand from
  numpy/pandas — **no new heavy dependency** (no NetworkX/scipy) to keep the bundle lean.
- ⬜ `schemas/graph.schema.json` — JGF subset the app accepts; validated on open, invalid files
  rejected with a log message.
- ⬜ Dedicated extension (`.jgf` / `.graph.json`) **and** a top-level `graph`-key sniff so unrelated
  JSON is never handed to the graph view.

**`generar_grafo` producer script**
- ⬜ Builds a **functional connectivity graph** directly from `matriz_pearson`'s correlation matrix
  (`matrix_csv`): each neuron is a node, and each pair of neurons is joined by a weighted edge equal
  to their Pearson correlation. The purpose is to surface which neurons are **highly correlated**
  (co-active) — strong edges reveal the functionally connected groups. Edges below a base
  `umbral_correlacion` cutoff are dropped so only meaningful connections remain; edge weight carries
  the correlation strength (and sign) into the viewer's width/color styling.
- ⬜ Bakes per-node **layout positions** into node `metadata` (deterministic, so the viewer needs no
  layout engine); viewer falls back to a dependency-free circular layout when positions are absent.
- ⬜ Bakes per-node **hub metrics** (degree, weighted strength, and a simple centrality) into
  `metadata` so the viewer can color/size nodes without recomputation.
- ⬜ Emits `graph_jgf` as a declared output so it links downstream like the other scripts.

**Interactive graph viewer** (`show_graph()`, wired into `on_file_viewer_double_clicked`)
- ⬜ Render with `pyqtgraph.GraphItem` inside the existing `plot_frame` (already bundled; reuses the
  CSV-plot infrastructure and its show/hide panel logic).
- ⬜ Edge styling by weight — **width** = magnitude, **color** = sign (diverging map), **opacity** to
  de-emphasize near-threshold edges. (`GraphItem` accepts a per-edge pen array.)
- ⬜ Viewer controls mirroring the CSV viewer UX: a **weight-threshold** input (hide edges below |w|)
  and a **keyword filter** on node labels.
- ⬜ **Click a node** → highlight its strongest connections / neighbors; dim the rest.
- ⬜ **Color/size nodes by hub metric** (degree / strength / centrality) selectable in the viewer,
  read from the baked metadata.
- ⬜ Hover tooltip showing node id/label + degree and edge weight.

**Build / tests**
- ⬜ Confirm no new bundled dependency is required; if one is added, update `requirements.txt` **and**
  the `collect_all` list in `neurocruncher.spec`.
- ⬜ Tests: JGF schema validation, `generar_grafo` output shape/links, and threshold/filter logic.

> Scope note: this phase establishes the end-to-end producer→viewer path and the interaction set.
> Detection/graph-quality tuning and visual polish are follow-up work, not blockers for the phase.

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
`numpy`, `pandas`, `opencv-python` (`cv2`), `matplotlib`, `tifffile`, `read_roi`

> A script may only import libraries that are in `requirements.txt` **and** collected in
> `neurocruncher.spec` — otherwise it works from source but crashes in the frozen build.
> To add one (e.g. `scipy`, `scikit-image`), add it to both `requirements.txt` and the
> `collect_all` list in the spec. `scipy`/`scikit-image` are **not** bundled yet; they'll be
> added when the first script (e.g. `matriz_pearson`) needs them.

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

**Bundle size.** The spec trims the frozen build (~1.6 GB → ~0.75 GB): it drops unused
packages (`scipy` and dev tools), keeps only Spanish/English Qt translations, excludes
unused Qt modules, and **does not bundle QtWebEngine** (~290 MB). PDFs are rendered by
QtPdf (`QPdfView`); `NeuroCrunch.py` imports `QWebEngineView` optionally, so the old
WebEngine fallback is simply unavailable in frozen builds. If a PDF ever fails to render,
that dropped fallback is the reason — re-add `PySide6.QtWebEngine*` to the spec to restore it.

See `requirements.txt` for the full pinned dependency set (developed and tested on Python 3.13).

`src/mainwindow.py` is auto-generated from `ui/mainwindow.ui` by Qt's `uic` tool. Do not edit it by hand.

To regenerate after editing the `.ui` file:

```bash
pyside6-uic ui/mainwindow.ui -o src/mainwindow.py
```

---

## Installing an unsigned build

Releases are currently **unsigned**, so the OS will warn on first launch. This is expected; the workarounds:

- **Windows** — SmartScreen shows "Windows protected your PC". Click **More info → Run anyway**.
- **macOS** — Gatekeeper blocks unsigned apps ("NeuroCrunch is damaged / can't be opened"). Right-click the app → **Open** (then confirm), or clear the quarantine flag: `xattr -dr com.apple.quarantine /Applications/NeuroCrunch.app`.
- **Linux (AppImage)** — no gatekeeper. Make it executable and run: `chmod +x NeuroCrunch-*-linux.AppImage && ./NeuroCrunch-*-linux.AppImage`.

Signing (a Windows code-signing certificate and Apple notarization) can be added later to remove these warnings.

---

## Open Questions / Decisions Needed

- [x] ~~Confirm GitHub repo URL~~ — `version.json` → `"repo": "danielzanelli/NeuroCrunch"`
- [x] ~~Windows installer format~~ — Inno Setup installer (Windows), `.dmg` (macOS), AppImage (Linux); ship unsigned initially
- [ ] Script timeout policy: maximum allowed runtime per script before the runner kills it?
- [x] ~~Script dependencies~~ — Scripts run in-process using the app's bundled Python; required libraries are bundled with the app and documented in the Plugin/Script Standard. New library requests go through a new app release.
- [ ] Confirm base/default language (currently Spanish — all existing strings are `es`)
- [ ] Which languages to ship in v1.0? Suggested: `es` (base) + `en`; others added by community via PR
- [ ] Language preference: per-user config file, or respect OS locale by default?
