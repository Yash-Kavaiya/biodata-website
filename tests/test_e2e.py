"""
End-to-end API tests: upload -> review -> approve -> match -> delete.
"""
import base64

from backend.config import settings
from tests.conftest import PDF_BYTES, PNG_BYTES, upload, uploaded_files


def test_full_workflow(client, provider):
    # Upload: OCR output is normalized ("Male" -> male, "28 years" -> 28, list -> text)
    res = upload(client)
    assert res.status_code == 200, res.text
    biodata_id = res.json()["id"]
    assert res.json()["status"] == "completed"

    record = client.get(f"/api/biodata/{biodata_id}").json()
    assert record["gender"] == "male"
    assert record["age"] == 28
    assert record["marital_status"] == "single"
    assert record["hobbies"] == "Cricket, Reading"
    assert "unexpected_key" not in record
    assert 0 < record["ocr_confidence"] < 1
    assert record["is_approved"] is False

    # Review queue + original document served inline
    pending = client.get("/api/biodata/pending").json()
    assert [b["id"] for b in pending["items"]] == [biodata_id]
    doc = client.get(f"/api/biodata/{biodata_id}/file")
    assert doc.status_code == 200
    assert doc.headers["content-type"] == "image/png"
    assert doc.headers["content-disposition"].startswith("inline")
    assert doc.content == PNG_BYTES

    # Not searchable until approved
    prefs = {"gender": "male", "religion": "hindu"}
    assert client.post("/api/search/preferences", json=prefs).json() == []

    # Edit & approve, clearing one field
    res = client.post(f"/api/validation/edit/{biodata_id}", json={"caste": None, "current_city": "Surat"})
    assert res.status_code == 200, res.text
    assert res.json()["caste"] is None
    assert res.json()["current_city"] == "Surat"
    assert res.json()["ocr_status"] == "approved"
    assert client.get("/api/biodata/pending").json()["total"] == 0

    # Preference search
    matches = client.post("/api/search/preferences", json={**prefs, "location": "surat"}).json()
    assert len(matches) == 1
    assert matches[0]["biodata"]["id"] == biodata_id
    assert matches[0]["similarity_score"] == 1.0

    # Compatible-profile search from a manually created (pre-approved) bride profile
    bride = client.post("/api/biodata", json={"name": "Priya", "gender": "female", "age": 26, "religion": "Hindu"})
    assert bride.status_code == 201
    # Same-gender profile in the age range must not be suggested
    client.post("/api/biodata", json={"name": "Asha", "gender": "female", "age": 27, "religion": "Hindu"})
    found = client.post(f"/api/search/by-biodata/{bride.json()['id']}").json()
    assert [m["biodata"]["id"] for m in found] == [biodata_id]

    stats = client.get("/api/search/stats").json()
    assert stats["total_approved"] == 3
    assert stats["age_range"] == {"min": 26, "max": 28}

    # Delete removes record and file
    assert len(uploaded_files()) == 1
    assert client.delete(f"/api/biodata/{biodata_id}").status_code == 200
    assert client.get(f"/api/biodata/{biodata_id}").status_code == 404
    assert uploaded_files() == []


def test_upload_rejects_invalid_files(client, provider, monkeypatch):
    res = upload(client, name="notes.txt", content=b"hello", mime="text/plain")
    assert res.status_code == 400
    assert "Invalid file type" in res.json()["detail"]

    res = upload(client, name="fake.pdf", content=PNG_BYTES, mime="application/pdf")
    assert res.status_code == 400
    assert "valid PDF" in res.json()["detail"]

    monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 0)
    res = upload(client)
    assert res.status_code == 400
    assert "too large" in res.json()["detail"]

    assert provider.calls == 0
    assert uploaded_files() == []
    assert client.get("/api/biodata").json()["total"] == 0


def test_ocr_failure_creates_no_record_and_cleans_up(client, provider):
    provider.responses = [ValueError("document is corrupt")]
    res = upload(client)
    assert res.status_code == 400
    assert "document is corrupt" in res.json()["detail"]
    assert provider.calls == 1  # non-transient errors are not retried
    assert uploaded_files() == []
    assert client.get("/api/biodata").json()["total"] == 0


def test_transient_errors_are_retried(client, provider):
    provider.responses = [RuntimeError("429 Too Many Requests"), RuntimeError("503 Service Unavailable")]
    res = upload(client)
    assert res.status_code == 200, res.text
    assert provider.calls == 3


def test_invalid_model_rejected(client, provider):
    res = client.post(
        "/api/upload/single?model=not-a-model", files={"file": ("a.png", PNG_BYTES, "image/png")}
    )
    assert res.status_code == 400
    assert provider.calls == 0


def test_sync_bulk_upload(client, provider):
    provider.responses = [{"name": "One"}, ValueError("unreadable")]
    files = [
        ("files", ("one.png", PNG_BYTES, "image/png")),
        ("files", ("two.pdf", PDF_BYTES, "application/pdf")),
        ("files", ("three.docx", b"PK", "application/octet-stream")),
    ]
    body = client.post("/api/upload/bulk", files=files).json()
    assert (body["total"], body["successful"], body["failed"]) == (3, 1, 2)
    assert len(uploaded_files()) == 1


