"""
OCR Service - LLM-based OCR for biodata extraction.

Providers only talk to the model and return raw text. Parsing, normalization
and confidence scoring are shared, so every provider produces identical output.
Errors are raised (not swallowed) so the queue can retry transient failures.
"""
import asyncio
import base64
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.config import settings
from backend.models import BiodataBase, Gender, MaritalStatus

logger = logging.getLogger(__name__)

MIME_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

BIODATA_FIELDS = list(BiodataBase.model_fields)

_GENDER_ALIASES = {
    "m": Gender.MALE, "male": Gender.MALE, "boy": Gender.MALE, "groom": Gender.MALE, "man": Gender.MALE,
    "f": Gender.FEMALE, "female": Gender.FEMALE, "girl": Gender.FEMALE, "bride": Gender.FEMALE,
    "woman": Gender.FEMALE, "other": Gender.OTHER,
}

_MARITAL_ALIASES = {
    "single": MaritalStatus.SINGLE, "unmarried": MaritalStatus.SINGLE,
    "never married": MaritalStatus.SINGLE, "bachelor": MaritalStatus.SINGLE,
    "married": MaritalStatus.MARRIED,
    "divorced": MaritalStatus.DIVORCED, "divorcee": MaritalStatus.DIVORCED,
    "widowed": MaritalStatus.WIDOWED, "widow": MaritalStatus.WIDOWED, "widower": MaritalStatus.WIDOWED,
}

_DOB_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y", "%B %d, %Y")


def build_extraction_prompt() -> str:
    """Prompt asking the model for a JSON object with every biodata field."""
    schema = ",\n".join(f'    "{field}": ...' for field in BIODATA_FIELDS)
    return f"""You are an expert at extracting structured data from biodata/matrimonial profile documents.

Analyze this biodata document and extract ALL available information into a single JSON object with exactly these keys:
{{
{schema}
}}

Rules:
1. Return ONLY the JSON object, no markdown or commentary.
2. Use null for fields not present in the document. Never invent values.
3. Preserve values as written (names, education, addresses), translated to English where needed.
4. "age" must be an integer. If missing but the date of birth is present, compute it as of {date.today().isoformat()}.
5. "gender" must be "male", "female", "other" or null. Infer it from clear cues (e.g. "Son of" -> male).
6. "marital_status" must be "single", "married", "divorced", "widowed" or null.
7. Every other value must be a string or null."""


@dataclass
class OCRResult:
    """Normalized OCR output."""
    data: Dict[str, Any]
    confidence: float
    raw_text: str


def parse_json_object(raw_text: str) -> Dict[str, Any]:
    """
    Extract the first JSON object from model output (tolerates code fences,
    chatter, and trailing text that itself contains braces).
    """
    text = raw_text or ""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            parsed, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if isinstance(parsed, dict):
            return parsed
        start = text.find("{", start + 1)
    return {}


def _age_from_dob(dob: str) -> Optional[int]:
    for fmt in _DOB_FORMATS:
        try:
            born = datetime.strptime(dob.strip(), fmt).date()
        except ValueError:
            continue
        today = date.today()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return None


def _to_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value if v not in (None, ""))
    elif isinstance(value, dict):
        value = ", ".join(f"{k}: {v}" for k, v in value.items() if v not in (None, ""))
    text = str(value).strip()
    return text if text and text.lower() not in {"null", "none", "n/a", "na", "-"} else None


