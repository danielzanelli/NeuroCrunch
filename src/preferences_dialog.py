# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""Preferences dialog for NeuroCrunch.

Currently exposes a single setting — the application language — but is the
natural home for future user preferences (persistence, UI options, etc.).
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QVBoxLayout,
    QWidget,
)


class PreferencesDialog(QDialog):
    """Small dialog letting the user pick the application language.

    Parameters
    ----------
    current_language:
        The language code currently active (e.g. ``"en"``).
    languages:
        Ordered sequence of ``(code, display_name)`` tuples to offer.
    parent:
        Parent widget (the main window).
    """

    def __init__(
        self,
        current_language: str,
        languages: Sequence[Tuple[str, str]],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._languages: List[Tuple[str, str]] = list(languages)

        self.setWindowTitle(QCoreApplication.translate('PreferencesDialog', 'Preferences'))
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.setContentsMargins(8, 8, 8, 8)
        form.setSpacing(8)

        self._combo = QComboBox()
        for code, label in self._languages:
            self._combo.addItem(label, code)
        idx = self._combo.findData(current_language)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        form.addRow(
            QCoreApplication.translate('PreferencesDialog', 'Language:'), self._combo
        )
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            QCoreApplication.translate('PreferencesDialog', 'Accept')
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            QCoreApplication.translate('PreferencesDialog', 'Cancel')
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_language(self) -> str:
        """Return the language code the user selected."""
        return self._combo.currentData()
