from __future__ import annotations

import os
import re
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from backend.app import models


def _safe_filename(name: str) -> str:
    name = os.path.basename(name)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or "upload"


def uploads_root() -> Path:
    return Path("data/uploads")


def artifacts_root() -> Path:
    return Path("data/artifacts")


def to_served_url(file_path: Path) -> str:
    p = str(file_path).replace("\\", "/")
    return p.replace("data/uploads", "/uploads", 1)


def to_artifact_url(file_path: Path) -> str:
    """
    Must match main.py:
        app.mount("/artifact-files", StaticFiles(directory="data/artifacts"), ...)
    """
    p = str(file_path).replace("\\", "/")
    return p.replace("data/artifacts", "/artifact-files", 1)


def build_upload_path(observation_id: int, original_filename: str) -> Path:
    safe = _safe_filename(original_filename)
    unique = uuid4().hex
    folder = uploads_root() / f"obs_{observation_id}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{unique}__{safe}"


def build_artifact_path(artifact_id: int, original_filename: str) -> Path:
    safe = _safe_filename(original_filename)
    unique = uuid4().hex
    folder = artifacts_root() / f"a_{artifact_id}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{unique}__{safe}"


def _served_to_disk_path(p: str) -> Path:
    p = (p or "").strip()

    # NEW correct prefix
    if p.startswith("/artifact-files/"):
        rel = p.removeprefix("/artifact-files/")
        return Path("data/artifacts") / rel

    # legacy prefix (you used to store /artifacts/…)
    if p.startswith("/artifacts/"):
        rel = p.removeprefix("/artifacts/")
        return Path("data/artifacts") / rel

    if p.startswith("/uploads/"):
        rel = p.removeprefix("/uploads/")
        return Path("data/uploads") / rel

    return Path(p)


def get_artifact_path(artifact: models.Artifact) -> Path:
    sp = getattr(artifact, "storage_path", None)
    if not sp or sp == "PENDING":
        raise RuntimeError(f"Artifact {artifact.id} has no usable storage_path")

    p = _served_to_disk_path(sp)
    return p if p.is_absolute() else (Path.cwd() / p)


@contextmanager
def open_artifact_handle(artifact: models.Artifact, mode: str = "rb"):
    path = get_artifact_path(artifact)
    with open(path, mode) as f:
        yield f
