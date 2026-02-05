from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app import models
from backend.app.services.jobs import enqueue_job

router = APIRouter()

@router.post("/artifacts/{artifact_id}/discover")
def run_discovery(artifact_id: int, db: Session = Depends(get_db)):
    a = db.get(models.Artifact, artifact_id)
    if not a:
        raise HTTPException(status_code=404, detail="artifact not found")
    enqueue_job(db, artifact_id, "extract_discovery")
    return {"ok": True, "artifact_id": artifact_id}