def normalize_biodata_fields(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Coerce raw LLM output into values that validate against BiodataBase.
    Unknown keys are dropped; unrecognized enum values become None.
    """
    data: Dict[str, Any] = {}
    for field in BIODATA_FIELDS:
        value = raw.get(field)
        if field == "age":
            data[field] = _parse_age(value)
        elif field == "gender":
            text = _to_text(value)
            data[field] = _GENDER_ALIASES.get(text.lower()) if text else None
        elif field == "marital_status":
            text = _to_text(value)
            data[field] = _MARITAL_ALIASES.get(text.lower()) if text else None
        else:
            data[field] = _to_text(value)

    if data["age"] is None and data["date_of_birth"]:
        data["age"] = _age_from_dob(data["date_of_birth"])
    return data


def _parse_age(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        age = int(value)
    else:
        match = re.search(r"\d{1,3}", str(value))
        if not match:
            return None
        age = int(match.group())
    return age if 0 < age < 120 else None


def compute_confidence(data: Dict[str, Any]) -> float:
    """Share of schema fields that were filled in."""
    filled = sum(1 for field in BIODATA_FIELDS if data.get(field) is not None)
    return round(filled / len(BIODATA_FIELDS), 4)


def _read_file(file_path: str) -> tuple[bytes, str]:
    path = Path(file_path)
    mime_type = MIME_TYPES.get(path.suffix.lower())
    if not mime_type:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    return path.read_bytes(), mime_type


class OCRProviderInterface(ABC):
    """A provider sends a document to a model and returns its raw text reply."""

    name: str = "unknown"

    @abstractmethod
    async def extract_text(self, file_path: str, model: Optional[str] = None) -> str:
        """Return the model's raw (JSON) response for the document."""


class AnthropicOCRProvider(OCRProviderInterface):
    """Anthropic Claude-based OCR provider."""

    name = "anthropic"
    api_url = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        self.model = model or settings.ANTHROPIC_MODEL

    async def extract_text(self, file_path: str, model: Optional[str] = None) -> str:
        if not self.api_key:
            raise ValueError("Anthropic API key not configured")

        content, media_type = _read_file(file_path)
        block_type = "document" if media_type == "application/pdf" else "image"
        payload = {
            "model": model or self.model,
            "max_tokens": 4096,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": block_type,
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.standard_b64encode(content).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": build_extraction_prompt()},
                ],
            }],
        }
        headers = {
            "content-type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(self.api_url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()

        return "".join(block.get("text", "") for block in result.get("content", []) if block.get("type") == "text")


class VertexAIOCRProvider(OCRProviderInterface):
    """Google Gemini on Vertex AI, via the google-genai SDK."""

    name = "vertexai"

    def __init__(self, project_id: Optional[str] = None, location: Optional[str] = None, model: Optional[str] = None):
        self.project_id = project_id or settings.GCP_PROJECT_ID
        self.location = location or settings.GCP_LOCATION
        self.model = model or settings.VERTEX_MODEL
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(vertexai=True, project=self.project_id, location=self.location)
        return self._client

    async def extract_text(self, file_path: str, model: Optional[str] = None) -> str:
        from google.genai import types

        content, mime_type = _read_file(file_path)
        response = await self._get_client().aio.models.generate_content(
            model=model or self.model,
            contents=[types.Part.from_bytes(data=content, mime_type=mime_type), build_extraction_prompt()],
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=4096,
                response_mime_type="application/json",
            ),
        )
        return response.text or ""


