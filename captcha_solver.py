# captcha_solver.py - Adapted from pow_client.py for browser use (parse and solve logic)
import visual_verification

SHAPE_KEYWORDS = ["circle", "square", "triangle", "rectangle",
                  "hexagon", "pentagon", "heptagon", "polygon"]
COLOR_KEYWORDS = ["red", "orange", "yellow", "green", "blue",
                  "purple", "white", "black", "gray"]
_POLY_ORDER    = ["triangle", "square", "rectangle", "pentagon", "hexagon", "heptagon"]

def _parse_instruction(instruction: str):
    instr        = instruction.lower()
    target_type  = next((k for k in SHAPE_KEYWORDS if k in instr), None)
    target_color = next((k for k in COLOR_KEYWORDS if k in instr), None)
    want_smallest = any(w in instr for w in ("smallest", "tiny", "minimum"))
    want_largest  = any(w in instr for w in ("largest", "biggest", "maximum"))
    if not want_smallest and not want_largest:
        want_largest = True
    return target_type, target_color, want_smallest, want_largest

def _json_area(s: dict):
    for k in ("area", "size"):
        v = s.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    w, h = s.get("width"), s.get("height")
    if isinstance(w, (int, float)) and isinstance(h, (int, float)):
        return float(w) * float(h)
    r = s.get("radius")
    if isinstance(r, (int, float)):
        return 3.14159 * r ** 2
    return 0.0

def _is_ambiguous(t: str) -> bool:
    return not t or t in ("unknown", "error", "no_contour") or t.startswith("unknown-")

def _type_matches_strict(detected: str, target: str) -> bool:
    if _is_ambiguous(detected):
        return False
    if target == "circle":
        return "circle" in detected
    if target in detected:
        return True
    try:
        return abs(_POLY_ORDER.index(target) - _POLY_ORDER.index(detected)) <= 1
    except ValueError:
        return False

def _type_confidence(detected: str, target: str) -> float:
    if not target:
        return 1.0
    if _is_ambiguous(detected):
        return 0.0
    if target == "circle" and "circle" in detected:
        return 1.0
    if target != "circle" and target in detected:
        return 1.0
    try:
        if abs(_POLY_ORDER.index(target) - _POLY_ORDER.index(detected)) == 1:
            return 0.7
    except ValueError:
        pass
    return 0.0

def solve_stage(stage: dict, stage_idx: int) -> str:
    instruction = stage.get("instruction") or ""
    shapes = stage.get("shapes") or []

    target_type, target_color, want_smallest, _ = _parse_instruction(instruction)
    want_largest = not want_smallest

    if not shapes:
        return "0"

    for idx, s in enumerate(shapes):
        b64 = s.get("img")
        if not b64:
            s["visual"] = dict(area=0.0, type="unknown", vertices=0, circularity=0.0, color="unknown", hull_area=0.0)
            continue

        vis = visual_verification.analyze_shape(b64)
        s["visual"] = vis

    # Filter
    if target_type:
        candidates = [s for s in shapes if _type_matches_strict(s.get("visual", {}).get("type", ""), target_type)]
    else:
        candidates = list(shapes)

    if target_color and candidates:
        cc = [s for s in candidates if s.get("visual", {}).get("color", "unknown") == target_color]
        if cc:
            candidates = cc

    if not candidates:
        candidates = list(shapes)

    def sort_key(s):
        vis = s.get("visual", {})
        area = vis.get("area", _json_area(s))
        conf = _type_confidence(vis.get("type", ""), target_type)
        return (area, -conf) if want_smallest else (-area, -conf)

    candidates.sort(key=sort_key)
    chosen = candidates[0]
    chosen_idx = shapes.index(chosen)

    return str(chosen_idx)