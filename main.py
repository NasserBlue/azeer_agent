import json
import logging
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return ("Server is running!", 200)

    # Print whatever headers Azeer sends
    logging.info("--- HEADERS RECEIVED ---")
    logging.info(dict(request.headers))

    # Print the exact Chat Assigned data
    data = request.get_json(silent=True) or {}
    logging.info("--- CHAT ASSIGNED PAYLOAD ---")
    logging.info(json.dumps(data, indent=2, ensure_ascii=False))

    return jsonify({"status": "received"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
