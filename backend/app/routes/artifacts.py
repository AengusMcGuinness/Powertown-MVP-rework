from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.db import get_db
from backend.app.schemas import ArtifactOut
from backend.app.services.storage import build_artifact_path, to_artifact_url

router = APIRouter()


def _sha256(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()


def _infer_kind(requested_kind: str, mime_type: Optional[str]) -> str:
    """
    If client leaves kind='file', infer a more specific kind from mime type so
    registry dispatch works (image -> OCR, pdf -> PDF extractor).
    """
    k = (requested_kind or "file").strip().lower()
    mt = (mime_type or "").strip().lower()

    if k and k != "file":
        return k

    if mt.startswith("image/"):
        return "image"
    if mt.startswith("application/pdf"):
        return "pdf"
    return "file"


@router.post("/upload", response_model=ArtifactOut)
async def upload_artifact(
    file: UploadFile = File(...),
    kind: str = Form("file"),
    industrial_park_id: Optional[int] = Form(None),
    building_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """
    Upload a generic artifact (file evidence) and optionally attach it to a park/site
    and/or building.

    Storage is local filesystem for MVP.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="missing filename")

    mt = (file.content_type or "").lower()
    kind_norm = kind.strip().lower() or "file"

    if kind_norm == "file":
        if mt.startswith("audio/"):
            kind_norm = "audio"
        elif mt.startswith("video/"):
            kind_norm = "video"
        elif mt == "application/pdf":
            kind_norm = "pdf"

    # Validate foreign keys if provided
    if industrial_park_id is not None and not db.get(models.IndustrialPark, industrial_park_id):
        raise HTTPException(status_code=404, detail="industrial_park not found")
    if building_id is not None and not db.get(models.Building, building_id):
        raise HTTPException(status_code=404, detail="building not found")

    # Require at least one association so artifacts don't float forever.
    if industrial_park_id is None and building_id is None:
        raise HTTPException(status_code=400, detail="must provide industrial_park_id or building_id")

    inferred_kind = _infer_kind(kind, file.content_type)

    # Create DB row first so we have an artifact_id for the storage folder
    artifact = models.Artifact(
        industrial_park_id=industrial_park_id,
        building_id=building_id,
        kind=inferred_kind,
        mime_type=file.content_type,
        original_filename=file.filename,
        storage_path="PENDING",
        status="uploaded",
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)

    # Save to disk + compute hash
    try:
        contents = await file.read()
        sha = _sha256(contents)
        path: Path = build_artifact_path(artifact.id, file.filename)
        path.write_bytes(contents)
    finally:
        await file.close()

    # Update DB with final storage path + metadata
    artifact.storage_path = to_artifact_url(path)
    artifact.bytes_size = len(contents)
    artifact.sha256 = sha
    db.add(artifact)
    db.commit()
    db.refresh(artifact)

    # Enqueue AFTER storage_path is set (prevents worker race on PENDING)
    from backend.app.services.jobs import enqueue_job
    enqueue_job(db, artifact.id, "extract_text")

    return artifact


@router.post("/text", response_model=ArtifactOut)
def create_text_artifact(
    text_content: str = Form(...),
    industrial_park_id: Optional[int] = Form(None),
    building_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """Create a text artifact (a note) attached to a site and/or building."""
    if industrial_park_id is None and building_id is None:
        raise HTTPException(status_code=400, detail="must provide industrial_park_id or building_id")

    if industrial_park_id is not None and not db.get(models.IndustrialPark, industrial_park_id):
        raise HTTPException(status_code=404, detail="industrial_park not found")
    if building_id is not None and not db.get(models.Building, building_id):
        raise HTTPException(status_code=404, detail="building not found")

    artifact = models.Artifact(
        industrial_park_id=industrial_park_id,
        building_id=building_id,
        kind="text",
        mime_type="text/plain",
        original_filename=None,
        storage_path=None,
        text_content=text_content,
        status="uploaded",
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)

    from backend.app.services.jobs import enqueue_job
    enqueue_job(db, artifact.id, "extract_text")

    return artifact


@router.get("/{artifact_id}", response_model=ArtifactOut)
def get_artifact(artifact_id: int, db: Session = Depends(get_db)):
    artifact = db.get(models.Artifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="artifact not found")
    return artifact


@router.get("", response_model=list[ArtifactOut])
def list_artifacts(
    industrial_park_id: Optional[int] = None,
    building_id: Optional[int] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    q = db.query(models.Artifact)
    if industrial_park_id is not None:
        q = q.filter(models.Artifact.industrial_park_id == industrial_park_id)
    if building_id is not None:
        q = q.filter(models.Artifact.building_id == building_id)
    q = q.order_by(models.Artifact.created_at.desc()).limit(max(1, min(limit, 1000)))
    return list(q.all())
