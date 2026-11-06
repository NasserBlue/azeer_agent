import os
import json
import logging
import threading
import time
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template_string
import requests
from google import genai

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# --- In-Memory Stores ---
ASSIGNMENT_LOGS = []
PENDING_ASSIGNMENTS = {}  # Holds pending alerts: {platform_id: dict}
BUFFER_LOCK = threading.Lock()

# --- Config ---
SUPERVISOR_NUMBER = "966509708034"
DEFAULT_TEMPLATE_NAME = "welcome03"

AZEER_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhZG1pbiI6dHJ1ZSwiaHR0cHM6Ly9oYXN1cmEuaW8vand0L2NsYWltcyI6eyJ4LWF2Yy1hcGlrZXktaWQiOiI3MzBlMDhiMi00MGQzLTRlMmMtYjA3NS1hOGIyYjhhNDEwOWEiLCJ4LWF2Yy1hcGlrZXktc2NvcGUiOiJpbnNlcnQiLCJ4LWF2Yy1ob3N0LWlkIjoiZjNjZWZhMGUtYmQyYi00NjY0LWE5MzUtZmY5ZTc4MDY3MGRmIiwieC1hdmMtcGxhdGZvcm0taWQiOiJuYXNzZXJqLjdAaG90bWFpbC5jb20iLCJ4LWF2Yy1wbGF0Zm9ybS10eXBlIjoiYXZvY2FkbyIsIngtaGFzdXJhLWFsbG93ZWQtcm9sZXMiOlsiYWRtaW4iLCJzdXBlcmFkbWluIl0sIngtaGFzdXJhLWJ1c2luZXNzLWlkIjoiMGRlODhlZjEtNmM1Ny00NTZhLWE0M2QtN2E4MjQwYWUzMDE3IiwieC1oYXN1cmEtZGVmYXVsdC1yb2xlIjoiYWRtaW4iLCJ4LWhhc3VyYS1wcm9maWxlLWlkIjoiNDExIiwieC1oYXN1cmEtdXNlci1pZCI6IjQxMSJ9LCJpYXQiOjE3OTM5NjQ4MjAsImlzcyI6ImF2b2NhZG8tY29yZSIsIm5hbWUiOiJOYXNzZXIgQWxKdWJhaWx5Iiwic3ViIjoiNDExIn0.69BPEVYFd-NqIRgcbVxwYApEF0J0wYDmU89up8vlsgE"
AZEER_SEND_URL = "https://api.mottasl.ai/v1/message/send"

# --- Gemini Client & Agent Profile ---
ai_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

AGENT_PROFILE = {
    "name": "Azeer AI Dispatcher",
    "id": "agent_dispatcher_01",
    "model": "gemini-2.5-flash",
    "role": "Customer Service Operations Monitor & WhatsApp Dispatcher",
    "description": "Monitors conversation assignment and customer interaction events in Azeer, summarizes conversation context, and notifies the supervisor via WhatsApp.",
}

