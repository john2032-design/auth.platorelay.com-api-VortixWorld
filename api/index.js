// api/index.js (directory: api/)
const cheerio = require('cheerio');
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

function solveStage(stage) {
  return "0";
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
  const button = $('button.inline-flex');
  if (button.length === 0) {
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
    answers.push(solveStage(stages[i]));
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
  const continueButton = $final('button:contains("Continue"), button:contains("Lootlabs")');
  if (continueButton.length === 0) {
    return sendError(res, 500, 'Final continue button not found', handlerStart);
  }
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