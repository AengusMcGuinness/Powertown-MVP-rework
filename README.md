# Powertown MVP  
**Local Artifact Ingestion, Search, and Structured Extraction for Energy Infrastructure**

Powertown MVP is a local-first web application for collecting, reviewing, and extracting structured information from energy- and power-related evidence such as PDFs, images, audio/video walkthroughs, and field notes.

It is designed to support workflows such as:
- utility interconnection review,
- site feasibility analysis,
- and early-stage infrastructure prospecting.

The system combines a FastAPI web server, a background processing worker, local file storage, and optional local LLMs (via `llama.cpp`) to turn unstructured documents into searchable, structured data.

---

## Core Capabilities

### Artifact ingestion
- Upload PDFs, images, video, or text notes
- Attach artifacts to buildings and industrial parks
- Files stored locally on disk (no cloud dependencies)

### Text extraction
- Embedded text extraction for PDFs
- OCR fallback for scanned documents or images
- Extracted text stored in segmented form
- Transcription available for videos or audio files

### Background processing
- Database-backed job queue
- Asynchronous worker processes jobs:
  - text extraction
  - structured extraction
  - discovery extraction
- Retryable and inspectable job history

### Review & search UI
- Artifact gallery view
- Artifact detail pages (file, text, claims, jobs)
- Keyword search across:
  - filenames
  - extracted text
  - claims
- Manual re-run of failed jobs from the UI

---

## Requirements

- Python 3.10+ (3.11 recommended)
- macOS or Linux
- SQLite (default) or Postgres
- Optional: `llama-cpp-python` + GGUF model for LLM-based extraction
- Optional: `ffmpeg` for audio/video transcription


---
## External Dependencies
### 1.  ffmpeg
The worker uses ffmpeg to decode audio/video before transcription.

Install it first:

**macOS (Homebrew)**
```
brew install ffmpeg
```
**Linux Debian/Ubuntu**
```
sudo apt install ffmpeg
```
Verify:
```
ffmpeg -version
```
If ffmpeg is missing:
- audio/video jobs will fail or hang
- `extract_text` jobs may remain stuck in processing for audio/video files

### 2. LLaMA model

Powertown uses local LLMs via `llama.cpp`. You must download a GGUF model file yourself.

Example (recommended size for MVP):
- `Meta-Llama-3.1-8B-Instruct-Q5_K_M.gguf`

Without a GGUF model:
- structured extraction is an undefined operation
- discovery extraction is an undefined operation
- the rest of the app should still function

## Environment variables (.env explained)

Powertown is configured entirely via environment variables.

You can set them:
- in a `.env` file (recommended)
- or directly in your shell

How .env works:
- `.env` lives at the repo root
- it is loaded automatically by:
  * the server
  * the worker
  * variables defined there are visible to both processes
    
### Minimal .env (recommended)
Create a file named .env in the repo root:
```
DATABASE_URL=sqlite:///./demo.db
```
This tells both the server and worker:
- use SQLite
- store the DB in `demo.db` in the repo root

### Full .env with LLaMA enabled
```
DATABASE_URL=sqlite:///./demo.db

# Path to your GGUF model (REQUIRED for structured extraction)
LLAMA_GGUF_PATH=/absolute/path/to/Meta-Llama-3.1-8B-Instruct-Q5_K_M.gguf

# LLaMA performance tuning (safe defaults)
LLAMA_THREADS=8
LLAMA_N_CTX=4096
LLAMA_TEMPERATURE=0.1
LLAMA_MAX_TOKENS=700
```

## Quick Start (Local Tutorial)

### 1. Create and activate a virtual environment


```bash
cd powertown
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. Create a .env file in the repo root:
```bash
DATABASE_URL=sqlite:///./demo.db

# Optional (required for structured + discovery extraction)
LLAMA_GGUF_PATH=/absolute/path/to/model.gguf
LLAMA_THREADS=8
LLAMA_N_CTX=4096
LLAMA_TEMPERATURE=0.1
LLAMA_MAX_TOKENS=700
```

### 4. Seed demo data
```
python -m backend.scripts.seed_demo --reset
```
This creates:
- one demo industrial park
- one or more demo buildings
- uploads artifacts for each buildling

### 5. Run the server
```
uvicorn backend.app.main:app --reload
```
Open in your browser:
- Review UI: http://127.0.0.1:8000/review
- Artifact gallery: http://127.0.0.1:8000/ui/artifacts
- Search: http://127.0.0.1:8000/ui/search
- API docs: http://127.0.0.1:8000/docs

