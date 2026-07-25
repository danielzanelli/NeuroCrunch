# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""generate_rois — Detects neuron somas in a calcium-imaging video and exports ROIs.

Supervised, per-video approach: the user paints a few example regions over
neurons ("inner") and over background ("outer") with NeuroCrunch's video ROI
editor and saves each set as an ImageJ ROI ZIP. This script builds a summary
projection of the video (mean, max or per-pixel standard deviation), computes a
small multi-scale feature stack on it, and trains a random forest (a compact,
self-contained NumPy implementation — see ``_RandomForest``) on the painted
examples to classify every pixel as neuron/background. The resulting
probability map is thresholded, cleaned,
optionally split where somas touch, filtered by diameter/circularity, and each
survivor is fitted to the requested output shape (circular, rectangular or
polygonal). Regions are written as an ImageJ/FIJI-compatible ROI ZIP — the same
format read by generate_signals and by NeuroCrunch's video ROI overlay.

Only libraries bundled with the app are used (numpy, cv2, tifffile, read_roi,
matplotlib); there is no scipy or scikit-learn dependency.

Contract: see README.md > "Writing Your Own Scripts".
"""
from __future__ import annotations

import os
import struct
import sys
import zipfile

import numpy as np

try:
    import cv2
except ImportError:
    print(
        "ERROR: The 'opencv-python' library is not installed. Run: pip install opencv-python",
        file=sys.stderr,
    )
    raise

try:
    import read_roi
except ImportError:
    print(
        "ERROR: The 'read_roi' library is not installed. Run: pip install read_roi",
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
# Feature stack (cv2 only) — multi-scale intensity / gradient / texture cues
# ---------------------------------------------------------------------------

_FEATURE_SIGMAS = (1.0, 2.0, 4.0)


def build_feature_stack(proj_u8):
    """Return an (H, W, K) float32 stack of per-pixel features for the forest.

    Channels: raw intensity, Gaussian-smoothed intensity, gradient magnitude and
    Laplacian at several scales, plus a difference-of-Gaussians. These give the
    classifier both brightness and local-shape/texture context so it can tell a
    bright round soma from bright background structure.
    """
    base = proj_u8.astype(np.float32)
    channels = [base]

    smoothed = {}
    for sigma in _FEATURE_SIGMAS:
        g = cv2.GaussianBlur(base, (0, 0), sigma)
        smoothed[sigma] = g
        channels.append(g)
        gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
        channels.append(cv2.magnitude(gx, gy))
        channels.append(cv2.Laplacian(g, cv2.CV_32F, ksize=3))

    channels.append(smoothed[_FEATURE_SIGMAS[0]] - smoothed[_FEATURE_SIGMAS[1]])  # DoG

    return np.stack(channels, axis=-1).astype(np.float32)


# ---------------------------------------------------------------------------
# ImageJ ROI rasterization (copied from generate_signals — isolated namespaces)
# ---------------------------------------------------------------------------


def _polygon_mask(xs, ys, shape):
    """Return a boolean mask (H × W) for a polygon defined by *xs*, *ys*."""
    from matplotlib.path import Path

    H, W = shape
    col_coords, row_coords = np.meshgrid(np.arange(W), np.arange(H))
    points = np.column_stack([col_coords.ravel(), row_coords.ravel()])
    path = Path(list(zip(xs, ys)))
    return path.contains_points(points).reshape(H, W)


def _rect_mask(left, top, width, height, shape):
    """Return a boolean mask for a rectangle."""
    H, W = shape
    mask = np.zeros(shape, dtype=bool)
    r0, r1 = max(0, int(top)), min(H, int(top + height))
    c0, c1 = max(0, int(left)), min(W, int(left + width))
    mask[r0:r1, c0:c1] = True
    return mask


def _oval_mask(left, top, width, height, shape):
    """Return a boolean mask for an oval/ellipse (approximated as a polygon)."""
    theta = np.linspace(0, 2 * np.pi, 360)
    cx, cy = left + width / 2, top + height / 2
    xs = (cx + (width / 2) * np.cos(theta)).tolist()
    ys = (cy + (height / 2) * np.sin(theta)).tolist()
    return _polygon_mask(xs, ys, shape)


def _roi_to_mask(name, roi, shape):
    """Rasterize one read_roi dict to a boolean mask, or None if unusable."""
    roi_type = roi.get("type", "").lower()
    if roi_type in ("polygon", "freehand", "traced", "freeline", "polyline"):
        xs = [float(v) for v in roi.get("x", [])]
        ys = [float(v) for v in roi.get("y", [])]
        if len(xs) >= 3:
            return _polygon_mask(xs, ys, shape)
    elif roi_type in ("rectangle", "rect"):
        return _rect_mask(roi["left"], roi["top"], roi["width"], roi["height"], shape)
    elif roi_type in ("oval", "ellipse"):
        return _oval_mask(roi["left"], roi["top"], roi["width"], roi["height"], shape)
    else:  # fallback on available geometry keys
        if "x" in roi and "y" in roi and len(roi["x"]) >= 3:
            return _polygon_mask([float(v) for v in roi["x"]], [float(v) for v in roi["y"]], shape)
        if all(k in roi for k in ("left", "top", "width", "height")):
            return _rect_mask(roi["left"], roi["top"], roi["width"], roi["height"], shape)
    print(f"  Warning: could not rasterize ROI '{name}' (type '{roi_type}'), skipping.", file=sys.stderr)
    return None


def load_label_mask(zip_path, shape):
    """Union every ROI in *zip_path* into a single boolean label mask."""
    if not os.path.isfile(zip_path):
        raise FileNotFoundError(f"ROI ZIP not found: {zip_path}")
    rois = read_roi.read_roi_zip(zip_path)
    union = np.zeros(shape, dtype=bool)
    for name, roi in rois.items():
        mask = _roi_to_mask(name, roi, shape)
        if mask is not None:
            union |= mask
    return union


# ---------------------------------------------------------------------------
# Random-forest pixel classification
#
# Implemented in pure NumPy: the bundled OpenCV 5.x headless wheel does not ship
# the `cv2.ml` module, and scikit-learn (which would pull in scipy) is not part
# of the app's dependency set. This compact CART/bagging forest keeps the
# dependency footprint unchanged while giving the user the requested ML model.
# ---------------------------------------------------------------------------

_MAX_SAMPLES_PER_CLASS = 10000  # cap training pixels per class for speed


class _RandomForest:
    """A small bootstrap-aggregated forest of Gini CART trees for two classes."""

    def __init__(self, n_trees=40, max_depth=10, min_samples=4, n_features=None, seed=0):
        self.n_trees = n_trees
        self.max_depth = max_depth
        self.min_samples = min_samples
        self.n_features = n_features
        self.seed = seed
        self.trees = []

    def fit(self, X, y):
        X = np.ascontiguousarray(X, dtype=np.float32)
        y = np.asarray(y, dtype=np.float64)
        n, k = X.shape
        self._n_feat = self.n_features or max(1, int(round(np.sqrt(k))))
        rng = np.random.default_rng(self.seed)
        self.trees = []
        for _ in range(self.n_trees):
            boot = rng.integers(0, n, n)  # bootstrap sample with replacement
            self.trees.append(self._build(X[boot], y[boot], 0, rng))
        return self

    def _build(self, X, y, depth, rng):
        m = X.shape[0]
        p = float(y.mean()) if m else 0.0
        if depth >= self.max_depth or m < self.min_samples or p in (0.0, 1.0):
            return {"leaf": True, "p": p}
        feat, thr = self._best_split(X, y, rng)
        if feat is None:
            return {"leaf": True, "p": p}
        left = X[:, feat] <= thr
        if left.all() or not left.any():
            return {"leaf": True, "p": p}
        return {
            "leaf": False, "f": feat, "t": thr,
            "L": self._build(X[left], y[left], depth + 1, rng),
            "R": self._build(X[~left], y[~left], depth + 1, rng),
        }

    def _best_split(self, X, y, rng):
        m, k = X.shape
        feats = rng.choice(k, self._n_feat, replace=False)
        total_pos = y.sum()
        best_g, best = np.inf, (None, None)
        for f in feats:
            vals = X[:, f]
            order = np.argsort(vals, kind="mergesort")
            sv, sy = vals[order], y[order]
            nl = np.arange(1, m)
            nr = m - nl
            pl = np.cumsum(sy)[:-1]          # positives in the left partition
            pr = total_pos - pl
            gini_l = 1.0 - (pl / nl) ** 2 - ((nl - pl) / nl) ** 2
            gini_r = 1.0 - (pr / nr) ** 2 - ((nr - pr) / nr) ** 2
            impurity = (nl * gini_l + nr * gini_r) / m
            impurity[sv[1:] == sv[:-1]] = np.inf  # can't split between equal values
            i = int(np.argmin(impurity))
            if impurity[i] < best_g:
                best_g = impurity[i]
                best = (int(f), float((sv[i] + sv[i + 1]) / 2.0))
        return best

    def predict_proba(self, X):
        X = np.ascontiguousarray(X, dtype=np.float32)
        acc = np.zeros(X.shape[0], dtype=np.float64)
        all_idx = np.arange(X.shape[0])
        for tree in self.trees:
            stack = [(tree, all_idx)]
            while stack:
                node, idx = stack.pop()
                if node["leaf"]:
                    acc[idx] += node["p"]
                    continue
                go_left = X[idx, node["f"]] <= node["t"]
                stack.append((node["L"], idx[go_left]))
                stack.append((node["R"], idx[~go_left]))
        return acc / len(self.trees)


def train_pixel_forest(features, inner_mask, outer_mask):
    """Train a random forest on the painted example pixels; return the model."""
    k = features.shape[2]
    flat = features.reshape(-1, k)

    pos = inner_mask.ravel()
    neg = outer_mask.ravel() & ~pos  # inner wins where the two overlap

    pos_idx = np.flatnonzero(pos)
    neg_idx = np.flatnonzero(neg)
    if pos_idx.size == 0:
        raise ValueError("The neuron (inner) ROI ZIP labels no pixels. Draw regions over somas and re-save.")
    if neg_idx.size == 0:
        raise ValueError("The background (outer) ROI ZIP labels no pixels. Draw regions over background and re-save.")

    rng = np.random.default_rng(0)
    if pos_idx.size > _MAX_SAMPLES_PER_CLASS:
        pos_idx = rng.choice(pos_idx, _MAX_SAMPLES_PER_CLASS, replace=False)
    if neg_idx.size > _MAX_SAMPLES_PER_CLASS:
        neg_idx = rng.choice(neg_idx, _MAX_SAMPLES_PER_CLASS, replace=False)
    print(f"  Training samples: {pos_idx.size} neuron / {neg_idx.size} background")

    X = np.vstack([flat[pos_idx], flat[neg_idx]])
    y = np.concatenate([np.ones(pos_idx.size), np.zeros(neg_idx.size)])
    return _RandomForest().fit(X, y)


def predict_probability(rf, features):
    """Return an (H, W) float32 map of the forest's neuron probability."""
    H, W, k = features.shape
    proba = rf.predict_proba(features.reshape(-1, k))
    return proba.reshape(H, W).astype(np.float32)


