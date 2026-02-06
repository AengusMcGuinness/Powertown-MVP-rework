from __future__ import annotations

import traceback
from typing import Iterable
from sqlalchemy.orm import Session
from backend.app import models
from backend.app.services.storage import get_artifact_path


MIN_TOTAL_CHARS = 200          # total chars across doc to consider "real"
MIN_NONEMPTY_PAGES = 1         # require at least this many pages with text


def extract_text_from_pdf(db: Session, artifact: models.Artifact) -> None:
    path = get_artifact_path(artifact)
    print(f"[pdf] START artifact_id={artifact.id} path={path} exists={path.exists()} size={path.stat().st_size if path.exists() else None}")


    # 1) Embedded text
    embedded_parts: list[tuple[int, str]] = []
    embedded_err: Exception | None = None

    try:
        import fitz  # pymupdf
        doc = fitz.open(path)
        for i in range(doc.page_count):
            page = doc.load_page(i)
            t = (page.get_text("text") or "").strip()
            if t:
                embedded_parts.append((i + 1, t))
        doc.close()

    except Exception as e:
        print(f"[pdf] embedded extraction failed artifact_id={artifact.id}: {e!r}")
        traceback.print_exc()
        embedded_err = e

    if _looks_good(embedded_parts):
        _write_segments(db, artifact.id, embedded_parts, source_prefix="pdf:embedded")
        return

    # 2) OCR fallback
    try:
        ocr_parts = ocr_pdf_pages(path)
    except Exception as e:
        # If embedded also failed, surface that context too
        if embedded_err is not None:
            raise RuntimeError(f"PDF embedded extraction failed: {embedded_err!r}; OCR failed: {e!r}") from e
        raise

    if _looks_good(ocr_parts):
        _write_segments(db, artifact.id, ocr_parts, source_prefix="pdf:ocr")
        return

    # If we get here: both embedded + OCR were “empty-ish”
    msg = "PDF text extraction produced too little text."
    if embedded_err is not None:
        msg += f" Embedded extraction error: {embedded_err!r}."
    msg += f" Embedded pages={len([p for p in embedded_parts if p[1].strip()])}, chars={_total_chars(embedded_parts)}."
    msg += f" OCR pages={len([p for p in ocr_parts if p[1].strip()])}, chars={_total_chars(ocr_parts)}."
    raise RuntimeError(msg)


def _looks_good(parts: list[tuple[int, str]]) -> bool:
    nonempty_pages = sum(1 for _, t in parts if (t or "").strip())
    return (nonempty_pages >= MIN_NONEMPTY_PAGES) and (_total_chars(parts) >= MIN_TOTAL_CHARS)


def _total_chars(parts: list[tuple[int, str]]) -> int:
    return sum(len((t or "").strip()) for _, t in parts)


def _write_segments(
    db: Session,
    artifact_id: int,
    parts: list[tuple[int, str]],
    *,
    source_prefix: str,
) -> None:
    # IMPORTANT: only delete + rewrite if we actually have something to write
    if not parts:
        raise RuntimeError("Refusing to write 0 segments.")

    db.query(models.ArtifactTextSegment).filter(
        models.ArtifactTextSegment.artifact_id == artifact_id
    ).delete(synchronize_session=False)

    seg_index = 0
    for page, t in parts:
        t = (t or "").strip()
        if not t:
            continue
        db.add(
            models.ArtifactTextSegment(
                artifact_id=artifact_id,
                segment_index=seg_index,
                text=t,
                source_ref=f"{source_prefix}:page:{page}",
            )
        )
        seg_index += 1

    if seg_index == 0:
        raise RuntimeError("All extracted segments were empty after stripping.")

    db.commit()


def ocr_pdf_pages(path) -> list[tuple[int, str]]:
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

    doc = fitz.open(path)
    parts: list[tuple[int, str]] = []
    try:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=220)  # bump dpi a bit
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            txt = (pytesseract.image_to_string(img) or "").strip()
            parts.append((i + 1, txt))
    finally:
        doc.close()

    return parts
