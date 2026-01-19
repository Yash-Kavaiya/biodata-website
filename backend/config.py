"""
Configuration settings for the Biodata application.
Follows Single Responsibility Principle - only handles configuration.
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    # App settings
    APP_NAME: str = "Biodata Management System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # Storage settings
    BASE_DIR: Path = Path(__file__).parent.parent
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    DB_DIR: Path = BASE_DIR / "backend" / "db"
    STORAGE_DIR: Path = BASE_DIR / "storage"

    # LLM settings (for OCR)
    LLM_PROVIDER: str = "vertexai"  # or "anthropic", "openai", "local"
    ANTHROPIC_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    
    # Vertex AI settings
    GCP_PROJECT_ID: Optional[str] = None
    GCP_LOCATION: str = "us-central1"
    VERTEX_MODEL: str = "gemini-2.0-flash-001"  # Default model
    
    # Available Gemini models for selection
    AVAILABLE_MODELS: list = [
        "gemini-2.0-flash-001",
        "gemini-2.0-flash-lite-001", 
        "gemini-2.5-pro-preview-06-05",
        "gemini-2.5-flash-preview-05-20",
    ]

    # File settings
    MAX_FILE_SIZE_MB: int = 10
    ALLOWED_EXTENSIONS: list = [".pdf", ".png", ".jpg", ".jpeg"]

    # Rate limiting & Queue settings
    QUEUE_CONCURRENCY: int = 5          # Max concurrent OCR tasks
    REQUESTS_PER_MINUTE: int = 50       # API rate limit (stay under provider limits)
    BURST_CAPACITY: int = 10            # Max burst requests
    MAX_RETRIES: int = 3                # Retry attempts for transient failures
    RETRY_BASE_DELAY: float = 2.0       # Base delay for exponential backoff
    RETRY_MAX_DELAY: float = 60.0       # Max retry delay
    BATCH_CHUNK_SIZE: int = 10          # Files processed per chunk
    MAX_BULK_FILES: int = 200           # Max files per bulk upload

    # Similarity search settings
    SIMILARITY_THRESHOLD: float = 0.7
    PKL_FILE_PATH: Path = BASE_DIR / "backend" / "db" / "embeddings.pkl"

    # Neo4j Graph Database settings
    NEO4J_URI: Optional[str] = None
    NEO4J_USERNAME: Optional[str] = None
    NEO4J_PASSWORD: Optional[str] = None
    NEO4J_DATABASE: str = "neo4j"

    class Config:
        env_file = Path(__file__).parent.parent / ".env"
        extra = "allow"

    def ensure_directories(self):
        """Create necessary directories if they don't exist."""
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.DB_DIR.mkdir(parents=True, exist_ok=True)
        self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
