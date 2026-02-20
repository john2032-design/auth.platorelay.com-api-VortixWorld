# app.py (directory: root)
from flask import Flask, request, jsonify, render_template
import time
from pow_client import handle_platorelay
import re
from urllib.parse import urlparse

app = Flask(__name__)

USER_RATE_LIMIT = {}

CONFIG = {
  'SUPPORTED_METHODS': ['GET', 'POST'],
  'RATE_LIMIT_WINDOW_MS': 60000,
  'MAX_REQUESTS_PER_WINDOW': 15
}

def get_current_time():
  return time.perf_counter_ns()

def format_duration(start_ns, end_ns = time.perf_counter_ns()):
  duration_ns = end_ns - start_ns
  duration_sec = duration_ns / 1_000_000_000
  return f"{duration_sec:.2f}s"

def extract_hostname(url):
  parsed = urlparse(url if url.startswith('http') else 'https://' + url)
  return parsed.hostname.lower().replace('www.', '') if parsed.hostname else ''

def sanitize_url(url):
  if not isinstance(url, str): return url
  return re.sub(r'[\r\n\t]', '', url.strip())

def get_user_id(req):
  if req.method == 'POST' and req.is_json:
    data = req.json
    return data.get('x_user_id') or data.get('x-user-id') or data.get('xUserId') or ''
  headers = req.headers
  return headers.get('x-user-id') or headers.get('x_user_id') or headers.get('x-userid') or ''

def send_error(status_code, message, start_time):
  return jsonify({
    'status': 'error',
    'result': message,
    'time_taken': format_duration(start_time)
  }), status_code

def send_success(result, user_id, start_time):
  return jsonify({
    'status': 'success',
    'result': result,
    'x_user_id': user_id or '',
    'time_taken': format_duration(start_time)
  })

@app.route('/', methods=['GET', 'POST', 'OPTIONS'])
def index():
  start_time = get_current_time()
  if request.method == 'OPTIONS':
    resp = jsonify({})
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type,x-user-id,x_user_id,x-userid,x-api-key'
    return resp, 200

  url = request.args.get('url') if request.method == 'GET' else (request.json.get('url') if request.is_json else None)
  if not url or not isinstance(url, str):
    return send_error(400, 'Missing URL parameter', start_time)
  url = sanitize_url(url)
  if not re.match(r'^https?://', url, re.I):
    return send_error(400, 'URL must start with http:// or https://', start_time)

  incoming_user_id = get_user_id(request)
  user_key = incoming_user_id or request.remote_addr or 'anonymous'
  now = time.time_ns() // 1_000_000
  if user_key not in USER_RATE_LIMIT:
    USER_RATE_LIMIT[user_key] = []
  times = USER_RATE_LIMIT[user_key]
  times = [t for t in times if now - t < CONFIG['RATE_LIMIT_WINDOW_MS']]
  times.append(now)
  USER_RATE_LIMIT[user_key] = times
  if len(times) > CONFIG['MAX_REQUESTS_PER_WINDOW']:
    return send_error(429, 'Rate limit reached', start_time)

  result = handle_platorelay(url, incoming_user_id)
  resp = jsonify(result)
  resp.headers['Access-Control-Allow-Origin'] = '*'
  return resp

if __name__ == '__main__':
  app.run(host='0.0.0.0', port=3000)