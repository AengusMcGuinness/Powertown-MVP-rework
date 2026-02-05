from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.db import get_db
from backend.app.schemas import IndustrialParkCreate, IndustrialParkOut

router = APIRouter()


@router.post("", response_model=IndustrialParkOut)
def create_industrial_park(
    payload: IndustrialParkCreate, db: Session = Depends(get_db)
):
    park = models.IndustrialPark(name=payload.name, location=payload.location)
    db.add(park)
    db.commit()
    db.refresh(park)
    return park
