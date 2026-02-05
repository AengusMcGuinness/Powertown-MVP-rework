from __future__ import annotations

from collections import defaultdict

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, Query
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_
from sqlalchemy import func

from backend.app import models
from backend.app.db import get_db
from backend.app.services.scoring_cache import get_or_compute_building_score
from backend.app.services.storage import build_artifact_path, to_artifact_url

import zipfile
from pathlib import Path
import io



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
def review_park(
    park_id: int,
    request: Request,
    status: Optional[str] = None,
    q: Optional[str] = Query(default=None),
    all_buildings: int = Query(default=0),
    all_artifacts: int = Query(default=0),
    db: Session = Depends(get_db),
):
    park = db.get(models.IndustrialPark, park_id)
    if not park:
        raise HTTPException(status_code=404, detail="site not found")

    # --- Limits (default top 10) ---
    BUILDINGS_LIMIT = 10
    ARTIFACTS_LIMIT = 10
    show_all_buildings = bool(all_buildings)
    show_all_artifacts = bool(all_artifacts)

    q_norm = (q or "").strip()
    q_like = f"%{q_norm}%" if q_norm else None

    # --- Buildings query ---
    bq = db.query(models.Building).filter(models.Building.industrial_park_id == park_id)
    if status:
        bq = bq.filter(models.Building.status == status)

    if q_norm:
        # lightweight filtering: name/address
        bq = bq.filter(
            or_(
                models.Building.name.ilike(q_like),
                models.Building.address.ilike(q_like),
            )
        )

    buildings_total = bq.count()

    # Choose which buildings to display
    if show_all_buildings:
        buildings = bq.order_by(models.Building.id.desc()).all()
    else:
        buildings = bq.order_by(models.Building.id.desc()).limit(BUILDINGS_LIMIT).all()

    buildings_shown = len(buildings)

    # Build cards (score + artifact counts)
    building_cards = []
    building_ids = [b.id for b in buildings]

    # Count artifacts per building efficiently (only for displayed buildings)
    artifact_counts = {}
    if building_ids:
        rows = (
            db.query(models.Artifact.building_id, func.count(models.Artifact.id))
            .filter(models.Artifact.building_id.in_(building_ids))
            .group_by(models.Artifact.building_id)
            .all()
        )
        artifact_counts = {bid: cnt for bid, cnt in rows}

    for b in buildings:
        score = get_or_compute_building_score(db, b.id)
        building_cards.append(
            {
                "building": b,
                "score": score,
                "artifact_count": int(artifact_counts.get(b.id, 0)),
            }
        )

    # Top candidates: compute from ALL matching buildings (not just displayed) so it's meaningful
    # If you want "top candidates among displayed only", change this to building_cards.
    top_candidates = []
    if buildings_total > 0:
        # Pull candidate set to score:
        # - if show_all_buildings or q is set, we've already got the set (buildings)
        # - otherwise we should score the full park to find top candidates
        if show_all_buildings or q_norm:
            candidate_buildings = buildings
        else:
            candidate_buildings = (
                db.query(models.Building)
                .filter(models.Building.industrial_park_id == park_id)
                .order_by(models.Building.id.desc())
                .all()
            )

        candidate_cards = []
        # artifact counts for candidates (optional; not needed for top scoring)
        for b in candidate_buildings:
            score = get_or_compute_building_score(db, b.id)
            candidate_cards.append({"building": b, "score": score, "artifact_count": 0})

        top_candidates = sorted(candidate_cards, key=lambda c: c["score"].score, reverse=True)[:5]

    # building lookup for artifacts list display
    # Use *all* buildings in the park for name lookup so artifacts link correctly.
    all_bldgs = (
        db.query(models.Building)
        .filter(models.Building.industrial_park_id == park_id)
        .all()
    )
    building_by_id = {b.id: b for b in all_bldgs}
    all_ids = list(building_by_id.keys())

    # --- Artifacts query (park or buildings in park) ---
    aq = db.query(models.Artifact).filter(
        or_(
            models.Artifact.industrial_park_id == park_id,
            models.Artifact.building_id.in_(all_ids) if all_ids else False,
        )
    )

    if q_norm:
        # lightweight artifact filtering: filename; (optionally) text_content
        aq = aq.filter(
            or_(
                models.Artifact.original_filename.ilike(q_like),
                models.Artifact.text_content.ilike(q_like),
            )
        )

    artifacts_total = aq.count()

    if show_all_artifacts:
        recent_artifacts = aq.order_by(models.Artifact.created_at.desc()).all()
    else:
        recent_artifacts = aq.order_by(models.Artifact.created_at.desc()).limit(ARTIFACTS_LIMIT).all()

    artifacts_shown = len(recent_artifacts)

    return templates.TemplateResponse(
        "review_park.html",
        {
            "request": request,
            "park": park,
            "q": q_norm or None,
            "all_buildings": show_all_buildings,
            "all_artifacts": show_all_artifacts,
            "buildings_total": int(buildings_total),
            "buildings_shown": int(buildings_shown),
            "artifacts_total": int(artifacts_total),
            "artifacts_shown": int(artifacts_shown),
            "building_cards": building_cards,
            "top_candidates": top_candidates,
            "recent_artifacts": recent_artifacts,
            "building_by_id": building_by_id,
        },
    )

