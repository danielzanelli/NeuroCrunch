# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""Self-contained viewers for the central tab area.

Each class here previews exactly one file and owns every widget and every piece
of state that file needs, so several of them can live side by side as tabs. They
all implement the :class:`~base_viewer.BaseViewer` protocol, as does
:class:`~graph_viewer.GraphViewer`. :func:`viewer_for` maps a path to the right
class.
"""
import os
import re
import struct
import zipfile

import numpy as np
import pandas as pd
import pyqtgraph as pg
import read_roi

from PySide6.QtCore import (
    QCoreApplication, QEvent, QLoggingCategory, QPoint, QRectF, QThread, QTimer,
    QUrl, Qt, Signal
)
from PySide6.QtGui import (
    QBrush, QColor, QImage, QKeySequence, QPainter, QPen, QPixmap, QPolygon, QShortcut
)
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QProxyStyle, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QStyle,
    QTabWidget, QTextBrowser, QVBoxLayout, QWidget
)
try:
    # Optional: QtWebEngine is a ~290 MB dependency used only as a PDF-viewer
    # fallback. The primary PDF path is QPdfView (QtPdf).
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineView = None

import icon_loader
from base_viewer import BaseViewer, keep_alive_until_finished
from graph_viewer import GraphViewer
from param_dialog import ParamForm
from script_runner import load_script_callable


MAX_PLOT_COLUMNS = 100  # Maximum number of columns allowed to plot at once

# The ALS calibration preview solves a dense linear system per iteration (cost
# grows with the cube of the length), so each trace is decimated to this many
# points before it is handed to the script's preview() function.
MAX_PREVIEW_POINTS = 800
# Preview runs on every displayed trace; cap how many so a manual run stays
# a few seconds even on a wide selection.
PREVIEW_MAX_TRACES = 12

# Sentinel series key for the untransformed input trace in the Filter-preview
# series selector, kept distinct from any name a script's preview() may return.
_PREVIEW_ORIGINAL = '__original__'

# pyqtgraph backgrounds matched to the viewer_frame color in each QSS theme
PLOT_BG = {True: '#1a1e23', False: '#ffffff'}
PLOT_AXIS = {True: '#9aa3ad', False: '#66707c'}

# Categorical palette validated for >=3:1 contrast on both the dark (#1a1e23)
# and light (#ffffff) plot surfaces; fixed slot order.
PLOT_COLOR_PALETTE = [
    '#3987e5', '#199e70', '#c98500', '#008300',
    '#9085e9', '#e66767', '#d55181', '#d95926',
]

IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.bmp', '.gif')
DATA_SUFFIXES = ('.csv', '.xls', '.xlsx')
VIDEO_SUFFIXES = ('.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.mpeg', '.mpg',
                  '.webm', '.tif', '.tiff')


def _tr(text: str) -> str:
    """Translate against the 'NeuroCrunch' context.

    These strings were moved out of NeuroCrunch.py, so keeping their original
    context means the existing translation catalogs still match them.
    """
    return QCoreApplication.translate('NeuroCrunch', text)


def _tr_csv(text: str) -> str:
    """Translate a CSVReaderWorker progress string."""
    return QCoreApplication.translate('CSVReaderWorker', text)


class ImageViewer(BaseViewer):
    """Shows a still image, rescaled to the tab as the window resizes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        # The scaled pixmap must not feed back into the layout: without this it
        # becomes the label's sizeHint and each resize grows the label (and the
        # window) a little more. Ignored policy lets the layout drive the size.
        self.image_label.setMinimumSize(1, 1)
        self.image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        layout.addWidget(self.image_label)

    def load(self, file_path):
        self._pixmap = QPixmap(file_path)
        if self._pixmap.isNull():
            self._pixmap = None
            self.load_done.emit(False, _tr('Error opening the file:\n{0}').format(
                os.path.basename(file_path)))
            return
        self._rescale()
        # The label may not have its final size until the layout settles, so
        # rescale again on the next event-loop tick; otherwise the first image
        # appears tiny instead of filling the viewer.
        QTimer.singleShot(0, self._rescale)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self):
        """Rescale the stored pixmap to the current label size."""
        if self._pixmap is None or self._pixmap.isNull():
            return
        self.image_label.setPixmap(self._pixmap.scaled(
            self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))


