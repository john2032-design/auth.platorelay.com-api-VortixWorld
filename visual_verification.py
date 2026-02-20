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

def save_to_dataset(b64_string, analysis, instruction=""):
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

def _decode(b64):
    try:
        raw_b64 = b64.split(",")[1] if "," in b64 else b64
        arr = np.frombuffer(base64.b64decode(raw_b64), np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
        if img is None:
            return None, None
        if img.ndim == 2:
            bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif img.shape[2] == 4:
            alpha = img[:, :, 3:].astype(np.float32) / 255.0
            rgb = img[:, :, :3].astype(np.float32)
            white = np.full_like(rgb, 255.0)
            comp = (rgb * alpha + white * (1.0 - alpha)).astype(np.uint8)
            bgr = cv2.cvtColor(comp, cv2.COLOR_RGB2BGR)
        else:
            bgr = img
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        return bgr, gray
    except Exception:
        return None, None

def _sample_background(bgr, sample_radius=8):
    h, w = bgr.shape[:2]
    r = min(sample_radius, h//4, w//4)
    corners = [
        bgr[:r, :r],
        bgr[:r, w-r:],
        bgr[h-r:, :r],
        bgr[h-r:, w-r:],
    ]
    samples = np.concatenate([c.reshape(-1, 3) for c in corners], axis=0)
    return samples.mean(axis=0)

def _foreground_mask(bgr, bg_color, thresh=30.0):
    diff = bgr.astype(np.float32) - bg_color.astype(np.float32)
    dist = np.linalg.norm(diff, axis=2)
    mask = (dist > thresh).astype(np.uint8) * 255
    return mask

def _extract_shape_contour(bgr, gray):
    h, w = gray.shape
    img_area = float(h * w)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    def _best_from_binary(binary):
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
        cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid = [c for c in cnts if img_area * 0.003 < cv2.contourArea(c) < img_area * 0.90]
        if not valid:
            return None, 0.0
        cnt = max(valid, key=cv2.contourArea)
        return cnt, cv2.contourArea(cnt)
    results = []
    bg = _sample_background(bgr)
    for thresh in (20, 35, 50, 15):
        mask = _foreground_mask(bgr, bg, thresh)
        cnt, area = _best_from_binary(mask)
        if cnt is not None and area > 0:
            results.append((area, cnt))
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    for flags in (cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU, cv2.THRESH_BINARY + cv2.THRESH_OTSU):
        _, b = cv2.threshold(blur, 0, 255, flags)
        cnt, area = _best_from_binary(b)
        if cnt is not None and area > 0:
            results.append((area, cnt))
    edges = cv2.Canny(blur, 30, 100)
    dilated = cv2.dilate(edges, kernel, iterations=3)
    cnt, area = _best_from_binary(dilated)
    if cnt is not None and area > 0:
        results.append((area, cnt))
    if not results:
        return None
    results.sort(key=lambda x: x[0], reverse=True)
    return results[0][1]

def _classify(cnt):
    perimeter = cv2.arcLength(cnt, True)
    area = cv2.contourArea(cnt)
    circularity = (4 * np.pi * area / (perimeter ** 2)) if perimeter > 0 else 0.0
    vertex_votes = {}
    for frac in (0.01, 0.015, 0.02, 0.03, 0.04, 0.05):
        approx = cv2.approxPolyDP(cnt, frac * perimeter, True)
        v = len(approx)
        vertex_votes[v] = vertex_votes.get(v, 0) + 1
    vertices = max(vertex_votes, key=lambda v: (vertex_votes[v], -v))
    if vertices == 3:
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
    if circularity >= 0.88 and shape not in ("circle", "circle-ish"):
        shape = "circle"
    return shape, vertices, circularity

def _dominant_color(bgr, mask=None):
    if bgr is None:
        return "unknown"
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    best, best_n = "unknown", 0
    for name, ranges in COLOR_RANGES.items():
        m = None
        for lo, hi in ranges:
            hit = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
            m = hit if m is None else cv2.bitwise_or(m, hit)
        if mask is not None:
            m = cv2.bitwise_and(m, mask)
        n = int(np.count_nonzero(m))
        if n > best_n:
            best_n, best = n, name
    return best

def analyze_shape(b64_string):
    EMPTY = dict(area=0.0, hull_area=0.0, bbox_area=0.0, type="unknown", vertices=0, circularity=0.0, color="unknown")
    try:
        bgr, gray = _decode(b64_string)
        if bgr is None:
            return EMPTY
        cnt = _extract_shape_contour(bgr, gray)
        if cnt is None:
            return {**EMPTY, "type": "no_contour"}
        area = cv2.contourArea(cnt)
        if area < 10:
            return EMPTY
        shape, vertices, circularity = _classify(cnt)
        hull = cv2.convexHull(cnt)
        hull_area = float(cv2.contourArea(hull))
        x, y, bw, bh = cv2.boundingRect(cnt)
        bbox_area = float(bw * bh)
        fmask = np.zeros(gray.shape, np.uint8)
        cv2.drawContours(fmask, [cnt], -1, 255, -1)
        color = _dominant_color(bgr, fmask)
        return dict(area=float(area), hull_area=hull_area, bbox_area=bbox_area, type=shape, vertices=vertices, circularity=float(circularity), color=color)
    except Exception as e:
        return {**EMPTY, "type": "error", "error": str(e)}