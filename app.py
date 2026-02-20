# app.py (directory: root)
from flask import Flask, request, jsonify
import time
import urllib.parse
import re
from urllib.parse import urlparse
import random
import math
import os
import json
import urllib.request
import http.cookiejar
import requests
from bs4 import BeautifulSoup
import base64
import numpy as np
import cv2

app = Flask(__name__)

def get_current_time():
    return time.perf_counter_ns()

def format_duration(start_ns, end_ns = time.perf_counter_ns()):
    duration_ns = end_ns - start_ns
    duration_sec = duration_ns / 1_000_000_000
    return f"{duration_sec:.2f}s"

CONFIG = {
  'SUPPORTED_METHODS': ['GET', 'POST'],
  'RATE_LIMIT_WINDOW_MS': 60000,
  'MAX_REQUESTS_PER_WINDOW': 15
}

HOST_RULES = {
  'lootlabs.gg': ['abysm'],
  'loot-link.com': ['abysm'],
  'lootdest.org': ['abysm'],
  'linkvertise.com': ['abysm']
}

USER_RATE_LIMIT = {}

def extract_hostname(url):
  try:
    parsed = urlparse(url if url.startswith('http') else 'https://' + url)
    return parsed.hostname.lower().replace('www.', '')
  except:
    return ''

def sanitize_url(url):
  if not isinstance(url, str):
    return url
  return url.strip().replace('\r', '').replace('\n', '').replace('\t', '')

def get_user_id(req):
  if req.method == 'POST':
    data = req.json
    return data.get('x_user_id') or data.get('x-user-id') or data.get('xUserId') or ''
  headers = req.headers
  return headers.get('x-user-id') or headers.get('x_user_id') or headers.get('x-userid') or ''

def send_error(res, status_code, message, start_time):
  return jsonify({
    'status': 'error',
    'result': message,
    'time_taken': format_duration(start_time)
  }), status_code

def send_success(res, result, user_id, start_time):
  return jsonify({
    'status': 'success',
    'result': result,
    'x_user_id': user_id or '',
    'time_taken': format_duration(start_time)
  })

def try_abysm(session, url):
  try:
    res = session.get('https://api.abysm.lat/v2/bypass', params={'url': url}, headers={'x-api-key': 'ABYSM-185EF369-E519-4670-969E-137F07BB52B8'})
    d = res.json()
    if d.get('status') == 'success' and d.get('data', {}).get('result'):
      return {'success': True, 'result': d['data']['result']}
    if d.get('result'):
      return {'success': True, 'result': d['result']}
    error_msg = d.get('error') or d.get('message') or None
    if error_msg and ('error' in error_msg or 'fail' in error_msg or 'failed' in error_msg):
      error_msg = 'Bypass Failed'
    return {'success': False, 'error': error_msg}
  except Exception as e:
    error_msg = str(e)
    if 'error' in error_msg or 'fail' in error_msg or 'failed' in error_msg:
      error_msg = 'Bypass Failed'
    return {'success': False, 'error': error_msg}

API_REGISTRY = {
  'abysm': try_abysm
}

def get_api_chain(hostname):
  for host, apis in HOST_RULES.items():
    if hostname == host or hostname.endswith('.' + host):
      return apis.copy()
  return []

def execute_api_chain(session, url, api_names):
  last_error = None
  for name in api_names:
    fn = API_REGISTRY.get(name)
    if not fn:
      continue
    result = fn(session, url)
    if result['success']:
      return {'success': True, 'result': result['result']}
    else:
      last_error = result.get('error') or result.get('message') or result.get('result') or last_error or 'Unknown error from upstream API'
  return {'success': False, 'error': last_error}