def _safe_zip_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = (info.filename or "").replace("\\", "/").lstrip("/")
        # zip-slip protection
        if ".." in name.split("/"):
            continue
        members.append(info)
    return members

@router.get("/review/buildings/{building_id}")
def review_building(building_id: int, request: Request, db: Session = Depends(get_db)):
    building = db.get(models.Building, building_id)
    if not building:
        raise HTTPException(status_code=404, detail="building not found")

    # Artifacts (newest first)
    artifacts = (
        db.query(models.Artifact)
        .filter(models.Artifact.building_id == building_id)
        .order_by(models.Artifact.created_at.desc(), models.Artifact.id.desc())
        .all()
    )
    artifact_ids = [a.id for a in artifacts]

    # Score (your existing cache + compute path)
    score = get_or_compute_building_score(db, building_id)

    # ---- Claims: per-artifact counts + total ----
    claim_counts_by_artifact: dict[int, int] = {}
    total_claims = 0
    if artifact_ids:
        rows = (
            db.query(models.Claim.artifact_id, func.count(models.Claim.id))
            .filter(models.Claim.artifact_id.in_(artifact_ids))
            .group_by(models.Claim.artifact_id)
            .all()
        )
        claim_counts_by_artifact = {aid: int(cnt) for (aid, cnt) in rows}
        total_claims = int(sum(claim_counts_by_artifact.values()))

    # ---- Text segments: total across artifacts in this building ----
    total_segments = 0
    if artifact_ids:
        total_segments = (
            db.query(func.count(models.ArtifactTextSegment.id))
            .filter(models.ArtifactTextSegment.artifact_id.in_(artifact_ids))
            .scalar()
        ) or 0
        total_segments = int(total_segments)

    # ---- Recent extracted text snippets (for quick triage) ----
    # Pull last 5 segments across this building’s artifacts
    recent_text_snippets: list[dict[str, Any]] = []
    if artifact_ids:
        seg_rows = (
            db.query(
                models.ArtifactTextSegment.artifact_id,
                models.ArtifactTextSegment.text,
                models.ArtifactTextSegment.source_ref,
                models.ArtifactTextSegment.created_at,
            )
            .filter(models.ArtifactTextSegment.artifact_id.in_(artifact_ids))
            .order_by(models.ArtifactTextSegment.created_at.desc(), models.ArtifactTextSegment.id.desc())
            .limit(5)
            .all()
        )
        recent_text_snippets = [
            {
                "artifact_id": r.artifact_id,
                "text": r.text or "",
                "source_ref": r.source_ref,
                "created_at": r.created_at,
            }
            for r in seg_rows
        ]

    return templates.TemplateResponse(
        "review_building.html",
        {
            "request": request,
            "building": building,
            "artifacts": artifacts,
            "score": score,
            # new template extras
            "claim_counts_by_artifact": claim_counts_by_artifact,
            "claim_counts": {"total": total_claims},
            "segment_counts": {"total": total_segments},
            "recent_text_snippets": recent_text_snippets,
        },
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
    park_id: Optional[int] = Form(None),
    park_name: Optional[str] = Form(None),
    park_location: Optional[str] = Form(None),

    building_name: str = Form(...),
    building_address: Optional[str] = Form(None),

    note_text: Optional[str] = Form(None),

    files: List[UploadFile] = File(default=[]),
    zip_file: Optional[UploadFile] = File(default=None),

    db: Session = Depends(get_db),
):
    # --- choose/create park ---
    park: Optional[models.IndustrialPark] = None
    if park_id:
        park = db.get(models.IndustrialPark, int(park_id))
        if not park:
            raise HTTPException(status_code=404, detail="site not found")
    else:
        pn = (park_name or "").strip()
        if not pn:
            raise HTTPException(status_code=400, detail="provide park_id or park_name")
        park = models.IndustrialPark(name=pn, location=(park_location or "").strip() or None)
        db.add(park)
        db.commit()
        db.refresh(park)

    # --- create building ---
    building = models.Building(
        industrial_park_id=park.id,
        name=building_name.strip(),
        address=(building_address or "").strip() or None,
    )
    db.add(building)
    db.commit()
    db.refresh(building)

    # --- optional note as a text artifact ---
    if note_text and note_text.strip():
        a = models.Artifact(
            industrial_park_id=park.id,
            building_id=building.id,
            kind="text",
            mime_type="text/plain",
            original_filename=None,
            storage_path=None,
            text_content=note_text,
            status="uploaded",
        )
        db.add(a)
        db.commit()
        db.refresh(a)
        enqueue_job(db, a.id, "extract_text")

    # --- helper to create a file artifact from bytes ---
    def _guess_kind(mime: Optional[str], filename: str) -> str:
        m = (mime or "").lower()
        fn = (filename or "").lower()
        if m == "application/pdf" or fn.endswith(".pdf"):
            return "pdf"
        if m.startswith("image/"):
            return "image"
        if m.startswith("audio/"):
            return "audio"
        if m.startswith("video/"):
            return "video"
        return "file"

    async def _create_file_artifact(filename: str, content_type: Optional[str], blob: bytes):
        artifact = models.Artifact(
            industrial_park_id=park.id,
            building_id=building.id,
            kind=_guess_kind(content_type, filename),
            mime_type=content_type,
            original_filename=filename,
            storage_path="PENDING",
            status="uploaded",
        )
        db.add(artifact)
        db.commit()
        db.refresh(artifact)

        path = build_artifact_path(artifact.id, filename)
        path.write_bytes(blob)
        artifact.storage_path = to_artifact_url(path)

        db.add(artifact)
        db.commit()
        db.refresh(artifact)

        enqueue_job(db, artifact.id, "extract_text")

    # --- direct files ---
    for f in files or []:
        if not f or not f.filename:
            continue
        blob = await f.read()
        await f.close()
        if blob:
            await _create_file_artifact(f.filename, f.content_type, blob)

    # --- zip upload (optional) ---
    if zip_file and zip_file.filename:
        if not zip_file.filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="zip_file must be a .zip")

        zip_blob = await zip_file.read()
        await zip_file.close()

        # Basic size guard (tune as needed)
        if len(zip_blob) > 200 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="zip too large (max 200MB)")

        with zipfile.ZipFile(io.BytesIO(zip_blob)) as zf:
            members = _safe_zip_members(zf)

            # Guard: max number of files
            if len(members) > 300:
                raise HTTPException(status_code=400, detail="zip contains too many files (max 300)")

            for info in members:
                name = info.filename.replace("\\", "/").lstrip("/")
                # Skip hidden/system files
                if name.split("/")[-1].startswith("."):
                    continue
                data = zf.read(info)
                if not data:
                    continue
                # Content-type unknown from zip; guess by extension
                await _create_file_artifact(Path(name).name, None, data)

    return RedirectResponse(url=f"/review/buildings/{building.id}", status_code=HTTP_303_SEE_OTHER)

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


