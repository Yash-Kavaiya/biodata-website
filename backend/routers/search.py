"""
Search Router - match finding.
"""
import tempfile
from collections import Counter
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from backend.models import BiodataInDB, MatchResult, OCRStatus, SearchPreferences
from backend.routers.biodata import get_or_404
from backend.routers.upload import read_valid_upload
from backend.services import db, ocr_service, queue_service, similarity_service

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("/preferences", response_model=List[MatchResult])
async def search_by_preferences(preferences: SearchPreferences, limit: int = Query(10, ge=1, le=50)):
    """Find approved biodatas matching the given preferences."""
    if not similarity_service.has_criteria(preferences):
        raise HTTPException(status_code=400, detail="Provide at least one search criterion")
    approved = await db.get_approved_biodatas()
    return await similarity_service.find_matches(preferences=preferences, biodatas=approved, limit=limit)


@router.post("/by-biodata/{biodata_id}", response_model=List[MatchResult])
async def search_by_biodata(biodata_id: str, limit: int = Query(10, ge=1, le=50)):
    """Find compatible profiles for an existing biodata."""
    source = await get_or_404(biodata_id)
    approved = await db.get_approved_biodatas()
    return await similarity_service.find_similar_profiles(source_biodata=source, biodatas=approved, limit=limit)


@router.post("/by-upload", response_model=List[MatchResult])
async def search_by_upload(file: UploadFile = File(...), limit: int = Query(10, ge=1, le=50)):
    """
    OCR an uploaded biodata and find compatible profiles.
    The file is processed in a temporary location and never stored.
    """
    try:
        content, ext = await read_valid_upload(file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"search{ext}"
        path.write_bytes(content)
        try:
            result = await queue_service.process_with_limit(ocr_service.process_file, str(path))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"OCR failed: {str(e)[:200]}")

    source = BiodataInDB(**result.data, ocr_status=OCRStatus.COMPLETED, ocr_confidence=result.confidence)
    approved = await db.get_approved_biodatas()
    return await similarity_service.find_similar_profiles(source_biodata=source, biodatas=approved, limit=limit)


@router.get("/stats")
async def get_search_stats():
    """Summary of approved profiles available for matching."""
    approved = await db.get_approved_biodatas()
    ages = [b.age for b in approved if b.age]
    return {
        "total_approved": len(approved),
        "by_gender": dict(Counter(b.gender.value if b.gender else "unknown" for b in approved)),
        "by_religion": dict(Counter(b.religion or "unknown" for b in approved).most_common(20)),
        "by_location": dict(Counter(b.current_city or b.state or "unknown" for b in approved).most_common(20)),
        "age_range": {"min": min(ages, default=None), "max": max(ages, default=None)},
    }
