# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""remove_floaters — Detects and removes small moving particles from a video.

Floaters (drifting debris, bubbles, out-of-focus specks) are transient: they do
not stay at any one pixel for long. A temporal-median background therefore does
not contain them, so a particle shows up as a localised deviation from that
background. This script flags those deviations, keeps only the blob-sized ones
(large stationary structures are real signal and are preserved), and fills them
back in — either by inpainting from neighbouring pixels or with the temporal
median. The result is written as a cleaned video file.

Command-line usage:
    python remove_floaters.py --input_video in.mp4 --output_dir ./out \\
                   [--sensitivity 3.0] [--min_particle_size 2] \\
                   [--max_particle_size 200] [--temporal_window 0] \\
                   [--fill_method inpaint] [--output_format mp4] [--fps 0]

    # Contract used by ScriptRunner: reads parameters from a JSON file and writes
    # the declared outputs to another JSON file:
    python remove_floaters.py --nc_params params.json --nc_output output.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:
    print(
        "ERROR: 'opencv-python' is not installed. Run: pip install opencv-python-headless",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    import tifffile

    _HAS_TIFFFILE = True
except ImportError:
    _HAS_TIFFFILE = False


# ---------------------------------------------------------------------------
# Cancellation / progress helpers (work with or without a ctx object)
# ---------------------------------------------------------------------------


def _is_cancelled(ctx: Any) -> bool:
    return bool(ctx is not None and getattr(ctx, "is_cancelled", lambda: False)())


def _progress(pct: float) -> None:
    print(f"PROGRESS:{pct:.0f}", flush=True)


# ---------------------------------------------------------------------------
# Video reading
# ---------------------------------------------------------------------------


def _to_uint8(frame: np.ndarray, scale: float) -> np.ndarray:
    """Scale an arbitrary-depth frame to 8-bit using a global *scale* factor."""
    if frame.dtype == np.uint8:
        return frame
    return np.clip(frame.astype(np.float32) * scale, 0, 255).astype(np.uint8)


def _read_tif(path: str) -> Tuple[List[np.ndarray], Optional[float]]:
    """Read a TIFF stack into a list of BGR uint8 frames."""
    if not _HAS_TIFFFILE:
        raise ImportError("'tifffile' is not installed. Run: pip install tifffile")
    stack = tifffile.imread(path)
    if stack.ndim == 2:
        stack = stack[None, ...]
    if stack.ndim not in (3, 4):
        raise ValueError(f"Unexpected TIFF dimensions: {stack.shape}")

    # Global scale so 16-bit (or float) stacks map to 8-bit without per-frame flicker.
    peak = float(np.max(stack)) if stack.size else 0.0
    scale = 255.0 / peak if peak > 0 and stack.dtype != np.uint8 else 1.0

    frames: List[np.ndarray] = []
    for frame in stack:
        frame = _to_uint8(frame, scale)
        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
        elif frame.shape[2] == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        frames.append(np.ascontiguousarray(frame))
    return frames, None


def _read_cv2(path: str) -> Tuple[List[np.ndarray], Optional[float]]:
    """Read a video into a list of BGR uint8 frames, plus its source fps."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise IOError(f"Could not open the video: {path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS)
    src_fps = float(src_fps) if src_fps and src_fps > 0 else None
    frames: List[np.ndarray] = []
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame)
    finally:
        cap.release()
    return frames, src_fps


def read_video(path: str) -> Tuple[List[np.ndarray], Optional[float]]:
    """Return (list of BGR uint8 frames, source fps or None)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".tif", ".tiff"):
        return _read_tif(path)
    return _read_cv2(path)


# ---------------------------------------------------------------------------
# Background estimation
# ---------------------------------------------------------------------------


def temporal_median(stack: np.ndarray, index: int, window: int) -> np.ndarray:
    """Median frame over a window centred on *index* (whole stack if window<=0)."""
    if window <= 0 or window >= len(stack):
        # Caller precomputes the global median; this branch is a safety net.
        return np.median(stack, axis=0)
    half = window // 2
    lo = max(0, index - half)
    hi = min(len(stack), index + half + 1)
    return np.median(stack[lo:hi], axis=0)


# ---------------------------------------------------------------------------
# Particle detection
# ---------------------------------------------------------------------------

_KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))


