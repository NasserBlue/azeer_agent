import os
import json
import logging
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
import requests
from google import genai

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# --- In-Memory Log Store ---
# Keeps the latest 50 assignment events
ASSIGNMENT_LOGS = []

# --- Azeer Credentials ---
AZEER_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhZG1pbiI6dHJ1ZSwiaHR0cHM6Ly9oYXN1cmEuaW8vand0L2NsYWltcyI6eyJ4LWF2Yy1hcGlrZXktaWQiOiI3MzBlMDhiMi00MGQzLTRlMmMtYjA3NS1hOGIyYjhhNDEwOWEiLCJ4LWF2Yy1hcGlrZXktc2NvcGUiOiJpbnNlcnQiLCJ4LWF2Yy1ob3N0LWlkIjoiZjNjZWZhMGUtYmQyYi00NjY0LWE5MzUtZmY5ZTc4MDY3MGRmIiwieC1hdmMtcGxhdGZvcm0taWQiOiJuYXNzZXJqLjdAaG90bWFpbC5jb20iLCJ4LWF2Yy1wbGF0Zm9ybS10eXBlIjoiYXZvY2FkbyIsIngtaGFzdXJhLWFsbG93ZWQtcm9sZXMiOlsiYWRtaW4iLCJzdXBlcmFkbWluIl0sIngtaGFzdXJhLWJ1c2luZXNzLWlkIjoiMGRlODhlZjEtNmM1Ny00NTZhLWE0M2QtN2E4MjQwYWUzMDE3IiwieC1oYXN1cmEtZGVmYXVsdC1yb2xlIjoiYWRtaW4iLCJ4LWhhc3VyYS1wcm9maWxlLWlkIjoiNDExIiwieC1oYXN1cmEtdXNlci1pZCI6IjQxMSJ9LCJpYXQiOjE3OTM5NjQ4MjAsImlzcyI6ImF2b2NhZG8tY29yZSIsIm5hbWUiOiJOYXNzZXIgQWxKdWJhaWx5Iiwic3ViIjoiNDExIn0.69BPEVYFd-NqIRgcbVxwYApEF0J0wYDmU89up8vlsgE"
AZEER_SEND_URL = "https://api.mottasl.ai/v1/message/send"
APPROVED_TEMPLATE_NAME = "welcome_customer"

# --- Gemini Client ---
ai_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Azeer Chat Assignments</title>
    <meta http-equiv="refresh" content="10">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f7fafc; padding: 30px; margin: 0; }
        .container { max-width: 900px; margin: auto; background: #ffffff; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); padding: 25px; }
        h1 { margin-top: 0; color: #1a202c; font-size: 22px; display: flex; justify-content: space-between; align-items: center; }
        .badge { font-size: 13px; background: #ebf8ff; color: #2b6cb0; padding: 4px 10px; border-radius: 9999px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { text-align: left; padding: 12px; border-bottom: 1px solid #edf2f7; font-size: 14px; }
        th { background: #f8fafc; color: #4a5568; font-weight: 600; }
        tr:hover { background-color: #f8fafc; }
        .empty { text-align: center; color: #a0aec0; padding: 40px 0; font-size: 15px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>
            <span>Azeer Assignment Log</span>
            <span class="badge">Auto-refreshes every 10s</span>
        </h1>
        {% if logs %}
        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Customer Name</th>
                    <th>Phone (Platform ID)</th>
                    <th>Assigned Agent</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {% for item in logs %}
                <tr>
                    <td>{{ item.time }}</td>
                    <td><strong>{{ item.contact_name }}</strong></td>
                    <td>{{ item.platform_id }}</td>
                    <td>{{ item.agent_name }}</td>
                    <td><span style="color: #38a169; font-weight: 600;">{{ item.status }}</span></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <div class="empty">No chat assignments received yet. Assign a conversation in Azeer to test.</div>
        {% endif %}
    </div>
</body>
</html>
"""

def send_azeer_template(recipient_phone: str, template_name: str, client_name: str):
    headers = {
        "Authorization": f"Bearer {AZEER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "to": recipient_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "ar"},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": client_name}]
                }
            ]
        }
    }
    try:
        res = requests.post(AZEER_SEND_URL, json=payload, headers=headers)
        return res.json()
    except Exception as e:
        logging.error("Failed to send template: %s", e)
        return None

@app.route("/", methods=["GET", "POST"])
def webhook():
    # Browser visits load the live table dashboard
    if request.method == "GET":
        return render_template_string(HTML_TEMPLATE, logs=ASSIGNMENT_LOGS)

    # Handle incoming webhook from Azeer
    data = request.get_json(silent=True) or {}
    event_type = data.get("webhook_event_type")

    if event_type == "chat_assigned":
        contact_name = data.get("contact_name") or "Unknown"
        platform_id = data.get("platform_id") or "Unknown"
        agent_name = data.get("agent_name") or "Unassigned"
        status = data.get("status") or "assigned"

        log_entry = {
            "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "contact_name": contact_name,
            "platform_id": platform_id,
            "agent_name": agent_name,
            "status": status
        }
        # Prepend so newest appears at the top
        ASSIGNMENT_LOGS.insert(0, log_entry)
        if len(ASSIGNMENT_LOGS) > 50:
            ASSIGNMENT_LOGS.pop()

        # Send approved template
        if platform_id != "Unknown":
            send_azeer_template(platform_id, APPROVED_TEMPLATE_NAME, contact_name)

    return jsonify({"status": "received"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
