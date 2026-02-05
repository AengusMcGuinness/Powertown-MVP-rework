from __future__ import annotations

import argparse
import base64
import hashlib
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from backend.app import models
from backend.app.db import SessionLocal, init_db
from backend.app.services.storage import artifacts_root, build_artifact_path, to_artifact_url

DEMO_PARK_NAME = "Demo Industrial Park"
DEMO_PARK_LOCATION = "Fall River, MA (demo)"

# 1x1 transparent PNG (very small) so you can render thumbnails without needing real images.
_PNG_1X1_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMA"
    "ASsJTYQAAAAASUVORK5CYII="
)


def _png_bytes() -> bytes:
    return base64.b64decode(_PNG_1X1_BASE64)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _artifact_folder_for_id(artifact_id: int) -> Path:
    # storage uses data/artifacts/a_<id>/
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


def _reset_demo_data(db: Session) -> None:
    """
    Deletes existing demo park (and its buildings/artifacts) if present.
    Also cleans up any artifact folders on disk.
    """
    park = (
        db.query(models.IndustrialPark)
        .filter(models.IndustrialPark.name == DEMO_PARK_NAME)
        .first()
    )
    if not park:
        return

    # Collect buildings
    buildings = (
        db.query(models.Building)
        .filter(models.Building.industrial_park_id == park.id)
        .all()
    )
    building_ids = [b.id for b in buildings]

    # Collect artifacts (park-level and building-level)
    artifacts = []

    # Park-level artifacts
    artifacts.extend(
        db.query(models.Artifact)
        .filter(models.Artifact.industrial_park_id == park.id)
        .all()
    )

    # Building-level artifacts
    if building_ids:
        artifacts.extend(
            db.query(models.Artifact)
            .filter(models.Artifact.building_id.in_(building_ids))
            .all()
        )

    artifact_ids = list({a.id for a in artifacts})

    # Delete artifact rows first
    if artifact_ids:
        db.query(models.Artifact).filter(models.Artifact.id.in_(artifact_ids)).delete(
            synchronize_session=False
        )
        db.commit()

    # Delete buildings
    if building_ids:
        db.query(models.Building).filter(models.Building.id.in_(building_ids)).delete(
            synchronize_session=False
        )
        db.commit()

    # Delete the park
    db.delete(park)
    db.commit()

    # Clean up artifact folders on disk
    for aid in artifact_ids:
        _delete_artifact_folder(aid)


def _create_text_artifact(
    db: Session,
    *,
    industrial_park_id: int | None = None,
    building_id: int | None = None,
    text: str,
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
    return a


def _create_placeholder_image_artifact(
    db: Session,
    *,
    industrial_park_id: int | None = None,
    building_id: int | None = None,
    filename: str = "demo_photo.png",
) -> models.Artifact:
    """
    Creates a file artifact and writes a tiny 1x1 png to disk under data/artifacts/a_<id>/...
    """
    # Create row first so we get an id
    a = models.Artifact(
        industrial_park_id=industrial_park_id,
        building_id=building_id,
        kind="image",
        mime_type="image/png",
        original_filename=filename,
        storage_path=None,
        text_content=None,
        status="uploaded",
    )
    db.add(a)
    db.commit()
    db.refresh(a)

    data = _png_bytes()
    disk_path = build_artifact_path(a.id, filename)
    disk_path.write_bytes(data)

    a.storage_path = to_artifact_url(disk_path)
    a.bytes_size = len(data)
    a.sha256 = _sha256(data)

    db.commit()
    db.refresh(a)
    return a


def seed_demo(db: Session) -> int:
    park = _get_or_create_demo_park(db)

    # Site-level artifact (proves park artifacts work)
    _create_text_artifact(
        db,
        industrial_park_id=park.id,
        text="Demo site-level artifact: broker OM / zoning notes would live here.",
    )

    building_specs = [
        # (name, address, notes[])
        (
            "Matouk Factory",
            "Approx: Textile plant near main road",
            [
                "Large paved lot; visible HVAC units. Mentioned transformer near loading dock. Facilities manager gave business card.",
                "Cold storage area reported; three-phase service likely. Significant truck traffic and distribution activity.",
            ],
        ),
        (
            "Riverside Cold Storage",
            "Rear entrance off service lane",
            [
                "Refrigeration compressors audible; multiple chillers. Switchgear cabinet visible near side wall.",
                "Ample yard space behind building; forklifts and loading docks active. Contact: maintenance supervisor @ example.com.",
            ],
        ),
        (
            "South Bay Logistics",
            "Warehouse row, unit 12",
            [
                "High bay warehouse; heavy forklift activity. Large parking lot with unused corner suitable for containers.",
                "No direct electrical info yet. Need follow-up on utility service size; ask for facilities contact.",
            ],
        ),
        (
            "Fall River Plastics",
            "Corner lot, near substation fence",
            [
                "Manufacturing floor; odor + machinery noise. Substation fence adjacent; transformer signage nearby.",
                "Spoke with receptionist; facilities manager name obtained; follow-up requested.",
            ],
        ),
        (
            "Harbor Metal Works",
            "Unit 7A",
            [
                "Welding/industrial load likely. Switchyard/substation visible across street; three-phase lines overhead.",
                "Tight siting—limited yard. Might need creative placement; ask about leasing adjacent space.",
            ],
        ),
        (
            "Bayview Distribution",
            "Dock-facing frontage",
            [
                "Multiple loading docks and trucks. Large paved staging area; good siting potential.",
                "Solar panels on roof; inverter boxes near utility room. Strong candidate; get electrical single-line diagram.",
            ],
        ),
        (
            "Granite Paper Co.",
            "Main plant, north side",
            [
                "HVAC + chiller plant visible. Transformer pad with warning labels; likely high service capacity.",
                "Contact: facilities@paperco.example. Mentioned interest in demand management.",
            ],
        ),
        (
            "Pier 9 Storage",
            "Small warehouse cluster",
            [
                "Minimal activity; unclear load. Plenty of space but unknown utility service.",
                "No contacts found. Might deprioritize unless utility upgrades are easy.",
            ],
        ),
    ]

    created_buildings = 0

    for name, address, notes in building_specs:
        existing = (
            db.query(models.Building)
            .filter(
                models.Building.industrial_park_id == park.id,
                models.Building.name == name,
            )
            .first()
        )

        if existing:
            building = existing
        else:
            building = models.Building(
                industrial_park_id=park.id,
                name=name,
                address=address,
            )
            db.add(building)
            db.commit()
            db.refresh(building)
            created_buildings += 1

        # Create text artifacts for each note
        for text in notes:
            _create_text_artifact(
                db, industrial_park_id=park.id, building_id=building.id, text=text
            )

        # Add one placeholder image artifact per building so UI can render thumbnails / file links
        _create_placeholder_image_artifact(
            db, industrial_park_id=park.id, building_id=building.id
        )

    return created_buildings


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo data for Powertown MVP (artifacts-only).")
    parser.add_argument(
        "--reset", action="store_true", help="Delete existing demo data before seeding."
    )
    args = parser.parse_args()

    # Ensure tables exist
    init_db()

    db = SessionLocal()
    try:
        if args.reset:
            _reset_demo_data(db)

        created = seed_demo(db)
        print(f"Seeded demo park '{DEMO_PARK_NAME}'. New buildings created: {created}")
        print("Open: http://127.0.0.1:8000/review")
    finally:
        db.close()


if __name__ == "__main__":
    main()
