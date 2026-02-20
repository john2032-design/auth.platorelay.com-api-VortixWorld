const getCurrentTime = () => process.hrtime.bigint();
const formatDuration = (startNs, endNs = process.hrtime.bigint()) => {
  const durationNs = Number(endNs - startNs);
  const durationSec = durationNs / 1_000_000_000;
  return `${durationSec.toFixed(2)}s`;
};

const CONFIG = {
  SUPPORTED_METHODS: ['GET', 'POST'],
  RATE_LIMIT_WINDOW_MS: 60000,
  MAX_REQUESTS_PER_WINDOW: 15
};

const HOST_RULES = {
  'lootlabs.gg': ['abysm'],
  'loot-link.com': ['abysm'],
  'lootdest.org': ['abysm'],
  'linkvertise.com': ['abysm']
};

const USER_RATE_LIMIT = new Map();

const extractHostname = (url) => {
  try {
    let u = new URL(url.startsWith('http') ? url : 'https://' + url);
    return u.hostname.toLowerCase().replace(/^www\./, '');
  } catch {
    return '';
  }
};

const sanitizeUrl = (url) => {
  if (typeof url !== 'string') return url;
  return url.trim().replace(/[\r\n\t]/g, '');
};

const getUserId = (req) => {
  if (req.method === 'POST') {
    return req.body?.['x_user_id'] || req.body?.['x-user-id'] || req.body?.xUserId || '';
  }
  return req.headers?.['x-user-id'] || req.headers?.['x_user_id'] || req.headers?.['x-userid'] || '';
};

const sendError = (res, statusCode, message, startTime) =>
  res.status(statusCode).json({
    status: 'error',
    result: message,
    time_taken: formatDuration(startTime)
  });

const sendSuccess = (res, result, userId, startTime) =>
  res.json({
    status: 'success',
    result,
    x_user_id: userId || '',
    time_taken: formatDuration(startTime)
  });

const tryAbysm = async (axios, url) => {
  try {
    const res = await axios.get('https://api.abysm.lat/v2/bypass', {
      params: { url },
      headers: { 'x-api-key': 'ABYSM-185EF369-E519-4670-969E-137F07BB52B8' }
    });
    const d = res.data;
    if (d?.status === 'success' && d?.data?.result) {
      return { success: true, result: d.data.result };
    }
    if (d?.result) return { success: true, result: d.result };
    let errorMsg = d?.error || d?.message || null;
    if (errorMsg && (errorMsg.includes('error') || errorMsg.includes('fail') || errorMsg.includes('failed')) ) {
      errorMsg = 'Bypass Failed';
    }
    return { success: false, error: errorMsg };
  } catch (e) {
    let errorMsg = e?.message || String(e);
    if (errorMsg.includes('error') || errorMsg.includes('fail') || errorMsg.includes('failed')) {
      errorMsg = 'Bypass Failed';
    }
    return { success: false, error: errorMsg };
  }
};

const API_REGISTRY = {
  abysm: tryAbysm
};

const getApiChain = (hostname) => {
  for (const [host, apis] of Object.entries(HOST_RULES)) {
    if (hostname === host || hostname.endsWith('.' + host)) {
      return [...apis];
    }
  }
  return [];
};

const executeApiChain = async (axios, url, apiNames) => {
  let lastError = null;
  for (let i = 0; i < apiNames.length; i++) {
    const name = apiNames[i];
    const fn = API_REGISTRY[name];
    if (!fn) continue;
    try {
      const result = await fn(axios, url);
      if (result && result.success) {
        return { success: true, result: result.result };
      } else {
        lastError = (result && (result.error || result.message || result.result)) || lastError || 'Unknown error from upstream API';
      }
    } catch (e) {
      lastError = e?.message || String(e);
    }
  }
  return { success: false, error: lastError };
};

