"""
FastAPI server implementation.

Endpoints -
    POST - /upload          - receive one or more invoice files (scoped to a session)
    GET  - /health          - liveness check
    POST - /sessions        - create a new chat session
    GET  - /sessions        - list all sessions
    GET  - /sessions/{id}   - get full session detail (messages + files)
    POST - /chat            - send a chat message (scoped to a session)
"""

import logging
import shutil
import tempfile
import os
import logging
import pika
import json
import uuid
import magic
import mimetypes

from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from supabase import Client, create_client

# from doc_tools import process_document

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("Loading env variables...")
load_dotenv()

app = FastAPI(title="Invoice Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*']
)


SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
BUCKET_NAME = os.getenv('BUCKET_NAME')
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
QUEUE_NAME = "document_processing_queue"

logger.info(f"SUPABASE_URL = {repr(SUPABASE_URL)}")
logger.info(f"BUCKET_NAME = {repr(BUCKET_NAME)}")
logger.info(f"SUPABASE_KEY exists = {SUPABASE_KEY is not None}")

supabase: Client = create_client(supabase_url=SUPABASE_URL, supabase_key=SUPABASE_KEY)
FRONTEND_DIR = Path(__file__).parent / "frontend"
app.mount("/static",  StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# ── In-memory session store ───────────────────────────────────────────────────
# Structure: { session_id: { "id", "created_at", "messages": [], "files": [] } }
sessions: dict = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_session(session_id: str) -> dict:
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return sessions[session_id]


# ── Static / index ────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def serve_index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/health")
async def health_check():
    return {'status': 'ok'}


# ── Session endpoints ─────────────────────────────────────────────────────────

@app.post("/sessions")
async def create_session():
    """Create a new chat session and return its ID."""
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "id": session_id,
        "created_at": _now_iso(),
        "messages": [],
        "files": []
    }
    logger.info(f"Created session: {session_id}")
    return {"session_id": session_id}


@app.get("/sessions")
async def list_sessions():
    """List all sessions with a summary (id, date, file count, last message)."""
    result = []
    for s in sessions.values():
        last_msg = None
        if s["messages"]:
            last = s["messages"][-1]
            last_msg = {"role": last["role"], "text": last["text"][:80]}
        result.append({
            "id": s["id"],
            "created_at": s["created_at"],
            "file_count": len(s["files"]),
            "message_count": len(s["messages"]),
            "last_message": last_msg
        })
    # Newest first
    result.sort(key=lambda x: x["created_at"], reverse=True)
    return {"sessions": result}


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Return full session detail including all messages and uploaded files."""
    s = _get_session(session_id)
    return {"session": s}


# ── Queue helper ──────────────────────────────────────────────────────────────

def publish_to_queue(payload: dict):
    """Establishes a safe connection with RabbitMQ and pushes a persistent task message."""
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
    channel = connection.channel()

    queue_arguments = {
        'x-queue-type': 'quorum',
        'x-delivery-limit': 5
    }

    channel.queue_declare(queue=QUEUE_NAME, durable=True, arguments=queue_arguments)

    channel.basic_publish(
        exchange='',
        routing_key=QUEUE_NAME,
        body=json.dumps(payload),
        properties=pika.BasicProperties(
            delivery_mode=pika.DeliveryMode.Persistent
        )
    )
    connection.close()


# ── Upload endpoint ───────────────────────────────────────────────────────────

@app.post("/upload")
async def upload_invoices(
    files: list[UploadFile] = File(...),
    session_id: Optional[str] = Form(None)
):
    """Accept one or more invoice files scoped to a session."""
    try:
        results = []
        ALLOWED_TEXT_EXT = {".pdf", ".doc", ".docx"}
        ALLOWED_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tiff"}

        for file in files:
            file_read = await file.read(2048)
            await file.seek(0)
            mime_type = magic.from_buffer(file_read, mime=True)
            file_ext = mimetypes.guess_extension(mime_type)

            if file_ext == '.jpe':
                file_ext = '.jpg'

            unique_id = str(uuid.uuid4())

            file_content = await file.read()
            if file_ext in ALLOWED_TEXT_EXT:
                file_path = f"text/{unique_id}_{file.filename}"

            elif file_ext in ALLOWED_IMG_EXT:
                file_path = f"image/{unique_id}_{file.filename}"

            else:
                results.append({
                    "status": "failed",
                    "success": False,
                    "filename": file.filename,
                    "error": f"Extension '{file_ext}' not supported."
                })
                continue

            response = supabase.storage.from_(BUCKET_NAME).upload(
                path=file_path,
                file=file_content,
                file_options={"content-type": file.content_type}
            )

            task_payload = {
                "file_path": file_path,
                "file_ext": file_ext,
                "original_filename": file.filename,
                "session_id": session_id
            }

            publish_to_queue(task_payload)
            logger.info(f"Queued message task for file: {file.filename} (session={session_id})")

            # Attach file record to the session
            file_record = {
                "id": unique_id,
                "filename": file.filename,
                "file_path": file_path,
                "file_ext": file_ext,
                "uploaded_at": _now_iso()
            }
            if session_id and session_id in sessions:
                sessions[session_id]["files"].append(file_record)

            results.append({
                "status": "queued",
                "success": True,
                "filename": file.filename,
                "file": file.filename,
                "name": file.filename,
                "original_filename": file.filename
            })

        return {"results": results}

    except Exception as e:
        logger.error(f"Upload and processing scheduling failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline scheduling failed: {str(e)}"
        )


# ── Chat endpoint ─────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


@app.post("/chat")
async def chat(req: ChatRequest):
    """Handle a chat message scoped to a session."""
    # Persist user message
    if req.session_id and req.session_id in sessions:
        sessions[req.session_id]["messages"].append({
            "role": "user",
            "text": req.message,
            "timestamp": _now_iso()
        })

    # TODO: wire to actual LLM / agent
    reply = f"(Agent placeholder) You said: {req.message}"

    # Persist agent reply
    if req.session_id and req.session_id in sessions:
        sessions[req.session_id]["messages"].append({
            "role": "agent",
            "text": reply,
            "timestamp": _now_iso()
        })

    return {"reply": reply}