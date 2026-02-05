from sqlalchemy.orm import Session
from backend.app import models
from backend.app.services.storage import get_artifact_path

def extract_text_from_pdf(db: Session, artifact: models.Artifact) -> None:
    # 1) try embedded text
    text = ""
    try:
        import fitz  # pymupdf
        path = get_artifact_path(artifact)
        doc = fitz.open(path)
        parts = []
        for i, page in enumerate(doc):
            t = page.get_text("text") or ""
            if t.strip():
                parts.append((i+1, t))
        text = "\n".join([p[1] for p in parts])
        if len(text.strip()) > 200:
            _write_segments(db, artifact.id, parts)
            return
    except Exception:
        pass

    # 2) OCR fallback (requires tesseract toolchain)
    ocr_parts = ocr_pdf_pages(artifact)
    _write_segments(db, artifact.id, ocr_parts)

def _write_segments(db: Session, artifact_id: int, parts):
    # parts: list[(page_num, text)]
    db.query(models.ArtifactTextSegment).filter(
        models.ArtifactTextSegment.artifact_id == artifact_id
    ).delete()
    for idx, (page, t) in enumerate(parts):
        seg = models.ArtifactTextSegment(
            artifact_id=artifact_id,
            segment_index=idx,
            text=t,
            source_ref=f"page:{page}",
        )
        db.add(seg)
    db.commit()

def ocr_pdf_pages(artifact: models.Artifact):
    """
    Render PDF pages to images via PyMuPDF and run Tesseract OCR.
    Returns list[(page_num, text)].
    """
    try:
        import fitz  # pymupdf
        from PIL import Image
        import pytesseract
    except Exception as e:
        raise RuntimeError(
            "PDF OCR deps missing. Install: pip install pymupdf pillow pytesseract; "
            "and install tesseract system package."
        ) from e

    path = get_artifact_path(artifact)
    doc = fitz.open(path)

    parts = []
    for i, page in enumerate(doc):
        # render at higher DPI for better OCR
        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        text = (pytesseract.image_to_string(img) or "").strip()
        parts.append((i + 1, text))
    return parts
