"""
Unit tests for parsing, normalization, rate limiting, storage and the JSON database.
"""
import asyncio
from datetime import date

import pytest

from backend.models import BiodataInDB, Gender, MaritalStatus, SearchPreferences
from backend.services.database_service import JSONDatabase
from backend.services.ocr_service import compute_confidence, normalize_biodata_fields, parse_json_object
from backend.services.queue_service import TokenBucket
from backend.services.similarity_service import similarity_service
from backend.services.storage_service import LocalStorageService, content_matches_extension


def run(coro):
    return asyncio.run(coro)


def test_db_lookups_stay_correct_after_listing(tmp_path):
    """Regression: get_all() used to sort the cache in place, so ids resolved to the wrong record."""
    db = JSONDatabase(tmp_path / "db.json")

    async def scenario():
        a = await db.create(BiodataInDB(name="A"))
        b = await db.create(BiodataInDB(name="B"))
        await db.get_all()
        assert (await db.get_by_id(a.id)).name == "A"
        await db.update(a.id, {"name": "A2"})
        await db.delete(b.id)
        assert [x.name for x in await db.list_all()] == ["A2"]

    run(scenario())


def test_db_persists_and_recovers_interrupted(tmp_path):
    path = tmp_path / "db.json"
    db = JSONDatabase(path)

    async def scenario():
        rec = await db.create(BiodataInDB(name="X", ocr_status="processing"))
        reopened = JSONDatabase(path)
        assert await reopened.recover_interrupted() == 1
        assert (await reopened.get_by_id(rec.id)).ocr_status == "failed"

    run(scenario())


def test_db_update_rejects_invalid_values(tmp_path):
    db = JSONDatabase(tmp_path / "db.json")

    async def scenario():
        rec = await db.create(BiodataInDB(name="X"))
        with pytest.raises(Exception):
            await db.update(rec.id, {"gender": "not-a-gender"})
        assert (await db.get_by_id(rec.id)).gender is None

    run(scenario())


def test_parse_json_object_handles_fences_and_garbage():
    assert parse_json_object('```json\n{"name": "A"}\n```') == {"name": "A"}
    assert parse_json_object("Sure! {\"age\": 5} hope that helps") == {"age": 5}
    assert parse_json_object("no json here") == {}
    assert parse_json_object("{broken") == {}
    assert parse_json_object("") == {}


def test_normalize_biodata_fields():
    data = normalize_biodata_fields({
        "name": "  Asha  ",
        "gender": "F",
        "age": None,
        "date_of_birth": "15/08/1998",
        "marital_status": "Never Married",
        "education": "",
        "occupation": "N/A",
        "siblings": {"brothers": 1, "sisters": 0},
        "bogus": "x",
    })
    expected_age = date.today().year - 1998 - ((date.today().month, date.today().day) < (8, 15))
    assert data["name"] == "Asha"
    assert data["gender"] == Gender.FEMALE
    assert data["age"] == expected_age
    assert data["marital_status"] == MaritalStatus.SINGLE
    assert data["education"] is None
    assert data["occupation"] is None
    assert data["siblings"] == "brothers: 1, sisters: 0"
    assert "bogus" not in data
    BiodataInDB(**data)  # must validate

    assert normalize_biodata_fields({"gender": "unknown", "age": "two hundred"})["gender"] is None
    assert normalize_biodata_fields({"age": 250})["age"] is None
    assert normalize_biodata_fields({"age": 27.0})["age"] == 27


def test_confidence_counts_only_schema_fields():
    assert compute_confidence({}) == 0
    assert compute_confidence(normalize_biodata_fields({"name": "A", "extra1": 1, "extra2": 2})) < 0.05


def test_token_bucket_spreads_concurrent_waiters():
    async def scenario():
        bucket = TokenBucket(rate=1.0, capacity=1)
        waits = await asyncio.gather(*(bucket.acquire() for _ in range(3)))
        return sorted(waits)

    waits = run(scenario())
    assert waits[0] == 0
    assert waits[1] == pytest.approx(1, abs=0.05)
    assert waits[2] == pytest.approx(2, abs=0.05)


