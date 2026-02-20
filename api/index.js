// api/index.js (directory: api/)
const cheerio = require('cheerio');
const cv = require('@techstark/opencv-js');

cv.onRuntimeInitialized = () => {
  console.log('OpenCV.js is ready');
};

const COLOR_RANGES = {
  red: [[[0, 120, 80], [10, 255, 255]], [[160, 120, 80], [180, 255, 255]]],
  orange: [[[11, 120, 80], [25, 255, 255]]],
  yellow: [[[26, 120, 80], [34, 255, 255]]],
  green: [[[35, 80, 60], [85, 255, 255]]],
  blue: [[[86, 80, 60], [130, 255, 255]]],
  purple: [[[131, 80, 60], [159, 255, 255]]],
  white: [[[0, 0, 190], [180, 40, 255]]],
  black: [[[0, 0, 0], [180, 255, 60]]],
  gray: [[[0, 0, 61], [180, 40, 189]]],
};

const SHAPE_KEYWORDS = ["circle", "square", "triangle", "rectangle", "hexagon", "pentagon", "heptagon", "polygon"];
const COLOR_KEYWORDS = ["red", "orange", "yellow", "green", "blue", "purple", "white", "black", "gray"];
const POLY_ORDER = ["triangle", "square", "rectangle", "pentagon", "hexagon", "heptagon"];

function _decode(b64) {
  try {
    const rawB64 = b64.split(",")[1] || b64;
    const buffer = Buffer.from(rawB64, 'base64');
    let img = cv.imdecode(new Uint8Array(buffer), cv.IMREAD_UNCHANGED);
    let bgr, gray;
    if (img.empty) {
      return null, null;
    }
    if (img.channels() === 1) {
      bgr = new cv.Mat();
      cv.cvtColor(img, bgr, cv.COLOR_GRAY2BGR);
    } else if (img.channels() === 4) {
      bgr = new cv.Mat();
      cv.cvtColor(img, bgr, cv.COLOR_BGRA2BGR);
    } else {
      bgr = img.clone();
    }
    gray = new cv.Mat();
    cv.cvtColor(bgr, gray, cv.COLOR_BGR2GRAY);
    return bgr, gray;
  } catch {
    return null, null;
  }
}

function _sample_background(bgr, sampleRadius = 8) {
  const h = bgr.rows;
  const w = bgr.cols;
  const r = Math.min(sampleRadius, Math.floor(h / 4), Math.floor(w / 4));
  const corners = [
    bgr.roi(new cv.Rect(0, 0, r, r)),
    bgr.roi(new cv.Rect(w - r, 0, r, r)),
    bgr.roi(new cv.Rect(0, h - r, r, r)),
    bgr.roi(new cv.Rect(w - r, h - r, r, r)),
  ];
  let sumB = 0, sumG = 0, sumR = 0, count = 0;
  for (const c of corners) {
    const mean = cv.mean(c);
    const pix = c.rows * c.cols;
    sumB += mean[0] * pix;
    sumG += mean[1] * pix;
    sumR += mean[2] * pix;
    count += pix;
  }
  return new cv.Scalar(sumB / count, sumG / count, sumR / count);
}

function _foreground_mask(bgr, bgColor, thresh = 30.0) {
  const diffF = new cv.Mat();
  bgr.convertTo(diffF, cv.CV_32F);
  const bgF = new cv.Mat(bgr.rows, bgr.cols, cv.CV_32FC3, bgColor);
  const diff = new cv.Mat();
  cv.subtract(diffF, bgF, diff);
  const norm = new cv.Mat();
  cv.norm(diff, norm, cv.NORM_L2, new cv.Mat());
  const mask = new cv.Mat();
  cv.threshold(norm, mask, thresh, 255, cv.THRESH_BINARY);
  return mask;
}

const kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, new cv.Size(3, 3));

function _best_from_binary(binary) {
  const closed = new cv.Mat();
  cv.morphologyEx(binary, closed, cv.MORPH_CLOSE, kernel, new cv.Point(-1, -1), 2);
  const contours = new cv.MatVector();
  const hierarchy = new cv.Mat();
  cv.findContours(closed, contours, hierarchy, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE);
  const imgArea = binary.rows * binary.cols;
  let valid = [];
  for (let i = 0; i < contours.size(); i++) {
    const c = contours.get(i);
    const a = cv.contourArea(c);
    if (imgArea * 0.003 < a && a < imgArea * 0.90) {
      valid.push(c);
    }
  }
  if (valid.length === 0) return null, 0.0;
  let maxA = 0;
  let cnt = null;
  for (const c of valid) {
    const a = cv.contourArea(c);
    if (a > maxA) {
      maxA = a;
      cnt = c;
    }
  }
  return cnt, maxA;
}