AGENT_SYSTEM_INSTRUCTIONS = """
You are an autonomous AI operations dispatcher.
Your instructions:
1. Receive assignment details: customer name, customer phone, and final assigned agent.
2. Produce a short, clean notification text for the supervisor in English.
3. Example format:
   🔔 Assignment Alert
   Customer: [Name] ([Phone])
   Assigned To: [Agent Name]
   Status: Active
Keep it exact, concise, and professional.
"""

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Azeer AI Agent Monitor</title>
    <meta http-equiv="refresh" content="5">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f7fafc; padding: 30px; margin: 0; color: #2d3748; }
        .container { max-width: 950px; margin: auto; background: #ffffff; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); padding: 25px; }
        .agent-card { background: #edf2f7; border-left: 4px solid #3182ce; padding: 18px; border-radius: 6px; margin-bottom: 25px; }
        .agent-card h2 { margin: 0 0 10px 0; font-size: 18px; color: #1a202c; }
        .agent-card p { margin: 5px 0; font-size: 13px; color: #4a5568; line-height: 1.5; }
        .tag { font-family: monospace; background: #e2e8f0; padding: 2px 6px; border-radius: 4px; font-size: 12px; }
        h1 { margin-top: 20px; font-size: 20px; display: flex; justify-content: space-between; align-items: center; }
        .badge { font-size: 12px; background: #ebf8ff; color: #2b6cb0; padding: 4px 10px; border-radius: 9999px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { text-align: left; padding: 12px; border-bottom: 1px solid #edf2f7; font-size: 14px; }
        th { background: #f8fafc; color: #4a5568; font-weight: 600; }
        tr:hover { background-color: #f8fafc; }
        .empty { text-align: center; color: #a0aec0; padding: 40px 0; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="agent-card">
            <h2>🤖 Agent Profile</h2>
            <p><strong>Name:</strong> {{ agent.name }} (<span class="tag">{{ agent.id }}</span>)</p>
            <p><strong>Role:</strong> {{ agent.role }}</p>
            <p><strong>AI Engine:</strong> <span class="tag">{{ agent.model }}</span></p>
            <p><strong>Target Supervisor:</strong> <span class="tag">+{{ supervisor }}</span></p>
        </div>

        <h1>
            <span>Live Activity Log</span>
            <span class="badge">Auto-refreshes every 5s</span>
        </h1>

        {% if logs %}
        <table>
            <thead>
                <tr>
                    <th>Timestamp</th>
                    <th>Customer Name</th>
                    <th>Customer Phone</th>
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
                    <td><strong style="color: #2b6cb0;">{{ item.agent_name }}</strong></td>
                    <td><span style="color: #38a169; font-weight: 600;">{{ item.status }}</span></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <div class="empty">No events received yet. Assign a conversation in Azeer to test.</div>
        {% endif %}
    </div>
</body>
</html>
"""

def generate_ai_brief(event_type: str, details: dict) -> str:
    """Uses Gemini 2.5 Flash to generate an alert message."""
    try:
        prompt = (
            f"Event: {event_type}\n"
            f"Details: {json.dumps(details, ensure_ascii=False)}\n"
            f"Create the supervisor WhatsApp message."
        )
        response = ai_client.models.generate_content(
            model=AGENT_PROFILE["model"],
            contents=prompt,
            config={
                "system_instruction": AGENT_SYSTEM_INSTRUCTIONS,
                "temperature": 0.1
            }
        )
        return response.text.strip()
    except Exception as e:
        logging.error("AI briefing generation error: %s", e)
        return (
            f"Assignment Alert:\n"
            f"Customer: {details.get('contact_name')} ({details.get('platform_id')})\n"
            f"Assigned To: {details.get('agent_name')}"
        )

def send_azeer_text_message(recipient_phone: str, text_message: str):
    headers = {
        "Authorization": f"Bearer {AZEER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "to": recipient_phone,
        "type": "text",
        "text": {"body": text_message}
    }
    try:
        res = requests.post(AZEER_SEND_URL, json=payload, headers=headers)
        return res.json()
    except Exception as e:
        logging.error("Failed to send text message: %s", e)
        return None

def send_azeer_template(recipient_phone: str, template_name: str, fallback_text: str):
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
                    "parameters": [{"type": "text", "text": fallback_text}]
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

def notify_supervisor(alert_message: str, fallback_text: str):
    resp = send_azeer_text_message(SUPERVISOR_NUMBER, alert_message)
    if not resp or resp.get("status") in ["failed", "error"] or "error" in resp:
        logging.info("Chat session expired/closed for supervisor. Sending template fallback...")
        send_azeer_template(SUPERVISOR_NUMBER, DEFAULT_TEMPLATE_NAME, fallback_text)

def process_settled_assignment(platform_id: str, trigger_epoch: float):
    """Waits 3 seconds so the final assignee payload arrives before writing to log or sending WhatsApp."""
    time.sleep(3.0)

    with BUFFER_LOCK:
        entry = PENDING_ASSIGNMENTS.get(platform_id)
        if not entry or entry["trigger_epoch"] != trigger_epoch:
            return  # Replaced by a newer payload; exit early

        # Remove from pending queue
        del PENDING_ASSIGNMENTS[platform_id]

    # 1. Update the official activity log
    log_item = {
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "contact_name": entry["contact_name"],
        "platform_id": entry["platform_id"],
        "agent_name": entry["agent_name"],
        "status": entry["status"]
    }
    ASSIGNMENT_LOGS.insert(0, log_item)
    if len(ASSIGNMENT_LOGS) > 50:
        ASSIGNMENT_LOGS.pop()

    # 2. Generate the AI alert using the settled agent name
    alert_text = generate_ai_brief("chat_assigned", {
        "contact_name": entry["contact_name"],
        "platform_id": entry["platform_id"],
        "agent_name": entry["agent_name"]
    })

    # 3. Send to WhatsApp
    fallback_info = f"{entry['contact_name']} -> {entry['agent_name']}"
    notify_supervisor(alert_text, fallback_info)
    logging.info("Processed final assignment: %s to %s", entry["contact_name"], entry["agent_name"])

@app.route("/", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return render_template_string(
            HTML_TEMPLATE,
            logs=ASSIGNMENT_LOGS,
            agent=AGENT_PROFILE,
            supervisor=SUPERVISOR_NUMBER
        )

    data = request.get_json(silent=True) or {}
    logging.info("AZEER RAW EVENT: %s", json.dumps(data, ensure_ascii=False))

    event_type = data.get("webhook_event_type") or data.get("type") or "unknown"
    contact_name = data.get("contact_name") or "Unknown Customer"
    platform_id = data.get("platform_id") or data.get("from") or "Unknown"
    agent_name = data.get("agent_name") or "Unassigned"
    status = data.get("status") or "assigned"

    if event_type == "chat_assigned" and platform_id != "Unknown":
        current_epoch = time.time()
        with BUFFER_LOCK:
            PENDING_ASSIGNMENTS[platform_id] = {
                "trigger_epoch": current_epoch,
                "contact_name": contact_name,
                "platform_id": platform_id,
                "agent_name": agent_name,
                "status": status
            }

        # Spawn non-blocking thread to wait for rapid successive webhooks to settle
        threading.Thread(
            target=process_settled_assignment,
            args=(platform_id, current_epoch),
            daemon=True
        ).start()

        return jsonify({"status": "buffering_final_assignment"}), 200

    return jsonify({"status": "received"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