def test_storage_confined_to_base_dir(tmp_path):
    storage = LocalStorageService(tmp_path / "uploads")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")

    assert run(storage.get_file(str(outside))) is None
    assert run(storage.delete_file("../secret.txt")) is False
    assert outside.exists()

    saved = run(storage.save_file_content(b"%PDF-1", "../../evil name.pdf"))
    assert storage.resolve_path(saved).parent == storage.base_path
    assert run(storage.file_exists(saved))


def test_content_signatures():
    assert content_matches_extension(b"%PDF-1.7", ".pdf")
    assert content_matches_extension(b"\xff\xd8\xff\xe0", ".JPG")
    assert not content_matches_extension(b"%PDF-1.7", ".png")
    assert not content_matches_extension(b"anything", ".exe")


def test_match_scoring():
    groom = BiodataInDB(name="G", gender="male", age=30, religion="Hindu", current_city="Mumbai")
    prefs = SearchPreferences(gender="male", min_age=25, max_age=32, religion="hindu", location="Pune")
    score, reasons = similarity_service.calculate_match_score(prefs, groom)
    # gender .2 + age .15 + religion .15 matched out of .6 possible (location missed)
    assert score == pytest.approx(0.5 / 0.6)
    assert "Gender: male" in reasons
    assert not any(r.startswith("Location") for r in reasons)

    results = run(similarity_service.find_matches(
        SearchPreferences(religion="hindu"),
        [BiodataInDB(name=str(i), religion="Hindu" if i != 2 else "Jain") for i in range(5)],
        limit=2,
    ))
    assert [r.biodata.name for r in results] == ["0", "1"]


# ----------------------------------------------------------------- NVIDIA provider

def _nvidia_provider(tmp_path, calls, reply_json='{"name": "Asha", "gender": "Female"}'):
    import json as _json

    import httpx

    from backend.services.ocr_service import NvidiaOCRProvider

    def handler(request):
        body = _json.loads(request.content)
        calls.append(body)
        is_vision = isinstance(body["messages"][0]["content"], list)
        text = "Name: Asha {brackets}" if is_vision else reply_json
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    return NvidiaOCRProvider(
        api_key="test-key", model="text-model", vision_model="vision-model",
        transport=httpx.MockTransport(handler),
    )


def test_nvidia_image_reads_then_extracts(tmp_path):
    from backend.services.ocr_service import OCRService

    image = tmp_path / "b.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    calls = []
    result = run(OCRService(_nvidia_provider(tmp_path, calls)).process_file(str(image)))

    assert [c["model"] for c in calls] == ["vision-model", "text-model"]
    assert calls[0]["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "Name: Asha {brackets}" in calls[1]["messages"][0]["content"]
    assert result.data["name"] == "Asha" and result.data["gender"] == Gender.FEMALE
    assert "--- Transcript ---" in result.raw_text


def test_nvidia_pdf_text_layer_skips_vision(tmp_path):
    import fitz

    pdf = tmp_path / "t.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Name: Asha Patel. Date of Birth: 01/01/1995. Education: MBA. City: Pune, Maharashtra.")
    doc.save(pdf)
    doc.close()

    calls = []
    run(_nvidia_provider(tmp_path, calls).extract_text(str(pdf)))
    assert [c["model"] for c in calls] == ["text-model"]
    assert "Asha Patel" in calls[0]["messages"][0]["content"]


def test_nvidia_scanned_pdf_is_rendered_for_vision(tmp_path):
    import fitz

    pdf = tmp_path / "scan.pdf"
    doc = fitz.open()
    doc.new_page()  # no text layer
    doc.save(pdf)
    doc.close()

    calls = []
    run(_nvidia_provider(tmp_path, calls).extract_text(str(pdf), model="override-model"))
    assert [c["model"] for c in calls] == ["vision-model", "override-model"]


def test_nvidia_errors_propagate_for_retry(tmp_path):
    import httpx

    from backend.services.ocr_service import NvidiaOCRProvider

    image = tmp_path / "b.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    provider = NvidiaOCRProvider(
        api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(429, json={"error": "rate"}))
    )
    with pytest.raises(httpx.HTTPStatusError) as exc:
        run(provider.extract_text(str(image)))
    assert exc.value.response.status_code == 429


def test_parse_json_ignores_braces_in_trailing_text():
    raw = '{"name": "A"}\n\n--- Transcript ---\nNotes {not json}'
    assert parse_json_object(raw) == {"name": "A"}
    assert parse_json_object('[1, 2] then {"age": 3}') == {"age": 3}
