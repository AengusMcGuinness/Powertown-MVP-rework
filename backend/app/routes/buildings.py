from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.db import get_db
from backend.app.schemas import BuildingCreate, BuildingDossierOut, BuildingOut

router = APIRouter()


@router.post("", response_model=BuildingOut)
def create_building(payload: BuildingCreate, db: Session = Depends(get_db)):
    park = db.get(models.IndustrialPark, payload.industrial_park_id)
    if not park:
        raise HTTPException(status_code=404, detail="industrial_park not found")

    building = models.Building(
        industrial_park_id=payload.industrial_park_id,
        name=payload.name,
        address=payload.address,
    )
    db.add(building)
    db.commit()
    db.refresh(building)
    return building


@router.get("/{building_id}", response_model=BuildingDossierOut)
def get_building_dossier(building_id: int, db: Session = Depends(get_db)):
    building = db.get(models.Building, building_id)
    if not building:
        raise HTTPException(status_code=404, detail="building not found")

    artifacts = (
        db.query(models.Artifact)
        .filter(models.Artifact.building_id == building_id)
        .order_by(models.Artifact.created_at.desc())
        .all()
    )

    return {"building": building, "artifacts": artifacts}
