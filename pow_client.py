# pow_client.py (directory: root)
import json
import math
import random
import time
import os
import urllib.request
import http.cookiejar
from typing import Any, Dict, List
from visual_verification import analyze_shape, save_to_dataset

REQUEST_URL = "https://sentry.platorelay.com/.gs/pow/captcha/request"
VERIFY_URL = "https://sentry.platorelay.com/.gs/pow/captcha/verify"

BASE_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Content-Type": "application/json",
    "Host": "sentry.platorelay.com",
    "Origin": "https://sentry.platorelay.com",
    "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
}

SHAPE_KEYWORDS = ["circle", "square", "triangle", "rectangle", "hexagon", "pentagon", "heptagon", "polygon"]
COLOR_KEYWORDS = ["red", "orange", "yellow", "green", "blue", "purple", "white", "black", "gray"]
_POLY_ORDER = ["triangle", "square", "rectangle", "pentagon", "hexagon", "heptagon"]

def _gen_fingerprint():
    val = random.randint(-0x7FFFFFFF, 0x7FFFFFFF)
    if val >= 0:
        return f"{val:08x}"
    else:
        return f"-{(-val):08x}"

def _gen_telemetry(dwell_ms: float):
    moves = random.randint(180, 320)
    speed_min = round(random.uniform(0.0005, 0.005), 15)
    speed_max = round(random.uniform(8.0, 16.0), 15)
    speed_median = round(random.uniform(0.15, 0.45), 15)
    speed_avg = round(random.uniform(0.45, 0.95), 15)
    speed_p25 = round(random.uniform(0.05, 0.15), 15)
    speed_p75 = round(random.uniform(0.55, 0.95), 15)
    vel_var = round(random.uniform(1.0, 3.0), 15)
    dir_changes = random.randint(1, 5)
    move_density = round(moves / (dwell_ms / 1000.0), 4)
    return {
        "dwellMs": round(dwell_ms, 1),
        "moves": moves,
        "velocityVar": vel_var,
        "velocityMedian": speed_median,
        "velocityAvg": speed_avg,
        "velocityMin": speed_min,
        "velocityMax": speed_max,
        "velocityP25": speed_p25,
        "velocityP75": speed_p75,
        "directionChanges": dir_changes,
        "keypresses": 0,
        "speedSamples": moves,
        "moveDensity": move_density,
    }

def _gen_path(dwell_ms: float):
    click_ts = round(dwell_ms + random.uniform(-200, 50), 1)
    total_dist = round(random.uniform(80, 400), 1)
    duration_ms = round(random.uniform(40, 120), 1)
    moves = random.randint(1, 4)
    avg_speed = round(total_dist / duration_ms, 4) if duration_ms > 0 else 0
    return {
        "moves": moves,
        "totalDist": total_dist,
        "durationMs": duration_ms,
        "avgSpeed": avg_speed,
        "clickTimestamp": click_ts,
        "timeToFirstClick": click_ts,
    }

def _gen_verify_meta(num_stages: int):
    base_dwell = random.uniform(10000, 20000)
    extra_dwell = (num_stages - 1) * random.uniform(5000, 10000)
    dwell_ms = base_dwell + extra_dwell
    path = _gen_path(dwell_ms)
    telemetry = _gen_telemetry(dwell_ms)
    fingerprint = _gen_fingerprint()
    return path, telemetry, fingerprint

def load_json(path: str, fallback: dict):
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return fallback

def send(opener, url: str, payload: dict, headers: dict):
    body = json.dumps(payload, separators=(",", ":")).encode()
    h = {**headers, "Content-Length": str(len(body))}
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with opener.open(req, timeout=30) as resp:
        raw = resp.read()
        try:
            p = json.loads(raw)
            return resp.status, resp.reason, json.dumps(p, indent=2), p
        except Exception:
            return resp.status, resp.reason, raw.decode("utf-8", errors="replace"), None

def _scrub(obj):
  if isinstance(obj, dict):
    return {k: ("<base64>" if isinstance(v, str) and len(v) > 100 and k == "img"
                else _scrub(v)) for k, v in obj.items()}
  if isinstance(obj, list):
    return [_scrub(i) for i in obj]
  return obj

