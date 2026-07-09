# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""JSON-backed QTranslator for NeuroCrunch.

Qt's normal translation path needs compiled binary ``.qm`` catalogs produced by
``lrelease``, which is not always available in the build environment. This
module provides a :class:`QTranslator` subclass that reads the human-editable
``assets/translations/neurocruncher_<lang>.json`` catalogs directly, so every
``QCoreApplication.translate`` call — and therefore every ``.tr()`` and every
auto-generated ``retranslateUi`` string — is translated without requiring Qt's
compiler.
"""
from __future__ import annotations

import json
import os
from typing import Dict

from PySide6.QtCore import QTranslator


class JsonTranslator(QTranslator):
    """A :class:`QTranslator` that resolves strings from a nested JSON catalog.

    The catalog shape matches ``neurocruncher_<lang>.json``::

        { "<context>": { "<source>": "<translation>", ... }, ... }
    """

    def __init__(self, data: Dict[str, Dict[str, str]], parent=None) -> None:
        super().__init__(parent)
        self._data = data or {}

    def translate(self, context, source_text, disambiguation=None, n=-1):
        entries = self._data.get(context)
        if entries:
            translated = entries.get(source_text)
            if translated:
                return translated
        # Returning None yields a null QString, which tells Qt "no translation
        # available; use the source text". Returning '' would instead render an
        # empty string, blanking out every untranslated label.
        return None

    def isEmpty(self) -> bool:
        return not self._data


def load_json_catalog(translations_dir: str, language: str) -> Dict[str, Dict[str, str]]:
    """Load ``neurocruncher_<language>.json`` from *translations_dir*.

    Returns an empty dict if the file is missing or malformed.
    """
    path = os.path.join(translations_dir, f'neurocruncher_{language}.json')
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
