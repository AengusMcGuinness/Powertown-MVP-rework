# backend/app/processors/registry.py
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app import models
from backend.app.processors import pdf, image, audio, structured, discovery


def run_job(db: Session, job: models.ProcessingJob) -> None:
    artifact = db.get(models.Artifact, job.artifact_id)
    if not artifact:
        raise RuntimeError(f"artifact not found: {job.artifact_id}")

    jt = (job.job_type or "").strip().lower()
    kind = (artifact.kind or "file").strip().lower()
    filename = (artifact.original_filename or "").lower()
    mime = (artifact.mime_type or "").lower()

    print(f"[registry] run_job job_id={job.id} type={jt} artifact_id={artifact.id}")
    print(f"[registry] artifact kind={kind} mime={mime or None} filename={artifact.original_filename!r}")

    if jt == "extract_text":
        _dispatch_extract_text(db, artifact, kind=kind, filename=filename, mime=mime)
        return

    if jt == "transcribe_audio":
        print("[registry] -> audio.transcribe_audio_video")
        audio.transcribe_audio_video(db, artifact)
        return

    if jt == "extract_structured":
        print("[registry] -> structured.extract_claims_from_text")
        structured.extract_claims_from_text(db, artifact)
        return

    if jt == "extract_discovery":
        print("[registry] -> discovery.extract_discovery_facts")
        discovery.extract_discovery_facts(db, artifact)
        return

    raise RuntimeError(f"unknown job type: {job.job_type!r}")


def _dispatch_extract_text(
    db: Session,
    artifact: models.Artifact,
    *,
    kind: str,
    filename: str,
    mime: str,
) -> None:
    # Route by kind/extension first (zip uploads often have mime=None)
    if kind == "pdf" or filename.endswith(".pdf") or mime == "application/pdf":
        print("[registry] -> pdf.extract_text_from_pdf")
        pdf.extract_text_from_pdf(db, artifact)
        return

    if kind in ("image", "photo") or filename.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")) or mime.startswith("image/"):
        print("[registry] -> image.ocr_image")
        image.ocr_image(db, artifact)
        return

    if kind in ("audio", "video") or filename.endswith((".mp3", ".wav", ".m4a", ".aac", ".ogg", ".mp4", ".mov")) or mime.startswith(("audio/", "video/")):
        print("[registry] -> audio.transcribe_audio_video")
        audio.transcribe_audio_video(db, artifact)
        return

    if kind == "text":
        print("[registry] -> inline: text artifact -> ArtifactTextSegment")
        _write_text_artifact_segment(db, artifact)
        return

    print(f"[registry] extract_text: unsupported kind={kind} filename={filename!r} mime={mime!r}; skipping")


def _write_text_artifact_segment(db: Session, artifact: models.Artifact) -> None:
    txt = (artifact.text_content or "").strip()
    if not txt:
        return

    db.query(models.ArtifactTextSegment).filter(
        models.ArtifactTextSegment.artifact_id == artifact.id
    ).delete(synchronize_session=False)

    db.add(
        models.ArtifactTextSegment(
            artifact_id=artifact.id,
            segment_index=0,
            text=txt,
            source_ref="text:note",
        )
    )
    db.commit()
