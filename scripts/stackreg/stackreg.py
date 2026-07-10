# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""stackreg - Stabilizes drift in a video by registering every frame.

Works like the StackReg plugin in ImageJ/FIJI: each frame is aligned to a
reference (the previous frame, the first frame, or the mean frame) and warped
back into place, producing a drift-corrected video. Translation is estimated
with phase correlation; Rigid Body and Affine motions are estimated with an
ECC (Enhanced Correlation Coefficient) optimizer. Both live in OpenCV, so no
extra dependency is required.

Command-line usage:
    python stackreg.py --input_video video.tif --output_dir ./results \\
                   [--transformation Translation] [--reference Previous] \\
                   [--output_format tif] [--fps 10]

    # Contract used by ScriptRunner: read parameters from a JSON file and write
    # the declared outputs to another JSON file.
    python stackreg.py --nc_params params.json --nc_output output.json
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
        "ERROR: The 'opencv-python' library is not installed. Run: pip install opencv-python",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    import tifffile

    _HAS_TIFFFILE = True
except ImportError:
    _HAS_TIFFFILE = False


# Map the human-readable choices from config.json to OpenCV motion models.
_MOTION_MODELS = {
    "translation": None,  # handled by phase correlation, not ECC
    "rigid body": cv2.MOTION_EUCLIDEAN,
    "affine": cv2.MOTION_AFFINE,
}


# ---------------------------------------------------------------------------
# Video reading
# ---------------------------------------------------------------------------


