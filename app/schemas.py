"""Request and response shapes for the API (Pydantic models)."""

from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.config import settings

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
PersonName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class RecipientIn(BaseModel):
    """One recipient. Validated row by row, see services.create_job."""

    name: PersonName
    email: EmailStr


class JobCreateRequest(BaseModel):
    course_name: ShortText
    issued_by: ShortText
    issue_date: date | None = Field(default=None, description="Defaults to today.")
    # Recipients are deliberately accepted as raw items here. Each one is
    # validated individually later so that one bad row is reported against that
    # row instead of rejecting the whole request.
    recipients: list[Any] = Field(min_length=1)

    @field_validator("recipients")
    @classmethod
    def check_recipient_limit(cls, value: list[Any]) -> list[Any]:
        limit = settings.max_recipients_per_job
        if len(value) > limit:
            raise ValueError(f"a single job can contain at most {limit} recipients")
        return value


class JobCounts(BaseModel):
    total: int
    pending: int
    generated: int
    failed: int
    invalid: int


class JobResponse(BaseModel):
    id: str
    course_name: str
    issued_by: str
    issue_date: date
    status: str
    counts: JobCounts
    progress_percent: float
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    status_url: str
    certificates_url: str
    download_url: str


class CertificateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    row_number: int
    recipient_name: str
    recipient_email: str
    status: str
    error_message: str | None
    generated_at: datetime | None
    # Only set once the certificate has been generated.
    download_url: str | None = None


class CertificateListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[CertificateResponse]


class JobListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[JobResponse]
