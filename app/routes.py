"""HTTP endpoints."""

import io
import re
import zipfile

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import services
from app.config import settings
from app.database import get_db
from app.models import Certificate, CertificateStatus, Job
from app.schemas import (
    CertificateListResponse,
    CertificateResponse,
    JobCounts,
    JobCreateRequest,
    JobListResponse,
    JobResponse,
)

router = APIRouter()


def _job_response(db: Session, job: Job) -> JobResponse:
    counts = services.get_counts(db, job.id)
    finished = counts["total"] - counts["pending"]
    progress = round(finished / counts["total"] * 100, 1) if counts["total"] else 100.0
    return JobResponse(
        id=job.id,
        course_name=job.course_name,
        issued_by=job.issued_by,
        issue_date=job.issue_date,
        status=job.status,
        counts=JobCounts(**counts),
        progress_percent=progress,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        status_url=f"/jobs/{job.id}",
        certificates_url=f"/jobs/{job.id}/certificates",
        download_url=f"/jobs/{job.id}/download",
    )


def _certificate_response(certificate: Certificate) -> CertificateResponse:
    response = CertificateResponse.model_validate(certificate)
    if certificate.status == CertificateStatus.GENERATED.value:
        response.download_url = f"/certificates/{certificate.id}/download"
    return response


def _get_job_or_404(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


def _safe_filename(name: str) -> str:
    """Make a recipient name safe to use as a file name."""
    cleaned = re.sub(r"[^A-Za-z0-9 _-]", "", name).strip().replace(" ", "_")
    return cleaned or "certificate"


@router.post("/jobs", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    payload: JobCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Submit a bulk request. Returns immediately; generation runs in the background."""
    job = services.create_job(db, payload)
    background_tasks.add_task(services.process_job, job.id)
    return _job_response(db, job)


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List jobs, newest first."""
    total = db.scalar(select(func.count()).select_from(Job))
    jobs = db.scalars(
        select(Job).order_by(Job.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return JobListResponse(
        total=total, limit=limit, offset=offset, items=[_job_response(db, job) for job in jobs]
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    """Status and progress of one job."""
    return _job_response(db, _get_job_or_404(db, job_id))


@router.get("/jobs/{job_id}/certificates", response_model=CertificateListResponse)
def list_job_certificates(
    job_id: str,
    status_filter: CertificateStatus | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Per-recipient results of a job. Use ?status=failed or ?status=invalid to see problems."""
    _get_job_or_404(db, job_id)
    conditions = [Certificate.job_id == job_id]
    if status_filter is not None:
        conditions.append(Certificate.status == status_filter.value)

    total = db.scalar(select(func.count()).select_from(Certificate).where(*conditions))
    certificates = db.scalars(
        select(Certificate)
        .where(*conditions)
        .order_by(Certificate.row_number)
        .limit(limit)
        .offset(offset)
    ).all()
    return CertificateListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[_certificate_response(certificate) for certificate in certificates],
    )


@router.get("/jobs/{job_id}/download")
def download_job_certificates(job_id: str, db: Session = Depends(get_db)):
    """Download every generated certificate of a job as one ZIP file."""
    _get_job_or_404(db, job_id)
    certificates = db.scalars(
        select(Certificate)
        .where(
            Certificate.job_id == job_id,
            Certificate.status == CertificateStatus.GENERATED.value,
        )
        .order_by(Certificate.row_number)
    ).all()
    if not certificates:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No certificates have been generated for this job yet"
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for certificate in certificates:
            # The row number keeps names unique when two recipients share a name.
            name = f"{certificate.row_number:04d}_{_safe_filename(certificate.recipient_name)}.pdf"
            archive.write(settings.storage_dir / certificate.file_path, arcname=name)

    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="certificates_{job_id}.zip"'},
    )


@router.get("/certificates/{certificate_id}", response_model=CertificateResponse)
def get_certificate(certificate_id: str, db: Session = Depends(get_db)):
    """Details of a single certificate."""
    certificate = db.get(Certificate, certificate_id)
    if certificate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate not found")
    return _certificate_response(certificate)


@router.get("/certificates/{certificate_id}/download")
def download_certificate(certificate_id: str, db: Session = Depends(get_db)):
    """Download one certificate as a PDF."""
    certificate = db.get(Certificate, certificate_id)
    if certificate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate not found")
    if certificate.status != CertificateStatus.GENERATED.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Certificate is not available for download (status: {certificate.status})",
        )

    path = settings.storage_dir / certificate.file_path
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate file is missing from storage")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"certificate_{_safe_filename(certificate.recipient_name)}.pdf",
    )
