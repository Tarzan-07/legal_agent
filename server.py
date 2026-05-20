"""
FastAPI server implementation.

Endpoints -
    POST - /upload - receive one or more invoice files
    GET - /invoices - list all stored invoices
    GET - /health - liveness check
"""

import logging
import shutil
import tempfile
import os

from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from supabase import Client, create_client

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

supabase: Client = create_client(supabase_url=SUPABASE_URL, supabase_key=SUPABASE_KEY)
FRONTEND_DIR = Path(__file__).parent / "frontend"
app.mount("/static",  StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/", include_in_schema=False)
async def serve_index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))

@app.get("/health")
async def health_check():
    return {'status': 'ok'}

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

            results.append({
                "status": "success",
                "path": file_path,
                "public_url": public_url
            })

        return {'results': results}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Upload to supabase failed: {str(e)}"
        )