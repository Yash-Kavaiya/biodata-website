"""
Configuration settings for the Biodata application.
All values can be overridden with environment variables or a `.env` file.
"""
from pathlib import Path
from typing import List, Optional, Set

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    # App settings
    APP_NAME: str = "Biodata Management System"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Storage settings
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    DB_DIR: Path = BASE_DIR / "backend" / "db"

    # Security
    # When both are set, every request (except /api/health) requires HTTP Basic auth.
    AUTH_USERNAME: Optional[str] = None
    AUTH_PASSWORD: Optional[str] = None
    # Comma-separated list of allowed CORS origins. Empty = same-origin only.
    CORS_ORIGINS: str = ""

    # LLM settings (for OCR): "vertexai", "nvidia", "anthropic" or "local" (no-op mock)
    LLM_PROVIDER: str = "vertexai"
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-sonnet-5-5"

    # Vertex AI settings
    GCP_PROJECT_ID: Optional[str] = None
    # Newer Gemini models are served from the "global" location only
    GCP_LOCATION: str = "global"
    VERTEX_MODEL: str = "gemini-3-flash-preview"
    AVAILABLE_MODELS: List[str] = ["gemini-3-flash-preview"]

    # NVIDIA NIM (OpenAI-compatible). A vision model reads the page, then a
    # text model (selectable in the UI) extracts the fields.
    NVIDIA_API_KEY: Optional[str] = None
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NVIDIA_MODEL: str = "nvidia/nemotron-3-ultra-550b-a55b"
    NVIDIA_VISION_MODEL: str = "nvidia/nemotron-3.5-super-vl-120b-a12b"
    NVIDIA_AVAILABLE_MODELS: List[str] = ["nvidia/nemotron-3-ultra-550b-a55b"]
    NVIDIA_ENABLE_THINKING: bool = False
    NVIDIA_MAX_PDF_PAGES: int = 4

    # File settings
    MAX_FILE_SIZE_MB: int = 10
    ALLOWED_EXTENSIONS: List[str] = [".pdf", ".png", ".jpg", ".jpeg"]

    # Rate limiting & queue settings
    QUEUE_CONCURRENCY: int = 5          # Max concurrent OCR tasks
    REQUESTS_PER_MINUTE: int = 50       # API rate limit (stay under provider limits)
    BURST_CAPACITY: int = 10            # Max burst requests
    MAX_RETRIES: int = 3                # Retry attempts for transient failures
    RETRY_BASE_DELAY: float = 2.0       # Base delay for exponential backoff
    RETRY_MAX_DELAY: float = 60.0       # Max retry delay
    MAX_BULK_FILES: int = 200           # Max files per bulk upload

    # Telegram bot (optional): send PDFs/photos to the bot to upload them.
    # Only the comma-separated chat IDs below may use it.
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_ALLOWED_CHAT_IDS: str = ""

    # Neo4j graph database settings (optional)
    NEO4J_URI: Optional[str] = None
    NEO4J_USERNAME: Optional[str] = None
    NEO4J_PASSWORD: Optional[str] = None
    NEO4J_DATABASE: str = "neo4j"

    @property
    def auth_enabled(self) -> bool:
        return bool(self.AUTH_USERNAME and self.AUTH_PASSWORD)

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def telegram_allowed_chat_ids(self) -> Set[int]:
        ids = set()
        for part in self.TELEGRAM_ALLOWED_CHAT_IDS.split(","):
            part = part.strip()
            if part.lstrip("-").isdigit():
                ids.add(int(part))
        return ids

    @property
    def max_file_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    def ensure_directories(self):
        """Create necessary directories if they don't exist."""
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.DB_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
