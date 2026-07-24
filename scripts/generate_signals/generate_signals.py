# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""generate_signals — Extracts fluorescence traces from a video with ROIs.

Computes metrics (maximum, mean, standard deviation, integral) within each ROI
frame by frame and saves the result as a CSV file.

Command-line usage:
    python generate_signals.py --input_video video.tif --input_roi rois.zip \\
                   --output_dir ./results [--fps 10] [--normalize] \\
                   [--no-metric_max] [--no-metric_mean] [--no-metric_std] [--no-metric_int]

    # Alternatively, passing all parameters as a JSON string:
    python generate_signals.py --params_json '{"input_video": "...", "input_roi": "...", ...}'

    # Contract used by ScriptRunner: reads parameters from a JSON file and writes
    # the declared outputs to another JSON file:
    python generate_signals.py --nc_params params.json --nc_output output.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    import read_roi
except ImportError:
    print(
        "ERROR: The 'read_roi' library is not installed. Run: pip install read-roi",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    import tifffile

    _HAS_TIFFFILE = True
except ImportError:
    _HAS_TIFFFILE = False

try:
    import cv2

    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False


# ---------------------------------------------------------------------------
# Mask creation
# ---------------------------------------------------------------------------


def _polygon_mask(
    xs: List[float], ys: List[float], shape: Tuple[int, int]
) -> np.ndarray:
    """Return a boolean mask (H × W) for a polygon defined by *xs*, *ys*."""
    from matplotlib.path import Path

    H, W = shape
    col_coords, row_coords = np.meshgrid(np.arange(W), np.arange(H))
    points = np.column_stack([col_coords.ravel(), row_coords.ravel()])
    path = Path(list(zip(xs, ys)))
    return path.contains_points(points).reshape(H, W)


def _rect_mask(
    left: float, top: float, width: float, height: float, shape: Tuple[int, int]
) -> np.ndarray:
    """Return a boolean mask for a rectangle."""
    H, W = shape
    mask = np.zeros(shape, dtype=bool)
    r0, r1 = max(0, int(top)), min(H, int(top + height))
    c0, c1 = max(0, int(left)), min(W, int(left + width))
    mask[r0:r1, c0:c1] = True
    return mask


def _oval_mask(
    left: float, top: float, width: float, height: float, shape: Tuple[int, int]
) -> np.ndarray:
    """Return a boolean mask for an oval/ellipse (approximated as polygon)."""
    theta = np.linspace(0, 2 * np.pi, 360)
    cx, cy = left + width / 2, top + height / 2
    xs = (cx + (width / 2) * np.cos(theta)).tolist()
    ys = (cy + (height / 2) * np.sin(theta)).tolist()
    return _polygon_mask(xs, ys, shape)


def build_masks(
    rois: Dict[str, Any], shape: Tuple[int, int]
) -> Dict[str, Optional[np.ndarray]]:
    """Build a dict of *roi_name* → boolean mask for every ROI in *rois*."""
    masks: Dict[str, Optional[np.ndarray]] = {}
    total_rois = len(rois)
    for idx, (name, roi) in enumerate(rois.items(), 1):
        if idx % 100 == 0 or idx == total_rois:
            print(f"  Progress: {idx}/{total_rois} masks generated...", flush=True)
            sys.stdout.flush()
        try:
            roi_type = roi.get("type", "").lower()

            if roi_type in ("polygon", "freehand", "traced", "freeline", "polyline"):
                xs = [float(v) for v in roi.get("x", [])]
                ys = [float(v) for v in roi.get("y", [])]
                if len(xs) >= 3:
                    masks[name] = _polygon_mask(xs, ys, shape)
                else:
                    print(
                        f"  Warning: ROI '{name}' has fewer than 3 vertices, skipping.",
                        file=sys.stderr,
                    )
                    masks[name] = None

            elif roi_type in ("rectangle", "rect"):
                masks[name] = _rect_mask(
                    roi["left"], roi["top"], roi["width"], roi["height"], shape
                )

            elif roi_type in ("oval", "ellipse"):
                masks[name] = _oval_mask(
                    roi["left"], roi["top"], roi["width"], roi["height"], shape
                )

            else:
                # Fallback: polygon if x/y keys present, rectangle otherwise
                if "x" in roi and "y" in roi and len(roi["x"]) >= 3:
                    xs = [float(v) for v in roi["x"]]
                    ys = [float(v) for v in roi["y"]]
                    masks[name] = _polygon_mask(xs, ys, shape)
                elif all(k in roi for k in ("left", "top", "width", "height")):
                    masks[name] = _rect_mask(
                        roi["left"], roi["top"], roi["width"], roi["height"], shape
                    )
                else:
                    print(
                        f"  Warning: Unknown ROI type '{roi_type}' for '{name}', skipping.",
                        file=sys.stderr,
                    )
                    masks[name] = None

        except Exception as exc:
            print(
                f"  Error creating mask for ROI '{name}': {exc}", file=sys.stderr
            )
            masks[name] = None

    return masks


# ---------------------------------------------------------------------------
# Video reading
# ---------------------------------------------------------------------------


def _iter_tif(path: str) -> Generator[Tuple[int, np.ndarray], None, None]:
    """Yield (frame_index, 2-D float64 array) from a TIFF stack."""
    if not _HAS_TIFFFILE:
        raise ImportError(
            "'tifffile' is not installed. Run: pip install tifffile"
        )
    stack = tifffile.imread(path)
    if stack.ndim == 2:
        yield 0, stack.astype(np.float64)
    elif stack.ndim == 3:
        for i, frame in enumerate(stack):
            yield i, frame.astype(np.float64)
    elif stack.ndim == 4:
        # (frames, H, W, C) → greyscale via luminosity weights
        for i, frame in enumerate(stack):
            if frame.shape[2] >= 3:
                gray = (
                    0.299 * frame[:, :, 0]
                    + 0.587 * frame[:, :, 1]
                    + 0.114 * frame[:, :, 2]
                )
            else:
                gray = frame[:, :, 0]
            yield i, gray.astype(np.float64)
    else:
        raise ValueError(f"Unexpected TIFF dimensions: {stack.shape}")


def _iter_cv2(path: str) -> Generator[Tuple[int, np.ndarray], None, None]:
    """Yield (frame_index, 2-D float64 greyscale array) using OpenCV."""
    if not _HAS_CV2:
        raise ImportError(
            "'opencv-python' is not installed. Run: pip install opencv-python"
        )
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise IOError(f"Could not open the video: {path}")
    frame_idx = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            yield frame_idx, cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float64)
            frame_idx += 1
    finally:
        cap.release()


