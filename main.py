import os
import re
import json
import uuid
import shutil

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse
from faster_whisper import WhisperModel
from groq import Groq
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="Voice Automation Agent")

whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
LLM_MODEL = "openai/gpt-oss-20b"

SYSTEM_PROMPT = """You convert a user's spoken automation request (Hindi, English or Hinglish)
into a JSON object describing an n8n workflow. Always reply with JSON only, using exactly this shape:

{
  "workflow_name": "short English name",
  "trigger": {
    "type": "schedule" | "gmail_new_email" | "webhook_event" | "manual",
    "schedule": "plain English schedule like 'every Monday 9am', or null",
    "cron": "5-field cron expression like '0 9 * * 1', or null",
    "description": "short English description of when this runs"
  },
  "actions": [
    {
      "type": "reply_email" | "send_email" | "google_sheets_append" | "send_telegram" | "other",
      "recipient": "who receives it, or null",
      "subject": "email subject if relevant, else null",
      "body": "short ready-to-send message text if relevant, else null",
      "description": "short English description of this step"
    }
  ]
}

Rules:
- Use trigger type "gmail_new_email" when the user wants something to happen when a new email arrives.
- Use "reply_email" when the user wants to reply to the sender of that email.
- Use "google_sheets_append" when the user wants data recorded or saved in a Google Sheet.
- List actions in the exact order the user described them. Include every step the user mentioned.
- Write all values in English. If something is not mentioned, use null."""


class TextIn(BaseModel):
    text: str


def transcribe_file(upload: UploadFile) -> str:
    temp_path = f"temp_{upload.filename}"
    try:
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(upload.file, f)
        segments, info = whisper_model.transcribe(
            temp_path,
            beam_size=5,
            initial_prompt="Hinglish: mujhe har Monday email bhejna hai, Google Sheet mein record karo, Telegram pe message bhejo, naya lead aaye.",
        )
        return " ".join(s.text for s in segments).strip()
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def parse_intent(text: str) -> dict:
    response = groq_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(response.choices[0].message.content)


def make_trigger(trigger: dict, name: str) -> dict:
    t = trigger.get("type")

    if t == "schedule":
        return {
            "parameters": {
                "rule": {
                    "interval": [
                        {
                            "field": "cronExpression",
                            "expression": trigger.get("cron") or "0 9 * * *",
                        }
                    ]
                }
            },
            "name": "Schedule Trigger",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [0, 0],
        }

    if t == "gmail_new_email":
        return {
            "parameters": {
                "pollTimes": {"item": [{"mode": "everyMinute"}]},
                "simple": True,
                "filters": {},
            },
            "name": "Gmail Trigger",
            "type": "n8n-nodes-base.gmailTrigger",
            "typeVersion": 1.2,
            "position": [0, 0],
        }

    if t == "webhook_event":
        path = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "voice-workflow"
        return {
            "parameters": {"httpMethod": "POST", "path": path},
            "name": "Webhook",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [0, 0],
            "webhookId": str(uuid.uuid4()),
        }

    return {
        "parameters": {},
        "name": "Manual Trigger",
        "type": "n8n-nodes-base.manualTrigger",
        "typeVersion": 1,
        "position": [0, 0],
    }


def make_action(action: dict, trigger_node: dict, x: int) -> dict:
    a_type = action.get("type")
    body = action.get("body") or action.get("description") or ""
    from_gmail = trigger_node["name"] == "Gmail Trigger"
    # Pichle node ke baad $json badal jata hai, isliye trigger se data seedha refer karte hain
    ref = "$('Gmail Trigger').item.json" if from_gmail else "$json"

    if a_type == "reply_email" and from_gmail:
        return {
            "parameters": {
                "resource": "message",
                "operation": "reply",
                "messageId": "={{ $('Gmail Trigger').item.json.id }}",
                "emailType": "text",
                "message": body,
                "options": {},
            },
            "name": "Reply to Email",
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
            "position": [x, 0],
        }

    if a_type in ("reply_email", "send_email"):
        return {
            "parameters": {
                "fromEmail": "you@example.com",
                "toEmail": "recipient@example.com",
                "subject": action.get("subject") or "Follow-up",
                "emailFormat": "text",
                "text": body,
            },
            "name": "Send Email",
            "type": "n8n-nodes-base.emailSend",
            "typeVersion": 2.1,
            "position": [x, 0],
        }

    if a_type == "google_sheets_append":
        return {
            "parameters": {
                "operation": "append",
                "documentId": {"__rl": True, "mode": "list", "value": ""},
                "sheetName": {"__rl": True, "mode": "list", "value": ""},
                "columns": {
                    "mappingMode": "defineBelow",
                    "value": {
                        "From": "={{ " + ref + ".From }}",
                        "Subject": "={{ " + ref + ".Subject }}",
                        "Message": "={{ " + ref + ".snippet }}",
                        "Received At": "={{ $now }}",
                    },
                    "matchingColumns": [],
                    "schema": [],
                },
                "options": {},
            },
            "name": "Add Row in Google Sheets",
            "type": "n8n-nodes-base.googleSheets",
            "typeVersion": 4.5,
            "position": [x, 0],
        }

    if a_type == "send_telegram":
        return {
            "parameters": {"chatId": "YOUR_CHAT_ID", "text": body},
            "name": "Send Telegram Message",
            "type": "n8n-nodes-base.telegram",
            "typeVersion": 1.2,
            "position": [x, 0],
        }

    return {
        "parameters": {},
        "name": f"TODO - {a_type}",
        "type": "n8n-nodes-base.noOp",
        "typeVersion": 1,
        "position": [x, 0],
    }


def build_workflow(intent: dict) -> dict:
    name = intent.get("workflow_name") or "Voice Workflow"
    trigger_node = make_trigger(intent.get("trigger") or {}, name)

    nodes = [trigger_node]
    used_names = {trigger_node["name"]}

    for i, action in enumerate(intent.get("actions") or [], start=1):
        node = make_action(action, trigger_node, x=300 * i)
        base_name, n = node["name"], 2
        while node["name"] in used_names:
            node["name"] = f"{base_name} {n}"
            n += 1
        used_names.add(node["name"])
        nodes.append(node)

    connections = {}
    for prev, nxt in zip(nodes, nodes[1:]):
        connections[prev["name"]] = {
            "main": [[{"node": nxt["name"], "type": "main", "index": 0}]]
        }

    return {
        "name": name,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
    }


@app.get("/")
def home():
    return {"message": "Voice Automation Agent chal raha hai!"}


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    return {"text": transcribe_file(audio)}


@app.post("/parse")
def parse(body: TextIn):
    return {"intent": parse_intent(body.text)}


@app.post("/voice-to-intent")
async def voice_to_intent(audio: UploadFile = File(...)):
    text = transcribe_file(audio)
    return {"text": text, "intent": parse_intent(text)}


@app.post("/workflow")
def workflow(body: TextIn):
    return build_workflow(parse_intent(body.text))


@app.post("/voice-to-workflow")
async def voice_to_workflow(audio: UploadFile = File(...)):
    text = transcribe_file(audio)
    intent = parse_intent(text)
    return {"text": text, "intent": intent, "workflow": build_workflow(intent)}


@app.post("/voice-to-workflow-only")
async def voice_to_workflow_only(audio: UploadFile = File(...)):
    text = transcribe_file(audio)
    return build_workflow(parse_intent(text))

@app.get("/app")
def web_app():
    return FileResponse("index.html")