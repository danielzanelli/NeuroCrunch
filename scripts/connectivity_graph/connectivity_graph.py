# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""connectivity_graph — Builds a connectivity network from a correlation matrix.

Reads a square correlation matrix (e.g. the Pearson matrix produced by
``pearson_matrix``) together with an ImageJ/FIJI ROI list (a ``.zip`` such as the
one produced by ``generate_rois``). ROI *i* in the list corresponds to row/column
*i* of the matrix, so each network node is placed at the centroid of its ROI and
each edge carries the matrix value between the two cells as a scalar weight.

Every finite pairwise weight is stored — no threshold is applied here — so the
full weighted graph is saved and thresholding is done interactively in the
viewer. The graph is written in the JSON Graph Format (JGF) as a ``.jgf`` file
that NeuroCrunch's built-in graph viewer can open and navigate interactively.

Output (in the output folder):
  * <name>_graph.jgf        — the connectivity graph (JSON Graph Format)

Contract: see README.md > "<script_name>.py — execution contract".
"""
from __future__ import annotations

import datetime
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    import read_roi
except ImportError:  # pragma: no cover - read_roi is a bundled dependency
    read_roi = None


# ---------------------------------------------------------------------------
# ROI geometry
# ---------------------------------------------------------------------------


def _roi_centroid(roi: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Return the (x, y) centroid of a single read_roi ROI, or None.

    Handles the shapes NeuroCrunch produces and reads: polygon/freehand/traced
    ROIs (``x``/``y`` vertex lists) and rectangle/oval ROIs
    (``left``/``top``/``width``/``height``).
    """
    xs = roi.get("x")
    ys = roi.get("y")
    if xs is not None and ys is not None and len(xs) and len(ys):
        xs = [float(v) for v in xs]
        ys = [float(v) for v in ys]
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    if all(k in roi for k in ("left", "top", "width", "height")):
        return (
            float(roi["left"]) + float(roi["width"]) / 2.0,
            float(roi["top"]) + float(roi["height"]) / 2.0,
        )

    # ImageJ point ROIs occasionally expose scalar left/top only.
    if "left" in roi and "top" in roi:
        return (float(roi["left"]), float(roi["top"]))

    return None


def _load_roi_centroids(roi_zip: str) -> Tuple[List[str], List[Optional[Tuple[float, float]]]]:
    """Load an ROI ZIP and return parallel lists of (names, centroids)."""
    if read_roi is None:
        raise ImportError("The 'read_roi' library is required to read ROI files.")
    rois = read_roi.read_roi_zip(roi_zip)
    if not rois:
        raise ValueError(f"No ROIs found in: {roi_zip}")
    names = list(rois.keys())
    centroids = [_roi_centroid(rois[name]) for name in names]
    return names, centroids


# ---------------------------------------------------------------------------
# Matrix ↔ ROI mapping
# ---------------------------------------------------------------------------


def _map_labels_to_rois(labels: List[str], n_rois: int) -> Tuple[List[Optional[int]], str]:
    """Map each matrix label to a 0-based ROI index.

    Two strategies, in order of preference:

    1. *Indexed* — when every label starts with an integer (e.g. ``"1_mean"``
       from generate_signals) that lands inside ``1..n_rois``, use that integer
       as a 1-based ROI index. This survives ``select_active`` dropping cells,
       because the surviving column keeps its original neuron number.
    2. *Positional* — otherwise fall back to row *i* ↔ ROI *i*, honouring the
       contract that the first ROI is the first row/column of the matrix.

    Returns ``(mapping, strategy)`` where ``mapping[i]`` is the ROI index for
    matrix row *i* (or ``None`` when no ROI is available for it).
    """
    parsed: List[Optional[int]] = []
    for lab in labels:
        m = re.match(r"^\s*(\d+)", str(lab))
        parsed.append(int(m.group(1)) if m else None)

    if all(p is not None and 1 <= p <= n_rois for p in parsed):
        return [p - 1 for p in parsed], "indexed"

    mapping = [i if i < n_rois else None for i in range(len(labels))]
    return mapping, "positional"


def _fallback_positions(
    n: int, mapped: List[Optional[Tuple[float, float]]]
) -> List[Tuple[float, float]]:
    """Place nodes that have no ROI centroid on a ring around the mapped ones."""
    known = [p for p in mapped if p is not None]
    if known:
        cx = sum(p[0] for p in known) / len(known)
        cy = sum(p[1] for p in known) / len(known)
        span = max(
            (max(p[0] for p in known) - min(p[0] for p in known)),
            (max(p[1] for p in known) - min(p[1] for p in known)),
            1.0,
        )
        radius = span * 0.75
    else:
        cx = cy = 0.0
        radius = max(n, 1) * 1.0

    positions: List[Tuple[float, float]] = []
    for k in range(n):
        angle = 2.0 * np.pi * k / max(n, 1)
        positions.append((cx + radius * np.cos(angle), cy + radius * np.sin(angle)))
    return positions


# ---------------------------------------------------------------------------
# JGF construction
# ---------------------------------------------------------------------------


