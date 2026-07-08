# Translation Management Guide

NeuroCrunch uses Qt's translation system for multilingual support. This guide explains how to add, update, and maintain translations.

## Overview

- **Base language**: Spanish (`es`)
- **Translation files**: Located in `assets/translations/`
- **Format**: Qt Linguist `.ts` (XML) source files, compiled to `.qm` (binary) or `.json` (fallback)
- **Build tool**: `build_translations.py` (Python fallback; uses Qt's `lrelease` if available)

## Translation Files

### `.ts` Files (Translation Source)

These are human-editable XML files where translators add translations:
- `neurocruncher_es.ts` — Spanish (base/fallback)
- `neurocruncher_en.ts` — English

Each message is marked with its source location for easy tracing:

```xml
<message>
    <location filename="src/NeuroCrunch.py" line="192"/>
    <source>Seleccionar carpeta local</source>
    <translation>Select Local Folder</translation>
</message>
```

### `.qm` / `.qm.json` Files (Compiled Translations)

Generated from `.ts` files by the build process. These are what the app loads at runtime.

## Adding a New Translatable String

### 1. In Python Code

Use `QCoreApplication.translate()` or the `self.tr()` helper (if in `NeuroCrunch` class):

```python
# In NeuroCrunch class
message = self.tr('Hello, World!')

# In other modules
from PySide6.QtCore import QCoreApplication
message = QCoreApplication.translate('ClassName', 'Hello, World!')
```

The first argument to `translate()` is the **context** — typically the class name where the string appears. This helps organize translations and avoid collisions.

### 2. Rebuild Translation Files

Update the `.ts` files from the source code (requires Qt tools):

```bash
lupdate src/ -ts assets/translations/neurocruncher_*.ts
```

Or use the Python fallback (see below).

### 3. Add Translations

Edit the `.ts` files (e.g., `neurocruncher_en.ts`) and add `<translation>` elements for new strings:

```xml
<message>
    <location filename="src/NeuroCrunch.py" line="192"/>
    <source>Hello, World!</source>
    <translation>Hola, Mundo!</translation>
</message>
```

### 4. Compile

```bash
python build_translations.py
```

This generates `.qm.json` files (fallback format) in `assets/translations/`.

For production, install Qt tools and they will generate proper binary `.qm` files:

```bash
pip install PySide6
python build_translations.py
```

## Build Tool: `build_translations.py`

Compiles all `.ts` files in `assets/translations/` to `.qm` (or `.qm.json` if `lrelease` is unavailable).

### Usage

```bash
python build_translations.py
```

### Behavior

- **With Qt tools installed**: Generates binary `.qm` files using Qt's `lrelease` tool
- **Without Qt tools**: Falls back to JSON format (`.qm.json`), which is sufficient for development

The app loads whichever format is available: binary `.qm` is preferred, then `.qm.json`.

## Workflow: Adding a New Language

To add support for a new language (e.g., French):

### 1. Create a New `.ts` File

Copy `neurocruncher_en.ts` and rename to `neurocruncher_fr.ts`, then translate the strings.

### 2. Rebuild

```bash
python build_translations.py
```

This will generate `neurocruncher_fr.qm.json` (or `.qm` with Qt tools).

### 3. Update the App

Modify `NeuroCrunch.py` to set `self.current_language = 'fr'` (or add a language selector dialog).

### 4. Test

Run the app and verify strings appear in French.

## CI/CD Integration

The GitHub Actions workflow (`.github/workflows/build.yml`) automatically runs `build_translations.py` before creating release builds. This ensures the latest translations are always bundled.

To add `lrelease` to CI/CD for production-quality `.qm` files:

```yaml
- name: Install Qt tools
  run: pip install PySide6

- name: Build translations
  run: python build_translations.py
```

## Localized Config Labels

Plugin manifests can supply per-language parameter labels. See [README.md > Plugin / Script Standard > Localized labels](README.md#localized-labels).

Example:

```json
{
  "name": "fps",
  "type": "int",
  "label": {"es": "Frames por segundo", "en": "Frames per second"},
  "description": {"es": "Velocidad de muestreo", "en": "Sampling rate"}
}
```

The app automatically picks the best match for the active language.

## Future Work

- **Qt Linguist UI**: Use the graphical Qt Linguist tool for translation management
- **Plural handling**: Add support for context-aware pluralization (e.g., "1 file" vs. "2 files")
- **Community translations**: Accept translations via Pull Request
- **Language selector dialog**: Add a Settings/Preferences dialog to switch languages without restarting
