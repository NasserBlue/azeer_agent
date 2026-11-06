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
app.url_map.strict_slashes = False  # Prevents 404 whether URL ends with / or not

# --- Configuration & Credentials ---
SUPERVISOR_NUMBER = "966509708034"
DEFAULT_TEMPLATE_NAME = "welcome03"
AZEER_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhZG1pbiI6dHJ1ZSwiaHR0cHM6Ly9oYXN1cmEuaW8vand0L2NsYWltcyI6eyJ4LWF2Yy1hcGlrZXktaWQiOiI3MzBlMDhiMi00MGQzLTRlMmMtYjA3NS1hOGIyYjhhNDEwOWEiLCJ4LWF2Yy1hcGlrZXktc2NvcGUiOiJpbnNlcnQiLCJ4LWF2Yy1ob3N0LWlkIjoiZjNjZWZhMGUtYmQyYi00NjY0LWE5MzUtZmY5ZTc4MDY3MGRmIiwieC1hdmMtcGxhdGZvcm0taWQiOiJuYXNzZXJqLjdAaG90bWFpbC5jb20iLCJ4LWF2Yy1wbGF0Zm9ybS10eXBlIjoiYXZvY2FkbyIsIngtaGFzdXJhLWFsbG93ZWQtcm9sZXMiOlsiYWRtaW4iLCJzdXBlcmFkbWluIl0sIngtaGFzdXJhLWJ1c2luZXNzLWlkIjoiMGRlODhlZjEtNmM1Ny00NTZhLWE0M2QtN2E4MjQwYWUzMDE3IiwieC1oYXN1cmEtZGVmYXVsdC1yb2xlIjoiYWRtaW4iLCJ4LWhhc3VyYS1wcm9maWxlLWlkIjoiNDExIiwieC1oYXN1cmEtdXNlci1pZCI6IjQxMSJ9LCJpYXQiOjE3OTM5NjQ4MjAsImlzcyI6ImF2b2NhZG8tY29yZSIsIm5hbWUiOiJOYXNzZXIgQWxKdWJhaWx5Iiwic3ViIjoiNDExIn0.69BPEVYFd-NqIRgcbVxwYApEF0J0wYDmU89up8vlsgE"
AZEER_SEND_URL = "https://api.mottasl.ai/v1/message/send"

# --- In-Memory Stores ---
ASSIGNMENT_LOGS = []
PENDING_ASSIGNMENTS = {}
CUSTOMER_BUFFERS = {}
BUFFER_LOCK = threading.Lock()

# --- Tools ---
def send_whatsapp_text(recipient_phone: str, message: str) -> dict:
    headers = {
        "Authorization": f"Bearer {AZEER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "to": recipient_phone,
        "type": "text",
        "text": {"body": message}
    }
    try:
        res = requests.post(AZEER_SEND_URL, json=payload, headers=headers)
        return res.json()
    except Exception as e:
        logging.error("WhatsApp text send error: %s", e)
        return {"error": str(e)}

def send_whatsapp_template(recipient_phone: str, template_name: str, param: str) -> dict:
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
                    "parameters": [{"type": "text", "text": param}]
                }
            ]
        }
    }
    try:
        res = requests.post(AZEER_SEND_URL, json=payload, headers=headers)
        return res.json()
    except Exception as e:
        logging.error("WhatsApp template send error: %s", e)
        return {"error": str(e)}

# --- Custom Agent Implementation (Matching your course style) ---
class Agent:
    def __init__(self, name, model, description, instruction, tools=None, sub_agents=None):
        self.name = name
        self.model = model
        self.description = description
        self.instruction = instruction
        self.tools = tools or []
        self.sub_agents = sub_agents or []
        self.client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    def run(self, task_input: str) -> str:
        res = self.client.models.generate_content(
            model=self.model,
            contents=task_input,
            config={
                "system_instruction": self.instruction,
                "temperature": 0.2
            }
        )
        msg_text = res.text.strip()
        # Execute tool dispatch
        resp = send_whatsapp_text(SUPERVISOR_NUMBER, msg_text)
        if not resp or resp.get("status") in ["failed", "error"] or "error" in resp:
            send_whatsapp_template(SUPERVISOR_NUMBER, DEFAULT_TEMPLATE_NAME, "Alert")
        return msg_text

# --- Sub-Agents ---
assignment_notifier_agent = Agent(
    name="AssignmentNotifierAgent",
    model="gemini-2.5-flash",
    description="Formats and dispatches alerts when a chat is assigned.",
    instruction="""
    You handle chat assignment alerts.
    Given customer details and the assigned agent:
    1. Construct a clean, professional English alert.
    2. Format:
       🔔 Assignment Alert
       Customer: [Customer Name] ([Phone Number])
       Assigned To: [Agent Name]
       Status: Active
    Keep it exact and professional.
    """,
    tools=[send_whatsapp_text, send_whatsapp_template]
)

