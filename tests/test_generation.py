"""Certificate generation, job progress and failure handling."""

from datetime import date

import pytest
from pypdf import PdfReader

from app import services
from app.certificate_template import CertificateRenderError, render_certificate
from app.config import settings
from app.models import Certificate, Job
from app.schemas import JobCreateRequest


def _pdf_text(path) -> str:
    return PdfReader(str(path)).pages[0].extract_text()


# --- The template on its own ------------------------------------------------


def test_template_renders_recipient_details_into_a_pdf(tmp_path):
    path = tmp_path / "certificate.pdf"

    render_certificate(
        path,
        recipient_name="Asha Verma",
        course_name="Python Backend Bootcamp",
        issued_by="Acme Academy",
        issue_date=date(2026, 10, 1),
        certificate_id="abc-123",
    )

    assert path.read_bytes().startswith(b"%PDF")
    text = _pdf_text(path)
    assert "Asha Verma" in text
    assert "Python Backend Bootcamp" in text
    assert "Acme Academy" in text
    assert "01 October 2026" in text
    assert "abc-123" in text


def test_template_handles_very_long_names(tmp_path):
    path = tmp_path / "long.pdf"
    long_name = "Wolfeschlegelsteinhausenbergerdorff " * 2 + "Maximilian Alexander III"

    render_certificate(
        path,
        recipient_name=long_name.strip(),
        course_name="Course",
        issued_by="Issuer",
        issue_date=date(2026, 10, 1),
        certificate_id="id",
    )

    assert len(PdfReader(str(path)).pages) == 1


def test_template_rejects_characters_the_font_cannot_draw(tmp_path):
    with pytest.raises(CertificateRenderError):
        render_certificate(
            tmp_path / "bad.pdf",
            recipient_name="आशा वर्मा",
            course_name="Course",
            issued_by="Issuer",
            issue_date=date(2026, 10, 1),
            certificate_id="id",
        )


# --- Generation through the API --------------------------------------------


def test_job_generates_a_certificate_file_for_every_recipient(client, db, job_payload):
    job_id = client.post("/jobs", json=job_payload).json()["id"]

    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "completed"
    assert job["counts"] == {"total": 3, "pending": 0, "generated": 3, "failed": 0, "invalid": 0}
    assert job["progress_percent"] == 100.0
    assert job["started_at"] and job["completed_at"]

    certificates = db.query(Certificate).filter_by(job_id=job_id).order_by("row_number").all()
    assert [c.status for c in certificates] == ["generated"] * 3
    for certificate in certificates:
        text = _pdf_text(settings.storage_dir / certificate.file_path)
        assert certificate.recipient_name in text
        assert certificate.id in text


def test_job_progress_moves_from_pending_to_completed(client, job_payload, monkeypatch):
    # Hold the background work back so the "not started yet" state can be observed.
    real_process_job = services.process_job
    monkeypatch.setattr(services, "process_job", lambda job_id: None)

    job_id = client.post("/jobs", json=job_payload).json()["id"]

    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "pending"
    assert job["counts"]["pending"] == 3
    assert job["progress_percent"] == 0.0
    assert job["completed_at"] is None

    real_process_job(job_id)

    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "completed"
    assert job["counts"]["generated"] == 3
    assert job["progress_percent"] == 100.0


def test_progress_is_visible_while_a_job_is_running(client, job_payload, monkeypatch):
    """Each certificate is committed as it finishes, so a status check mid-job sees it."""
    snapshots = []
    real_render = services.render_certificate

    def render_and_check_status(path, **kwargs):
        job_id = path.parent.name
        snapshots.append(client.get(f"/jobs/{job_id}").json())
        real_render(path, **kwargs)

    monkeypatch.setattr(services, "render_certificate", render_and_check_status)

    client.post("/jobs", json=job_payload)

    assert [s["status"] for s in snapshots] == ["processing"] * 3
    assert [s["counts"]["generated"] for s in snapshots] == [0, 1, 2]
    assert [s["progress_percent"] for s in snapshots] == [0.0, 33.3, 66.7]


def test_one_failing_certificate_does_not_stop_the_others(client, job_payload, monkeypatch):
    real_render = services.render_certificate

    def flaky_render(path, **kwargs):
        if kwargs["recipient_name"] == "Rahul Mehta":
            raise RuntimeError("disk full")
        real_render(path, **kwargs)

    monkeypatch.setattr(services, "render_certificate", flaky_render)

    job_id = client.post("/jobs", json=job_payload).json()["id"]

    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "completed_with_errors"
    assert job["counts"] == {"total": 3, "pending": 0, "generated": 2, "failed": 1, "invalid": 0}

    items = client.get(f"/jobs/{job_id}/certificates").json()["items"]
    assert [item["status"] for item in items] == ["generated", "failed", "generated"]
    failed = items[1]
    assert failed["recipient_name"] == "Rahul Mehta"
    assert failed["error_message"] == "disk full"
    assert failed["download_url"] is None


def test_unsupported_name_fails_only_that_certificate(client, job_payload):
    job_payload["recipients"].append({"name": "आशा वर्मा", "email": "hindi@example.com"})

    job_id = client.post("/jobs", json=job_payload).json()["id"]

    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "completed_with_errors"
    assert job["counts"]["generated"] == 3
    assert job["counts"]["failed"] == 1
    failed = client.get(f"/jobs/{job_id}/certificates", params={"status": "failed"}).json()
    assert "cannot display" in failed["items"][0]["error_message"]


def test_job_is_failed_when_nothing_could_be_generated(client, job_payload):
    job_payload["recipients"] = [{"name": "", "email": "x"}, {"name": "No Email"}]

    job_id = client.post("/jobs", json=job_payload).json()["id"]

    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert job["counts"]["invalid"] == 2


def test_interrupted_jobs_are_resumed(db, job_payload):
    """Simulates a restart: the job was stored but the server stopped before generating."""
    job = services.create_job(db, JobCreateRequest(**job_payload))
    assert job.status == "pending"

    services.resume_unfinished_jobs()

    db.expire_all()
    assert db.get(Job, job.id).status == "completed"
    assert services.get_counts(db, job.id)["generated"] == 3
