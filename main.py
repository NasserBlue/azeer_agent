import os
import json
import logging
import threading
import time
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template_string
import requests
from google.adk.agents import Agent
from google import genai

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# --- Configuration & Credentials ---
SUPERVISOR_NUMBER = "966509708034"
DEFAULT_TEMPLATE_NAME = "welcome03"
AZEER_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhZG1pbiI6dHJ1ZSwiaHR0cHM6Ly9oYXN1cmEuaW8vand0L2NsYWltcyI6eyJ4LWF2Yy1hcGlrZXktaWQiOiI3MzBlMDhiMi00MGQzLTRlMmMtYjA3NS1hOGIyYjhhNDEwOWEiLCJ4LWF2Yy1hcGlrZXktc2NvcGUiOiJpbnNlcnQiLCJ4LWF2Yy1ob3N0LWlkIjoiZjNjZWZhMGUtYmQyYi00NjY0LWE5MzUtZmY5ZTc4MDY3MGRmIiwieC1hdmMtcGxhdGZvcm0taWQiOiJuYXNzZXJqLjdAaG90bWFpbC5jb20iLCJ4LWF2Yy1wbGF0Zm9ybS10eXBlIjoiYXZvY2FkbyIsIngtaGFzdXJhLWFsbG93ZWQtcm9sZXMiOlsiYWRtaW4iLCJzdXBlcmFkbWluIl0sIngtaGFzdXJhLWJ1c2luZXNzLWlkIjoiMGRlODhlZjEtNmM1Ny00NTZhLWE0M2QtN2E4MjQwYWUzMDE3IiwieC1oYXN1cmEtZGVmYXVsdC1yb2xlIjoiYWRtaW4iLCJ4LWhhc3VyYS1wcm9maWxlLWlkIjoiNDExIiwieC1oYXN1cmEtdXNlci1pZCI6IjQxMSJ9LCJpYXQiOjE3OTM5NjQ4MjAsImlzcyI6ImF2b2NhZG8tY29yZSIsIm5hbWUiOiJOYXNzZXIgQWxKdWJhaWx5Iiwic3ViIjoiNDExIn0.69BPEVYFd-NqIRgcbVxwYApEF0J0wYDmU89up8vlsgE"
AZEER_SEND_URL = "https://api.mottasl.ai/v1/message/send"

# --- In-Memory Stores ---
ASSIGNMENT_LOGS = []
PENDING_ASSIGNMENTS = {}
CUSTOMER_MESSAGE_BUFFERS = {}
BUFFER_LOCK = threading.Lock()
MESSAGE_TIMEOUT_SECONDS = 20

# Initialize direct GenAI fallback client
genai_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# --- Tools (Callable by Agents) ---
def send_whatsapp_text(recipient_phone: str, message: str) -> dict:
    """Sends normal free-form text via Azeer when the 24-hour chat session is open."""
    headers = {
        "Authorization": f"Bearer {AZEER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "to": recipient_phone,
        "type": "text",
        "text": {"body": message}
    }
