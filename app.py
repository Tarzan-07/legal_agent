"""
FastAPI server implementation.

Endpoints -
    POST - /upload - receive one or more invoice files
    GET - /health - liveness check
"""

import logging
import shutil
import tempfile
import os
import logging
import pika
import json

from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from supabase import Client, create_client

from doc_tools import process_and_graph_doc

logging.basicConfig(logging.INFO)
logger = logging.getLogger(__name__)

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

supabase: Client = create_client(supabase_url=SUPABASE_URL, supabase_key=SUPABASE_KEY)
FRONTEND_DIR = Path(__file__).parent / "frontend"
app.mount("/static",  StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/", include_in_schema=False)
async def serve_index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))

@app.get("/health")
async def health_check():
    return {'status': 'ok'}


def publish_to_queue(payload: dict):
    """Establishes a safe connection with rabbit mq and safely pushes a persistent task message."""

    connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
    channel = connection.channel()

    # To ensure a queue survives system crashes or daemon restarts.
    channel.queue_declare(queue=QUEUE_NAME, durable=True)

    channel.basic_publish(
        exchange='',
        routing_key=QUEUE_NAME,
        body=json.dumps(payload),
        properties=pika.BasicProperties(
            delivery_mode=pika.DeliveryMode.Persistent
        )
    )
    connection.close()
# Upload functionality

@app.post("/upload")
async def upload_invoices(files: list[UploadFile] = File(...)):
    """Accept one or more invoice files, run the full ingestion pipeline."""
    try:
        results = []
        ALLOWED_TEXT_EXT = {".pdf", ".doc", ".docx"}
        ALLOWED_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tiff"}

        for file in files:
            file_ext = Path(file.filename).suffix.lower()
            
            if file_ext in ALLOWED_TEXT_EXT: 
                file_path = f"text/{file.filename}"
                
            elif file_ext in ALLOWED_IMG_EXT:
                file_path = f"image/{file.filename}"
            
            else:
                results.append({
                    "status": "failed",
                    "filename": file.filename,
                    "error": f"Extension '{file_ext}' not supported."
                })
                continue
    
            file_content = await file.read()
            response = supabase.storage.from_(BUCKET_NAME).upload(
                path=file_path,
                file=file_content,
                file_options={"content-type": file.content_type}
            )

            public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_path)

            task_payload = {
                "file_path": file_path,
                "path": file_path,
                "public_url": public_url
            }
            
            publish_to_queue(task_payload)
            logger.info(f"Queued message task for file: {file.filename}")

            results.append({
                "status": "queued",
                "filename": file.filename,
                "public_url": public_url
            })

        return {"results": results}

        # logger.info(f"Successfully stored the file in supabase !")
        # return {'results': results}



    except Exception as e:
        logger.error(f"Upload and processing scheduling failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline scheduling failed: {str(e)}"
        )