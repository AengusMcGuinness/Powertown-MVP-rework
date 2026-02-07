from __future__ import annotations

import argparse
import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

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
# Repo + showroom asset locations (robust to where script is run)
#   backend/scripts/seed_demo.py -> repo root is parents[2]
# ------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_DATA_DIR = REPO_ROOT / "demo_data"

SHOWROOM_IMAGES_DIR = DEMO_DATA_DIR / "showroom_images"
SHOWROOM_PDFS_DIR = DEMO_DATA_DIR / "showroom_pdfs"
SHOWROOM_VIDEO_DIR = DEMO_DATA_DIR / "showroom_video"
SHOWROOM_AUDIO_DIR = DEMO_DATA_DIR / "showroom_audio"


# --------------------------
# Helpers
# --------------------------
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


def _mime_for(filename: str) -> Optional[str]:
    mt, _ = mimetypes.guess_type(filename)
    return mt


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


def _list_files(dirpath: Path, exts: Sequence[str]) -> list[Path]:
    if not dirpath.exists():
        return []
    out: list[Path] = []
    for ext in exts:
        out.extend([p for p in dirpath.glob(f"*{ext}") if p.is_file()])
    return sorted(out)


def _collect_showroom_assets() -> tuple[list[Path], list[Path], list[Path], list[Path]]:
    images = _list_files(SHOWROOM_IMAGES_DIR, (".jpg", ".jpeg", ".png", ".webp"))
    pdfs = _list_files(SHOWROOM_PDFS_DIR, (".pdf",))
    videos = _list_files(SHOWROOM_VIDEO_DIR, (".mp4", ".mov", ".mkv"))
    audios = _list_files(SHOWROOM_AUDIO_DIR, (".m4a", ".mp3", ".wav", ".aac"))
    return images, pdfs, videos, audios


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

    artifacts: list[models.Artifact] = []
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


@dataclass(frozen=True)
class BuildingSpec:
    name: str
    address: str
    notes: list[str]
    want_pdfs: bool = True
    want_video: bool = True
    want_audio: bool = True


def seed_showroom(db: Session, *, enqueue: bool = True) -> int:
    park = _get_or_create_demo_park(db)

    images, pdfs, videos, audios = _collect_showroom_assets()

    if not (images or pdfs or videos or audios):
        raise FileNotFoundError(
            "No showroom assets found. Add files under demo_data/showroom_{images,pdfs,video,audio}/"
        )

    # Park-level note
    _create_text_artifact(
        db,
        industrial_park_id=park.id,
        text=(
            "Demo showroom: mixed notes + media stored under demo_data/showroom_*.\n"
            "Browse: /ui/artifacts\n"
            "Search: /ui/search (try: transformer, interconnect, feasibility, panel)\n"
            "Run worker to process OCR/transcription/claims."
        ),
        enqueue=enqueue,
    )

    building_specs: list[BuildingSpec] = [
        BuildingSpec(
            name="Bayview Distribution Center",
            address="Dock-facing frontage, Unit A",
            notes=[
                "Multiple loading docks; steady truck traffic. Large paved staging yard suitable for containerized storage.",
                "Transformer/panel photo captured; ask for single-line diagram + service voltage (likely three-phase).",
                "Facilities manager mentioned interest in peak shaving / demand response.",
            ],
            want_pdfs=True,
            want_video=True,
            want_audio=True,
        ),
        BuildingSpec(
            name="Riverside Cold Storage",
            address="Rear entrance off service lane",
            notes=[
                "Refrigeration compressors/chillers running. Industrial load profile likely.",
                "Switchgear cabinet/utility room access on east side. Open yard space behind building.",
                "Follow-up: identify interconnection constraints and peak demand.",
            ],
            want_pdfs=True,
            want_video=True,
            want_audio=True,
        ),
    ]

    # Helper: split a list into N nearly-even chunks (no duplication)
    def split_even(items: list[Path], n: int) -> list[list[Path]]:
        chunks: list[list[Path]] = [[] for _ in range(n)]
        for idx, item in enumerate(items):
            chunks[idx % n].append(item)
        return chunks

    n_buildings = len(building_specs)
    images_by_b = split_even(images, n_buildings)
    pdfs_by_b = split_even(pdfs, n_buildings)
    videos_by_b = split_even(videos, n_buildings)
    audios_by_b = split_even(audios, n_buildings)

    created_buildings = 0

    for bi, spec in enumerate(building_specs):
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

        # Notes as text artifacts
        for t in spec.notes:
            _create_text_artifact(
                db,
                industrial_park_id=park.id,
                building_id=building.id,
                text=t,
                enqueue=enqueue,
            )

        slug = spec.name.replace(" ", "_").lower()

        # Attach split assets (no duplication)
        for img in images_by_b[bi]:
            _create_file_artifact_from_path(
                db,
                industrial_park_id=park.id,
                building_id=building.id,
                src_path=img,
                dest_filename=f"{slug}__{img.name}",
                enqueue=enqueue,
            )

        if spec.want_pdfs:
            for p in pdfs_by_b[bi]:
                _create_file_artifact_from_path(
                    db,
                    industrial_park_id=park.id,
                    building_id=building.id,
                    src_path=p,
                    dest_filename=f"{slug}__{p.name}",
                    enqueue=enqueue,
                )

        if spec.want_video:
            for v in videos_by_b[bi]:
                _create_file_artifact_from_path(
                    db,
                    industrial_park_id=park.id,
                    building_id=building.id,
                    src_path=v,
                    dest_filename=f"{slug}__{v.name}",
                    enqueue=enqueue,
                )

        if spec.want_audio:
            for a in audios_by_b[bi]:
                _create_file_artifact_from_path(
                    db,
                    industrial_park_id=park.id,
                    building_id=building.id,
                    src_path=a,
                    dest_filename=f"{slug}__{a.name}",
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
        print()
        print("Showroom asset dirs:")
        print(f"  images: {SHOWROOM_IMAGES_DIR}")
        print(f"  pdfs:   {SHOWROOM_PDFS_DIR}")
        print(f"  video:  {SHOWROOM_VIDEO_DIR}")
        print(f"  audio:  {SHOWROOM_AUDIO_DIR} (optional)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
