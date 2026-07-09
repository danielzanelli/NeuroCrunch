# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""select_active — Selects active cells/traces by an activity threshold.

Reads a CSV of fluorescence traces (columns = cells/metrics, rows = time),
detects which traces show at least one activity event — a stretch of
``min_duration`` consecutive frames above ``mean + threshold_std·deviation`` — and
writes a CSV with the metadata columns (frame, time_s) plus only the traces
considered active. Preserves the format for the downstream scripts
(pearson_matrix, generate_charts).

Contract: see README.md > "<script_name>.py — execution contract".
"""
from __future__ import annotations

import os
import numpy as np
import pandas as pd

# Metadata columns that are not cell signals (kept as-is).
IGNORED_COLUMNS = {"", "Slice", "frame", "time_s", "time"}


def _signal_columns(df: pd.DataFrame):
    """Return the signal columns: numeric and not metadata."""
    cols = []
    for col in df.columns:
        if str(col).strip() in IGNORED_COLUMNS:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            cols.append(col)
    return cols


def _max_run_above(values: np.ndarray, threshold: float) -> int:
    """Length of the longest stretch of consecutive values above the threshold.

    NaNs count as 'below' (they break the stretch).
    """
    with np.errstate(invalid="ignore"):
        above = (values > threshold) & ~np.isnan(values)
    best = run = 0
    for flag in above:
        run = run + 1 if flag else 0
        if run > best:
            best = run
    return best


def run(params):
    input_csv = params["input_csv"]
    output_dir = params["output_dir"]
    threshold_std = float(params.get("threshold_std", 2.5))
    min_duration = int(params.get("min_duration", 3))

    if not os.path.isfile(input_csv):
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Reading traces: {os.path.basename(input_csv)}")
    df = pd.read_csv(input_csv)

    signal_cols = _signal_columns(df)
    meta_cols = [c for c in df.columns if c not in signal_cols]
    if not signal_cols:
        raise ValueError("The CSV contains no numeric signal columns.")

    print(f"  Signal columns: {len(signal_cols)} | metadata: {len(meta_cols)}")
    print(f"  Criterion: > mean + {threshold_std}·deviation for >= {min_duration} frames")

    active_cols = []
    total = len(signal_cols)
    for i, col in enumerate(signal_cols, start=1):
        x = df[col].to_numpy(dtype=float)
        # Robust baseline: median + k·σ_MAD. Using median/MAD instead of mean/std
        # keeps the threshold from being inflated by the events themselves (a few
        # large transients would otherwise raise std and mask real activity).
        median = np.nanmedian(x)
        mad = np.nanmedian(np.abs(x - median))
        robust_std = 1.4826 * mad
        if not robust_std or np.isnan(robust_std):
            robust_std = np.nanstd(x)  # fallback for degenerate/flat traces
        threshold = median + threshold_std * robust_std
        if _max_run_above(x, threshold) >= min_duration:
            active_cols.append(col)

        if total and (i % max(1, total // 10) == 0 or i == total):
            print(f"PROGRESS:{i / total * 100:.0f}")

    print(f"Active cells: {len(active_cols)} / {total}")

    out_df = df[meta_cols + active_cols]
    base = os.path.splitext(os.path.basename(input_csv))[0]
    active_path = os.path.join(output_dir, f"{base}_active.csv")
    out_df.to_csv(active_path, index=False)
    print(f"Active-cells CSV saved: {active_path}")

    return {"active_csv": active_path}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Selects active cells/traces.")
    parser.add_argument("--input_csv", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--threshold_std", type=float, default=2.5)
    parser.add_argument("--min_duration", type=int, default=3)
    args = parser.parse_args()
    print(run(vars(args)))
