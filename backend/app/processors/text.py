import re
from sqlalchemy.orm import Session
from backend.app import models

_WS = re.compile(r"\s+")

def normalize_text_artifact(db: Session, artifact: models.Artifact) -> None:
    """
    For 'kind=text' artifacts: normalize whitespace and write as a single segment.
    """
    text = (artifact.text_content or "").strip()
    text = _WS.sub(" ", text)

    db.query(models.ArtifactTextSegment).filter(
        models.ArtifactTextSegment.artifact_id == artifact.id
    ).delete()

    seg = models.ArtifactTextSegment(
        artifact_id=artifact.id,
        segment_index=0,
        text=text,
        source_ref="text:note",
    )
    db.add(seg)
    db.commit()