class NvidiaOCRProvider(OCRProviderInterface):
    """
    NVIDIA NIM (OpenAI-compatible API) as a two-stage pipeline:

    1. Read: a vision model transcribes each page image to text. PDFs that
       already carry a text layer skip this step entirely.
    2. Extract: a text model (Nemotron Ultra by default) turns the transcript
       into the biodata JSON.

    Two stages are needed because the Nemotron text models do not accept images.
    """

    name = "nvidia"
    # A PDF page with at least this many characters of embedded text is used as-is
    MIN_TEXT_LAYER_CHARS = 80

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        vision_model: Optional[str] = None,
        base_url: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.api_key = api_key or settings.NVIDIA_API_KEY
        self.model = model or settings.NVIDIA_MODEL
        self.vision_model = vision_model or settings.NVIDIA_VISION_MODEL
        self.base_url = (base_url or settings.NVIDIA_BASE_URL).rstrip("/")
        self._transport = transport  # injectable for tests

    async def _chat(self, client: httpx.AsyncClient, model: str, content: Any, max_tokens: int) -> str:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": settings.NVIDIA_ENABLE_THINKING},
        }
        response = await client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        return message.get("content") or ""

    def _document_pages(self, file_path: str) -> tuple[List[str], List[bytes]]:
        """
        Split a document into (embedded text per page, PNG images of pages needing OCR).
        Images are returned as-is; PDF pages without a usable text layer are rendered.
        """
        content, mime_type = _read_file(file_path)
        if mime_type != "application/pdf":
            return [], [content]

        import fitz  # PyMuPDF

        texts, images = [], []
        with fitz.open(stream=content, filetype="pdf") as doc:
            for page in list(doc)[: settings.NVIDIA_MAX_PDF_PAGES]:
                text = page.get_text().strip()
                if len(text) >= self.MIN_TEXT_LAYER_CHARS:
                    texts.append(text)
                else:
                    images.append(page.get_pixmap(dpi=150).tobytes("png"))
        return texts, images

    async def _transcribe(self, client: httpx.AsyncClient, image: bytes) -> str:
        mime = "image/jpeg" if image.startswith(b"\xff\xd8\xff") else "image/png"
        data_url = f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"
        return await self._chat(client, self.vision_model, [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": (
                "Transcribe all text in this biodata document exactly, line by line, "
                "keeping labels next to their values. Translate non-English text to English. "
                "Output only the text."
            )},
        ], max_tokens=4096)

    async def extract_text(self, file_path: str, model: Optional[str] = None) -> str:
        if not self.api_key:
            raise ValueError("NVIDIA API key not configured (set NVIDIA_API_KEY)")

        texts, images = await asyncio.to_thread(self._document_pages, file_path)
        async with httpx.AsyncClient(timeout=300.0, transport=self._transport) as client:
            for image in images:
                texts.append(await self._transcribe(client, image))
            transcript = "\n\n".join(t for t in texts if t.strip())
            if not transcript:
                raise ValueError("No text could be read from the document")

            prompt = f"{build_extraction_prompt()}\n\nDocument text:\n{transcript}"
            answer = await self._chat(client, model or self.model, prompt, max_tokens=4096)

        # Keep the transcript with the JSON so reviewers can see what the model read
        return f"{answer.strip()}\n\n--- Transcript ---\n{transcript}"


class MockOCRProvider(OCRProviderInterface):
    """No-op provider used when no LLM is configured. Extracts nothing."""

    name = "local"

    async def extract_text(self, file_path: str, model: Optional[str] = None) -> str:
        return "{}"


def get_default_provider() -> OCRProviderInterface:
    """Pick the OCR provider from configuration."""
    provider = settings.LLM_PROVIDER.lower()
    if provider == "vertexai":
        return VertexAIOCRProvider()
    if provider == "nvidia":
        if settings.NVIDIA_API_KEY:
            return NvidiaOCRProvider()
        logger.warning("LLM_PROVIDER=nvidia but NVIDIA_API_KEY is not set; using mock OCR")
    elif provider == "anthropic":
        if settings.ANTHROPIC_API_KEY:
            return AnthropicOCRProvider()
        logger.warning("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set; using mock OCR")
    elif provider != "local":
        logger.warning("Unknown LLM_PROVIDER %r; using mock OCR", settings.LLM_PROVIDER)
    return MockOCRProvider()


class OCRService:
    """Coordinates extraction: provider call -> JSON parsing -> normalization -> confidence."""

    def __init__(self, provider: Optional[OCRProviderInterface] = None):
        self.provider = provider or get_default_provider()

    @property
    def provider_name(self) -> str:
        return self.provider.name

    def available_models(self) -> List[str]:
        """Models the user may pick from."""
        if isinstance(self.provider, VertexAIOCRProvider):
            return list(settings.AVAILABLE_MODELS)
        if isinstance(self.provider, NvidiaOCRProvider):
            return list(dict.fromkeys([self.provider.model, *settings.NVIDIA_AVAILABLE_MODELS]))
        if isinstance(self.provider, AnthropicOCRProvider):
            return [self.provider.model]
        return []

    def default_model(self) -> Optional[str]:
        return getattr(self.provider, "model", None)

    def validate_model(self, model: Optional[str]) -> Optional[str]:
        """Return the model if allowed, else raise ValueError."""
        if model and model not in self.available_models():
            raise ValueError(f"Unsupported model: {model}")
        return model

    async def process_file(self, file_path: str, model: Optional[str] = None) -> OCRResult:
        """Run OCR on a file. Raises on provider errors."""
        raw_text = await self.provider.extract_text(file_path, model=model)
        data = normalize_biodata_fields(parse_json_object(raw_text))
        return OCRResult(data=data, confidence=compute_confidence(data), raw_text=raw_text)


# Singleton instance
ocr_service = OCRService()