def _parse_instruction(instruction: str):
  instr = instruction.lower()
  target_type = next((k for k in SHAPE_KEYWORDS if k in instr), None)
  target_color = next((k for k in COLOR_KEYWORDS if k in instr), None)
  want_smallest = any(w in instr for w in ("smallest", "tiny", "minimum"))
  want_largest = any(w in instr for w in ("largest", "biggest", "maximum"))
  if not want_smallest and not want_largest:
    want_largest = True
  return target_type, target_color, want_smallest, want_largest

def _json_area(s: Dict[str, Any]) -> float:
  for k in ("area", "size"):
    v = s.get(k)
    if isinstance(v, (int, float)):
      return float(v)
  w, h = s.get("width"), s.get("height")
  if isinstance(w, (int, float)) and isinstance(h, (int, float)):
    return float(w) * float(h)
  r = s.get("radius")
  if isinstance(r, (int, float)):
    return math.pi * r ** 2
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

def solve_stage(stage: Dict[str, Any], stage_idx: int) -> str:
    instruction = stage.get("instruction") or ""
    shapes: List[Dict[str, Any]] = stage.get("shapes") or []

    target_type, target_color, want_smallest, want_largest = _parse_instruction(instruction)

    print(f"\n  [Stage {stage_idx}] \"{instruction}\"")
    print(f"  target_type={target_type!r}  target_color={target_color!r}  "
          f"shapes={len(shapes)}  want_smallest={want_smallest}")

    if not shapes:
        print("  WARNING: no shapes"); return "0"

    os.makedirs("debug_captchas", exist_ok=True)

    for idx, s in enumerate(shapes):
        b64 = s.get("img")
        if not b64:
            s["visual"] = dict(area=0.0, type="unknown", vertices=0,
                               circularity=0.0, color="unknown", hull_area=0.0)
            continue

        vis = analyze_shape(b64)
        s["visual"] = vis

        if os.environ.get("COLLECT_DATASET"):
            save_to_dataset(b64, vis, instruction)

        try:
            raw = b64.split(",")[1] if "," in b64 else b64
            with open(f"debug_captchas/s{stage_idx}_i{idx}_{vis['type']}.png", "wb") as f:
                f.write(base64.b64decode(raw))
        except Exception:
            pass

        passes = _type_matches_strict(vis['type'], target_type) if target_type else True
        print(f"    [{idx}] {vis['type']:<12} {vis.get('color','?'):<8} "
              f"area={vis['area']:>7.0f}  hull={vis.get('hull_area',0):>7.0f}  "
              f"v={vis['vertices']}  c={vis.get('circularity',0):.2f}  "
              f"{'✓' if passes else '✗'}")

    if target_type:
        candidates = [s for s in shapes
                      if _type_matches_strict(s.get("visual", {}).get("type", ""), target_type)]
    else:
        candidates = list(shapes)

    if target_color:
        cc = [s for s in candidates
              if s.get("visual", {}).get("color", "unknown") in ("unknown", target_color)]
        if cc:
            candidates = cc

    if not candidates:
        candidates = list(shapes)

    print(f"  [Filter] {len(candidates)}/{len(shapes)} candidates")

    def sort_key(s):
        vis  = s.get("visual", {})
        area = vis.get("area", _json_area(s))
        conf = _type_confidence(vis.get("type", ""), target_type)
        return (area, conf) if want_smallest else (-area, conf)

    candidates.sort(key=sort_key, reverse=want_largest)
    chosen = candidates[0]
    return str(shapes.index(chosen))