def detect_particle_mask(
    gray_frame: np.ndarray,
    gray_bg: np.ndarray,
    sensitivity: float,
    min_size: int,
    max_size: int,
) -> np.ndarray:
    """Return a uint8 mask (0/255) of moving-particle pixels in *gray_frame*."""
    diff = cv2.absdiff(gray_frame, gray_bg)

    mean, std = float(diff.mean()), float(diff.std())
    thr = mean + sensitivity * std
    # Guard against a perfectly flat difference image (std == 0).
    raw = (diff > max(thr, 1e-6)).astype(np.uint8) * 255

    # Drop isolated single-pixel noise before component analysis.
    raw = cv2.morphologyEx(raw, cv2.MORPH_OPEN, _KERNEL)

    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(raw, connectivity=8)
    mask = np.zeros_like(raw)
    for i in range(1, n_labels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < min_size:
            continue
        if max_size > 0 and area > max_size:
            continue  # too big to be a floater — keep it (real structure)
        mask[labels == i] = 255

    # Dilate slightly so the fill also covers the particle's soft halo.
    if np.any(mask):
        mask = cv2.dilate(mask, _KERNEL, iterations=1)
    return mask


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_FOURCC = {"mp4": "mp4v", "avi": "MJPG"}


def main(params: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    input_video = os.path.abspath(os.path.normpath(params["input_video"]))
    output_dir = os.path.abspath(os.path.normpath(params["output_dir"]))
    sensitivity = float(params.get("sensitivity", 3.0))
    min_size = int(params.get("min_particle_size", 2))
    max_size = int(params.get("max_particle_size", 200))
    window = int(params.get("temporal_window", 0))
    fill_method = str(params.get("fill_method", "inpaint")).lower()
    output_format = str(params.get("output_format", "mp4")).lower()
    req_fps = int(params.get("fps", 0))

    if not os.path.isfile(input_video):
        raise FileNotFoundError(f"Input video not found: {input_video}")
    if output_format not in _FOURCC:
        raise ValueError(f"Unsupported output_format: {output_format}")
    os.makedirs(output_dir, exist_ok=True)

    # ---- Load frames --------------------------------------------------------
    print(f"Reading: {os.path.basename(input_video)}")
    frames, src_fps = read_video(input_video)
    n_frames = len(frames)
    if n_frames == 0:
        raise ValueError("The video contains no frames.")
    H, W = frames[0].shape[:2]
    print(f"  {n_frames} frame(s), {W} x {H} px")

    fps = req_fps if req_fps > 0 else int(round(src_fps)) if src_fps else 10

    # Grayscale stack drives detection; the BGR frames are what we clean.
    frames_bgr = np.stack(frames).astype(np.uint8)
    gray_stack = np.stack(
        [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    ).astype(np.uint8)

    use_global = window <= 0 or window >= n_frames
    global_gray_bg = np.median(gray_stack, axis=0) if use_global else None
    global_color_bg = (
        np.median(frames_bgr, axis=0)
        if (use_global and fill_method == "background")
        else None
    )
    if use_global:
        print("  Background: temporal median over the whole clip")
    else:
        print(f"  Background: sliding temporal median (window = {window} frames)")

    # ---- Output writer ------------------------------------------------------
    video_stem = os.path.splitext(os.path.basename(input_video))[0]
    output_video = os.path.join(
        output_dir, f"{video_stem}_clean.{output_format}"
    )
    fourcc = cv2.VideoWriter_fourcc(*_FOURCC[output_format])
    writer = cv2.VideoWriter(output_video, fourcc, float(fps), (W, H), True)
    if not writer.isOpened():
        raise IOError(
            f"Could not open a video writer for {output_video} "
            f"(codec '{_FOURCC[output_format]}')."
        )

    # ---- Process frames -----------------------------------------------------
    print(f"Removing floaters (fill = {fill_method})...")
    particles_total = 0
    try:
        for i in range(n_frames):
            if _is_cancelled(ctx):
                print("Cancelled by user.")
                writer.release()
                if os.path.isfile(output_video):
                    os.remove(output_video)
                return {}

            gray_bg = (
                global_gray_bg
                if use_global
                else temporal_median(gray_stack, i, window)
            )
            gray_bg_u8 = gray_bg.astype(np.uint8)

            mask = detect_particle_mask(
                gray_stack[i], gray_bg_u8, sensitivity, min_size, max_size
            )

            if np.any(mask):
                particles_total += 1
                if fill_method == "background":
                    if use_global:
                        color_bg = global_color_bg
                    else:
                        color_bg = temporal_median(frames_bgr, i, window)
                    cleaned = frames_bgr[i].copy()
                    sel = mask.astype(bool)
                    cleaned[sel] = color_bg.astype(np.uint8)[sel]
                else:  # inpaint
                    cleaned = cv2.inpaint(
                        frames_bgr[i], mask, 3, cv2.INPAINT_TELEA
                    )
            else:
                cleaned = frames_bgr[i]

            writer.write(cleaned)

            if (i + 1) % 25 == 0 or i + 1 == n_frames:
                _progress(100.0 * (i + 1) / n_frames)
                print(f"  Frame {i + 1}/{n_frames}...", flush=True)
    finally:
        writer.release()

    print(f"  Frames with particles removed: {particles_total}/{n_frames}")
    print(f"Cleaned video saved to: {output_video}")
    print(f"OUTPUT:output_video={output_video}")
    return {"output_video": output_video}


# run() is the canonical entry point called by the app's script runner.
run = main


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Detects and removes small moving particles from a video."
    )
    parser.add_argument("--nc_params", type=str)
    parser.add_argument("--nc_output", type=str)
    parser.add_argument("--params_json", type=str)
    parser.add_argument("--input_video", type=str)
    parser.add_argument("--output_dir", type=str)
    parser.add_argument("--sensitivity", type=float, default=3.0)
    parser.add_argument("--min_particle_size", type=int, default=2)
    parser.add_argument("--max_particle_size", type=int, default=200)
    parser.add_argument("--temporal_window", type=int, default=0)
    parser.add_argument(
        "--fill_method", type=str, default="inpaint", choices=["inpaint", "background"]
    )
    parser.add_argument(
        "--output_format", type=str, default="mp4", choices=["mp4", "avi"]
    )
    parser.add_argument("--fps", type=int, default=0)

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
        if not args.input_video or not args.output_dir:
            parser.error("--input_video and --output_dir are required")
        params = {
            "input_video": args.input_video,
            "output_dir": args.output_dir,
            "sensitivity": args.sensitivity,
            "min_particle_size": args.min_particle_size,
            "max_particle_size": args.max_particle_size,
            "temporal_window": args.temporal_window,
            "fill_method": args.fill_method,
            "output_format": args.output_format,
            "fps": args.fps,
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
