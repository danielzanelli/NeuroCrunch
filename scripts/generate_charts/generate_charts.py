# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""generate_charts — Generates summary charts from processed traces.

Reads a CSV of traces (columns = cells, rows = time) and produces, in the output
folder:
  * traces_overlay.<fmt>  — all traces overlaid
  * traces_raster.<fmt>   — heatmap (raster) of cells × time
  * mean_trace.<fmt>      — mean trace ± deviation

The image format (png/svg/pdf) is configurable.

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


def _time_axis(df: pd.DataFrame, n: int):
    """Use time_s if available, otherwise the frame index."""
    for name in ("time_s", "time"):
        if name in df.columns:
            return df[name].to_numpy(dtype=float), "Time (s)"
    return np.arange(n, dtype=float), "Frame"


def run(params):
    input_csv = params["input_csv"]
    output_dir = params["output_dir"]
    fmt = params.get("format", "png")
    title = params.get("title", "") or "Trace summary"

    if not os.path.isfile(input_csv):
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")
    figures_dir = os.path.join(output_dir, "figures")
    os.makedirs(figures_dir, exist_ok=True)

    print(f"Reading traces: {os.path.basename(input_csv)}")
    df = pd.read_csv(input_csv)
    signal_cols = _signal_columns(df)
    if not signal_cols:
        raise ValueError("The CSV contains no numeric signal columns.")

    t, t_label = _time_axis(df, len(df))
    data = df[signal_cols].to_numpy(dtype=float)  # shape (frames, cells)
    print(f"  {len(signal_cols)} cells × {len(df)} frames")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    saved = []

    # 1) Overlay of all traces.
    fig, ax = plt.subplots(figsize=(10, 5))
    for j in range(data.shape[1]):
        ax.plot(t, data[:, j], linewidth=0.6, alpha=0.7)
    ax.set_title(f"{title} — overlaid traces")
    ax.set_xlabel(t_label)
    ax.set_ylabel("Fluorescence")
    p = os.path.join(figures_dir, f"traces_overlay.{fmt}")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)
    print("PROGRESS:40")

    # 2) Raster / heatmap of cells × time.
    fig, ax = plt.subplots(figsize=(10, max(3, data.shape[1] * 0.2)))
    im = ax.imshow(
        data.T, aspect="auto", cmap="viridis",
        extent=[float(t[0]), float(t[-1]), data.shape[1], 0],
    )
    ax.set_title(f"{title} — raster")
    ax.set_xlabel(t_label)
    ax.set_ylabel("Cell")
    fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02, label="Fluorescence")
    p = os.path.join(figures_dir, f"traces_raster.{fmt}")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)
    print("PROGRESS:70")

    # 3) Mean trace ± deviation.
    mean = np.nanmean(data, axis=1)
    std = np.nanstd(data, axis=1)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(t, mean, color="C0", label="mean")
    ax.fill_between(t, mean - std, mean + std, color="C0", alpha=0.25, label="± deviation")
    ax.set_title(f"{title} — mean trace")
    ax.set_xlabel(t_label)
    ax.set_ylabel("Fluorescence")
    ax.legend(loc="upper right")
    p = os.path.join(figures_dir, f"mean_trace.{fmt}")
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)
    print("PROGRESS:100")

    print(f"Charts saved to: {figures_dir}")
    for s in saved:
        print(f"  {os.path.basename(s)}")

    return {"figures_dir": figures_dir}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generates summary charts.")
    parser.add_argument("--input_csv", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--format", default="png", choices=["png", "svg", "pdf"])
    parser.add_argument("--title", default="")
    args = parser.parse_args()
    print(run(vars(args)))
