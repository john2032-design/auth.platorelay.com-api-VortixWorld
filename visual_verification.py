# visual_verification.py
"""
visual_verification.py
======================
Detects shape type, area, and dominant color from a base64-encoded image.

Core strategy:
  1. Sample the background color from image corners.
  2. Build a foreground mask = pixels that differ from background by > threshold.
  3. Find contours on that mask — these are the actual shapes, not the canvas.
  4. Classify the largest foreground contour.

This avoids the canvas-detection bug where thresholding picks up the entire
image rectangle as "the shape."
"""

import cv2
import numpy as np
import base64
import json
import os

DATASET_FILE = "fine_tuning_dataset.jsonl"

COLOR_RANGES = {
    "red":    [((0,   120,  80), (10,  255, 255)),
               ((160, 120,  80), (180, 255, 255))],
    "orange": [((11,  120,  80), (25,  255, 255))],
    "yellow": [((26,  120,  80), (34,  255, 255))],
    "green":  [((35,   80,  60), (85,  255, 255))],
    "blue":   [((86,   80,  60), (130, 255, 255))],
    "purple": [((131,  80,  60), (159, 255, 255))],
    "white":  [((0,     0, 190), (180,  40, 255))],
    "black":  [((0,     0,   0), (180, 255,  60))],
    "gray":   [((0,     0,  61), (180,  40, 189))],
}

# ─────────────────────────────────────────────────────────────────────────────
# I/O helpers
# ─────────────────────────────────────────────────────────────────────────────

def save_to_dataset(b64_string: str, analysis: dict, instruction: str = ""):
    try:
        with open(DATASET_FILE, "a") as f:
            f.write(json.dumps({
                "image": b64_string,
                "meta":  {"instruction": instruction},
                "label": {
                    "type":     analysis["type"],
                    "area":     analysis["area"],
                    "vertices": analysis["vertices"],
                },
            }) + "\n")
    except Exception as e:
        print(f"  [Dataset] save failed: {e}")


def _decode(b64: str):
    """
    Returns (bgr_uint8, gray_uint8) composited onto a WHITE background.
    Handles GRAY / BGR / BGRA / RGBA source images.
    Returns (None, None) on failure.
    """
    try:
        raw_b64 = b64.split(",")[1] if "," in b64 else b64
        arr     = np.frombuffer(base64.b64decode(raw_b64), np.uint8)
        img     = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
        if img is None:
            return None, None

        if img.ndim == 2:                          # grayscale
            bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif img.shape[2] == 4:                    # RGBA / BGRA
            alpha = img[:, :, 3:].astype(np.float32) / 255.0
            rgb   = img[:, :, :3].astype(np.float32)
            # composite onto white
            white = np.full_like(rgb, 255.0)
            comp  = (rgb * alpha + white * (1.0 - alpha)).astype(np.uint8)
            bgr   = cv2.cvtColor(comp, cv2.COLOR_RGB2BGR) \
                    if img.shape[2] == 4 and _is_rgb_order(img) else comp
        else:                                       # BGR (standard)
            bgr = img

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        return bgr, gray

    except Exception:
        return None, None


def _is_rgb_order(img: np.ndarray) -> bool:
    """Heuristic: if decoded with IMREAD_UNCHANGED, OpenCV gives BGRA for PNG."""
    return False   # OpenCV always returns BGRA for 4-channel PNGs


# ─────────────────────────────────────────────────────────────────────────────
# Background estimation
# ─────────────────────────────────────────────────────────────────────────────

