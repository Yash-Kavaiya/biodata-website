"""
Test fixtures. Environment is configured before the app is imported so tests
never touch the real database, uploads folder, LLM provider or Neo4j.
"""
import json
import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="biodata-tests-"))
os.environ.update({
    "LLM_PROVIDER": "local",
    "NEO4J_URI": "",
    "TELEGRAM_BOT_TOKEN": "",
    "AUTH_USERNAME": "",
    "AUTH_PASSWORD": "",
    "UPLOAD_DIR": str(_TMP / "uploads"),
    "DB_DIR": str(_TMP / "db"),
    "RETRY_BASE_DELAY": "0.01",
    "RETRY_MAX_DELAY": "0.05",
    "REQUESTS_PER_MINUTE": "60000",
    "BURST_CAPACITY": "1000",
    "LOG_LEVEL": "WARNING",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.config import settings  # noqa: E402
from backend.main import app  # noqa: E402
from backend.services import db, ocr_service, queue_service  # noqa: E402
from backend.services.ocr_service import OCRProviderInterface  # noqa: E402

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PDF_BYTES = b"%PDF-1.4\n% test document\n"

SAMPLE_EXTRACTION = {
    "name": "Rahul Sharma",
    "age": "28 years",
    "gender": "Male",
    "education": "B.Tech Computer Engineering",
    "occupation": "Software Engineer",
    "religion": "Hindu",
    "caste": "Brahmin",
    "current_city": "Ahmedabad",
    "state": "Gujarat",
    "marital_status": "Unmarried",
    "hobbies": ["Cricket", "Reading"],
    "unexpected_key": "should be dropped",
}


class FakeProvider(OCRProviderInterface):
    """Scriptable OCR provider: returns queued responses (str/dict) or raises queued exceptions."""

    name = "fake"

    def __init__(self):
        self.responses = []
        self.default = SAMPLE_EXTRACTION
        self.calls = 0

    async def extract_text(self, file_path, model=None):
        self.calls += 1
        response = self.responses.pop(0) if self.responses else self.default
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, str) else "```json\n" + json.dumps(response) + "\n```"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_state():
    """Empty database/uploads and a fresh fake provider for every test."""
    db._write_data({"biodatas": [], "metadata": {"version": "1.0"}})
    shutil.rmtree(settings.UPLOAD_DIR, ignore_errors=True)
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    breaker = queue_service.circuit_breaker
    breaker.state, breaker.failures = "closed", 0

    original = ocr_service.provider
    ocr_service.provider = FakeProvider()
    yield ocr_service.provider
    ocr_service.provider = original


@pytest.fixture
def provider(clean_state) -> FakeProvider:
    return clean_state


def upload(client, name="biodata.png", content=PNG_BYTES, mime="image/png"):
    return client.post("/api/upload/single", files={"file": (name, content, mime)})


def uploaded_files():
    return list(settings.UPLOAD_DIR.iterdir())
