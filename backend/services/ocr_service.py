"""
OCR Service - LLM-based OCR for biodata extraction.
Follows Single Responsibility Principle.
"""
import base64
import json
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import httpx

from backend.config import settings
from backend.models import BiodataBase, OCRStatus


class OCRProviderInterface(ABC):
    """Abstract interface for OCR providers."""

    @abstractmethod
    async def extract_biodata(self, file_path: str) -> Tuple[Dict[str, Any], float, str]:
        """
        Extract biodata from file using OCR.

        Args:
            file_path: Path to the PDF/image file

        Returns:
            Tuple of (extracted_data, confidence_score, raw_text)
        """
        pass


class AnthropicOCRProvider(OCRProviderInterface):
    """Anthropic Claude-based OCR provider."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.api_url = "https://api.anthropic.com/v1/messages"
        self.model = "claude-sonnet-4-20250514"

    def _get_extraction_prompt(self) -> str:
        """Get the prompt for biodata extraction."""
        return """You are an expert at extracting structured data from biodata/matrimonial profile documents.

Analyze this biodata document and extract ALL available information into the following JSON structure.
Be thorough and extract every piece of information visible in the document.

Required JSON structure:
{
    "name": "Full name",
    "age": number or null,
    "gender": "male" or "female" or "other" or null,
    "date_of_birth": "date string" or null,
    "height": "height string" or null,
    "weight": "weight string" or null,
    "complexion": "complexion description" or null,
    "blood_group": "blood group" or null,
    "education": "education details" or null,
    "occupation": "occupation/job" or null,
    "income": "income/salary" or null,
    "company": "company name" or null,
    "father_name": "father's name" or null,
    "father_occupation": "father's occupation" or null,
    "mother_name": "mother's name" or null,
    "mother_occupation": "mother's occupation" or null,
    "siblings": "siblings info" or null,
    "native_place": "native place" or null,
    "current_city": "current city" or null,
    "state": "state" or null,
    "country": "country" or null,
    "religion": "religion" or null,
    "caste": "caste" or null,
    "subcaste": "subcaste" or null,
    "gotra": "gotra" or null,
    "rashi": "rashi/zodiac" or null,
    "nakshatra": "nakshatra/star" or null,
    "manglik": "manglik status" or null,
    "contact_number": "phone number" or null,
    "email": "email address" or null,
    "marital_status": "single" or "married" or "divorced" or "widowed" or null,
    "partner_preferences": "partner preference details" or null,
    "hobbies": "hobbies/interests" or null,
    "about": "about/description" or null
}

IMPORTANT:
1. Return ONLY the JSON object, no additional text
2. Use null for fields not found in the document
3. Preserve exact values as written in the document
4. For age, extract the number only
5. Extract ALL text content you can read from the document"""

    async def _encode_file(self, file_path: str) -> Tuple[str, str]:
        """Encode file to base64 for API."""
        path = Path(file_path)
        suffix = path.suffix.lower()

        with open(file_path, "rb") as f:
            content = f.read()

        encoded = base64.standard_b64encode(content).decode("utf-8")

        # Determine media type
        if suffix == ".pdf":
            media_type = "application/pdf"
        elif suffix in [".png"]:
            media_type = "image/png"
        elif suffix in [".jpg", ".jpeg"]:
            media_type = "image/jpeg"
        else:
            media_type = "application/octet-stream"

        return encoded, media_type

    async def extract_biodata(self, file_path: str) -> Tuple[Dict[str, Any], float, str]:
        """
        Extract biodata using Claude Vision.

        Args:
            file_path: Path to the file

        Returns:
            Tuple of (extracted_data, confidence_score, raw_text)
        """
        if not self.api_key:
            raise ValueError("Anthropic API key not configured")

        encoded_content, media_type = await self._encode_file(file_path)

        # Build the message with image/document
        if media_type == "application/pdf":
            content = [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": encoded_content,
                    },
                },
                {"type": "text", "text": self._get_extraction_prompt()},
            ]
        else:
            content = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": encoded_content,
                    },
                },
                {"type": "text", "text": self._get_extraction_prompt()},
            ]

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": content}],
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(self.api_url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()

        # Extract the text response
        raw_text = result["content"][0]["text"]

        # Parse JSON from response
        try:
            # Try to find JSON in the response
            json_match = re.search(r"\{[\s\S]*\}", raw_text)
            if json_match:
                extracted_data = json.loads(json_match.group())
            else:
                extracted_data = {}
        except json.JSONDecodeError:
            extracted_data = {}

        # Calculate confidence based on filled fields
        total_fields = len(BiodataBase.model_fields)
        filled_fields = sum(1 for v in extracted_data.values() if v is not None)
        confidence = filled_fields / total_fields if total_fields > 0 else 0.0

        return extracted_data, confidence, raw_text


class MockOCRProvider(OCRProviderInterface):
    """Mock OCR provider for testing without API."""

    async def extract_biodata(self, file_path: str) -> Tuple[Dict[str, Any], float, str]:
        """Return mock data for testing."""
        mock_data = {
            "name": "Test User",
            "age": 28,
            "gender": "male",
            "education": "MBA",
            "occupation": "Software Engineer",
            "religion": "Hindu",
            "caste": "General",
            "current_city": "Mumbai",
            "state": "Maharashtra",
            "country": "India",
        }
        return mock_data, 0.75, "Mock OCR text output"


class OCRService:
    """
    Main OCR service that coordinates extraction.
    Follows Open/Closed Principle - easy to add new providers.
    """

    def __init__(self, provider: Optional[OCRProviderInterface] = None):
        self.provider = provider or self._get_default_provider()

    def _get_default_provider(self) -> OCRProviderInterface:
        """Get the default OCR provider based on configuration."""
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key:
            return AnthropicOCRProvider(api_key)
        else:
            # Fall back to mock for development
            return MockOCRProvider()

    async def process_file(self, file_path: str) -> Tuple[Dict[str, Any], float, str, OCRStatus]:
        """
        Process a file and extract biodata.

        Args:
            file_path: Path to the uploaded file

        Returns:
            Tuple of (extracted_data, confidence, raw_text, status)
        """
        try:
            extracted_data, confidence, raw_text = await self.provider.extract_biodata(
                file_path
            )

            # Determine status based on confidence
            if confidence >= 0.7:
                status = OCRStatus.COMPLETED
            elif confidence >= 0.3:
                status = OCRStatus.COMPLETED  # Still completed, but needs review
            else:
                status = OCRStatus.COMPLETED  # Completed with low confidence

            return extracted_data, confidence, raw_text, status

        except Exception as e:
            return {}, 0.0, str(e), OCRStatus.FAILED

    async def reprocess_file(self, file_path: str) -> Tuple[Dict[str, Any], float, str, OCRStatus]:
        """Re-run OCR on a file."""
        return await self.process_file(file_path)


# Singleton instance
ocr_service = OCRService()
