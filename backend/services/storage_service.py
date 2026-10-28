"""
Storage Service - Handles file storage operations.
`StorageInterface` lets a cloud backend (GCS, S3, ...) be swapped in later.
"""
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from backend.config import settings
from backend.models import utcnow

# Leading bytes of each accepted file type
_SIGNATURES = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
}


def content_matches_extension(content: bytes, extension: str) -> bool:
    """Check the file's magic bytes agree with its extension."""
    return any(content.startswith(sig) for sig in _SIGNATURES.get(extension.lower(), ()))


class StorageInterface(ABC):
    """Abstract interface for storage operations."""

    @abstractmethod
    async def save_file_content(self, content: bytes, filename: str) -> str:
        """Save bytes and return the stored path."""

    @abstractmethod
    async def get_file(self, file_path: str) -> Optional[bytes]:
        """Retrieve a file by path."""

    @abstractmethod
    async def delete_file(self, file_path: str) -> bool:
        """Delete a file by path."""

    @abstractmethod
    async def file_exists(self, file_path: str) -> bool:
        """Check if file exists."""


class LocalStorageService(StorageInterface):
    """Local filesystem storage, confined to `base_path`."""

    def __init__(self, base_path: Optional[Path] = None):
        self.base_path = (base_path or settings.UPLOAD_DIR).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _generate_unique_filename(self, original_filename: str) -> str:
        """Generate a unique, filesystem-safe filename."""
        timestamp = utcnow().strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        path = Path(original_filename)
        safe_name = "".join(c for c in path.stem[:50] if c.isalnum() or c in "._-")
        return f"{timestamp}_{unique_id}_{safe_name}{path.suffix.lower()}"

    def resolve_path(self, file_path: str) -> Optional[Path]:
        """
        Resolve a stored path, refusing anything outside the storage directory.
        Paths recorded under a previous upload directory fall back to the same
        filename in the current one, so moving the uploads folder keeps working.
        """
        path = Path(file_path).resolve()
        if path.is_relative_to(self.base_path):
            return path
        return self.base_path / Path(file_path.replace("\\", "/")).name

    async def save_file_content(self, content: bytes, filename: str) -> str:
        file_path = self.base_path / self._generate_unique_filename(filename)
        file_path.write_bytes(content)
        return str(file_path)

    async def get_file(self, file_path: str) -> Optional[bytes]:
        path = self.resolve_path(file_path)
        return path.read_bytes() if path and path.is_file() else None

    async def delete_file(self, file_path: str) -> bool:
        path = self.resolve_path(file_path)
        if path and path.is_file():
            path.unlink()
            return True
        return False

    async def file_exists(self, file_path: str) -> bool:
        path = self.resolve_path(file_path)
        return bool(path and path.is_file())


# Default storage instance
storage_service = LocalStorageService()
