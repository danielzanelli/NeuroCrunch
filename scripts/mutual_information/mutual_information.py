# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""mutual_information — Mutual-information matrix between neuron traces.

Reads a CSV of traces (columns = per-neuron metrics, rows = time) and computes
the pairwise mutual information (MI) between neurons for a single chosen metric.
MI captures any statistical dependence between two signals — including non-linear
relations that Pearson correlation misses — at the cost of needing a density
estimate, which here is a simple equal-width histogram of each signal.

The output is the *normalised* MI, NMI(X,Y) = I(X,Y) / sqrt(H(X)·H(Y)), which
lies in [0, 1] (0 = independent, 1 = fully dependent). Normalising makes the
matrix a drop-in replacement for the Pearson matrix: it shares the same [0, 1]
scale, feeds ``connectivity_graph`` unchanged, and is thresholded later in the
viewer rather than here.

Column names are expected to carry a metric name and a neuron number, in either
order, e.g. ``Mean7``/``Max7`` (ImageJ Multi-Measure style) or ``7_mean``
(NeuroCrunch's generate_signals style). The neuron number identifies the cell —
because upstream steps (e.g. select_active) may drop cells, the numbers can skip
values, but each metric is present for every kept neuron. Only the columns for
the selected metric are used, and the resulting matrix is labelled by neuron
number so the connectivity graph can map each node back to its ROI.

Outputs (in the output folder):
  * <name>_mutualinfo_<metric>.csv  — the NMI matrix (rows/cols = neurons)
  * <name>_mutualinfo_<metric>.png  — a heatmap of the matrix (skipped if huge)

The signal range is found in a first streaming pass over row chunks; a second
pass digitises each chunk to compact bin indices, so raw float frames are never
all held in memory at once. Peak memory is O(rows × neurons) bytes of int8 bin
indices plus O(neurons²) for the matrix.

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


def _auto_bins(n_rows: int) -> int:
    """Pick a histogram bin count from the sample size (Rice-style rule).

    More frames support finer bins, but too many bins on too few frames
    over-estimates dependence (every point lands in its own cell). Kept modest
    (8..64) to keep the joint histograms well populated and the matrix cheap.
    """
    b = int(round(2.0 * n_rows ** (1.0 / 3.0)))
    return int(np.clip(b, 8, 64))


def _streaming_mutual_information(
    input_csv: str, sel_cols: List[str], bins: int
) -> Tuple[np.ndarray, int, int]:
    """Two-pass, chunked normalised mutual information over *sel_cols*.

    Pass 1 finds each column's [min, max] range; pass 2 digitises each chunk
    into equal-width bin indices (dropping rows with any NaN, same as pass 1)
    and stacks the compact int8 codes. Marginal and joint histograms then give
    ``NMI = I(X,Y) / sqrt(H(X)·H(Y))`` in [0, 1] for every neuron pair.
    """
    k = len(sel_cols)
    chunk_rows = _chunk_rows(k)

    # --- Pass 1: per-column min/max over complete rows ---
    col_min = np.full(k, np.inf, dtype=np.float64)
    col_max = np.full(k, -np.inf, dtype=np.float64)
    for chunk in pd.read_csv(input_csv, usecols=sel_cols, chunksize=chunk_rows):
        x = chunk[sel_cols].to_numpy(dtype=np.float64)
        x = x[~np.isnan(x).any(axis=1)]
        if x.size == 0:
            continue
        col_min = np.minimum(col_min, x.min(axis=0))
        col_max = np.maximum(col_max, x.max(axis=0))
    if not np.isfinite(col_min).all():
        raise ValueError("Not enough complete rows to compute mutual information.")

    span = col_max - col_min
    # Constant columns (zero span) have zero entropy and no information; give
    # them a dummy positive span so digitising doesn't divide by zero — every
    # value simply falls in bin 0.
    safe_span = np.where(span > 0, span, 1.0)

    # --- Pass 2: digitise each chunk to compact bin indices ---
    codes_parts: List[np.ndarray] = []
    for chunk in pd.read_csv(input_csv, usecols=sel_cols, chunksize=chunk_rows):
        x = chunk[sel_cols].to_numpy(dtype=np.float64)
        x = x[~np.isnan(x).any(axis=1)]
        if x.size == 0:
            continue
        idx = ((x - col_min) / safe_span * bins).astype(np.int64)
        np.clip(idx, 0, bins - 1, out=idx)  # the max value maps just past the top
        codes_parts.append(idx.astype(np.int8))
    codes = np.concatenate(codes_parts, axis=0)
    n = codes.shape[0]
    if n < 2:
        raise ValueError("Not enough complete rows to compute mutual information.")

    # Marginal histograms and entropies (nats), one row per neuron.
    marg = np.zeros((k, bins), dtype=np.float64)
    for i in range(k):
        marg[i] = np.bincount(codes[:, i], minlength=bins)
    p_marg = marg / n
    ent = _entropy_rows(p_marg)  # H(X_i)

    mi = np.zeros((k, k), dtype=np.float64)
    codes_i = codes.astype(np.int64)
    for i in range(k):
        ci = codes_i[:, i]
        for j in range(i + 1, k):
            joint = np.bincount(ci * bins + codes_i[:, j], minlength=bins * bins)
            p_joint = joint.reshape(bins, bins) / n
            mi[i, j] = mi[j, i] = _mutual_info_from_joint(p_joint, ent[i], ent[j])

    np.fill_diagonal(mi, 1.0)  # a signal is perfectly dependent on itself
    return mi, n, bins


def _entropy_rows(p: np.ndarray) -> np.ndarray:
    """Shannon entropy (nats) of each row of a probability matrix."""
    with np.errstate(divide="ignore", invalid="ignore"):
        terms = np.where(p > 0, p * np.log(p), 0.0)
    return -terms.sum(axis=1)


def _mutual_info_from_joint(p_joint: np.ndarray, h_x: float, h_y: float) -> float:
    """Normalised MI in [0, 1] from a joint distribution and marginal entropies."""
    if h_x <= 0.0 or h_y <= 0.0:
        return 0.0  # a constant signal carries no information about anything
    px = p_joint.sum(axis=1)
    py = p_joint.sum(axis=0)
    h_xy = _entropy_rows(p_joint.reshape(1, -1))[0]  # joint entropy H(X,Y)
    info = h_x + h_y - h_xy  # I(X,Y) = H(X) + H(Y) - H(X,Y)
    nmi = info / np.sqrt(h_x * h_y)
    return float(np.clip(nmi, 0.0, 1.0))


def _save_heatmap(mi: np.ndarray, neurons: List[int], metric: str, path: str) -> None:
    """Render a heatmap of the mutual-information matrix (size-capped)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = len(neurons)
    size = min(max(4.0, n * 0.3), 20.0)  # cap so the figure never explodes
    fig, ax = plt.subplots(figsize=(size, size))
    im = ax.imshow(mi, cmap="magma", vmin=0, vmax=1)
    ax.set_title(f"Mutual information — {metric} ({n} neurons)")
    if n <= 60:
        ax.set_xticks(range(n))
        ax.set_yticks(range(n))
        ax.set_xticklabels(neurons, rotation=90, fontsize=6)
        ax.set_yticklabels(neurons, fontsize=6)
    else:
        ax.set_xticks([])
        ax.set_yticks([])
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="Normalised MI")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def run(params):
    input_csv = params["input_csv"]
    output_dir = params["output_dir"]
    metric = str(params.get("metric", "Mean"))
    bins_param = params.get("bins", "auto")

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
            "to compute mutual information."
        )

    # An explicit bin count wins; "auto" (or anything non-numeric) defers to a
    # sample-size rule computed once the row count is known.
    bins = None
    try:
        bins = int(bins_param)
    except (TypeError, ValueError):
        bins = None
    if bins is not None and bins < 2:
        raise ValueError("Bin count must be at least 2.")

    preview = neurons if len(neurons) <= 20 else neurons[:20] + ["..."]
    print(f"Computing MI for metric '{token}' over {len(neurons)} neurons: {preview}")
    print("PROGRESS:20")

    if bins is None:
        # A cheap frame count from a single column drives the auto bin rule.
        n_est = sum(
            len(c)
            for c in pd.read_csv(
                input_csv, usecols=[sel_cols[0]], chunksize=_chunk_rows(1)
            )
        )
        bins = _auto_bins(max(n_est, 2))
        print(f"  Auto-selected {bins} histogram bins for ~{n_est} frames")
    else:
        print(f"  Using {bins} histogram bins")

    mi, n_rows, bins = _streaming_mutual_information(input_csv, sel_cols, bins)
    print(f"  Used {n_rows} complete frames")
    print("PROGRESS:70")

    mi_df = pd.DataFrame(mi, index=neurons, columns=neurons)
    base = os.path.splitext(os.path.basename(input_csv))[0]
    safe_metric = re.sub(r"[^A-Za-z0-9]+", "", token) or "metric"
    matrix_path = os.path.join(output_dir, f"{base}_mutualinfo_{safe_metric}.csv")
    mi_df.to_csv(matrix_path, float_format="%.6f")
    print(f"Matrix saved: {matrix_path}")
    print("PROGRESS:85")

    outputs = {"matrix_csv": matrix_path}

    if len(neurons) > _HEATMAP_MAX_NEURONS:
        print(
            f"Skipping heatmap: {len(neurons)} neurons exceeds the "
            f"{_HEATMAP_MAX_NEURONS}-neuron limit for image rendering."
        )
    else:
        heatmap_path = os.path.join(output_dir, f"{base}_mutualinfo_{safe_metric}.png")
        try:
            _save_heatmap(mi, neurons, token, heatmap_path)
            print(f"Heatmap saved: {heatmap_path}")
            outputs["heatmap_png"] = heatmap_path
        except Exception as exc:  # noqa: BLE001 - heatmap is best-effort
            print(f"Warning: could not render heatmap: {exc}")
    print("PROGRESS:100")

    return outputs


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Mutual-information matrix.")
    parser.add_argument("--input_csv", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--metric", default="Mean")
    parser.add_argument("--bins", default="auto")
    args = parser.parse_args()
    print(run(vars(args)))
