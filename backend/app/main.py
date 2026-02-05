# backend/app/main.py
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend.app.db import init_db

# For worker processing of jobs
import subprocess
import sys
import signal

app = FastAPI(
    title="Powertown MVP",
    version="0.1.0",
    description="Minimal internal platform to capture and review multimodal building observations.",
)

# Templates
templates = Jinja2Templates(directory="backend/app/templates")

# ---- Ensure local storage dirs exist ----
uploads_dir = Path("data/uploads")
uploads_dir.mkdir(parents=True, exist_ok=True)

artifacts_dir = Path("data/artifacts")
artifacts_dir.mkdir(parents=True, exist_ok=True)

static_dir = Path("backend/app/static")
static_dir.mkdir(parents=True, exist_ok=True)

# ---- Static mounts ----
# IMPORTANT:
# - /uploads is for observation media (legacy)
# - /artifact-files is for the new generalized artifact store
# We must NOT mount StaticFiles on /artifacts because /artifacts is the API router prefix.
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")
app.mount("/artifact-files", StaticFiles(directory=str(artifacts_dir)), name="artifact-files")
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ---- CORS (MVP-friendly) ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    # Create tables if they don't exist (MVP convenience)
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


# ---- Route wiring ----
from backend.app.routes import artifacts, buildings, export, parks, search, ui
from backend.app.routes.ui_artifacts import router as ui_artifacts_router

# Core REST-ish APIs
app.include_router(parks.router, prefix="/industrial-parks", tags=["industrial-parks"])
app.include_router(buildings.router, prefix="/buildings", tags=["buildings"])
app.include_router(artifacts.router, prefix="/artifacts", tags=["artifacts"])
app.include_router(search.router, prefix="/search", tags=["search"])
app.include_router(export.router, prefix="/export", tags=["export"])

# UI (HTML)
app.include_router(ui.router, tags=["ui"])
app.include_router(ui_artifacts_router, tags=["ui"])

_worker_process: subprocess.Popen | None = None

@app.on_event("startup")
def start_worker():
    global _worker_process

    # Only start worker in the *actual* server process, not the reloader
    if os.environ.get("UVICORN_RELOAD") == "true":
        # This is the reloader process; skip
        return

    print("Starting background worker process...")

    _worker_process = subprocess.Popen(
        [sys.executable, "-m", "backend.scripts.worker"],
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=os.environ.copy(),
    )

@app.on_event("shutdown")
def stop_worker():
    global _worker_process
    if _worker_process and _worker_process.poll() is None:
        print("Stopping background worker...")
        _worker_process.terminate()