class TextViewer(BaseViewer):
    """Shows a file as plain text (the fallback for unknown extensions)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.text_browser = QTextBrowser()
        layout.addWidget(self.text_browser)

    def load(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.text_browser.setPlainText(f.read())
        except Exception as e:
            self.load_done.emit(False, _tr('Error loading text file:\n{0}').format(str(e)))


class CSVReaderWorker(QThread):
    """Worker thread to read CSV files with progress reporting."""
    progress_updated = Signal(str)  # Signal to update progress
    data_loaded = Signal(object)  # Signal when data is loaded
    error_occurred = Signal(str)  # Signal when error occurs

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        """Run in background thread."""
        try:
            filename = os.path.basename(self.file_path)
            self.progress_updated.emit(_tr_csv('Opening CSV {0}: {1}%').format(filename, 0))

            if self.file_path.lower().endswith('.csv'):
                # Count total lines upfront so progress can be calculated correctly
                with open(self.file_path, 'rb') as f:
                    total_lines = sum(1 for _ in f) - 1  # subtract header row

                chunk_size = max(total_lines // 100, 200)
                chunk_size = min(chunk_size, 10000)

                chunks = []
                loaded_rows = 0
                for chunk in pd.read_csv(self.file_path, chunksize=chunk_size):
                    chunks.append(chunk)
                    loaded_rows += len(chunk)
                    progress = min(int((loaded_rows / max(total_lines, 1)) * 100), 100)
                    self.progress_updated.emit(
                        _tr_csv('Opening CSV {0}: {1}%').format(filename, progress))

                if chunks:
                    data = pd.concat(chunks, ignore_index=True)
                else:
                    data = pd.read_csv(self.file_path)

            elif self.file_path.lower().endswith(('.xls', '.xlsx')):
                self.progress_updated.emit(_tr_csv('Opening file {0}: {1}%').format(filename, 0))
                data = pd.read_excel(self.file_path)
                self.progress_updated.emit(_tr_csv('Opening file {0}: {1}%').format(filename, 100))
            else:
                raise ValueError('File format not supported for charts.')

            self.data_loaded.emit(data)
        except Exception as e:
            self.error_occurred.emit(str(e))


class _PreviewWorker(QThread):
    """Runs a script's pure ``preview(sample, params)`` on each trace off the UI
    thread.

    *samples* is ``{column_name: 1-D array}``; the result is
    ``{column_name: {series_name: array}}``. A monotonically increasing *token*
    lets the viewer discard a superseded run's result.
    """

    progress = Signal(int, int, int)  # token, done, total
    done = Signal(int, object)        # token, {col: result dict}
    failed = Signal(int, str)         # token, error message

    def __init__(self, preview_fn, samples, params, token, parent=None):
        super().__init__(parent)
        self._preview_fn = preview_fn
        self._samples = samples
        self._params = params
        self._token = token

    def run(self):
        try:
            out = {}
            total = len(self._samples)
            for i, (name, y) in enumerate(self._samples.items(), start=1):
                result = self._preview_fn({'y': y}, self._params)
                if isinstance(result, dict) and result:
                    out[name] = result
                self.progress.emit(self._token, i, total)
            self.done.emit(self._token, out)
        except Exception as e:  # noqa: BLE001 - surfaced to the log
            self.failed.emit(self._token, str(e))


class PlotViewer(BaseViewer):
    """Plots columns of a CSV/Excel file, with a tabbed column selector below."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = None
        self.file_path = None             # path of the CSV/Excel currently shown
        self._reader = None
        self._plot_items = {}
        self._signal_col_by_key = {}
        self._plot_menu_widget = None
        self._is_dark = True
        self._displayed_columns = []      # columns from the last plot (preview input)

        # Calibration tab state, injected by the host via
        # set_calibration_context(). Empty by default so a plain CSV shows no
        # preview tab.
        self._calib_plugins = []          # PluginInfo objects with a 'traces' calibration
        self._calib_apply_cb = None       # host callback: (script_id, values) -> None
        self._calib_saved_values = {}     # {script_id: saved param values}
        self._calib_language = 'en'
        self._calib_form = None           # current ParamForm
        self._calib_scroll = None         # scroll area the ParamForm lives in
        self._calib_script_combo = None
        self._calib_status = None
        self._preview_fn_cache = {}       # {script_id: preview callable or None}
        self._preview_worker = None
        self._preview_token = 0
        self._preview_idx = None          # shared x-axis (frame indices) of the run
        self._preview_raw_map = {}        # {column: decimated raw values}
        self._preview_result = {}         # {column: {series_name: array}} of the last run
        self._preview_series_state = {}   # {series_key: checked} persisted across runs
        self._preview_series_checks = {}  # {series_key: QCheckBox} current widgets
        self._preview_series_layout = None  # grid holding the series checkboxes
        self._preview_series_box = None   # container widget (hidden until a run)
        self._showing_preview = False     # True when the plot shows a preview, not columns

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.plot_widget, 1)

    def load(self, file_path):
        # Load data in background thread with progress reporting
        self.file_path = file_path
        self._reader = CSVReaderWorker(file_path)
        # Queued (the default across threads): let the reader push progress
        # without blocking on the GUI slot for every tick.
        self._reader.progress_updated.connect(self._on_reader_progress)
        self._reader.data_loaded.connect(self._on_csv_loaded)
        self._reader.error_occurred.connect(self._on_csv_error)
        keep_alive_until_finished(self._reader)
        self._reader.start()

    def set_calibration_context(self, plugins, apply_cb, saved_values_by_id, language='en'):
        """Enable the "Calibration" tab for the given calibratable *plugins*.

        Injected by the host so ``viewers`` stays decoupled from the plugin
        system. *plugins* is a list of PluginInfo objects whose manifest declares
        ``calibration.kind == 'traces'``; *apply_cb* is ``(script_id, values)``
        called when the user clicks "Apply to pipeline"; *saved_values_by_id*
        seeds the knobs from the pipeline config — it may be a
        ``{script_id: {param: value}}`` dict or a zero-arg callable returning one,
        so the form reflects the script's *current* configuration each time it is
        (re)built. A no-op (no tab) when *plugins* is empty.
        """
        self._calib_plugins = list(plugins or [])
        self._calib_apply_cb = apply_cb
        self._calib_saved_values = saved_values_by_id or {}
        self._calib_language = language or 'en'
        self._preview_fn_cache = {}
        # If the CSV is already loaded, rebuild the menu so the tab appears now.
        if self.data is not None:
            self._rebuild_plot_menu()

    def refresh_calibration(self):
        """Re-read configured params into the Filter-preview form after a config load.

        Called by the host when a new pipeline config is loaded at runtime.
        Rebuilds the knob form so it shows the newly loaded values (the saved-values
        provider reads live config), and re-runs the preview when one is currently
        on screen so the plot follows the new config too.
        """
        if self._calib_scroll is None:
            return  # the Filter-preview tab was never built (no calibratable script)
        self._rebuild_calib_form()
        if self._showing_preview and self._preview_raw_map:
            self._run_preview()

    def set_calibration_language(self, language):
        """Update the language used for calibration widget labels.

        Called by the host on a runtime language change, before ``retranslate``
        rebuilds the menu, so the knob labels follow the new language too.
        """
        self._calib_language = language or 'en'

    def apply_theme(self, is_dark):
        self._is_dark = is_dark
        self.plot_widget.setBackground(PLOT_BG[is_dark])
        plot_item = self.plot_widget.getPlotItem()
        for side in ('bottom', 'left'):
            plot_item.getAxis(side).setPen(pg.mkPen(color=PLOT_AXIS[is_dark], width=1))
            plot_item.getAxis(side).setTextPen(pg.mkPen(color=PLOT_AXIS[is_dark]))

    def retranslate(self):
        # The column selector is built from code, so rebuild it to pick up the
        # new language (no-op when no file is loaded yet).
        self._rebuild_plot_menu()

    def _on_reader_progress(self, message):
        self.progress_changed.emit(message)

    def _on_csv_error(self, error_msg):
        self.load_done.emit(False, _tr('Error loading data for chart:\n{0}').format(error_msg))

    def _on_csv_loaded(self, data):
        """Handle CSV loaded from background thread."""
        self.data = data
        self.load_done.emit(True, _tr('Loaded: {0} rows, {1} columns').format(
            len(data), len(data.columns)))
        self._rebuild_plot_menu()
        # Prefer the Neuron Selection plot when the file's columns match the
        # neuron/metric convention; otherwise fall back to plotting every column.
        if self._signal_col_by_key:
            self.plot_selected_neurons()
        else:
            self.plot_data()

    def _rebuild_plot_menu(self):
        """(Re)build the tabbed column selector below the plot for self.data.

        Called on load and on a language change. The active tab is kept.
        """
        if self.data is None:
            return

        # Default to the Neuron Selection tab (index 0) on first build; keep the
        # user's active tab across rebuilds (language change).
        active_tab = 0
        if self._plot_menu_widget is not None:
            active_tab = self._plot_menu_widget.currentIndex()
            self._plot_menu_widget.setParent(None)
            self._plot_menu_widget.deleteLater()
            self._plot_menu_widget = None

        self._plot_menu_widget = self._build_plot_menu()
        self._plot_menu_widget.setCurrentIndex(active_tab)
        self.layout().addWidget(self._plot_menu_widget)

    def _build_plot_menu(self):
        """Build the tabbed column selector shown below the plot.

        Two tabs, both vertically stacked so they stay usable on small screens:
        a *Neuron Selection* tab that picks columns by neuron id and metric, and
        a *Regex* tab (column range + substring filter).
        """
        tabs = QTabWidget(self)
        tabs.addTab(self._build_neuron_tab(), _tr('Neuron Selection'))
        tabs.addTab(self._build_regex_tab(), _tr('Plot Columns'))
        # A calibratable script (e.g. the ALS filter) adds a live preview tab.
        if self._calib_plugins:
            tabs.addTab(self._build_filter_preview_tab(), _tr('Calibration'))
        # Hug the content vertically so the plot keeps the rest of the tab.
        tabs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        return tabs

    def _tab_layout(self, tab):
        """A tight vertical layout so the selector stays as small as possible."""
        tab.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        v = QVBoxLayout(tab)
        v.setContentsMargins(4, 3, 4, 3)
        v.setSpacing(3)
        return v

    def _columns_desc_label(self):
        """Compact one-line 'total / maximum allowed' caption shared by both tabs."""
        total_columns = len(self.data.columns)
        max_selectable = min(MAX_PLOT_COLUMNS, total_columns)
        return QLabel(_tr('Total columns: {0} · Maximum allowed: {1}').format(
            total_columns, max_selectable))

    def _build_regex_tab(self):
        """Range + substring column selector (the original plotting controls)."""
        total_columns = len(self.data.columns)

        tab = QWidget()
        v = self._tab_layout(tab)
        v.addWidget(self._columns_desc_label())

        # A grid keeps the row labels and inputs aligned in columns.
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)  # inputs expand to fill the width

        # Regex finder for column names
        self.regex_input = QLineEdit()
        self.regex_input.returnPressed.connect(self.plot_data)
        grid.addWidget(QLabel(_tr('Columns that include:')), 0, 0)
        grid.addWidget(self.regex_input, 0, 1)

        # Start column spinbox. This tab is the fallback for unrecognised
        # formats, so default to every column (including the first).
        self.start_spin = QSpinBox()
        self.start_spin.setMinimum(0)
        self.start_spin.setMaximum(total_columns - 1)
        self.start_spin.setValue(0)
        self.start_spin.lineEdit().returnPressed.connect(self.plot_data)
        grid.addWidget(QLabel(_tr('Start column:')), 1, 0)
        grid.addWidget(self.start_spin, 1, 1)

        # End column spinbox
        self.end_spin = QSpinBox()
        self.end_spin.setMinimum(0)
        self.end_spin.setMaximum(total_columns - 1)
        self.end_spin.setValue(total_columns - 1)
        self.end_spin.lineEdit().returnPressed.connect(self.plot_data)
        grid.addWidget(QLabel(_tr('End column:')), 2, 0)
        grid.addWidget(self.end_spin, 2, 1)

        v.addLayout(grid)

        plot_btn = QPushButton(_tr('Plot'))
        plot_btn.clicked.connect(self.plot_data)
        v.addWidget(plot_btn)
        return tab

    def _build_neuron_tab(self):
        """Pick columns by neuron id and metric, parsed from the column names."""
        metrics, neurons = self._parse_signal_columns()

        tab = QWidget()
        v = self._tab_layout(tab)

        self.metric_checks = {}
        if not self._signal_col_by_key:
            v.addWidget(QLabel(_tr(
                'No neuron/metric columns were recognised in this file.')))
            return tab

        v.addWidget(self._columns_desc_label())
        v.addWidget(QLabel(_tr('Found {0} metrics and {1} neurons.').format(
            len(metrics), len(neurons))))

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)

        # Metrics: one checkbox each, in a compact 3-column grid so many metrics
        # don't overflow the width on small screens. Default to a single metric
        # (a 'Mean' column, matched case-insensitively, otherwise the first) to
        # keep the initial plot legible.
        default_metric = next(
            (m for m in metrics if m.lower() == 'mean'), metrics[0] if metrics else None)
        grid.addWidget(QLabel(_tr('Metrics:')), 0, 0, Qt.AlignTop)
        metrics_box = QWidget()
        metrics_grid = QGridLayout(metrics_box)
        metrics_grid.setContentsMargins(0, 0, 0, 0)
        metrics_grid.setHorizontalSpacing(8)
        metrics_grid.setVerticalSpacing(1)
        for i, m in enumerate(metrics):
            cb = QCheckBox(m)
            cb.setChecked(m == default_metric)
            self.metric_checks[m] = cb
            metrics_grid.addWidget(cb, i // 3, i % 3)
        grid.addWidget(metrics_box, 0, 1)

        # Neurons: a free-text list of ids and/or ranges (blank = every neuron).
        # Default to the first five neurons so the initial plot stays readable.
        self.neuron_input = QLineEdit()
        self.neuron_input.setText('1-5')
        self.neuron_input.setPlaceholderText(_tr('e.g. 22, 223, 627 or 1-10 (blank = all)'))
        self.neuron_input.returnPressed.connect(self.plot_selected_neurons)
        grid.addWidget(QLabel(_tr('Neurons:')), 1, 0)
        grid.addWidget(self.neuron_input, 1, 1)

        v.addLayout(grid)

        plot_btn = QPushButton(_tr('Plot'))
        plot_btn.clicked.connect(self.plot_selected_neurons)
        v.addWidget(plot_btn)
        return tab

    def _parse_signal_columns(self):
        """Map column names to (metric, neuron-id) pairs.

        Recognises the two conventions the pipeline emits: 'Metric<idx>' (e.g.
        ``Mean123``) and '<idx>_metric' (e.g. ``667_Max``). Fills
        ``self._signal_col_by_key`` with {(metric, idx): column_name} and returns
        (sorted metric names, sorted neuron ids). Columns matching neither
        pattern (``frame``, ``time_s``, ...) are ignored.
        """
        metric_first = re.compile(r'^([a-zA-Z_]+?)(\d+)$')
        index_first = re.compile(r'^(\d+)_([a-zA-Z_]+)$')
        col_by_key = {}
        metrics = set()
        neurons = set()
        for col in self.data.columns:
            name = str(col).strip()
            m = metric_first.match(name)
            if m:
                metric, idx = m.group(1), int(m.group(2))
            else:
                m = index_first.match(name)
                if not m:
                    continue
                idx, metric = int(m.group(1)), m.group(2)
            col_by_key[(metric, idx)] = col
            metrics.add(metric)
            neurons.add(idx)
        self._signal_col_by_key = col_by_key
        return sorted(metrics), sorted(neurons)

    def plot_data(self):
        """Plot columns chosen in the Regex tab (range + substring filter)."""
        try:
            # Get column range from spinboxes
            start_col = self.start_spin.value()
            end_col = self.end_spin.value()

            columns_to_plot = list(self.data.columns[start_col:end_col+1])

            # Filter columns by "regex" input (simple substring match)
            regex_filter = self.regex_input.text().strip()
            if regex_filter:
                columns_to_plot = [col for col in columns_to_plot if regex_filter in str(col)]

            self._plot_columns(columns_to_plot)
        except Exception as e:
            self.log_message.emit(_tr('Error loading data for chart:\n{0}').format(str(e)))
            self.plot_widget.clear()

    def plot_selected_neurons(self):
        """Plot columns chosen in the Neuron Selection tab (neuron ids x metrics)."""
        try:
            selected_metrics = [m for m, cb in self.metric_checks.items() if cb.isChecked()]
            if not selected_metrics:
                self.log_message.emit(_tr('Select at least one metric to plot.'))
                return

            text = self.neuron_input.text().strip()
            if text:
                neuron_ids = self._parse_neuron_ids(text)
            else:
                neuron_ids = sorted({idx for _, idx in self._signal_col_by_key})

            # Group by neuron so each neuron's metrics stay together in the legend.
            columns_to_plot = []
            missing = []
            for n in neuron_ids:
                cols = [self._signal_col_by_key[(m, n)]
                        for m in selected_metrics if (m, n) in self._signal_col_by_key]
                if cols:
                    columns_to_plot.extend(cols)
                else:
                    missing.append(n)

            if missing:
                self.log_message.emit(_tr('No data for neuron(s): {0}').format(
                    ', '.join(str(n) for n in missing)))

            if not columns_to_plot:
                self.log_message.emit(_tr('No matching neuron/metric columns to plot.'))
                self.plot_widget.clear()
                return

            self._plot_columns(columns_to_plot)
        except Exception as e:
            self.log_message.emit(_tr('Error loading data for chart:\n{0}').format(str(e)))
            self.plot_widget.clear()

    def _parse_neuron_ids(self, text):
        """Parse '1, 2, 5-8' into an ordered, de-duplicated list of neuron ids.

        Accepts single ids and inclusive ranges ('a-b', either order); unknown
        tokens are skipped with a note.
        """
        ids = []
        seen = set()
        for tok in re.split(r'[\s,;]+', text.strip()):
            if not tok:
                continue
            rng = re.match(r'^(\d+)\s*-\s*(\d+)$', tok)
            if rng:
                lo, hi = int(rng.group(1)), int(rng.group(2))
                seq = range(min(lo, hi), max(lo, hi) + 1)
            elif tok.isdigit():
                seq = (int(tok),)
            else:
                self.log_message.emit(_tr("Ignoring invalid neuron id: '{0}'").format(tok))
                continue
            for n in seq:
                if n not in seen:
                    seen.add(n)
                    ids.append(n)
        return ids

    def _time_axis(self):
        """Return ``(column_name, x_array)`` for a ``time_s`` column, else ``(None, None)``.

        When the CSV carries an explicit time base it drives the x-axis of every
        trace instead of the default sample index.
        """
        for col in self.data.columns:
            if str(col).strip().lower() == 'time_s':
                x = pd.to_numeric(self.data[col], errors='coerce').to_numpy(dtype=float)
                return col, x
        return None, None

    def _plot_columns(self, columns_to_plot):
        """Render *columns_to_plot* as lines with a clickable, toggleable legend."""
        self._showing_preview = False
        try:
            # A 'time_s' column defines the shared x-axis; never plot it as a trace.
            time_col, x = self._time_axis()
            if time_col is not None:
                columns_to_plot = [c for c in columns_to_plot if c != time_col]
            self.plot_widget.setLabel('bottom', str(time_col) if time_col is not None else '')

            capped = len(columns_to_plot) > MAX_PLOT_COLUMNS
            columns_to_plot = columns_to_plot[:MAX_PLOT_COLUMNS]
            if capped:
                self.log_message.emit(_tr('Plotting the first {0} columns only.').format(
                    MAX_PLOT_COLUMNS))

            # Clear previous plot and legend
            self.plot_widget.clear()
            self._plot_items = {}
            # Remember what's on screen so the Filter-preview tab can calibrate
            # against exactly these traces.
            self._displayed_columns = list(columns_to_plot)

            # Create a legend (ensure a single legend is used for this plot)
            try:
                legend = self.plot_widget.addLegend()
            except Exception as e:
                self.log_message.emit(_tr(
                    'Warning: Could not create the interactive legend:\n{0}').format(str(e)))
                legend = None

            # Plot selected columns and save references
            for i, column in enumerate(columns_to_plot):
                pen = pg.mkPen(PLOT_COLOR_PALETTE[i % len(PLOT_COLOR_PALETTE)], width=2)
                if x is not None:
                    y = pd.to_numeric(self.data[column], errors='coerce').to_numpy(dtype=float)
                    plot_item = self.plot_widget.plot(x, y, pen=pen, name=str(column))
                else:
                    plot_item = self.plot_widget.plot(self.data[column], pen=pen, name=str(column))
                # store by column name for toggling
                self._plot_items[str(column)] = plot_item

            # Make legend entries clickable to toggle visibility
            self._attach_clickable_legend(legend)
        except Exception as e:
            self.log_message.emit(_tr('Error loading data for chart:\n{0}').format(str(e)))
            self.plot_widget.clear()

    def _attach_clickable_legend(self, legend):
        """Make each legend entry toggle its curve's visibility on click.

        Entries are matched to ``self._plot_items`` by their label text, so both
        the column plots and the calibration preview series can be toggled the
        same way. Best-effort — silently skips if the pyqtgraph legend API differs.
        """
        if legend is None:
            return
        try:
            for sample, label in list(legend.items):  # (sample, label) pairs
                try:
                    label_text = str(label.text)
                except Exception:
                    try:
                        label_text = str(label.toPlainText())
                    except Exception:
                        label_text = None
                if not label_text:
                    continue

                def make_toggle(name, lab, samp):
                    def _toggle(event):
                        item = self._plot_items.get(name)
                        if item is None:
                            return
                        visible = not item.isVisible()
                        item.setVisible(visible)
                        try:
                            lab.setOpacity(1.0 if visible else 0.4)
                        except Exception:
                            pass
                        try:
                            samp.setOpacity(1.0 if visible else 0.25)
                        except Exception:
                            pass
                    return _toggle

                try:
                    handler = make_toggle(label_text, label, sample)
                    sample.mousePressEvent = handler
                    label.mousePressEvent = handler
                except Exception:
                    pass
        except Exception:
            # Non-fatal: continue without a clickable legend.
            pass

    # ------------------------------------------------------------------
    # Calibration tab (interactive parameter tuning)
    # ------------------------------------------------------------------

    def _build_filter_preview_tab(self):
        """Tab that tunes a calibratable script against the displayed traces.

        Renders the script's numeric knobs (in a compact scroll area so the plot
        stays large) and, on the *Preview* button, runs the script's ``preview()``
        on every currently displayed trace and overlays the result. "Apply to
        pipeline" writes the tuned values back to the pipeline config.
        """
        tab = QWidget()
        v = self._tab_layout(tab)

        # Script row: which calibratable script to tune.
        self._calib_script_combo = QComboBox()
        for pinfo in self._calib_plugins:
            self._calib_script_combo.addItem(str(pinfo.name), pinfo.id)
        self._calib_script_combo.currentIndexChanged.connect(self._on_calib_script_changed)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(QLabel(_tr('Script:')))
        row.addWidget(self._calib_script_combo, 1)
        v.addLayout(row)

        # Parameters and the controls sit side by side: the knobs are crowded
        # vertically but there is spare width, so the action buttons and the
        # series checkboxes stack in a single column to the right of the inputs.
        mid_row = QHBoxLayout()
        mid_row.setContentsMargins(0, 0, 0, 0)
        mid_row.setSpacing(8)

        # Parameters live in a short scroll area so many knobs don't push the
        # plot off screen.
        self._calib_scroll = QScrollArea()
        self._calib_scroll.setWidgetResizable(True)
        self._calib_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._calib_scroll.setMaximumHeight(150)
        mid_row.addWidget(self._calib_scroll, 1)

        # Right column: the two action buttons stacked over the series selector.
        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(4)

        preview_btn = QPushButton(_tr('Preview'))
        preview_btn.clicked.connect(self._run_preview)
        right_col.addWidget(preview_btn)
        apply_btn = QPushButton(_tr('Apply to Config'))
        apply_btn.clicked.connect(self._on_calib_apply)
        right_col.addWidget(apply_btn)

        # Series selector: which of the script's preview outputs to draw. The
        # available series come from the script's result, so this stays hidden
        # until the first Preview run populates it.
        self._preview_series_checks = {}
        self._preview_series_box = QWidget()
        box_v = QVBoxLayout(self._preview_series_box)
        box_v.setContentsMargins(0, 0, 0, 0)
        box_v.setSpacing(2)
        box_v.addWidget(QLabel(_tr('Series to plot:')))
        self._preview_series_layout = QVBoxLayout()
        self._preview_series_layout.setContentsMargins(0, 0, 0, 0)
        self._preview_series_layout.setSpacing(1)
        box_v.addLayout(self._preview_series_layout)
        self._preview_series_box.setVisible(False)
        right_col.addWidget(self._preview_series_box)
        right_col.addStretch(1)
        mid_row.addLayout(right_col, 0)
        v.addLayout(mid_row)

        # Status line spans the full width below both columns so it stays legible.
        self._calib_status = QLabel('')
        self._calib_status.setStyleSheet('color: #888888; font-size: 10px;')
        self._calib_status.setWordWrap(True)
        v.addWidget(self._calib_status)

        self._rebuild_calib_form()
        return tab

    def _series_label(self, key):
        """Human label for a preview series key (the raw trace reads 'Original')."""
        if key == _PREVIEW_ORIGINAL:
            return _tr('Original')
        return key[:1].upper() + key[1:]

    def _rebuild_series_checks(self, ordered_keys):
        """Populate the series selector with one checkbox per available preview
        output, preserving each series' prior checked state across runs."""
        if self._preview_series_layout is None:
            return
        while self._preview_series_layout.count():
            item = self._preview_series_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._preview_series_checks = {}
        for key in ordered_keys:
            cb = QCheckBox(self._series_label(key))
            cb.setChecked(self._preview_series_state.get(key, True))
            cb.toggled.connect(lambda checked, k=key: self._on_series_toggled(k, checked))
            self._preview_series_checks[key] = cb
            self._preview_series_layout.addWidget(cb)
        self._preview_series_box.setVisible(bool(ordered_keys))

    def _on_series_toggled(self, key, checked):
        # Re-plot from the cached result — no need to recompute the preview.
        self._preview_series_state[key] = checked
        self._render_preview()

    def _saved_values_for(self, script_id):
        """Current saved param values for *script_id* (the script's configured
        values when available, else empty so manifest defaults apply).

        Resolves the dict-or-callable passed by the host on every call, so the
        form always reflects the script's latest configuration.
        """
        src = self._calib_saved_values
        if callable(src):
            try:
                src = src() or {}
            except Exception:
                src = {}
        return dict(src.get(script_id) or {})

    def _current_calib_plugin(self):
        """The PluginInfo currently selected in the script combo, or None."""
        if self._calib_script_combo is None:
            return None
        sid = self._calib_script_combo.currentData()
        return next((p for p in self._calib_plugins if p.id == sid), None)

    def _calib_param_defs(self, pinfo):
        """Manifest params of *pinfo* to expose as knobs (calibration.params or all)."""
        names = (pinfo.calibration or {}).get('params')
        params = pinfo.parameters or []
        if names:
            by_name = {p.get('name'): p for p in params if p.get('name')}
            return [by_name[n] for n in names if n in by_name]
        # Default: every tunable (non-file/directory) parameter.
        return [p for p in params if p.get('type') not in ('file', 'directory')]

    def _on_calib_script_changed(self, _index):
        # Only swap the knob form; the preview stays manual (Preview button).
        self._rebuild_calib_form()
        # A different script exposes different preview series, so hide the stale
        # selector until the next Preview run repopulates it.
        if self._preview_series_box is not None:
            self._preview_series_box.setVisible(False)

    def _rebuild_calib_form(self):
        """(Re)build the ParamForm for the selected script inside the scroll area."""
        if self._calib_scroll is None:
            return
        pinfo = self._current_calib_plugin()
        if pinfo is None:
            return
        param_defs = self._calib_param_defs(pinfo)
        saved = self._saved_values_for(pinfo.id)
        self._calib_form = ParamForm(param_defs, saved, language=self._calib_language)
        # Pressing Enter in any knob re-runs the preview at once.
        self._calib_form.submitted.connect(self._run_preview)
        # Replaces (and deletes) any previous form widget held by the scroll area.
        self._calib_scroll.setWidget(self._calib_form)

    def _preview_fn_for(self, pinfo):
        """Return (and cache) the script's ``preview`` callable, or None."""
        if pinfo.id not in self._preview_fn_cache:
            self._preview_fn_cache[pinfo.id] = load_script_callable(pinfo, 'preview')
        return self._preview_fn_cache[pinfo.id]

    def _preview_columns(self):
        """The displayed traces to calibrate against (numeric only, capped)."""
        cols = [c for c in self._displayed_columns if c in self.data.columns]
        numeric = []
        for c in cols:
            y = pd.to_numeric(self.data[c], errors='coerce').to_numpy(dtype=float)
            if np.isfinite(y).any():
                numeric.append((c, y))
        return numeric

    def _run_preview(self):
        """Run the script's preview() on every displayed trace (Preview button)."""
        if self.data is None or self._calib_form is None:
            return
        pinfo = self._current_calib_plugin()
        if pinfo is None:
            return
        preview_fn = self._preview_fn_for(pinfo)
        if preview_fn is None:
            self._set_calib_status(_tr('This script has no preview() function.'))
            return

        numeric = self._preview_columns()
        if not numeric:
            self._set_calib_status(_tr('Plot some traces first (Regex or Neuron Selection).'))
            return

        capped = len(numeric) > PREVIEW_MAX_TRACES
        numeric = numeric[:PREVIEW_MAX_TRACES]

        # Every column shares the frame axis, so decimate once.
        n = numeric[0][1].shape[0]
        if n > MAX_PREVIEW_POINTS:
            idx = np.linspace(0, n - 1, MAX_PREVIEW_POINTS).astype(int)
        else:
            idx = np.arange(n)

        samples = {}
        raw_map = {}
        for name, y in numeric:
            yd = y[idx]
            nan = np.isnan(yd)
            if nan.any() and (~nan).any():
                valid = np.flatnonzero(~nan)
                yd = yd.copy()
                yd[nan] = np.interp(np.flatnonzero(nan), valid, yd[valid])
            samples[name] = yd
            raw_map[name] = yd

        params = self._calib_form.get_values()
        self._preview_token += 1
        token = self._preview_token
        self._preview_idx = idx
        self._preview_raw_map = raw_map
        note = _tr(' (showing first {0})').format(PREVIEW_MAX_TRACES) if capped else ''
        self._set_calib_status(_tr('Computing preview for {0} trace(s)…').format(len(samples)) + note)

        worker = _PreviewWorker(preview_fn, samples, params, token, parent=self)
        worker.progress.connect(self._on_preview_progress)
        worker.done.connect(self._on_preview_done)
        worker.failed.connect(self._on_preview_failed)
        keep_alive_until_finished(worker)
        self._preview_worker = worker
        worker.start()

    def _on_preview_progress(self, token, done, total):
        if token == self._preview_token:
            self._set_calib_status(_tr('Computing preview… {0}/{1}').format(done, total))

    def _on_preview_failed(self, token, message):
        if token != self._preview_token:
            return
        self._set_calib_status(_tr('Preview failed: {0}').format(message))

    def _on_preview_done(self, token, result):
        if token != self._preview_token:
            return  # a newer run superseded this one
        self._preview_result = result or {}
        # Discover the series the script returned (union across columns, in the
        # order first seen), with 'Original' (the raw trace) always first, and
        # offer them as checkboxes so the user picks which to draw.
        ordered = [_PREVIEW_ORIGINAL]
        seen = set()
        for col in self._preview_raw_map:
            for name in (self._preview_result.get(col) or {}):
                if name not in seen:
                    seen.add(name)
                    ordered.append(name)
        self._rebuild_series_checks(ordered)
        self._render_preview()

    def _render_preview(self):
        """(Re)plot the cached preview, keeping only the checked series.

        One line per (displayed column x checked series), labelled "col: series".
        Runs off the stored result, so toggling checkboxes never recomputes.
        """
        if not self._preview_raw_map:
            return
        self._showing_preview = True
        checked = {k for k, cb in self._preview_series_checks.items() if cb.isChecked()}
        series = {}
        for col, y in self._preview_raw_map.items():
            if _PREVIEW_ORIGINAL in checked:
                series[f'{col}: {self._series_label(_PREVIEW_ORIGINAL)}'] = y
            for name, values in (self._preview_result.get(col, {}) or {}).items():
                if name not in checked:
                    continue
                arr = np.asarray(values, dtype=float).ravel()
                if arr.shape[0] == y.shape[0]:
                    series[f'{col}: {self._series_label(name)}'] = arr
        self._plot_named_series(self._preview_idx, series)
        self._set_calib_status(_tr('Previewing {0} series (click legend to toggle).').format(
            len(series)))

    def _plot_named_series(self, x, series_map):
        """Plot each named 1-D array in *series_map* over the shared x, with a
        clickable/toggleable legend (shared with the column plots)."""
        try:
            self.plot_widget.clear()
            self._plot_items = {}
            legend = None
            try:
                legend = self.plot_widget.addLegend()
            except Exception:
                legend = None
            for i, (name, values) in enumerate(series_map.items()):
                pen = pg.mkPen(PLOT_COLOR_PALETTE[i % len(PLOT_COLOR_PALETTE)], width=2)
                item = self.plot_widget.plot(x, values, pen=pen, name=str(name))
                self._plot_items[str(name)] = item
            self._attach_clickable_legend(legend)
        except Exception as e:
            self.log_message.emit(_tr('Error rendering preview:\n{0}').format(str(e)))

    def _set_calib_status(self, text):
        if self._calib_status is not None:
            self._calib_status.setText(text)

    def _input_param_name(self, pinfo):
        """Name of the script's input parameter (its first ``file`` knob), or None."""
        for p in (pinfo.parameters or []):
            if p.get('type') == 'file':
                return p.get('name')
        return None

    def _on_calib_apply(self):
        """Write the current knob values back into the pipeline config.

        Along with the tuned knobs, the path of the CSV currently open in this
        viewer is written to the script's input parameter, so the calibrated
        script points at the same data the preview was tuned against.
        """
        pinfo = self._current_calib_plugin()
        if pinfo is None or self._calib_form is None or self._calib_apply_cb is None:
            return
        values = self._calib_form.get_values()
        input_name = self._input_param_name(pinfo)
        if input_name and self.file_path:
            values[input_name] = self.file_path
        self._calib_apply_cb(pinfo.id, values)
        # Keep the local seed in sync so re-opening the form shows the applied
        # values. When the host supplies a callable, it already reads live config,
        # so there is nothing to sync here.
        if isinstance(self._calib_saved_values, dict):
            self._calib_saved_values[pinfo.id] = dict(values)
        self._set_calib_status(_tr('Applied to "{0}".').format(str(pinfo.name)))


class PdfViewer(BaseViewer):
    """Shows a PDF with QtPdf, falling back to QtWebEngine when unavailable."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pdf_document = None
        self._pdf_view = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

    def load(self, file_path):
        # Prefer QtPdf (QPdfView) when available for smooth scrolling and stable behavior
        try:
            from PySide6.QtPdf import QPdfDocument
            from PySide6.QtPdfWidgets import QPdfView

            self._pdf_document = QPdfDocument(self)
            self._pdf_document.load(file_path)
            self._pdf_view = QPdfView(self)
            self._pdf_view.setDocument(self._pdf_document)
            # Prefer multi-page / continuous scrolling if available; fall back silently if not.
            try:
                try:
                    self._pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
                except Exception:
                    try:
                        self._pdf_view.setPageMode(QPdfView.PageMode.Continuous)
                    except Exception:
                        pass

                # Keep FitInView zoom when available
                try:
                    self._pdf_view.setZoomMode(self._pdf_view.ZoomMode.FitInView)
                except Exception:
                    pass
            except Exception:
                # Any unexpected API differences are ignored; default view will be used.
                pass
            self.layout().addWidget(self._pdf_view)
            self.load_done.emit(True, _tr('Loading PDF (QPdfView): {0}').format(
                os.path.basename(file_path)))
            return
        except Exception:
            # QtPdf not available or failed — fall back to QWebEngineView below
            pass

        if QWebEngineView is None:
            self.load_done.emit(False, _tr(
                'Could not display the PDF with QtPdf and QtWebEngine is not available: {0}'
            ).format(os.path.basename(file_path)))
            return
        try:
            web_view = QWebEngineView(self)
            # Enable plugins if available to help with embedded PDF viewers
            try:
                from PySide6.QtWebEngineCore import QWebEngineSettings
                web_view.settings().setAttribute(QWebEngineSettings.PluginsEnabled, True)
            except Exception:
                pass

            web_view.setUrl(QUrl.fromLocalFile(file_path))
            self.layout().addWidget(web_view)
            web_view.setFocus()
            self._pdf_view = web_view
            self.load_done.emit(True, _tr('Loading PDF (QWebEngineView): {0}').format(
                os.path.basename(file_path)))
        except Exception as e:
            self.load_done.emit(False, _tr('Error loading PDF:\n{0}').format(str(e)))


# ImageJ ROI type codes (ij.gui.Roi): the annotator maps its shapes onto these.
_IJ_POLYGON, _IJ_RECT, _IJ_OVAL, _IJ_FREELINE, _IJ_FREEHAND = 0, 1, 2, 4, 7


def brush_stroke_to_polygon(points, radius):
    """Convert a brush stroke into the outline polygon of the area it paints.

    The on-screen brush is a round-capped stroke of width ``2*radius`` — i.e. the
    union of discs of *radius* swept along *points*. Rasterising that union and
    tracing its outer contour yields a polygon whose area matches what the user
    sees, so the saved ROI is an area (not a thin line). Returns a list of
    absolute ``(x, y)`` vertices, or ``None`` if tracing fails.
    """
    try:
        import cv2
    except ImportError:
        return None
    r = max(1, int(radius))
    pts = np.array([[int(round(x)), int(round(y))] for x, y in points], dtype=np.int32)
    pad = r + 2
    minx, miny = pts[:, 0].min() - pad, pts[:, 1].min() - pad
    maxx, maxy = pts[:, 0].max() + pad, pts[:, 1].max() + pad
    mask = np.zeros((maxy - miny + 1, maxx - minx + 1), dtype=np.uint8)
    local = pts - [minx, miny]
    if len(local) > 1:
        cv2.polylines(mask, [local], False, 255, thickness=2 * r)
    # Discs at every vertex give the round caps and joins the stroke has.
    for p in local:
        cv2.circle(mask, (int(p[0]), int(p[1])), r, 255, -1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    contour = cv2.approxPolyDP(contour, 1.5, True)  # drop near-collinear points
    poly = [(int(x) + minx, int(y) + miny) for [[x, y]] in contour]
    return poly if len(poly) >= 3 else None


def encode_imagej_roi(region):
    """Encode one annotator *region* as ImageJ ``.roi`` bytes.

    Produces the same binary format ``read_roi`` parses, so a saved archive
    re-loads in this viewer and in ImageJ/FIJI. Rectangles → RECT, circles →
    OVAL, polygons → POLYGON, and brush strokes → FREEHAND, saved as the outline
    of the painted area so their thickness matches the on-screen stroke.
    Coordinates are stored as shorts relative to the bounding box, per the
    ImageJ convention.
    """
    rtype = region['type']
    stroke_w = 0
    xs, ys = [], []
    if rtype in ('rect', 'ellipse'):
        left, top = int(region['left']), int(region['top'])
        right, bottom = left + int(region['width']), top + int(region['height'])
        n = 0
        ij_type = _IJ_RECT if rtype == 'rect' else _IJ_OVAL
    else:
        pts = region['points']
        if rtype == 'polygon':
            ij_type = _IJ_POLYGON
        else:  # brush → outline of the painted area (fall back to a thick line)
            poly = brush_stroke_to_polygon(pts, int(region.get('radius', 1)))
            if poly:
                pts = poly
                ij_type = _IJ_FREEHAND
            else:
                ij_type = _IJ_FREELINE
                stroke_w = int(2 * region.get('radius', 1))
        xs = [int(round(p[0])) for p in pts]
        ys = [int(round(p[1])) for p in pts]
        left, top = min(xs), min(ys)
        right, bottom = max(xs) + 1, max(ys) + 1
        n = len(pts)

    coords = bytearray()
    for xi in xs:
        coords += struct.pack('>h', xi - left)
    for yi in ys:
        coords += struct.pack('>h', yi - top)

    # A second 64-byte header follows the coordinates; readers (incl. read_roi)
    # require its offset to be set even though we leave its C/Z/T fields zero.
    header2_offset = 64 + len(coords)

    header = bytearray(64)  # ImageJ ROI header is 64 bytes, big-endian
    struct.pack_into('>4s', header, 0, b'Iout')
    struct.pack_into('>h', header, 4, 227)        # version
    header[6] = ij_type & 0xff                     # ROI type
    struct.pack_into('>h', header, 8, top)
    struct.pack_into('>h', header, 10, left)
    struct.pack_into('>h', header, 12, bottom)
    struct.pack_into('>h', header, 14, right)
    struct.pack_into('>h', header, 16, n)
    struct.pack_into('>h', header, 34, stroke_w)   # stroke width
    struct.pack_into('>i', header, 60, header2_offset)

    header2 = bytearray(64)  # zeroed C/Z/T position + name/image metadata
    return bytes(header) + bytes(coords) + bytes(header2)


class _AbsoluteSeekStyle(QProxyStyle):
    """Makes a left-click on the slider groove jump straight to that position
    (absolute seek) instead of stepping one page at a time. Dragging keeps
    working, so a click and a drag both map to the same seek behaviour.

    Always construct this without a base style: QProxyStyle *takes ownership*
    of any style handed to its constructor, and ``QWidget.style()`` returns the
    application-wide style, so passing one in would make this object delete the
    style shared by every widget. A base-less proxy resolves
    ``QApplication.style()`` dynamically instead, which also keeps working when
    the theme manager swaps the application style.
    """

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.SH_Slider_AbsoluteSetButtons:
            return Qt.LeftButton.value
        return super().styleHint(hint, option, widget, returnData)


# Playing a video is noisy on the terminal by default, from two independent
# sources, so both are turned down once before the first player is built.
_AV_LOG_ERROR = 16
_media_logs_quieted = False


def _quiet_media_logs():
    """Turn down media-stack chatter. Best effort, never fatal."""
    global _media_logs_quieted
    if _media_logs_quieted:
        return
    _media_logs_quieted = True  # only ever worth trying once

    # 1. Qt Multimedia announces itself through Qt's own logging categories at
    #    info level ("Using Qt multimedia with FFmpeg version ...", "No HW
    #    decoder found"), which is on by default. Drop info and debug there
    #    and keep warnings up, so real backend problems still show. Skipped
    #    when QT_LOGGING_RULES is set, so an explicit debugging session set up
    #    by the user is never overridden.
    if not os.environ.get('QT_LOGGING_RULES'):
        QLoggingCategory.setFilterRules(
            'qt.multimedia.*.debug=false\nqt.multimedia.*.info=false')

    # 2. FFmpeg — the library behind that backend on Windows and Linux — logs
    #    straight to the process stderr at AV_LOG_INFO: a stream dump per file
    #    opened, plus for JPEG-range (yuvj*) video one "deprecated pixel format
    #    used" line from libswscale per converted frame. AV_LOG_ERROR keeps
    #    genuine decode failures visible and drops the rest.
    #    The level is a global inside libavutil, so this has to reach the very
    #    library the backend uses: loading it by the path Qt ships hands back
    #    the already-loaded module rather than a second copy. Backends without
    #    a bundled FFmpeg (macOS uses AVFoundation) have nothing to quiet.
    try:
        import ctypes
        import glob
        import PySide6

        base = os.path.dirname(PySide6.__file__)
        names = ('avutil-*.dll' if os.name == 'nt' else 'libavutil.so*')
        for folder in (base, os.path.join(base, 'Qt', 'lib')):
            for path in sorted(glob.glob(os.path.join(folder, names))):
                try:
                    ctypes.CDLL(path).av_log_set_level(_AV_LOG_ERROR)
                    return
                except (OSError, AttributeError):
                    continue
    except Exception:
        pass  # never let log tidying stop a video from playing


class VideoViewer(BaseViewer):
    """Plays a video through a QVideoSink so ROIs can be painted on each frame.

    Also hosts a lightweight ROI *annotator*: pausing on a frame, the user can
    draw rectangle and polygon regions and save them to a ``regions.json``
    artifact. That file becomes an ordinary ``file`` input for a downstream ML/ROI
    script, so the region selection is calibrated visually without the script
    itself needing any UI.
    """

    # Colour of regions drawn in edit mode (amber), distinct from the green used
    # for loaded ImageJ ROIs.
    _EDIT_PEN = (230, 168, 23, 235)
    _EDIT_BRUSH = (230, 168, 23, 60)

    # Zoom bounds and per-wheel-notch step for the frame zoom.
    _MAX_ZOOM = 8.0
    _ZOOM_STEP = 1.25

    # Minimap shown while zoomed in: longest side in label pixels, the largest
    # fraction of the label it may take up (so it stays out of the way on a
    # small pane), the corner margin, and the size below which it is not worth
    # drawing at all.
    _MINIMAP_MAX_SIDE = 108
    _MINIMAP_MAX_FRACTION = 0.20
    _MINIMAP_MARGIN = 8
    _MINIMAP_MIN_SIDE = 36

    def __init__(self, parent=None):
        super().__init__(parent)
        self.roi_data = {}
        self._pending_frame = None
        # Last decoded frame kept as a clean (ROI-free) base so the overlay can
        # be repainted on demand — e.g. when ROIs load or toggle while paused.
        self._current_image = None
        self._show_rois = True

        # Zoom/pan state, applied whether the video is playing or paused.
        # ``_zoom`` is 1.0 at the fit-to-view baseline; ``_view_center`` is the
        # image-space point shown at the label centre (None => image centre).
        # Kept in image coordinates so the same transform positions both the
        # frame and the ROI overlays.
        self._zoom = 1.0
        self._view_center = None
        # Drag-to-pan bookkeeping: (press position, view centre and scale at
        # press) while a pan gesture is in flight, else None.
        self._pan_origin = None
        # Cached minimap thumbnail, keyed on (frame, size) so a pan redraw does
        # not rescale the whole frame on every mouse move.
        self._minimap_cache = None

        # ROI annotator state (Tier 2 calibration). Regions are stored in
        # original-image coordinates so they scale with the display.
        self._edit_mode = False
        self._edit_shape = 'rect'         # 'rect' | 'ellipse' | 'polygon' | 'brush'
        self._edit_brush_size = 12        # brush stroke radius in image pixels
        self._edit_regions = []           # finalized regions (dicts)
        self._edit_current = None         # in-progress region, or None
        self._edit_cursor = None          # last mouse position (image coords)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # QLabel displays decoded frames; black background for letterboxing
        self.display_label = QLabel()
        self.display_label.setAlignment(Qt.AlignCenter)
        self.display_label.setStyleSheet("background: black;")
        # The label-sized canvas we set as the pixmap must not feed back into the
        # layout: without this the pixmap's size becomes the label's sizeHint and
        # the video (and window) grow every frame. Ignored policy lets the layout
        # drive the label size instead of the pixmap.
        self.display_label.setMinimumSize(1, 1)
        self.display_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        # ROI overlay toggle: floats in the top-right corner of the video rather
        # than sitting next to the play button (where it read as a pause icon).
        # Hidden until a ROI file is loaded so the video stays uncluttered.
        self.roi_button = QPushButton(self.display_label)
        self.roi_button.setCheckable(True)
        self.roi_button.setChecked(True)
        self.roi_button.setToolTip(_tr('Show/hide ROIs'))
        self.roi_button.setIcon(icon_loader.get_icon('square-dashed', '#ffffff', 14))
        self.roi_button.setFixedSize(28, 28)
        self.roi_button.setCursor(Qt.PointingHandCursor)
        self.roi_button.setStyleSheet(
            "QPushButton { background: rgba(0, 0, 0, 130); border: none; border-radius: 4px; }"
            "QPushButton:hover { background: rgba(0, 0, 0, 180); }"
            "QPushButton:checked { background: rgba(25, 158, 112, 190); }"
        )
        self.roi_button.clicked.connect(self.toggle_rois)
        self.roi_button.hide()
        # Reposition the floating button whenever the video area resizes.
        self.display_label.installEventFilter(self)

        # Before the first player exists: creating one spins up the media
        # backend, which announces itself on the terminal unless muted first.
        _quiet_media_logs()

        # QVideoSink receives raw frames — lets us draw ROIs before display
        self.media_player = QMediaPlayer(self)
        self.video_sink = QVideoSink(self)
        self.media_player.setVideoSink(self.video_sink)
        self.video_sink.videoFrameChanged.connect(self._on_video_frame_received)
        # play() only reaches PlayingState once the media has finished loading,
        # so the icon has to follow the player's own state rather than be set
        # from the call site (which would read the pre-transition state).
        self.media_player.playbackStateChanged.connect(self._on_playback_state_changed)
        # Basename of the file whose (asynchronous) load has not been reported
        # yet; None once load_done has been emitted for it.
        self._pending_load = None
        self.media_player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.media_player.errorOccurred.connect(self._on_media_error)

        # Render timer: pull the latest stored frame at a fixed ~30 fps so the
        # main thread is not flooded by every decoded frame from the video sink.
        self.frame_timer = QTimer(self)
        self.frame_timer.setInterval(33)  # ~30 fps
        self.frame_timer.timeout.connect(self._render_pending_frame)

        # Control bar
        control_widget = QWidget()
        control_layout = QHBoxLayout(control_widget)
        control_layout.setContentsMargins(0, 2, 0, 2)
        control_layout.setSpacing(3)

        self.play_button = QPushButton()
        self.play_button.setIcon(icon_loader.get_icon('play', icon_loader.glyph_color(), 14))
        self.play_button.setFixedSize(30, 24)
        self.play_button.clicked.connect(self.toggle_play_pause)
        control_layout.addWidget(self.play_button)

        self.progress_slider = QSlider(Qt.Horizontal)
        self.progress_slider.setMinimum(0)
        # Click anywhere on the groove to seek there (not just drag the handle).
        # setStyle() does not take ownership, so the proxy is kept alive by this
        # attribute for as long as the slider needs it.
        self._seek_style = _AbsoluteSeekStyle()
        self.progress_slider.setStyle(self._seek_style)
        self.progress_slider.sliderMoved.connect(self.set_position)
        # sliderMoved only fires while dragging: a click on the groove moves the
        # handle (absolute-set, above) without ever emitting it, so the player
        # would keep its old position and the next positionChanged would snap the
        # handle straight back. Seek on press and release too, which covers a
        # plain click, a click-and-hold and the end of a drag.
        self.progress_slider.sliderPressed.connect(self._seek_to_slider)
        self.progress_slider.sliderReleased.connect(self._seek_to_slider)
        self.media_player.durationChanged.connect(self.update_duration)
        self.media_player.positionChanged.connect(self.update_position)
        control_layout.addWidget(self.progress_slider, 1)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setMinimumWidth(85)
        self.time_label.setMaximumHeight(22)
        self.time_label.setStyleSheet("font-size: 10px;")
        control_layout.addWidget(self.time_label)

        # ROI annotator toggle: pauses on the current frame and reveals the edit
        # toolbar below.
        self.edit_button = QPushButton()
        self.edit_button.setCheckable(True)
        self.edit_button.setToolTip(_tr('Draw and save ROIs on the current frame'))
        self.edit_button.setIcon(icon_loader.get_icon('square-dashed', icon_loader.glyph_color(), 14))
        self.edit_button.setFixedSize(30, 24)
        self.edit_button.clicked.connect(self._toggle_edit_mode)
        control_layout.addWidget(self.edit_button)

        # Edit toolbar (hidden until edit mode is on): shape picker, clear, save.
        self.edit_toolbar = QWidget()
        edit_layout = QHBoxLayout(self.edit_toolbar)
        edit_layout.setContentsMargins(2, 0, 2, 2)
        edit_layout.setSpacing(4)
        self.shape_label = QLabel(_tr('Shape:'))
        edit_layout.addWidget(self.shape_label)
        self.shape_combo = QComboBox()
        self.shape_combo.addItem(_tr('Rectangle'), 'rect')
        self.shape_combo.addItem(_tr('Circle'), 'ellipse')
        self.shape_combo.addItem(_tr('Polygon'), 'polygon')
        self.shape_combo.addItem(_tr('Paintbrush'), 'brush')
        self.shape_combo.currentIndexChanged.connect(self._on_shape_changed)
        edit_layout.addWidget(self.shape_combo)

        # Brush point size (shown only while the Paintbrush shape is active).
        self.brush_label = QLabel(_tr('Brush:'))
        edit_layout.addWidget(self.brush_label)
        self.brush_spin = QSpinBox()
        self.brush_spin.setRange(1, 200)
        self.brush_spin.setValue(self._edit_brush_size)
        self.brush_spin.setToolTip(_tr('Brush point size (px)'))
        self.brush_spin.valueChanged.connect(self._on_brush_size_changed)
        edit_layout.addWidget(self.brush_spin)

        self.edit_hint = QLabel('')
        self.edit_hint.setStyleSheet('color: #888888; font-size: 10px;')
        edit_layout.addWidget(self.edit_hint, 1)
        self.undo_region_btn = QPushButton(_tr('Undo'))
        self.undo_region_btn.setToolTip(_tr('Undo the last region (Ctrl+Z)'))
        self.undo_region_btn.clicked.connect(self._undo_region)
        edit_layout.addWidget(self.undo_region_btn)
        self.clear_regions_btn = QPushButton(_tr('Clear'))
        self.clear_regions_btn.clicked.connect(self._clear_regions)
        edit_layout.addWidget(self.clear_regions_btn)
        self.save_regions_btn = QPushButton(_tr('Save regions…'))
        self.save_regions_btn.clicked.connect(self._save_regions)
        edit_layout.addWidget(self.save_regions_btn)
        # Brush size is only relevant for the Paintbrush shape (default is Rectangle).
        self.brush_label.hide()
        self.brush_spin.hide()
        self.edit_toolbar.hide()

        # Ctrl+Z undoes the last drawn region while editing.
        self.undo_shortcut = QShortcut(QKeySequence.Undo, self)
        self.undo_shortcut.activated.connect(self._undo_region)

        layout.addWidget(self.display_label, 1)
        layout.addWidget(control_widget, 0)
        layout.addWidget(self.edit_toolbar, 0)

    def load(self, file_path):
        try:
            self._reset_zoom()
            self.frame_timer.start()
            # Preview videos are usually short clips, so play them on a loop
            # rather than leaving a frozen last frame. Set per load: the loop
            # count is tied to the media being played.
            self.media_player.setLoops(QMediaPlayer.Loops.Infinite)
            # Opening the media is asynchronous, so the outcome is not known
            # here: _on_media_status_changed / _on_media_error report it once
            # the backend has actually parsed the file.
            self._pending_load = os.path.basename(file_path)
            self.media_player.setSource(QUrl.fromLocalFile(file_path))
            self.media_player.play()

            self._update_play_icon()
        except Exception as e:
            self._pending_load = None
            self.load_done.emit(False, _tr('Error loading video:\n{0}').format(str(e)))

    def _finish_load(self, ok, detail):
        """Report the result of the load in flight, at most once per load."""
        if self._pending_load is None:
            return
        name, self._pending_load = self._pending_load, None
        if ok:
            self.load_done.emit(True, _tr('Playing video: {0}').format(name))
        else:
            self.load_done.emit(
                False, _tr('Error loading video:\n{0}').format(detail or name))

    def _on_media_status_changed(self, status):
        if status in (QMediaPlayer.MediaStatus.LoadedMedia,
                      QMediaPlayer.MediaStatus.BufferedMedia):
            self._finish_load(True, None)
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            # Reached when the backend rejects the file without a separate
            # errorOccurred, so fall back to whatever error text it has.
            self._finish_load(False, self.media_player.errorString())

    def _on_media_error(self, _error, error_string):
        self._finish_load(False, error_string)

    def load_roi(self, roi_zip_path):
        """Load a ROI zip; the regions are painted onto every subsequent frame."""
        try:
            rois = read_roi.read_roi_zip(roi_zip_path)
            if not rois:
                self.log_message.emit(_tr('No ROIs found in {0}').format(
                    os.path.basename(roi_zip_path)))
                return
            self.roi_data = rois
            self.roi_button.show()
            self._position_roi_button()
            # Repaint the frame already on screen so the ROIs appear at once,
            # even while the video is paused.
            self._redraw_current_frame()
            self.log_message.emit(_tr('ROIs loaded: {0} regions from {1}').format(
                len(rois), os.path.basename(roi_zip_path)))
        except Exception as e:
            self.log_message.emit(_tr('Error loading ROI:\n{0}').format(str(e)))

    def on_activated(self):
        # Playback stays paused on purpose; only frame rendering resumes.
        self.frame_timer.start()

    def on_deactivated(self):
        self.media_player.pause()
        self.frame_timer.stop()
        self._update_play_icon()

    def release(self):
        self.frame_timer.stop()
        self.media_player.stop()
        self.media_player.setSource(QUrl())

    def apply_theme(self, is_dark):
        self._update_play_icon()

    def retranslate(self):
        """Re-apply translations to the code-built ROI edit toolbar."""
        self.roi_button.setToolTip(_tr('Show/hide ROIs'))
        self.edit_button.setToolTip(_tr('Draw and save ROIs on the current frame'))
        self.shape_label.setText(_tr('Shape:'))
        for i, label in enumerate((_tr('Rectangle'), _tr('Circle'),
                                   _tr('Polygon'), _tr('Paintbrush'))):
            self.shape_combo.setItemText(i, label)
        self.brush_label.setText(_tr('Brush:'))
        self.brush_spin.setToolTip(_tr('Brush point size (px)'))
        self.undo_region_btn.setText(_tr('Undo'))
        self.undo_region_btn.setToolTip(_tr('Undo the last region (Ctrl+Z)'))
        self.clear_regions_btn.setText(_tr('Clear'))
        self.save_regions_btn.setText(_tr('Save regions…'))
        if self._edit_mode:
            self._update_edit_hint()

    def eventFilter(self, obj, event):
        if obj is self.display_label:
            etype = event.type()
            # Keep the floating ROI toggle pinned to the top-right of the video.
            if etype == QEvent.Resize:
                self._position_roi_button()
            # Mouse wheel zooms the paused frame (and its ROI overlays).
            elif etype == QEvent.Wheel and self._handle_wheel_zoom(event):
                return True
            # Dragging pans the zoomed frame. Checked before the annotator so a
            # pan in progress keeps the mouse, and so the middle button pans
            # even in edit mode (where the left button draws).
            if self._handle_pan_event(event):
                return True
            # In edit mode, the label captures mouse input to draw regions.
            if self._edit_mode and self._handle_edit_event(event):
                return True
        return super().eventFilter(obj, event)

    def _handle_wheel_zoom(self, event):
        """Zoom the paused frame toward the cursor. Returns True if consumed.

        Works while playing as well as while paused: the zoom/pan view belongs
        to the display, so every decoded frame — and the ROI overlay painted
        onto it — is shown through the same transform.
        """
        if self._current_image is None or self._current_image.isNull():
            return False
        delta = event.angleDelta().y()
        if delta == 0:
            return False

        transform = self._view_transform()
        if transform is None:
            return False
        scale, tx, ty = transform

        factor = self._ZOOM_STEP if delta > 0 else 1.0 / self._ZOOM_STEP
        new_zoom = min(max(self._zoom * factor, 1.0), self._MAX_ZOOM)
        if new_zoom == self._zoom:
            return True

        # Keep the image point under the cursor pinned in place across the zoom.
        base = scale / self._zoom
        new_scale = base * new_zoom
        pos = event.position()
        px = (pos.x() - tx) / scale
        py = (pos.y() - ty) / scale
        lw, lh = self.display_label.width(), self.display_label.height()
        self._view_center = (px + (lw / 2.0 - pos.x()) / new_scale,
                             py + (lh / 2.0 - pos.y()) / new_scale)
        self._zoom = new_zoom
        self._update_cursor()
        self._redraw_current_frame()
        return True

    def _reset_zoom(self):
        """Return to the fit-to-view baseline (used when playback resumes)."""
        self._zoom = 1.0
        self._view_center = None
        self._pan_origin = None
        self._update_cursor()

    def _can_pan(self):
        """True when the frame is zoomed in far enough to have somewhere to go."""
        return (self._zoom > 1.0
                and self._current_image is not None
                and not self._current_image.isNull())

    def _handle_pan_event(self, event):
        """Drag the zoomed frame around. Returns True if the event is consumed.

        The left button pans whenever the annotator is off; the middle button
        always does, so a zoomed frame can still be navigated while drawing.
        """
        etype = event.type()
        if etype == QEvent.MouseButtonPress:
            if not self._can_pan():
                return False
            button = event.button()
            if button != Qt.MiddleButton and not (
                    button == Qt.LeftButton and not self._edit_mode):
                return False
            transform = self._view_transform()
            if transform is None:
                return False
            # _view_transform() has just resolved (and clamped) the centre, so
            # it is safe to anchor the drag to it.
            self._pan_origin = (event.position(), self._view_center, transform[0])
            self._update_cursor()
            return True

        if self._pan_origin is None:
            return False

        if etype == QEvent.MouseMove:
            start_pos, start_center, scale = self._pan_origin
            pos = event.position()
            # Drag the image with the cursor: the view centre moves the opposite
            # way, by the cursor delta converted back to image pixels.
            self._view_center = (
                start_center[0] - (pos.x() - start_pos.x()) / scale,
                start_center[1] - (pos.y() - start_pos.y()) / scale,
            )
            self._redraw_current_frame()
            return True

        if etype in (QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            self._pan_origin = None
            self._update_cursor()
            return True

        return False

    def _update_cursor(self):
        """Pick the frame cursor for the current pan/zoom/edit state."""
        if self._pan_origin is not None:
            cursor = Qt.ClosedHandCursor
        elif self._edit_mode:
            cursor = Qt.CrossCursor
        elif self._can_pan():
            cursor = Qt.OpenHandCursor
        else:
            cursor = Qt.ArrowCursor
        self.display_label.setCursor(cursor)

    def _handle_edit_event(self, event):
        """Handle a drawing gesture on the frame; return True if consumed."""
        etype = event.type()
        if etype not in (
            QEvent.MouseButtonPress, QEvent.MouseMove,
            QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick,
        ):
            return False

        pt = self._label_to_image(event.position().toPoint())
        shape = self._edit_shape

        if etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if pt is None:
                return True
            if shape in ('rect', 'ellipse'):
                self._edit_current = {'type': shape, 'x0': pt[0], 'y0': pt[1],
                                      'x1': pt[0], 'y1': pt[1]}
            elif shape == 'brush':
                self._edit_current = {'type': 'brush', 'radius': int(self._edit_brush_size),
                                      'points': [pt]}
            else:  # polygon: each click adds a vertex
                if self._edit_current is None:
                    self._edit_current = {'type': 'polygon', 'points': [pt]}
                else:
                    self._edit_current['points'].append(pt)
            self._edit_cursor = pt
            self._redraw_current_frame()
            return True

        if etype == QEvent.MouseMove:
            self._edit_cursor = pt
            if self._edit_current is not None and pt is not None:
                if shape in ('rect', 'ellipse'):
                    self._edit_current['x1'], self._edit_current['y1'] = pt
                elif shape == 'brush':
                    self._edit_current['points'].append(pt)
                self._redraw_current_frame()
            return True

        if etype == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            if shape in ('rect', 'ellipse', 'brush') and self._edit_current is not None:
                self._finalize_region(self._edit_current)
                self._edit_current = None
                self._redraw_current_frame()
            return True

        if etype == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            # Close the polygon in progress.
            if shape == 'polygon' and self._edit_current is not None:
                if len(self._edit_current['points']) >= 3:
                    self._finalize_region(self._edit_current)
                self._edit_current = None
                self._redraw_current_frame()
            return True

        return False

    def _position_roi_button(self):
        """Pin the floating ROI toggle to the top-right corner of the video."""
        margin = 8
        x = self.display_label.width() - self.roi_button.width() - margin
        self.roi_button.move(max(margin, x), margin)

    def _update_play_icon(self):
        name = 'pause' if self.media_player.isPlaying() else 'play'
        self.play_button.setIcon(icon_loader.get_icon(name, icon_loader.glyph_color(), 14))

    def _on_playback_state_changed(self, _state):
        """Keep the play/pause icon in sync with the player's actual state."""
        self._update_play_icon()

    def _on_video_frame_received(self, frame):
        """Store the latest decoded frame; rendering is done by the timer at ~30 fps."""
        self._pending_frame = frame

    def _render_pending_frame(self):
        """Render the latest stored video frame (called by QTimer at ~30 fps)."""
        frame = self._pending_frame
        if frame is None or not frame.isValid():
            return
        self._pending_frame = None

        image = frame.toImage()
        if image.isNull():
            return

        # Keep the clean frame so ROIs can be repainted on demand while paused.
        self._current_image = image
        self._display_image(image)

    def _redraw_current_frame(self):
        """Repaint the frame already on screen with the current ROI state.

        Used when ROIs load or the overlay is toggled while the video is paused,
        so the change shows without waiting for the next decoded frame.
        """
        if self._current_image is not None and not self._current_image.isNull():
            self._display_image(self._current_image)

    def _display_image(self, image):
        """Paint the ROI overlay (when enabled) onto *image* and show it.

        *image* is treated as read-only; a copy is drawn on so the stored base
        frame stays clean for future repaints.
        """
        show_loaded = bool(self.roi_data and self._show_rois)
        if show_loaded or self._edit_mode:
            image = QImage(image)  # copy-on-write; detaches when painted
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing, True)
            if show_loaded:
                painter.setPen(QPen(QColor(0, 255, 0, 230), 2))
                painter.setBrush(QBrush(QColor(0, 255, 0, 50)))
                for roi_d in self.roi_data.values():
                    try:
                        if isinstance(roi_d, dict):
                            if 'x' in roi_d and 'y' in roi_d:
                                points = [QPoint(int(x), int(y)) for x, y in zip(roi_d['x'], roi_d['y'])]
                                if len(points) > 2:
                                    painter.drawPolygon(QPolygon(points))
                            elif all(k in roi_d for k in ['left', 'top', 'width', 'height']):
                                painter.drawRect(
                                    int(roi_d['left']), int(roi_d['top']),
                                    int(roi_d['width']), int(roi_d['height'])
                                )
                    except Exception:
                        pass
            if self._edit_mode:
                self._draw_edit_regions(painter)
            painter.end()

        transform = self._view_transform()
        if transform is None:
            return
        scale, tx, ty = transform
        lw, lh = self.display_label.width(), self.display_label.height()

        # Compose onto a label-sized canvas: black letterbox, then the frame
        # (with its baked-in ROIs) placed by the shared image->label transform,
        # so overlays stay aligned with the video at any zoom/pan.
        canvas = QPixmap(lw, lh)
        canvas.fill(Qt.black)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, self._smooth_scaling())
        painter.save()
        painter.translate(tx, ty)
        painter.scale(scale, scale)
        painter.drawImage(0, 0, image)
        painter.restore()
        # The minimap is a navigation aid drawn in label space, so it keeps its
        # size and corner while the frame beneath it zooms and pans.
        if self._zoom > 1.0:
            painter.setRenderHint(QPainter.Antialiasing, True)
            self._draw_minimap(painter, lw, lh, scale, tx, ty)
        painter.end()
        self.display_label.setPixmap(canvas)

    def _smooth_scaling(self):
        """Whether the magnified frame is interpolated rather than nearest-neighbour.

        Only worth paying for when magnified — at fit-to-view the frame is
        downscaled, where the fast path is already indistinguishable.
        """
        return self._zoom > 1.0

    def _draw_minimap(self, painter, lw, lh, scale, tx, ty):
        """Draw the whole frame in the top-left corner with the visible region
        outlined, so it is clear where the zoomed view sits.

        Uses the clean base frame rather than the ROI-painted copy: it is a
        locator, and a stable source keeps the scaled thumbnail cacheable.
        """
        img = self._current_image
        iw, ih = img.width(), img.height()
        side = min(self._MINIMAP_MAX_SIDE,
                   int(lw * self._MINIMAP_MAX_FRACTION),
                   int(lh * self._MINIMAP_MAX_FRACTION))
        if side < self._MINIMAP_MIN_SIDE:
            return  # too little room for the minimap to be readable
        thumb_scale = min(side / iw, side / ih)
        mw, mh = max(1, int(iw * thumb_scale)), max(1, int(ih * thumb_scale))
        # Top-left: the floating ROI toggle occupies the opposite corner.
        mx = my = self._MINIMAP_MARGIN

        painter.setOpacity(0.85)
        painter.drawPixmap(mx, my, self._minimap_thumbnail(mw, mh))
        painter.setOpacity(1.0)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 140), 1))
        painter.drawRect(QRectF(mx - 0.5, my - 0.5, mw + 1, mh + 1))

        # The visible region: the slice of the image the label currently maps
        # onto, clamped to the frame and expressed in minimap pixels.
        sx, sy = mw / iw, mh / ih
        x0, y0 = max(0.0, -tx / scale), max(0.0, -ty / scale)
        x1, y1 = min(float(iw), (lw - tx) / scale), min(float(ih), (lh - ty) / scale)
        view = QRectF(mx + x0 * sx, my + y0 * sy,
                      max(2.0, (x1 - x0) * sx), max(2.0, (y1 - y0) * sy))
        painter.setPen(QPen(QColor(*self._EDIT_PEN), 2))
        painter.setBrush(QBrush(QColor(255, 255, 255, 40)))
        painter.drawRect(view)

    def _minimap_thumbnail(self, mw, mh):
        """The current frame scaled to *mw* x *mh*, cached between redraws."""
        key = (self._current_image.cacheKey(), mw, mh)
        if self._minimap_cache is None or self._minimap_cache[0] != key:
            scaled = self._current_image.scaled(
                mw, mh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self._minimap_cache = (key, QPixmap.fromImage(scaled))
        return self._minimap_cache[1]

    def _view_transform(self):
        """Return ``(scale, tx, ty)`` mapping image coords to label coords.

        At ``_zoom == 1`` this is the fit-to-view letterbox used during
        playback; when zoomed in the view is clamped so it stays over the image.
        The clamped centre is written back to ``_view_center``. Returns ``None``
        when there is nothing sized to map.
        """
        img = self._current_image
        if img is None or img.isNull():
            return None
        iw, ih = img.width(), img.height()
        lw, lh = self.display_label.width(), self.display_label.height()
        if iw <= 0 or ih <= 0 or lw <= 0 or lh <= 0:
            return None
        base = min(lw / iw, lh / ih)
        scale = base * self._zoom
        # Size of the visible window expressed in image pixels.
        vw, vh = lw / scale, lh / scale
        cx, cy = self._view_center or (iw / 2.0, ih / 2.0)
        # Keep the window over the image on each axis it no longer fully covers.
        cx = min(max(cx, vw / 2.0), iw - vw / 2.0) if vw < iw else iw / 2.0
        cy = min(max(cy, vh / 2.0), ih - vh / 2.0) if vh < ih else ih / 2.0
        self._view_center = (cx, cy)
        return scale, lw / 2.0 - cx * scale, lh / 2.0 - cy * scale

    def toggle_play_pause(self):
        """Toggle between play and pause"""
        if self.media_player.isPlaying():
            self.media_player.pause()
        else:
            # The zoom/pan view survives play/pause: playback carries on inside
            # the zoomed region instead of snapping back to fit-to-view.
            self.frame_timer.start()
            self.media_player.play()
        self._update_play_icon()

    def toggle_rois(self):
        """Show or hide the ROI overlay, repainting the current frame at once."""
        self._show_rois = self.roi_button.isChecked()
        self._redraw_current_frame()

    # ------------------------------------------------------------------
    # ROI annotator (Tier 2 calibration)
    # ------------------------------------------------------------------

    def _toggle_edit_mode(self):
        """Enter/leave ROI edit mode: pause on the current frame and draw regions."""
        self._edit_mode = self.edit_button.isChecked()
        if self._edit_mode:
            if self._current_image is None or self._current_image.isNull():
                self.log_message.emit(_tr('Play the video to a frame before editing ROIs.'))
                self.edit_button.setChecked(False)
                self._edit_mode = False
                return
            self.media_player.pause()
            self._update_play_icon()
            self.edit_toolbar.show()
            self._update_edit_hint()
        else:
            self._edit_current = None
            self.edit_toolbar.hide()
        self._update_cursor()
        self._redraw_current_frame()

    def _on_shape_changed(self, _index):
        self._edit_shape = self.shape_combo.currentData() or 'rect'
        self._edit_current = None  # drop any half-drawn shape when switching
        is_brush = self._edit_shape == 'brush'
        self.brush_label.setVisible(is_brush)
        self.brush_spin.setVisible(is_brush)
        self._update_edit_hint()
        self._redraw_current_frame()

    def _on_brush_size_changed(self, value):
        self._edit_brush_size = int(value)

    def _update_edit_hint(self):
        hints = {
            'polygon': _tr('Click to add points, double-click to close.'),
            'brush': _tr('Drag to paint a freehand area.'),
            'ellipse': _tr('Drag to draw a circle.'),
        }
        self.edit_hint.setText(hints.get(self._edit_shape, _tr('Drag to draw a rectangle.')))

    def _undo_region(self):
        """Remove the most recent region (button / Ctrl+Z). Cancels a shape in
        progress first, if any."""
        if not self._edit_mode:
            return
        if self._edit_current is not None:
            self._edit_current = None
        elif self._edit_regions:
            self._edit_regions.pop()
        else:
            return
        self._redraw_current_frame()

    def _clear_regions(self):
        self._edit_regions = []
        self._edit_current = None
        self._redraw_current_frame()

    def _finalize_region(self, region):
        """Store *region* (in image coords) with an auto label, dropping empties."""
        label = f'region_{len(self._edit_regions) + 1}'
        rtype = region['type']
        if rtype in ('rect', 'ellipse'):
            x0, x1 = sorted((region['x0'], region['x1']))
            y0, y1 = sorted((region['y0'], region['y1']))
            if x1 - x0 < 2 or y1 - y0 < 2:
                return  # ignore accidental clicks
            self._edit_regions.append({
                'type': rtype, 'label': label,
                'left': int(round(x0)), 'top': int(round(y0)),
                'width': int(round(x1 - x0)), 'height': int(round(y1 - y0)),
            })
        elif rtype == 'brush':
            pts = region.get('points', [])
            if not pts:
                return
            self._edit_regions.append({
                'type': 'brush', 'label': label,
                'radius': int(region.get('radius', self._edit_brush_size)),
                'points': [[int(round(px)), int(round(py))] for px, py in pts],
            })
        else:  # polygon
            pts = region.get('points', [])
            if len(pts) < 3:
                return
            self._edit_regions.append({
                'type': 'polygon', 'label': label,
                'points': [[int(round(px)), int(round(py))] for px, py in pts],
            })

    def _label_to_image(self, point):
        """Map a display-label point to original-image coordinates.

        Uses the same zoom/pan transform as :meth:`_display_image`, so drawing
        lines up with the frame whatever the zoom. Returns ``(x, y)`` floats
        inside the image, or ``None`` outside it.
        """
        transform = self._view_transform()
        if transform is None:
            return None
        scale, tx, ty = transform
        x = (point.x() - tx) / scale
        y = (point.y() - ty) / scale
        iw, ih = self._current_image.width(), self._current_image.height()
        if 0 <= x < iw and 0 <= y < ih:
            return (x, y)
        return None

    def _draw_edit_regions(self, painter):
        """Paint saved regions plus the in-progress shape (in image coords)."""
        painter.setPen(QPen(QColor(*self._EDIT_PEN), 2))
        painter.setBrush(QBrush(QColor(*self._EDIT_BRUSH)))
        for region in self._edit_regions:
            self._draw_one_region(painter, region, closed=True)
        if self._edit_current is not None:
            self._draw_one_region(painter, self._edit_current, closed=False)

    def _region_bbox(self, region):
        """Return (x, y, w, h) for a rect/ellipse in either storage form."""
        if 'left' in region:  # finalized: left/top/width/height
            return int(region['left']), int(region['top']), int(region['width']), int(region['height'])
        x0, y0, x1, y1 = region['x0'], region['y0'], region['x1'], region['y1']  # in-progress
        return int(min(x0, x1)), int(min(y0, y1)), int(abs(x1 - x0)), int(abs(y1 - y0))

    def _draw_one_region(self, painter, region, closed):
        rtype = region['type']
        if rtype == 'rect':
            painter.drawRect(*self._region_bbox(region))
        elif rtype == 'ellipse':
            painter.drawEllipse(*self._region_bbox(region))
        elif rtype == 'brush':
            # Freehand stroke: a thick round-capped polyline of the brush width.
            pts = [QPoint(int(p[0]), int(p[1])) for p in region['points']]
            if not pts:
                return
            radius = int(region.get('radius', self._edit_brush_size))
            saved = painter.pen()
            stroke = QPen(QColor(*self._EDIT_PEN), max(1, 2 * radius))
            stroke.setCapStyle(Qt.RoundCap)
            stroke.setJoinStyle(Qt.RoundJoin)
            painter.setPen(stroke)
            if len(pts) == 1:
                painter.drawPoint(pts[0])
            else:
                painter.drawPolyline(QPolygon(pts))
            painter.setPen(saved)
        elif rtype == 'polygon':
            # Finalized regions store 'points' as [x, y] pairs; in-progress ones
            # store (x, y) tuples plus a live cursor segment.
            pts = [QPoint(int(p[0]), int(p[1])) for p in region['points']]
            if not pts:
                return
            if closed and len(pts) > 2:
                painter.drawPolygon(QPolygon(pts))
            else:
                painter.drawPolyline(QPolygon(pts))
                if self._edit_cursor is not None:
                    painter.drawLine(pts[-1], QPoint(int(self._edit_cursor[0]),
                                                     int(self._edit_cursor[1])))

    def _save_regions(self):
        """Save the drawn regions as a .zip of ImageJ .roi files.

        This is the format ``read_roi`` reads, so the archive re-loads here (and
        in ImageJ/FIJI) and feeds a downstream ML/ROI script as an ordinary file
        input.
        """
        if not self._edit_regions:
            self.log_message.emit(_tr('No regions drawn to save.'))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, _tr('Save regions'), 'regions.zip',
            _tr('ROI archives (*.zip)') + ';;' + _tr('All files (*)'),
        )
        if not path:
            return
        try:
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for i, region in enumerate(self._edit_regions, start=1):
                    name = region.get('label') or f'region_{i}'
                    zf.writestr(f'{name}.roi', encode_imagej_roi(region))
            self.log_message.emit(_tr('Saved {0} ROIs to {1}').format(
                len(self._edit_regions), os.path.basename(path)))
        except (OSError, zipfile.BadZipFile) as e:
            self.log_message.emit(_tr('Error saving regions:\n{0}').format(str(e)))

    def set_position(self, position):
        """Set media player position when slider is moved"""
        self.media_player.setPosition(position)

    def _seek_to_slider(self):
        """Seek to wherever the slider handle currently sits."""
        self.set_position(self.progress_slider.value())

    def update_duration(self, duration):
        """Update slider max when duration changes"""
        self.progress_slider.setMaximum(duration)

    def update_position(self, position):
        """Update slider and time label"""
        if not self.progress_slider.isSliderDown():
            self.progress_slider.setValue(position)

        # Update time label
        current = position // 1000
        duration = self.media_player.duration() // 1000
        current_time = f"{current // 60:02d}:{current % 60:02d}"
        total_time = f"{duration // 60:02d}:{duration % 60:02d}"
        self.time_label.setText(f"{current_time} / {total_time}")


def viewer_for(file_path, parent=None):
    """Return the viewer class instance that can preview *file_path*.

    Unknown extensions fall back to :class:`TextViewer`, as the single-viewer
    version did.
    """
    lowered = file_path.lower()
    if lowered.endswith(IMAGE_SUFFIXES):
        return ImageViewer(parent)
    if lowered.endswith('.jgf'):
        return GraphViewer(parent)
    if lowered.endswith(DATA_SUFFIXES):
        return PlotViewer(parent)
    if lowered.endswith('.pdf'):
        return PdfViewer(parent)
    if lowered.endswith(VIDEO_SUFFIXES):
        return VideoViewer(parent)
    return TextViewer(parent)