def iter_video(path: str) -> Generator[Tuple[int, np.ndarray], None, None]:
    """Return the appropriate frame generator based on file extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".tif", ".tiff"):
        return _iter_tif(path)
    return _iter_cv2(path)


def estimate_frame_count(path: str) -> Optional[int]:
    """Best-effort estimate of total frames (for progress reporting)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".tif", ".tiff") and _HAS_TIFFFILE:
        try:
            with tifffile.TiffFile(path) as tif:
                n = len(tif.pages)
                return n if n > 1 else None
        except Exception:
            return None
    if _HAS_CV2:
        try:
            cap = cv2.VideoCapture(path)
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
            return n if n > 0 else None
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Metric calculation
# ---------------------------------------------------------------------------

MetricCache = Dict[str, float]
MetricFunc = Callable[[np.ndarray, MetricCache], float]


def _metric_max(_: np.ndarray, cache: MetricCache) -> float:
    return cache["max"]


def _metric_mean(_: np.ndarray, cache: MetricCache) -> float:
    return cache["mean"]


def _metric_std(_: np.ndarray, cache: MetricCache) -> float:
    return cache["std"]


def _metric_int(_: np.ndarray, cache: MetricCache) -> float:
    return cache["int"]


# Add custom metrics here. Signature: fn(pixels, cache) -> float
# Example:
# def _metric_median(pixels: np.ndarray, cache: MetricCache) -> float:
#     return float(np.median(pixels))
# METRIC_REGISTRY["median"] = _metric_median
METRIC_REGISTRY: Dict[str, MetricFunc] = {
    "max": _metric_max,
    "mean": _metric_mean,
    "std": _metric_std,
    "int": _metric_int,
}


def _prepare_builtin_cache(pixels: np.ndarray, selected: List[str]) -> MetricCache:
    """Prepare built-in metrics once to avoid repeated numpy calls."""
    cache: MetricCache = {}

    need_sum = "mean" in selected or "int" in selected or "std" in selected
    need_max = "max" in selected

    if need_sum:
        s = float(np.sum(pixels))
        cache["int"] = s

        if "mean" in selected or "std" in selected:
            mean = s / float(pixels.size)
            cache["mean"] = mean
            if "std" in selected:
                ex2 = float(np.mean(pixels * pixels))
                var = max(0.0, ex2 - mean * mean)
                cache["std"] = float(np.sqrt(var))

    if need_max:
        cache["max"] = float(np.max(pixels))

    return cache


