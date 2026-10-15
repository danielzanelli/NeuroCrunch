# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""select_active — Selects active cells/traces by an activity threshold.

Reads a CSV of fluorescence traces (columns = cells/metrics, rows = time),
detects which traces show at least one activity event — a stretch of
``min_duration`` consecutive frames above a robust threshold
``median + threshold_std·(1.4826·MAD)`` (falling back to the standard deviation
for flat traces) — and writes a CSV with the metadata columns (frame, time_s)
plus only the traces
considered active. Preserves the format for the downstream scripts
(pearson_matrix, connectivity_graph).

The median and MAD are taken from a reference window, ``reference_start_s`` to
``reference_end_s`` (0 = the recording's end), which defaults to the whole
recording — e.g. a quiet pre-stimulus period. Times come from the CSV's
``time_s``/``time`` column, or from ``fps`` when it has neither.

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


def _robust_threshold(x: np.ndarray, threshold_std: float) -> float:
    """Activity threshold for one trace: median + k·(robust MAD).

    Using median/MAD instead of mean/std keeps the threshold from being inflated
    by the events themselves (a few large transients would otherwise raise std
    and mask real activity). Falls back to the standard deviation for flat traces
    where the MAD is zero.
    """
    median = np.nanmedian(x)
    mad = np.nanmedian(np.abs(x - median))
    robust_std = 1.4826 * mad
    if not robust_std or np.isnan(robust_std):
        robust_std = np.nanstd(x)  # fallback for degenerate/flat traces
    return median + threshold_std * robust_std


# The reference-window helpers mirror spike_analysis (scripts run in isolated
# namespaces, so they are duplicated rather than imported).


def parse_reference_window(params):
    """(start_s, end_s) of the reference window; end_s <= 0 means the recording's end."""
    start_s = float(params.get("reference_start_s", 0.0) or 0.0)
    end_s = float(params.get("reference_end_s", 0.0) or 0.0)
    if start_s < 0.0:
        raise ValueError(f"reference_start_s must be >= 0 (got {start_s}).")
    if end_s > 0.0 and end_s <= start_s:
        raise ValueError(
            f"reference_end_s ({end_s}) must be greater than reference_start_s ({start_s}), "
            "or 0 to use the rest of the recording."
        )
    return start_s, end_s


def _reference_mask(t: np.ndarray, start_s: float, end_s: float) -> np.ndarray:
    """Samples inside the reference window [start_s, end_s] (end_s <= 0 = no end)."""
    mask = t >= start_s
    if end_s > 0.0:
        mask &= t <= end_s
    if np.count_nonzero(mask) < 3:
        raise ValueError(
            f"The reference window {start_s:g}-{end_s:g} s holds fewer than 3 samples; "
            "widen it or check the time axis."
            if end_s > 0.0
            else f"The reference window from {start_s:g} s holds fewer than 3 samples; "
            "lower its start or check the time axis."
        )
    return mask


def _time_axis(df: pd.DataFrame, fps: float):
    """The recording's time axis and its source column (None when derived from fps)."""
    n_rows = df.shape[0]
    for name in ("time_s", "time"):
        if name in df.columns:
            t = pd.to_numeric(df[name], errors="coerce").to_numpy(dtype=float)
            if t.shape[0] == n_rows and np.isfinite(t).all():
                return t, name
    return np.arange(n_rows, dtype=float) / fps, None


def run(params):
    input_csv = params["input_csv"]
    output_dir = params["output_dir"]
    threshold_std = float(params.get("threshold_std", 2.5))
    min_duration = int(params.get("min_duration", 3))
    reference_start_s, reference_end_s = parse_reference_window(params)
    fps = float(params.get("fps", 10.0))
    if fps <= 0:
        raise ValueError(f"fps must be positive (got {fps}).")

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
    print(f"  Criterion: > median + {threshold_std}·(robust MAD) for >= {min_duration} frames")

    t, time_column = _time_axis(df, fps)
    reference = _reference_mask(t, reference_start_s, reference_end_s)
    time_source = f"'{time_column}' column" if time_column else f"fps={fps}"
    if reference.all():
        print(f"  Median/MAD reference: the whole recording (time from {time_source})")
    else:
        print(
            f"  Median/MAD reference: {t[reference][0]:g}-{t[reference][-1]:g} s "
            f"({np.count_nonzero(reference)} of {t.shape[0]} samples, time from {time_source})"
        )

    active_cols = []
    total = len(signal_cols)
    for i, col in enumerate(signal_cols, start=1):
        x = df[col].to_numpy(dtype=float)
        threshold = _robust_threshold(x[reference], threshold_std)
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


def preview(sample, params):
    """Classify one trace for the interactive threshold preview.

    Pure and headless — no file I/O, no plotting. The app's Filter-preview tab
    feeds one (already-decimated) trace and the current parameter values, then
    overlays the returned series so the user can watch which traces clear the
    threshold as they tune it. It reuses the same core as ``run()`` so the
    preview matches the batch result.

    The trace is returned under either ``"active"`` or ``"inactive"`` — whichever
    class it would fall into at the current threshold — plus a flat ``"threshold"``
    line at the cutoff. A trace only carries the key for its own class, so the
    tab's Active / Inactive checkboxes separate the surviving traces from the
    dropped ones, while ``"threshold"`` shows every trace's cutoff line.

    Note: the tab decimates each trace before calling this, so the ``threshold``
    value (median + k·MAD) is stable but the ``min_duration`` consecutive-frame
    test runs on the decimated trace — the active/inactive call is therefore
    approximate right at the boundary.

    The reference window is placed on the sample's time axis: the CSV's own
    ``"t"`` (seconds) when the app passes one, else the plot's x values ``"x"``
    (then frame numbers) divided by ``fps``. Its first and last samples are
    returned as vertical markers (``"_vlines"``, in ``"x"`` units).

    Returns ``{}`` for an all-NaN or empty trace.
    """
    y = np.asarray(sample.get("y"), dtype=float).ravel()
    nan = np.isnan(y)
    if nan.all() or y.shape[0] < 1:
        return {}
    if nan.any():
        valid = np.flatnonzero(~nan)
        y[nan] = np.interp(np.flatnonzero(nan), valid, y[valid])

    threshold_std = float(params.get("threshold_std", 2.5))
    min_duration = int(params.get("min_duration", 3))
    reference_start_s, reference_end_s = parse_reference_window(params)
    fps = float(params.get("fps", 10.0))
    if fps <= 0:
        raise ValueError(f"fps must be positive (got {fps}).")

    x = sample.get("x")
    x = None if x is None else np.asarray(x, dtype=float).ravel()
    if x is None or x.shape[0] != y.shape[0]:
        x = np.arange(y.shape[0], dtype=float)
    t = sample.get("t")
    t = None if t is None else np.asarray(t, dtype=float).ravel()
    if t is None or t.shape[0] != y.shape[0] or not np.isfinite(t).all():
        t = x / fps

    reference = _reference_mask(t, reference_start_s, reference_end_s)
    threshold = _robust_threshold(y[reference], threshold_std)
    active = _max_run_above(y, threshold) >= min_duration

    key = "active" if active else "inactive"
    line = [float(threshold)] * y.shape[0]
    x_ref = x[reference]
    return {
        key: y.tolist(),
        "threshold": line,
        "_vlines": {
            "SD reference start": float(x_ref[0]),
            "SD reference end": float(x_ref[-1]),
        },
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Selects active cells/traces.")
    parser.add_argument("--input_csv", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--threshold_std", type=float, default=2.5)
    parser.add_argument("--min_duration", type=int, default=3)
    parser.add_argument("--reference_start_s", type=float, default=0.0)
    parser.add_argument("--reference_end_s", type=float, default=0.0)
    parser.add_argument("--fps", type=float, default=10.0)
    args = parser.parse_args()
    print(run(vars(args)))
