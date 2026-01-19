"""
Database Service - JSON-based local database.
Follows Single Responsibility and Interface Segregation principles.
"""
import json
import os
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
import threading
from contextlib import contextmanager

from backend.config import settings
from backend.models import BiodataInDB, OCRStatus


class JSONDatabase:
    """
    JSON file-based database for biodata storage.
    Thread-safe implementation with file locking.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (settings.DB_DIR / "biodata.json")
        self._lock = threading.Lock()
        self._ensure_db_exists()

    def _ensure_db_exists(self):
        """Create database file if it doesn't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            self._write_data({"biodatas": [], "metadata": {"version": "1.0", "created_at": datetime.utcnow().isoformat()}})

    @contextmanager
    def _file_lock(self):
        """Thread-safe file access context manager."""
        self._lock.acquire()
        try:
            yield
        finally:
            self._lock.release()

    def _read_data(self) -> Dict[str, Any]:
        """Read all data from JSON file."""
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"biodatas": [], "metadata": {"version": "1.0"}}

    def _write_data(self, data: Dict[str, Any]):
        """Write data to JSON file."""
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str, ensure_ascii=False)

    async def create(self, biodata: BiodataInDB) -> BiodataInDB:
        """
        Create a new biodata record.

        Args:
            biodata: BiodataInDB model instance

        Returns:
            Created biodata with ID
        """
        with self._file_lock():
            data = self._read_data()
            biodata_dict = biodata.model_dump()
            biodata_dict["created_at"] = datetime.utcnow().isoformat()
            biodata_dict["updated_at"] = datetime.utcnow().isoformat()
            data["biodatas"].append(biodata_dict)
            self._write_data(data)
            return BiodataInDB(**biodata_dict)

    async def get_by_id(self, biodata_id: str) -> Optional[BiodataInDB]:
        """
        Get biodata by ID.

        Args:
            biodata_id: Unique identifier

        Returns:
            BiodataInDB or None if not found
        """
        with self._file_lock():
            data = self._read_data()
            for item in data["biodatas"]:
                if item.get("id") == biodata_id:
                    return BiodataInDB(**item)
            return None

    async def get_all(
        self,
        page: int = 1,
        page_size: int = 10,
        status_filter: Optional[OCRStatus] = None
    ) -> tuple[List[BiodataInDB], int]:
        """
        Get all biodatas with pagination.

        Args:
            page: Page number (1-indexed)
            page_size: Items per page
            status_filter: Optional OCR status filter

        Returns:
            Tuple of (list of biodatas, total count)
        """
        with self._file_lock():
            data = self._read_data()
            biodatas = data.get("biodatas", [])

            # Apply status filter
            if status_filter:
                biodatas = [b for b in biodatas if b.get("ocr_status") == status_filter.value]

            total = len(biodatas)

            # Sort by created_at descending
            biodatas.sort(key=lambda x: x.get("created_at", ""), reverse=True)

            # Apply pagination
            start = (page - 1) * page_size
            end = start + page_size
            paginated = biodatas[start:end]

            return [BiodataInDB(**item) for item in paginated], total

    async def update(self, biodata_id: str, update_data: Dict[str, Any]) -> Optional[BiodataInDB]:
        """
        Update biodata by ID.

        Args:
            biodata_id: Unique identifier
            update_data: Dictionary of fields to update

        Returns:
            Updated BiodataInDB or None if not found
        """
        with self._file_lock():
            data = self._read_data()
            for i, item in enumerate(data["biodatas"]):
                if item.get("id") == biodata_id:
                    # Update fields
                    for key, value in update_data.items():
                        if value is not None:
                            item[key] = value
                    item["updated_at"] = datetime.utcnow().isoformat()
                    data["biodatas"][i] = item
                    self._write_data(data)
                    return BiodataInDB(**item)
            return None

    async def delete(self, biodata_id: str) -> bool:
        """
        Delete biodata by ID.

        Args:
            biodata_id: Unique identifier

        Returns:
            True if deleted, False if not found
        """
        with self._file_lock():
            data = self._read_data()
            original_len = len(data["biodatas"])
            data["biodatas"] = [b for b in data["biodatas"] if b.get("id") != biodata_id]
            if len(data["biodatas"]) < original_len:
                self._write_data(data)
                return True
            return False

    async def search(self, query: Dict[str, Any]) -> List[BiodataInDB]:
        """
        Search biodatas by multiple criteria.

        Args:
            query: Dictionary of search criteria

        Returns:
            List of matching biodatas
        """
        with self._file_lock():
            data = self._read_data()
            results = []

            for item in data.get("biodatas", []):
                match = True
                for key, value in query.items():
                    if value is None:
                        continue
                    item_value = item.get(key)
                    if item_value is None:
                        match = False
                        break
                    # Case-insensitive string comparison
                    if isinstance(value, str) and isinstance(item_value, str):
                        if value.lower() not in item_value.lower():
                            match = False
                            break
                    # Exact match for other types
                    elif item_value != value:
                        match = False
                        break

                if match:
                    results.append(BiodataInDB(**item))

            return results

    async def get_approved_biodatas(self) -> List[BiodataInDB]:
        """Get all approved biodatas for similarity matching."""
        with self._file_lock():
            data = self._read_data()
            approved = [
                BiodataInDB(**item)
                for item in data.get("biodatas", [])
                if item.get("is_approved") or item.get("ocr_status") == "approved"
            ]
            return approved

    async def get_pending_validation(self) -> List[BiodataInDB]:
        """Get biodatas pending OCR validation."""
        with self._file_lock():
            data = self._read_data()
            pending = [
                BiodataInDB(**item)
                for item in data.get("biodatas", [])
                if item.get("ocr_status") in ["completed", "pending"]
                and not item.get("is_approved")
            ]
            return pending


# Singleton database instance
db = JSONDatabase()