def compute_metrics_fast(pixels: np.ndarray, selected: List[str]) -> List[float]:
    """Compute selected metrics preserving metric order in *selected*."""
    if pixels.size == 0:
        return [float("nan")] * len(selected)

    cache = _prepare_builtin_cache(pixels, selected)
    values: List[float] = []
    for metric_name in selected:
        func = METRIC_REGISTRY.get(metric_name)
        if func is None:
            raise KeyError(f"Unknown metric: {metric_name}")
        values.append(float(func(pixels, cache)))
    return values


def selected_metrics_from_params(params: Dict[str, Any]) -> List[str]:
    """Collect selected metrics preserving order: max, mean, std, int."""
    metric_keys = [
        ("max", "metric_max"),
        ("mean", "metric_mean"),
        ("std", "metric_std"),
        ("int", "metric_int"),
    ]
    selected = [k for k, p in metric_keys if params.get(p, True)]
    if not selected:
        print("ERROR: At least one metric must be selected.", file=sys.stderr)
        sys.exit(1)
    return selected


def build_output_columns(neuron_ids: List[int], metrics: List[str]) -> List[str]:
    """Create output columns: frame, time_s, then neuron_metric columns."""
    return ["frame", "time_s"] + [
        f"{neuron_id}_{metric}"
        for neuron_id in neuron_ids
        for metric in metrics
    ]


def process_frames(
    input_video: str,
    roi_flat_indices: List[np.ndarray],
    metrics: List[str],
    fps: int,
) -> List[List[Any]]:
    """Run the main frame loop and return all rows for the output DataFrame."""
    total = estimate_frame_count(input_video)
    total_str = str(total) if total else "?"
    print(f"Processing: {os.path.basename(input_video)}")
    print(f"  Metrics: {', '.join(metrics)}")

    rows: List[List[Any]] = []
    for frame_idx, frame in iter_video(input_video):
        frame_flat = frame.ravel()
        row: List[Any] = [frame_idx, round(frame_idx / fps, 6)]
        for flat_idx in roi_flat_indices:
            row.extend(compute_metrics_fast(frame_flat[flat_idx], metrics))
        rows.append(row)

        if (frame_idx + 1) % 100 == 0:
            print(f"  Frame {frame_idx + 1}/{total_str}...", flush=True)

    print(f"  Total frames processed: {len(rows)}")
    return rows


# ---------------------------------------------------------------------------
# Z-score normalisation
# ---------------------------------------------------------------------------


