"""Shared test setup.

Tests run against a throwaway SQLite database and storage folder. The
environment variables are set before the app is imported, because the app
reads its settings at import time.
"""

import os
import tempfile
from pathlib import Path

_TEST_DIR = Path(tempfile.mkdtemp(prefix="certgen_tests_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_DIR / 'test.db').as_posix()}"
os.environ["STORAGE_DIR"] = str(_TEST_DIR / "certificates")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    """Every test starts with empty tables."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    # Starlette's TestClient runs background tasks before returning the
    # response, so by the time a POST /jobs call returns the job has finished.
    return TestClient(app)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def job_payload():
    return {
        "course_name": "Python Backend Bootcamp",
        "issued_by": "Acme Academy",
        "issue_date": "2026-10-01",
        "recipients": [
            {"name": "Asha Verma", "email": "asha@example.com"},
            {"name": "Rahul Mehta", "email": "rahul@example.com"},
            {"name": "Maria Garcia", "email": "maria@example.com"},
        ],
    }