def test_async_bulk_upload_and_status(client, provider):
    files = [
        ("files", ("a.png", PNG_BYTES, "image/png")),
        ("files", ("b.pdf", PDF_BYTES, "application/pdf")),
        ("files", ("c.gif", b"GIF89a", "image/gif")),
    ]
    res = client.post("/api/upload/async/bulk", files=files)
    assert res.status_code == 200, res.text
    job = res.json()
    assert (job["queued"], job["validation_errors"]) == (2, 1)

    # TestClient runs background tasks before returning, so the job is finished
    status = client.get(f"/api/upload/batch/{job['job_id']}/status").json()
    assert status["status"] == "partial"
    assert (status["processed"], status["successful"], status["failed"]) == (3, 2, 1)
    assert status["errors"][0]["filename"] == "c.gif"

    results = client.get(f"/api/upload/batch/{job['job_id']}/results").json()["results"]
    assert {r["filename"] for r in results} == {"a.png", "b.pdf"}
    assert client.get("/api/biodata").json()["total"] == 2

    assert client.get("/api/upload/batch/does-not-exist/status").status_code == 404


def test_reocr_success_and_failure(client, provider):
    biodata_id = upload(client).json()["id"]
    client.post(f"/api/validation/approve/{biodata_id}")

    provider.responses = [{"name": "Rahul S. Sharma", "age": 29}]
    res = client.post(f"/api/validation/re-ocr/{biodata_id}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["name"], body["age"], body["ocr_status"], body["is_approved"]) == (
        "Rahul S. Sharma", 29, "completed", False
    )
    assert body["religion"] is None  # re-OCR replaces fields rather than merging stale ones

    provider.responses = [ValueError("bad scan")]
    res = client.post(f"/api/validation/re-ocr/{biodata_id}")
    assert res.status_code == 502
    assert client.get(f"/api/biodata/{biodata_id}").json()["ocr_status"] == "failed"
    assert client.get("/api/biodata/pending").json()["items"][0]["id"] == biodata_id


def test_reject_and_auto_approve(client, provider):
    # Default sample fills 11 of 34 fields (~32% confidence); a name alone is ~3%
    provider.responses = [{"name": "Low"}]
    low = upload(client).json()["id"]
    high = upload(client).json()["id"]
    rejected = upload(client).json()["id"]

    assert client.post(f"/api/validation/reject/{rejected}").json()["ocr_status"] == "rejected"

    res = client.post("/api/validation/auto-approve-all?min_confidence=0.3").json()
    assert res["approved_count"] == 1
    statuses = {b["id"]: b["ocr_status"] for b in client.get("/api/biodata?page_size=10").json()["items"]}
    assert statuses == {low: "completed", high: "approved", rejected: "rejected"}


def test_list_pagination_and_filters(client, provider):
    provider.responses = [{"name": f"Person {i}", "current_city": "Pune" if i % 2 else "Delhi"} for i in range(5)]
    ids = [upload(client).json()["id"] for _ in range(5)]
    client.post(f"/api/validation/approve/{ids[0]}")

    page = client.get("/api/biodata?page=2&page_size=2").json()
    assert (page["total"], page["pages"], len(page["items"])) == (5, 3, 2)

    assert client.get("/api/biodata?q=pune").json()["total"] == 2
    assert client.get("/api/biodata?status=approved").json()["total"] == 1
    assert client.get("/api/biodata?status=bogus").status_code == 422
    assert client.get("/api/biodata/stats").json() == {"total": 5, "completed": 4, "approved": 1}


def test_search_requires_criteria(client):
    assert client.post("/api/search/preferences", json={}).status_code == 400


def test_search_by_upload_does_not_store_file(client, provider):
    client.post("/api/biodata", json={"name": "Priya", "gender": "female", "age": 26, "religion": "Hindu"})
    res = client.post("/api/search/by-upload", files={"file": ("q.png", PNG_BYTES, "image/png")})
    assert res.status_code == 200, res.text
    assert [m["biodata"]["name"] for m in res.json()] == ["Priya"]
    assert uploaded_files() == []
    assert client.get("/api/biodata").json()["total"] == 1


def test_graph_endpoints_without_neo4j(client):
    assert client.get("/api/graph/data").json() == {"nodes": [], "edges": []}
    assert client.get("/api/graph/stats").json()["configured"] is False
    assert client.post("/api/graph/sync").status_code == 400


def test_basic_auth(client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_USERNAME", "admin")
    monkeypatch.setattr(settings, "AUTH_PASSWORD", "s3cret")

    assert client.get("/api/health").status_code == 200
    res = client.get("/api/biodata")
    assert res.status_code == 401
    assert res.headers["www-authenticate"].startswith("Basic")
    assert client.get("/").status_code == 401

    def auth(user, pw):
        return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}

    assert client.get("/api/biodata", headers=auth("admin", "wrong")).status_code == 401
    assert client.get("/api/biodata", headers=auth("admin", "s3cret")).status_code == 200


def test_unknown_routes_404(client):
    assert client.get("/api/nope").status_code == 404
    assert client.get("/files/anything.pdf").status_code == 404
    assert client.get("/static/../backend/config.py").status_code == 404
