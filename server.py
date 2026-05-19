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
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles,
from pydantic import BaseModel

app = FastAPI(title="Invoice Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*']
)

FRONTEND_DIR = Path(__file__).parent / "frontend"
app.mount("/static",  StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/", include_in_schema=False)
async def serve_index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))

@app.get("/health")
async def health_check():
    return {'status': 'ok'}

