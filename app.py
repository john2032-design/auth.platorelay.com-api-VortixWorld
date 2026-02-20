# app.py (directory: root)
from flask import Flask, request, jsonify, render_template
import time
from pow_client import handle_platorelay

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    start_time = time.perf_counter_ns()
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
    set_cors_headers(resp)
    return resp

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)