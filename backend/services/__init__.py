"""Services package."""
from .storage_service import storage_service, LocalStorageService, StorageInterface
from .database_service import db, JSONDatabase
from .ocr_service import ocr_service, OCRService
from .similarity_service import similarity_service, SimilarityService

__all__ = [
    "storage_service",
    "LocalStorageService",
    "StorageInterface",
    "db",
    "JSONDatabase",
    "ocr_service",
    "OCRService",
    "similarity_service",
    "SimilarityService",
]
