from flask import Flask, request, render_template, jsonify
import time
from pow_client import handle_platorelay

app = Flask(__name__)

@app.route('/', methods=['GET'])
def index():
    url = request.args.get('url')
    if url:
        result = handle_platorelay(url, '')
        return jsonify(result)
    return render_template('index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)