# ---------------------------------------------------------------------------
# Soma segmentation from the probability map (cv2 only — no scipy)
# ---------------------------------------------------------------------------


def segment_somas(prob_map, threshold, min_diameter, max_diameter,
                   min_circularity, separate_touching):
    """Return a list of OpenCV contours for blobs that pass the soma filters."""
    mask = (prob_map >= threshold).astype(np.uint8) * 255

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    if separate_touching and np.any(mask):
        # A grayscale guide for the watershed: the probability map itself.
        guide = _to_uint8(prob_map)
        contours = _watershed_contours(mask, guide, min_diameter)
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


def _watershed_contours(mask, guide, min_diameter):
    """Split touching somas: local-maxima seeding on the distance transform,
    then classic marker-based watershed. Local maxima and labeling use only cv2
    (dilation-equality peaks + connected components), so no scipy is needed."""
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    min_peak_distance = max(1, min_diameter // 2)
    filt_size = int(2 * min_peak_distance + 1)

    peak_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (filt_size, filt_size))
    dilated = cv2.dilate(dist, peak_kernel)
    local_max = ((dist == dilated) & (dist > 0)).astype(np.uint8)

    n_labels, peak_labels = cv2.connectedComponents(local_max, connectivity=8)
    n_peaks = n_labels - 1  # label 0 is background
    if n_peaks == 0:
        return []

    markers = np.zeros(mask.shape, dtype=np.int32)
    markers[mask == 0] = 1  # background
    markers[peak_labels > 0] = peak_labels[peak_labels > 0] + 1  # soma seeds: 2..n_peaks+1

    img_3ch = cv2.cvtColor(guide, cv2.COLOR_GRAY2BGR)
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


