from datetime import datetime
from sqlalchemy.orm import Session
from backend.app import models

def enqueue_job(db: Session, artifact_id: int, job_type: str) -> models.ProcessingJob:
    job = models.ProcessingJob(
        artifact_id=artifact_id,
        job_type=job_type,
        status="queued",
        updated_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
