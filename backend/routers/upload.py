"""
Upload Router - Handles file uploads (single and bulk) with optimized queue processing.
Supports 100+ concurrent uploads with proper rate limiting and failure isolation.
"""
import asyncio
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Query

from backend.models import (
    UploadResponse,
    BulkUploadResponse,
    BiodataInDB,
    OCRStatus,
)
from backend.services import storage_service, db, ocr_service, similarity_service, queue_service, graph_service
from backend.services.ocr_service import OCRService
from backend.services.queue_service import BatchJob, BatchStatus
from backend.config import settings

router = APIRouter(prefix="/api/upload", tags=["upload"])
logger = logging.getLogger(__name__)


@dataclass
class FileData:
    """Holds file content and metadata for processing."""
    content: bytes
    filename: str
    extension: str


# ==================== Helper Functions ====================

def validate_file_extension(filename: str) -> tuple:
    """
    Validate file extension.
    Returns: (is_valid, extension, error_message)
    """
    ext = "." + filename.split(".")[-1].lower() if "." in filename else ""
    if ext not in settings.ALLOWED_EXTENSIONS:
        return False, ext, f"Invalid file type. Allowed: {settings.ALLOWED_EXTENSIONS}"
    return True, ext, ""


def validate_file_size(content: bytes) -> tuple:
    """
    Validate file size.
    Returns: (is_valid, error_message)
    """
    if len(content) > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        return False, f"File too large. Max size: {settings.MAX_FILE_SIZE_MB}MB"
    return True, ""


