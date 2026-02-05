from __future__ import annotations

import datetime as dt
import hashlib

from sqlalchemy.orm import Session

from backend.app import models
from backend.app.services.scoring import ScoreResult, score_building

SCORING_VERSION = "v1"


def _input_hash(texts: list[str | None]) -> str:
    cleaned = [" ".join((t or "").split()) for t in texts if t and t.strip()]
    payload = "\n".join(cleaned).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def get_or_compute_building_score(db: Session, building_id: int) -> ScoreResult:
    # Pull text artifacts (notes) for this building
    rows = (
        db.query(models.Artifact.text_content)
        .filter(
            models.Artifact.building_id == building_id,
            models.Artifact.kind == "text",
        )
        .all()
    )
    texts = [r[0] for r in rows]
    h = _input_hash(texts)

    cached = (
        db.query(models.BuildingScoreCache)
        .filter(
            models.BuildingScoreCache.building_id == building_id,
            models.BuildingScoreCache.version == SCORING_VERSION,
        )
        .first()
    )

    # Cache hit if hash matches
    if cached and cached.input_hash == h:
        return ScoreResult.model_validate_json(cached.payload_json)

    # Cache miss → compute fresh
    result = score_building(texts)
    payload_json = result.model_dump_json()

    if cached is None:
        cached = models.BuildingScoreCache(
            building_id=building_id,
            version=SCORING_VERSION,
            input_hash=h,
            payload_json=payload_json,
            updated_at=dt.datetime.utcnow(),
        )
        db.add(cached)
    else:
        cached.input_hash = h
        cached.payload_json = payload_json
        cached.updated_at = dt.datetime.utcnow()

    db.commit()
    return result
