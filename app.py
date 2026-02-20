from flask import Flask, request, jsonify
import time
from pow_client import handle_platorelay
from visual_verification import _parse_instruction

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
  if request.method == 'GET':
    url = request.args.get('url')
  else:
    url = request.json.get('url') if request.is_json else None
  if not url:
    return jsonify({"status": "error", "result": "Missing URL parameter", "time_taken": "0.00s"}), 400
  incoming_user_id = request.headers.get('x-user-id') or request.headers.get('x_user_id') or request.headers.get('x-userid') or ''
  result = handle_platorelay(url, incoming_user_id)
  return jsonify(result)

if __name__ == '__main__':
  app.run(host='0.0.0.0', port=3000)