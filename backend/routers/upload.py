"""
Upload Router - Handles file uploads (single and bulk).
"""
import asyncio
from typing import List
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from backend.models import (
    UploadResponse,
    BulkUploadResponse,
    BiodataInDB,
    OCRStatus,
)
from backend.services import storage_service, db, ocr_service, similarity_service
from backend.config import settings

router = APIRouter(prefix="/api/upload", tags=["upload"])


async def process_single_upload(file: UploadFile) -> UploadResponse:
    """
    Process a single file upload with OCR.

    Args:
        file: Uploaded file

    Returns:
        UploadResponse with status
    """
    # Validate file extension
    filename = file.filename or "unknown"
    ext = "." + filename.split(".")[-1].lower() if "." in filename else ""

    if ext not in settings.ALLOWED_EXTENSIONS:
        return UploadResponse(
            id="",
            filename=filename,
            status=OCRStatus.FAILED,
            message=f"Invalid file type. Allowed: {settings.ALLOWED_EXTENSIONS}"
        )

    # Validate file size
    content = await file.read()
    await file.seek(0)  # Reset file pointer

    if len(content) > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        return UploadResponse(
            id="",
            filename=filename,
            status=OCRStatus.FAILED,
            message=f"File too large. Max size: {settings.MAX_FILE_SIZE_MB}MB"
        )

    try:
        # Save file to storage
        file_path = await storage_service.save_file_content(content, filename)

        # Create initial database record
        biodata = BiodataInDB(
            file_path=file_path,
            original_filename=filename,
            ocr_status=OCRStatus.PROCESSING,
        )
        saved_biodata = await db.create(biodata)

        # Run OCR processing
        extracted_data, confidence, raw_text, status = await ocr_service.process_file(
            file_path
        )

        # Update biodata with OCR results
        update_data = {
            **extracted_data,
            "ocr_status": status.value,
            "ocr_confidence": confidence,
            "raw_ocr_text": raw_text,
        }
        await db.update(saved_biodata.id, update_data)

        # Index for similarity search if successful
        if status == OCRStatus.COMPLETED:
            updated_biodata = await db.get_by_id(saved_biodata.id)
            if updated_biodata:
                await similarity_service.index_biodata(updated_biodata)

        return UploadResponse(
            id=saved_biodata.id,
            filename=filename,
            status=status,
            message=f"Processed with {confidence:.0%} confidence"
        )

    except Exception as e:
        return UploadResponse(
            id="",
            filename=filename,
            status=OCRStatus.FAILED,
            message=str(e)
        )


@router.post("/single", response_model=UploadResponse)
async def upload_single_file(file: UploadFile = File(...)):
    """
    Upload a single biodata PDF/image file.

    The file will be processed with OCR to extract biodata information.
    """
    result = await process_single_upload(file)
    if result.status == OCRStatus.FAILED and not result.id:
        raise HTTPException(status_code=400, detail=result.message)
    return result


@router.post("/bulk", response_model=BulkUploadResponse)
async def upload_bulk_files(files: List[UploadFile] = File(...)):
    """
    Upload multiple biodata files at once.

    Files are processed asynchronously in parallel.
    """
    if len(files) > 50:
        raise HTTPException(
            status_code=400,
            detail="Maximum 50 files allowed per bulk upload"
        )

    # Process files in parallel
    tasks = [process_single_upload(file) for file in files]
    results = await asyncio.gather(*tasks)

    successful = sum(1 for r in results if r.status != OCRStatus.FAILED)
    failed = len(results) - successful

    return BulkUploadResponse(
        total=len(results),
        successful=successful,
        failed=failed,
        uploads=results
    )


@router.post("/async/single")
async def upload_single_async(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    """
    Upload a single file for async processing.

    Returns immediately with a tracking ID. Use the biodata endpoint
    to check processing status.
    """
    filename = file.filename or "unknown"
    ext = "." + filename.split(".")[-1].lower() if "." in filename else ""

    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {settings.ALLOWED_EXTENSIONS}"
        )

    # Save file immediately
    content = await file.read()
    file_path = await storage_service.save_file_content(content, filename)

    # Create pending record
    biodata = BiodataInDB(
        file_path=file_path,
        original_filename=filename,
        ocr_status=OCRStatus.PENDING,
    )
    saved_biodata = await db.create(biodata)

    # Schedule background processing
    async def process_ocr():
        try:
            await db.update(saved_biodata.id, {"ocr_status": OCRStatus.PROCESSING.value})
            extracted_data, confidence, raw_text, status = await ocr_service.process_file(
                file_path
            )
            update_data = {
                **extracted_data,
                "ocr_status": status.value,
                "ocr_confidence": confidence,
                "raw_ocr_text": raw_text,
            }
            await db.update(saved_biodata.id, update_data)

            if status == OCRStatus.COMPLETED:
                updated = await db.get_by_id(saved_biodata.id)
                if updated:
                    await similarity_service.index_biodata(updated)
        except Exception as e:
            await db.update(saved_biodata.id, {
                "ocr_status": OCRStatus.FAILED.value,
                "raw_ocr_text": str(e)
            })

    background_tasks.add_task(asyncio.create_task, process_ocr())

    return {
        "id": saved_biodata.id,
        "filename": filename,
        "status": "pending",
        "message": "File uploaded. Processing in background."
    }


@router.post("/async/bulk")
async def upload_bulk_async(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...)
):
    """
    Upload multiple files for async processing.

    Returns immediately with tracking IDs.
    """
    if len(files) > 50:
        raise HTTPException(
            status_code=400,
            detail="Maximum 50 files allowed per bulk upload"
        )

    results = []

    for file in files:
        filename = file.filename or "unknown"
        ext = "." + filename.split(".")[-1].lower() if "." in filename else ""

        if ext not in settings.ALLOWED_EXTENSIONS:
            results.append({
                "id": "",
                "filename": filename,
                "status": "failed",
                "message": f"Invalid file type"
            })
            continue

        # Save file
        content = await file.read()
        file_path = await storage_service.save_file_content(content, filename)

        # Create pending record
        biodata = BiodataInDB(
            file_path=file_path,
            original_filename=filename,
            ocr_status=OCRStatus.PENDING,
        )
        saved_biodata = await db.create(biodata)

        results.append({
            "id": saved_biodata.id,
            "filename": filename,
            "status": "pending",
            "message": "Queued for processing"
        })

    # Schedule background processing for all pending files
    async def process_all():
        pending_ids = [r["id"] for r in results if r["status"] == "pending"]
        for biodata_id in pending_ids:
            try:
                biodata = await db.get_by_id(biodata_id)
                if biodata and biodata.file_path:
                    await db.update(biodata_id, {"ocr_status": OCRStatus.PROCESSING.value})
                    extracted_data, confidence, raw_text, status = await ocr_service.process_file(
                        biodata.file_path
                    )
                    update_data = {
                        **extracted_data,
                        "ocr_status": status.value,
                        "ocr_confidence": confidence,
                        "raw_ocr_text": raw_text,
                    }
                    await db.update(biodata_id, update_data)

                    if status == OCRStatus.COMPLETED:
                        updated = await db.get_by_id(biodata_id)
                        if updated:
                            await similarity_service.index_biodata(updated)
            except Exception as e:
                await db.update(biodata_id, {
                    "ocr_status": OCRStatus.FAILED.value,
                    "raw_ocr_text": str(e)
                })

    background_tasks.add_task(asyncio.create_task, process_all())

    return {
        "total": len(results),
        "queued": sum(1 for r in results if r["status"] == "pending"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "uploads": results
    }
