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
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
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
4. For 'age': If explicit age is missing but Date of Birth is present, CALCULATE the age based on current year (2025).
5. For 'gender': If not explicitly stated, INFER it from the name, photos, or family details (e.g., "Son of" -> Male).
6. Extract ALL text content you can read from the document"""

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


class VertexAIOCRProvider(OCRProviderInterface):
    """Google Vertex AI Gemini-based OCR provider."""

    def __init__(self, project_id: Optional[str] = None, location: str = "us-central1", model: str = "gemini-2.0-flash-001"):
        self.project_id = project_id or settings.GCP_PROJECT_ID
        self.location = location or settings.GCP_LOCATION
        self.model = model
        self._initialized = False

    def _initialize(self):
        """Initialize Vertex AI SDK."""
        if not self._initialized:
            try:
                import vertexai
                from vertexai.generative_models import GenerativeModel
                
                if self.project_id:
                    vertexai.init(project=self.project_id, location=self.location)
                else:
                    # Use default credentials
                    vertexai.init(location=self.location)
                self._initialized = True
            except Exception as e:
                raise ValueError(f"Failed to initialize Vertex AI: {e}")

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
4. For 'age': If explicit age is missing but Date of Birth is present, CALCULATE the age based on current year (2025).
5. For 'gender': If not explicitly stated, INFER it from the name, photos, or family details (e.g., "Son of" -> Male).
6. Extract ALL text content you can read from the document"""

    async def _load_file_as_part(self, file_path: str):
        """Load file as Vertex AI Part."""
        from vertexai.generative_models import Part
        
        path = Path(file_path)
        suffix = path.suffix.lower()

        with open(file_path, "rb") as f:
            content = f.read()

        # Determine mime type
        if suffix == ".pdf":
            mime_type = "application/pdf"
        elif suffix == ".png":
            mime_type = "image/png"
        elif suffix in [".jpg", ".jpeg"]:
            mime_type = "image/jpeg"
        else:
            mime_type = "application/octet-stream"

        return Part.from_data(content, mime_type=mime_type)

    async def extract_biodata(self, file_path: str) -> Tuple[Dict[str, Any], float, str]:
        """
        Extract biodata using Vertex AI Gemini.

        Args:
            file_path: Path to the file

        Returns:
            Tuple of (extracted_data, confidence_score, raw_text)
        """
        self._initialize()
        
        from vertexai.generative_models import GenerativeModel

        # Load model
        model = GenerativeModel(self.model)

        # Create content with file
        file_part = await self._load_file_as_part(file_path)
        
        # Generate response
        response = await model.generate_content_async(
            [file_part, self._get_extraction_prompt()],
            generation_config={
                "max_output_tokens": 4096,
                "temperature": 0.1,
            }
        )

        # Extract the text response
        raw_text = response.text

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
    """Mock OCR provider - returns empty data when no LLM is configured."""

    async def extract_biodata(self, file_path: str) -> Tuple[Dict[str, Any], float, str]:
        """Return empty data - configure LLM_PROVIDER in .env for real OCR."""
        import asyncio
        await asyncio.sleep(0.5) # Simulate latency
            
        # Return empty dict - no hardcoded values
        # User must configure vertexai or anthropic in .env for actual OCR
        return {}, 0.9, "Mock OCR Response"


class OCRService:
    """
    Main OCR service that coordinates extraction.
    Follows Open/Closed Principle - easy to add new providers.
    """

    def __init__(self, provider: Optional[OCRProviderInterface] = None, model: Optional[str] = None):
        self.model = model
        self.provider = provider or self._get_default_provider()

    def _get_default_provider(self) -> OCRProviderInterface:
        """Get the default OCR provider based on configuration."""
        llm_provider = settings.LLM_PROVIDER.lower()
        
        if llm_provider == "vertexai":
            project_id = settings.GCP_PROJECT_ID
            location = settings.GCP_LOCATION
            model = self.model or settings.VERTEX_MODEL
            return VertexAIOCRProvider(project_id=project_id, location=location, model=model)
        elif llm_provider == "anthropic":
            api_key = settings.ANTHROPIC_API_KEY
            if api_key:
                return AnthropicOCRProvider(api_key)
        
        # Fall back to mock for development
        return MockOCRProvider()

    def set_model(self, model: str):
        """Switch to a different model."""
        self.model = model
        if isinstance(self.provider, VertexAIOCRProvider):
            self.provider.model = model

    async def process_file(self, file_path: str, model: Optional[str] = None) -> Tuple[Dict[str, Any], float, str, OCRStatus]:
        """
        Process a file and extract biodata.

        Args:
            file_path: Path to the uploaded file
            model: Optional model override for this request

        Returns:
            Tuple of (extracted_data, confidence, raw_text, status)
        """
        try:
            # Temporarily set model if provided
            original_model = None
            if model and isinstance(self.provider, VertexAIOCRProvider):
                original_model = self.provider.model
                self.provider.model = model

            extracted_data, confidence, raw_text = await self.provider.extract_biodata(
                file_path
            )

            # Restore original model
            if original_model and isinstance(self.provider, VertexAIOCRProvider):
                self.provider.model = original_model

            # Post-processing: Calculate Age if missing
            try:
                if not extracted_data.get('age') and extracted_data.get('date_of_birth'):
                    from datetime import datetime
                    dob_str = str(extracted_data['date_of_birth'])
                    # Try common formats
                    for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d.%m.%Y', '%B %d, %Y']:
                        try:
                            dob = datetime.strptime(dob_str, fmt)
                            today = datetime.now()
                            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                            extracted_data['age'] = age
                            break
                        except ValueError:
                            continue
            except Exception as e:
                # Ignore calculation errors
                print(f"Error calculating age: {e}")

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

    async def reprocess_file(self, file_path: str, model: Optional[str] = None) -> Tuple[Dict[str, Any], float, str, OCRStatus]:
        """Re-run OCR on a file."""
        return await self.process_file(file_path, model=model)
    
    @staticmethod
    def get_available_models() -> list:
        """Get list of available Gemini models."""
        return [
            "gemini-2.0-flash-001",
            "gemini-2.0-flash-lite-001",
            "gemini-2.5-pro-preview-06-05",
            "gemini-2.5-flash-preview-05-20",
        ]


# Singleton instance
ocr_service = OCRService()

