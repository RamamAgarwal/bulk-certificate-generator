"""Business logic: creating jobs, generating certificates, reporting progress."""

import logging
from datetime import date

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.certificate_template import render_certificate
from app.config import settings
from app.database import SessionLocal
from app.models import Certificate, CertificateStatus, Job, JobStatus, utcnow
from app.schemas import JobCreateRequest, RecipientIn

logger = logging.getLogger(__name__)


def _describe_validation_error(error: ValidationError) -> str:
    """Turn a Pydantic error into one short readable line, e.g. 'email: not valid'."""
    parts = []
    for item in error.errors():
        field = ".".join(str(loc) for loc in item["loc"]) or "recipient"
        parts.append(f"{field}: {item['msg']}")
    return "; ".join(parts)


def _raw_text(row: object, key: str) -> str:
    """Best-effort copy of what the client sent, for reporting invalid rows."""
    if isinstance(row, dict) and row.get(key) is not None:
        return str(row[key])[:200]
    return ""


def create_job(db: Session, payload: JobCreateRequest) -> Job:
    """Store the job and one certificate row per recipient.

    Valid recipients start as "pending". Invalid ones are stored as "invalid"
    with the reason, so they show up in the job result without blocking the
    valid ones. Nothing is generated here; see process_job.
    """
    job = Job(
        course_name=payload.course_name,
        issued_by=payload.issued_by,
        issue_date=payload.issue_date or date.today(),
        total_count=len(payload.recipients),
    )

    seen_emails: set[str] = set()
    for row_number, row in enumerate(payload.recipients, start=1):
        certificate = Certificate(
            row_number=row_number,
            recipient_name=_raw_text(row, "name"),
            recipient_email=_raw_text(row, "email"),
        )
        try:
            recipient = RecipientIn.model_validate(row)
        except ValidationError as error:
            certificate.status = CertificateStatus.INVALID.value
            certificate.error_message = _describe_validation_error(error)
        else:
            email = recipient.email.lower()
            certificate.recipient_name = recipient.name
            certificate.recipient_email = email
            if email in seen_emails:
                certificate.status = CertificateStatus.INVALID.value
                certificate.error_message = "email: duplicate of an earlier recipient in this request"
            else:
                seen_emails.add(email)
                certificate.status = CertificateStatus.PENDING.value
        job.certificates.append(certificate)

    db.add(job)
    db.commit()
    return job


def get_counts(db: Session, job_id: str) -> dict[str, int]:
    """Number of certificates in each status for a job."""
    rows = db.execute(
        select(Certificate.status, func.count())
        .where(Certificate.job_id == job_id)
        .group_by(Certificate.status)
    ).all()
    counts = {status.value: 0 for status in CertificateStatus}
    for status, count in rows:
        counts[status] = count
    counts["total"] = sum(counts.values())
    return counts


def process_job(job_id: str) -> None:
    """Generate every pending certificate of a job. Runs in the background.

    Each certificate is generated and committed on its own. That gives two
    things: progress is visible while the job runs, and an error on one
    certificate is recorded against that certificate only.
    """
    # The request's session is already closed by the time this runs, so the
    # worker opens its own.
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return

        job.status = JobStatus.PROCESSING.value
        job.started_at = job.started_at or utcnow()
        db.commit()

        pending = db.scalars(
            select(Certificate)
            .where(
                Certificate.job_id == job_id,
                Certificate.status == CertificateStatus.PENDING.value,
            )
            .order_by(Certificate.row_number)
        ).all()

        for certificate in pending:
            relative_path = f"{job.id}/{certificate.id}.pdf"
            try:
                render_certificate(
                    settings.storage_dir / relative_path,
                    recipient_name=certificate.recipient_name,
                    course_name=job.course_name,
                    issued_by=job.issued_by,
                    issue_date=job.issue_date,
                    certificate_id=certificate.id,
                )
            except Exception as error:  # one bad certificate must not stop the rest
                logger.exception("Certificate %s failed", certificate.id)
                certificate.status = CertificateStatus.FAILED.value
                certificate.error_message = str(error)[:500] or type(error).__name__
            else:
                certificate.status = CertificateStatus.GENERATED.value
                certificate.file_path = relative_path
                certificate.generated_at = utcnow()
            db.commit()

        counts = get_counts(db, job_id)
        if counts["generated"] == counts["total"]:
            job.status = JobStatus.COMPLETED.value
        elif counts["generated"] > 0:
            job.status = JobStatus.COMPLETED_WITH_ERRORS.value
        else:
            job.status = JobStatus.FAILED.value
        job.completed_at = utcnow()
        db.commit()


def resume_unfinished_jobs() -> None:
    """Continue jobs that were interrupted, e.g. by a server restart.

    Called once at startup. Certificates that were already generated keep their
    status, so only the remaining pending ones are processed.
    """
    with SessionLocal() as db:
        job_ids = db.scalars(
            select(Job.id)
            .where(Job.status.in_([JobStatus.PENDING.value, JobStatus.PROCESSING.value]))
            .order_by(Job.created_at)
        ).all()
    for job_id in job_ids:
        logger.info("Resuming unfinished job %s", job_id)
        process_job(job_id)
