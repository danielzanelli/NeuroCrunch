# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""pearson_matrix — Pearson correlation matrix between neuron traces.

Reads a CSV of traces (columns = per-neuron metrics, rows = time) and computes
the Pearson correlation matrix between neurons for a single chosen metric.

Column names are expected to carry a metric name and a neuron number, in either
order, e.g. ``Mean7``/``Max7`` (ImageJ Multi-Measure style) or ``7_mean``
(NeuroCrunch's generate_signals style). The neuron number identifies the cell —
because upstream steps (e.g. select_active) may drop cells, the numbers can skip
values, but each metric is present for every kept neuron. Only the columns for
the selected metric are correlated, and the resulting matrix is labelled by
neuron number so the connectivity graph can map each node back to its ROI.

Outputs (in the output folder):
  * <name>_pearson_<metric>.csv  — the correlation matrix (rows/cols = neurons)
  * <name>_pearson_<metric>.png  — a heatmap of the matrix (skipped if huge)

The correlation is computed in a single streaming pass over row chunks, so files
far larger than RAM are handled without loading every frame at once. No
correlation threshold is applied here — thresholding is done later, when viewing
the connectivity graph.

Contract: see README.md > "<script_name>.py — execution contract".
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# A column is <MetricName><neuron> (e.g. "Mean7") or <neuron><sep><MetricName>
# (e.g. "7_mean"). Separators between the two parts are optional.
_COL_METRIC_FIRST = re.compile(r"^([A-Za-z]+)[ _\-]*(\d+)$")
_COL_NUMBER_FIRST = re.compile(r"^(\d+)[ _\-]*([A-Za-z]+)$")

# Above this neuron count the full heatmap image is skipped (the matrix CSV is
# still written) to avoid a multi-gigabyte figure.
_HEATMAP_MAX_NEURONS = 1500


def _parse_column(col) -> Optional[Tuple[str, int]]:
    """Return ``(metric_name, neuron_number)`` for a column, or ``None``.

    The metric name keeps its original casing. Handles both ``Mean7`` and
    ``7_mean`` orderings; non-signal columns such as ``frame``, ``time_s`` or
    ``Slice`` don't match and are ignored.
    """
    s = str(col).strip()
    m = _COL_METRIC_FIRST.match(s)
    if m:
        return m.group(1), int(m.group(2))
    m = _COL_NUMBER_FIRST.match(s)
    if m:
        return m.group(2), int(m.group(1))
    return None


def _detect_columns(
    columns,
) -> Tuple[Dict[str, List[Tuple[str, int]]], Dict[str, str]]:
    """Group parseable columns by lower-cased metric token.

    Returns ``(by_token, display)`` where ``by_token[key]`` is the list of
    ``(col_name, neuron)`` for the metric and ``display[key]`` is the metric's
    original casing (first seen), used for filenames and titles.
    """
    by_token: Dict[str, List[Tuple[str, int]]] = {}
    display: Dict[str, str] = {}
    for col in columns:
        parsed = _parse_column(col)
        if parsed is None:
            continue
        metric_name, neuron = parsed
        key = metric_name.lower()
        by_token.setdefault(key, []).append((str(col), neuron))
        display.setdefault(key, metric_name)
    return by_token, display


def _select_metric(
    by_token: Dict[str, List[Tuple[str, int]]], display: Dict[str, str], metric: str
) -> Tuple[List[str], List[int], str]:
    """Pick the columns for *metric*; return ``(col_names, neurons, metric_name)``.

    Matching is case-insensitive: an exact metric token wins, otherwise an
    unambiguous prefix match is accepted (so ``"Std"`` matches ``"StdDev"`` and
    ``"Int"`` matches ``"IntDen"``). Columns are ordered by neuron number and
    duplicate neurons are dropped.
    """
    m = str(metric).strip().lower()
    if not by_token:
        raise ValueError(
            "No columns of the form '<Metric><neuron>' (e.g. 'Mean7') or "
            "'<neuron>_<metric>' (e.g. '7_mean') were found in the CSV."
        )

    if m in by_token:
        key = m
    else:
        candidates = sorted(t for t in by_token if t.startswith(m))
        if len(candidates) == 1:
            key = candidates[0]
        elif len(candidates) > 1:
            names = [display[t] for t in candidates]
            raise ValueError(
                f"Metric '{metric}' is ambiguous; it matches {names}. "
                "Use a more specific name."
            )
        else:
            raise ValueError(
                f"Metric '{metric}' not found. Available metrics: "
                f"{[display[t] for t in sorted(by_token)]}."
            )

    seen = set()
    cols: List[str] = []
    neurons: List[int] = []
    for col, neuron in sorted(by_token[key], key=lambda t: t[1]):
        if neuron in seen:
            continue  # keep the first column for a given neuron number
        seen.add(neuron)
        cols.append(col)
        neurons.append(neuron)
    return cols, neurons, display[key]


def _chunk_rows(n_cols: int) -> int:
    """Rows per read chunk, sized so each chunk stays around ~50 MB."""
    return max(1000, min(200_000, int(50_000_000 / max(n_cols, 1) / 8)))


def _streaming_pearson(input_csv: str, sel_cols: List[str]) -> Tuple[np.ndarray, int]:
    """Two-pass, chunked Pearson correlation over *sel_cols*.

    Pass 1 accumulates column means; pass 2 accumulates centred cross-products.
    Centring before the cross-product avoids the catastrophic cancellation of the
    naive ``E[XX] - E[X]E[X]`` formula on traces with a large baseline. Peak
    memory is O(rows_per_chunk × cols) for the data plus O(cols²) for the
    accumulator — independent of the number of frames.
    """
    k = len(sel_cols)
    chunk_rows = _chunk_rows(k)

    # --- Pass 1: means (over rows with no NaN in the selected columns) ---
    n = 0
    col_sum = np.zeros(k, dtype=np.float64)
    for chunk in pd.read_csv(input_csv, usecols=sel_cols, chunksize=chunk_rows):
        x = chunk[sel_cols].to_numpy(dtype=np.float64)
        x = x[~np.isnan(x).any(axis=1)]
        if x.size == 0:
            continue
        n += x.shape[0]
        col_sum += x.sum(axis=0)
    if n < 2:
        raise ValueError("Not enough complete rows to compute a correlation.")
    mean = col_sum / n

    # --- Pass 2: centred cross-products (same rows dropped as pass 1) ---
    cross = np.zeros((k, k), dtype=np.float64)
    for chunk in pd.read_csv(input_csv, usecols=sel_cols, chunksize=chunk_rows):
        x = chunk[sel_cols].to_numpy(dtype=np.float64)
        x = x[~np.isnan(x).any(axis=1)]
        if x.size == 0:
            continue
        xc = x - mean
        cross += xc.T @ xc

    std = np.sqrt(np.clip(np.diag(cross) / n, 0.0, None))
    denom = np.outer(std, std)
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = (cross / n) / denom
    corr[~np.isfinite(corr)] = 0.0  # flat/constant traces have no correlation
    np.clip(corr, -1.0, 1.0, out=corr)
    np.fill_diagonal(corr, 1.0)
    return corr, n


def _save_heatmap(corr: np.ndarray, neurons: List[int], metric: str, path: str) -> None:
    """Render a heatmap of the correlation matrix (size-capped)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = len(neurons)
    size = min(max(4.0, n * 0.3), 20.0)  # cap so the figure never explodes
    fig, ax = plt.subplots(figsize=(size, size))
    im = ax.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_title(f"Pearson correlation — {metric} ({n} neurons)")
    if n <= 60:
        ax.set_xticks(range(n))
        ax.set_yticks(range(n))
        ax.set_xticklabels(neurons, rotation=90, fontsize=6)
        ax.set_yticklabels(neurons, fontsize=6)
    else:
        ax.set_xticks([])
        ax.set_yticks([])
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="Pearson r")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def run(params):
    input_csv = params["input_csv"]
    output_dir = params["output_dir"]
    metric = str(params.get("metric", "Mean"))

    if not os.path.isfile(input_csv):
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Reading columns: {os.path.basename(input_csv)}")
    header = pd.read_csv(input_csv, nrows=0)
    by_token, display = _detect_columns(header.columns)
    if by_token:
        summary = ", ".join(
            f"{display[t]} ({len(by_token[t])})" for t in sorted(by_token)
        )
        print(f"  Detected metrics: {summary}")

    sel_cols, neurons, token = _select_metric(by_token, display, metric)
    if len(sel_cols) < 2:
        raise ValueError(
            f"Metric '{metric}' has fewer than 2 neurons; at least 2 are needed "
            "to compute a correlation."
        )
    preview = neurons if len(neurons) <= 20 else neurons[:20] + ["..."]
    print(f"Correlating metric '{token}' over {len(neurons)} neurons: {preview}")
    print("PROGRESS:20")

    corr, n_rows = _streaming_pearson(input_csv, sel_cols)
    print(f"  Used {n_rows} complete frames")
    print("PROGRESS:70")

    corr_df = pd.DataFrame(corr, index=neurons, columns=neurons)
    base = os.path.splitext(os.path.basename(input_csv))[0]
    safe_metric = re.sub(r"[^A-Za-z0-9]+", "", token) or "metric"
    matrix_path = os.path.join(output_dir, f"{base}_pearson_{safe_metric}.csv")
    corr_df.to_csv(matrix_path, float_format="%.6f")
    print(f"Matrix saved: {matrix_path}")
    print("PROGRESS:85")

    outputs = {"matrix_csv": matrix_path}

    if len(neurons) > _HEATMAP_MAX_NEURONS:
        print(
            f"Skipping heatmap: {len(neurons)} neurons exceeds the "
            f"{_HEATMAP_MAX_NEURONS}-neuron limit for image rendering."
        )
    else:
        heatmap_path = os.path.join(output_dir, f"{base}_pearson_{safe_metric}.png")
        try:
            _save_heatmap(corr, neurons, token, heatmap_path)
            print(f"Heatmap saved: {heatmap_path}")
            outputs["heatmap_png"] = heatmap_path
        except Exception as exc:  # noqa: BLE001 - heatmap is best-effort
            print(f"Warning: could not render heatmap: {exc}")
    print("PROGRESS:100")

    return outputs


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pearson correlation matrix.")
    parser.add_argument("--input_csv", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--metric", default="Mean")
    args = parser.parse_args()
    print(run(vars(args)))
