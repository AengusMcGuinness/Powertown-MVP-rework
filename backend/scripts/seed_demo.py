from __future__ import annotations

import argparse
import hashlib
import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from backend.app import models
from backend.app.db import SessionLocal, init_db
from backend.app.services.storage import artifacts_root, build_artifact_path, to_artifact_url

# If you want the seed to automatically enqueue processing jobs
try:
    from backend.app.services.jobs import enqueue_job  # type: ignore
except Exception:
    enqueue_job = None  # allow seeding even if jobs module changes


DEMO_PARK_NAME = "Demo Industrial Park"
DEMO_PARK_LOCATION = "Fall River, MA (demo)"


# ------------------------------------------------------------
# Asset locations (relative to repo root)
# ------------------------------------------------------------
REPO_ROOT = Path.cwd()

# These already exist in your repo (per your tree dump)
WITH_MEDIA_DIR = REPO_ROOT / "demo_data" / "with_media"

DEFAULT_IMAGE_1 = WITH_MEDIA_DIR / "transformer.jpg"
DEFAULT_IMAGE_2 = WITH_MEDIA_DIR / "loading_dock.jpg"
DEFAULT_AUDIO_1 = WITH_MEDIA_DIR / "audio_note.m4a"

# Optional: put real PDFs here to showcase embedded-text extraction + OCR fallbacks.
# Example: create demo_data/showroom_pdfs/ and drop in:
#   generation_interconnect.pdf
#   data_acquisition_map.pdf
#   power_use_acquisition_map.pdf
SHOWROOM_PDFS_DIR = REPO_ROOT / "demo_data" / "showroom_pdfs"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _artifact_folder_for_id(artifact_id: int) -> Path:
    return artifacts_root() / f"a_{artifact_id}"


def _delete_artifact_folder(artifact_id: int) -> None:
    folder = _artifact_folder_for_id(artifact_id)
    if not folder.exists() or not folder.is_dir():
        return
    for p in folder.glob("*"):
        try:
            p.unlink()
        except Exception:
            pass
    try:
        folder.rmdir()
    except Exception:
        pass


def _get_or_create_demo_park(db: Session) -> models.IndustrialPark:
    park = (
        db.query(models.IndustrialPark)
        .filter(models.IndustrialPark.name == DEMO_PARK_NAME)
        .first()
    )
    if park:
        if not park.location:
            park.location = DEMO_PARK_LOCATION
            db.commit()
            db.refresh(park)
        return park

    park = models.IndustrialPark(name=DEMO_PARK_NAME, location=DEMO_PARK_LOCATION)
    db.add(park)
    db.commit()
    db.refresh(park)
    return park


def _reset_demo_data(db: Session) -> None:
    """
    Deletes existing demo park (and its buildings/artifacts) if present.
    Also cleans up artifact folders on disk.

    IMPORTANT: we delete dependent tables first:
      - processing_jobs
      - artifact_text_segments
      - claims
    """
    park = (
        db.query(models.IndustrialPark)
        .filter(models.IndustrialPark.name == DEMO_PARK_NAME)
        .first()
    )
    if not park:
        return

    buildings = (
        db.query(models.Building)
        .filter(models.Building.industrial_park_id == park.id)
        .all()
    )
    building_ids = [b.id for b in buildings]

    artifacts = []

    artifacts.extend(
        db.query(models.Artifact)
        .filter(models.Artifact.industrial_park_id == park.id)
        .all()
    )
    if building_ids:
        artifacts.extend(
            db.query(models.Artifact)
            .filter(models.Artifact.building_id.in_(building_ids))
            .all()
        )

    artifact_ids = sorted({a.id for a in artifacts})

    if artifact_ids:
        # dependent tables first
        db.query(models.ProcessingJob).filter(
            models.ProcessingJob.artifact_id.in_(artifact_ids)
        ).delete(synchronize_session=False)

        db.query(models.ArtifactTextSegment).filter(
            models.ArtifactTextSegment.artifact_id.in_(artifact_ids)
        ).delete(synchronize_session=False)

        db.query(models.Claim).filter(
            models.Claim.artifact_id.in_(artifact_ids)
        ).delete(synchronize_session=False)

        db.query(models.Artifact).filter(
            models.Artifact.id.in_(artifact_ids)
        ).delete(synchronize_session=False)

        db.commit()

    if building_ids:
        db.query(models.Building).filter(models.Building.id.in_(building_ids)).delete(
            synchronize_session=False
        )
        db.commit()

    db.delete(park)
    db.commit()

    for aid in artifact_ids:
        _delete_artifact_folder(aid)


