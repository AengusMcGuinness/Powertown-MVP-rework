from sqlalchemy.orm import Session
from backend.app import models
from backend.app.processors.pdf import extract_text_from_pdf
from backend.app.processors.image import ocr_image
from backend.app.processors.text import normalize_text_artifact
from backend.app.processors.structured import extract_claims_from_text
from backend.app.processors.audio import transcribe_audio_video

def run_job(db: Session, job: models.ProcessingJob) -> None:
    artifact = db.query(models.Artifact).get(job.artifact_id)
    if artifact is None:
        raise RuntimeError("artifact not found")
    if job.job_type == "extract_text":
        if artifact.kind == "text":
            normalize_text_artifact(db, artifact)
        elif artifact.kind in ("pdf", "file") and (artifact.mime_type or "").lower() == "application/pdf":
            extract_text_from_pdf(db, artifact)
        elif artifact.kind == "image":
            ocr_image(db, artifact)
        elif artifact.kind in ("audio", "video"):
            transcribe_audio_video(db, artifact)
        else:
            return

        from backend.app.services.jobs import enqueue_job
        enqueue_job(db, artifact.id, "extract_structured")

    elif job.job_type == "extract_structured":
        extract_claims_from_text(db, artifact)

    elif job.job_type == "extract_discovery":
        from backend.app.processors.discovery import extract_discovery_facts
        extract_discovery_facts(db, artifact)


    else:
        raise RuntimeError(f"unknown job_type: {job.job_type}")