function _extract_shape_contour(bgr, gray) {
  const results = [];
  const bg = _sample_background(bgr);
  for (const thresh of [20, 35, 50, 15]) {
    const mask = _foreground_mask(bgr, bg, thresh);
    const [cnt, area] = _best_from_binary(mask);
    if (cnt) results.push({area, cnt});
  }
  const blur = new cv.Mat();
  cv.GaussianBlur(gray, blur, new cv.Size(3, 3), 0, 0, cv.BORDER_DEFAULT);
  for (const flags of [cv.THRESH_BINARY_INV + cv.THRESH_OTSU, cv.THRESH_BINARY + cv.THRESH_OTSU]) {
    const otsu = new cv.Mat();
    cv.threshold(blur, otsu, 0, 255, flags);
    const [cnt, area] = _best_from_binary(otsu);
    if (cnt) results.push({area, cnt});
  }
  const edges = new cv.Mat();
  cv.Canny(blur, edges, 30, 100, 3, false);
  const dilated = new cv.Mat();
  cv.dilate(edges, dilated, kernel, new cv.Point(-1, -1), 3);
  const [cnt, area] = _best_from_binary(dilated);
  if (cnt) results.push({area, cnt});
  if (results.length === 0) return null;
  results.sort((a, b) => b.area - a.area);
  return results[0].cnt;
}

function _classify(cnt) {
  const perimeter = cv.arcLength(cnt, true);
  const area = cv.contourArea(cnt);
  const circularity = perimeter > 0 ? (4 * Math.PI * area) / (perimeter ** 2) : 0.0;
  const vertexVotes = new Map();
  for (const frac of [0.01, 0.015, 0.02, 0.03, 0.04, 0.05]) {
    const approx = new cv.Mat();
    cv.approxPolyDP(cnt, approx, frac * perimeter, true);
    const v = approx.rows;
    vertexVotes.set(v, (vertexVotes.get(v) || 0) + 1);
  }
  let vertices = 0;
  let maxVote = 0;
  for (const [v, count] of vertexVotes) {
    if (count > maxVote || (count === maxVote && v < vertices)) {
      maxVote = count;
      vertices = v;
    }
  }
  let shape;
  if (vertices === 3) {
    shape = "triangle";
  } else if (vertices === 4) {
    const bounding = cnt.boundingRect();
    const ar = bounding.width / bounding.height;
    shape = (0.78 <= ar && ar <= 1.28) ? "square" : "rectangle";
  } else if (vertices === 5) {
    shape = "pentagon";
  } else if (vertices === 6) {
    shape = "hexagon";
  } else if (vertices === 7) {
    shape = "heptagon";
  } else if (vertices >= 8) {
    shape = circularity >= 0.72 ? "circle" : "circle-ish";
  } else {
    shape = circularity >= 0.72 ? "circle" : `unknown-${vertices}`;
  }
  if (circularity >= 0.88 && !shape.includes("circle")) {
    shape = "circle";
  }
  return shape, vertices, circularity;
}

function _dominant_color(bgr, mask = null) {
  const hsv = new cv.Mat();
  cv.cvtColor(bgr, hsv, cv.COLOR_BGR2HSV);
  let best = "unknown";
  let bestN = 0;
  for (const [name, ranges] of Object.entries(COLOR_RANGES)) {
    let m = new cv.Mat(hsv.rows, hsv.cols, cv.CV_8U, new cv.Scalar(0));
    for (const [lo, hi] of ranges) {
      const hit = new cv.Mat();
      cv.inRange(hsv, new cv.Scalar(...lo), new cv.Scalar(...hi), hit);
      cv.or(m, hit, m);
      hit.delete();
    }
    if (mask) {
      cv.and(m, mask, m);
    }
    const n = cv.countNonZero(m);
    if (n > bestN) {
      bestN = n;
      best = name;
    }
    m.delete();
  }
  hsv.delete();
  return best;
}

