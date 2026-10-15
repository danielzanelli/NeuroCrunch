# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple


import numpy as np
import pandas as pd


IGNORED_COLUMNS = {"", "Slice", "frame", "time_s", "time"}


def _is_ignored_column(column: str) -> bool:
    return column.strip() in IGNORED_COLUMNS


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


def _butter_mask(freqs: np.ndarray, low_cutoff: float, high_cutoff: float, order: int) -> np.ndarray:
    # Zero-phase band-pass built directly in the frequency domain, as the
    # product of a Butterworth low-pass and high-pass magnitude response.
    # No scipy.signal.butter/filtfilt: scipy is excluded from the shipped build.
    if high_cutoff > 0:
        with np.errstate(divide="ignore"):
            low_pass = 1.0 / np.sqrt(1.0 + (freqs / high_cutoff) ** (2 * order))
    else:
        low_pass = np.ones_like(freqs)

    if low_cutoff > 0:
        high_pass = np.zeros_like(freqs)
        nonzero = freqs > 0
        high_pass[nonzero] = 1.0 / np.sqrt(1.0 + (low_cutoff / freqs[nonzero]) ** (2 * order))
    else:
        high_pass = np.ones_like(freqs)

    return low_pass * high_pass


def _validate_cutoffs(fps: float, low_cutoff: float, high_cutoff: float) -> None:
    if fps <= 0:
        raise ValueError("Sampling rate (fps) must be greater than 0.")
    if low_cutoff > 0 and high_cutoff > 0 and low_cutoff >= high_cutoff:
        raise ValueError("Low cutoff must be smaller than high cutoff.")
    nyquist = fps / 2.0
    if high_cutoff >= nyquist:
        raise ValueError(
            f"High cutoff ({high_cutoff} Hz) must be below the Nyquist frequency ({nyquist} Hz = fps/2)."
        )


def bandpass_filter(
    y: np.ndarray,
    *,
    fps: float,
    low_cutoff: float,
    high_cutoff: float,
    order: int,
) -> np.ndarray:
    length = y.shape[0]
    if length < 3:
        return y.copy()

    # Reflect-pad so the FFT's implicit periodicity doesn't smear the trace's
    # first/last second into its opposite end.
    pad = min(length - 1, max(1, int(round(fps))))
    padded = np.pad(y, pad, mode="reflect")

    freqs = np.fft.rfftfreq(padded.shape[0], d=1.0 / fps)
    mask = _butter_mask(freqs, low_cutoff, high_cutoff, order)
    filtered_padded = np.fft.irfft(np.fft.rfft(padded) * mask, n=padded.shape[0])

    return filtered_padded[pad: pad + length]


def main(params: Dict[str, Any]) -> Dict[str, Any]:
    input_csv = os.path.abspath(os.path.normpath(params["input_csv"]))
    output_dir = os.path.abspath(os.path.normpath(params["output_dir"]))
    column_order = parse_column_order(params.get("column_order"))

    fps = float(params.get("fps", 10.0))
    low_cutoff = float(params.get("low_cutoff", 0.1))
    high_cutoff = float(params.get("high_cutoff", 3.0))
    order = int(params.get("order", 2))

    _validate_cutoffs(fps, low_cutoff, high_cutoff)

    if not os.path.isfile(input_csv):
        raise FileNotFoundError(f"input_csv not found: {input_csv}")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Loading CSV: {input_csv}")
    df = pd.read_csv(input_csv)
    print(f"CSV loaded: {df.shape[0]} rows x {df.shape[1]} columns")
    signal_columns, skipped_columns = _iter_signal_columns(df.columns, column_order)
    if skipped_columns:
        print(
            "Skipping unsupported columns (no signal pattern): "
            + ", ".join(skipped_columns)
        )
    if not signal_columns:
        raise ValueError("No signal columns found in the input CSV.")

    available_metrics, _ = get_metrics_and_indices(df, column_order)
    selected_metrics = parse_metrics_param(params.get("metrics"), available_metrics)
    target_columns = build_target_columns(df, selected_metrics, column_order)

    print(f"Available metrics: {', '.join(available_metrics)}")
    print(f"Selected metrics: {', '.join(selected_metrics)}")
    print(f"Columns to process: {len(target_columns)}")
    print(f"Band-pass: {low_cutoff} - {high_cutoff} Hz | fps={fps} | order={order}")

    filtered_df = df.copy()
    total = len(target_columns)
    for i, column in enumerate(target_columns, start=1):
        y = pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)
        nan_mask = np.isnan(y)
        if nan_mask.all():
            continue
        if nan_mask.any():
            valid_idx = np.flatnonzero(~nan_mask)
            y[nan_mask] = np.interp(np.flatnonzero(nan_mask), valid_idx, y[valid_idx])

        filtered_df[column] = bandpass_filter(
            y, fps=fps, low_cutoff=low_cutoff, high_cutoff=high_cutoff, order=order
        )

        print(f"PROGRESS:{i / total * 100:.0f}")

    stem = os.path.splitext(os.path.basename(input_csv))[0]
    filtered_csv = os.path.join(output_dir, f"{stem}_bandpass.csv")
    filtered_df.to_csv(filtered_csv, index=False)
    print(f"Filtered CSV saved to: {filtered_csv}")

    print(f"OUTPUT:filtered_csv={filtered_csv}")

    return {
        "filtered_csv": filtered_csv,
    }


