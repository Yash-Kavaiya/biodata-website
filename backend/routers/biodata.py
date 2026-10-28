"""
Biodata Router - CRUD operations for biodata.
"""
import logging
import math
import mimetypes
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from backend.models import (
    BiodataCreate,
    BiodataInDB,
    BiodataListResponse,
    BiodataResponse,
    BiodataUpdate,
    OCRStatus,
)
from backend.services import db, graph_service, storage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/biodata", tags=["biodata"])


async def get_or_404(biodata_id: str) -> BiodataInDB:
    biodata = await db.get_by_id(biodata_id)
    if not biodata:
        raise HTTPException(status_code=404, detail="Biodata not found")
    return biodata


@router.get("", response_model=BiodataListResponse)
async def list_biodatas(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: Optional[OCRStatus] = Query(None, description="Filter by OCR status"),
    q: Optional[str] = Query(None, max_length=100, description="Text search over name, education, city, ..."),
):
    """List biodatas, newest first, with pagination and optional filters."""
    items, total = await db.get_all(page=page, page_size=page_size, status_filter=status, query=q)
    return BiodataListResponse(
        total=total,
        items=items,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
    )


@router.get("/stats")
async def get_biodata_stats():
    """Record counts by OCR status."""
    return await db.status_counts()


@router.get("/pending")
async def get_pending_validation():
    """Biodatas awaiting review."""
    pending = await db.get_pending_validation()
    return {"total": len(pending), "items": pending}


@router.get("/approved")
async def get_approved_biodatas():
    """All approved biodatas."""
    approved = await db.get_approved_biodatas()
    return {"total": len(approved), "items": approved}


@router.get("/{biodata_id}", response_model=BiodataResponse)
async def get_biodata(biodata_id: str):
    """Get a specific biodata by ID."""
    return await get_or_404(biodata_id)


@router.post("", response_model=BiodataResponse, status_code=201)
async def create_biodata(biodata: BiodataCreate):
    """Create a biodata manually (no file). Manual entries are pre-approved."""
    saved = await db.create(BiodataInDB(**biodata.model_dump(), ocr_status=OCRStatus.APPROVED, is_approved=True))
    await graph_service.sync(saved)
    return saved


@router.put("/{biodata_id}", response_model=BiodataResponse)
async def update_biodata(biodata_id: str, update: BiodataUpdate):
    """Update fields of a biodata. Fields sent as null are cleared."""
    await get_or_404(biodata_id)
    updated = await db.update(biodata_id, update.model_dump(exclude_unset=True))
    await graph_service.sync(updated)
    return updated


@router.delete("/{biodata_id}")
async def delete_biodata(biodata_id: str):
    """Delete a biodata and its associated file."""
    existing = await get_or_404(biodata_id)
    if existing.file_path:
        await storage_service.delete_file(existing.file_path)
    await db.delete(biodata_id)
    await graph_service.remove_biodata(biodata_id)
    return {"message": "Biodata deleted successfully", "id": biodata_id}


@router.get("/{biodata_id}/file")
async def get_biodata_file(biodata_id: str, download: bool = False):
    """Serve the original document (inline by default, `?download=true` to save)."""
    biodata = await get_or_404(biodata_id)
    if not biodata.file_path or not await storage_service.file_exists(biodata.file_path):
        raise HTTPException(status_code=404, detail="Original file not available")

    path = storage_service.resolve_path(biodata.file_path)
    filename = biodata.original_filename or path.name
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/{biodata_id}/ocr-text")
async def get_ocr_text(biodata_id: str):
    """Raw OCR model output for a biodata."""
    biodata = await get_or_404(biodata_id)
    return {
        "id": biodata_id,
        "raw_ocr_text": biodata.raw_ocr_text,
        "ocr_confidence": biodata.ocr_confidence,
        "ocr_status": biodata.ocr_status,
    }