def load_frames(path: str) -> Tuple[List[np.ndarray], bool]:
    """Load every frame of *path* into memory, preserving dtype and channels.

    Returns ``(frames, is_color)`` where each frame is either a 2-D array
    (grayscale) or a 3-D H×W×3 BGR array.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in (".tif", ".tiff"):
        return _load_tif(path)
    return _load_cv2(path)


def _load_tif(path: str) -> Tuple[List[np.ndarray], bool]:
    if not _HAS_TIFFFILE:
        raise ImportError("'tifffile' is not installed. Run: pip install tifffile")
    stack = tifffile.imread(path)
    if stack.ndim == 2:  # single grayscale frame
        return [stack], False
    if stack.ndim == 3:  # (frames, H, W) grayscale stack
        return [frame for frame in stack], False
    if stack.ndim == 4:  # (frames, H, W, C)
        return [frame for frame in stack], True
    raise ValueError(f"Unexpected TIFF dimensions: {stack.shape}")


def _load_cv2(path: str) -> Tuple[List[np.ndarray], bool]:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise IOError(f"Could not open the video: {path}")
    frames: List[np.ndarray] = []
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame)  # BGR uint8
    finally:
        cap.release()
    if not frames:
        raise ValueError(f"No frames could be read from: {path}")
    return frames, True


def _to_gray_f32(frame: np.ndarray) -> np.ndarray:
    """Return a single-channel float32 view used for registration."""
    if frame.ndim == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame
    return gray.astype(np.float32)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def _identity() -> np.ndarray:
    return np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)


def _to_3x3(mat_2x3: np.ndarray) -> np.ndarray:
    out = np.eye(3, dtype=np.float32)
    out[:2, :] = mat_2x3
    return out


def _estimate_translation(ref: np.ndarray, cur: np.ndarray, window: np.ndarray) -> np.ndarray:
    """Return the 2×3 matrix warping *cur* onto *ref* by translation only."""
    (dx, dy), _ = cv2.phaseCorrelate(ref, cur, window)
    # phaseCorrelate returns how much *cur* is shifted relative to *ref*;
    # to bring it back we translate by the opposite amount.
    mat = _identity()
    mat[0, 2] = -dx
    mat[1, 2] = -dy
    return mat


def _estimate_ecc(ref: np.ndarray, cur: np.ndarray, motion: int) -> np.ndarray:
    """Return the 2×3 matrix warping *cur* onto *ref* using ECC.

    Falls back to the identity if the optimizer fails to converge.
    """
    warp = _identity()
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 1e-4)
    try:
        _, warp = cv2.findTransformECC(ref, cur, warp, motion, criteria, None, 5)
    except cv2.error:
        # No convergence for this frame: leave it unregistered rather than abort.
        return _identity()
    # findTransformECC maps reference→current coordinates; invert it so the
    # matrix warps *cur* onto *ref* directly, matching the translation path
    # and letting _warp apply every matrix the same way.
    return cv2.invertAffineTransform(warp)


def register(
    grays: List[np.ndarray],
    transformation: str,
    reference: str,
) -> List[np.ndarray]:
    """Compute a 2×3 warp matrix per frame, mapping it onto the reference frame.

    Parameters
    ----------
    grays : list of float32 single-channel frames.
    transformation : "translation", "rigid body", or "affine".
    reference : "previous", "first", or "mean".
    """
    n = len(grays)
    if n == 0:
        return []

    shape = grays[0].shape
    window = cv2.createHanningWindow((shape[1], shape[0]), cv2.CV_32F)
    motion = _MOTION_MODELS[transformation]
    is_translation = motion is None

    mats: List[np.ndarray] = [_identity()]

    if reference == "previous":
        # Align each frame to the one before it and accumulate the transform,
        # so every frame lands in the coordinate system of the first frame.
        cumulative = _to_3x3(_identity())
        for i in range(1, n):
            if is_translation:
                step = _estimate_translation(grays[i - 1], grays[i], window)
            else:
                step = _estimate_ecc(grays[i - 1], grays[i], motion)
            cumulative = cumulative @ _to_3x3(step)
            mats.append(cumulative[:2, :].astype(np.float32))
            _tick(i, n)
    else:
        if reference == "mean":
            ref = np.mean(np.stack(grays), axis=0).astype(np.float32)
        else:  # "first"
            ref = grays[0]
        for i in range(1, n):
            if is_translation:
                mats.append(_estimate_translation(ref, grays[i], window))
            else:
                mats.append(_estimate_ecc(ref, grays[i], motion))
            _tick(i, n)

    return mats


def _tick(i: int, n: int) -> None:
    """Emit a registration progress update (0–50 % of the run)."""
    if (i + 1) % 25 == 0 or i == n - 1:
        pct = (i + 1) / n * 50.0
        print(f"PROGRESS:{pct:.0f}")
        print(f"  Registered {i + 1}/{n} frames...", flush=True)


# ---------------------------------------------------------------------------
# Warping + writing
# ---------------------------------------------------------------------------


def _warp(frame: np.ndarray, mat: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    return cv2.warpAffine(
        frame, mat, (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )


def _to_uint8_bgr(frame: np.ndarray) -> np.ndarray:
    """Scale/convert a warped frame to 8-bit BGR for MP4/AVI writing."""
    if frame.dtype != np.uint8:
        f = frame.astype(np.float32)
        peak = float(f.max())
        if peak > 0:
            f = f / peak * 255.0
        frame = f.astype(np.uint8)
    if frame.ndim == 2:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    return frame


def write_video(
    frames: List[np.ndarray],
    mats: List[np.ndarray],
    output_path: str,
    output_format: str,
    fps: int,
) -> None:
    """Warp every frame with its matrix and write the drift-corrected video."""
    n = len(frames)

    if output_format == "tif":
        warped = []
        for i, (frame, mat) in enumerate(zip(frames, mats)):
            warped.append(_warp(frame, mat))
            _tick_write(i, n)
        tifffile.imwrite(output_path, np.stack(warped))
        return

    # MP4 / AVI via OpenCV's VideoWriter (8-bit).
    h, w = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*("mp4v" if output_format == "mp4" else "MJPG"))
    writer = cv2.VideoWriter(output_path, fourcc, float(fps), (w, h), isColor=True)
    if not writer.isOpened():
        raise IOError(f"Could not open the video writer for: {output_path}")
    try:
        for i, (frame, mat) in enumerate(zip(frames, mats)):
            writer.write(_to_uint8_bgr(_warp(frame, mat)))
            _tick_write(i, n)
    finally:
        writer.release()


def _tick_write(i: int, n: int) -> None:
    """Emit a warp/write progress update (50–100 % of the run)."""
    if (i + 1) % 25 == 0 or i == n - 1:
        pct = 50.0 + (i + 1) / n * 50.0
        print(f"PROGRESS:{pct:.0f}")
        print(f"  Wrote {i + 1}/{n} frames...", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(params: Dict[str, Any]) -> Dict[str, Any]:
    input_video = os.path.abspath(os.path.normpath(params["input_video"]))
    output_dir = os.path.abspath(os.path.normpath(params["output_dir"]))
    transformation = str(params.get("transformation", "Translation")).strip().lower()
    reference = str(params.get("reference", "Previous")).strip().lower()
    output_format = str(params.get("output_format", "tif")).strip().lower()
    fps = int(params.get("fps", 10))

    if transformation not in _MOTION_MODELS:
        raise ValueError(f"Unknown transformation: {params.get('transformation')!r}")
    if reference not in ("previous", "first", "mean"):
        raise ValueError(f"Unknown reference: {params.get('reference')!r}")
    if output_format not in ("tif", "mp4", "avi"):
        raise ValueError(f"Unknown output format: {params.get('output_format')!r}")
    if output_format == "tif" and not _HAS_TIFFFILE:
        raise ImportError("'tifffile' is required for TIFF output. Run: pip install tifffile")

    if not os.path.isfile(input_video):
        raise FileNotFoundError(f"Input video not found: {input_video}")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Loading: {os.path.basename(input_video)}")
    frames, _ = load_frames(input_video)
    n = len(frames)
    h, w = frames[0].shape[:2]
    print(f"  {n} frame(s), {w} x {h} px")
    print(f"  Transformation: {transformation}  |  Reference: {reference}")

    if n < 2:
        print("Video has fewer than 2 frames; nothing to stabilize.")
        mats = [_identity() for _ in frames]
    else:
        print("Registering frames...")
        grays = [_to_gray_f32(f) for f in frames]
        mats = register(grays, transformation, reference)

    video_stem = os.path.splitext(os.path.basename(input_video))[0]
    output_video = os.path.join(output_dir, f"{video_stem}_stabilized.{output_format}")

    print(f"Writing stabilized video: {output_video}")
    write_video(frames, mats, output_video, output_format, fps)
    print("PROGRESS:100")
    print(f"Saved: {output_video}")

    return {"output_video": output_video}


# run() is the canonical entry point called by the app's script runner.
run = main


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stabilizes drift in a video by registering every frame."
    )
    parser.add_argument("--nc_params", type=str,
                        help="Path to a JSON file with all parameters (ScriptRunner contract).")
    parser.add_argument("--nc_output", type=str,
                        help="Path to write the declared outputs as JSON (ScriptRunner contract).")
    parser.add_argument("--params_json", type=str,
                        help="All parameters as a JSON string (alternative to the individual flags).")
    parser.add_argument("--input_video", type=str, help="Path to the input video")
    parser.add_argument("--output_dir", type=str, help="Output folder")
    parser.add_argument("--transformation", type=str, default="Translation",
                        choices=["Translation", "Rigid Body", "Affine"])
    parser.add_argument("--reference", type=str, default="Previous",
                        choices=["Previous", "First", "Mean"])
    parser.add_argument("--output_format", type=str, default="tif",
                        choices=["tif", "mp4", "avi"])
    parser.add_argument("--fps", type=int, default=10)

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
            "transformation": args.transformation,
            "reference": args.reference,
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
