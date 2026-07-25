# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""Locale-map helpers shared across NeuroCrunch.

Manifest strings (labels, descriptions, script/output names) may be either a
plain string or a ``{locale: string}`` map, e.g. ``{"en": "…", "es": "…"}``.
These two pure helpers resolve such a value to a single display string. Kept
Qt-free so both the GUI modules and the plugin manager can import them without
pulling in PySide6.
"""
from __future__ import annotations

from typing import Any, Dict


def localize(value: Any, fallback: str = '', language: str = 'en') -> str:
    """Resolve *value* (string or locale map) to a plain string.

    Preference order for a locale map is *language*, then English, then any
    available value, then *fallback*. ``None`` yields *fallback*; any other
    non-string type is coerced with ``str()``.
    """
    if value is None:
        return fallback
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get(language) or value.get('en') or next(iter(value.values()), fallback)
    return str(value)


def resolve_label(field: Dict[str, Any], key: str = 'label', language: str = 'en') -> str:
    """Return a human-readable string for *key* in *field*, handling locale maps.

    Falls back to the field's ``name`` when *key* is absent or its locale map is
    empty, so a labelled row always has *some* caption.
    """
    value = field.get(key)
    if value is None:
        return field.get('name', '')
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return (
            value.get(language) or value.get('en')
            or next(iter(value.values()), field.get('name', ''))
        )
    return str(value)
