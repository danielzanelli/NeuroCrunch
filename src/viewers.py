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

import pandas as pd
import pyqtgraph as pg
import read_roi

from PySide6.QtCore import QCoreApplication, QPoint, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap, QPolygon
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
    QSlider, QSpinBox, QTabWidget, QTextBrowser, QVBoxLayout, QWidget
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


MAX_PLOT_COLUMNS = 100  # Maximum number of columns allowed to plot at once

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


class ImageViewer(BaseViewer):
    """Shows a still image, rescaled to the tab as the window resizes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
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
            self.progress_updated.emit(
                QCoreApplication.translate('CSVReaderWorker', 'Opening CSV {0}: 0%').format(filename)
            )

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
                    self.progress_updated.emit(f'Opening CSV {filename}: {progress}%')

                if chunks:
                    data = pd.concat(chunks, ignore_index=True)
                else:
                    data = pd.read_csv(self.file_path)

            elif self.file_path.lower().endswith(('.xls', '.xlsx')):
                self.progress_updated.emit(f'Opening file {filename}: 0%')
                data = pd.read_excel(self.file_path)
                self.progress_updated.emit(f'Opening file {filename}: 100%')
            else:
                raise ValueError('File format not supported for charts.')

            self.data_loaded.emit(data)
        except Exception as e:
            self.error_occurred.emit(str(e))


class PlotViewer(BaseViewer):
    """Plots columns of a CSV/Excel file, with a tabbed column selector below."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = None
        self._reader = None
        self._plot_items = {}
        self._signal_col_by_key = {}
        self._plot_menu_widget = None
        self._is_dark = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.plot_widget, 1)

    def load(self, file_path):
        # Load data in background thread with progress reporting
        self._reader = CSVReaderWorker(file_path)
        self._reader.progress_updated.connect(self._on_reader_progress, Qt.BlockingQueuedConnection)
        self._reader.data_loaded.connect(self._on_csv_loaded)
        self._reader.error_occurred.connect(self._on_csv_error)
        keep_alive_until_finished(self._reader)
        self._reader.start()

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
        self.plot_data()

    def _rebuild_plot_menu(self):
        """(Re)build the tabbed column selector below the plot for self.data.

        Called on load and on a language change. The active tab is kept.
        """
        if self.data is None:
            return

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
        a *Regex* tab (column range + substring filter) and a *Neuron Selection*
        tab that picks columns by neuron id and metric.
        """
        tabs = QTabWidget(self)
        tabs.addTab(self._build_regex_tab(), _tr('Regex'))
        tabs.addTab(self._build_neuron_tab(), _tr('Neuron Selection'))
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

        # Start column spinbox (default 1: the first column is usually the index)
        default_start = min(1, total_columns - 1)
        self.start_spin = QSpinBox()
        self.start_spin.setMinimum(0)
        self.start_spin.setMaximum(total_columns - 1)
        self.start_spin.setValue(default_start)
        self.start_spin.lineEdit().returnPressed.connect(self.plot_data)
        grid.addWidget(QLabel(_tr('Start column:')), 1, 0)
        grid.addWidget(self.start_spin, 1, 1)

        # End column spinbox
        self.end_spin = QSpinBox()
        self.end_spin.setMinimum(0)
        self.end_spin.setMaximum(total_columns - 1)
        self.end_spin.setValue(min(default_start + 1, total_columns - 1))
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
        # don't overflow the width on small screens.
        grid.addWidget(QLabel(_tr('Metrics:')), 0, 0, Qt.AlignTop)
        metrics_box = QWidget()
        metrics_grid = QGridLayout(metrics_box)
        metrics_grid.setContentsMargins(0, 0, 0, 0)
        metrics_grid.setHorizontalSpacing(8)
        metrics_grid.setVerticalSpacing(1)
        for i, m in enumerate(metrics):
            cb = QCheckBox(m)
            cb.setChecked(True)
            self.metric_checks[m] = cb
            metrics_grid.addWidget(cb, i // 3, i % 3)
        grid.addWidget(metrics_box, 0, 1)

        # Neurons: a free-text list of ids and/or ranges (blank = every neuron).
        self.neuron_input = QLineEdit()
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

    def _plot_columns(self, columns_to_plot):
        """Render *columns_to_plot* as lines with a clickable, toggleable legend."""
        try:
            capped = len(columns_to_plot) > MAX_PLOT_COLUMNS
            columns_to_plot = columns_to_plot[:MAX_PLOT_COLUMNS]
            if capped:
                self.log_message.emit(_tr('Plotting the first {0} columns only.').format(
                    MAX_PLOT_COLUMNS))

            # Clear previous plot and legend
            self.plot_widget.clear()
            self._plot_items = {}

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
                plot_item = self.plot_widget.plot(self.data[column], pen=pen, name=str(column))
                # store by column name for toggling
                self._plot_items[str(column)] = plot_item

            # Make legend entries clickable to toggle visibility
            if legend is not None:
                try:
                    # legend.items is a list of (sample, label) pairs
                    for sample, label in list(legend.items):
                        # label may be a QGraphicsTextItem or similar; get the text
                        try:
                            label_text = str(label.text)
                        except Exception:
                            try:
                                label_text = str(label.toPlainText())
                            except Exception:
                                # fallback: read from the label's bounding rect or skip
                                label_text = None

                        # If label_text not available, try reading from the associated plot item name
                        if not label_text:
                            continue

                        # Define toggle function bound to this label_text
                        def make_toggle(name, lab, samp):
                            def _toggle(event):
                                item = self._plot_items.get(name)
                                if item is None:
                                    return
                                visible = not item.isVisible()
                                item.setVisible(visible)
                                # visually dim the legend entry when hidden
                                try:
                                    lab.setOpacity(1.0 if visible else 0.4)
                                except Exception:
                                    pass
                                try:
                                    samp.setOpacity(1.0 if visible else 0.25)
                                except Exception:
                                    pass
                            return _toggle

                        # Attach click handler to both sample and label if possible
                        try:
                            handler = make_toggle(label_text, label, sample)
                            sample.mousePressEvent = handler
                            label.mousePressEvent = handler
                        except Exception:
                            # best-effort; ignore if API differs
                            pass
                except Exception:
                    # Non-fatal: continue without clickable legend
                    pass
        except Exception as e:
            self.log_message.emit(_tr('Error loading data for chart:\n{0}').format(str(e)))
            self.plot_widget.clear()


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


class VideoViewer(BaseViewer):
    """Plays a video through a QVideoSink so ROIs can be painted on each frame."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.roi_data = {}
        self._pending_frame = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # QLabel displays decoded frames; black background for letterboxing
        self.display_label = QLabel()
        self.display_label.setAlignment(Qt.AlignCenter)
        self.display_label.setStyleSheet("background: black;")

        # QVideoSink receives raw frames — lets us draw ROIs before display
        self.media_player = QMediaPlayer(self)
        self.video_sink = QVideoSink(self)
        self.media_player.setVideoSink(self.video_sink)
        self.video_sink.videoFrameChanged.connect(self._on_video_frame_received)

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
        self.progress_slider.sliderMoved.connect(self.set_position)
        self.media_player.durationChanged.connect(self.update_duration)
        self.media_player.positionChanged.connect(self.update_position)
        control_layout.addWidget(self.progress_slider, 1)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setMinimumWidth(85)
        self.time_label.setMaximumHeight(22)
        self.time_label.setStyleSheet("font-size: 10px;")
        control_layout.addWidget(self.time_label)

        layout.addWidget(self.display_label, 1)
        layout.addWidget(control_widget, 0)

    def load(self, file_path):
        try:
            self.frame_timer.start()
            # Load and play, suppressing FFmpeg stderr noise
            try:
                old_stderr_fd = os.dup(2)
                null_fd = os.open(os.devnull, os.O_WRONLY)
                os.dup2(null_fd, 2)
                try:
                    self.media_player.setSource(QUrl.fromLocalFile(file_path))
                    self.media_player.play()
                finally:
                    os.dup2(old_stderr_fd, 2)
                    os.close(old_stderr_fd)
                    os.close(null_fd)
            except Exception:
                self.media_player.setSource(QUrl.fromLocalFile(file_path))
                self.media_player.play()

            self._update_play_icon()
            self.load_done.emit(True, _tr('Playing video: {0}').format(
                os.path.basename(file_path)))
        except Exception as e:
            self.load_done.emit(False, _tr('Error loading video:\n{0}').format(str(e)))

    def load_roi(self, roi_zip_path):
        """Load a ROI zip; the regions are painted onto every subsequent frame."""
        try:
            rois = read_roi.read_roi_zip(roi_zip_path)
            if not rois:
                self.log_message.emit(_tr('No ROIs found in {0}').format(
                    os.path.basename(roi_zip_path)))
                return
            self.roi_data = rois
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

    def _update_play_icon(self):
        name = 'pause' if self.media_player.isPlaying() else 'play'
        self.play_button.setIcon(icon_loader.get_icon(name, icon_loader.glyph_color(), 14))

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

        if self.roi_data:
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing, True)
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
            painter.end()

        pixmap = QPixmap.fromImage(image)
        if not pixmap.isNull() and self.display_label.width() > 0:
            self.display_label.setPixmap(
                pixmap.scaled(self.display_label.size(),
                              Qt.KeepAspectRatio, Qt.FastTransformation)
            )

    def toggle_play_pause(self):
        """Toggle between play and pause"""
        if self.media_player.isPlaying():
            self.media_player.pause()
        else:
            self.frame_timer.start()
            self.media_player.play()
        self._update_play_icon()

    def set_position(self, position):
        """Set media player position when slider is moved"""
        self.media_player.setPosition(position)

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
