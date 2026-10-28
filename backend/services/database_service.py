"""
Database Service - JSON-based local database.
Thread-safe, with an in-memory cache and an id -> position index for O(1) lookups.
"""
import json
import os
import threading
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.config import settings
from backend.models import BiodataInDB, OCRStatus, utcnow

# Fields searched by the free-text `q` filter
_TEXT_SEARCH_FIELDS = (
    "name", "education", "occupation", "current_city", "state",
    "native_place", "religion", "caste", "original_filename",
)


class JSONDatabase:
    """
    JSON file-based database for biodata storage.

    The cached list is never reordered in place: `_index` maps ids to list
    positions, so any in-place sort would silently point lookups at the wrong record.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (settings.DB_DIR / "biodata.json")
        self._lock = threading.RLock()
        self._cache: Optional[Dict[str, Any]] = None
        self._index: Dict[str, int] = {}
        self._ensure_db_exists()

    def _ensure_db_exists(self):
        """Create database file if it doesn't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            self._write_data({"biodatas": [], "metadata": {"version": "1.0", "created_at": utcnow().isoformat()}})

    def _read_data(self) -> Dict[str, Any]:
        """Read all data from JSON file (cached after first read)."""
        if self._cache is not None:
            return self._cache
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                self._cache = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            self._cache = {"biodatas": [], "metadata": {"version": "1.0"}}
        self._rebuild_index()
        return self._cache

    def _rebuild_index(self):
        """Rebuild the id -> position mapping."""
        self._index = {
            item["id"]: i
            for i, item in enumerate(self._cache.get("biodatas", []))
            if item.get("id")
        }

    def _write_data(self, data: Dict[str, Any]):
        """Atomically write data to the JSON file and refresh the cache."""
        tmp_path = self.db_path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str, ensure_ascii=False)
        os.replace(tmp_path, self.db_path)
        self._cache = data
        self._rebuild_index()

    def _items(self) -> List[Dict[str, Any]]:
        return self._read_data().setdefault("biodatas", [])

    @staticmethod
    def _serialize(biodata: BiodataInDB) -> Dict[str, Any]:
        return biodata.model_dump(mode="json")

    async def create(self, biodata: BiodataInDB) -> BiodataInDB:
        """Create a new biodata record."""
        with self._lock:
            data = self._read_data()
            now = utcnow()
            biodata.created_at = now
            biodata.updated_at = now
            data.setdefault("biodatas", []).append(self._serialize(biodata))
            self._write_data(data)
            return biodata

    async def get_by_id(self, biodata_id: str) -> Optional[BiodataInDB]:
        """Get biodata by ID."""
        with self._lock:
            items = self._items()
            idx = self._index.get(biodata_id)
            if idx is None:
                return None
            return BiodataInDB(**items[idx])

    async def get_all(
        self,
        page: int = 1,
        page_size: int = 10,
        status_filter: Optional[OCRStatus] = None,
        query: Optional[str] = None,
    ) -> Tuple[List[BiodataInDB], int]:
        """
        Get biodatas with pagination, newest first.

        Args:
            page: Page number (1-indexed)
            page_size: Items per page
            status_filter: Optional OCR status filter
            query: Optional case-insensitive text filter over common fields

        Returns:
            Tuple of (list of biodatas, total matching count)
        """
        with self._lock:
            items = self._items()
            if status_filter:
                items = [b for b in items if b.get("ocr_status") == status_filter.value]
            if query:
                needle = query.lower().strip()
                items = [
                    b for b in items
                    if any(needle in str(b.get(f) or "").lower() for f in _TEXT_SEARCH_FIELDS)
                ]
            # sorted() returns a copy; never sort the cached list in place
            items = sorted(items, key=lambda x: str(x.get("created_at", "")), reverse=True)
            start = (page - 1) * page_size
            return [BiodataInDB(**item) for item in items[start:start + page_size]], len(items)

    async def list_all(self) -> List[BiodataInDB]:
        """Get every biodata record (unpaginated)."""
        with self._lock:
            return [BiodataInDB(**item) for item in self._items()]

    async def update(self, biodata_id: str, update_data: Dict[str, Any]) -> Optional[BiodataInDB]:
        """
        Update biodata fields by ID. Every key in `update_data` is applied,
        including explicit None values (which clear the field).
        """
        with self._lock:
            data = self._read_data()
            idx = self._index.get(biodata_id)
            if idx is None:
                return None
            item = dict(data["biodatas"][idx])
            item.update(update_data)
            item["updated_at"] = utcnow()
            # Validate before persisting so a bad value can't corrupt the record
            validated = BiodataInDB(**item)
            data["biodatas"][idx] = self._serialize(validated)
            self._write_data(data)
            return validated

    async def delete(self, biodata_id: str) -> bool:
        """Delete biodata by ID."""
        with self._lock:
            data = self._read_data()
            idx = self._index.get(biodata_id)
            if idx is None:
                return False
            del data["biodatas"][idx]
            self._write_data(data)
            return True

    async def get_approved_biodatas(self) -> List[BiodataInDB]:
        """Get all approved biodatas for matching."""
        with self._lock:
            return [
                BiodataInDB(**item)
                for item in self._items()
                if item.get("is_approved") or item.get("ocr_status") == OCRStatus.APPROVED.value
            ]

    async def get_pending_validation(self) -> List[BiodataInDB]:
        """Get biodatas awaiting review (including failed re-OCR attempts), oldest first."""
        reviewable = {OCRStatus.PENDING.value, OCRStatus.COMPLETED.value, OCRStatus.FAILED.value}
        with self._lock:
            items = [
                item for item in self._items()
                if item.get("ocr_status") in reviewable and not item.get("is_approved")
            ]
            items = sorted(items, key=lambda x: str(x.get("created_at", "")))
            return [BiodataInDB(**item) for item in items]

    async def recover_interrupted(self) -> int:
        """Mark records left in PROCESSING by a crash/restart as FAILED so they can be retried."""
        with self._lock:
            data = self._read_data()
            stuck = [b for b in data.get("biodatas", []) if b.get("ocr_status") == OCRStatus.PROCESSING.value]
            for item in stuck:
                item["ocr_status"] = OCRStatus.FAILED.value
                item["updated_at"] = utcnow().isoformat()
            if stuck:
                self._write_data(data)
            return len(stuck)

    async def status_counts(self) -> Dict[str, int]:
        """Count records by OCR status."""
        with self._lock:
            counts = Counter(item.get("ocr_status", "unknown") for item in self._items())
            return {"total": sum(counts.values()), **counts}


# Singleton database instance
db = JSONDatabase()