message_summary_agent = Agent(
    name="MessageSummaryAgent",
    model="gemini-2.5-flash",
    description="Summarizes customer inquiries for the supervisor.",
    instruction="""
    You summarize incoming customer inquiries.
    1. Read the messages sent by the client.
    2. Write an executive alert in English explaining what the customer is asking.
    3. Format:
       📩 New Inquiry Summary
       Client: [Customer Name] ([Customer Phone])
       Summary: There is a client who is asking about [Inquiry Details].
    """,
    tools=[send_whatsapp_text, send_whatsapp_template]
)

# --- Root Agent ---
root_agent = Agent(
    name="RootAgent",
    model="gemini-2.5-flash",
    description="Central operations dispatcher managing specialized sub-agents.",
    instruction="""
    You are the central supervisor agent for Azeer customer operations.
    Route assignment tasks to AssignmentNotifierAgent and customer message summaries to MessageSummaryAgent.
    """,
    tools=[send_whatsapp_text, send_whatsapp_template],
    sub_agents=[assignment_notifier_agent, message_summary_agent]
)

# --- Web Monitor Interface ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{{ agent.name }} Monitor</title>
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
            <h2>🤖 Agent Hierarchy</h2>
            <p><strong>Root Agent:</strong> {{ agent.name }} (<span class="tag">{{ agent.model }}</span>)</p>
            <p><strong>Description:</strong> {{ agent.description }}</p>
            <p><strong>Sub-Agents:</strong>
                {% for sub in agent.sub_agents %}
                    <span class="tag">{{ sub.name }}</span>
                {% endfor %}
            </p>
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

# --- Background Buffer Runners ---
def process_settled_assignment(platform_id: str, trigger_epoch: float):
    time.sleep(3.0)
    with BUFFER_LOCK:
        entry = PENDING_ASSIGNMENTS.get(platform_id)
        if not entry or entry["trigger_epoch"] != trigger_epoch:
            return
        del PENDING_ASSIGNMENTS[platform_id]

    ASSIGNMENT_LOGS.insert(0, {
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "contact_name": entry["contact_name"],
        "platform_id": entry["platform_id"],
        "agent_name": entry["agent_name"],
        "status": entry["status"]
    })
    if len(ASSIGNMENT_LOGS) > 50:
        ASSIGNMENT_LOGS.pop()

    prompt = (
        f"Send an assignment alert.\n"
        f"Customer: {entry['contact_name']} ({entry['platform_id']})\n"
        f"Assigned Representative: {entry['agent_name']}"
    )
    assignment_notifier_agent.run(prompt)

def process_customer_summary(platform_id: str):
    data = CUSTOMER_BUFFERS.pop(platform_id, None)
    if not data or not data["messages"]:
        return

    full_conversation = "\n".join([f"- {m}" for m in data["messages"]])
    prompt = (
        f"Customer Name: {data['contact_name']}\n"
        f"Customer Phone: {platform_id}\n"
        f"Messages Received:\n{full_conversation}\n\n"
        f"Summarize the inquiry according to instructions."
    )
    message_summary_agent.run(prompt)

# --- Routes (Handles both / and /webhook) ---
@app.route("/", methods=["GET", "POST"])
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return render_template_string(
            HTML_TEMPLATE,
            logs=ASSIGNMENT_LOGS,
            agent=root_agent,
            supervisor=SUPERVISOR_NUMBER
        )

    data = request.get_json(silent=True) or {}
    event_type = data.get("webhook_event_type") or data.get("type") or "unknown"
    contact_name = data.get("contact_name") or "Unknown Customer"
    platform_id = data.get("platform_id") or data.get("from") or "Unknown"
    agent_name = data.get("agent_name") or "Unassigned"
    status = data.get("status") or "assigned"

    if event_type == "chat_assigned" and platform_id != "Unknown":
        now = time.time()
        with BUFFER_LOCK:
            PENDING_ASSIGNMENTS[platform_id] = {
                "trigger_epoch": now,
                "contact_name": contact_name,
                "platform_id": platform_id,
                "agent_name": agent_name,
                "status": status
            }
        threading.Thread(target=process_settled_assignment, args=(platform_id, now), daemon=True).start()
        return jsonify({"status": "buffering_assignment"}), 200

    if event_type in ["incoming_message", "message", "message_received"]:
        text_body = data.get("text") or data.get("message_body", {}).get("text", {}).get("body") or data.get("message", "")
        if text_body and platform_id != "Unknown":
            if platform_id not in CUSTOMER_BUFFERS:
                CUSTOMER_BUFFERS[platform_id] = {"contact_name": contact_name, "messages": [], "timer": None}
            entry = CUSTOMER_BUFFERS[platform_id]
            entry["messages"].append(text_body)
            if entry["timer"]:
                entry["timer"].cancel()
            if len(entry["messages"]) >= 4:
                process_customer_summary(platform_id)
            else:
                t = threading.Timer(20.0, process_customer_summary, args=[platform_id])
                entry["timer"] = t
                t.daemon = True
                t.start()
        return jsonify({"status": "buffering_message"}), 200

    return jsonify({"status": "received"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
