# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""spike_analysis — Measures every spike in each processed signal.

Reads a CSV of processed traces (ALS-corrected and/or band-passed, so spikes sit
above a flat baseline plus noise) together with the ImageJ/FIJI ROI archive the
signals were extracted from, and writes one row per detected spike.

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

Output (in the output folder):
  * <name>_spikes.csv       — one row per spike

Contract: see README.md > "<script_name>.py — execution contract".
"""
from __future__ import annotations

import argparse
import json
import os
import re
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


def split_metric_and_index(column: str) -> Tuple[str, int]:
    # Pattern 1: Mean123 / baseline_filt_123
    match_metric_first = re.match(r"^([a-zA-Z_]+?)(\d+)$", column)
    if match_metric_first:
        return match_metric_first.group(1), int(match_metric_first.group(2))

    # Pattern 2: 123_mean / 123_baseline_filt
    match_index_first = re.match(r"^(\d+)_([a-zA-Z_]+)$", column)
    if match_index_first:
        return match_index_first.group(2), int(match_index_first.group(1))

    raise ValueError(
        f"Column name '{column}' does not match the supported patterns: "
        "'(MetricName)(index)' or '(index)_(metric_name)'"
    )


def _iter_signal_columns(columns: Iterable[str]) -> Tuple[List[str], List[str]]:
    signal_columns: List[str] = []
    skipped_columns: List[str] = []

    for col in columns:
        if _is_ignored_column(col):
            continue
        try:
            split_metric_and_index(col)
            signal_columns.append(col)
        except ValueError:
            skipped_columns.append(col)

    return signal_columns, skipped_columns


def get_metrics_and_indices(df: pd.DataFrame) -> Tuple[List[str], List[int]]:
    metrics: Set[str] = set()
    indices: Set[int] = set()

    signal_columns, _ = _iter_signal_columns(df.columns)
    for col in signal_columns:
        metric, idx = split_metric_and_index(col)
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


def build_target_columns(df: pd.DataFrame, selected_metrics: Iterable[str]) -> List[str]:
    metric_set = set(selected_metrics)
    target_cols: List[str] = []

    signal_columns, _ = _iter_signal_columns(df.columns)
    for col in signal_columns:
        metric, _ = split_metric_and_index(col)
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


def _map_columns_to_rois(columns: Sequence[str], n_rois: int) -> Tuple[List[Optional[int]], str]:
    """Map each signal column to a 0-based ROI index.

    *Indexed* — the neuron number carried by the column name (``7_mean`` and
    ``Mean7`` both mean ROI 7) used as a 1-based ROI index. This survives
    ``select_active`` dropping cells, since a surviving column keeps its original
    number, and it maps several metrics of the same cell to the same ROI.

    *Positional* — otherwise column *i* falls back to ROI *i*.
    """
    parsed: List[Optional[int]] = []
    for col in columns:
        try:
            _, idx = split_metric_and_index(str(col))
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
) -> Dict[str, Any]:
    """Measure one spike by the half-peak method.

    The apex is strictly above the half level (it cleared the detection
    threshold and ``height_fraction`` < 1), so both flank walks start below it.
    """
    amplitude = float(y[apex] - baseline)
    half_level = baseline + height_fraction * amplitude
    truncated = False

    # Rising flank: last sample at or below the half level before the apex.
    j = None
    for i in range(apex, left - 1, -1):
        if y[i] <= half_level:
            j = i
            break
    if j is None:
        # Still above the half level at the search bound: the spike is clipped
        # by the recording edge or runs into its neighbour.
        truncated = True
        start_s, y_start, lo_idx = float(t[left]), float(y[left]), left
        interior_lo = left + 1
    else:
        start_s, y_start, lo_idx = _cross_time(t, y, j, j + 1, half_level), half_level, j
        interior_lo = j + 1

    # Falling flank: first sample at or below the half level after the apex.
    k = None
    for i in range(apex, right + 1):
        if y[i] <= half_level:
            k = i
            break
    if k is None:
        truncated = True
        end_s, y_end, hi_idx = float(t[right]), float(y[right]), right
        interior_hi = right - 1
    else:
        end_s, y_end, hi_idx = _cross_time(t, y, k - 1, k, half_level), half_level, k
        interior_hi = k - 1

    # Area over exactly the reported window, with the interpolated crossings
    # spliced in as endpoints so the area matches the reported start/end times.
    t_seg = np.concatenate(([start_s], t[interior_lo:interior_hi + 1], [end_s]))
    y_seg = np.concatenate(([y_start], y[interior_lo:interior_hi + 1], [y_end]))
    auc = float(np.trapezoid(y_seg - baseline, x=t_seg))

    return {
        "start_s": start_s,
        "end_s": end_s,
        "width_s": end_s - start_s,
        "spike_time_s": float(t[apex]),
        "max_height": amplitude,
        "auc": auc,
        "truncated": truncated,
        # Sample span and level of the window, for the calibration preview.
        "lo_idx": lo_idx,
        "hi_idx": hi_idx,
        "half_level": half_level,
    }


def analyze_trace(
    y: np.ndarray,
    t: np.ndarray,
    *,
    threshold_std: float,
    height_fraction: float,
    min_duration: int,
) -> List[Dict[str, Any]]:
    """Detect and measure every spike in one trace.

    Returns a list of per-spike dicts (empty when the trace is flat, unusable, or
    simply has no spike above the threshold).
    """
    baseline, sigma = _robust_baseline(y)
    if not np.isfinite(sigma) or sigma <= 0.0:
        return []

    threshold = baseline + threshold_std * sigma
    apexes = _find_apexes(y, threshold, min_duration)
    if not apexes:
        return []

    bounds = _search_bounds(y, apexes)
    spikes = []
    for index, (apex, (left, right)) in enumerate(zip(apexes, bounds), start=1):
        spike = _measure_spike(y, t, apex, left, right, baseline, height_fraction)
        spike["spike_index"] = index
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
    "truncated",
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
    roi_zip = os.path.abspath(os.path.normpath(params["roi_zip"]))
    output_dir = os.path.abspath(os.path.normpath(params["output_dir"]))

    threshold_std = float(params.get("threshold_std", 3.0))
    height_fraction = float(params.get("height_fraction", 0.5))
    min_duration = int(params.get("min_duration", 3))
    fps = float(params.get("fps", 10.0))

    if not 0.0 < height_fraction < 1.0:
        raise ValueError(f"height_fraction must be between 0 and 1 (got {height_fraction}).")
    if fps <= 0:
        raise ValueError(f"fps must be positive (got {fps}).")
    if not os.path.isfile(input_csv):
        raise FileNotFoundError(f"input_csv not found: {input_csv}")
    if not os.path.isfile(roi_zip):
        raise FileNotFoundError(f"ROI file not found: {roi_zip}")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Loading CSV: {input_csv}")
    df = pd.read_csv(input_csv)
    print(f"CSV loaded: {df.shape[0]} rows x {df.shape[1]} columns")
    if df.shape[0] < 3:
        raise ValueError("The input CSV needs at least 3 rows to measure a spike.")

    signal_columns, skipped_columns = _iter_signal_columns(df.columns)
    if skipped_columns:
        print("Skipping unsupported columns (no signal pattern): " + ", ".join(skipped_columns))
    if not signal_columns:
        raise ValueError("No signal columns found in the input CSV.")

    available_metrics, _ = get_metrics_and_indices(df)
    selected_metrics = parse_metrics_param(params.get("metrics"), available_metrics)
    target_columns = build_target_columns(df, selected_metrics)

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

    print(f"Reading ROIs: {os.path.basename(roi_zip)}")
    roi_names, roi_centroids = _load_roi_centroids(roi_zip)
    print(f"  {len(roi_names)} ROI(s)")
    mapping, strategy = _map_columns_to_rois(target_columns, len(roi_names))
    print(f"  Signal -> ROI mapping: {strategy}")

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

        roi_index = mapping[i - 1]
        centroid = (
            roi_centroids[roi_index]
            if roi_index is not None and 0 <= roi_index < len(roi_centroids)
            else None
        )
        if centroid is None:
            unmapped_signals += 1

        spikes = analyze_trace(
            y,
            t,
            threshold_std=threshold_std,
            height_fraction=height_fraction,
            min_duration=min_duration,
        )
        if not spikes:
            empty_signals += 1

        for spike in spikes:
            spike["signal"] = column
            spike["x"] = centroid[0] if centroid else float("nan")
            spike["y"] = centroid[1] if centroid else float("nan")
            rows.append(spike)

        print(f"PROGRESS:{i / total * 100:.0f}")

    if unmapped_signals:
        print(f"Warning: {unmapped_signals} signal(s) had no matching ROI; their x/y are empty.")
    if empty_signals:
        print(f"{empty_signals} of {total} signal(s) had no detectable spike.")

    spikes_df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    stem = os.path.splitext(os.path.basename(input_csv))[0]
    spikes_csv = os.path.join(output_dir, f"{stem}_spikes.csv")
    spikes_df.to_csv(spikes_csv, index=False, float_format="%.6f")

    truncated_count = int(spikes_df["truncated"].sum()) if not spikes_df.empty else 0
    print(f"{len(rows)} spike(s) measured across {total - empty_signals} signal(s)")
    if truncated_count:
        print(f"  {truncated_count} spike(s) clipped at a search bound (truncated = True)")
    print(f"Spikes CSV saved to: {spikes_csv}")

    return {"spikes_csv": spikes_csv}


def preview(sample: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    """Detect spikes in a single trace for interactive calibration.

    Pure and headless — no file I/O, no plotting. Reuses the same detection and
    measurement core as ``main()``, so what the preview draws is what the batch
    run will measure, with one caveat: the app decimates the displayed trace to
    at most 800 points, so ``min_duration`` (counted in frames) is coarser here
    than in the real run on a long recording.

    Returns the detection threshold, each spike's own half level over its window,
    and the trace itself inside the detected windows. The two window series sit
    at the baseline outside the spikes rather than using NaN gaps.
    """
    y = np.asarray(sample.get("y"), dtype=float).ravel()
    y = _interpolate_nans(y)
    if y is None or y.shape[0] < 3:
        return {}

    threshold_std = float(params.get("threshold_std", 3.0))
    height_fraction = float(params.get("height_fraction", 0.5))
    min_duration = int(params.get("min_duration", 3))
    if not 0.0 < height_fraction < 1.0:
        raise ValueError(f"height_fraction must be between 0 and 1 (got {height_fraction}).")

    baseline, sigma = _robust_baseline(y)
    if not np.isfinite(sigma) or sigma <= 0.0:
        return {}

    # The preview has no time axis; sample indices are enough to place the
    # windows, and every reported time is derived from the same crossings.
    t = np.arange(y.shape[0], dtype=float)
    spikes = analyze_trace(
        y,
        t,
        threshold_std=threshold_std,
        height_fraction=height_fraction,
        min_duration=min_duration,
    )

    half_levels = np.full(y.shape[0], baseline, dtype=float)
    detected = np.full(y.shape[0], baseline, dtype=float)
    for spike in spikes:
        lo, hi = spike["lo_idx"], spike["hi_idx"]
        half_levels[lo:hi + 1] = spike["half_level"]
        detected[lo:hi + 1] = y[lo:hi + 1]

    threshold = baseline + threshold_std * sigma
    return {
        "threshold": [threshold] * y.shape[0],
        "half_level": half_levels.tolist(),
        "detected": detected.tolist(),
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
    parser.add_argument("--metrics", type=str, default="Mean")

    parser.add_argument("--threshold_std", type=float, default=3.0)
    parser.add_argument("--height_fraction", type=float, default=0.5)
    parser.add_argument("--min_duration", type=int, default=3)
    parser.add_argument("--fps", type=float, default=10.0)

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
        if not args.input_csv or not args.roi_zip or not args.output_dir:
            parser.error("--input_csv, --roi_zip and --output_dir are required")

        params = {
            "input_csv": args.input_csv,
            "roi_zip": args.roi_zip,
            "output_dir": args.output_dir,
            "metrics": args.metrics,
            "threshold_std": args.threshold_std,
            "height_fraction": args.height_fraction,
            "min_duration": args.min_duration,
            "fps": args.fps,
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
