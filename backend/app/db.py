# backend/app/db.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# 1) Load .env as early as possible.
#    Use find_dotenv so it works even if you run commands from a subdir.
load_dotenv(dotenv_path=os.getenv("DOTENV_PATH") or None)

# 2) Pick a default DB that is NOT inside backend/app/.
#    This prevents “mystery app.db” from reappearing there.
_DEFAULT_DB_PATH = Path.cwd() / "demo.db"  # change to data/powertown.db if you prefer
_DEFAULT_DB_URL = f"sqlite:///{_DEFAULT_DB_PATH.as_posix()}"

DB_URL = os.getenv("DATABASE_URL", _DEFAULT_DB_URL)

# SQLite needs this
connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}

engine = create_engine(DB_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

print("[db] DATABASE_URL =", os.getenv("DATABASE_URL"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    # Import here so models are registered before create_all
    from backend.app.models import Base  # noqa
    Base.metadata.create_all(bind=engine)
