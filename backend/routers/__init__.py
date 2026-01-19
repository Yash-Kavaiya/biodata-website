"""Routers package."""
from .upload import router as upload_router
from .biodata import router as biodata_router
from .validation import router as validation_router
from .search import router as search_router

__all__ = [
    "upload_router",
    "biodata_router",
    "validation_router",
    "search_router",
]