def zscore_normalize(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    for col in df.columns:
        std = df[col].std()
        if std > 0:
            result[col] = (df[col] - df[col].mean()) / std
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(params: Dict[str, Any]) -> Dict[str, Any]:
    input_video = params["input_video"]
    input_roi   = params["input_roi"]
    output_dir  = params["output_dir"]
    fps         = int(params.get("fps", 10))
    normalize   = bool(params.get("normalize", False))

    metrics = selected_metrics_from_params(params)

    # Normalize all file paths to absolute paths (critical for subprocess execution)
    input_video = os.path.abspath(os.path.normpath(input_video))
    input_roi = os.path.abspath(os.path.normpath(input_roi))
    output_dir = os.path.abspath(os.path.normpath(output_dir))

    # Validate inputs
    for label, path in (("input_video", input_video), ("input_roi", input_roi)):
        if not os.path.isfile(path):
            print(f"ERROR: '{label}' not found: {path}", file=sys.stderr)
            sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    # ---- Load ROIs ----------------------------------------------------------
    print(f"Loading ROIs from: {os.path.basename(input_roi)}")
    rois = read_roi.read_roi_zip(input_roi)
    if not rois:
        print("ERROR: No ROIs found in the ZIP file.", file=sys.stderr)
        sys.exit(1)
    print(f"  {len(rois)} ROI(s): {', '.join(rois.keys())}")

    # ---- Determine image dimensions from first frame -------------------------
    print("Reading first frame to determine dimensions...")
    first_frame: Optional[np.ndarray] = None
    for _, frame in iter_video(input_video):
        first_frame = frame
        break
    if first_frame is None:
        print("ERROR: Could not read any frame from the video.", file=sys.stderr)
        sys.exit(1)
    H, W = first_frame.shape[:2]
    print(f"  Resolution: {W} × {H} px")

    # ---- Build ROI masks -----------------------------------------------------
    print("Generating ROI masks...")
    all_masks = build_masks(rois, (H, W))
    valid_masks = {name: mask for name, mask in all_masks.items() if mask is not None}
    if not valid_masks:
        print("ERROR: Could not create any valid mask.", file=sys.stderr)
        sys.exit(1)
    skipped = len(all_masks) - len(valid_masks)
    print(f"  {len(valid_masks)} valid" + (f", {skipped} skipped." if skipped else "."))

    # Assign each neuron the 1-based position of its ROI in the *full* ROI list
    # (all_masks preserves ROI insertion order = order in the ZIP). Numbering over
    # every ROI — not just the valid ones — keeps neuron numbers aligned with each
    # ROI's position in the file, so a skipped ROI leaves a gap instead of shifting
    # the rest. This is the identifier the downstream scripts rely on:
    # select_active/pearson_matrix preserve it, and connectivity_graph maps column
    # "N_mean" back to the N-th ROI in the same ZIP.
    valid_items = [
        (position, mask)
        for position, (_, mask) in enumerate(all_masks.items(), start=1)
        if mask is not None
    ]
    neuron_ids = [position for position, _ in valid_items]

    # Precompute flattened pixel indices per ROI for faster per-frame extraction.
    roi_flat_indices = [np.flatnonzero(mask.ravel()) for _, mask in valid_items]

    # ---- Build output column names -------------------------------------------
    # Frame | Time (s) | ROI1_max | ROI1_mean | ... | ROIn_int
    columns = build_output_columns(neuron_ids, metrics)

    # ---- Process frames ------------------------------------------------------
    rows = process_frames(
        input_video=input_video,
        roi_flat_indices=roi_flat_indices,
        metrics=metrics,
        fps=fps,
    )

    # ---- Build and optionally normalise DataFrame ----------------------------
    df = pd.DataFrame(rows, columns=columns)

    if normalize:
        print("Normalizing signals (Z-score)...")
        signal_cols = columns[2:]
        df[signal_cols] = zscore_normalize(df[signal_cols])

    # ---- Save CSV ------------------------------------------------------------
    video_stem = os.path.splitext(os.path.basename(input_video))[0]
    output_csv = os.path.join(output_dir, f"{video_stem}_traces.csv")
    df.to_csv(output_csv, index=False)
    print(f"CSV saved to: {output_csv}")
    print(f"  {len(df)} rows × {len(df.columns)} columns")

    # Emit structured output for the pipeline runner
    print(f"OUTPUT:output_csv={output_csv}")

    return {"output_csv": output_csv}


# run() is the canonical entry point called by the app's script runner.
# main() is kept as an alias for backward compatibility and CLI use.
run = main


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extracts fluorescence traces from a video using ROIs."
    )
    parser.add_argument(
        "--nc_params",
        type=str,
        help="Path to a JSON file with all parameters (ScriptRunner contract).",
    )
    parser.add_argument(
        "--nc_output",
        type=str,
        help="Path to write the declared outputs as JSON (ScriptRunner contract).",
    )
    parser.add_argument(
        "--params_json",
        type=str,
        help="All parameters as a JSON string (alternative to the individual flags).",
    )
    parser.add_argument("--input_video",  type=str, help="Path to the input video")
    parser.add_argument("--input_roi",    type=str, help="Path to the ROI ZIP")
    parser.add_argument("--fps",          type=int, default=10)
    parser.add_argument("--output_dir",   type=str, help="Output folder")
    parser.add_argument("--normalize",    action="store_true", default=False)
    parser.add_argument("--metric_max",  action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--metric_mean", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--metric_std",  action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--metric_int",  action=argparse.BooleanOptionalAction, default=True)

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
        if not args.input_video or not args.input_roi or not args.output_dir:
            parser.error("--input_video, --input_roi and --output_dir are required")
        params = {
            "input_video":  args.input_video,
            "input_roi":    args.input_roi,
            "fps":          args.fps,
            "output_dir":   args.output_dir,
            "normalize":    args.normalize,
            "metric_max":   args.metric_max,
            "metric_mean":  args.metric_mean,
            "metric_std":   args.metric_std,
            "metric_int":   args.metric_int,
        }

    try:
        outputs = main(params)
    except Exception as exc:  # noqa: BLE001 - surface any error to the pipeline runner
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.nc_output:
        try:
            with open(args.nc_output, "w", encoding="utf-8") as f:
                json.dump(outputs or {}, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            print(f"ERROR: could not write --nc_output: {exc}", file=sys.stderr)
            sys.exit(1)