const setCorsHeaders = (req, res) => {
  const allowedOrigins = process.env.ALLOWED_ORIGINS?.split(',') || ['*'];
  const origin = req.headers.origin;
  if (allowedOrigins.includes('*')) {
    res.setHeader('Access-Control-Allow-Origin', '*');
  } else if (origin && allowedOrigins.includes(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Access-Control-Allow-Credentials', 'true');
  }
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type,x-user-id,x_user_id,x-userid,x-api-key');
};

let axiosInstance = null;

const cv = require('@u4/opencv4nodejs');

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

const POLY_ORDER = ['triangle', 'square', 'rectangle', 'pentagon', 'hexagon', 'heptagon'];

function sampleBackground(bgr, sampleRadius = 8) {
  const h = bgr.rows;
  const w = bgr.cols;
  const r = Math.min(sampleRadius, Math.floor(h / 4), Math.floor(w / 4));
  const corners = [
    bgr.getRegion(new cv.Rect(0, 0, r, r)),
    bgr.getRegion(new cv.Rect(w - r, 0, r, r)),
    bgr.getRegion(new cv.Rect(0, h - r, r, r)),
    bgr.getRegion(new cv.Rect(w - r, h - r, r, r)),
  ];
  let sumB = 0, sumG = 0, sumR = 0, count = 0;
  for (const c of corners) {
    const mean = c.mean();
    const pix = c.rows * c.cols;
    sumB += mean.x * pix;
    sumG += mean.y * pix;
    sumR += mean.z * pix;
    count += pix;
  }
  return new cv.Vec3(sumB / count, sumG / count, sumR / count);
}

function foregroundMask(bgr, bgColor, thresh = 30.0) {
  const diffF = bgr.convertTo(cv.CV_32F);
  const bgF = new cv.Mat(bgr.rows, bgr.cols, cv.CV_32FC3, bgColor);
  const diff = diffF.sub(bgF);
  const channels = diff.split();
  const dx2 = channels[0].mul(channels[0]);
  const dy2 = channels[1].mul(channels[1]);
  const dz2 = channels[2].mul(channels[2]);
  const distSquared = dx2.add(dy2).add(dz2);
  const dist = distSquared.sqrt();
  const mask = dist.threshold(thresh, 255, cv.THRESH_BINARY);
  return mask.convertTo(cv.CV_8U);
}

const kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, new cv.Size(3, 3));

function bestFromBinary(binary) {
  const closed = binary.morphologyEx(cv.MORPH_CLOSE, kernel, {iterations: 2});
  const contours = closed.findContours(cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE);
  const imgArea = binary.rows * binary.cols;
  const valid = contours.filter(c => {
    const a = cv.contourArea(c);
    return imgArea * 0.003 < a && a < imgArea * 0.90;
  });
  if (valid.length === 0) return [null, 0.0];
  let maxA = 0;
  let cnt = null;
  for (const c of valid) {
    const a = cv.contourArea(c);
    if (a > maxA) {
      maxA = a;
      cnt = c;
    }
  }
  return [cnt, maxA];
}

function extractShapeContour(bgr, gray) {
  const results = [];
  const bg = sampleBackground(bgr);
  for (const thresh of [20, 35, 50, 15]) {
    const mask = foregroundMask(bgr, bg, thresh);
    const [cnt, area] = bestFromBinary(mask);
    if (cnt) results.push({area, cnt});
  }
  const blur = gray.gaussianBlur(new cv.Size(3, 3), 0);
  for (const flags of [cv.THRESH_BINARY_INV | cv.THRESH_OTSU, cv.THRESH_BINARY | cv.THRESH_OTSU]) {
    const [, b] = blur.threshold(0, 255, flags);
    const [cnt, area] = bestFromBinary(b);
    if (cnt) results.push({area, cnt});
  }
  const edges = blur.canny(30, 100);
  const dilated = edges.dilate(kernel, new cv.Point(-1, -1), {iterations: 3});
  const [cnt, area] = bestFromBinary(dilated);
  if (cnt) results.push({area, cnt});
  if (results.length === 0) return null;
  results.sort((a, b) => b.area - a.area);
  return results[0].cnt;
}

