# This Python file uses the following encoding: utf-8
"""NeuroCrunch - Plugin Manager

Discovers script plugins (bundled and user-installed), validates their
manifest.json against schemas/plugin_manifest.schema.json, and exposes them
as PluginInfo objects.

See README.md > "Plugin / Script Standard" for the manifest format.
"""
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import jsonschema
except ImportError:  # pragma: no cover - jsonschema is a declared dependency
    jsonschema = None

logger = logging.getLogger(__name__)

# Default location of the manifest JSON Schema, relative to this file.
DEFAULT_SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'schemas', 'plugin_manifest.schema.json'
)

MANIFEST_FILENAME = 'manifest.json'
REQUIRED_MANIFEST_FIELDS = ('id', 'name', 'description', 'version', 'author', 'category', 'entry_point')


@dataclass
class PluginInfo:
    """Metadata describing a discovered script plugin."""
    id: str
    name: str
    description: str
    version: str
    author: str
    category: str
    entry_point: str  # Absolute path to the script's entry point (e.g. main.py)
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    outputs: Dict[str, Any] = field(default_factory=dict)
    is_official: bool = True


class PluginManager:
    """Discovers and validates script plugins from bundled and user directories."""

    def __init__(self, schema_path: Optional[str] = None):
        self.schema_path = schema_path or DEFAULT_SCHEMA_PATH
        self._schema = None
        self.warnings: List[str] = []

    def discover_scripts(self, bundled_dir: Optional[str], user_dir: Optional[str] = None) -> Dict[str, PluginInfo]:
        """Scan bundled_dir and, optionally, user_dir for script subfolders.

        A subfolder is a valid plugin if it contains a manifest.json that
        validates against the plugin manifest JSON Schema, and its declared
        entry_point file exists. Invalid entries are skipped and a warning is
        logged (and recorded in self.warnings) explaining why.

        Scripts found in user_dir override bundled scripts with the same id,
        so users can shadow or upgrade an official script locally.

        Returns a dict mapping plugin id -> PluginInfo.
        """
        self.warnings = []
        discovered: Dict[str, PluginInfo] = {}

        for directory, is_official in ((bundled_dir, True), (user_dir, False)):
            if not directory or not os.path.isdir(directory):
                continue

            try:
                entries = sorted(os.listdir(directory))
            except PermissionError as e:
                self._warn(f'No se pudo leer la carpeta de scripts "{directory}": {e}')
                continue

            for entry in entries:
                entry_path = os.path.join(directory, entry)
                if not os.path.isdir(entry_path):
                    continue

                plugin_info = self._load_plugin(entry_path, is_official)
                if plugin_info is not None:
                    discovered[plugin_info.id] = plugin_info

        return discovered

    def _load_plugin(self, folder_path: str, is_official: bool) -> Optional[PluginInfo]:
        manifest_path = os.path.join(folder_path, MANIFEST_FILENAME)
        if not os.path.isfile(manifest_path):
            self._warn(f'Carpeta de script omitida (sin {MANIFEST_FILENAME}): "{folder_path}"')
            return None

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            self._warn(f'No se pudo leer el manifiesto "{manifest_path}": {e}')
            return None

        if not isinstance(manifest, dict):
            self._warn(f'Manifiesto inválido "{manifest_path}": se esperaba un objeto JSON.')
            return None

        if not self._validate_manifest(manifest, manifest_path):
            return None

        missing = [key for key in REQUIRED_MANIFEST_FIELDS if key not in manifest]
        if missing:
            self._warn(f'Manifiesto "{manifest_path}" incompleto, faltan campos: {", ".join(missing)}')
            return None

        entry_point_path = os.path.join(folder_path, manifest['entry_point'])
        if not os.path.isfile(entry_point_path):
            self._warn(f'Script omitido, entry_point no encontrado: "{entry_point_path}"')
            return None

        return PluginInfo(
            id=manifest['id'],
            name=manifest['name'],
            description=manifest['description'],
            version=manifest['version'],
            author=manifest['author'],
            category=manifest['category'],
            entry_point=os.path.abspath(entry_point_path),
            parameters=manifest.get('parameters', []),
            outputs=manifest.get('outputs', {}),
            is_official=is_official,
        )

    def _validate_manifest(self, manifest: dict, manifest_path: str) -> bool:
        schema = self._load_schema()
        if not schema or jsonschema is None:
            # No schema available (or jsonschema not installed): fall back to
            # the required-field check performed by the caller.
            return True

        try:
            jsonschema.validate(instance=manifest, schema=schema)
        except jsonschema.exceptions.ValidationError as e:
            self._warn(f'Manifiesto inválido "{manifest_path}": {e.message}')
            return False

        return True

    def _load_schema(self) -> dict:
        if self._schema is not None:
            return self._schema

        try:
            with open(self.schema_path, 'r', encoding='utf-8') as f:
                self._schema = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning('No se pudo cargar el schema de manifiestos "%s": %s', self.schema_path, e)
            self._schema = {}

        return self._schema

    def _warn(self, message: str) -> None:
        logger.warning(message)
        self.warnings.append(message)