def _guess_kind(mime_type: Optional[str], filename: str) -> str:
    mt = (mime_type or "").lower()
    fn = filename.lower()

    if mt == "application/pdf" or fn.endswith(".pdf"):
        return "pdf"
    if mt.startswith("image/") or fn.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return "image"
    if mt.startswith("audio/") or fn.endswith((".m4a", ".mp3", ".wav", ".aac")):
        return "audio"
    if mt.startswith("video/") or fn.endswith((".mp4", ".mov", ".mkv")):
        return "video"
    if fn.endswith(".txt"):
        return "text"
    return "file"


def _mime_for(filename: str) -> Optional[str]:
    mt, _ = mimetypes.guess_type(filename)
    return mt


def _create_text_artifact(
    db: Session,
    *,
    industrial_park_id: int | None = None,
    building_id: int | None = None,
    text: str,
    enqueue: bool = True,
) -> models.Artifact:
    a = models.Artifact(
        industrial_park_id=industrial_park_id,
        building_id=building_id,
        kind="text",
        mime_type="text/plain",
        original_filename=None,
        storage_path=None,
        text_content=text,
        status="uploaded",
    )
    db.add(a)
    db.commit()
    db.refresh(a)

    if enqueue and enqueue_job is not None:
        enqueue_job(db, a.id, "extract_text")

    return a


def _create_file_artifact_from_path(
    db: Session,
    *,
    industrial_park_id: int | None = None,
    building_id: int | None = None,
    src_path: Path,
    dest_filename: Optional[str] = None,
    enqueue: bool = True,
) -> models.Artifact:
    if not src_path.exists():
        raise FileNotFoundError(f"missing demo asset: {src_path}")

    filename = dest_filename or src_path.name
    mime_type = _mime_for(filename)
    kind = _guess_kind(mime_type, filename)

    # Create DB row first to get ID for storage folder
    a = models.Artifact(
        industrial_park_id=industrial_park_id,
        building_id=building_id,
        kind=kind,
        mime_type=mime_type,
        original_filename=filename,
        storage_path="PENDING",
        status="uploaded",
    )
    db.add(a)
    db.commit()
    db.refresh(a)

    data = src_path.read_bytes()
    disk_path = build_artifact_path(a.id, filename)
    disk_path.write_bytes(data)

    a.storage_path = to_artifact_url(disk_path)
    a.bytes_size = len(data)
    a.sha256 = _sha256(data)

    db.commit()
    db.refresh(a)

    if enqueue and enqueue_job is not None:
        enqueue_job(db, a.id, "extract_text")

    return a


def _collect_showroom_pdfs() -> list[Path]:
    if not SHOWROOM_PDFS_DIR.exists():
        return []
    pdfs = sorted([p for p in SHOWROOM_PDFS_DIR.glob("*.pdf") if p.is_file()])
    return pdfs


@dataclass
class BuildingSpec:
    name: str
    address: str
    notes: list[str]
    want_pdfs: bool = True