def set_cors_headers(res):
  allowed_origins = os.environ.get('ALLOWED_ORIGINS', '*').split(',')
  origin = request.headers.get('Origin')
  if '*' in allowed_origins:
    res.headers['Access-Control-Allow-Origin'] = '*'
  elif origin and origin in allowed_origins:
    res.headers['Access-Control-Allow-Origin'] = origin
    res.headers['Access-Control-Allow-Credentials'] = 'true'
  res.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
  res.headers['Access-Control-Allow-Headers'] = 'Content-Type,x-user-id,x_user_id,x-userid,x-api-key'
  return res

def analyze_shape(b64_string):
  EMPTY = {'area': 0.0, 'hull_area': 0.0, 'bbox_area': 0.0,
           'type': "unknown", 'vertices': 0, 'circularity': 0.0, 'color': "unknown"}
  try:
    raw_b64 = b64_string.split(",")[1] if "," in b64_string else b64_string
    arr = np.frombuffer(base64.b64decode(raw_b64), np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    if img is None:
      return EMPTY
    if img.ndim == 2:
      bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:
      alpha = img[:, :, 3:].astype(np.float32) / 255.0
      rgb = img[:, :, :3].astype(np.float32)
      white = np.full_like(rgb, 255.0)
      comp = (rgb * alpha + white * (1.0 - alpha)).astype(np.uint8)
      bgr = cv2.cvtColor(comp, cv2.COLOR_RGB2BGR) if img.shape[2] == 4 else comp
    else:
      bgr = img
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    cnt = _extract_shape_contour(bgr, gray)
    if cnt is None:
      return {**EMPTY, "type": "no_contour"}
    area, perimeter = cv2.contourArea(cnt), cv2.arcLength(cnt, True)
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
    return {
      'area': float(area),
      'hull_area': hull_area,
      'bbox_area': bbox_area,
      'type': shape,
      'vertices': vertices,
      'circularity': float(circularity),
      'color': color,
    }
  except Exception as e:
    return {**EMPTY, "type": "error", "error": str(e)}

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

def _dominant_color(bgr, mask = None):
  if (bgr is None):
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

def _parse_instruction(instruction):
  instr = instruction.lower()
  target_type = next((k for k in SHAPE_KEYWORDS if k in instr), None)
  target_color = next((k for k in COLOR_KEYWORDS if k in instr), None)
  want_smallest = any(w in instr for w in ("smallest", "tiny", "minimum"))
  want_largest = any(w in instr for w in ("largest", "biggest", "maximum"))
  if not want_smallest and not want_largest:
    want_largest = True
  return target_type, target_color, want_smallest, want_largest

def _json_area(s):
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

def _is_ambiguous(t):
  return not t or t in ("unknown", "error", "no_contour") or t.startswith("unknown-")

def _type_matches_strict(detected, target):
  if _is_ambiguous(detected):
    return False
  if target == "circle":
    return "circle" in detected
  if target in detected:
    return True
  try:
    return abs(POLY_ORDER.index(target) - POLY_ORDER.index(detected)) <= 1
  except ValueError:
    return False

def _type_confidence(detected, target):
  if not target:
    return 1.0
  if _is_ambiguous(detected):
    return 0.0
  if target == "circle" and "circle" in detected:
    return 1.0
  if target != "circle" and target in detected:
    return 1.0
  try:
    if abs(POLY_ORDER.index(target) - POLY_ORDER.index(detected)) == 1:
      return 0.7
  except ValueError:
    pass
  return 0.0

async function solve_stage(stage) {
  const instruction = stage.instruction || "";
  const shapes = stage.shapes || [];
  const [targetType, targetColor, wantSmallest, wantLargest] = _parse_instruction(instruction);
  if (shapes.length === 0) return "0";
  for (let i = 0; i < shapes.length; i++) {
    const s = shapes[i];
    const b64 = s.img;
    if (!b64) {
      s.visual = { area: 0.0, type: "unknown", vertices: 0, circularity: 0.0, color: "unknown" };
      continue;
    }
    s.visual = analyze_shape(b64);
  }
  let candidates = shapes.filter(s => _type_matches_strict(s.visual.type || "", targetType || ""));
  if (candidates.length === 0) candidates = shapes;
  if (targetColor) {
    const cc = candidates.filter(s => (s.visual.color || "unknown") === targetColor || s.visual.color === "unknown");
    if (cc.length > 0) candidates = cc;
  }
  candidates.sort((a, b) => {
    const areaA = _json_area(a.visual);
    const areaB = _json_area(b.visual);
    const confA = _type_confidence(a.visual.type || "", targetType || "");
    const confB = _type_confidence(b.visual.type || "", targetType || "");
    if (wantSmallest) {
      if (areaA !== areaB) return areaA - areaB;
      return confB - confA;
    } else {
      if (areaA !== areaB) return areaB - areaA;
      return confB - confA;
    }
  });
  const chosen = candidates[0];
  return shapes.indexOf(chosen).toString();
}

const REQUEST_URL = 'https://sentry.platorelay.com/.gs/pow/captcha/request';
const VERIFY_URL = 'https://sentry.platorelay.com/.gs/pow/captcha/verify';

const BASE_HEADERS = {
  'Accept': '*/*',
  'Accept-Encoding': 'gzip, deflate, br, zstd',
  'Accept-Language': 'en-US,en;q=0.9',
  'Connection': 'keep-alive',
  'Content-Type': 'application/json',
  'Host': 'sentry.platorelay.com',
  'Origin': 'https://sentry.platorelay.com',
  'sec-ch-ua': '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
  'sec-ch-ua-mobile': '?0',
  'sec-ch-ua-platform': '"Windows"',
  'Sec-Fetch-Dest': 'empty',
  'Sec-Fetch-Mode': 'cors',
  'Sec-Fetch-Site': 'same-origin',
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
};

async function handlePlatorelay(axios, url, handlerStart, res, incomingUserId) {
  let response;
  try {
    response = await axios.get(url, { headers: { Accept: 'text/html' }, responseType: 'text' });
  } catch (e) {
    return sendError(res, 500, `Failed to fetch initial page: ${e.message}`, handlerStart);
  }
  const $ = cheerio.load(response.data);
  const title = $('h3.font-semibold.tracking-tight.text-2xl.text-center').text().trim();
  let isAndroid = title === 'Delta Android Keysystem';
  let isIos = title === 'Delta iOS Keysystem';
  await new Promise(r => setTimeout(r, 5000));
  let sentryUrl = 'https://sentry.platorelay.com/a?d=' + encodeURIComponent(new URL(url).searchParams.get('d') || '');
  let d = new URL(sentryUrl).searchParams.get('d') || '';
  const referer = `https://sentry.platorelay.com/a?d=${d}`;
  const headers = { ...BASE_HEADERS, Referer: referer };
  const reqPl = { telemetry: {}, deviceFingerprint: '', forcePuzzle: false };
  try {
    response = await axios.post(REQUEST_URL, reqPl, { headers });
  } catch (e) {
    return sendError(res, 500, `Captcha request failed: ${e.message}`, handlerStart);
  }
  const parsed = response.data;
  if (!parsed.success) {
    return sendError(res, 500, parsed.error || 'Captcha request failed', handlerStart);
  }
  const data = parsed.data;
  const puzzleId = data.id;
  if (!puzzleId) {
    return sendError(res, 500, 'No puzzle ID', handlerStart);
  }
  let stages = data.stages || (data.puzzle ? [data.puzzle] : []);
  if (stages.length === 0) {
    return sendError(res, 500, 'No stages', handlerStart);
  }
  const answers = [];
  for (let i = 0; i < stages.length; i++) {
    answers.push(await solve_stage(stages[i]));
  }
  const { path, telemetry, fingerprint } = genVerifyMeta(stages.length);
  const verPl = { id: puzzleId, answers, path, telemetry, deviceFingerprint: fingerprint };
  await new Promise(r => setTimeout(r, 3000));
  let verResponse;
  try {
    verResponse = await axios.post(VERIFY_URL, verPl, { headers });
  } catch (e) {
    return sendError(res, 500, `Captcha verify failed: ${e.message}`, handlerStart);
  }
  const pv = verResponse.data;
  if (!pv.success) {
    return sendError(res, 500, pv.error || 'Captcha verify failed', handlerStart);
  }
  let nextUrl = pv.data?.result || pv.result || pv.token;
  if (!nextUrl || !nextUrl.startsWith('https://')) {
    return sendError(res, 500, 'No next URL after captcha', handlerStart);
  }
  let hostname = extractHostname(nextUrl);
  let apiChain = getApiChain(hostname);
  if (apiChain.length > 0) {
    const bypassResult = await executeApiChain(axios, nextUrl, apiChain);
    if (!bypassResult.success) {
      return sendError(res, 500, bypassResult.error || 'Bypass failed', handlerStart);
    }
    nextUrl = bypassResult.result;
  }
  if (isIos) {
    hostname = extractHostname(nextUrl);
    apiChain = getApiChain(hostname);
    if (apiChain.length > 0) {
      const bypassResult = await executeApiChain(axios, nextUrl, apiChain);
      if (!bypassResult.success) {
        return sendError(res, 500, bypassResult.error || 'Second bypass failed', handlerStart);
      }
      nextUrl = bypassResult.result;
    }
  }
  try {
    response = await axios.get(nextUrl, { headers: { Accept: 'text/html' }, responseType: 'text' });
  } catch (e) {
    return sendError(res, 500, `Failed to fetch final page: ${e.message}`, handlerStart);
  }
  const finalHtml = response.data;
  await new Promise(r => setTimeout(r, 5000));
  const $final = cheerio.load(finalHtml);
  const keyText = $final('div#keyText').text().trim();
  if (!keyText.startsWith('FREE_')) {
    return sendError(res, 500, 'Invalid key format', handlerStart);
  }
  return sendSuccess(res, keyText, incomingUserId, handlerStart);
}

module.exports = async (req, res) => {
  const handlerStart = getCurrentTime();
  setCorsHeaders(req, res);
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (!CONFIG.SUPPORTED_METHODS.includes(req.method)) {
    return sendError(res, 405, 'Method not allowed', handlerStart);
  }
  let url = req.method === 'GET' ? req.query.url : req.body?.url;
  if (!url || typeof url !== 'string') {
    return sendError(res, 400, 'Missing URL parameter', handlerStart);
  }
  url = sanitize_url(url);
  if (!/^https?:\/\//i.test(url)) {
    return sendError(res, 400, 'URL must start with http:// or https://', handlerStart);
  }
  if (!axiosInstance) {
    const jar = new CookieJar();
    axiosInstance = wrapper(axios.create({
      timeout: 90000,
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36' },
      jar
    }));
  }
  const axios = axiosInstance;
  const hostname = extractHostname(url);
  if (!hostname) {
    return sendError(res, 400, 'Invalid URL', handlerStart);
  }
  if (hostname !== 'auth.platorelay.com') {
    return sendError(res, 400, 'This API only supports auth.platorelay.com URLs', handlerStart);
  }
  const incomingUserId = getUserId(req);
  const userKey = incomingUserId || req.headers['x-forwarded-for'] || req.ip || 'anonymous';
  const now = Date.now();
  if (!(userKey in USER_RATE_LIMIT)) USER_RATE_LIMIT[userKey] = [];
  let times = USER_RATE_LIMIT[userKey];
  times = times.filter(t => now - t < CONFIG.RATE_LIMIT_WINDOW_MS);
  times.push(now);
  USER_RATE_LIMIT[userKey] = times;
  if (times.length > CONFIG.MAX_REQUESTS_PER_WINDOW) {
    return sendError(res, 429, 'Rate limit reached', handlerStart);
  }
  return await handlePlatorelay(axios, url, handlerStart, res, incomingUserId);
};