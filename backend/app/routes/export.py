from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.db import get_db
from backend.app.services.scoring import score_building

router = APIRouter()


def _dt_iso(dt: Optional[datetime]) -> str:
    return dt.isoformat() if dt else ""


def _as_text(v) -> str:
    if v is None:
        return ""
    return str(v)


def _csv_response(output: io.StringIO, filename: str) -> Response:
    csv_bytes = output.getvalue().encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ----------------------------------------------------------------------
# 1) Building summaries (fixed)
# ----------------------------------------------------------------------
@router.get("/csv")
def export_building_summaries_csv(
    park_id: Optional[int] = Query(default=None, description="Filter by industrial park id"),
    db: Session = Depends(get_db),
):
    """
    Export one row per building, suitable for map/spreadsheet workflows.

    Includes:
      - park + building info
      - readiness score (from artifact_text_segments + note artifacts)
      - artifact counts by kind + last artifact time
      - claim count (claims joined via artifact -> building)
    """

    parks_by_id = {p.id: p for p in db.query(models.IndustrialPark).all()}

    bq = db.query(models.Building)
    if park_id is not None:
        bq = bq.filter(models.Building.industrial_park_id == park_id)
    buildings = bq.order_by(models.Building.industrial_park_id, models.Building.id).all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(
        [
            "park_id",
            "park_name",
            "park_location",
            "building_id",
            "building_name",
            "building_address",
            "readiness_score",
            "confidence",
            "top_drivers",
            "artifact_count",
            "text_count",
            "image_count",
            "pdf_count",
            "audio_count",
            "video_count",
            "last_artifact_at",
            "claim_count",
            "building_created_at",
        ]
    )

    building_ids = [b.id for b in buildings]
    if not building_ids:
        filename = (
            "powertown_building_export.csv"
            if park_id is None
            else f"powertown_building_export_park_{park_id}.csv"
        )
        return _csv_response(output, filename)

    a = models.Artifact

    # ✅ IMPORTANT FIX:
    # Use sqlalchemy.case (imported as case), NOT func.case.
    agg_rows = (
        db.query(
            a.building_id.label("building_id"),
            func.count(a.id).label("artifact_count"),
            func.sum(case((func.lower(a.kind) == "text", 1), else_=0)).label("text_count"),
            func.sum(case((func.lower(a.kind).in_(("image", "photo")), 1), else_=0)).label("image_count"),
            func.sum(case((func.lower(a.kind) == "pdf", 1), else_=0)).label("pdf_count"),
            func.sum(case((func.lower(a.kind) == "audio", 1), else_=0)).label("audio_count"),
            func.sum(case((func.lower(a.kind) == "video", 1), else_=0)).label("video_count"),
            func.max(a.created_at).label("last_artifact_at"),
        )
        .filter(a.building_id.in_(building_ids))
        .group_by(a.building_id)
        .all()
    )
    agg_by_building = {r.building_id: r for r in agg_rows}

    # Claim counts per building: claim -> artifact -> building
    c = models.Claim
    claim_rows = (
        db.query(
            a.building_id.label("building_id"),
            func.count(c.id).label("claim_count"),
        )
        .join(a, a.id == c.artifact_id)
        .filter(a.building_id.in_(building_ids))
        .group_by(a.building_id)
        .all()
    )
    claims_by_building = {r.building_id: int(r.claim_count or 0) for r in claim_rows}

    # Gather extracted text segments per building
    seg = models.ArtifactTextSegment
    seg_rows = (
        db.query(a.building_id, seg.text)
        .join(a, a.id == seg.artifact_id)
        .filter(a.building_id.in_(building_ids))
        .order_by(a.building_id.asc(), seg.segment_index.asc())
        .all()
    )

    texts_by_building: dict[int, list[str]] = {bid: [] for bid in building_ids}
    for bid, text in seg_rows:
        if text:
            texts_by_building[bid].append(text)

    # Also include note artifacts (text_content)
    note_rows = (
        db.query(a.building_id, a.text_content)
        .filter(a.building_id.in_(building_ids))
        .filter(func.lower(a.kind) == "text")
        .all()
    )
    for bid, text in note_rows:
        if text:
            texts_by_building[bid].append(text)

    for b in buildings:
        park = parks_by_id.get(b.industrial_park_id)
        agg = agg_by_building.get(b.id)

        building_texts = texts_by_building.get(b.id, [])
        score = score_building(building_texts)

        writer.writerow(
            [
                b.industrial_park_id,
                park.name if park else "",
                (park.location if park else "") or "",
                b.id,
                b.name,
                (b.address or "") if hasattr(b, "address") else "",
                getattr(score, "score", ""),
                getattr(score, "confidence", ""),
                "; ".join(getattr(score, "drivers", []) or []),
                int(getattr(agg, "artifact_count", 0) or 0) if agg else 0,
                int(getattr(agg, "text_count", 0) or 0) if agg else 0,
                int(getattr(agg, "image_count", 0) or 0) if agg else 0,
                int(getattr(agg, "pdf_count", 0) or 0) if agg else 0,
                int(getattr(agg, "audio_count", 0) or 0) if agg else 0,
                int(getattr(agg, "video_count", 0) or 0) if agg else 0,
                _dt_iso(getattr(agg, "last_artifact_at", None) if agg else None),
                int(claims_by_building.get(b.id, 0) or 0),
                _dt_iso(getattr(b, "created_at", None)),
            ]
        )

    filename = (
        "powertown_building_export.csv"
        if park_id is None
        else f"powertown_building_export_park_{park_id}.csv"
    )
    return _csv_response(output, filename)