function classify(cnt) {
  const perimeter = cv.arcLength(cnt, true);
  const area = cv.contourArea(cnt);
  const circularity = perimeter > 0 ? (4 * Math.PI * area) / (perimeter ** 2) : 0.0;
  const vertexVotes = new Map();
  for (const frac of [0.01, 0.015, 0.02, 0.03, 0.04, 0.05]) {
    const approx = cnt.approxPolyDP(frac * perimeter, true);
    const v = approx.length;
    vertexVotes.set(v, (vertexVotes.get(v) || 0) + 1);
  }
  let vertices = 0;
  let maxVote = 0;
  for (const [v, count] of vertexVotes.entries()) {
    if (count > maxVote || (count === maxVote && v < vertices)) {
      maxVote = count;
      vertices = v;
    }
  }
  let shape;
  if (vertices === 3) shape = 'triangle';
  else if (vertices === 4) {
    const bounding = cnt.boundingRect();
    const ar = bounding.width / bounding.height;
    shape = ar >= 0.78 && ar <= 1.28 ? 'square' : 'rectangle';
  } else if (vertices === 5) shape = 'pentagon';
  else if (vertices === 6) shape = 'hexagon';
  else if (vertices === 7) shape = 'heptagon';
  else if (vertices >= 8) shape = circularity >= 0.72 ? 'circle' : 'circle-ish';
  else shape = circularity >= 0.72 ? 'circle' : `unknown-${vertices}`;
  if (circularity >= 0.88 && !shape.includes('circle')) shape = 'circle';
  return { shape, vertices, circularity };
}

function dominantColor(bgr, mask = null) {
  const hsv = bgr.cvtColor(cv.COLOR_BGR2HSV);
  let best = 'unknown';
  let bestN = 0;
  for (const [name, ranges] of Object.entries(COLOR_RANGES)) {
    let m = new cv.Mat(hsv.rows, hsv.cols, cv.CV_8U, 0);
    for (const [lo, hi] of ranges) {
      const hit = hsv.inRange(new cv.Vec3(...lo), new cv.Vec3(...hi));
      m = m.or(hit);
    }
    if (mask) m = m.and(mask);
    const n = m.countNonZero();
    if (n > bestN) {
      bestN = n;
      best = name;
    }
  }
  return best;
}

