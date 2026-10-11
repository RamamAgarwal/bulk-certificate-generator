"""Application settings, read from environment variables with sensible defaults."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    # Any SQLAlchemy URL works here (e.g. postgresql+psycopg://user:pass@host/db).
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./certificates.db")
    )
    # Folder where generated PDF files are written.
    storage_dir: Path = field(
        default_factory=lambda: Path(os.getenv("STORAGE_DIR", "./generated_certificates"))
    )
    # Upper bound on recipients in a single request, to protect the server.
    max_recipients_per_job: int = field(
        default_factory=lambda: int(os.getenv("MAX_RECIPIENTS_PER_JOB", "5000"))
    )


settings = Settings()
