from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.db import get_db
from backend.app.services.scoring_cache import get_or_compute_building_score
from backend.app.services.storage import build_artifact_path, to_artifact_url

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


def _infer_kind_from_upload(u: UploadFile) -> str:
    c = (u.content_type or "").lower()
    name = (u.filename or "").lower()
    if c.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return "image"
    if c.startswith("audio/") or name.endswith((".mp3", ".wav", ".m4a", ".aac", ".ogg")):
        return "audio"
    if c == "application/pdf" or name.endswith(".pdf"):
        return "pdf"
    return "file"


@router.get("/")
def root():
    return RedirectResponse(url="/review")


@router.get("/review")
def review_home(request: Request, db: Session = Depends(get_db)):
    parks = db.query(models.IndustrialPark).order_by(models.IndustrialPark.id.desc()).all()

    park_cards = []
    for p in parks:
        buildings = db.query(models.Building).filter(models.Building.industrial_park_id == p.id).all()
        building_ids = [b.id for b in buildings]

        q = db.query(models.Artifact).filter(models.Artifact.industrial_park_id == p.id)
        if building_ids:
            q = q.union_all(db.query(models.Artifact).filter(models.Artifact.building_id.in_(building_ids)))
        artifacts = q.order_by(models.Artifact.created_at.desc()).all()

        last_activity_at = artifacts[0].created_at if artifacts else None
        park_cards.append(
            {
                "park": p,
                "building_count": len(buildings),
                "artifact_count": len(artifacts),
                "last_activity_at": last_activity_at,
            }
        )

    return templates.TemplateResponse("review_home.html", {"request": request, "park_cards": park_cards})


@router.get("/review/parks/{park_id}")
def review_park(park_id: int, request: Request, status: Optional[str] = None, db: Session = Depends(get_db)):
    park = db.get(models.IndustrialPark, park_id)
    if not park:
        raise HTTPException(status_code=404, detail="site not found")

    bq = db.query(models.Building).filter(models.Building.industrial_park_id == park_id)
    if status:
        bq = bq.filter(models.Building.status == status)
    buildings = bq.order_by(models.Building.id.desc()).all()

    building_cards = []
    for b in buildings:
        score = get_or_compute_building_score(db, b.id)
        artifact_count = db.query(models.Artifact).filter(models.Artifact.building_id == b.id).count()
        building_cards.append({"building": b, "score": score, "artifact_count": artifact_count})

    top_candidates = sorted(building_cards, key=lambda c: c["score"].score, reverse=True)[:5]

    building_by_id = {b.id: b for b in buildings}
    ids = list(building_by_id.keys())
    aq = db.query(models.Artifact).filter(
        (models.Artifact.industrial_park_id == park_id)
        | (models.Artifact.building_id.in_(ids) if ids else False)
    )
    recent_artifacts = aq.order_by(models.Artifact.created_at.desc()).limit(15).all()

    return templates.TemplateResponse(
        "review_park.html",
        {
            "request": request,
            "park": park,
            "building_cards": building_cards,
            "top_candidates": top_candidates,
            "recent_artifacts": recent_artifacts,
            "building_by_id": building_by_id,
        },
    )


@router.get("/review/buildings/{building_id}")
def review_building(building_id: int, request: Request, db: Session = Depends(get_db)):
    building = db.get(models.Building, building_id)
    if not building:
        raise HTTPException(status_code=404, detail="building not found")

    artifacts = (
        db.query(models.Artifact)
        .filter(models.Artifact.building_id == building_id)
        .order_by(models.Artifact.created_at.desc())
        .all()
    )
    score = get_or_compute_building_score(db, building_id)

    return templates.TemplateResponse(
        "review_building.html",
        {"request": request, "building": building, "artifacts": artifacts, "score": score},
    )


@router.post("/review/buildings/{building_id}/status")
def set_building_status(building_id: int, status: str = Form(...), db: Session = Depends(get_db)):
    b = db.get(models.Building, building_id)
    if not b:
        raise HTTPException(status_code=404, detail="building not found")
    status = (status or "").strip().lower()
    if status not in {"new", "reviewed", "shortlisted"}:
        raise HTTPException(status_code=400, detail="invalid status")
    b.status = status
    db.add(b)
    db.commit()
    return RedirectResponse(url=f"/review/buildings/{building_id}", status_code=303)


@router.get("/capture")
def capture_form(request: Request, db: Session = Depends(get_db)):
    parks = db.query(models.IndustrialPark).order_by(models.IndustrialPark.id.desc()).all()
    return templates.TemplateResponse("capture.html", {"request": request, "parks": parks})


@router.post("/capture")
async def capture_submit(
    request: Request,
    park_id: str = Form(""),
    park_name: str = Form(""),
    park_location: str = Form(""),
    building_name: str = Form(...),
    building_address: str = Form(""),
    note_text: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    pid = _clean_int(park_id)
    park = db.get(models.IndustrialPark, pid) if pid else None
    if not park:
        if not park_name.strip():
            raise HTTPException(status_code=400, detail="provide park_id or park_name")
        park = models.IndustrialPark(name=park_name.strip(), location=park_location.strip() or None, created_at=datetime.utcnow())
        db.add(park)
        db.commit()
        db.refresh(park)

    building = models.Building(
        industrial_park_id=park.id,
        name=building_name.strip(),
        address=building_address.strip() or None,
        created_at=datetime.utcnow(),
        status="new",
    )
    db.add(building)
    db.commit()
    db.refresh(building)

    if note_text and note_text.strip():
        a = models.Artifact(
            industrial_park_id=park.id,
            building_id=building.id,
            kind="text",
            mime_type="text/plain",
            original_filename=None,
            storage_path=None,
            text_content=note_text.strip(),
            status="uploaded",
        )
        db.add(a)
        db.commit()

    for f in files or []:
        if not f.filename:
            continue
        kind = _infer_kind_from_upload(f)
        artifact = models.Artifact(
            industrial_park_id=park.id,
            building_id=building.id,
            kind=kind,
            mime_type=f.content_type,
            original_filename=f.filename,
            storage_path="PENDING",
            status="uploaded",
        )
        db.add(artifact)
        db.commit()
        db.refresh(artifact)

        try:
            contents = await f.read()
            path = build_artifact_path(artifact.id, f.filename)
            path.write_bytes(contents)
        finally:
            await f.close()

        artifact.storage_path = to_artifact_url(path)
        artifact.bytes_size = len(contents)
        db.add(artifact)
        db.commit()

    return RedirectResponse(url=f"/review/buildings/{building.id}", status_code=303)


# --- UI Search (fixed) ---
@router.get("/ui/search")
def ui_search(
    request: Request,
    q: str = "",
    mode: str = "kw",           # accept but currently ignore
    building_id: str = "",      # accept empty string safely
    db: Session = Depends(get_db),
):
    bid = _clean_int(building_id)
    results = None
    if (q or "").strip():
        from backend.app.routes.search import search as api_search
        results = api_search(q=q.strip(), building_id=bid, limit=50, db=db)

    return templates.TemplateResponse(
        "search.html",
        {"request": request, "q": q, "results": results, "mode": mode, "building_id": bid},
    )


# Keep old link alive: /search -> /ui/search
@router.get("/search")
def old_search_redirect(q: str = ""):
    if q:
        return RedirectResponse(url=f"/ui/search?q={q}", status_code=307)
    return RedirectResponse(url="/ui/search", status_code=307)
