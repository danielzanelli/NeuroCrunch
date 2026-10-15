# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""spike_analysis — Measures every spike in each processed signal.

Reads a CSV of processed traces (ALS-corrected and/or band-passed, so spikes sit
above a flat baseline plus noise), optionally together with the ImageJ/FIJI ROI
archive the signals were extracted from, and writes one row per detected spike.
When the ROI archive is given, each row also carries its ROI centroid (x, y);
without it the x/y columns are left out.

Spikes are found with the same robust rule ``select_active`` uses — a run of
``min_duration`` consecutive frames above ``median + k·1.4826·MAD`` — and are
then measured with the **half-peak method**: each spike's start and end are the
crossings of a fixed fraction of its own amplitude (0.5 = half maximum) on the
rising and falling flank, linearly interpolated between samples so the times are
not quantised to the frame grid. ``end - start`` is therefore the FWHM, and the
area under the curve is integrated over that same window so every row's area
matches its own start/end times.

One spike is reported per run above the detection threshold, so two spikes that
never drop back below it — a doublet on a shared plateau — are measured as a
single spike at the higher of the two. Lowering ``threshold_std`` separates them
whenever the trace dips between them.

The baseline (median) and noise SD (1.4826·MAD) are taken from a reference
window, ``reference_start_s`` to ``reference_end_s`` (0 = the recording's end),
which defaults to the whole recording — e.g. a quiet pre-stimulus period.

Output (in the output folder):
  * <name>_spikes.xlsx (or .csv, per ``output_format``) — one row per spike

Contract: see README.md > "<script_name>.py — execution contract".
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd

try:
    import read_roi
except ImportError:  # pragma: no cover - read_roi is a bundled dependency
    read_roi = None


# Scripts run in isolated namespaces, so the column-parsing helpers (from
# band_pass_filter) and the ROI helpers (from connectivity_graph) are duplicated
# here rather than imported. This is the house convention.


# ---------------------------------------------------------------------------
# Column parsing
# ---------------------------------------------------------------------------

IGNORED_COLUMNS = {"", "Slice", "frame", "time_s", "time"}


def _is_ignored_column(column: str) -> bool:
    return str(column).strip() in IGNORED_COLUMNS


# Signal columns are "<feature>_<neuron>" (e.g. "Mean_7", "dF/F0_7") or
# "<neuron>_<feature>" (e.g. "7_Mean"), as set by the column_order parameter.
# The feature name may hold any character except "_", which separates the parts.
COLUMN_ORDERS = ("feature_neuron", "neuron_feature")


def parse_column_order(value: Any) -> str:
    column_order = str(value or "feature_neuron").strip().lower()
    if column_order not in COLUMN_ORDERS:
        raise ValueError(
            f"column_order must be one of {', '.join(COLUMN_ORDERS)} (got {value})."
        )
    return column_order


def split_metric_and_index(column: str, column_order: str) -> Tuple[str, int]:
    parts = str(column).strip().split("_")
    if len(parts) == 2:
        metric_name, index = parts if column_order == "feature_neuron" else parts[::-1]
        if metric_name and index.isascii() and index.isdigit():
            return metric_name, int(index)

    expected = "<feature>_<neuron>" if column_order == "feature_neuron" else "<neuron>_<feature>"
    raise ValueError(f"Column name '{column}' does not match the pattern '{expected}'")


def _iter_signal_columns(columns: Iterable[str], column_order: str) -> Tuple[List[str], List[str]]:
    signal_columns: List[str] = []
    skipped_columns: List[str] = []

    for col in columns:
        if _is_ignored_column(col):
            continue
        try:
            split_metric_and_index(col, column_order)
            signal_columns.append(col)
        except ValueError:
            skipped_columns.append(col)

    return signal_columns, skipped_columns


def get_metrics_and_indices(df: pd.DataFrame, column_order: str) -> Tuple[List[str], List[int]]:
    metrics: Set[str] = set()
    indices: Set[int] = set()

    signal_columns, _ = _iter_signal_columns(df.columns, column_order)
    for col in signal_columns:
        metric, idx = split_metric_and_index(col, column_order)
        metrics.add(metric)
        indices.add(idx)

    return sorted(metrics), sorted(indices)


def parse_metrics_param(metrics_param: str | None, available_metrics: Sequence[str]) -> List[str]:
    if not metrics_param:
        return list(available_metrics)

    requested = [m.strip() for m in metrics_param.split(",") if m.strip()]
    if not requested:
        return list(available_metrics)

    available_by_lower = {m.lower(): m for m in available_metrics}
    invalid = [m for m in requested if m.lower() not in available_by_lower]
    if invalid:
        raise ValueError(
            "Metric(s) not found in the CSV: "
            + ", ".join(invalid)
            + ". Available metrics: "
            + ", ".join(available_metrics)
        )

    # Preserve user order while resolving to the canonical metric spelling in the CSV.
    return [available_by_lower[m.lower()] for m in requested]


def build_target_columns(
    df: pd.DataFrame, selected_metrics: Iterable[str], column_order: str
) -> List[str]:
    metric_set = set(selected_metrics)
    target_cols: List[str] = []

    signal_columns, _ = _iter_signal_columns(df.columns, column_order)
    for col in signal_columns:
        metric, _ = split_metric_and_index(col, column_order)
        if metric in metric_set:
            target_cols.append(col)

    if not target_cols:
        raise ValueError("No columns found for the selected metrics.")

    return target_cols


# ---------------------------------------------------------------------------
# ROI geometry and mapping
# ---------------------------------------------------------------------------


def _roi_centroid(roi: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Return the (x, y) centroid of a single read_roi ROI, or None."""
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
    return names, [_roi_centroid(rois[name]) for name in names]


def _map_columns_to_rois(
    columns: Sequence[str], n_rois: int, column_order: str
) -> Tuple[List[Optional[int]], str]:
    """Map each signal column to a 0-based ROI index.

    *Indexed* — the neuron number carried by the column name (``Mean_7`` or
    ``7_Mean``, per ``column_order``, means ROI 7) used as a 1-based ROI index. This survives
    ``select_active`` dropping cells, since a surviving column keeps its original
    number, and it maps several metrics of the same cell to the same ROI.

    *Positional* — otherwise column *i* falls back to ROI *i*.
    """
    parsed: List[Optional[int]] = []
    for col in columns:
        try:
            _, idx = split_metric_and_index(str(col), column_order)
        except ValueError:
            idx = None
        parsed.append(idx)

    if parsed and all(p is not None and 1 <= p <= n_rois for p in parsed):
        return [p - 1 for p in parsed], "indexed"

    return [i if i < n_rois else None for i in range(len(columns))], "positional"


# ---------------------------------------------------------------------------
# Spike detection and measurement
# ---------------------------------------------------------------------------


def _interpolate_nans(y: np.ndarray) -> Optional[np.ndarray]:
    """Fill gaps by linear interpolation. Returns None for an all-NaN trace."""
    nan_mask = np.isnan(y)
    if nan_mask.all():
        return None
    if nan_mask.any():
        valid_idx = np.flatnonzero(~nan_mask)
        y = y.copy()
        y[nan_mask] = np.interp(np.flatnonzero(nan_mask), valid_idx, y[valid_idx])
    return y


def parse_reference_window(params: Dict[str, Any]) -> Tuple[float, float]:
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


def _robust_baseline(y: np.ndarray) -> Tuple[float, float]:
    """Return (baseline, sigma) as median and 1.4826·MAD, std as a fallback."""
    baseline = float(np.nanmedian(y))
    mad = float(np.nanmedian(np.abs(y - baseline)))
    sigma = 1.4826 * mad
    if not np.isfinite(sigma) or sigma <= 0.0:
        sigma = float(np.nanstd(y))
    return baseline, sigma


def _find_apexes(y: np.ndarray, threshold: float, min_duration: int) -> List[int]:
    """Index of the maximum of every run of >= min_duration frames above threshold."""
    above = y > threshold
    if not above.any():
        return []

    edges = np.diff(np.concatenate(([False], above, [False])).astype(np.int8))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)  # exclusive
    keep = (ends - starts) >= min_duration

    return [int(s + np.argmax(y[s:e])) for s, e in zip(starts[keep], ends[keep])]


def _search_bounds(y: np.ndarray, apexes: Sequence[int]) -> List[Tuple[int, int]]:
    """How far each apex's flank walk may travel: the minimum between neighbours.

    Without this, one broad spike could swallow the next when the trace never
    descends to the half level between them.
    """
    n = y.shape[0]
    bounds: List[Tuple[int, int]] = []
    for i, apex in enumerate(apexes):
        if i == 0:
            left = 0
        else:
            prev = apexes[i - 1]
            left = prev + int(np.argmin(y[prev:apex + 1]))
        if i == len(apexes) - 1:
            right = n - 1
        else:
            nxt = apexes[i + 1]
            right = apex + int(np.argmin(y[apex:nxt + 1]))
        bounds.append((left, right))
    return bounds


def _cross_time(t: np.ndarray, y: np.ndarray, a: int, b: int, level: float) -> float:
    """Time at which the segment between samples a and b crosses ``level``."""
    dy = y[b] - y[a]
    if dy == 0.0:
        return float(t[b])
    frac = min(max((level - y[a]) / dy, 0.0), 1.0)
    return float(t[a] + frac * (t[b] - t[a]))


def _measure_spike(
    y: np.ndarray,
    t: np.ndarray,
    apex: int,
    left: int,
    right: int,
    baseline: float,
    height_fraction: float,
) -> Optional[Dict[str, Any]]:
    """Measure one spike by the half-peak method.

    The apex is strictly above the half level (it cleared the detection
    threshold and ``height_fraction`` < 1), so both flank walks start below it.
    Returns None when a flank never drops to the half level within its search
    bound: the spike is clipped by the recording edge or runs into its
    neighbour, so it cannot be measured.
    """
    amplitude = float(y[apex] - baseline)
    half_level = baseline + height_fraction * amplitude

    # Rising flank: last sample at or below the half level before the apex.
    j = None
    for i in range(apex, left - 1, -1):
        if y[i] <= half_level:
            j = i
            break

    # Falling flank: first sample at or below the half level after the apex.
    k = None
    for i in range(apex, right + 1):
        if y[i] <= half_level:
            k = i
            break

    if j is None or k is None:
        return None

    start_s = _cross_time(t, y, j, j + 1, half_level)
    end_s = _cross_time(t, y, k - 1, k, half_level)

    # Area over exactly the reported window, with the interpolated crossings
    # spliced in as endpoints so the area matches the reported start/end times.
    t_seg = np.concatenate(([start_s], t[j + 1:k], [end_s]))
    y_seg = np.concatenate(([half_level], y[j + 1:k], [half_level]))
    auc = float(np.trapezoid(y_seg - baseline, x=t_seg))

    return {
        "start_s": start_s,
        "end_s": end_s,
        "width_s": end_s - start_s,
        "spike_time_s": float(t[apex]),
        "max_height": amplitude,
        "auc": auc,
        # Sample span and level of the window, for the calibration preview.
        "lo_idx": j,
        "hi_idx": k,
        "half_level": half_level,
    }


def analyze_trace(
    y: np.ndarray,
    t: np.ndarray,
    *,
    threshold_std: float,
    height_fraction: float,
    min_duration: int,
    reference: Optional[np.ndarray] = None,
) -> List[Dict[str, Any]]:
    """Detect and measure every spike in one trace.

    The baseline and noise SD come from the samples selected by the boolean
    mask *reference* (the whole trace when None); spikes are searched for over
    the whole trace either way.

    Returns a list of per-spike dicts (empty when the trace is flat, unusable, or
    simply has no spike above the threshold).
    """
    baseline, sigma = _robust_baseline(y if reference is None else y[reference])
    if not np.isfinite(sigma) or sigma <= 0.0:
        return []

    threshold = baseline + threshold_std * sigma
    apexes = _find_apexes(y, threshold, min_duration)
    if not apexes:
        return []

    bounds = _search_bounds(y, apexes)
    spikes = []
    for apex, (left, right) in zip(apexes, bounds):
        spike = _measure_spike(y, t, apex, left, right, baseline, height_fraction)
        if spike is None:
            continue
        spike["spike_index"] = len(spikes) + 1
        spikes.append(spike)
    return spikes


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

OUTPUT_COLUMNS = [
    "signal",
    "spike_index",
    "start_s",
    "end_s",
    "width_s",
    "spike_time_s",
    "max_height",
    "auc",
    "x",
    "y",
]


def _time_axis(df: pd.DataFrame, n_rows: int, fps: float) -> Tuple[np.ndarray, Optional[str]]:
    """The recording's time axis: the CSV's own column when it has one."""
    for name in ("time_s", "time"):
        if name in df.columns:
            t = pd.to_numeric(df[name], errors="coerce").to_numpy(dtype=float)
            if t.shape[0] == n_rows and np.isfinite(t).all():
                return t, name
    return np.arange(n_rows, dtype=float) / fps, None


def main(params: Dict[str, Any]) -> Dict[str, Any]:
    input_csv = os.path.abspath(os.path.normpath(params["input_csv"]))
    roi_zip_param = str(params.get("roi_zip") or "").strip()
    roi_zip = os.path.abspath(os.path.normpath(roi_zip_param)) if roi_zip_param else None
    output_dir = os.path.abspath(os.path.normpath(params["output_dir"]))
    column_order = parse_column_order(params.get("column_order"))

    threshold_std = float(params.get("threshold_std", 3.0))
    height_fraction = float(params.get("height_fraction", 0.5))
    min_duration = int(params.get("min_duration", 3))
    reference_start_s, reference_end_s = parse_reference_window(params)
    fps = float(params.get("fps", 10.0))
    output_format = str(params.get("output_format", "xlsx")).lower()

    if output_format not in ("xlsx", "csv"):
        raise ValueError(f"output_format must be 'xlsx' or 'csv' (got {output_format}).")
    if not 0.0 < height_fraction < 1.0:
        raise ValueError(f"height_fraction must be between 0 and 1 (got {height_fraction}).")
    if fps <= 0:
        raise ValueError(f"fps must be positive (got {fps}).")
    if not os.path.isfile(input_csv):
        raise FileNotFoundError(f"input_csv not found: {input_csv}")
    if roi_zip and not os.path.isfile(roi_zip):
        raise FileNotFoundError(f"ROI file not found: {roi_zip}")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Loading CSV: {input_csv}")
    df = pd.read_csv(input_csv)
    print(f"CSV loaded: {df.shape[0]} rows x {df.shape[1]} columns")
    if df.shape[0] < 3:
        raise ValueError("The input CSV needs at least 3 rows to measure a spike.")

    signal_columns, skipped_columns = _iter_signal_columns(df.columns, column_order)
    if skipped_columns:
        print("Skipping unsupported columns (no signal pattern): " + ", ".join(skipped_columns))
    if not signal_columns:
        raise ValueError("No signal columns found in the input CSV.")

    available_metrics, _ = get_metrics_and_indices(df, column_order)
    selected_metrics = parse_metrics_param(params.get("metrics"), available_metrics)
    target_columns = build_target_columns(df, selected_metrics, column_order)

    print(f"Available metrics: {', '.join(available_metrics)}")
    print(f"Selected metrics: {', '.join(selected_metrics)}")
    print(f"Columns to process: {len(target_columns)}")

    t, time_column = _time_axis(df, df.shape[0], fps)
    if time_column:
        print(f"Time axis: '{time_column}' column")
    else:
        print(f"Time axis: no time column in the CSV, derived from fps={fps}")
    print(
        f"Detection: {threshold_std} SD over baseline, >= {min_duration} frame(s) | "
        f"width at {height_fraction:.0%} of each spike's amplitude"
    )
    reference = _reference_mask(t, reference_start_s, reference_end_s)
    if reference.all():
        print("Baseline and SD reference: the whole recording")
    else:
        print(
            f"Baseline and SD reference: {t[reference][0]:g}-{t[reference][-1]:g} s "
            f"({np.count_nonzero(reference)} of {t.shape[0]} samples)"
        )

    roi_centroids: List[Optional[Tuple[float, float]]] = []
    mapping: List[Optional[int]] = []
    if roi_zip:
        print(f"Reading ROIs: {os.path.basename(roi_zip)}")
        roi_names, roi_centroids = _load_roi_centroids(roi_zip)
        print(f"  {len(roi_names)} ROI(s)")
        mapping, strategy = _map_columns_to_rois(target_columns, len(roi_names), column_order)
        print(f"  Signal -> ROI mapping: {strategy}")
    else:
        print("No ROI file given: the spikes table will have no x/y columns.")

    rows: List[Dict[str, Any]] = []
    empty_signals = 0
    unmapped_signals = 0
    total = len(target_columns)

    for i, column in enumerate(target_columns, start=1):
        y = pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)
        y = _interpolate_nans(y)
        if y is None:
            print(f"  Skipping '{column}': the trace has no usable data.")
            empty_signals += 1
            print(f"PROGRESS:{i / total * 100:.0f}")
            continue

        centroid = None
        if roi_zip:
            roi_index = mapping[i - 1]
            if roi_index is not None and 0 <= roi_index < len(roi_centroids):
                centroid = roi_centroids[roi_index]
            if centroid is None:
                unmapped_signals += 1

        spikes = analyze_trace(
            y,
            t,
            threshold_std=threshold_std,
            height_fraction=height_fraction,
            min_duration=min_duration,
            reference=reference,
        )
        if not spikes:
            empty_signals += 1

        for spike in spikes:
            spike["signal"] = column
            if roi_zip:
                spike["x"] = centroid[0] if centroid else float("nan")
                spike["y"] = centroid[1] if centroid else float("nan")
            rows.append(spike)

        print(f"PROGRESS:{i / total * 100:.0f}")

    if unmapped_signals:
        print(f"Warning: {unmapped_signals} signal(s) had no matching ROI; their x/y are empty.")
    if empty_signals:
        print(f"{empty_signals} of {total} signal(s) had no detectable spike.")

    columns = OUTPUT_COLUMNS if roi_zip else [c for c in OUTPUT_COLUMNS if c not in ("x", "y")]
    spikes_df = pd.DataFrame(rows, columns=columns)
    stem = os.path.splitext(os.path.basename(input_csv))[0]
    spikes_file = os.path.join(output_dir, f"{stem}_spikes.{output_format}")
    if output_format == "xlsx":
        spikes_df.to_excel(spikes_file, index=False, sheet_name="spikes")
    else:
        spikes_df.to_csv(spikes_file, index=False, float_format="%.6f")

    print(f"{len(rows)} spike(s) measured across {total - empty_signals} signal(s)")
    print(f"Spikes file saved to: {spikes_file}")

    return {"spikes_file": spikes_file}


def preview(sample: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    """Detect spikes in a single trace for interactive calibration.

    Pure and headless — no file I/O, no plotting. Reuses the same detection and
    measurement core as ``main()``, so what the preview draws is what the batch
    run will measure, with one caveat: the app decimates the displayed trace to
    at most 800 points, so ``min_duration`` (counted in frames) is coarser here
    than in the real run on a long recording.

    The reference window is placed on the sample's time axis: the CSV's own
    ``"t"`` (seconds) when the app passes one, else the plot's x values
    ``"x"`` (then frame numbers) divided by ``fps``.

    Returns the detection threshold, each spike's own half level over its
    window ("detected"), which sits at the baseline outside the spikes rather
    than using NaN gaps, and the reference window's first and last samples as
    vertical markers (``"_vlines"``, in the sample's ``"x"`` units).
    """
    y = np.asarray(sample.get("y"), dtype=float).ravel()
    y = _interpolate_nans(y)
    if y is None or y.shape[0] < 3:
        return {}

    threshold_std = float(params.get("threshold_std", 3.0))
    height_fraction = float(params.get("height_fraction", 0.5))
    min_duration = int(params.get("min_duration", 3))
    reference_start_s, reference_end_s = parse_reference_window(params)
    fps = float(params.get("fps", 10.0))
    if not 0.0 < height_fraction < 1.0:
        raise ValueError(f"height_fraction must be between 0 and 1 (got {height_fraction}).")
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
    baseline, sigma = _robust_baseline(y[reference])
    if not np.isfinite(sigma) or sigma <= 0.0:
        return {}

    spikes = analyze_trace(
        y,
        t,
        threshold_std=threshold_std,
        height_fraction=height_fraction,
        min_duration=min_duration,
        reference=reference,
    )

    detected = np.full(y.shape[0], baseline, dtype=float)
    for spike in spikes:
        detected[spike["lo_idx"]:spike["hi_idx"] + 1] = spike["half_level"]

    threshold = baseline + threshold_std * sigma
    x_ref = x[reference]
    return {
        "threshold": [threshold] * y.shape[0],
        "detected": detected.tolist(),
        "_vlines": {
            "SD reference start": float(x_ref[0]),
            "SD reference end": float(x_ref[-1]),
        },
    }


# run() is the canonical entry point called by the app's script runner.
# main() is kept as an alias for backward compatibility and CLI use.
run = main


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Measures the spikes of processed signals (half-peak method)."
    )
    parser.add_argument("--nc_params", type=str)
    parser.add_argument("--nc_output", type=str)
    parser.add_argument("--params_json", type=str)

    parser.add_argument("--input_csv", type=str)
    parser.add_argument("--roi_zip", type=str)
    parser.add_argument("--output_dir", type=str)
    parser.add_argument("--column_order", choices=COLUMN_ORDERS, default="feature_neuron")
    parser.add_argument("--metrics", type=str, default="Mean")

    parser.add_argument("--threshold_std", type=float, default=3.0)
    parser.add_argument("--height_fraction", type=float, default=0.5)
    parser.add_argument("--min_duration", type=int, default=3)
    parser.add_argument("--reference_start_s", type=float, default=0.0)
    parser.add_argument("--reference_end_s", type=float, default=0.0)
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--output_format", choices=("xlsx", "csv"), default="xlsx")

    args = parser.parse_args()

    if args.nc_params:
        try:
            with open(args.nc_params, "r", encoding="utf-8") as f:
                params = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: could not read --nc_params: {exc}", file=sys.stderr)
            sys.exit(1)
        params.pop("_context", None)
    elif args.params_json:
        try:
            params = json.loads(args.params_json)
        except json.JSONDecodeError as exc:
            print(f"ERROR: invalid JSON in --params_json: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        if not args.input_csv or not args.output_dir:
            parser.error("--input_csv and --output_dir are required")

        params = {
            "input_csv": args.input_csv,
            "roi_zip": args.roi_zip,
            "output_dir": args.output_dir,
            "column_order": args.column_order,
            "metrics": args.metrics,
            "threshold_std": args.threshold_std,
            "height_fraction": args.height_fraction,
            "min_duration": args.min_duration,
            "reference_start_s": args.reference_start_s,
            "reference_end_s": args.reference_end_s,
            "fps": args.fps,
            "output_format": args.output_format,
        }

    try:
        outputs = main(params)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.nc_output:
        try:
            with open(args.nc_output, "w", encoding="utf-8") as f:
                json.dump(outputs or {}, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            print(f"ERROR: could not write --nc_output: {exc}", file=sys.stderr)
            sys.exit(1)
