"""Creating a generation job and validating its input."""

from app.config import settings


def test_create_job_is_accepted_and_returns_job_details(client, job_payload):
    response = client.post("/jobs", json=job_payload)

    assert response.status_code == 202
    body = response.json()
    assert body["id"]
    assert body["course_name"] == "Python Backend Bootcamp"
    assert body["issued_by"] == "Acme Academy"
    assert body["issue_date"] == "2026-10-01"
    assert body["counts"]["total"] == 3
    assert body["status_url"] == f"/jobs/{body['id']}"


def test_issue_date_defaults_to_today(client, job_payload):
    from datetime import date

    del job_payload["issue_date"]
    response = client.post("/jobs", json=job_payload)

    assert response.status_code == 202
    assert response.json()["issue_date"] == date.today().isoformat()


def test_job_appears_in_job_list(client, job_payload):
    job_id = client.post("/jobs", json=job_payload).json()["id"]

    body = client.get("/jobs").json()

    assert body["total"] == 1
    assert body["items"][0]["id"] == job_id


# --- Request-level validation: the whole request is rejected ---------------


def test_missing_course_name_is_rejected(client, job_payload):
    del job_payload["course_name"]
    assert client.post("/jobs", json=job_payload).status_code == 422


def test_blank_issuer_is_rejected(client, job_payload):
    job_payload["issued_by"] = "   "
    assert client.post("/jobs", json=job_payload).status_code == 422


def test_empty_recipient_list_is_rejected(client, job_payload):
    job_payload["recipients"] = []
    assert client.post("/jobs", json=job_payload).status_code == 422


def test_invalid_issue_date_is_rejected(client, job_payload):
    job_payload["issue_date"] = "not-a-date"
    assert client.post("/jobs", json=job_payload).status_code == 422


def test_too_many_recipients_is_rejected(client, job_payload, monkeypatch):
    monkeypatch.setattr(settings, "max_recipients_per_job", 2)

    response = client.post("/jobs", json=job_payload)

    assert response.status_code == 422
    assert "at most 2 recipients" in response.text


# --- Row-level validation: bad rows are reported, good rows still run ------


def test_invalid_recipients_are_reported_without_blocking_valid_ones(client, job_payload):
    job_payload["recipients"] += [
        {"name": "", "email": "noname@example.com"},
        {"name": "Bad Email", "email": "not-an-email"},
        {"email": "missing.name@example.com"},
        "this is not even an object",
    ]

    # The POST response is a snapshot taken before generation starts:
    # invalid rows are already known, valid ones are still waiting.
    job = client.post("/jobs", json=job_payload).json()
    assert job["status"] == "pending"
    assert job["counts"] == {"total": 7, "pending": 3, "generated": 0, "failed": 0, "invalid": 4}

    job = client.get(f"/jobs/{job['id']}").json()
    assert job["status"] == "completed_with_errors"
    assert job["counts"] == {"total": 7, "pending": 0, "generated": 3, "failed": 0, "invalid": 4}

    invalid = client.get(f"/jobs/{job['id']}/certificates", params={"status": "invalid"}).json()
    assert invalid["total"] == 4
    by_row = {item["row_number"]: item for item in invalid["items"]}
    assert "name" in by_row[4]["error_message"]
    assert "email" in by_row[5]["error_message"]
    assert by_row[5]["recipient_name"] == "Bad Email"  # original data is kept for reference
    assert "name" in by_row[6]["error_message"]
    assert by_row[7]["error_message"]
    assert all(item["download_url"] is None for item in invalid["items"])


def test_duplicate_email_in_one_request_is_marked_invalid(client, job_payload):
    job_payload["recipients"].append({"name": "Asha Again", "email": "ASHA@example.com"})

    job_id = client.post("/jobs", json=job_payload).json()["id"]

    invalid = client.get(f"/jobs/{job_id}/certificates", params={"status": "invalid"}).json()
    assert invalid["total"] == 1
    assert invalid["items"][0]["row_number"] == 4
    assert "duplicate" in invalid["items"][0]["error_message"]


def test_name_is_trimmed_and_email_lowercased(client, job_payload):
    job_payload["recipients"] = [{"name": "  Asha Verma  ", "email": "Asha@Example.com"}]

    job_id = client.post("/jobs", json=job_payload).json()["id"]

    item = client.get(f"/jobs/{job_id}/certificates").json()["items"][0]
    assert item["recipient_name"] == "Asha Verma"
    assert item["recipient_email"] == "asha@example.com"