def _sample_background(bgr: np.ndarray, sample_radius: int = 8) -> np.ndarray:
    """
    Sample corner + edge pixels to estimate background color.
    Returns mean BGR as float32 array shape (3,).
    """
    h, w = bgr.shape[:2]
    r    = min(sample_radius, h // 4, w // 4)
    corners = [
        bgr[:r,  :r ],
        bgr[:r,  w-r:],
        bgr[h-r:, :r ],
        bgr[h-r:, w-r:],
    ]
    samples = np.concatenate([c.reshape(-1, 3) for c in corners], axis=0)
    return samples.mean(axis=0)   # (B, G, R) float


def _foreground_mask(bgr: np.ndarray, bg_color: np.ndarray,
                     thresh: float = 30.0) -> np.ndarray:
    """
    Pixels whose L2 distance from bg_color exceeds thresh become foreground (255).
    Works regardless of whether background is white, black, gray, or colored.
    """
    diff = bgr.astype(np.float32) - bg_color.astype(np.float32)
    dist = np.linalg.norm(diff, axis=2)              # (H, W) float
    mask = (dist > thresh).astype(np.uint8) * 255
    return mask


# ─────────────────────────────────────────────────────────────────────────────
# Contour extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_shape_contour(bgr: np.ndarray, gray: np.ndarray):
    """
    Returns the best contour representing the foreground shape.
    Strategy:
      1. Try background-subtraction mask (best for solid shapes on uniform bg).
      2. Fall back to Canny edges if background is noisy / textured.
    """
    h, w = gray.shape
    img_area = float(h * w)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    def _best_from_binary(binary: np.ndarray):
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
        cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # reject full-image boundary and tiny noise
        valid = [c for c in cnts
                 if img_area * 0.003 < cv2.contourArea(c) < img_area * 0.90]
        if not valid:
            return None, 0.0
        cnt  = max(valid, key=cv2.contourArea)
        return cnt, cv2.contourArea(cnt)

    results = []

    # ── Strategy 1: background subtraction at multiple thresholds ────────────
    bg = _sample_background(bgr)
    for thresh in (20, 35, 50, 15):
        mask = _foreground_mask(bgr, bg, thresh)
        cnt, area = _best_from_binary(mask)
        if cnt is not None and area > 0:
            results.append((area, cnt))

    # ── Strategy 2: Otsu on grayscale (both polarities) ──────────────────────
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    for flags in (cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
                  cv2.THRESH_BINARY     + cv2.THRESH_OTSU):
        _, b = cv2.threshold(blur, 0, 255, flags)
        cnt, area = _best_from_binary(b)
        if cnt is not None and area > 0:
            results.append((area, cnt))

    # ── Strategy 3: Canny edges ───────────────────────────────────────────────
    edges = cv2.Canny(blur, 30, 100)
    dilated = cv2.dilate(edges, kernel, iterations=3)
    cnt, area = _best_from_binary(dilated)
    if cnt is not None and area > 0:
        results.append((area, cnt))

    if not results:
        return None

    # Return the contour with the largest area
    # (background-subtraction almost always wins if it works)
    results.sort(key=lambda x: x[0], reverse=True)
    return results[0][1]


# ─────────────────────────────────────────────────────────────────────────────
# Shape classification
# ─────────────────────────────────────────────────────────────────────────────

def _classify(cnt: np.ndarray) -> tuple:
    """
    Returns (shape_name: str, vertices: int, circularity: float).
    """
    perimeter   = cv2.arcLength(cnt, True)
    area        = cv2.contourArea(cnt)
    circularity = (4 * np.pi * area / (perimeter ** 2)) if perimeter > 0 else 0.0

    # Try a range of epsilon values and vote on the most common vertex count
    vertex_votes = {}
    for frac in (0.01, 0.015, 0.02, 0.03, 0.04, 0.05):
        approx = cv2.approxPolyDP(cnt, frac * perimeter, True)
        v = len(approx)
        vertex_votes[v] = vertex_votes.get(v, 0) + 1

    # Pick vertex count with the most votes; break ties by preferring lower count
    vertices = max(vertex_votes, key=lambda v: (vertex_votes[v], -v))

    if   vertices == 3:
        shape = "triangle"
    elif vertices == 4:
        x, y, bw, bh = cv2.boundingRect(cnt)
        ar = float(bw) / bh if bh else 1.0
        shape = "square" if 0.78 <= ar <= 1.28 else "rectangle"
    elif vertices == 5:
        shape = "pentagon"
    elif vertices == 6:
        shape = "hexagon"
    elif vertices == 7:
        shape = "heptagon"
    elif vertices >= 8:
        shape = "circle" if circularity >= 0.72 else "circle-ish"
    else:
        shape = "circle" if circularity >= 0.72 else f"unknown-{vertices}"

    # High-circularity override (anti-aliased circles often get 5-7 vertices)
    if circularity >= 0.88 and shape not in ("circle", "circle-ish"):
        shape = "circle"

    return shape, vertices, circularity


# ─────────────────────────────────────────────────────────────────────────────
# Dominant color
# ─────────────────────────────────────────────────────────────────────────────

def _dominant_color(bgr: np.ndarray, mask: np.ndarray = None) -> str:
    """
    Returns the dominant named color.
    If mask is provided (uint8, 255=foreground), only those pixels are analysed.
    """
    if bgr is None:
        return "unknown"
    hsv  = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    best, best_n = "unknown", 0
    for name, ranges in COLOR_RANGES.items():
        m = None
        for lo, hi in ranges:
            hit = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
            m   = hit if m is None else cv2.bitwise_or(m, hit)
        if mask is not None:
            m = cv2.bitwise_and(m, mask)
        n = int(np.count_nonzero(m))
        if n > best_n:
            best_n, best = n, name
    return best


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def analyze_shape(b64_string: str) -> dict:
    """
    Decode image → detect foreground shape → classify → return metadata dict.

    Returns:
        {
          area, hull_area, bbox_area,  # float, pixels²
          type,                         # str  e.g. "hexagon"
          vertices,                     # int
          circularity,                  # float 0-1
          color,                        # str  e.g. "green"
        }
    """
    EMPTY = dict(area=0.0, hull_area=0.0, bbox_area=0.0,
                 type="unknown", vertices=0, circularity=0.0, color="unknown")

    try:
        bgr, gray = _decode(b64_string)
        if bgr is None:
            return EMPTY

        cnt = _extract_shape_contour(bgr, gray)
        if cnt is None:
            return {**EMPTY, "type": "no_contour"}

        area, perimeter = cv2.contourArea(cnt), cv2.arcLength(cnt, True)
        if area < 10:
            return EMPTY

        shape, vertices, circularity = _classify(cnt)

        hull      = cv2.convexHull(cnt)
        hull_area = float(cv2.contourArea(hull))

        x, y, bw, bh = cv2.boundingRect(cnt)
        bbox_area    = float(bw * bh)

        # Build a foreground mask scoped to the bounding rect for color detection
        fmask = np.zeros(gray.shape, np.uint8)
        cv2.drawContours(fmask, [cnt], -1, 255, -1)  # filled shape silhouette

        color = _dominant_color(bgr, fmask)

        return dict(
            area        = float(area),
            hull_area   = hull_area,
            bbox_area   = bbox_area,
            type        = shape,
            vertices    = vertices,
            circularity = float(circularity),
            color       = color,
        )

    except Exception as e:
        return {**EMPTY, "type": "error", "error": str(e)}


if __name__ == "__main__":
    pass