def _save_probability(prob_map, output_dir, video_stem):
    heat = cv2.applyColorMap(_to_uint8(prob_map), cv2.COLORMAP_JET)
    path = os.path.join(output_dir, f"{video_stem}_probability.png")
    cv2.imwrite(path, heat)
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(params):
    input_video = params["input_video"]
    inner_rois = params["inner_rois"]
    outer_rois = params["outer_rois"]
    output_dir = params["output_dir"]
    roi_type = params.get("roi_type", "circular")
    projection_method = params.get("projection_method", "std")
    threshold = float(params.get("probability_threshold", 0.5))
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
    proj_u8 = _to_uint8(proj)
    shape = proj_u8.shape
    print("PROGRESS:35")

    print("Building feature stack...")
    features = build_feature_stack(proj_u8)

    print("Loading painted example regions...")
    inner_mask = load_label_mask(inner_rois, shape)
    outer_mask = load_label_mask(outer_rois, shape)
    print(f"  Neuron pixels: {int(inner_mask.sum())}, background pixels: {int(outer_mask.sum())}")

    print("Training random forest...")
    rf = train_pixel_forest(features, inner_mask, outer_mask)
    print("PROGRESS:60")

    print("Classifying pixels...")
    prob_map = predict_probability(rf, features)
    print("PROGRESS:75")

    print(f"Segmenting somas (threshold {threshold:.2f})...")
    contours = segment_somas(
        prob_map, threshold, min_diameter, max_diameter,
        min_circularity, separate_touching,
    )
    print(f"  Candidate somas kept after filtering: {len(contours)}")
    print("PROGRESS:85")

    fitted = [_shape_from_contour(cnt, roi_type) for cnt in contours]
    fitted.sort(key=lambda item: (item[1][1], item[1][0]))  # reading order: top-to-bottom, left-to-right
    shapes = [shp for shp, _ in fitted]

    if not shapes:
        raise ValueError(
            "No somas detected. Try lowering the detection threshold, widening the "
            "diameter range, lowering 'min_circularity', or painting clearer examples."
        )

    video_stem = os.path.splitext(os.path.basename(input_video))[0]
    roi_zip = _write_roi_zip(shapes, output_dir, video_stem)
    print(f"ROI ZIP saved: {roi_zip} ({len(shapes)} ROIs)")

    preview_png = _save_preview(proj_u8, shapes, output_dir, video_stem)
    print(f"Preview image saved: {preview_png}")
    prob_png = _save_probability(prob_map, output_dir, video_stem)
    print(f"Probability map saved: {prob_png}")
    print("PROGRESS:100")

    return {"roi_zip": roi_zip, "preview_png": preview_png}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Detects neuron somas with a trained random forest and exports ROIs.")
    parser.add_argument("--input_video", required=True)
    parser.add_argument("--inner_rois", required=True, help="ROI ZIP with neuron (positive) example regions")
    parser.add_argument("--outer_rois", required=True, help="ROI ZIP with background (negative) example regions")
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--roi_type", default="circular", choices=["circular", "rectangular", "polygonal"])
    parser.add_argument("--projection_method", default="std", choices=["mean", "max", "std"])
    parser.add_argument("--probability_threshold", type=float, default=0.5)
    parser.add_argument("--min_soma_diameter_px", type=int, default=5)
    parser.add_argument("--max_soma_diameter_px", type=int, default=40)
    parser.add_argument("--min_circularity", type=float, default=0.5)
    parser.add_argument("--separate_touching", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    print(run(vars(args)))
