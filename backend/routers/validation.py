"""
Validation Router - review workflow for OCR results.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.models import BiodataResponse, BiodataUpdate, OCRStatus
from backend.routers.biodata import get_or_404
from backend.services import db, graph_service, ocr_service, queue_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/validation", tags=["validation"])

APPROVED = {"ocr_status": OCRStatus.APPROVED.value, "is_approved": True}


@router.post("/approve/{biodata_id}", response_model=BiodataResponse)
async def approve_biodata(biodata_id: str):
    """Approve OCR results; the biodata becomes searchable."""
    await get_or_404(biodata_id)
    updated = await db.update(biodata_id, APPROVED)
    await graph_service.sync(updated)
    return updated


@router.post("/reject/{biodata_id}", response_model=BiodataResponse)
async def reject_biodata(biodata_id: str):
    """Reject OCR results; the biodata is excluded from matching."""
    await get_or_404(biodata_id)
    updated = await db.update(biodata_id, {"ocr_status": OCRStatus.REJECTED.value, "is_approved": False})
    await graph_service.sync(updated)
    return updated


@router.post("/edit/{biodata_id}", response_model=BiodataResponse)
async def edit_and_approve(biodata_id: str, update: BiodataUpdate):
    """Correct extracted fields and approve in one step. Fields sent as null are cleared."""
    await get_or_404(biodata_id)
    updated = await db.update(biodata_id, {**update.model_dump(exclude_unset=True), **APPROVED})
    await graph_service.sync(updated)
    return updated


@router.post("/re-ocr/{biodata_id}", response_model=BiodataResponse)
async def rerun_ocr(biodata_id: str, model: Optional[str] = Query(None, description="Model to use for OCR")):
    """Re-run OCR on the original file. The result needs approval again."""
    biodata = await get_or_404(biodata_id)
    if not biodata.file_path:
        raise HTTPException(status_code=400, detail="No file associated with this biodata")
    try:
        model = ocr_service.validate_model(model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await db.update(biodata_id, {"ocr_status": OCRStatus.PROCESSING.value, "is_approved": False})
    await graph_service.remove_biodata(biodata_id)
    try:
        result = await queue_service.process_with_limit(ocr_service.process_file, biodata.file_path, model=model)
    except Exception as e:
        logger.error(f"Re-OCR failed for {biodata_id}: {e}")
        await db.update(biodata_id, {"ocr_status": OCRStatus.FAILED.value})
        raise HTTPException(status_code=502, detail=f"OCR failed: {str(e)[:200]}")

    return await db.update(biodata_id, {
        **result.data,
        "ocr_status": OCRStatus.COMPLETED.value,
        "ocr_confidence": result.confidence,
        "raw_ocr_text": result.raw_text,
    })


@router.post("/auto-approve-all")
async def auto_approve_all(min_confidence: float = Query(0.35, ge=0, le=1)):
    """Approve every completed, unapproved biodata whose OCR confidence meets the threshold."""
    approved_count = 0
    for biodata in await db.list_all():
        if (
            biodata.ocr_status == OCRStatus.COMPLETED
            and not biodata.is_approved
            and (biodata.ocr_confidence or 0) >= min_confidence
        ):
            updated = await db.update(biodata.id, APPROVED)
            await graph_service.sync(updated)
            approved_count += 1

    return {
        "message": f"Auto-approved {approved_count} biodatas",
        "approved_count": approved_count,
        "min_confidence": min_confidence,
    }
