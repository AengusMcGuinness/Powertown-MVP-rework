from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.db import get_db
from backend.app.services.jobs import enqueue_job

from fastapi import Form

templates = Jinja2Templates(directory="backend/app/templates")
router = APIRouter()


def _clean_int(s: str | None) -> Optional[int]:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return int(s)
    except Exception:
        return None


@router.get("/ui/artifacts")
def artifact_gallery(
    request: Request,
    q: str = "",
    park_id: str = "",
    building_id: str = "",
    kind: str = "",
    status: str = "",
    page: int = 1,
    page_size: int = 30,
    db: Session = Depends(get_db),
):
    page = max(1, page)
    page_size = max(5, min(page_size, 100))
    offset = (page - 1) * page_size

    pid = _clean_int(park_id)
    bid = _clean_int(building_id)

    aq = db.query(models.Artifact)

    if pid is not None:
        aq = aq.filter(models.Artifact.industrial_park_id == pid)
    if bid is not None:
        aq = aq.filter(models.Artifact.building_id == bid)
    if kind.strip():
        aq = aq.filter(models.Artifact.kind == kind.strip().lower())
    if status.strip():
        aq = aq.filter(models.Artifact.status == status.strip().lower())

    q_stripped = (q or "").strip()
    if q_stripped:
        qlike = f"%{q_stripped}%"

        claim_match = (
            db.query(models.Claim.artifact_id)
            .filter(or_(models.Claim.field_key.ilike(qlike), models.Claim.value_json.ilike(qlike)))
            .subquery()
        )
        text_match = (
            db.query(models.ArtifactTextSegment.artifact_id)
            .filter(models.ArtifactTextSegment.text.ilike(qlike))
            .subquery()
        )

        aq = aq.filter(
            or_(
                models.Artifact.original_filename.ilike(qlike),
                models.Artifact.kind.ilike(qlike),
                models.Artifact.mime_type.ilike(qlike),
                models.Artifact.text_content.ilike(qlike),
                models.Artifact.id.in_(claim_match),
                models.Artifact.id.in_(text_match),
            )
        )

    total = aq.count()
    artifacts = (
        aq.order_by(models.Artifact.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    parks = db.query(models.IndustrialPark).order_by(models.IndustrialPark.name.asc()).all()

    page_count = (total + page_size - 1) // page_size

    # claim count per artifact (cheap enough for MVP scale)
    claim_counts: dict[int, int] = {}
    if artifacts:
        ids = [a.id for a in artifacts]
        rows = db.query(models.Claim.artifact_id).filter(models.Claim.artifact_id.in_(ids)).all()
        for (aid,) in rows:
            claim_counts[aid] = claim_counts.get(aid, 0) + 1

    return templates.TemplateResponse(
        "artifact_gallery.html",
        {
            "request": request,
            "artifacts": artifacts,
            "parks": parks,
            "claim_counts": claim_counts,
            "q": q_stripped,
            "park_id": pid,
            "building_id": bid,
            "kind": kind,
            "status": status,
            "page": page,
            "page_size": page_size,
            "total": total,
            "page_count": page_count,
        },
    )


@router.get("/ui/artifacts/{artifact_id}")
def artifact_detail(artifact_id: int, request: Request, db: Session = Depends(get_db)):
    a = db.get(models.Artifact, artifact_id)
    if not a:
        raise HTTPException(status_code=404, detail="artifact not found")

    segments = (
        db.query(models.ArtifactTextSegment)
        .filter(models.ArtifactTextSegment.artifact_id == artifact_id)
        .order_by(models.ArtifactTextSegment.segment_index.asc())
        .all()
    )

    claims = (
        db.query(models.Claim)
        .filter(models.Claim.artifact_id == artifact_id)
        .order_by(models.Claim.confidence.desc())
        .all()
    )

    jobs = (
        db.query(models.ProcessingJob)
        .filter(models.ProcessingJob.artifact_id == artifact_id)
        .order_by(models.ProcessingJob.id.desc())
        .all()
    )

    building = db.get(models.Building, a.building_id) if a.building_id else None
    park = db.get(models.IndustrialPark, a.industrial_park_id) if a.industrial_park_id else None

    return templates.TemplateResponse(
        "artifact_detail.html",
        {
            "request": request,
            "artifact": a,
            "segments": segments,
            "claims": claims,
            "jobs": jobs,
            "building": building,
            "park": park,
        },
    )


@router.post("/ui/artifacts/{artifact_id}/discover")
def ui_run_discovery(artifact_id: int, db: Session = Depends(get_db)):
    a = db.get(models.Artifact, artifact_id)
    if not a:
        raise HTTPException(status_code=404, detail="artifact not found")

    enqueue_job(db, artifact_id, "extract_discovery")
    return RedirectResponse(url=f"/ui/artifacts/{artifact_id}", status_code=303)

@router.post("/ui/artifacts/{artifact_id}/retry-failed")
def ui_retry_failed_jobs(artifact_id: int, db: Session = Depends(get_db)):
    """
    For this artifact: look at latest jobs; if any are failed, enqueue the same job_type again.
    We do NOT edit old job rows; we add new queued jobs (history stays intact).
    """
    a = db.get(models.Artifact, artifact_id)
    if not a:
        raise HTTPException(status_code=404, detail="artifact not found")

    failed_types = [
        jt for (jt,) in (
            db.query(models.ProcessingJob.job_type)
            .filter(models.ProcessingJob.artifact_id == artifact_id)
            .filter(models.ProcessingJob.status == "failed")
            .distinct()
            .all()
        )
    ]

    for jt in failed_types:
        enqueue_job(db, artifact_id, jt)

    return RedirectResponse(url=f"/ui/artifacts/{artifact_id}", status_code=303)


@router.post("/ui/artifacts/{artifact_id}/retry")
def ui_retry_job_type(
    artifact_id: int,
    job_type: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Retry a specific job_type for this artifact (even if it didn't fail).
    """
    a = db.get(models.Artifact, artifact_id)
    if not a:
        raise HTTPException(status_code=404, detail="artifact not found")

    jt = (job_type or "").strip()
    if not jt:
        raise HTTPException(status_code=400, detail="job_type required")

    enqueue_job(db, artifact_id, jt)
    return RedirectResponse(url=f"/ui/artifacts/{artifact_id}", status_code=303)


@router.post("/ui/artifacts/{artifact_id}/rerun-pipeline")
def ui_rerun_pipeline(artifact_id: int, db: Session = Depends(get_db)):
    """
    Convenience: rerun the common pipeline. Adjust job types to match your worker registry.
    """
    a = db.get(models.Artifact, artifact_id)
    if not a:
        raise HTTPException(status_code=404, detail="artifact not found")

    # Order doesn't strictly matter if your worker just pulls queued jobs,
    # but it's nice to enqueue in a sane sequence.
    enqueue_job(db, artifact_id, "extract_text")
    enqueue_job(db, artifact_id, "extract_structured")
    enqueue_job(db, artifact_id, "extract_discovery")

    return RedirectResponse(url=f"/ui/artifacts/{artifact_id}", status_code=303)
