# 🎙️ Voice Automation Agent

Speak an automation in Hindi, English or Hinglish and get a ready-to-import **n8n workflow**.

**Example:** *"When a new lead email arrives, reply to it and log it in Google Sheets"* → n8n workflow with `Gmail Trigger → Reply to Email → Add Row in Google Sheets`.

## How it works

```
Voice → faster-whisper (speech to text) → Groq LLM (intent as JSON) → n8n workflow JSON
```

1. **Record** your voice in the browser (`/app`)
2. **Transcribe** locally with `faster-whisper` (free, runs on CPU)
3. **Understand** the request with an LLM that returns a strict JSON: trigger + ordered list of actions
4. **Generate** a valid n8n workflow JSON, then paste it into the n8n canvas (Ctrl+V)

## Tech stack

FastAPI · faster-whisper · Groq API · n8n · Vanilla JS (MediaRecorder)

## Supported today

| Triggers | Actions |
|---|---|
| Schedule (cron) | Reply to email (Gmail) |
| Gmail new email | Send email (SMTP) |
| Webhook | Append row to Google Sheets |
| Manual | Telegram message |

Anything else becomes a placeholder `TODO` node.

## Run locally

```bash
git clone https://github.com/sandeepguptajmd/voice-automation-agent.git
cd voice-automation-agent
python -m venv venv
venv\Scripts\activate        # Windows (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
```

Create a `.env` file (see `.env.example`):

```
GROQ_API_KEY=your_groq_api_key_here
```

Get a free key at [console.groq.com](https://console.groq.com), then start the server:

```bash
uvicorn main:app --reload
```

Open **http://127.0.0.1:8000/app**, press the mic button and speak.
API docs are at **/docs**.

## API endpoints

| Endpoint | What it does |
|---|---|
| `POST /transcribe` | Audio → text |
| `POST /parse` | Text → intent JSON |
| `POST /workflow` | Text → n8n workflow JSON |
| `POST /voice-to-workflow` | Audio → text + intent + workflow |
| `POST /voice-to-workflow-only` | Audio → n8n workflow JSON (paste-ready) |

## Limitations

- Workflows are imported by pasting JSON. The n8n Cloud free trial has no public API, so auto-push is not supported yet.
- Credentials (Gmail, Google Sheets, SMTP) must be connected inside n8n after import.
- Only the triggers and actions listed above are generated.

## Roadmap

- More node types (HTTP Request, Code, LLM)
- Auto-create workflows through the n8n API (self-hosted)
- Multi-language UI