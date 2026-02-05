"""
Database wiring for the Powertown Prospecting MVP.

- Uses SQLite by default (file-based, no external service required).
- Exposes:
    - engine: SQLAlchemy Engine
    - SessionLocal: session factory
    - get_db(): FastAPI dependency that yields a session
    - init_db(): optional helper to create tables (MVP-friendly)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Load .env from project root (and/or current working directory)
load_dotenv()

_DEFAULT_DB_PATH = Path.cwd() / "demo.db"
DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{_DEFAULT_DB_PATH}")

connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}

# Ensure parent directory exists for sqlite file
if DB_URL.startswith("sqlite:///"):
    db_path = DB_URL.replace("sqlite:///", "", 1)
    Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(DB_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from backend.app.models import Base
    Base.metadata.create_all(bind=engine)
