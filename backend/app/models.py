from __future__ import annotations

import datetime as dt
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Float
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class BuildingScoreCache(Base):
    __tablename__ = "building_score_cache"
    __table_args__ = (
        UniqueConstraint(
            "building_id", "version", name="uq_score_cache_building_version"
        ),
    )

    id = Column(Integer, primary_key=True)
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=False)

    version = Column(String, nullable=False, default="v1")
    input_hash = Column(String, nullable=False)
    payload_json = Column(Text, nullable=False)

    updated_at = Column(DateTime, nullable=False, default=dt.datetime.utcnow)

    building = relationship("Building")


class BuildingScore(Base):
    __tablename__ = "building_scores"
    __table_args__ = (
        UniqueConstraint("building_id", name="uq_building_scores_building_id"),
    )

    id = Column(Integer, primary_key=True)
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=False)

    score = Column(Integer, nullable=False)
    confidence = Column(String, nullable=False, default="unknown")
    drivers = Column(Text, nullable=False, default="")  # JSON string for simplicity

    version = Column(String, nullable=False, default="v1")
    # hash of all "text" artifact content linked to this building
    input_hash = Column(String, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=dt.datetime.utcnow)

    building = relationship("Building")


class IndustrialPark(Base):
    """A site / industrial park."""

    __tablename__ = "industrial_parks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    buildings: Mapped[list[Building]] = relationship(back_populates="industrial_park")
    artifacts: Mapped[list[Artifact]] = relationship(
        "Artifact", back_populates="industrial_park"
    )


class Building(Base):
    __tablename__ = "buildings"

    status = Column(String, nullable=False, default="new")

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    industrial_park_id: Mapped[int] = mapped_column(
        ForeignKey("industrial_parks.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    industrial_park: Mapped[IndustrialPark] = relationship(back_populates="buildings")
    artifacts: Mapped[list[Artifact]] = relationship(
        "Artifact", back_populates="building"
    )


class Artifact(Base):
    """Generic evidence object (upload anything).

    Artifacts can be attached to a site (IndustrialPark) and/or a Building.

    Notes:
      - Observations are intentionally removed; "notes" are stored as text artifacts.
      - MediaAsset is replaced by Artifact (kind=image/audio/pdf/cad/etc).
    """

    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Associations (optional to keep ingestion flexible)
    industrial_park_id: Mapped[int | None] = mapped_column(
        ForeignKey("industrial_parks.id"), nullable=True
    )
    building_id: Mapped[int | None] = mapped_column(
        ForeignKey("buildings.id"), nullable=True
    )

    # Artifact payload
    kind: Mapped[str] = mapped_column(String(50), nullable=False, default="file")
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # For file artifacts
    storage_path: Mapped[str | None] = mapped_column(String(700), nullable=True)
    bytes_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # For text artifacts (notes)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="uploaded")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    industrial_park: Mapped[IndustrialPark | None] = relationship(
        "IndustrialPark", back_populates="artifacts"
    )
    building: Mapped[Building | None] = relationship("Building", back_populates="artifacts")

class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    artifact: Mapped["Artifact"] = relationship("Artifact")


class ArtifactTextSegment(Base):
    __tablename__ = "artifact_text_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    artifact: Mapped["Artifact"] = relationship("Artifact")

class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id"), nullable=False)
    building_id: Mapped[int | None] = mapped_column(ForeignKey("buildings.id"), nullable=True)

    field_key: Mapped[str] = mapped_column(String(100), nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
