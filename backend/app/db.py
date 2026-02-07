# backend/app/db.py

from __future__ import annotations

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# ------------------------------------------------------------
# Database URL handling
# ------------------------------------------------------------

# Default: local SQLite file in repo root
_DEFAULT_DB_URL = "sqlite:///./demo.db"

# Read from environment if provided, otherwise use default
DB_URL = os.getenv("DATABASE_URL", _DEFAULT_DB_URL)

# Optional debug logging (off by default)
if os.getenv("POWERTOWN_DEBUG_ENV") == "1":
    print("[db] Using DATABASE_URL:", DB_URL)


# ------------------------------------------------------------
# SQLAlchemy engine + session
# ------------------------------------------------------------

# SQLite needs special flags for multithreaded FastAPI usage
_connect_args = {}
if DB_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    DB_URL,
    future=True,
    echo=False,
    connect_args=_connect_args,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    future=True,
)

Base = declarative_base()


# ------------------------------------------------------------
# Database initialization
# ------------------------------------------------------------

def init_db() -> None:
    """
    Initialize database tables.

    Safe to call multiple times.
    """
    # Import models here so they are registered with SQLAlchemy
    from backend.app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


# ------------------------------------------------------------
# Dependency helper (FastAPI)
# ------------------------------------------------------------

def get_db():
    """
    FastAPI dependency that yields a DB session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
