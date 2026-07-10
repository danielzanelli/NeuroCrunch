# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""generate_rois — Detects neuron somas in a calcium-imaging video and exports ROIs.

Builds a summary projection image from the video (mean, max, or per-pixel
standard deviation across frames), segments bright round blobs with classic
computer-vision steps (Gaussian denoise, Otsu threshold, morphological
cleanup, optional watershed splitting of touching cells), filters the
candidates by diameter and circularity, and fits each survivor to the
requested output shape (circular, rectangular or polygonal). Regions are
written as an ImageJ/FIJI-compatible ROI ZIP — the same format read by
generate_signals and by NeuroCrunch's video ROI overlay.

Contract: see README.md > "<script_name>.py — execution contract".
"""
from __future__ import annotations

import os
import struct
import sys
import zipfile

import numpy as np
from scipy import ndimage as ndi

try:
    import cv2
except ImportError:
    print(
        "ERROR: The 'opencv-python' library is not installed. Run: pip install opencv-python",
        file=sys.stderr,
    )
    raise

try:
    import tifffile

    _HAS_TIFFFILE = True
except ImportError:
    _HAS_TIFFFILE = False


# ---------------------------------------------------------------------------
# Video reading (self-contained: scripts run in isolated namespaces, so
# helpers are not shared across script folders)
# ---------------------------------------------------------------------------


def _iter_tif(path):
    if not _HAS_TIFFFILE:
        raise ImportError("'tifffile' is not installed. Run: pip install tifffile")
    stack = tifffile.imread(path)
    if stack.ndim == 2:
        yield stack.astype(np.float64)
    elif stack.ndim == 3:
        for frame in stack:
            yield frame.astype(np.float64)
    elif stack.ndim == 4:
        for frame in stack:
            if frame.shape[2] >= 3:
                gray = 0.299 * frame[:, :, 0] + 0.587 * frame[:, :, 1] + 0.114 * frame[:, :, 2]
            else:
                gray = frame[:, :, 0]
            yield gray.astype(np.float64)
    else:
        raise ValueError(f"Unexpected TIFF dimensions: {stack.shape}")


def _iter_cv2(path):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise IOError(f"Could not open the video: {path}")
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            yield cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float64)
    finally:
        cap.release()


def iter_video(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".tif", ".tiff"):
        return _iter_tif(path)
    return _iter_cv2(path)


def build_projection(input_video, method):
    """Stream the video once and return a single 2-D summary image."""
    count = 0
    running_sum = None
    running_sumsq = None
    running_max = None

    for frame in iter_video(input_video):
        count += 1
        if method == "max":
            running_max = frame if running_max is None else np.maximum(running_max, frame)
        elif method == "mean":
            running_sum = frame.copy() if running_sum is None else running_sum + frame
        else:  # "std"
            running_sum = frame.copy() if running_sum is None else running_sum + frame
            running_sumsq = frame * frame if running_sumsq is None else running_sumsq + frame * frame

        if count % 200 == 0:
            print(f"  Frame {count}...", flush=True)

    if count == 0:
        raise ValueError("The video contains no readable frames.")
    print(f"  Frames read: {count}")

    if method == "max":
        return running_max
    if method == "mean":
        return running_sum / count
    mean = running_sum / count
    variance = np.maximum(0.0, running_sumsq / count - mean * mean)
    return np.sqrt(variance)


def _to_uint8(img):
    lo, hi = float(np.min(img)), float(np.max(img))
    if hi <= lo:
        return np.zeros(img.shape, dtype=np.uint8)
    scaled = (img - lo) / (hi - lo) * 255.0
    return np.clip(scaled, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Soma segmentation
# ---------------------------------------------------------------------------


def segment_somas(proj_u8, gaussian_sigma, threshold_offset, min_diameter, max_diameter,
                   min_circularity, separate_touching):
    """Return a list of OpenCV contours for blobs that pass the soma filters."""
    if gaussian_sigma > 0:
        k = max(3, int(round(gaussian_sigma * 3)) | 1)  # odd kernel size
        blurred = cv2.GaussianBlur(proj_u8, (k, k), gaussian_sigma)
    else:
        blurred = proj_u8

    otsu_thresh, _ = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    final_thresh = float(np.clip(otsu_thresh + threshold_offset, 0, 255))
    _, mask = cv2.threshold(blurred, final_thresh, 255, cv2.THRESH_BINARY)
    print(f"  Otsu threshold: {otsu_thresh:.1f} (+ offset {threshold_offset:+.1f} = {final_thresh:.1f})")

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    if separate_touching and np.any(mask):
        contours = _watershed_contours(mask, blurred, min_diameter)
    else:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    somas = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area <= 0:
            continue
        diameter = 2.0 * np.sqrt(area / np.pi)
        if diameter < min_diameter or diameter > max_diameter:
            continue
        perimeter = cv2.arcLength(cnt, True)
        circularity = (4.0 * np.pi * area / (perimeter * perimeter)) if perimeter > 0 else 0.0
        if circularity < min_circularity:
            continue
        somas.append(cnt)
    return somas


def _watershed_contours(mask, blurred, min_diameter):
    """Split touching somas: local-maxima seeding on the distance transform,
    then classic marker-based watershed."""
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    min_peak_distance = max(1, min_diameter // 2)
    filt_size = int(2 * min_peak_distance + 1)
    local_max = (dist == ndi.maximum_filter(dist, size=filt_size)) & (dist > 0)
    peak_labels, n_peaks = ndi.label(local_max)
    if n_peaks == 0:
        return []

    markers = np.zeros(mask.shape, dtype=np.int32)
    markers[mask == 0] = 1  # background
    markers[peak_labels > 0] = peak_labels[peak_labels > 0] + 1  # soma seeds: 2..n_peaks+1

    img_3ch = cv2.cvtColor(blurred, cv2.COLOR_GRAY2BGR)
    cv2.watershed(img_3ch, markers)

    contours = []
    for label in range(2, n_peaks + 2):
        region = (markers == label).astype(np.uint8) * 255
        cnts, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours.extend(cnts)
    return contours


def _shape_from_contour(cnt, roi_type):
    """Fit *cnt* to the requested output shape. Returns (shape_dict, centroid)."""
    if roi_type == "circular":
        (cx, cy), radius = cv2.minEnclosingCircle(cnt)
        shape = dict(kind="oval", left=cx - radius, top=cy - radius,
                     width=2 * radius, height=2 * radius)
        return shape, (cx, cy)

    if roi_type == "rectangular":
        x, y, w, h = cv2.boundingRect(cnt)
        shape = dict(kind="rect", left=float(x), top=float(y), width=float(w), height=float(h))
        return shape, (x + w / 2.0, y + h / 2.0)

    # polygonal: simplify the traced contour to a manageable number of vertices
    perimeter = cv2.arcLength(cnt, True)
    approx = cv2.approxPolyDP(cnt, max(1.0, 0.01 * perimeter), True)
    xs = [float(p[0][0]) for p in approx]
    ys = [float(p[0][1]) for p in approx]
    if len(xs) < 3:
        x, y, w, h = cv2.boundingRect(cnt)
        xs, ys = [x, x + w, x + w, x], [y, y, y + h, y + h]
    m = cv2.moments(cnt)
    cx = m["m10"] / m["m00"] if m["m00"] else xs[0]
    cy = m["m01"] / m["m00"] if m["m00"] else ys[0]
    return dict(kind="polygon", x=xs, y=ys), (cx, cy)


# ---------------------------------------------------------------------------
# ImageJ ROI encoding (no writer library is bundled — only 'read_roi')
# Byte layout verified against read_roi's decoder (OFFSET table).
# ---------------------------------------------------------------------------

_ROI_TYPE_RECT = 1
_ROI_TYPE_OVAL = 2
_ROI_TYPE_TRACED = 8


def _pack_roi(roi_type_code, top, left, bottom, right, xs=None, ys=None):
    xs, ys = xs or [], ys or []
    header = bytearray(64)  # zero-initialized: unused fields (colors, stroke, etc.) stay 0
    header[0:4] = b"Iout"
    struct.pack_into(">H", header, 4, 227)  # version
    header[6] = roi_type_code
    struct.pack_into(">h", header, 8, int(round(top)))
    struct.pack_into(">h", header, 10, int(round(left)))
    struct.pack_into(">h", header, 12, int(round(bottom)))
    struct.pack_into(">h", header, 14, int(round(right)))
    struct.pack_into(">H", header, 16, len(xs))

    coords = bytearray()
    for x in xs:
        coords += struct.pack(">H", int(round(x - left)))
    for y in ys:
        coords += struct.pack(">H", int(round(y - top)))

    # read_roi's decoder unconditionally reads channel/slice/frame position from
    # an "extended header" once hdr2Offset > 0; real ImageJ always writes one, so
    # a zero-filled 64-byte block (all-zero position = "unset") is required even
    # though this exporter has nothing to put in it, or read_roi raises UnboundLocalError.
    header2_offset = 64 + len(coords)
    struct.pack_into(">I", header, 60, header2_offset)
    header2 = bytearray(64)

    return bytes(header) + bytes(coords) + bytes(header2)


def _imagej_roi_bytes(shape):
    kind = shape["kind"]
    if kind == "rect":
        left, top, width, height = shape["left"], shape["top"], shape["width"], shape["height"]
        return _pack_roi(_ROI_TYPE_RECT, top, left, top + height, left + width)
    if kind == "oval":
        left, top, width, height = shape["left"], shape["top"], shape["width"], shape["height"]
        return _pack_roi(_ROI_TYPE_OVAL, top, left, top + height, left + width)
    xs, ys = shape["x"], shape["y"]
    return _pack_roi(_ROI_TYPE_TRACED, min(ys), min(xs), max(ys), max(xs), xs=xs, ys=ys)


def _write_roi_zip(shapes, output_dir, video_stem):
    zip_path = os.path.join(output_dir, f"{video_stem}_rois.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, shape in enumerate(shapes, start=1):
            zf.writestr(f"{i:04d}.roi", _imagej_roi_bytes(shape))
    return zip_path


def _save_preview(proj_u8, shapes, output_dir, video_stem):
    preview = cv2.cvtColor(proj_u8, cv2.COLOR_GRAY2BGR)
    for i, shape in enumerate(shapes, start=1):
        color, font = (0, 255, 0), cv2.FONT_HERSHEY_SIMPLEX
        if shape["kind"] == "rect":
            x, y, w, h = int(shape["left"]), int(shape["top"]), int(shape["width"]), int(shape["height"])
            cv2.rectangle(preview, (x, y), (x + w, y + h), color, 1)
            origin = (x, max(0, y - 3))
        elif shape["kind"] == "oval":
            cx, cy = int(shape["left"] + shape["width"] / 2), int(shape["top"] + shape["height"] / 2)
            axes = (int(shape["width"] / 2), int(shape["height"] / 2))
            cv2.ellipse(preview, (cx, cy), axes, 0, 0, 360, color, 1)
            origin = (cx, max(0, cy - axes[1] - 3))
        else:
            pts = np.array(list(zip(shape["x"], shape["y"])), dtype=np.int32).reshape(-1, 1, 2)
            cv2.polylines(preview, [pts], True, color, 1)
            origin = (int(shape["x"][0]), int(shape["y"][0]))
        cv2.putText(preview, str(i), origin, font, 0.35, color, 1)

    preview_path = os.path.join(output_dir, f"{video_stem}_rois_preview.png")
    cv2.imwrite(preview_path, preview)
    return preview_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(params):
    input_video = params["input_video"]
    output_dir = params["output_dir"]
    roi_type = params.get("roi_type", "circular")
    projection_method = params.get("projection_method", "std")
    gaussian_sigma = float(params.get("gaussian_sigma", 1.5))
    threshold_offset = float(params.get("threshold_offset", 0.0))
    min_diameter = int(params.get("min_soma_diameter_px", 5))
    max_diameter = int(params.get("max_soma_diameter_px", 40))
    min_circularity = float(params.get("min_circularity", 0.5))
    separate_touching = bool(params.get("separate_touching", True))

    if not os.path.isfile(input_video):
        raise FileNotFoundError(f"Input video not found: {input_video}")
    if min_diameter > max_diameter:
        raise ValueError("min_soma_diameter_px must be <= max_soma_diameter_px")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Reading video: {os.path.basename(input_video)}")
    print(f"  Projection: {projection_method}")
    proj = build_projection(input_video, projection_method)
    print("PROGRESS:40")

    proj_u8 = _to_uint8(proj)

    print("Segmenting somas...")
    contours = segment_somas(
        proj_u8, gaussian_sigma, threshold_offset,
        min_diameter, max_diameter, min_circularity, separate_touching,
    )
    print(f"  Candidate somas kept after filtering: {len(contours)}")
    print("PROGRESS:70")

    fitted = [_shape_from_contour(cnt, roi_type) for cnt in contours]
    fitted.sort(key=lambda item: (item[1][1], item[1][0]))  # reading order: top-to-bottom, left-to-right
    shapes = [shape for shape, _ in fitted]

    if not shapes:
        raise ValueError(
            "No somas detected. Try lowering 'min_circularity', widening the "
            "diameter range, or adjusting 'threshold_offset'."
        )

    video_stem = os.path.splitext(os.path.basename(input_video))[0]
    roi_zip = _write_roi_zip(shapes, output_dir, video_stem)
    print(f"ROI ZIP saved: {roi_zip} ({len(shapes)} ROIs)")
    print("PROGRESS:90")

    preview_png = _save_preview(proj_u8, shapes, output_dir, video_stem)
    print(f"Preview image saved: {preview_png}")
    print("PROGRESS:100")

    return {"roi_zip": roi_zip, "preview_png": preview_png}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Detects neuron somas and exports ROIs.")
    parser.add_argument("--input_video", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--roi_type", default="circular", choices=["circular", "rectangular", "polygonal"])
    parser.add_argument("--projection_method", default="std", choices=["mean", "max", "std"])
    parser.add_argument("--gaussian_sigma", type=float, default=1.5)
    parser.add_argument("--threshold_offset", type=float, default=0.0)
    parser.add_argument("--min_soma_diameter_px", type=int, default=5)
    parser.add_argument("--max_soma_diameter_px", type=int, default=40)
    parser.add_argument("--min_circularity", type=float, default=0.5)
    parser.add_argument("--separate_touching", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    print(run(vars(args)))
