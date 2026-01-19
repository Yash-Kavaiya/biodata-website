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
    LLM_PROVIDER: str = "anthropic"  # or "openai", "local"
    ANTHROPIC_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None

    # File settings
    MAX_FILE_SIZE_MB: int = 10
    ALLOWED_EXTENSIONS: list = [".pdf", ".png", ".jpg", ".jpeg"]

    # Similarity search settings
    SIMILARITY_THRESHOLD: float = 0.7
    PKL_FILE_PATH: Path = BASE_DIR / "backend" / "db" / "embeddings.pkl"

    class Config:
        env_file = ".env"
        extra = "allow"

    def ensure_directories(self):
        """Create necessary directories if they don't exist."""
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.DB_DIR.mkdir(parents=True, exist_ok=True)
        self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