def build_jgf(
    labels: List[str],
    positions: List[Tuple[float, float]],
    roi_names: List[Optional[str]],
    matrix: np.ndarray,
    title: str,
    metadata_extra: Dict[str, Any],
) -> Dict[str, Any]:
    """Assemble a JSON Graph Format document with all weighted edges.

    Every finite off-diagonal pair of the matrix becomes an edge carrying the
    correlation value as its weight — no threshold is applied here, so the full
    weighted graph is stored and the viewer can threshold it interactively. Each
    node records its total connection ``strength`` (sum of ``|weight|``) for
    hub-aware sizing.
    """
    n = len(labels)

    # All undirected edges from the upper triangle (vectorised).
    iu, ju = np.triu_indices(n, k=1)
    w = matrix[iu, ju]
    finite = np.isfinite(w)
    iu, ju, w = iu[finite], ju[finite], w[finite]

    strength = np.zeros(n, dtype=float)
    np.add.at(strength, iu, np.abs(w))
    np.add.at(strength, ju, np.abs(w))

    edges: List[Dict[str, Any]] = [
        {
            "source": labels[i],
            "target": labels[j],
            "relation": "correlation",
            "metadata": {"weight": round(float(val), 4)},
        }
        for i, j, val in zip(iu.tolist(), ju.tolist(), w.tolist())
    ]

    nodes: List[Dict[str, Any]] = []
    for i, lab in enumerate(labels):
        x, y = positions[i]
        nodes.append(
            {
                "id": str(lab),
                "label": str(lab),
                "metadata": {
                    "x": round(float(x), 4),
                    "y": round(float(y), 4),
                    "roi_name": roi_names[i],
                    "strength": round(float(strength[i]), 4),
                },
            }
        )

    max_abs = float(np.abs(w).max()) if w.size else 0.0
    graph = {
        "directed": False,
        "type": "neuro-connectivity",
        "label": title,
        "metadata": {
            "generator": "NeuroCrunch connectivity_graph",
            "format": "JSON Graph Format",
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "node_count": n,
            "edge_count": len(edges),
            "max_abs_weight": round(max_abs, 4),
            **metadata_extra,
        },
        "nodes": nodes,
        "edges": edges,
    }
    return {"graph": graph}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(params):
    matrix_csv = params["matrix_csv"]
    roi_zip = params["roi_zip"]
    output_dir = params["output_dir"]

    if not os.path.isfile(matrix_csv):
        raise FileNotFoundError(f"Correlation matrix not found: {matrix_csv}")
    if not os.path.isfile(roi_zip):
        raise FileNotFoundError(f"ROI file not found: {roi_zip}")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Reading correlation matrix: {os.path.basename(matrix_csv)}")
    corr = pd.read_csv(matrix_csv, index_col=0)
    labels = [str(c) for c in corr.columns]
    n = len(labels)
    if n < 2:
        raise ValueError("The correlation matrix needs at least 2 rows/columns.")
    if corr.shape[0] != corr.shape[1]:
        raise ValueError(
            f"Expected a square matrix; got {corr.shape[0]}x{corr.shape[1]}."
        )
    matrix = corr.to_numpy(dtype=float)
    print(f"  {n} nodes")
    print("PROGRESS:20")

    print(f"Reading ROIs: {os.path.basename(roi_zip)}")
    roi_names_all, roi_centroids_all = _load_roi_centroids(roi_zip)
    print(f"  {len(roi_names_all)} ROI(s)")
    if len(roi_names_all) < n:
        print(
            f"  Warning: fewer ROIs ({len(roi_names_all)}) than matrix nodes ({n}); "
            "unmatched nodes will be placed on a fallback ring."
        )

    mapping, strategy = _map_labels_to_rois(labels, len(roi_names_all))
    print(f"  Node -> ROI mapping: {strategy}")
    print("PROGRESS:45")

    # Resolve each node's ROI name and centroid via the mapping.
    node_roi_names: List[Optional[str]] = []
    mapped_positions: List[Optional[Tuple[float, float]]] = []
    for ri in mapping:
        if ri is not None and 0 <= ri < len(roi_centroids_all):
            node_roi_names.append(roi_names_all[ri])
            mapped_positions.append(roi_centroids_all[ri])
        else:
            node_roi_names.append(None)
            mapped_positions.append(None)

    n_missing = sum(1 for p in mapped_positions if p is None)
    if n_missing:
        print(f"  {n_missing} node(s) without an ROI centroid; using fallback positions.")
    fallback = _fallback_positions(n, mapped_positions)
    positions = [p if p is not None else fallback[i] for i, p in enumerate(mapped_positions)]
    print("PROGRESS:60")

    base = os.path.splitext(os.path.basename(matrix_csv))[0]
    metadata_extra = {
        "correlation_matrix": os.path.basename(matrix_csv),
        "roi_source": os.path.basename(roi_zip),
        "mapping": strategy,
    }
    jgf = build_jgf(
        labels=labels,
        positions=positions,
        roi_names=node_roi_names,
        matrix=matrix,
        title=base,
        metadata_extra=metadata_extra,
    )
    edge_count = jgf["graph"]["metadata"]["edge_count"]
    print(f"Built graph: {n} nodes, {edge_count} edges (all pairwise weights)")
    print("PROGRESS:80")

    jgf_path = os.path.join(output_dir, f"{base}_graph.jgf")
    # Compact separators keep complete (O(n^2)-edge) graphs to a manageable size.
    with open(jgf_path, "w", encoding="utf-8") as f:
        json.dump(jgf, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Graph saved: {jgf_path}")
    print("PROGRESS:100")

    return {"graph_jgf": jgf_path}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Builds a JGF connectivity graph from a correlation matrix and ROIs."
    )
    parser.add_argument("--matrix_csv", required=True)
    parser.add_argument("--roi_zip", required=True)
    parser.add_argument("--output_dir", required=True)
    args = parser.parse_args()
    print(run(vars(args)))