function analyze_shape(b64String) {
  const EMPTY = { area: 0.0, hullArea: 0.0, bboxArea: 0.0, type: 'unknown', vertices: 0, circularity: 0.0, color: 'unknown' };
  try {
    const [bgr, gray] = _decode(b64String);
    if (!bgr) return EMPTY;
    const cnt = _extract_shape_contour(bgr, gray);
    if (!cnt) return { ...EMPTY, "type": "no_contour" };
    const area = cv.contourArea(cnt);
    const perimeter = cv.arcLength(cnt, true);
    if (area < 10) return EMPTY;
    const [shape, vertices, circularity] = _classify(cnt);
    const hull = new cv.Mat();
    cv.convexHull(cnt, hull, false, true);
    const hullArea = cv.contourArea(hull);
    const bounding = cnt.boundingRect();
    const bboxArea = bounding.width * bounding.height;
    const fmask = new cv.Mat(gray.rows, gray.cols, cv.CV_8U, new cv.Scalar(0));
    const contoursVec = new cv.MatVector();
    contoursVec.push_back(cnt);
    cv.drawContours(fmask, contoursVec, -1, new cv.Scalar(255), cv.FILLED);
    const color = _dominant_color(bgr, fmask);
    bgr.delete();
    gray.delete();
    cnt.delete();
    hull.delete();
    fmask.delete();
    contoursVec.delete();
    return { area, hullArea, bboxArea, type: shape, vertices, circularity, color };
  } catch (e) {
    return { ...EMPTY, type: 'error', error: e.toString() };
  }
}

function _parse_instruction(instruction) {
  const instr = instruction.toLowerCase();
  const targetType = SHAPE_KEYWORDS.find(k => instr.includes(k)) || null;
  const targetColor = COLOR_KEYWORDS.find(k => instr.includes(k)) || null;
  const wantSmallest = ['smallest', 'tiny', 'minimum'].some(w => instr.includes(w));
  const wantLargest = ['largest', 'biggest', 'maximum'].some(w => instr.includes(w));
  if (!wantSmallest && !wantLargest) wantLargest = true;
  return targetType, targetColor, wantSmallest, wantLargest;
}

function _json_area(s) {
  let v = s.area || s.size;
  if (typeof v === 'number') return v;
  const w = s.width, h = s.height;
  if (typeof w === 'number' && typeof h === 'number') return w * h;
  const r = s.radius;
  if (typeof r === 'number') return Math.PI * r ** 2;
  return 0.0;
}

function _is_ambiguous(t) {
  return !t || t === "unknown" || t === "error" || t === "no_contour" || t.startsWith("unknown-");
}

function _type_matches_strict(detected, target) {
  if (_is_ambiguous(detected)) return false;
  if (target === "circle") return detected.includes("circle");
  if (detected.includes(target)) return true;
  const i1 = POLY_ORDER.indexOf(target);
  const i2 = POLY_ORDER.indexOf(detected);
  if (i1 === -1 || i2 === -1) return false;
  return Math.abs(i1 - i2) <= 1;
}

function _type_confidence(detected, target) {
  if (!target) return 1.0;
  if (_is_ambiguous(detected)) return 0.0;
  if (target === "circle" && detected.includes("circle")) return 1.0;
  if (target !== "circle" && detected.includes(target)) return 1.0;
  const i1 = POLY_ORDER.indexOf(target);
  const i2 = POLY_ORDER.indexOf(detected);
  if (i1 !== -1 && i2 !== -1 && Math.abs(i1 - i2) === 1) return 0.7;
  return 0.0;
}

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
    const areaA = _json_area(a.visual || {});
    const areaB = _json_area(b.visual || {});
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
  'sec-ch-ua': '"Not:A-Brand";v="99", "Google Chrome";v="125", "Chromium";v="125"',
  'sec-ch-ua-mobile': '?0',
  'sec-ch-ua-platform': '"Windows"',
  'Sec-Fetch-Dest': 'empty',
  'Sec-Fetch-Mode': 'cors',
  'Sec-Fetch-Site': 'same-origin',
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
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
  url = sanitizeUrl(url);
  if (!/^https?:\/\//i.test(url)) {
    return sendError(res, 400, 'URL must start with http:// or https://', handlerStart);
  }
  if (!axiosInstance) {
    axiosInstance = require('axios').create({
      timeout: 90000,
      headers: { 'User-Agent': 'Mozilla/5.0 (compatible; BypassBot/2.0)' }
    });
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
  if (!USER_RATE_LIMIT.has(userKey)) USER_RATE_LIMIT.set(userKey, []);
  let times = USER_RATE_LIMIT.get(userKey);
  times = times.filter(t => now - t < CONFIG.RATE_LIMIT_WINDOW_MS);
  times.push(now);
  USER_RATE_LIMIT.set(userKey, times);
  if (times.length > CONFIG.MAX_REQUESTS_PER_WINDOW) {
    return sendError(res, 429, 'Rate limit reached', handlerStart);
  }
  return await handlePlatorelay(axios, url, handlerStart, res, incomingUserId);
};