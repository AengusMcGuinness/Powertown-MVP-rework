from __future__ import annotations

import json
import re
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.processors.structured import get_llm, run_llm, parse_json_loose


def _slug(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:80] or "fact"


def _build_prompt(text: str, max_facts: int) -> str:
    return f"""You extract useful facts from documents.

Return ONLY valid JSON. No extra text.

Schema:
{{
  "facts": [
    {{
      "label": "short human-readable name",
      "value": "string|number|bool|object",
      "type": "string|number|bool|date|money|quantity|id|other",
      "category": "power|interconnection|zoning|real_estate|equipment|contacts|other",
      "confidence": 0.0,
      "evidence": "short exact quote from input"
    }}
  ]
}}

Rules:
- Extract up to {max_facts} facts that would matter for evaluating a site for power / interconnection / BESS readiness.
- Prefer concrete numbers, IDs, voltages, capacities, distances, dates, names, utilities, substations.
- Do NOT invent facts. If unsure, omit.

Input:
\"\"\"{text[:12000]}\"\"\"

JSON:
"""


def extract_discovery_facts(db: Session, artifact: models.Artifact, max_facts: int = 40) -> None:
    segs = (
        db.query(models.ArtifactTextSegment)
        .filter(models.ArtifactTextSegment.artifact_id == artifact.id)
        .order_by(models.ArtifactTextSegment.segment_index.asc())
        .all()
    )
    text = "\n".join((s.text or "") for s in segs).strip()

    # wipe old discovery claims
    db.query(models.Claim).filter(
        models.Claim.artifact_id == artifact.id,
        models.Claim.field_key.like("disc:%"),
    ).delete(synchronize_session=False)
    db.commit()

    if not text:
        return

    llm = get_llm()
    out = run_llm(llm, _build_prompt(text, max_facts=max_facts))
    data = parse_json_loose(out)

    facts = data.get("facts", [])
    if not isinstance(facts, list):
        return

    for item in facts:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        if not label:
            continue

        payload = {
            "label": label,
            "value": item.get("value"),
            "type": item.get("type", "string"),
            "category": item.get("category", "other"),
            "evidence": item.get("evidence"),
        }
        conf = float(item.get("confidence", 0.5) or 0.5)
        conf = max(0.0, min(1.0, conf))

        db.add(
            models.Claim(
                artifact_id=artifact.id,
                building_id=artifact.building_id,
                field_key=f"disc:{_slug(label)}",
                value_json=json.dumps(payload),
                unit=None,
                confidence=conf,
                source_ref="discovery:llamacpp",
            )
        )

    db.commit()
