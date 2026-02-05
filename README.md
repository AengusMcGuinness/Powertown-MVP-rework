# Powertown MVP  
**Local Artifact Ingestion, Search, and Structured Extraction for Energy Infrastructure**

Powertown MVP is a local-first web application for collecting, reviewing, and extracting structured information from power- and energy-related documents (PDFs, images, and notes).

It is designed to support workflows such as:
- utility interconnection review,
- site feasibility analysis,
- and early-stage infrastructure prospecting.

The system combines a FastAPI web server, a background processing worker, local file storage, and optional local LLMs (via `llama.cpp`) to turn unstructured documents into searchable, structured data.

---

## Core Capabilities

### Artifact ingestion
- Upload PDFs, images, or text notes
- Attach artifacts to buildings and industrial parks
- Files stored locally on disk (no cloud dependencies)

### Text extraction
- Embedded text extraction for PDFs
- OCR fallback for scanned documents or images
- Extracted text stored in segmented form

### Background processing
- Database-backed job queue
- Asynchronous worker processes jobs:
  - text extraction
  - structured extraction
  - discovery extraction
- Retryable and inspectable job history

### Structured extraction
- Schema-based claim extraction (key–value facts)
- Confidence scores per claim
- Designed for power / energy documents (manuals, policies, studies)

### Discovery mode
- Open-ended extraction for unknown or novel document fields
- Produces flexible `disc:*` claims
- Useful for manuals, regulations, and unfamiliar PDFs

### Review & search UI
- Artifact gallery view
- Artifact detail pages (file, text, claims, jobs)
- Keyword search across:
  - filenames
  - extracted text
  - claims
- Manual re-run of failed jobs from the UI

## Architecture Overview
Static files are served locally:
- Artifacts: `/artifact-files/*`
- Uploads: `/uploads/*`

---

## Requirements

- Python 3.10+ (3.11 recommended)
- macOS or Linux
- SQLite (default) or Postgres
- Optional: `llama-cpp-python` + GGUF model for LLM-based extraction

---

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
If `LLAMA_GGUF_PATH` is not set, structured and discovery extraction will be skipped or fail gracefully.

### 3. Initialize the database
```
python -c "from backend.app.db import init_db; init_db()"
```
Verify:
```
sqlite3 demo.db ".tables"
```

### 4. Seed demo data
```
python -m backend.scripts.seed_demo
```
This creates:
- one demo industrial park
- one or more demo buildings

### 5. Run the server
```
uvicorn backend.app.main:app --reload
```
Open in your browser:
- Review UI: http://127.0.0.1:8000/review
- Artifact gallery: http://127.0.0.1:8000/ui/artifacts
- Search: http://127.0.0.1:8000/ui/search
- API docs: http://127.0.0.1:8000/docs