def preview(sample: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    """Run the band-pass filter on a single trace for interactive calibration.

    Pure and headless — no file I/O, no plotting. The app's Filter-preview tab
    feeds one (already-decimated) trace and the current parameter values, then
    overlays the returned series so the user can tune the cutoffs against real
    data. It reuses the same core as ``main()`` so the preview matches the
    batch result.

    Parameters
    ----------
    sample : dict
        ``{"y": <1-D array-like>}`` — a single fluorescence trace.
    params : dict
        Same parameter keys read by ``main()``.

    Returns
    -------
    dict
        ``{"filtered": [...]}`` — the filtered trace. Returns ``{}`` only when
        the trace itself has no usable data (too short / all-NaN). An invalid
        cutoff/fps combination raises ``ValueError`` instead of returning
        ``{}``, so the calibration tab reports it rather than silently
        showing nothing.
    """
    y = np.asarray(sample.get("y"), dtype=float).ravel()
    nan_mask = np.isnan(y)
    if nan_mask.all() or y.shape[0] < 3:
        return {}
    if nan_mask.any():
        valid_idx = np.flatnonzero(~nan_mask)
        y[nan_mask] = np.interp(np.flatnonzero(nan_mask), valid_idx, y[valid_idx])

    fps = float(params.get("fps", 10.0))
    low_cutoff = float(params.get("low_cutoff", 0.1))
    high_cutoff = float(params.get("high_cutoff", 3.0))
    order = int(params.get("order", 2))

    _validate_cutoffs(fps, low_cutoff, high_cutoff)

    filtered = bandpass_filter(
        y, fps=fps, low_cutoff=low_cutoff, high_cutoff=high_cutoff, order=order
    )

    return {"filtered": filtered.tolist()}


# run() is the canonical entry point called by the app's script runner.
# main() is kept as an alias for backward compatibility and CLI use.
run = main


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Band-pass filters fluorescence signals (removes slow drift and fast noise)."
    )
    parser.add_argument("--nc_params", type=str)
    parser.add_argument("--nc_output", type=str)
    parser.add_argument("--params_json", type=str)

    parser.add_argument("--input_csv", type=str)
    parser.add_argument("--output_dir", type=str)
    parser.add_argument("--column_order", choices=COLUMN_ORDERS, default="feature_neuron")
    parser.add_argument("--metrics", type=str, default="")

    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--low_cutoff", type=float, default=0.1)
    parser.add_argument("--high_cutoff", type=float, default=3.0)
    parser.add_argument("--order", type=int, default=2)

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
            "output_dir": args.output_dir,
            "column_order": args.column_order,
            "metrics": args.metrics,
            "fps": args.fps,
            "low_cutoff": args.low_cutoff,
            "high_cutoff": args.high_cutoff,
            "order": args.order,
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
