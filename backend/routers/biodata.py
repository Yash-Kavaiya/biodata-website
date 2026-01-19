"""
Biodata Router - CRUD operations for biodata.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from backend.models import (
    BiodataResponse,
    BiodataListResponse,
    BiodataCreate,
    BiodataUpdate,
    BiodataInDB,
    OCRStatus,
)
from backend.services import db, storage_service, similarity_service

router = APIRouter(prefix="/api/biodata", tags=["biodata"])


@router.get("", response_model=BiodataListResponse)
async def list_biodatas(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: Optional[str] = Query(None, description="Filter by OCR status")
):
    """
    List all biodatas with pagination.

    Args:
        page: Page number (1-indexed)
        page_size: Items per page (max 100)
        status: Optional OCR status filter
    """
    status_filter = None
    if status:
        try:
            status_filter = OCRStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    biodatas, total = await db.get_all(
        page=page,
        page_size=page_size,
        status_filter=status_filter
    )

    return BiodataListResponse(
        total=total,
        items=biodatas,
        page=page,
        page_size=page_size
    )


@router.get("/pending")
async def get_pending_validation():
    """Get biodatas pending OCR validation."""
    pending = await db.get_pending_validation()
    return {
        "total": len(pending),
        "items": pending
    }


@router.get("/approved")
async def get_approved_biodatas():
    """Get all approved biodatas."""
    approved = await db.get_approved_biodatas()
    return {
        "total": len(approved),
        "items": approved
    }


@router.get("/{biodata_id}", response_model=BiodataResponse)
async def get_biodata(biodata_id: str):
    """Get a specific biodata by ID."""
    biodata = await db.get_by_id(biodata_id)
    if not biodata:
        raise HTTPException(status_code=404, detail="Biodata not found")
    return biodata


@router.post("", response_model=BiodataResponse)
async def create_biodata(biodata: BiodataCreate):
    """
    Create a new biodata manually (without file upload).
    """
    new_biodata = BiodataInDB(
        **biodata.model_dump(),
        ocr_status=OCRStatus.APPROVED,  # Manual entries are pre-approved
        is_approved=True,
    )
    saved = await db.create(new_biodata)

    # Index for similarity search
    await similarity_service.index_biodata(saved)

    return saved


@router.put("/{biodata_id}", response_model=BiodataResponse)
async def update_biodata(biodata_id: str, update: BiodataUpdate):
    """Update an existing biodata."""
    existing = await db.get_by_id(biodata_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Biodata not found")

    update_data = update.model_dump(exclude_unset=True)
    updated = await db.update(biodata_id, update_data)

    if updated:
        # Re-index for similarity search
        await similarity_service.index_biodata(updated)

    return updated


@router.delete("/{biodata_id}")
async def delete_biodata(biodata_id: str):
    """Delete a biodata and its associated file."""
    existing = await db.get_by_id(biodata_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Biodata not found")

    # Delete file if exists
    if existing.file_path:
        await storage_service.delete_file(existing.file_path)

    # Remove from similarity index
    await similarity_service.remove_from_index(biodata_id)

    # Delete from database
    deleted = await db.delete(biodata_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete biodata")

    return {"message": "Biodata deleted successfully", "id": biodata_id}


@router.get("/{biodata_id}/file")
async def get_biodata_file(biodata_id: str):
    """Download the original file for a biodata."""
    biodata = await db.get_by_id(biodata_id)
    if not biodata:
        raise HTTPException(status_code=404, detail="Biodata not found")

    if not biodata.file_path:
        raise HTTPException(status_code=404, detail="No file associated with this biodata")

    if not await storage_service.file_exists(biodata.file_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        biodata.file_path,
        filename=biodata.original_filename or "biodata_file",
        media_type="application/octet-stream"
    )


@router.get("/{biodata_id}/ocr-text")
async def get_ocr_text(biodata_id: str):
    """Get the raw OCR text for a biodata."""
    biodata = await db.get_by_id(biodata_id)
    if not biodata:
        raise HTTPException(status_code=404, detail="Biodata not found")

    return {
        "id": biodata_id,
        "raw_ocr_text": biodata.raw_ocr_text,
        "ocr_confidence": biodata.ocr_confidence,
        "ocr_status": biodata.ocr_status
    }
