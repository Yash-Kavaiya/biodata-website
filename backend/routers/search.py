"""
Search Router - Match finding and similarity search.
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, UploadFile, File

from backend.models import (
    SearchPreferences,
    MatchResult,
    BiodataInDB,
    Gender,
    MaritalStatus,
    OCRStatus,
)
from backend.services import (
    db,
    storage_service,
    ocr_service,
    similarity_service,
    neo4j_service,
    graph_service,
)

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/graph")
async def get_graph_data(
    biodata_id: Optional[str] = None, limit: int = Query(50, ge=1, le=200)
):
    """Get graph data for visualization."""
    return await graph_service.get_graph_data(biodata_id, limit)


@router.post("/preferences", response_model=List[MatchResult])
async def search_by_preferences(
    preferences: SearchPreferences, limit: int = Query(10, ge=1, le=50)
):
    """
    Find matching biodatas based on preferences.

    Args:
        preferences: Search criteria
        limit: Maximum number of results
    """
    # Get approved biodatas for searching
    approved = await db.get_approved_biodatas()

    if not approved:
        return []

    # Find matches
    matches = await similarity_service.find_matches(
        preferences=preferences, biodatas=approved, limit=limit
    )

    return matches


@router.get("/simple")
async def simple_search(
    gender: Optional[str] = None,
    min_age: Optional[int] = Query(None, ge=18),
    max_age: Optional[int] = Query(None, le=100),
    religion: Optional[str] = None,
    caste: Optional[str] = None,
    education: Optional[str] = None,
    location: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
):
    """
    Simple search endpoint with query parameters.
    """
    gender_enum = None
    if gender:
        try:
            gender_enum = Gender(gender.lower())
        except ValueError:
            pass

    preferences = SearchPreferences(
        gender=gender_enum,
        min_age=min_age,
        max_age=max_age,
        religion=religion,
        caste=caste,
        education=education,
        location=location,
    )

    approved = await db.get_approved_biodatas()
    matches = await similarity_service.find_matches(
        preferences=preferences, biodatas=approved, limit=limit
    )

    return {"total": len(matches), "matches": matches}


@router.post("/by-biodata/{biodata_id}", response_model=List[MatchResult])
async def search_by_biodata(biodata_id: str, limit: int = Query(10, ge=1, le=50)):
    """
    Find matches similar to an existing biodata.
    Useful for finding compatible profiles.
    """
    source = await db.get_by_id(biodata_id)
    if not source:
        raise HTTPException(status_code=404, detail="Biodata not found")

    approved = await db.get_approved_biodatas()
    matches = await similarity_service.find_similar_profiles(
        source_biodata=source, biodatas=approved, limit=limit
    )

    return matches


@router.get("/graph/similar/{biodata_id}")
async def get_similar_graph(biodata_id: str, limit: int = Query(10, ge=1, le=20)):
    """
    Get graph-based similar biodatas.
    """
    similar = await graph_service.find_similar(biodata_id, limit)
    return {"similar": similar}


@router.post("/by-upload", response_model=List[MatchResult])
async def search_by_upload(
    file: UploadFile = File(...), limit: int = Query(10, ge=1, le=50)
):
    """
    Upload a biodata and find matching profiles.
    The uploaded file is processed with OCR and matches are found.
    """
    filename = file.filename or "search_upload"

    # Save and process file
    content = await file.read()
    file_path = await storage_service.save_file_content(content, filename)

    # Run OCR
    extracted_data, confidence, raw_text, status = await ocr_service.process_file(
        file_path
    )

    if status == OCRStatus.FAILED:
        # Clean up
        await storage_service.delete_file(file_path)
        raise HTTPException(status_code=400, detail=f"OCR failed: {raw_text}")

    # Create temporary biodata for searching
    temp_biodata = BiodataInDB(
        **extracted_data,
        file_path=file_path,
        original_filename=filename,
        ocr_status=status,
        ocr_confidence=confidence,
    )

    # Find matches
    approved = await db.get_approved_biodatas()
    matches = await similarity_service.find_similar_profiles(
        source_biodata=temp_biodata, biodatas=approved, limit=limit
    )

    # Clean up temporary file
    await storage_service.delete_file(file_path)

    return matches


@router.get("/stats")
async def get_search_stats():
    """Get statistics about available biodatas for matching."""
    from collections import Counter

    approved = await db.get_approved_biodatas()

    # Use Counter for O(1) amortized increments
    gender_counts: Counter = Counter()
    religion_counts: Counter = Counter()
    location_counts: Counter = Counter()
    min_age = float("inf")
    max_age = float("-inf")

    for biodata in approved:
        gender_counts[biodata.gender.value if biodata.gender else "unknown"] += 1
        religion_counts[biodata.religion or "unknown"] += 1
        location_counts[biodata.current_city or biodata.state or "unknown"] += 1
        if biodata.age:
            if biodata.age < min_age:
                min_age = biodata.age
            if biodata.age > max_age:
                max_age = biodata.age

    return {
        "total_approved": len(approved),
        "by_gender": dict(gender_counts),
        "by_religion": dict(religion_counts),
        "age_range": {
            "min": min_age if min_age != float("inf") else None,
            "max": max_age if max_age != float("-inf") else None,
        },
        "by_location": dict(location_counts),
    }
