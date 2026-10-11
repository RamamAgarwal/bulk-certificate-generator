"""Database tables.

A Job is one bulk request. It has one Certificate row per recipient in the
request, including recipients whose data was invalid, so the client can see
exactly what happened to every row they sent.
"""

import uuid
from datetime import date, datetime, timezone
from enum import Enum

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JobStatus(str, Enum):
    PENDING = "pending"  # accepted, generation not started yet
    PROCESSING = "processing"  # certificates are being generated
    COMPLETED = "completed"  # every recipient got a certificate
    COMPLETED_WITH_ERRORS = "completed_with_errors"  # some succeeded, some did not
    FAILED = "failed"  # no certificate could be generated


class CertificateStatus(str, Enum):
    PENDING = "pending"  # waiting to be generated
    GENERATED = "generated"  # PDF is ready to download
    FAILED = "failed"  # data was valid but generation raised an error
    INVALID = "invalid"  # recipient data failed validation, never attempted


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Current time in UTC, without tzinfo so it is stored the same way by every database."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_name: Mapped[str] = mapped_column(String(150))
    issued_by: Mapped[str] = mapped_column(String(150))
    issue_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default=JobStatus.PENDING.value, index=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    certificates: Mapped[list["Certificate"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class Certificate(Base):
    __tablename__ = "certificates"
    __table_args__ = (Index("ix_certificates_job_status", "job_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    # Position of this recipient in the request (1-based), so the client can
    # match a result back to the row they submitted.
    row_number: Mapped[int] = mapped_column(Integer)
    recipient_name: Mapped[str] = mapped_column(String(200))
    recipient_email: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(20), default=CertificateStatus.PENDING.value)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Path of the PDF relative to settings.storage_dir.
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    job: Mapped[Job] = relationship(back_populates="certificates")
