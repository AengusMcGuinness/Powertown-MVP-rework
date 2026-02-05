# backend/tests/conftest.py
import os
import tempfile
import importlib

import pytest
from fastapi.testclient import TestClient

@pytest.fixture(scope="session")
def client():
    # temp sqlite file
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["DATABASE_URL"] = f"sqlite:///{path}"

    # Import after env var set
    import backend.app.db as db
    import backend.app.models as models
    import backend.app.main as main

    # Ensure tables exist
    db.init_db()

    with TestClient(main.app) as c:
        yield c