def handle_platorelay(url, incoming_user_id):
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    try:
        req = urllib.request.Request(url, headers={"Accept": "text/html"})
        response = opener.open(req)
        html = response.read().decode("utf-8")
    except Exception as e:
        return {"status": "error", "result": f"Failed to fetch initial page: {str(e)}", "time_taken": "0.00s"}
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("h3", {"class": "font-semibold tracking-tight text-2xl text-center"})
    title_text = title.text.strip() if title else ""
    is_android = "Android" in title_text
    is_ios = "iOS" in title_text
    time.sleep(5)
    button = soup.find("button", string=re.compile("Continue|Lootlabs", re.I))
    if not button:
        return {"status": "error", "result": "Button not found", "time_taken": "0.00s"}
    d = url.split("d=")[-1].split("&")[0] if "d=" in url else ""
    sentry_url = f"https://sentry.platorelay.com/a?d={urllib.parse.quote(d)}"
    referer = sentry_url
    headers = {**BASE_HEADERS, "Referer": referer}
    req_pl = {"telemetry": {}, "deviceFingerprint": "", "forcePuzzle": False}
    try:
        status, reason, body, parsed = send(opener, REQUEST_URL, req_pl, headers)
    except Exception as e:
        return {"status": "error", "result": f"Captcha request failed: {str(e)}", "time_taken": "0.00s"}
    if not parsed or not parsed.get("success"):
        return {"status": "error", "result": parsed.get("error") or "Captcha request failed", "time_taken": "0.00s"}
    data = parsed.get("data", {})
    puzzle_id = data.get("id")
    if not puzzle_id:
        return {"status": "error", "result": "No puzzle ID", "time_taken": "0.00s"}
    stages = data.get("stages") or ([data.get("puzzle")] if data.get("puzzle") else [])
    if not stages:
        return {"status": "error", "result": "No stages", "time_taken": "0.00s"}
    answers = []
    for i, stage in enumerate(stages):
        answers.append(solve_stage(stage, i))
    path, telemetry, fingerprint = _gen_verify_meta(len(stages))
    ver_pl = {"id": puzzle_id, "answers": answers, "path": path, "telemetry": telemetry, "deviceFingerprint": fingerprint}
    time.sleep(3)
    try:
        status, reason, body, pv = send(opener, VERIFY_URL, ver_pl, headers)
    except Exception as e:
        return {"status": "error", "result": f"Captcha verify failed: {str(e)}", "time_taken": "0.00s"}
    if not pv or not pv.get("success"):
        return {"status": "error", "result": pv.get("error") or "Captcha verify failed", "time_taken": "0.00s"}
    next_url = pv.get("data", {}).get("result") or pv.get("result") or pv.get("token")
    if not next_url or not next_url.startswith("https://"):
        return {"status": "error", "result": "No next URL after captcha", "time_taken": "0.00s"}
    hostname = extract_hostname(next_url)
    api_chain = get_api_chain(hostname)
    if api_chain:
        bypass_result = execute_api_chain(next_url, api_chain)
        if not bypass_result["success"]:
            return {"status": "error", "result": bypass_result["error"] or "Bypass failed", "time_taken": "0.00s"}
        next_url = bypass_result["result"]
    if is_ios:
        hostname = extract_hostname(next_url)
        api_chain = get_api_chain(hostname)
        if api_chain:
            bypass_result = execute_api_chain(next_url, api_chain)
            if not bypass_result["success"]:
                return {"status": "error", "result": bypass_result["error"] or "Second bypass failed", "time_taken": "0.00s"}
            next_url = bypass_result["result"]
    try:
        req = urllib.request.Request(next_url, headers={"Accept": "text/html"})
        response = opener.open(req)
        final_html = response.read().decode("utf-8")
    except Exception as e:
        return {"status": "error", "result": f"Failed to fetch final page: {str(e)}", "time_taken": "0.00s"}
    time.sleep(5)
    soup_final = BeautifulSoup(final_html, "html.parser")
    key_text = soup_final.find("div", id="keyText")
    key = key_text.text.strip() if key_text else ""
    if not key.startswith("FREE_"):
        return {"status": "error", "result": "Invalid key format", "time_taken": "0.00s"}
    return {"status": "success", "result": key, "x_user_id": incoming_user_id or "", "time_taken": "0.00s"}

def get_api_chain(hostname):
  for host, apis in HOST_RULES.items():
    if hostname == host or hostname.endswith('.' + host):
      return apis.copy()
  return []

def execute_api_chain(url, api_names):
  for name in api_names:
    if name == 'abysm':
      result = try_abysm(url)
      if result['success']:
        return result
  return {"success": False, "error": "All bypasses failed"}

def try_abysm(url):
  try:
    res = requests.get('https://api.abysm.lat/v2/bypass', params={'url': url}, headers={'x-api-key': 'ABYSM-185EF369-E519-4670-969E-137F07BB52B8'})
    d = res.json()
    if d.get('status') == 'success' and d.get('data', {}).get('result'):
      return {"success": True, "result": d['data']['result']}
    if d.get('result'):
      return {"success": True, "result": d['result']}
    error_msg = d.get('error') or d.get('message') or None
    if error_msg and any(x in error_msg.lower() for x in ['error', 'fail', 'failed']):
      error_msg = 'Bypass Failed'
    return {"success": False, "error": error_msg}
  except Exception as e:
    error_msg = str(e)
    if any(x in error_msg.lower() for x in ['error', 'fail', 'failed']):
      error_msg = 'Bypass Failed'
    return {"success": False, "error": error_msg}