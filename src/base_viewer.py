# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""Protocol shared by every viewer that can live in a tab of the central pane.

Kept in its own module so both :mod:`viewers` and :mod:`graph_viewer` can
implement it without importing each other.
"""
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Signal

# Tabs can be closed while their file is still loading, so the loader threads
# must outlive the viewer that started them instead of being collected mid-run.
_PENDING_WORKERS = set()


def keep_alive_until_finished(worker):
    """Hold a reference to *worker* (a detached QThread) until it finishes."""
    _PENDING_WORKERS.add(worker)
    worker.finished.connect(lambda: _PENDING_WORKERS.discard(worker))


class BaseViewer(QWidget):
    """One open file: owns its widgets, its data and its resources.

    Subclasses implement :meth:`load` and override only the hooks they need.
    The host window connects the signals to the log and calls the hooks on tab
    activation, theme/language changes and tab close.
    """

    progress_changed = Signal(str)   # live progress line (replaces the last log line)
    load_done = Signal(bool, str)    # (success, already-translated log line)
    log_message = Signal(str)        # any other already-translated log line

    def load(self, file_path: str) -> None:
        """Display *file_path*. Errors are reported through ``load_done``."""
        raise NotImplementedError

    def apply_theme(self, is_dark: bool) -> None:
        """Re-colour anything Qt stylesheets cannot reach (plots, icons)."""

    def retranslate(self) -> None:
        """Re-apply translations to labels built from code."""

    def on_activated(self) -> None:
        """This tab became the current one."""

    def on_deactivated(self) -> None:
        """Another tab became the current one."""

    def release(self) -> None:
        """Stop timers/players before the widget is destroyed."""