# ----------------------------------------------------------------------
# 2) New export: artifacts index (one row per artifact)
# ----------------------------------------------------------------------
@router.get("/artifacts.csv")
def export_artifacts_csv(
    park_id: Optional[int] = Query(default=None),
    building_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Export one row per artifact (index of evidence).
    """
    a = models.Artifact
    b = models.Building
    p = models.IndustrialPark

    q = (
        db.query(
            a.id.label("artifact_id"),
            a.industrial_park_id,
            p.name.label("park_name"),
            a.building_id,
            b.name.label("building_name"),
            a.kind,
            a.mime_type,
            a.original_filename,
            a.storage_path,
            a.bytes_size,
            a.sha256,
            a.status,
            a.error_message,
            a.created_at,
        )
        .outerjoin(b, b.id == a.building_id)
        .outerjoin(p, p.id == a.industrial_park_id)
    )

    if park_id is not None:
        q = q.filter(a.industrial_park_id == park_id)
    if building_id is not None:
        q = q.filter(a.building_id == building_id)

    q = q.order_by(a.created_at.desc(), a.id.desc())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "artifact_id",
            "park_id",
            "park_name",
            "building_id",
            "building_name",
            "kind",
            "mime_type",
            "original_filename",
            "storage_path",
            "bytes_size",
            "sha256",
            "status",
            "error_message",
            "created_at",
        ]
    )

    for r in q.all():
        writer.writerow(
            [
                r.artifact_id,
                r.industrial_park_id,
                _as_text(r.park_name),
                r.building_id,
                _as_text(r.building_name),
                _as_text(r.kind),
                _as_text(r.mime_type),
                _as_text(r.original_filename),
                _as_text(r.storage_path),
                _as_text(r.bytes_size),
                _as_text(r.sha256),
                _as_text(r.status),
                _as_text(r.error_message),
                _dt_iso(r.created_at),
            ]
        )

    filename = "powertown_artifacts.csv"
    if building_id is not None:
        filename = f"powertown_artifacts_building_{building_id}.csv"
    elif park_id is not None:
        filename = f"powertown_artifacts_park_{park_id}.csv"
    return _csv_response(output, filename)


# ----------------------------------------------------------------------
# 3) New export: claims (one row per claim)
# ----------------------------------------------------------------------
@router.get("/claims.csv")
def export_claims_csv(
    park_id: Optional[int] = Query(default=None),
    building_id: Optional[int] = Query(default=None),
    artifact_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Export one row per claim (structured extraction output), with context:
    claim -> artifact -> building -> park.
    """
    c = models.Claim
    a = models.Artifact
    b = models.Building
    p = models.IndustrialPark

    q = (
        db.query(
            c.id.label("claim_id"),
            c.artifact_id,
            a.building_id,
            b.name.label("building_name"),
            a.industrial_park_id,
            p.name.label("park_name"),
            c.field_key,
            c.value_json,
            c.unit,
            c.confidence,
            c.source_ref,
            c.created_at,
        )
        .join(a, a.id == c.artifact_id)
        .outerjoin(b, b.id == a.building_id)
        .outerjoin(p, p.id == a.industrial_park_id)
    )

    if artifact_id is not None:
        q = q.filter(c.artifact_id == artifact_id)
    if building_id is not None:
        q = q.filter(a.building_id == building_id)
    if park_id is not None:
        q = q.filter(a.industrial_park_id == park_id)

    q = q.order_by(c.confidence.desc().nullslast(), c.id.asc())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "claim_id",
            "artifact_id",
            "park_id",
            "park_name",
            "building_id",
            "building_name",
            "field_key",
            "value_json",
            "unit",
            "confidence",
            "source_ref",
            "created_at",
        ]
    )

    for r in q.all():
        writer.writerow(
            [
                r.claim_id,
                r.artifact_id,
                r.industrial_park_id,
                _as_text(r.park_name),
                r.building_id,
                _as_text(r.building_name),
                _as_text(r.field_key),
                _as_text(r.value_json),
                _as_text(r.unit),
                _as_text(r.confidence),
                _as_text(r.source_ref),
                _dt_iso(r.created_at),
            ]
        )

    filename = "powertown_claims.csv"
    if artifact_id is not None:
        filename = f"powertown_claims_artifact_{artifact_id}.csv"
    elif building_id is not None:
        filename = f"powertown_claims_building_{building_id}.csv"
    elif park_id is not None:
        filename = f"powertown_claims_park_{park_id}.csv"

    return _csv_response(output, filename)
