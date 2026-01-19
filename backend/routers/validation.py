"""
Validation Router - OCR validation operations.
"""
from fastapi import APIRouter, HTTPException

from backend.models import (
    BiodataResponse,
    BiodataUpdate,
    OCRValidationRequest,
    OCRStatus,
)
from backend.services import db, ocr_service, similarity_service

router = APIRouter(prefix="/api/validation", tags=["validation"])


@router.post("/approve/{biodata_id}", response_model=BiodataResponse)
async def approve_biodata(biodata_id: str):
    """
    Approve OCR results for a biodata.
    Marks the biodata as approved and ready for matching.
    """
    biodata = await db.get_by_id(biodata_id)
    if not biodata:
        raise HTTPException(status_code=404, detail="Biodata not found")

    updated = await db.update(biodata_id, {
        "ocr_status": OCRStatus.APPROVED.value,
        "is_approved": True
    })

    if updated:
        # Index for similarity search
        await similarity_service.index_biodata(updated)

    return updated


@router.post("/reject/{biodata_id}", response_model=BiodataResponse)
async def reject_biodata(biodata_id: str):
    """
    Reject OCR results for a biodata.
    The biodata will be removed from matching.
    """
    biodata = await db.get_by_id(biodata_id)
    if not biodata:
        raise HTTPException(status_code=404, detail="Biodata not found")

    updated = await db.update(biodata_id, {
        "ocr_status": OCRStatus.REJECTED.value,
        "is_approved": False
    })

    # Remove from similarity index
    await similarity_service.remove_from_index(biodata_id)

    return updated


@router.post("/edit/{biodata_id}", response_model=BiodataResponse)
async def edit_and_approve(biodata_id: str, update: BiodataUpdate):
    """
    Edit OCR results and approve the biodata.
    Allows correcting any extraction errors before approval.
    """
    biodata = await db.get_by_id(biodata_id)
    if not biodata:
        raise HTTPException(status_code=404, detail="Biodata not found")

    update_data = update.model_dump(exclude_unset=True)
    update_data["ocr_status"] = OCRStatus.APPROVED.value
    update_data["is_approved"] = True

    updated = await db.update(biodata_id, update_data)

    if updated:
        # Re-index with corrected data
        await similarity_service.index_biodata(updated)

    return updated


@router.post("/re-ocr/{biodata_id}", response_model=BiodataResponse)
async def rerun_ocr(biodata_id: str):
    """
    Re-run OCR processing on the original file.
    Useful if initial OCR failed or had poor results.
    """
    biodata = await db.get_by_id(biodata_id)
    if not biodata:
        raise HTTPException(status_code=404, detail="Biodata not found")

    if not biodata.file_path:
        raise HTTPException(
            status_code=400,
            detail="No file associated with this biodata"
        )

    # Mark as processing
    await db.update(biodata_id, {"ocr_status": OCRStatus.PROCESSING.value})

    # Re-run OCR
    extracted_data, confidence, raw_text, status = await ocr_service.reprocess_file(
        biodata.file_path
    )

    # Update with new results
    update_data = {
        **extracted_data,
        "ocr_status": status.value,
        "ocr_confidence": confidence,
        "raw_ocr_text": raw_text,
        "is_approved": False  # Needs re-approval after re-OCR
    }
    updated = await db.update(biodata_id, update_data)

    return updated


@router.post("/auto-approve-all")
async def auto_approve_all(min_confidence: float = 0.7):
    """
    Auto-approve all completed biodatas with confidence above threshold.

    Args:
        min_confidence: Minimum OCR confidence to auto-approve (0-1)
    """
    biodatas, _ = await db.get_all(page=1, page_size=1000)

    approved_count = 0
    for biodata in biodatas:
        if (
            biodata.ocr_status == OCRStatus.COMPLETED
            and not biodata.is_approved
            and biodata.ocr_confidence
            and biodata.ocr_confidence >= min_confidence
        ):
            await db.update(biodata.id, {
                "ocr_status": OCRStatus.APPROVED.value,
                "is_approved": True
            })
            await similarity_service.index_biodata(biodata)
            approved_count += 1

    return {
        "message": f"Auto-approved {approved_count} biodatas",
        "approved_count": approved_count,
        "min_confidence": min_confidence
    }


@router.post("/validate")
async def validate_action(request: OCRValidationRequest):
    """
    Perform validation action on a biodata.
    Supports: approve, reject, edit, re-ocr
    """
    action = request.action.lower()

    if action == "approve":
        return await approve_biodata(request.biodata_id)
    elif action == "reject":
        return await reject_biodata(request.biodata_id)
    elif action == "edit":
        if not request.updated_data:
            raise HTTPException(
                status_code=400,
                detail="updated_data required for edit action"
            )
        return await edit_and_approve(request.biodata_id, request.updated_data)
    elif action == "re-ocr":
        return await rerun_ocr(request.biodata_id)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action: {action}. Supported: approve, reject, edit, re-ocr"
        )
