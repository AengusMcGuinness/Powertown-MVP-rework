from sqlalchemy.orm import Session
from backend.app import models
from backend.app.services.storage import get_artifact_path

def ocr_image(db: Session, artifact: models.Artifact) -> None:
    """
    Runs OCR on an image artifact and writes ArtifactTextSegment rows.
    """
    path = get_artifact_path(artifact)

    try:
        from PIL import Image
        import pytesseract
    except Exception as e:
        raise RuntimeError(
            "OCR dependencies missing. Install: pip install pillow pytesseract; "
            "and install tesseract system package."
        ) from e

    img = Image.open(path)

    text = pytesseract.image_to_string(img) or ""
    text = text.strip()

    _write_segments(db, artifact.id, [(1, text)], source_prefix="image")

def _write_segments(db: Session, artifact_id: int, parts, source_prefix: str = "ocr"):
    # parts: list[(page_num, text)]
    db.query(models.ArtifactTextSegment).filter(
        models.ArtifactTextSegment.artifact_id == artifact_id
    ).delete()
    for idx, (page, t) in enumerate(parts):
        seg = models.ArtifactTextSegment(
            artifact_id=artifact_id,
            segment_index=idx,
            text=t,
            source_ref=f"{source_prefix}:{page}",
        )
        db.add(seg)
    db.commit()
