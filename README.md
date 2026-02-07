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

### 1. Clone the repo and create a virtual environment


```bash
cd Powertown-MVP-rework
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
python -m uvicorn backend.app.main:app --reload
```
Open in your browser:
- Review UI: http://127.0.0.1:8000/review
- Artifact gallery: http://127.0.0.1:8000/ui/artifacts
- Search: http://127.0.0.1:8000/ui/search
- API docs: http://127.0.0.1:8000/docs

## Future Work
The current system is intentionally local and minimal, but its architecture is designed to evolve toward a production-scale ingestion and decision-support platform. The following areas represent the most important next steps.

### Natural-language and semantic search
Search is currently implemented as keyword and substring matching over filenames, extracted text, and structured claims. While simple and transparent, this approach does not capture semantic intent and requires users to know which terms to search for.

Future versions would introduce semantic search using embeddings over extracted text segments and claims, enabling natural-language queries such as “sites with high industrial load and available electrical infrastructure.” A hybrid approach (BM25 + vector search) would preserve deterministic keyword behavior while improving recall and ranking quality. The existing text segmentation and claim models are already structured in a way that supports embedding-based indexing without schema changes.

### LLM integration and reliability
Structured and discovery extraction currently rely on local LLMs via `llama.cpp`. While useful for offline experimentation, this path is slow, hardware-dependent, and fragile for large documents. Some extraction paths are currently unreliable or partially broken due to model and context limitations.

Future iterations would introduce a clean abstraction layer for multiple LLM backends, including hosted providers such as OpenAI. This would allow routing high-value or long-context jobs to hosted models while retaining local models for lightweight or offline use. Moving LLM calls out of the critical path would significantly improve throughput, observability, and failure handling.

### Scalable artifact storage
Artifacts are currently stored on the local filesystem and served directly by the FastAPI application. This simplifies development but does not scale across machines or deployments.

A production-ready version would migrate artifact storage to an object store such as Amazon S3 (or compatible systems like MinIO). Artifacts would be addressed by content hash or stable IDs, with signed URLs for access. This change would:
	- decouple storage from compute
	- enable horizontal scaling of workers and web servers
	- allow safe handling of large media and PDFs
	- simplify backups and lifecycle management

The current storage abstraction is intentionally narrow to make this transition straightforward.

### Background processing and job execution
The worker system is currently a single-process, polling-based executor backed by SQLite. This is sufficient for an MVP but limits throughput and resilience.

Future work would include:
	- moving job state to a centralized database or queue (e.g. Postgres + advisory locks, or a message queue)
	- parallel job execution
	- better job visibility and metrics
	- explicit backoff and retry policies per processor

These changes become necessary once document volume or extraction complexity increases.

### Query-time reasoning and evidence synthesis
The system currently extracts evidence but does not synthesize answers across artifacts at query time. Future versions could support natural-language questions answered using extracted claims and text segments, with explicit citations back to source artifacts. This would turn Powertown from an ingestion and review tool into a lightweight decision-support system.

### Summary
The MVP prioritizes clarity, traceability, and local reproducibility. Future work focuses on semantic understanding, scalable storage, reliable LLM integration, and production-grade job execution. Most current limitations are deliberate engineering tradeoffs rather than fundamental constraints, and the existing architecture is designed to support these upgrades without major rewrites.


