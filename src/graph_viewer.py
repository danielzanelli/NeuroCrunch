# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""NeuroCrunch - Interactive JSON Graph Format (JGF) viewer.

Renders a connectivity graph (``.jgf``) produced by the ``connectivity_graph``
script. The file stores every pairwise weight, so the viewer is where the graph
becomes readable: a **threshold slider** filters edges live by ``|weight|`` and
the network redraws dynamically. Node diameter and edge stroke width have their
own sliders, edges are colour-graded by sign and strength with opacity
proportional to ``|weight|``, nodes are shaded by how many edges they still
have at the current threshold so hubs stand out, and clicking a node highlights
it and its neighbours (with their labels).

The viewer is built to stay responsive on large graphs:

  * **Threaded loading** — the file is parsed and converted to compact numpy
    arrays on a background thread, with progress reported like the CSV loader.
  * **Vectorised, bucketed rendering** — edges are drawn as a small pool of
    ``PlotCurveItem`` batches (per sign, per weight bucket), each a single Qt
    path, instead of one graphics item per edge.
  * **Render cap** — at most ``_MAX_RENDERED_EDGES`` (strongest) edges are drawn
    at once, so dragging the threshold to zero on a complete graph can't stall
    the UI.

Public surface used by the main window: :meth:`GraphViewer.load` (async),
:meth:`GraphViewer.apply_theme`, the ``plot_widget`` attribute, and the
``progress_changed`` / ``load_done`` signals.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QCoreApplication, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from base_viewer import BaseViewer

# Edge colour gradients (weak -> strong) for each sign; opacity tracks |weight|.
_POS_WEAK = (232, 150, 160)
_POS_STRONG = (198, 36, 58)     # #c6243a
_NEG_WEAK = (150, 186, 232)
_NEG_STRONG = (28, 92, 200)     # #1c5cc8
_SELECT_COLOR = (230, 168, 23)    # #e6a817 amber — the selected node/edges
_NEIGHBOR_COLOR = (25, 158, 112)  # #199e70 green — its neighbours

_NBINS = 16                 # weight buckets per sign (colour/opacity gradient)
_ALPHA_FLOOR = 0.16         # faintest edges stay just visible
_MAX_RENDERED_EDGES = 40000  # hard cap on drawn edges (strongest kept)
_MAX_NEIGHBOR_LABELS = 40   # labels shown around a selected node
_ISOLATED_ALPHA = 90        # nodes left with no visible edge fade back
_WEIGHT_LABEL_OFFSET = 0.6  # edge-weight label shift off the line, in label boxes
_TARGET_INITIAL_EDGES = 2000  # initial threshold aims to show ~this many edges

_EMPTY_IDX = np.empty(0, dtype=np.int64)

_HIST_BINS = 64             # bars in the threshold histogram

_THEMES = {
    True: {   # dark
        "bg": "#1a1e23",
        "axis": "#9aa3ad",
        "text": "#e6e6e6",
        "node_fill": (74, 84, 96),      # least-connected node (low end of the ramp)
        "node_pen": (138, 149, 162),    # dim, so the fill carries the hub signal
        "hub_high": (236, 242, 250),    # most-connected node at this threshold
        "hist_off": (74, 82, 92),       # bins below the threshold (hidden edges)
        "hist_on": (94, 160, 226),      # bins kept by the threshold
    },
    False: {  # light
        "bg": "#ffffff",
        "axis": "#66707c",
        "text": "#202020",
        "node_fill": (188, 196, 205),   # least-connected node (low end of the ramp)
        "node_pen": (58, 65, 73),       # #3a4149
        "hub_high": (26, 34, 44),       # most-connected node at this threshold
        "hist_off": (198, 204, 212),
        "hist_on": (44, 110, 180),
    },
}