def _make_snippet(text: str, q: str, radius: int = 90) -> str:
    """
    Returns a short HTML snippet with <mark>highlight</mark>.
    Safe enough for MVP: we escape the original text then insert marks
    by operating on lowercase match positions.
    """
    if not text:
        return ""
    q = (q or "").strip()
    if not q:
        return html.escape(text[: 2 * radius])

    low = text.lower()
    qlow = q.lower()
    idx = low.find(qlow)
    if idx < 0:
        return html.escape(text[: 2 * radius])

    start = max(0, idx - radius)
    end = min(len(text), idx + len(q) + radius)
    chunk = text[start:end]

    # Escape first, then mark by locating in escaped text is hard;
    # instead we do a simple safe approach: escape chunks and then
    # replace escaped query occurrences case-insensitively using a scan.
    escaped = html.escape(chunk)

    # Best-effort marking: find in lowercased chunk (not escaped),
    # then slice original chunk and escape pieces separately.
    pre = html.escape(chunk[: idx - start])
    mid = html.escape(chunk[idx - start : idx - start + len(q)])
    post = html.escape(chunk[idx - start + len(q) :])

    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{pre}<mark>{mid}</mark>{post}{suffix}"


# --- UI Search (fixed) ---
@router.get("/ui/search")
def ui_search(
    request: Request,
    q: str = "",
    mode: str = "kw",       # kept for future (nl vs kw)
    building_id: str = "",  # allow empty string
    park_id: str = "",      # allow empty string
    limit: int = 60,
    db: Session = Depends(get_db),
):
    q = (q or "").strip()
    limit = max(10, min(int(limit), 200))

    bid = _clean_int(building_id)
    pid = _clean_int(park_id)

    results = {
        "artifact_matches": [],   # artifacts matched by filename/metadata
        "claim_matches": [],      # individual claim hits
        "text_groups": [],        # grouped text matches by artifact
    }

    if not q:
        return templates.TemplateResponse(
            "search.html",
            {
                "request": request,
                "q": q,
                "mode": mode,
                "building_id": bid,
                "park_id": pid,
                "results": results,
            },
        )

    like = f"%{q}%"

    # ---- Base artifact scope (optional filters) ----
    artifact_scope = db.query(models.Artifact)
    if bid is not None:
        artifact_scope = artifact_scope.filter(models.Artifact.building_id == bid)
    if pid is not None:
        artifact_scope = artifact_scope.filter(models.Artifact.industrial_park_id == pid)

    scoped_ids = [row[0] for row in artifact_scope.with_entities(models.Artifact.id).all()]
    # If no artifacts match filters, keep empty scope early
    if (bid is not None or pid is not None) and not scoped_ids:
        return templates.TemplateResponse(
            "search.html",
            {
                "request": request,
                "q": q,
                "mode": mode,
                "building_id": bid,
                "park_id": pid,
                "results": results,
            },
        )

    # ---- 1) Artifact metadata matches ----
    aq = db.query(models.Artifact)
    if scoped_ids:
        aq = aq.filter(models.Artifact.id.in_(scoped_ids))
    aq = aq.filter(
        or_(
            models.Artifact.original_filename.ilike(like),
            models.Artifact.kind.ilike(like),
            models.Artifact.mime_type.ilike(like),
            models.Artifact.text_content.ilike(like),
        )
    ).order_by(models.Artifact.created_at.desc()).limit(25)

    results["artifact_matches"] = list(aq.all())

    # ---- 2) Claim matches (show top N by confidence) ----
    cq = db.query(models.Claim)
    if scoped_ids:
        cq = cq.filter(models.Claim.artifact_id.in_(scoped_ids))
    cq = cq.filter(
        or_(
            models.Claim.field_key.ilike(like),
            models.Claim.value_json.ilike(like),
            models.Claim.unit.ilike(like),
        )
    ).order_by(models.Claim.confidence.desc()).limit(40)

    claim_rows = list(cq.all())
    # Map artifacts for display
    claim_artifacts = {}
    if claim_rows:
        aids = sorted({c.artifact_id for c in claim_rows})
        for a in db.query(models.Artifact).filter(models.Artifact.id.in_(aids)).all():
            claim_artifacts[a.id] = a

    results["claim_matches"] = [
        {"claim": c, "artifact": claim_artifacts.get(c.artifact_id)}
        for c in claim_rows
    ]

    # ---- 3) Text segment matches (grouped by artifact, top N snippets each) ----
    tq = db.query(models.ArtifactTextSegment)
    if scoped_ids:
        tq = tq.filter(models.ArtifactTextSegment.artifact_id.in_(scoped_ids))
    tq = tq.filter(models.ArtifactTextSegment.text.ilike(like)).order_by(
        models.ArtifactTextSegment.artifact_id.asc(),
        models.ArtifactTextSegment.segment_index.asc(),
    ).limit(limit)

    segs = list(tq.all())

    # Load referenced artifacts
    seg_artifacts = {}
    if segs:
        aids = sorted({s.artifact_id for s in segs})
        for a in db.query(models.Artifact).filter(models.Artifact.id.in_(aids)).all():
            seg_artifacts[a.id] = a

    grouped: dict[int, list[models.ArtifactTextSegment]] = defaultdict(list)
    for s in segs:
        grouped[s.artifact_id].append(s)

    # Build groups with top 3 snippets per artifact
    text_groups = []
    for aid, seg_list in grouped.items():
        a = seg_artifacts.get(aid)
        if not a:
            continue

        # Keep first few segments for that artifact (already ordered by seg_index)
        top = seg_list[:3]
        matches = []
        for s in top:
            matches.append(
                {
                    "segment_index": s.segment_index,  # used only for deep-link anchor
                    "snippet_html": _make_snippet(s.text, q),
                }
            )

        text_groups.append(
            {
                "artifact": a,
                "matches": matches,
                "more_count": max(0, len(seg_list) - len(top)),
            }
        )

    # Sort groups by recency of artifact
    text_groups.sort(key=lambda g: (g["artifact"].created_at or 0), reverse=True)
    results["text_groups"] = text_groups

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "q": q,
            "mode": mode,
            "building_id": bid,
            "park_id": pid,
            "results": results,
        },
    )

# Keep old link alive: /search -> /ui/search
@router.get("/search")
def old_search_redirect(q: str = ""):
    if q:
        return RedirectResponse(url=f"/ui/search?q={q}", status_code=307)
    return RedirectResponse(url="/ui/search", status_code=307)
