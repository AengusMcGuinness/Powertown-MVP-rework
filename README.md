# Powertown Prospecting MVP

A lightweight internal tool for collecting, organizing, and reviewing field observations about commercial and industrial buildings, with the goal of identifying strong battery storage candidates.

This project is designed as an MVP to support Powertown’s on-the-ground prospecting workflow: turning messy, multimodal field notes into structured, decision-ready building dossiers.

---

## Problem Context

Powertown teams collect real-world data in industrial parks: notes, photos, conversations, business cards, and informal observations. This information is inherently messy, subjective, and gathered asynchronously by different people.

The challenge is not data collection alone — it’s **organizing and synthesizing that information** so the team can:
- review what was learned in the field,
- compare buildings within an industrial park,
- and prioritize which sites are strong candidates for battery deployment.

This MVP focuses on that core workflow.

---

## Design Philosophy

- **Append-only observations**  
  Field data should never be overwritten. Observations are timestamped, attributed, and additive.

- **Multimodal by default**  
  Notes, photos, and other media are first-class inputs, not afterthoughts.

- **Transparent heuristics over black boxes**  
  Battery readiness is computed using a simple, explainable scoring function rather than ML.

- **Optimize for speed and clarity**  
  This is a small internal tool meant to be easy to run, easy to inspect, and easy to extend.

---

## Features

- REST API for:
  - Creating buildings
  - Adding observations
  - Uploading media linked to observations
- Relational data model (SQLite)
- Local file storage for media
- Aggregated “building dossier” views
- Simple battery readiness scoring
- Seed data to demonstrate a realistic industrial park workflow

---

## Tech Stack

- **Backend:** FastAPI (Python)
- **Database:** SQLite
- **ORM:** SQLAlchemy
- **File storage:** Local filesystem
- **API docs:** Auto-generated OpenAPI (Swagger UI)

---

## Quickstart

### 1. Clone the repo
```bash
git clone git@github.com:AengusMcGuinness/powertown-mvp.git
cd powertown-mvp
```
### 2. Create and activate a virtual environment
```
python -m venv .venv
source .venv/bin/activate
```
### 3. Install dependencies
```
pip install -r requirements.txt
```
### 4. Initialize the database (one-time)
```
python -m backend.scripts.init_db
```
This will create a local SQLite database at: `backend/app/app.db`
### 5. Run the server
```
uvicorn backend.app.main:app --reload
```
# Demo (Recommended)

Run the full demo locally with seeded data:

```bash
python -m backend.scripts.init_db
python -m backend.scripts.seed_demo --reset
uvicorn backend.app.main:app --reload
```
Then open:
- Review home: http://127.0.0.1:8000/review
- Capture form: http://127.0.0.1:8000/capture

This demo includes:
- 1 industrial park
- 8 buildings
- multiple observations per building
- attached media
- readiness scores that respond to observation content

## Battery Readiness Scoring

Each building is assigned a simple, transparent readiness score (0–100) based on observed signals across all notes:

Signals include:
- **Load indicators** (e.g., manufacturing, cold storage, HVAC)
- **Electrical infrastructure** (e.g., transformers, switchgear, substations)
- **On-site generation** (e.g., solar)
- **Siting space** (e.g., large lots, parking, yards)
- **Contacts identified** (e.g., facilities manager, business card)

The score is intentionally heuristic and explainable, designed to support human review rather than replace it.

# Bulk Offline Import & Demo Data

Field prospecting often happens offline or asynchronously. To support this workflow, the MVP includes a bulk offline import pipeline that allows teams to upload structured field data after the fact, with or without associated media.

## Bulk Import Options

The application supports two bulk import modes:

- ZIP import (with media) 
  - Upload a single .zip file containing:
  - a manifest.csv describing parks, buildings, and observations
  - any referenced media files (photos, audio, business cards)
- CSV-only import (no media)
  - Upload a standalone manifest.csv to create parks, buildings, and observations without attachments.

Both flows deduplicate parks and buildings, create append-only observations, attach media safely, and generate a detailed import report summarizing what was created or skipped.

## Demo Data

The repository includes reproducible demo files to test both bulk import paths:
```
demo_data/
├── with_media/
│   ├── manifest.csv
│   ├── transformer.jpg
│   ├── loading_dock.jpg
│   ├── audio_note.m4a
│   └── demo_with_media.zip
└── csv_only/
    ├── manifest.csv
    └── demo_csv_only.zip
```
## Try it locally

### 1.  Start the server
```
uvicorn backend.app.main:app --reload
```
### 2. Open
```
http://127.0.0.1:8000/bulk
```
### 3. Upload
Either `demo_data/with_media/demo_with_media.zip` or `demo_data/with_media/demo_with_media.zip`
After upload, the app displays an Import Report detailing:
- rows imported vs skipped
- observations created
- media files attached or missing
- affected industrial parks (with links)

## Features

- Server-rendered web UI for field capture and review
- Append-only observations with timestamping
- Media upload and inline rendering (photos, audio, cards)
- Park- and building-level review pages
- Explainable battery readiness scoring
- CSV export for downstream mapping and analysis
- SQLite-backed relational data model