class _GraphData:
    """Parsed graph as compact arrays, handed from the loader to the viewer."""

    __slots__ = (
        "ids", "labels", "roi_names", "pos", "strength",
        "src", "dst", "weight", "abs_weight", "max_abs", "graph_meta",
    )

    def __init__(self) -> None:
        self.ids: List[str] = []
        self.labels: List[str] = []
        self.roi_names: List[Optional[str]] = []
        self.pos = np.zeros((0, 2), dtype=np.float32)
        self.strength = np.zeros(0, dtype=np.float32)
        self.src = np.zeros(0, dtype=np.int32)
        self.dst = np.zeros(0, dtype=np.int32)
        self.weight = np.zeros(0, dtype=np.float32)
        self.abs_weight = np.zeros(0, dtype=np.float32)
        self.max_abs = 1.0
        self.graph_meta: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# JGF parsing helpers (shared, pure functions)
# ---------------------------------------------------------------------------


def _extract_graph(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(doc, dict):
        raise ValueError("Invalid JGF: top level is not an object.")
    if isinstance(doc.get("graph"), dict):
        return doc["graph"]
    if isinstance(doc.get("graphs"), list) and doc["graphs"]:
        return doc["graphs"][0]
    if "nodes" in doc:
        return doc
    raise ValueError("Invalid JGF: no 'graph' or 'nodes' found.")


def _as_node_list(nodes: Any) -> List[Dict[str, Any]]:
    if isinstance(nodes, list):
        return [n for n in nodes if isinstance(n, dict)]
    if isinstance(nodes, dict):
        out = []
        for nid, body in nodes.items():
            node = dict(body or {})
            node.setdefault("id", nid)
            out.append(node)
        return out
    return []


def _edge_weight(edge: Dict[str, Any]) -> float:
    meta = edge.get("metadata")
    val = meta.get("weight") if isinstance(meta, dict) else edge.get("weight", 0.0)
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Background loader
# ---------------------------------------------------------------------------


class _GraphLoadWorker(QThread):
    """Parses a JGF file and builds arrays off the UI thread."""

    progress = Signal(int, int, str)   # token, percent, message
    loaded = Signal(int, object)       # token, _GraphData
    failed = Signal(int, str)          # token, error

    _EDGE_CHUNK = 200_000

    def __init__(self, path: str, token: int, parent=None) -> None:
        super().__init__(parent)
        self._path = path
        self._token = token

    def run(self) -> None:  # noqa: C901 - linear, readable stages
        try:
            self.progress.emit(self._token, 5, self.tr("Reading graph file..."))
            with open(self._path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            self.progress.emit(self._token, 30, self.tr("Parsing nodes..."))

            graph = _extract_graph(doc)
            nodes = _as_node_list(graph.get("nodes", []))
            if not nodes:
                raise ValueError("The graph contains no nodes.")

            n = len(nodes)
            data = _GraphData()
            data.graph_meta = graph.get("metadata", {}) or {}
            data.pos = np.zeros((n, 2), dtype=np.float32)
            data.strength = np.zeros(n, dtype=np.float32)
            index: Dict[str, int] = {}
            for k, node in enumerate(nodes):
                nid = str(node.get("id"))
                data.ids.append(nid)
                index[nid] = k
                data.labels.append(str(node.get("label", nid)))
                meta = node.get("metadata") or {}
                data.pos[k, 0] = float(meta.get("x", k) or 0.0)
                data.pos[k, 1] = float(meta.get("y", k) or 0.0)
                data.strength[k] = float(meta.get("strength", 0.0) or 0.0)
                data.roi_names.append(meta.get("roi_name"))

            raw_edges = graph.get("edges") or []
            self.progress.emit(self._token, 40, self.tr("Building edges..."))
            src, dst, weight, count = self._build_edges(raw_edges, index)
            data.src = src[:count]
            data.dst = dst[:count]
            data.weight = weight[:count]
            data.abs_weight = np.abs(data.weight)
            meta_max = data.graph_meta.get("max_abs_weight")
            data.max_abs = (
                float(meta_max) if meta_max
                else (float(data.abs_weight.max()) if count else 1.0)
            ) or 1.0

            self.progress.emit(self._token, 100, self.tr("Rendering..."))
            self.loaded.emit(self._token, data)
        except Exception as exc:  # noqa: BLE001 - surface to the UI
            self.failed.emit(self._token, str(exc))

    def _build_edges(self, raw_edges, index):
        """Return (src, dst, weight, count). Fast path for well-formed files."""
        m = len(raw_edges)
        src = np.empty(m, dtype=np.int32)
        dst = np.empty(m, dtype=np.int32)
        weight = np.empty(m, dtype=np.float32)
        try:
            # Fast path: every endpoint resolves, no self-loops assumed. Chunked
            # so progress can advance during a multi-million-edge build.
            for start in range(0, m, self._EDGE_CHUNK):
                sl = raw_edges[start:start + self._EDGE_CHUNK]
                stop = start + len(sl)
                src[start:stop] = np.fromiter(
                    (index[str(e["source"])] for e in sl), np.int32, len(sl))
                dst[start:stop] = np.fromiter(
                    (index[str(e["target"])] for e in sl), np.int32, len(sl))
                weight[start:stop] = np.fromiter(
                    (_edge_weight(e) for e in sl), np.float32, len(sl))
                if m:
                    self.progress.emit(
                        self._token, 40 + int(55 * stop / m), self.tr("Building edges..."))
            return src, dst, weight, m
        except (KeyError, TypeError):
            pass
        # Safe path: filter unknown endpoints and self-loops.
        count = 0
        for idx, edge in enumerate(raw_edges):
            s = index.get(str(edge.get("source")))
            t = index.get(str(edge.get("target")))
            if s is None or t is None or s == t:
                continue
            src[count] = s
            dst[count] = t
            weight[count] = _edge_weight(edge)
            count += 1
            if m and idx % self._EDGE_CHUNK == 0:
                self.progress.emit(
                    self._token, 40 + int(55 * idx / m), self.tr("Building edges..."))
        return src, dst, weight, count

    def tr(self, text: str) -> str:
        return QCoreApplication.translate("GraphViewer", text)


class _WeightHistogram(QWidget):
    """Tiny bar chart of the |weight| distribution, tracking the threshold.

    Each bar counts the edges whose ``|weight|`` falls inside that bin — i.e.
    how many connections are gained (or lost) by sweeping the threshold across
    it — so the shape is a plain density, not a cumulative curve. Bars below
    the current threshold are drawn muted: they are the edges being filtered
    out. Bar heights are log scaled, since weight distributions pile up near
    zero and a linear scale leaves the whole useful tail flat on the baseline.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._heights = np.zeros(0, dtype=np.float32)  # normalised to 0..1
        self._frac = 0.0                               # threshold as 0..1
        self._theme = _THEMES[True]
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(80)

    def sizeHint(self) -> QSize:
        return QSize(220, 26)

    def set_data(self, abs_weight: np.ndarray, max_abs: float) -> None:
        if abs_weight.size == 0 or max_abs <= 0:
            self._heights = np.zeros(0, dtype=np.float32)
        else:
            counts, _ = np.histogram(abs_weight, bins=_HIST_BINS, range=(0.0, max_abs))
            scaled = np.log1p(counts.astype(np.float32))
            peak = float(scaled.max())
            self._heights = scaled / peak if peak > 0 else scaled
        self.update()

    def set_threshold(self, frac: float) -> None:
        frac = min(1.0, max(0.0, float(frac)))
        if frac != self._frac:
            self._frac = frac
            self.update()

    def apply_theme(self, theme: Dict[str, Any]) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        n = self._heights.size
        if n == 0:
            return
        w = self.width()
        h = self.height()
        bar_w = w / n
        cut = self._frac * n  # bins fully left of this are below the threshold
        off = QColor(*self._theme["hist_off"])
        on = QColor(*self._theme["hist_on"])

        painter = QPainter(self)
        for i in range(n):
            bar_h = max(1.0, float(self._heights[i]) * (h - 1))
            rect = QRectF(i * bar_w, h - bar_h, max(1.0, bar_w - 1.0), bar_h)
            painter.fillRect(rect, off if i + 1 <= cut else on)
        painter.end()


class GraphViewer(BaseViewer):
    """A self-contained interactive viewer for a single JGF graph."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._data: Optional[_GraphData] = None
        self._selected: Optional[int] = None
        self._degree = np.zeros(0, dtype=np.int64)  # per node, at the threshold
        self._node_diameter = 8.0
        self._edge_width = 1.0

        self._worker: Optional[_GraphLoadWorker] = None
        self._token = 0

        self._is_dark = True
        self._theme = _THEMES[True]
        self._active_labels: List[pg.TextItem] = []

        self._build_ui()

    # ------------------------------------------------------------------
    # UI scaffolding
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setAntialiasing(False)  # off by default for big graphs
        vb = self.plot_widget.getViewBox()
        vb.setAspectLocked(True)
        vb.invertY(True)  # ROI/image coordinates: y grows downward
        vb.setMenuEnabled(False)
        self.plot_widget.getPlotItem().hideButtons()
        self.plot_widget.scene().sigMouseClicked.connect(self._on_scene_clicked)

        # Edges: a pool of batched curves — one per (sign, weight bucket) — so
        # colour and opacity can vary with |weight| while staying vectorised.
        # Added weak -> strong so the strongest edges paint on top.
        self._neg_curves: List[pg.PlotCurveItem] = []
        self._pos_curves: List[pg.PlotCurveItem] = []
        for _ in range(_NBINS):
            cn = pg.PlotCurveItem()
            cp = pg.PlotCurveItem()
            self._neg_curves.append(cn)
            self._pos_curves.append(cp)
            self.plot_widget.addItem(cn)
            self.plot_widget.addItem(cp)

        self._curve_hl = pg.PlotCurveItem()
        self.plot_widget.addItem(self._curve_hl)

        # Nodes: one base scatter (uniform style, hover tooltip) plus a tiny
        # overlay scatter for the selection highlight. Both are made
        # click-transparent so panning and node picking are never intercepted.
        self._node_item = pg.ScatterPlotItem(pxMode=True, hoverable=True)
        self._node_item.setAcceptedMouseButtons(Qt.NoButton)
        self._hl_nodes = pg.ScatterPlotItem(pxMode=True)
        self._hl_nodes.setAcceptedMouseButtons(Qt.NoButton)
        self._hl_nodes.setAcceptHoverEvents(False)
        self.plot_widget.addItem(self._node_item)
        self.plot_widget.addItem(self._hl_nodes)

        layout.addWidget(self.plot_widget, 1)

        # Debounce re-renders while a slider is dragged.
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(40)
        self._render_timer.timeout.connect(self._render_edges)

        # --- control bar: Reset button on top, sliders stacked vertically ---
        controls = QWidget()
        cbox = QVBoxLayout(controls)
        cbox.setContentsMargins(4, 2, 4, 2)
        cbox.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        self.btn_reset = QPushButton(self.tr("Reset view"))
        self.btn_reset.clicked.connect(self.reset_view)
        top_row.addWidget(self.btn_reset)
        top_row.addSpacing(6)
        self.hist = _WeightHistogram()
        self.hist.setToolTip(
            self.tr("Edge count per |weight| bin; muted bars are below the threshold")
        )
        top_row.addWidget(self.hist, 1)
        cbox.addLayout(top_row)

        # A grid keeps the row labels and slider tracks aligned in columns.
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(3)
        grid.setColumnStretch(1, 1)  # sliders expand to fill the width

        grid.addWidget(QLabel(self.tr("Min |weight|:")), 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(1000)
        self.slider.setValue(0)
        self.slider.valueChanged.connect(self._on_threshold_changed)
        grid.addWidget(self.slider, 0, 1)
        self.lbl_threshold = QLabel("0.00")
        self.lbl_threshold.setMinimumWidth(34)
        grid.addWidget(self.lbl_threshold, 0, 2)

        grid.addWidget(QLabel(self.tr("Nodes:")), 1, 0)
        self.node_slider = QSlider(Qt.Horizontal)
        self.node_slider.setMinimum(2)
        self.node_slider.setMaximum(30)
        self.node_slider.setValue(int(self._node_diameter))
        self.node_slider.valueChanged.connect(self._on_node_size_changed)
        grid.addWidget(self.node_slider, 1, 1)

        grid.addWidget(QLabel(self.tr("Edges:")), 2, 0)
        self.edge_slider = QSlider(Qt.Horizontal)
        self.edge_slider.setMinimum(1)   # width = value * 0.5  -> 0.5 .. 6.0
        self.edge_slider.setMaximum(12)
        self.edge_slider.setValue(int(self._edge_width / 0.5))
        self.edge_slider.valueChanged.connect(self._on_edge_width_changed)
        grid.addWidget(self.edge_slider, 2, 1)

        cbox.addLayout(grid)
        layout.addWidget(controls, 0)

        self.info = QLabel(self.tr("No graph loaded."))
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.info, 0)

        self._set_controls_enabled(False)

    def tr(self, text: str) -> str:  # noqa: A003 - mirror QWidget.tr for i18n
        return QCoreApplication.translate("GraphViewer", text)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for w in (self.btn_reset, self.slider, self.node_slider, self.edge_slider):
            w.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Loading (async)
    # ------------------------------------------------------------------

    def load(self, file_path: str) -> None:
        """Start loading *file_path* on a background thread."""
        self._token += 1
        self._set_controls_enabled(False)
        self.info.setText(
            self.tr("Loading {0}...").format(os.path.basename(file_path))
        )
        worker = _GraphLoadWorker(file_path, self._token, parent=self)
        worker.progress.connect(self._on_worker_progress)
        worker.loaded.connect(self._on_worker_loaded)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_worker_progress(self, token: int, pct: int, message: str) -> None:
        if token != self._token:
            return
        self.info.setText(f"{message} {pct}%")
        self.progress_changed.emit(f"{message} {pct}%")

    def _on_worker_failed(self, token: int, message: str) -> None:
        if token != self._token:
            return
        self.info.setText(self.tr("Failed to load graph: {0}").format(message))
        self.load_done.emit(False, self.tr("Error loading graph:\n{0}").format(message))

    def _on_worker_loaded(self, token: int, data: _GraphData) -> None:
        if token != self._token:
            return  # a newer load superseded this one
        self._data = data
        self._selected = None

        # Initial threshold: show roughly _TARGET_INITIAL_EDGES strongest edges.
        m = data.abs_weight.size
        if m > _TARGET_INITIAL_EDGES and data.max_abs > 0:
            kth = m - _TARGET_INITIAL_EDGES
            thr0 = float(np.partition(data.abs_weight, kth)[kth])
            slider_val = int(round(thr0 / data.max_abs * 1000))
        else:
            slider_val = 0
        self.slider.blockSignals(True)
        self.slider.setValue(min(1000, max(0, slider_val)))
        self.slider.blockSignals(False)
        self.lbl_threshold.setText(f"{self._threshold():.2f}")
        self.hist.set_data(data.abs_weight, data.max_abs)
        self.hist.set_threshold(self.slider.value() / 1000.0)

        self._build_nodes()
        self._render_edges()
        self.reset_view()
        self._set_controls_enabled(True)

        n = len(data.ids)
        self.load_done.emit(True, self.tr("Graph loaded: {0} nodes, {1} edges").format(n, m))

    def release(self) -> None:
        """Ignore any in-flight load and wait for the worker before teardown."""
        self._token += 1
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.wait(2000)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _threshold(self) -> float:
        if self._data is None:
            return 0.0
        return self.slider.value() / 1000.0 * self._data.max_abs

    def _build_nodes(self) -> None:
        """Draw the base node scatter (hover tooltip); shading comes per render."""
        data = self._data
        if data is None:
            return
        theme = self._theme
        self._node_item.setData(
            pos=data.pos,
            size=self._node_diameter,
            brush=pg.mkBrush(*theme["node_fill"]),
            pen=pg.mkPen(color=theme["node_pen"], width=1.0),
            data=np.arange(len(data.ids)),
            hoverable=True,
            hoverPen=pg.mkPen(theme["text"], width=2),
            tip=self._node_tip,
        )

    def _shade_nodes(self, above: np.ndarray) -> None:
        """Shade each node by how many of its edges survive the threshold.

        Hubs read straight off the plot: the busiest node at the current
        threshold takes the brightest fill (darkest, in the light theme), and
        nodes left with no edge at all fade back. The ramp is renormalised on
        every render, so it always spans the degrees actually on screen rather
        than washing out as the threshold climbs.
        """
        data = self._data
        n = len(data.ids)
        if above.size:
            deg = np.bincount(
                np.concatenate((data.src[above], data.dst[above])), minlength=n)
        else:
            deg = np.zeros(n, dtype=np.int64)
        self._degree = deg

        low = np.array(self._theme["node_fill"], dtype=np.float32)
        high = np.array(self._theme["hub_high"], dtype=np.float32)
        peak = int(deg.max()) if n else 0
        if peak > 0:
            # sqrt lifts the middle: degree is skewed, and a linear ramp leaves
            # everything but the single biggest hub sitting at the low colour.
            rgb = low + (high - low) * np.sqrt(deg / peak)[:, None]
        else:
            rgb = np.tile(low, (n, 1))
        self._node_item.setBrush([
            pg.mkBrush(int(r), int(g), int(b), 255 if d else _ISOLATED_ALPHA)
            for (r, g, b), d in zip(rgb, deg)
        ])

    def _bin_pen(self, positive: bool, b: int, dim: float):
        """Pen for weight bucket *b*: colour graded by strength, alpha ~ |weight|."""
        frac = (b + 0.5) / _NBINS
        weak, strong = (_POS_WEAK, _POS_STRONG) if positive else (_NEG_WEAK, _NEG_STRONG)
        color = tuple(int(round(weak[i] + (strong[i] - weak[i]) * frac)) for i in range(3))
        alpha = int(round(255 * max(_ALPHA_FLOOR, frac) * dim))
        return pg.mkPen(color=(color[0], color[1], color[2], alpha), width=self._edge_width)

    def _render_edges(self) -> None:
        """Rebuild the bucketed edge curves and highlight overlays."""
        data = self._data
        if data is None:
            return
        thr = self._threshold()
        above = np.flatnonzero(data.abs_weight >= thr)
        total_above = int(above.size)
        self._shade_nodes(above)  # before the render cap trims *above*

        capped = above.size > _MAX_RENDERED_EDGES
        if capped:  # keep only the strongest _MAX_RENDERED_EDGES
            strongest = np.argpartition(
                data.abs_weight[above], -_MAX_RENDERED_EDGES)[-_MAX_RENDERED_EDGES:]
            above = above[strongest]

        selecting = self._selected is not None
        dim = 0.28 if selecting else 1.0
        if above.size:
            frac = np.clip(data.abs_weight[above] / data.max_abs, 0.0, 1.0)
            bins = np.minimum((frac * _NBINS).astype(int), _NBINS - 1)
            positive = data.weight[above] >= 0
        for b in range(_NBINS):
            if above.size:
                in_bin = bins == b
                pos_idx = above[in_bin & positive]
                neg_idx = above[in_bin & ~positive]
            else:
                pos_idx = neg_idx = _EMPTY_IDX
            self._set_curve(self._pos_curves[b], pos_idx, self._bin_pen(True, b, dim))
            self._set_curve(self._neg_curves[b], neg_idx, self._bin_pen(False, b, dim))

        self._draw_highlight(thr)
        if selecting:
            self._update_selection_info(thr)
        else:
            self._update_overview_info(total_above, capped)

    def _set_curve(self, curve: pg.PlotCurveItem, eidx: np.ndarray, pen) -> None:
        data = self._data
        if eidx.size == 0:
            curve.setData(x=np.empty(0, np.float32), y=np.empty(0, np.float32))
            return
        si = data.src[eidx]
        ti = data.dst[eidx]
        px = data.pos[:, 0]
        py = data.pos[:, 1]
        xs = np.empty(eidx.size * 2, dtype=np.float32)
        ys = np.empty(eidx.size * 2, dtype=np.float32)
        xs[0::2] = px[si]
        xs[1::2] = px[ti]
        ys[0::2] = py[si]
        ys[1::2] = py[ti]
        curve.setData(x=xs, y=ys, connect="pairs", pen=pen,
                      antialias=False, skipFiniteCheck=True)

    def _draw_highlight(self, thr: float) -> None:
        data = self._data
        self._curve_hl.setData(x=np.empty(0, np.float32), y=np.empty(0, np.float32))
        self._hl_nodes.setData(pos=np.zeros((0, 2), dtype=np.float32))
        self._clear_active_labels()
        if self._selected is None:
            return

        s = self._selected
        inc = ((data.src == s) | (data.dst == s)) & (data.abs_weight >= thr)
        eidx = np.flatnonzero(inc)
        if eidx.size > _MAX_RENDERED_EDGES:
            strongest = np.argpartition(
                data.abs_weight[eidx], -_MAX_RENDERED_EDGES)[-_MAX_RENDERED_EDGES:]
            eidx = eidx[strongest]
        self._set_curve(self._curve_hl, eidx,
                        pg.mkPen(color=(*_SELECT_COLOR, 235), width=self._edge_width + 0.6))

        neigh = np.where(data.src[eidx] == s, data.dst[eidx], data.src[eidx])
        neigh = np.unique(neigh)
        d = self._node_diameter
        if neigh.size:
            pos = np.vstack([data.pos[neigh], data.pos[s][None, :]])
            sizes = [d * 1.5] * neigh.size + [d * 2.0]
            brushes = [pg.mkBrush(*_NEIGHBOR_COLOR)] * neigh.size + [pg.mkBrush(*_SELECT_COLOR)]
        else:
            pos = data.pos[s][None, :]
            sizes = [d * 2.0]
            brushes = [pg.mkBrush(*_SELECT_COLOR)]
        self._hl_nodes.setData(
            pos=pos, size=sizes, brush=brushes,
            pen=pg.mkPen(self._theme["node_pen"], width=1.0), pxMode=True,
        )
        self._draw_active_labels(s, eidx)

    def _draw_active_labels(self, s: int, eidx: np.ndarray) -> None:
        """Label the selected node, its (strongest) neighbours and edge weights."""
        data = self._data
        color = self._theme["text"]
        self._add_label(s, color)
        if not eidx.size:
            return
        order = eidx[np.argsort(-data.abs_weight[eidx])]
        seen = set()
        for e in order:
            other = int(data.dst[e] if data.src[e] == s else data.src[e])
            if other in seen:
                continue
            seen.add(other)
            self._add_label(other, color)
            self._add_weight_label(int(e), s, other)
            if len(seen) >= _MAX_NEIGHBOR_LABELS:
                break

    def _add_label(self, k: int, color) -> None:
        data = self._data
        self._add_text(data.labels[k], float(data.pos[k, 0]), float(data.pos[k, 1]),
                       color, (0.5, 1.3))

    def _add_weight_label(self, e: int, s: int, other: int) -> None:
        """Show an edge's weight beside its midpoint, clear of the line itself.

        The offset is expressed through the text anchor, so it is a fixed
        fraction of the label box (screen space) and survives zooming. The
        direction is the screen-space normal of the outgoing edge, which puts
        every label on the same side of its line.
        """
        data = self._data
        dx = float(data.pos[other, 0] - data.pos[s, 0])
        dy = float(data.pos[other, 1] - data.pos[s, 1])   # view y grows downward
        norm = math.hypot(dx, dy)
        if norm:
            nx, ny = -dy / norm, dx / norm
            anchor = (0.5 - _WEIGHT_LABEL_OFFSET * nx, 0.5 - _WEIGHT_LABEL_OFFSET * ny)
        else:
            anchor = (0.5, 1.3)
        self._add_text(
            f"{float(data.weight[e]):+.2f}",
            float(data.pos[s, 0] + data.pos[other, 0]) / 2.0,
            float(data.pos[s, 1] + data.pos[other, 1]) / 2.0,
            _SELECT_COLOR, anchor,
        )

    def _add_text(self, text: str, x: float, y: float, color, anchor) -> None:
        ti = pg.TextItem(text=text, color=color, anchor=anchor)
        ti.setPos(x, y)
        self.plot_widget.addItem(ti)
        self._active_labels.append(ti)

    def _clear_active_labels(self) -> None:
        for ti in self._active_labels:
            self.plot_widget.removeItem(ti)
        self._active_labels = []

    def _node_tip(self, x: float, y: float, data: Any) -> str:
        k = int(data)
        roi = self._data.roi_names[k] if self._data else None
        parts = [self._data.labels[k]]
        if roi and str(roi) != self._data.labels[k]:
            parts.append(self.tr("ROI: {0}").format(roi))
        parts.append(self.tr("strength {0:.2f}").format(float(self._data.strength[k])))
        if k < self._degree.size:
            parts.append(self.tr("{0} connections shown").format(int(self._degree[k])))
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _on_scene_clicked(self, event) -> None:
        """Select the nearest node to a left click, or deselect on empty space.

        Selection is done here (rather than via ScatterPlotItem.sigClicked) so it
        picks the genuinely nearest node within a pixel tolerance — robust to
        overlapping points and zoom level, and never intercepted by overlays.
        """
        if self._data is None or event.button() != Qt.LeftButton:
            return
        vb = self.plot_widget.getViewBox()
        pt = vb.mapSceneToView(event.scenePos())
        dx = self._data.pos[:, 0] - pt.x()
        dy = self._data.pos[:, 1] - pt.y()
        d2 = dx * dx + dy * dy
        k = int(np.argmin(d2))

        try:
            px_scale = float(vb.viewPixelSize()[0]) or 1.0
        except Exception:  # noqa: BLE001 - fall back to raw data units
            px_scale = 1.0
        tol = (self._node_diameter / 2.0 + 6.0) * px_scale

        if float(np.sqrt(d2[k])) <= tol:
            if self._selected != k:
                self._selected = k
                self._render_edges()
        elif self._selected is not None:
            self._selected = None
            self._render_edges()

    def _on_threshold_changed(self, value: int) -> None:
        self.lbl_threshold.setText(f"{self._threshold():.2f}")
        self.hist.set_threshold(value / 1000.0)  # cheap repaint, tracks the drag
        self._render_timer.start()  # debounced -> _render_edges

    def _on_node_size_changed(self, value: int) -> None:
        self._node_diameter = float(value)
        if self._data is not None:
            self._node_item.setSize(self._node_diameter)
            self._draw_highlight(self._threshold())

    def _on_edge_width_changed(self, value: int) -> None:
        self._edge_width = value * 0.5
        self._render_timer.start()

    def reset_view(self) -> None:
        """Reset the pan/zoom and clear any selection."""
        if self._selected is not None:
            self._selected = None
            self._render_edges()
        self.plot_widget.getViewBox().autoRange(padding=0.08)

    # ------------------------------------------------------------------
    # Info panel
    # ------------------------------------------------------------------

    def _update_overview_info(self, total_above: int, capped: bool) -> None:
        data = self._data
        thr = self._threshold()
        msg = self.tr("{0} nodes · {1} edges with |weight| ≥ {2:.2f}").format(
            len(data.ids), total_above, thr
        )
        if capped:
            msg += self.tr(" · showing strongest {0}").format(_MAX_RENDERED_EDGES)
        msg += self.tr(" · click a node to inspect it")
        self.info.setText(msg)

    def _update_selection_info(self, thr: float) -> None:
        data = self._data
        s = self._selected
        inc = ((data.src == s) | (data.dst == s)) & (data.abs_weight >= thr)
        eidx = np.flatnonzero(inc)
        deg = int(eidx.size)
        order = eidx[np.argsort(-data.abs_weight[eidx])][:6]
        top = ", ".join(
            f"{data.labels[data.dst[e] if data.src[e] == s else data.src[e]]} "
            f"({data.weight[e]:+.2f})"
            for e in order
        )
        roi = data.roi_names[s]
        roi_str = f" · ROI {roi}" if roi and str(roi) != data.labels[s] else ""
        text = self.tr("Selected {0}{1} · {2} connections ≥ {3:.2f}").format(
            data.labels[s], roi_str, deg, thr
        )
        if deg:
            text += f"\n{top}" + (", …" if deg > 6 else "")
        self.info.setText(text)

    # ------------------------------------------------------------------
    # Theming
    # ------------------------------------------------------------------

    def apply_theme(self, is_dark: bool) -> None:
        """Match the widget to the active light/dark theme."""
        self._is_dark = bool(is_dark)
        self._theme = _THEMES[self._is_dark]
        self.hist.apply_theme(self._theme)
        self.plot_widget.setBackground(self._theme["bg"])
        plot_item = self.plot_widget.getPlotItem()
        for side in ("bottom", "left"):
            axis = plot_item.getAxis(side)
            axis.setPen(pg.mkPen(color=self._theme["axis"], width=1))
            axis.setTextPen(pg.mkPen(color=self._theme["axis"]))
        if self._data is not None:
            self._build_nodes()
            self._render_edges()
