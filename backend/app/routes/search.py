from __future__ import annotations

import json
import re
from typing import Optional, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.app.db import get_db
from backend.app import models
from backend.app.processors.structured import get_llm, run_llm, parse_json_loose
from backend.app.processors.structured_keys import ALLOWED_KEYS

router = APIRouter()

def _nl_query_to_filters(q: str) -> dict[str, Any]:
    keys = list(ALLOWED_KEYS.keys())
    prompt = f"""Convert the user's query into JSON filters over claim keys.

Allowed keys (use ONLY these keys):
{keys}

Return ONLY valid JSON:
{{
  "must": [{{"key":"...", "op":"=", "value": ...}}, ...],
  "range": [{{"key":"...", "op":"<|<=|>|>=", "value": number}}, ...],
  "keywords": ["...", "..."]
}}

Rules:
- Use key names exactly as given.
- Use op "=" for bool/string exact match.
- Use op "~" for approximate numeric match (e.g., 12.47kV).
- Put numeric comparisons in "range".
- Do not invent keys; if not possible, omit.

User query: {q}
JSON:
"""
    llm = get_llm()
    out = run_llm(llm, prompt)
    try:
        data = parse_json_loose(out)
    except Exception as e:
        return {"must": [], "range": [], "keywords": [q]}

    if not isinstance(data, dict):
        return {"must": [], "range": [], "keywords": [q]}
    data.setdefault("must", [])
    data.setdefault("range", [])
    data.setdefault("keywords", [])
    return data


def _extract_claim_value(value_json: str) -> Any:
    try:
        v = json.loads(value_json)
    except Exception:
        return value_json
    if isinstance(v, dict) and "value" in v:
        return v["value"]
    return v


@router.get("")
def search(
    q: str = Query(..., min_length=2),
    building_id: Optional[int] = None,
    limit: int = 50,
    mode: str = "kw",
    db: Session = Depends(get_db),
):
    mode = (mode or "kw").strip().lower()
    limit = max(1, min(limit, 200))

    if mode == "nl":
        try:
            filt = _nl_query_to_filters(q)
        except Exception as e:
            # Log and fall back to keyword search
            print("NL parse failed:", e)
            return _keyword_search(q, building_id, limit, db)
        
        cq = db.query(models.Claim)
        if building_id is not None:
            cq = cq.filter(models.Claim.building_id == building_id)
        claims_all = list(cq.all())

        def matches(claim: models.Claim) -> bool:
            v = _extract_claim_value(claim.value_json)

            # must filters
            for m in filt.get("must", []):
                if not isinstance(m, dict):
                    continue
                if claim.field_key != m.get("key"):
                    continue
                op = m.get("op", "=")
                target = m.get("value")
                if op == "=":
                    if v != target:
                        return False
                elif op == "~":
                    try:
                        if abs(float(v) - float(target)) > 0.25:
                            return False
                    except Exception:
                        return False

            # range filters
            for r in filt.get("range", []):
                if not isinstance(r, dict):
                    continue
                if claim.field_key != r.get("key"):
                    continue
                op = r.get("op")
                try:
                    num = float(v)
                    thr = float(r.get("value"))
                except Exception:
                    return False
                if op == "<" and not (num < thr): return False
                if op == "<=" and not (num <= thr): return False
                if op == ">" and not (num > thr): return False
                if op == ">=" and not (num >= thr): return False

            return True

        claim_hits = [c for c in claims_all if matches(c)]
        claim_hits.sort(key=lambda c: c.confidence or 0.0, reverse=True)
        claim_hits = claim_hits[:limit]

        return {
            "q": q,
            "mode": "nl",
            "filters": filt,
            "artifacts": [],
            "segments": [],
            "claims": [
                {
                    "artifact_id": c.artifact_id,
                    "field_key": c.field_key,
                    "value": json.loads(c.value_json),
                    "confidence": c.confidence,
                }
                for c in claim_hits
            ],
        }

    # default keyword mode
    qlike = f"%{q.lower()}%"

    aq = db.query(models.Artifact)
    if building_id is not None:
        aq = aq.filter(models.Artifact.building_id == building_id)
    aq = aq.filter(
        or_(
            models.Artifact.original_filename.ilike(qlike),
            models.Artifact.kind.ilike(qlike),
            models.Artifact.mime_type.ilike(qlike),
        )
    ).order_by(models.Artifact.created_at.desc()).limit(limit)
    artifacts = list(aq.all())

    cq = db.query(models.Claim)
    if building_id is not None:
        cq = cq.filter(models.Claim.building_id == building_id)
    cq = cq.filter(or_(models.Claim.field_key.ilike(qlike), models.Claim.value_json.ilike(qlike))) \
           .order_by(models.Claim.confidence.desc()).limit(limit)
    claims = list(cq.all())

    sq = db.query(models.ArtifactTextSegment).filter(models.ArtifactTextSegment.text.ilike(qlike))
    if building_id is not None:
        sq = sq.join(models.Artifact, models.Artifact.id == models.ArtifactTextSegment.artifact_id) \
               .filter(models.Artifact.building_id == building_id)
    sq = sq.limit(limit)
    segments = list(sq.all())

    return {
        "q": q,
        "mode": "kw",
        "artifacts": [
            {"id": a.id, "building_id": a.building_id, "kind": a.kind, "filename": a.original_filename, "storage_path": a.storage_path}
            for a in artifacts
        ],
        "claims": [
            {"artifact_id": c.artifact_id, "field_key": c.field_key, "value": json.loads(c.value_json), "confidence": c.confidence}
            for c in claims
        ],
        "segments": [
            {"artifact_id": s.artifact_id, "segment_index": s.segment_index, "snippet": (s.text or "")[:220]}
            for s in segments
        ],
    }