async def process_file_atomic(
    file_path: str,
    filename: str,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Process a single file atomically:
    1. Run OCR (rate limited with retry)
    2. If success: save to DB, return result
    3. If fail: delete file, return error (NO DB record created)

    Returns dict with id, filename, status, message
    """
    try:
        # OCR call (rate limiting handled by queue_service.process_with_limit)
        extracted_data, confidence, raw_text, status = await queue_service.process_with_limit(
            ocr_service.process_file,
            file_path,
            model=model
        )

        if status == OCRStatus.FAILED:
            # Cleanup file - no DB record
            await storage_service.delete_file(file_path)
            return {
                "id": "",
                "filename": filename,
                "status": OCRStatus.FAILED.value,
                "message": f"OCR Failed: {raw_text[:100]}" if raw_text else "OCR Failed"
            }

        # Create DB record only on success
        biodata = BiodataInDB(
            file_path=file_path,
            original_filename=filename,
            ocr_status=status.value,
            ocr_confidence=confidence,
            raw_ocr_text=raw_text,
            **extracted_data
        )
        saved_biodata = await db.create(biodata)

        # Index for similarity search and sync to Neo4j graph
        if status == OCRStatus.COMPLETED:
            try:
                await similarity_service.index_biodata(saved_biodata)
            except Exception as e:
                logger.warning(f"Failed to index biodata {saved_biodata.id}: {e}")

            # Sync to Neo4j graph database
            try:
                await graph_service.add_biodata(saved_biodata)
            except Exception as e:
                logger.warning(f"Failed to sync biodata {saved_biodata.id} to Neo4j: {e}")

        return {
            "id": saved_biodata.id,
            "filename": filename,
            "status": status.value,
            "message": f"Processed with {confidence:.0%} confidence"
        }

    except Exception as e:
        # Emergency cleanup
        try:
            await storage_service.delete_file(file_path)
        except:
            pass
        logger.error(f"Error processing {filename}: {e}")
        return {
            "id": "",
            "filename": filename,
            "status": OCRStatus.FAILED.value,
            "message": str(e)[:200]
        }


async def process_single_upload(
    file: UploadFile,
    model: Optional[str] = None
) -> UploadResponse:
    """Process a single file upload with validation and OCR."""
    filename = file.filename or "unknown"

    # Validate extension
    is_valid, ext, error = validate_file_extension(filename)
    if not is_valid:
        return UploadResponse(
            id="",
            filename=filename,
            status=OCRStatus.FAILED,
            message=error
        )

    # Read and validate size
    content = await file.read()
    is_valid, error = validate_file_size(content)
    if not is_valid:
        return UploadResponse(
            id="",
            filename=filename,
            status=OCRStatus.FAILED,
            message=error
        )

    try:
        # Save file
        file_path = await storage_service.save_file_content(content, filename)

        # Process atomically
        result = await process_file_atomic(file_path, filename, model)

        return UploadResponse(
            id=result["id"],
            filename=result["filename"],
            status=OCRStatus(result["status"]),
            message=result["message"]
        )

    except Exception as e:
        return UploadResponse(
            id="",
            filename=filename,
            status=OCRStatus.FAILED,
            message=str(e)
        )


# ==================== API Endpoints ====================

@router.get("/models")
async def get_available_models():
    """Get list of available Gemini models for OCR."""
    return {
        "models": OCRService.get_available_models(),
        "default": settings.VERTEX_MODEL,
        "provider": settings.LLM_PROVIDER,
    }


@router.post("/single", response_model=UploadResponse)
async def upload_single_file(
    file: UploadFile = File(...),
    model: Optional[str] = Query(None, description="Gemini model to use for OCR")
):
    """Upload a single biodata PDF/image file."""
    result = await process_single_upload(file, model=model)
    if result.status == OCRStatus.FAILED and not result.id:
        raise HTTPException(status_code=400, detail=result.message)
    return result


@router.post("/bulk", response_model=BulkUploadResponse)
async def upload_bulk_files(
    files: List[UploadFile] = File(...),
    model: Optional[str] = Query(None, description="Gemini model to use for OCR")
):
    """
    Upload multiple biodata files (synchronous, up to 50 files).
    For larger batches, use /bulk/async endpoint.

    Features:
    - Rate limiting to avoid API quota errors
    - Automatic retry on transient failures
    - Failed files are NOT added to database
    """
    if len(files) > 50:
        raise HTTPException(
            status_code=400,
            detail="Maximum 50 files for sync upload. Use /bulk/async for larger batches."
        )

    # Process all files in parallel (rate limiting handled internally)
    tasks = [process_single_upload(file, model) for file in files]
    results = await asyncio.gather(*tasks)

    successful = sum(1 for r in results if r.status != OCRStatus.FAILED)
    failed = len(results) - successful

    return BulkUploadResponse(
        total=len(results),
        successful=successful,
        failed=failed,
        uploads=results
    )


@router.post("/bulk/async")
async def upload_bulk_async(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    model: Optional[str] = Query(None, description="Gemini model to use for OCR")
):
    """
    Upload large batches (100+ files) with async background processing.

    Features:
    - Handles 100-200 files efficiently
    - Rate limiting (50 RPM default)
    - Automatic retry with exponential backoff
    - Circuit breaker to prevent cascade failures
    - Chunked processing (10 files per chunk)
    - Progress tracking via /batch/{job_id}/status
    - Failed files are automatically cleaned up (not added to DB)

    Returns:
    - job_id: Use this to track progress via /batch/{job_id}/status
    """
    if len(files) > settings.MAX_BULK_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {settings.MAX_BULK_FILES} files per bulk upload."
        )

    # Step 1: Quickly validate and save all files
    file_data_list: List[tuple] = []  # (FileData, file_path)
    validation_errors: List[Dict[str, str]] = []

    for file in files:
        filename = file.filename or "unknown"

        # Validate extension
        is_valid, ext, error = validate_file_extension(filename)
        if not is_valid:
            validation_errors.append({"filename": filename, "error": error})
            continue

        # Read content
        content = await file.read()

        # Validate size
        is_valid, error = validate_file_size(content)
        if not is_valid:
            validation_errors.append({"filename": filename, "error": error})
            continue

        # Save file immediately (fast operation)
        try:
            file_path = await storage_service.save_file_content(content, filename)
            file_data_list.append((
                FileData(content=content, filename=filename, extension=ext),
                file_path
            ))
        except Exception as e:
            validation_errors.append({"filename": filename, "error": str(e)})

    # Create batch job
    job = await queue_service.create_batch_job(len(file_data_list) + len(validation_errors))

    # Add validation errors to job
    for err in validation_errors:
        await queue_service.update_batch_progress(
            job,
            success=False,
            error=err["error"],
            filename=err["filename"]
        )

    # Step 2: Schedule background OCR processing
    async def process_batch():
        """Process all files in controlled chunks."""
        chunk_size = settings.BATCH_CHUNK_SIZE

        for i in range(0, len(file_data_list), chunk_size):
            chunk = file_data_list[i:i + chunk_size]

            # Process chunk in parallel
            async def process_one(item: tuple):
                file_data, file_path = item
                try:
                    result = await process_file_atomic(file_path, file_data.filename, model)
                    success = result["status"] != OCRStatus.FAILED.value
                    await queue_service.update_batch_progress(
                        job,
                        success=success,
                        result=result if success else None,
                        error=result["message"] if not success else None,
                        filename=file_data.filename
                    )
                except Exception as e:
                    # Cleanup on crash
                    try:
                        await storage_service.delete_file(file_path)
                    except:
                        pass
                    await queue_service.update_batch_progress(
                        job,
                        success=False,
                        error=str(e),
                        filename=file_data.filename
                    )

            tasks = [process_one(item) for item in chunk]
            await asyncio.gather(*tasks, return_exceptions=True)

            # Small delay between chunks
            if i + chunk_size < len(file_data_list):
                await asyncio.sleep(0.2)

        logger.info(f"Batch {job.id} completed: {job.successful}/{job.total} successful")

    background_tasks.add_task(process_batch)

    return {
        "job_id": job.id,
        "total": len(files),
        "queued": len(file_data_list),
        "validation_errors": len(validation_errors),
        "errors": validation_errors[:10],  # First 10 errors
        "message": f"Processing {len(file_data_list)} files in background. Track progress at /batch/{job.id}/status"
    }


@router.get("/batch/{job_id}/status")
async def get_batch_status(job_id: str):
    """
    Get the status of a batch upload job.

    Returns:
    - Progress percentage
    - Success/failure counts
    - Recent errors (if any)
    - Overall status (processing/completed/partial/failed)
    """
    job = await queue_service.get_batch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")

    return job.to_dict()


@router.get("/batch/{job_id}/results")
async def get_batch_results(job_id: str):
    """
    Get the results of a completed batch job.
    Includes list of successfully processed biodata IDs.
    """
    job = await queue_service.get_batch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")

    return {
        **job.to_dict(),
        "results": job.results,  # Full results for completed items
    }


@router.post("/async/single")
async def upload_single_async(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    model: Optional[str] = Query(None, description="Gemini model to use for OCR")
):
    """
    Upload a single file for async processing.
    Returns immediately with a pending status.
    """
    filename = file.filename or "unknown"

    # Validate extension
    is_valid, ext, error = validate_file_extension(filename)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)

    # Read and validate size
    content = await file.read()
    is_valid, error = validate_file_size(content)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)

    # Save file
    file_path = await storage_service.save_file_content(content, filename)

    # Create batch job for single file
    job = await queue_service.create_batch_job(1)

    async def process_single():
        try:
            result = await process_file_atomic(file_path, filename, model)
            success = result["status"] != OCRStatus.FAILED.value
            await queue_service.update_batch_progress(
                job,
                success=success,
                result=result if success else None,
                error=result["message"] if not success else None,
                filename=filename
            )
        except Exception as e:
            try:
                await storage_service.delete_file(file_path)
            except:
                pass
            await queue_service.update_batch_progress(
                job,
                success=False,
                error=str(e),
                filename=filename
            )

    background_tasks.add_task(process_single)

    return {
        "job_id": job.id,
        "filename": filename,
        "status": "pending",
        "message": f"Processing in background. Track at /batch/{job.id}/status"
    }


@router.delete("/batch/{job_id}")
async def cancel_batch_job(job_id: str):
    """
    Cancel a batch job (cleanup tracking data).
    Note: Already-submitted OCR tasks cannot be cancelled.
    """
    job = await queue_service.get_batch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")

    # Mark as failed if still processing
    if job.status == BatchStatus.PROCESSING:
        job.status = BatchStatus.FAILED
        from datetime import datetime
        job.completed_at = datetime.utcnow()

    return {"message": "Batch job cancelled", "job_id": job_id}


@router.get("/queue/stats")
async def get_queue_stats():
    """
    Get current queue statistics.
    Useful for monitoring system load.
    """
    return {
        "circuit_breaker_state": queue_service.circuit_breaker.state,
        "circuit_breaker_failures": queue_service.circuit_breaker.failures,
        "rate_limit_tokens": queue_service.rate_limiter.tokens,
        "rate_limit_capacity": queue_service.rate_limiter.capacity,
        "config": {
            "concurrency": settings.QUEUE_CONCURRENCY,
            "requests_per_minute": settings.REQUESTS_PER_MINUTE,
            "batch_chunk_size": settings.BATCH_CHUNK_SIZE,
            "max_bulk_files": settings.MAX_BULK_FILES,
        }
    }
