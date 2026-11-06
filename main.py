import os
import json
import logging
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template_string
import requests
from google import genai

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# --- In-Memory Log Store ---
ASSIGNMENT_LOGS = []
LAST_PROCESSED = {}

# --- Target Supervisor & Azeer Config ---
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
    "description": "Monitors conversation assignment and customer interaction events in Azeer, summarizes conversation context, and immediately notifies the designated supervisor via WhatsApp."
}

AGENT_SYSTEM_INSTRUCTIONS = """
You are an autonomous AI customer service operations dispatcher.
Your responsibilities:
1. Parse incoming customer events, chat assignments, and incoming WhatsApp messages from Azeer.
2. Formulate a crisp, concise executive alert in English for the supervisor.
3. Include critical context: Customer Name, Phone Number, Assigned Agent, and a brief description of the trigger event.
4. Keep the tone professional, clear, and direct. Avoid conversational fluff.
"""

# --- Dashboard HTML (English Interface) ---
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
        .agent-card h2 { margin: 0 0 10px 0; font-size: 18px; color: #1a202c; display: flex; align-items: center; gap: 8px; }
        .agent-card p { margin: 5px 0; font-size: 13px; color: #4a5568; line-height: 1.5; }
        .tag { font-family: monospace; background: #e2e8f0; padding: 2px 6px; border-radius: 4px; font-size: 12px; }
        h1 { margin-top: 20px; font-size: 20px; display: flex; justify-content: space-between; align-items: center; }
        .badge { font-size: 12px; background: #ebf8ff; color: #2b6cb0; padding: 4px 10px; border-radius: 9999px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { text-align: left; padding: 12px; border-bottom: 1px solid #edf2f7; font-size: 14px; }
        th { background: #f8fafc; color: #4a5568; font-weight: 600; }
        tr:hover { background-color: #f8fafc; }
        .status-pill { font-weight: 600; color: #38a169; }
        .empty { text-align: center; color: #a0aec0; padding: 40px 0; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <!-- Agent Profile & Identity -->
        <div class="agent-card">
            <h2>🤖 Agent Profile</h2>
            <p><strong>Name:</strong> {{ agent.name }} (<span class="tag">{{ agent.id }}</span>)</p>
            <p><strong>Role:</strong> {{ agent.role }}</p>
            <p><strong>AI Engine:</strong> <span class="tag">{{ agent.model }}</span></p>
            <p><strong>Description:</strong> {{ agent.description }}</p>
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
                    <td><span class="status-pill">{{ item.status }}</span></td>
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
    """Uses Gemini 2.5 Flash with strict system instructions to generate an English alert."""
    try:
        prompt = (
            f"Event Triggered: {event_type}\n"
            f"Payload Details: {json.dumps(details, ensure_ascii=False)}\n\n"
            f"Draft a short, structured WhatsApp alert to be sent to the supervisor in English."
        )
        response = ai_client.models.generate_content(
            model=AGENT_PROFILE["model"],
            contents=prompt,
            config={
                "system_instruction": AGENT_SYSTEM_INSTRUCTIONS,
                "temperature": 0.2
            }
        )
        return response.text.strip()
    except Exception as e:
        logging.error("AI briefing generation error: %s", e)
        return (
            f"ALERT: New {event_type} event.\n"
            f"Customer: {details.get('contact_name')} ({details.get('platform_id')})\n"
            f"Agent: {details.get('agent_name', 'N/A')}"
        )

def send_azeer_text_message(recipient_phone: str, text_message: str):
    """Sends normal free-form text if chat window is open."""
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
    """Sends pre-approved template when 24h WhatsApp window is expired/closed."""
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
    """Attempts standard text first; falls back to template if conversation session is closed."""
    resp = send_azeer_text_message(SUPERVISOR_NUMBER, alert_message)
    if not resp or resp.get("status") in ["failed", "error"] or "error" in resp:
        logging.info("Chat window closed for supervisor. Falling back to template message...")
        send_azeer_template(SUPERVISOR_NUMBER, DEFAULT_TEMPLATE_NAME, fallback_text)

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
    logging.info("AZEER WEBHOOK EVENT: %s", json.dumps(data, ensure_ascii=False))

    event_type = data.get("webhook_event_type") or data.get("type") or "unknown"
    contact_name = data.get("contact_name") or "Unknown Customer"
    platform_id = data.get("platform_id") or data.get("from") or "Unknown"
    agent_name = data.get("agent_name") or "Unassigned"
    status = data.get("status") or event_type

    now = datetime.now(timezone.utc)
    current_time_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")

    # 1. Assignment Event
    if event_type == "chat_assigned":
        # Consolidate double-events within 5s to show only the final assignee
        if platform_id in LAST_PROCESSED:
            time_diff = (now - LAST_PROCESSED[platform_id]["time"]).total_seconds()
            if time_diff <= 5.0 and ASSIGNMENT_LOGS:
                ASSIGNMENT_LOGS[0]["agent_name"] = agent_name
                ASSIGNMENT_LOGS[0]["time"] = current_time_str
                LAST_PROCESSED[platform_id]["time"] = now
                return jsonify({"status": "updated_to_final_agent"}), 200

        ASSIGNMENT_LOGS.insert(0, {
            "time": current_time_str,
            "contact_name": contact_name,
            "platform_id": platform_id,
            "agent_name": agent_name,
            "status": status
        })
        if len(ASSIGNMENT_LOGS) > 50:
            ASSIGNMENT_LOGS.pop()
        LAST_PROCESSED[platform_id] = {"time": now}

        # Generate English alert via Gemini and dispatch
        alert_body = generate_ai_brief("chat_assigned", {
            "contact_name": contact_name,
            "platform_id": platform_id,
            "agent_name": agent_name
        })
        notify_supervisor(alert_body, contact_name)

    # 2. Incoming Customer Message Event
    elif event_type in ["incoming_message", "message", "message_received"]:
        msg_text = data.get("text") or data.get("message_body", {}).get("text", {}).get("body", "")
        alert_body = generate_ai_brief("incoming_message", {
            "contact_name": contact_name,
            "platform_id": platform_id,
            "customer_message": msg_text
        })
        notify_supervisor(alert_body, contact_name)

    return jsonify({"status": "received"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