def seed_showroom(db: Session, *, enqueue: bool = True) -> int:
    park = _get_or_create_demo_park(db)

    # Park-level doc (nice for gallery + search)
    _create_text_artifact(
        db,
        industrial_park_id=park.id,
        text=(
            "Demo showroom: This site contains a mix of notes, photos, audio clips, and PDFs.\n"
            "Use /ui/artifacts to browse, /ui/search to find keywords like 'transformer', 'interconnection', 'PJM', etc.\n"
            "Run the worker to process OCR/transcription/claims."
        ),
        enqueue=enqueue,
    )

    # Ensure assets exist (fail loudly so demo isn't “empty”)
    for p in [DEFAULT_IMAGE_1, DEFAULT_IMAGE_2, DEFAULT_AUDIO_1]:
        if not p.exists():
            raise FileNotFoundError(
                f"Expected demo asset not found: {p}\n"
                "Make sure demo_data/with_media exists in your repo."
            )

    showroom_pdfs = _collect_showroom_pdfs()

    building_specs: list[BuildingSpec] = [
        BuildingSpec(
            name="Bayview Distribution Center",
            address="Dock-facing frontage, Unit A",
            notes=[
                "Multiple loading docks; steady truck traffic. Large paved staging yard suitable for containerized storage.",
                "Transformer pad visible near south wall; ask for single-line diagram and service voltage (likely three-phase).",
                "Contact: facilities manager mentioned interest in demand response / peak shaving."
            ],
            want_pdfs=True,
        ),
        BuildingSpec(
            name="Riverside Cold Storage",
            address="Rear entrance off service lane",
            notes=[
                "Refrigeration compressors/chillers running. High industrial load profile likely.",
                "Switchgear cabinet and utility room access on east side. Plenty of open yard space behind building.",
                "Follow-up: identify utility interconnection constraints and peak demand."
            ],
            want_pdfs=True,
        ),
        BuildingSpec(
            name="Harbor Metal Works",
            address="Unit 7A, corner lot",
            notes=[
                "Welding + industrial equipment suggests meaningful load. Limited yard; might need creative siting.",
                "Overhead three-phase lines on adjacent street; confirm transformer ownership (utility vs customer).",
            ],
            want_pdfs=False,
        ),
        BuildingSpec(
            name="South Bay Logistics",
            address="Warehouse row, unit 12",
            notes=[
                "High-bay warehouse; forklifts and distribution activity. Large parking lot with an unused corner.",
                "No electrical details yet. Need follow-up with facilities for service size and panel capacity.",
            ],
            want_pdfs=False,
        ),
        BuildingSpec(
            name="Granite Paper Co.",
            address="Main plant, north side",
            notes=[
                "HVAC + chiller plant visible; transformer warning labels near loading dock. Likely high service capacity.",
                "Mentioned interest in demand management; contact email collected.",
            ],
            want_pdfs=True,
        ),
    ]

    created_buildings = 0

    # Reuse the same real media assets but rename per-building so the UI looks realistic
    for i, spec in enumerate(building_specs, start=1):
        existing = (
            db.query(models.Building)
            .filter(
                models.Building.industrial_park_id == park.id,
                models.Building.name == spec.name,
            )
            .first()
        )

        if existing:
            building = existing
        else:
            building = models.Building(
                industrial_park_id=park.id,
                name=spec.name,
                address=spec.address,
            )
            db.add(building)
            db.commit()
            db.refresh(building)
            created_buildings += 1

        # Notes => text artifacts (these drive scoring immediately)
        for t in spec.notes:
            _create_text_artifact(
                db,
                industrial_park_id=park.id,
                building_id=building.id,
                text=t,
                enqueue=enqueue,
            )

        # Photos (real JPGs)
        _create_file_artifact_from_path(
            db,
            industrial_park_id=park.id,
            building_id=building.id,
            src_path=DEFAULT_IMAGE_1,
            dest_filename=f"{spec.name.replace(' ', '_').lower()}__transformer.jpg",
            enqueue=enqueue,
        )
        _create_file_artifact_from_path(
            db,
            industrial_park_id=park.id,
            building_id=building.id,
            src_path=DEFAULT_IMAGE_2,
            dest_filename=f"{spec.name.replace(' ', '_').lower()}__loading_dock.jpg",
            enqueue=enqueue,
        )

        # Audio (real .m4a)
        _create_file_artifact_from_path(
            db,
            industrial_park_id=park.id,
            building_id=building.id,
            src_path=DEFAULT_AUDIO_1,
            dest_filename=f"{spec.name.replace(' ', '_').lower()}__walkthrough_audio.m4a",
            enqueue=enqueue,
        )

        # Optional PDFs (if you provided any)
        if spec.want_pdfs and showroom_pdfs:
            # attach up to 2 PDFs per building for variety
            for p in showroom_pdfs[:2]:
                _create_file_artifact_from_path(
                    db,
                    industrial_park_id=park.id,
                    building_id=building.id,
                    src_path=p,
                    dest_filename=f"{spec.name.replace(' ', '_').lower()}__{p.name}",
                    enqueue=enqueue,
                )

    return created_buildings


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a realistic showroom demo dataset.")
    parser.add_argument("--reset", action="store_true", help="Delete existing demo data before seeding.")
    parser.add_argument(
        "--no-enqueue",
        action="store_true",
        help="Do not enqueue processing jobs (useful if you only want DB rows).",
    )
    args = parser.parse_args()

    init_db()

    db = SessionLocal()
    try:
        if args.reset:
            _reset_demo_data(db)

        created = seed_showroom(db, enqueue=(not args.no_enqueue))
        print(f"Seeded showroom park '{DEMO_PARK_NAME}'. New buildings created: {created}")
        print("Open:")
        print("  - Review home:        http://127.0.0.1:8000/review")
        print("  - Artifact gallery:   http://127.0.0.1:8000/ui/artifacts")
        print("  - Search:             http://127.0.0.1:8000/ui/search")
        if SHOWROOM_PDFS_DIR.exists():
            print(f"PDF folder: {SHOWROOM_PDFS_DIR} (add PDFs here for richer demos)")
        else:
            print(f"Tip: create {SHOWROOM_PDFS_DIR} and drop a few real PDFs in it for a stronger demo.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