function analyzeShape(b64String) {
  const EMPTY = { area: 0.0, hullArea: 0.0, bboxArea: 0.0, type: 'unknown', vertices: 0, circularity: 0.0, color: 'unknown' };
  try {
    let rawB64 = b64String.split(',')[1] || b64String;
    const buffer = Buffer.from(rawB64, 'base64');
    let img = cv.imdecode(buffer, cv.IMREAD_UNCHANGED);
    if (img.empty) return EMPTY;
    let bgr = new cv.Mat();
    if (img.channels() === 1) {
      cv.cvtColor(img, bgr, cv.COLOR_GRAY2BGR);
    } else if (img.channels() === 4) {
      cv.cvtColor(img, bgr, cv.COLOR_BGRA2BGR);
    } else {
      bgr = img.clone();
    }
    const gray = new cv.Mat();
    cv.cvtColor(bgr, gray, cv.COLOR_BGR2GRAY);
    const cnt = extractShapeContour(bgr, gray);
    if (!cnt) return { ...EMPTY, type: 'no_contour' };
    const area = cv.contourArea(cnt);
    if (area < 10) return EMPTY;
    const {shape, vertices, circularity} = classify(cnt);
    const hull = new cv.Mat();
    cv.convexHull(cnt, hull, false, true);
    const hullArea = cv.contourArea(hull);
    const bounding = cnt.boundingRect();
    const bboxArea = bounding.width * bounding.height;
    const fmask = new cv.Mat(gray.rows, gray.cols, cv.CV_8U, new cv.Scalar(0));
    const contoursVec = new cv.MatVector();
    contoursVec.push_back(cnt);
    cv.drawContours(fmask, contoursVec, -1, new cv.Scalar(255), cv.FILLED);
    const color = dominantColor(bgr, fmask);
    img.delete();
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

const SHAPE_KEYWORDS = ["circle", "square", "triangle", "rectangle", "hexagon", "pentagon", "heptagon", "polygon"];

const COLOR_KEYWORDS = ["red", "orange", "yellow", "green", "blue", "purple", "white", "black", "gray"];

function genFingerprint() {
  const val = Math.floor(Math.random() * 0xFFFFFFFF) - 0x80000000;
  const hex = Math.abs(val).toString(16).padStart(8, '0');
  return val >= 0 ? hex : `-${hex}`;
}

function genTelemetry(dwellMs) {
  const moves = Math.floor(Math.random() * 141) + 180;
  const speedMin = +(Math.random() * 0.0045 + 0.0005).toFixed(15);
  const speedMax = +(Math.random() * 8 + 8).toFixed(15);
  const speedMedian = +(Math.random() * 0.3 + 0.15).toFixed(15);
  const speedAvg = +(Math.random() * 0.5 + 0.45).toFixed(15);
  const speedP25 = +(Math.random() * 0.1 + 0.05).toFixed(15);
  const speedP75 = +(Math.random() * 0.4 + 0.55).toFixed(15);
  const velVar = +(Math.random() * 2 + 1).toFixed(15);
  const dirChanges = Math.floor(Math.random() * 5) + 1;
  const moveDensity = +(moves / (dwellMs / 1000)).toFixed(4);
  return {
    dwellMs: +dwellMs.toFixed(1),
    moves,
    velocityVar: velVar,
    velocityMedian: speedMedian,
    velocityAvg: speedAvg,
    velocityMin: speedMin,
    velocityMax: speedMax,
    velocityP25: speedP25,
    velocityP75: speedP75,
    directionChanges: dirChanges,
    keypresses: 0,
    speedSamples: moves,
    moveDensity,
  };
}

function genPath(dwellMs) {
  const clickTs = +(dwellMs + Math.random() * 250 - 200).toFixed(1);
  const totalDist = +(Math.random() * 320 + 80).toFixed(1);
  const durationMs = +(Math.random() * 80 + 40).toFixed(1);
  const moves = Math.floor(Math.random() * 4) + 1;
  const avgSpeed = durationMs > 0 ? +(totalDist / durationMs).toFixed(4) : 0;
  return {
    moves,
    totalDist,
    durationMs,
    avgSpeed,
    clickTimestamp: clickTs,
    timeToFirstClick: clickTs,
  };
}

function genVerifyMeta(numStages) {
  const baseDwell = Math.random() * 10000 + 10000;
  const extraDwell = (numStages - 1) * (Math.random() * 5000 + 5000);
  const dwellMs = baseDwell + extraDwell;
  const path = genPath(dwellMs);
  const telemetry = genTelemetry(dwellMs);
  const fingerprint = genFingerprint();
  return { path, telemetry, fingerprint };
}

function parseInstruction(instruction) {
  const instr = instruction.toLowerCase();
  const targetType = SHAPE_KEYWORDS.find(k => instr.includes(k)) || null;
  const targetColor = COLOR_KEYWORDS.find(k => instr.includes(k)) || null;
  const wantSmallest = ['smallest', 'tiny', 'minimum'].some(w => instr.includes(w));
  const wantLargest = ['largest', 'biggest', 'maximum'].some(w => instr.includes(w)) || (!wantSmallest);
  return { targetType, targetColor, wantSmallest, wantLargest };
}

function isAmbiguous(t) {
  return !t || ['unknown', 'error', 'no_contour'].includes(t) || t.startsWith('unknown-');
}

function typeMatchesStrict(detected, target) {
  if (isAmbiguous(detected)) return false;
  if (target === 'circle') return detected.includes('circle');
  if (detected.includes(target)) return true;
  const i1 = POLY_ORDER.indexOf(target);
  const i2 = POLY_ORDER.indexOf(detected);
  if (i1 === -1 || i2 === -1) return false;
  return Math.abs(i1 - i2) <= 1;
}

function typeConfidence(detected, target) {
  if (!target) return 1.0;
  if (isAmbiguous(detected)) return 0.0;
  if (target === 'circle' && detected.includes('circle')) return 1.0;
  if (target !== 'circle' && detected.includes(target)) return 1.0;
  const i1 = POLY_ORDER.indexOf(target);
  const i2 = POLY_ORDER.indexOf(detected);
  if (i1 !== -1 && i2 !== -1 && Math.abs(i1 - i2) === 1) return 0.7;
  return 0.0;
}

function jsonArea(s) {
  let a = s.area || s.size;
  if (typeof a === 'number') return a;
  const w = s.width, h = s.height;
  if (typeof w === 'number' && typeof h === 'number') return w * h;
  const r = s.radius;
  if (typeof r === 'number') return Math.PI * r * r;
  return 0.0;
}

async function solveStage(stage, stageIdx) {
  const instruction = stage.instruction || '';
  let shapes = stage.shapes || [];
  const { targetType, targetColor, wantSmallest, wantLargest } = parseInstruction(instruction);
  if (shapes.length === 0) return '0';
  for (const s of shapes) {
    const b64 = s.img;
    if (!b64) {
      s.visual = { area: 0.0, type: 'unknown', vertices: 0, circularity: 0.0, color: 'unknown' };
      continue;
    }
    s.visual = analyzeShape(b64);
  }
  let candidates = shapes.filter(s => typeMatchesStrict(s.visual.type || '', targetType || ''));
  if (candidates.length === 0) candidates = shapes;
  if (targetColor) {
    const cc = candidates.filter(s => (s.visual.color || 'unknown') === targetColor);
    if (cc.length > 0) candidates = cc;
  }
  candidates.sort((a, b) => {
    const areaA = jsonArea(a.visual);
    const areaB = jsonArea(b.visual);
    const confA = typeConfidence(a.visual.type || '', targetType || '');
    const confB = typeConfidence(b.visual.type || '', targetType || '');
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
  const html = response.data;
  const androidStructure = '<div class="flex flex-col p-6 space-y-1"><h3 class="font-semibold tracking-tight text-2xl text-center">Delta Android Keysystem</h3>';
  const iosStructure = '<div class="flex flex-col p-6 space-y-1"><h3 class="font-semibold tracking-tight text-2xl text-center">Delta iOS Keysystem</h3>';
  let isAndroid = html.includes(androidStructure);
  let isIos = html.includes(iosStructure);
  if (!isAndroid && !isIos) {
    return sendError(res, 500, 'Unknown keysystem type', handlerStart);
  }
  const steps = isAndroid ? 1 : 2;
  let buttonStructure = isAndroid ? '<button class="inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none ring-offset-background bg-primary text-primary-foreground hover:bg-primary/90 h-10 w-full p-4" target="_blank">Continue</button>' : '<button class="inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none ring-offset-background bg-primary text-primary-foreground hover:bg-primary/90 h-10 w-full p-4" target="_blank">Lootlabs (1 step)</button>';
  await new Promise(r => setTimeout(r, 5000));
  const buttonIndex = html.indexOf(buttonStructure);
  if (buttonIndex === -1) {
    return sendError(res, 500, 'Button not found', handlerStart);
  }
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
    answers.push(await solveStage(stages[i], i));
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
  const continueButton = '<button class="inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none ring-offset-background bg-primary text-primary-foreground hover:bg-primary/90 h-10 w-full p-4">Continue</button>';
  if (!finalHtml.includes(continueButton)) {
    return sendError(res, 500, 'Final continue button not found', handlerStart);
  }
  const keyStructure = '<div class="key-text" id="keyText">';
  const keyIndex = finalHtml.indexOf(keyStructure);
  if (keyIndex === -1) {
    return sendError(res, 500, 'Key not found', handlerStart);
  }
  const start = keyIndex + keyStructure.length;
  const end = finalHtml.indexOf('</div>', start);
  const key = finalHtml.substring(start, end).trim();
  if (!key.startsWith('FREE_')) {
    return sendError(res, 500, 'Invalid key format', handlerStart);
  }
  return sendSuccess(res, key, incomingUserId, handlerStart);
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