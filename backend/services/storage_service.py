"""
Storage Service - Handles file storage operations.
Follows Interface Segregation and Dependency Inversion principles.
Designed to be easily swappable between local and cloud storage.
"""
import os
import shutil
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, BinaryIO
from datetime import datetime

from backend.config import settings


class StorageInterface(ABC):
    """Abstract interface for storage operations (Dependency Inversion)."""

    @abstractmethod
    async def save_file(self, file: BinaryIO, filename: str) -> str:
        """Save a file and return the path."""
        pass

    @abstractmethod
    async def get_file(self, file_path: str) -> Optional[bytes]:
        """Retrieve a file by path."""
        pass

    @abstractmethod
    async def delete_file(self, file_path: str) -> bool:
        """Delete a file by path."""
        pass

    @abstractmethod
    async def file_exists(self, file_path: str) -> bool:
        """Check if file exists."""
        pass


class LocalStorageService(StorageInterface):
    """
    Local file storage implementation.
    Single Responsibility: Only handles local file system operations.
    """

    def __init__(self, base_path: Optional[Path] = None):
        self.base_path = base_path or settings.UPLOAD_DIR
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _generate_unique_filename(self, original_filename: str) -> str:
        """Generate a unique filename to prevent collisions."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        ext = Path(original_filename).suffix
        safe_name = Path(original_filename).stem[:50]  # Limit name length
        # Sanitize filename
        safe_name = "".join(c for c in safe_name if c.isalnum() or c in "._-")
        return f"{timestamp}_{unique_id}_{safe_name}{ext}"

    async def save_file(self, file: BinaryIO, filename: str) -> str:
        """
        Save uploaded file to local storage.

        Args:
            file: File-like object to save
            filename: Original filename

        Returns:
            Path where file was saved
        """
        unique_filename = self._generate_unique_filename(filename)
        file_path = self.base_path / unique_filename

        # Read content and write to file
        content = file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        return str(file_path)

    async def save_file_content(self, content: bytes, filename: str) -> str:
        """
        Save file content directly.

        Args:
            content: Bytes content to save
            filename: Original filename

        Returns:
            Path where file was saved
        """
        unique_filename = self._generate_unique_filename(filename)
        file_path = self.base_path / unique_filename

        with open(file_path, "wb") as f:
            f.write(content)

        return str(file_path)

    async def get_file(self, file_path: str) -> Optional[bytes]:
        """
        Read file content from storage.

        Args:
            file_path: Path to the file

        Returns:
            File content as bytes or None if not found
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return None
            with open(path, "rb") as f:
                return f.read()
        except Exception:
            return None

    async def delete_file(self, file_path: str) -> bool:
        """
        Delete a file from storage.

        Args:
            file_path: Path to the file

        Returns:
            True if deleted, False otherwise
        """
        try:
            path = Path(file_path)
            if path.exists():
                path.unlink()
                return True
            return False
        except Exception:
            return False

    async def file_exists(self, file_path: str) -> bool:
        """Check if a file exists in storage."""
        return Path(file_path).exists()


class CloudStorageService(StorageInterface):
    """
    Cloud storage implementation (placeholder for future).
    Can be implemented for Google Cloud Storage, AWS S3, etc.
    """

    def __init__(self, bucket_name: str = "biodata-bucket"):
        self.bucket_name = bucket_name
        # Initialize cloud client here
        # self.client = storage.Client()
        # self.bucket = self.client.bucket(bucket_name)

    async def save_file(self, file: BinaryIO, filename: str) -> str:
        """Save file to cloud storage."""
        # Implement cloud upload logic
        raise NotImplementedError("Cloud storage not yet implemented")

    async def get_file(self, file_path: str) -> Optional[bytes]:
        """Get file from cloud storage."""
        raise NotImplementedError("Cloud storage not yet implemented")

    async def delete_file(self, file_path: str) -> bool:
        """Delete file from cloud storage."""
        raise NotImplementedError("Cloud storage not yet implemented")

    async def file_exists(self, file_path: str) -> bool:
        """Check if file exists in cloud storage."""
        raise NotImplementedError("Cloud storage not yet implemented")


def get_storage_service() -> StorageInterface:
    """
    Factory function to get the appropriate storage service.
    Follows Open/Closed Principle - easy to extend with new storage types.
    """
    storage_type = os.getenv("STORAGE_TYPE", "local")

    if storage_type == "cloud":
        return CloudStorageService()
    else:
        return LocalStorageService()


# Default storage instance
storage_service = LocalStorageService()
