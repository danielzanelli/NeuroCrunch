# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""pearson_matrix — Pearson correlation matrix between traces.

Reads a CSV of traces (columns = cells, rows = time), computes the Pearson
correlation matrix between all cells and saves:
  * matrix_csv   — the correlation matrix as a CSV
  * heatmap_png  — a heatmap of the matrix

``correlation_threshold`` is used to report how many cell pairs exceed that
absolute correlation value.

Contract: see README.md > "<script_name>.py — execution contract".
"""
from __future__ import annotations

import os
import numpy as np
import pandas as pd

IGNORED_COLUMNS = {"", "Slice", "frame", "time_s", "time"}


def _signal_columns(df: pd.DataFrame):
    return [
        c for c in df.columns
        if str(c).strip() not in IGNORED_COLUMNS and pd.api.types.is_numeric_dtype(df[c])
    ]


def run(params):
    input_csv = params["input_csv"]
    output_dir = params["output_dir"]
    threshold = float(params.get("correlation_threshold", 0.5))

    if not os.path.isfile(input_csv):
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Reading traces: {os.path.basename(input_csv)}")
    df = pd.read_csv(input_csv)
    signal_cols = _signal_columns(df)
    if len(signal_cols) < 2:
        raise ValueError("At least 2 signal columns are needed to correlate.")

    print(f"  Computing Pearson correlation between {len(signal_cols)} cells...")
    print("PROGRESS:30")
    corr = df[signal_cols].corr(method="pearson")

    base = os.path.splitext(os.path.basename(input_csv))[0]
    matrix_path = os.path.join(output_dir, f"{base}_pearson.csv")
    corr.to_csv(matrix_path)
    print(f"Matrix saved: {matrix_path}")
    print("PROGRESS:60")

    # Count pairs (upper triangle) that exceed the threshold in absolute value.
    n = len(signal_cols)
    upper = np.triu(np.ones((n, n), dtype=bool), k=1)
    vals = corr.to_numpy()
    n_pairs = int(np.sum((np.abs(vals) >= threshold) & upper))
    total_pairs = n * (n - 1) // 2
    print(f"Pairs with |correlation| >= {threshold}: {n_pairs} / {total_pairs}")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(max(4, n * 0.3), max(4, n * 0.3)))
    im = ax.imshow(vals, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_title("Pearson correlation matrix")
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(signal_cols, rotation=90, fontsize=6)
    ax.set_yticklabels(signal_cols, fontsize=6)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="Pearson r")
    heatmap_path = os.path.join(output_dir, f"{base}_pearson_heatmap.png")
    fig.savefig(heatmap_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Heatmap saved: {heatmap_path}")
    print("PROGRESS:100")

    return {"matrix_csv": matrix_path, "heatmap_png": heatmap_path}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Pearson correlation matrix.")
    parser.add_argument("--input_csv", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--correlation_threshold", type=float, default=0.5)
    args = parser.parse_args()
    print(run(vars(args)))
