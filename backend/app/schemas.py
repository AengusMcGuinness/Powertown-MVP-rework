from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------- Industrial Parks (Sites) ----------


class IndustrialParkCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    location: Optional[str] = Field(None, max_length=200)


class IndustrialParkOut(BaseModel):
    id: int
    name: str
    location: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Buildings ----------


class BuildingCreate(BaseModel):
    industrial_park_id: int
    name: str = Field(..., min_length=1, max_length=200)
    address: Optional[str] = Field(None, max_length=300)


class BuildingOut(BaseModel):
    id: int
    industrial_park_id: int
    name: str
    address: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Artifacts (Evidence) ----------


class ArtifactOut(BaseModel):
    id: int
    industrial_park_id: Optional[int]
    building_id: Optional[int]

    kind: str
    mime_type: Optional[str]
    original_filename: Optional[str]

    # For file artifacts
    storage_path: Optional[str]
    bytes_size: Optional[int]
    sha256: Optional[str]

    # For text artifacts (notes)
    text_content: Optional[str]

    status: str
    error_message: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Dossier ----------


class BuildingDossierOut(BaseModel):
    building: BuildingOut
    artifacts: List[ArtifactOut] = []
