"""Checking job status and retrieving generated certificates."""

import io
import zipfile

from pypdf import PdfReader

from app import services


def test_unknown_job_returns_404(client):
    assert client.get("/jobs/does-not-exist").status_code == 404
    assert client.get("/jobs/does-not-exist/certificates").status_code == 404
    assert client.get("/jobs/does-not-exist/download").status_code == 404


def test_list_certificates_of_a_job(client, job_payload):
    job_id = client.post("/jobs", json=job_payload).json()["id"]

    body = client.get(f"/jobs/{job_id}/certificates").json()

    assert body["total"] == 3
    assert [item["row_number"] for item in body["items"]] == [1, 2, 3]
    assert [item["recipient_name"] for item in body["items"]] == [
        "Asha Verma",
        "Rahul Mehta",
        "Maria Garcia",
    ]
    for item in body["items"]:
        assert item["status"] == "generated"
        assert item["download_url"] == f"/certificates/{item['id']}/download"


def test_certificate_list_supports_pagination_and_status_filter(client, job_payload):
    job_payload["recipients"].append({"name": "Bad", "email": "nope"})
    job_id = client.post("/jobs", json=job_payload).json()["id"]

    page = client.get(f"/jobs/{job_id}/certificates", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 4
    assert [item["row_number"] for item in page["items"]] == [3, 4]

    generated = client.get(f"/jobs/{job_id}/certificates", params={"status": "generated"}).json()
    assert generated["total"] == 3

    bad_filter = client.get(f"/jobs/{job_id}/certificates", params={"status": "bogus"})
    assert bad_filter.status_code == 422


def test_download_single_certificate_as_pdf(client, job_payload):
    job_id = client.post("/jobs", json=job_payload).json()["id"]
    item = client.get(f"/jobs/{job_id}/certificates").json()["items"][0]

    response = client.get(item["download_url"])

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "certificate_Asha_Verma.pdf" in response.headers["content-disposition"]
    text = PdfReader(io.BytesIO(response.content)).pages[0].extract_text()
    assert "Asha Verma" in text


def test_get_single_certificate_details(client, job_payload):
    job_id = client.post("/jobs", json=job_payload).json()["id"]
    item = client.get(f"/jobs/{job_id}/certificates").json()["items"][0]

    response = client.get(f"/certificates/{item['id']}")

    assert response.status_code == 200
    assert response.json() == item


def test_unknown_certificate_returns_404(client):
    assert client.get("/certificates/does-not-exist").status_code == 404
    assert client.get("/certificates/does-not-exist/download").status_code == 404


def test_downloading_a_certificate_that_was_not_generated_returns_409(client, job_payload):
    job_payload["recipients"] = [{"name": "Bad Email", "email": "nope"}]
    job_id = client.post("/jobs", json=job_payload).json()["id"]
    item = client.get(f"/jobs/{job_id}/certificates").json()["items"][0]

    response = client.get(f"/certificates/{item['id']}/download")

    assert response.status_code == 409
    assert "invalid" in response.json()["detail"]


def test_download_all_certificates_of_a_job_as_zip(client, job_payload):
    job_payload["recipients"].append({"name": "Bad Email", "email": "nope"})
    job_id = client.post("/jobs", json=job_payload).json()["id"]

    response = client.get(f"/jobs/{job_id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == [
            "0001_Asha_Verma.pdf",
            "0002_Rahul_Mehta.pdf",
            "0003_Maria_Garcia.pdf",
        ]
        assert archive.read("0001_Asha_Verma.pdf").startswith(b"%PDF")


def test_zip_download_returns_404_before_anything_is_generated(client, job_payload, monkeypatch):
    monkeypatch.setattr(services, "process_job", lambda job_id: None)
    job_id = client.post("/jobs", json=job_payload).json()["id"]

    assert client.get(f"/jobs/{job_id}/download").status_code == 404


def test_health_check(client):
    assert client.get("/health").json() == {"status": "ok"}
